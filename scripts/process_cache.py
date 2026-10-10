"""
Stage 3.1: process the cached receipts WITH memory.

First run: extracts every email, saves orders, marks emails done.
Second run: every email is already marked, so it skips all of them and
makes zero Bedrock calls. That second run is the idempotency proof.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from extraction import ExtractionError, compute_deadline, extract_receipt
from state import StateStore

load_dotenv()

CACHE_DIR = Path("cache")
MODEL_ID = os.environ.get("BEDROCK_EXTRACTION_MODEL_ID")


def main() -> None:
    if not MODEL_ID:
        print("FAILED: BEDROCK_EXTRACTION_MODEL_ID is not set in .env")
        return

    store = StateStore()
    stats = {"skipped_already_done": 0, "not_a_receipt": 0, "saved_to_order": 0, "failed": 0}
    bedrock_calls = 0

    for path in sorted(CACHE_DIR.glob("*.json")):
        record = json.loads(path.read_text())
        message_id = record["message_id"]

        if store.is_email_done(message_id):
            stats["skipped_already_done"] += 1
            continue

        bedrock_calls += 1
        try:
            receipt = extract_receipt(
                email_text=record["stripped_text"],
                message_id=message_id,
                merchant_key=record["merchant_key"],
                model_id=MODEL_ID,
                email_date_header=record["date"],
            )
        except ExtractionError as e:
            store.record_failure(message_id, str(e))
            stats["failed"] += 1
            continue

        if not receipt.is_valid_receipt:
            store.mark_email_done(message_id, "not_a_receipt")
            stats["not_a_receipt"] += 1
            continue

        deadline = compute_deadline(receipt, sender_email=record["from"])
        order_pk = store.upsert_order(receipt, deadline)
        store.mark_email_done(message_id, "valid_receipt", order_pk=order_pk)
        stats["saved_to_order"] += 1

    print("\n=== Run summary ===")
    print(f"Bedrock calls made: {bedrock_calls}")
    for key, value in stats.items():
        print(f"  {key}: {value}")

    orders = store.list_orders()
    print(f"\n=== Orders in DynamoDB: {len(orders)} ===")
    for o in sorted(orders, key=lambda o: o.get("return_deadline") or "9999"):
        print(
            f"  {o['merchant']:<12} {str(o['order_number'])[:24]:<24} "
            f"deadline={o.get('return_deadline')} emails={len(o['email_ids'])} "
            f"items={len(o['items'])}"
        )


if __name__ == "__main__":
    main()
