"""
State store (DynamoDB).

Two item types share one table, distinguished by the partition key prefix:

  EMAIL#<gmail_message_id>   -> "I have handled this email" (idempotency)
  ORDER#<merchant>#<order#>  -> one merged record per order, even when an
                                order spans several emails

Idempotency strategy: at-least-once processing + idempotent writes.
The order is written first, then the email is marked done. If the process
crashes between the two, the email is simply reprocessed next run, and the
order upsert merges to the same result instead of duplicating anything.
"""

import os
from datetime import datetime, timezone
from decimal import Decimal
import re

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

REGION = os.environ.get("AWS_REGION")
TABLE_NAME = os.environ.get("DYNAMODB_TABLE_NAME", "warranty-agent-state")

# Stop retrying an email whose extraction keeps failing, so one bad email
# can't cost model calls on every scheduled run forever.
MAX_FAILURE_ATTEMPTS = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_table_if_missing() -> None:
    client = boto3.client("dynamodb", region_name=REGION)
    try:
        client.describe_table(TableName=TABLE_NAME)
        print(f"Table {TABLE_NAME} already exists.")
        return
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise

    print(f"Creating table {TABLE_NAME} (on-demand billing)...")
    client.create_table(
        TableName=TABLE_NAME,
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        # On-demand: pay per request, $0 when idle. Provisioned capacity
        # would bill hourly even with no traffic.
        BillingMode="PAY_PER_REQUEST",
    )
    client.get_waiter("table_exists").wait(TableName=TABLE_NAME)
    print("Table is ready.")


def _earliest(a: str | None, b: str | None) -> str | None:
    # ISO dates (YYYY-MM-DD) sort correctly as plain strings.
    values = [v for v in (a, b) if v]
    return min(values) if values else None


def _larger(a, b):
    values = [v for v in (a, b) if v is not None]
    return max(values) if values else None


class StateStore:
    def __init__(self) -> None:
        self.table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)

    # ---- idempotency ----------------------------------------------------

    def is_email_done(self, message_id: str) -> bool:
        item = self.table.get_item(
            Key={"pk": f"EMAIL#{message_id}"}, ConsistentRead=True
        ).get("Item")
        if not item:
            return False
        if item["outcome"] == "extraction_error":
            return int(item.get("attempts", 0)) >= MAX_FAILURE_ATTEMPTS
        return True

    def mark_email_done(self, message_id: str, outcome: str, order_pk: str | None = None) -> None:
        self.table.put_item(
            Item={
                "pk": f"EMAIL#{message_id}",
                "record_type": "email",
                "outcome": outcome,  # valid_receipt | not_a_receipt
                "order_pk": order_pk,
                "processed_at": _now(),
            }
        )

    def record_failure(self, message_id: str, error: str) -> None:
        self.table.update_item(
            Key={"pk": f"EMAIL#{message_id}"},
            UpdateExpression=(
                "SET #o = :o, #rt = :rt, #e = :e, #t = :t ADD #a :one"
            ),
            ExpressionAttributeNames={
                "#o": "outcome", "#rt": "record_type", "#e": "last_error",
                "#t": "last_attempt_at", "#a": "attempts",
            },
            ExpressionAttributeValues={
                ":o": "extraction_error", ":rt": "email",
                ":e": error[:300], ":t": _now(), ":one": 1,
            },
        )

    # ---- orders ---------------------------------------------------------

    @staticmethod
    def _normalize_order_number(raw: str | None) -> str | None:
        """Some merchants write one order in different formats across emails,
        e.g. 'U15262120' and '1026907 / U15262120-1'. Keep the part after a
        slash and drop a short '-N' suffix (long ids like BBY01-806814680481
        are left alone)."""
        if not raw:
            return None
        value = raw.split("/")[-1].strip().upper()
        return re.sub(r"-\d{1,2}$", "", value)

    @staticmethod
    def _order_pk(receipt) -> str:
        ident = StateStore._normalize_order_number(receipt.order_number) or f"EMAIL-{receipt.message_id}"
        return f"ORDER#{receipt.merchant_key}#{ident}"

    def upsert_order(self, receipt, deadline) -> str:
        """Create the order, or merge this email into the existing one.
        Merge rules are conservative: earliest order date, earliest
        deadline (so we never alert late), union of items."""
        order_pk = self._order_pk(receipt)
        now = _now()
        existing = self.table.get_item(Key={"pk": order_pk}, ConsistentRead=True).get("Item")

        new_order_date = receipt.order_date.isoformat() if receipt.order_date else None
        new_deadline = deadline.return_deadline.isoformat() if deadline.return_deadline else None
        new_items = [i.description for i in receipt.items]
        # DynamoDB rejects Python floats; money must be stored as Decimal.
        new_total = Decimal(str(receipt.total_amount)) if receipt.total_amount is not None else None

        if existing is None:
            item = {
                "pk": order_pk,
                "record_type": "order",
                "merchant": receipt.merchant_key,
                "order_number": receipt.order_number,
                "order_date": new_order_date,
                "return_deadline": new_deadline,
                "deadline_source": deadline.source,
                "deadline_detail": deadline.source_detail,
                "items": new_items,
                "total_amount": new_total,
                "email_ids": [receipt.message_id],
                "alerted": False,
                "first_seen": now,
                "updated_at": now,
            }
        else:
            item = dict(existing)  # preserves 'alerted' and 'first_seen'
            item["order_date"] = _earliest(existing.get("order_date"), new_order_date)
            if new_deadline and (
                not existing.get("return_deadline") or new_deadline < existing["return_deadline"]
            ):
                item["return_deadline"] = new_deadline
                item["deadline_source"] = deadline.source
                item["deadline_detail"] = deadline.source_detail
            item["items"] = existing["items"] + [d for d in new_items if d not in existing["items"]]
            item["total_amount"] = _larger(existing.get("total_amount"), new_total)
            if receipt.message_id not in existing["email_ids"]:
                item["email_ids"] = existing["email_ids"] + [receipt.message_id]
            item["updated_at"] = now

        self.table.put_item(Item=item)
        return order_pk

    def list_orders(self) -> list[dict]:
        # A Scan reads the whole table. Fine for ~100 items; at real scale
        # you would use a secondary index on return_deadline instead.
        items: list[dict] = []
        kwargs = {"FilterExpression": Attr("record_type").eq("order")}
        while True:
            resp = self.table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return items
