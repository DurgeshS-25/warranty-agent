"""
Agent tools. Each returns a SHORT status string: the orchestrating model
never sees email bodies, only outcomes.

Email source is the local cache for now. Swapping in live Gmail later only
changes _load_cache(); the tools and agent stay the same.
"""

import json
import os
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv
from strands import tool

from extraction import ExtractionError, compute_deadline, extract_receipt
from state import StateStore

load_dotenv()

CACHE_DIR = Path("cache")
EXTRACTION_MODEL_ID = os.environ.get("BEDROCK_EXTRACTION_MODEL_ID")
MAX_EMAILS_PER_RUN = 10

_store: StateStore | None = None


def _get_store() -> StateStore:
    global _store
    if _store is None:
        _store = StateStore()
    return _store


def _load_cache() -> dict[str, dict]:
    records = {}
    for path in sorted(CACHE_DIR.glob("*.json")):
        record = json.loads(path.read_text())
        records[record["message_id"]] = record
    return records


def _today() -> date:
    # AGENT_AS_OF lets us replay "what would the agent say on date X"
    # against cached data, without waiting for real deadlines to approach.
    override = os.environ.get("AGENT_AS_OF")
    return date.fromisoformat(override) if override else date.today()


@tool
def list_new_emails(limit: int = MAX_EMAILS_PER_RUN) -> str:
    """List receipt-candidate emails that have not been processed yet.

    Args:
        limit: Maximum number of emails to return (hard-capped at 10).
    """
    limit = max(1, min(limit, MAX_EMAILS_PER_RUN))
    store = _get_store()
    new = [r for r in _load_cache().values() if not store.is_email_done(r["message_id"])]
    if not new:
        return "NO_NEW_EMAILS"
    shown = new[:limit]
    lines = [f"{r['message_id']} | {r['merchant_key']} | {r['subject'][:70]}" for r in shown]
    return f"{len(new)} unprocessed in total; showing {len(shown)}:\n" + "\n".join(lines)


@tool
def process_email(message_id: str) -> str:
    """Extract one email, compute its return deadline, and save it.

    Args:
        message_id: The message_id exactly as returned by list_new_emails.
    """
    if not EXTRACTION_MODEL_ID:
        return "ERROR: BEDROCK_EXTRACTION_MODEL_ID is not set"
    record = _load_cache().get(message_id)
    if record is None:
        return f"ERROR: unknown message_id {message_id}"

    store = _get_store()
    if store.is_email_done(message_id):
        return "SKIPPED: already processed"

    try:
        receipt = extract_receipt(
            email_text=record["stripped_text"],
            message_id=message_id,
            merchant_key=record["merchant_key"],
            model_id=EXTRACTION_MODEL_ID,
            email_date_header=record["date"],
        )
    except ExtractionError as e:
        store.record_failure(message_id, str(e))
        return "ERROR: extraction failed (recorded; retried on later runs, max 3 attempts)"

    if not receipt.is_valid_receipt:
        store.mark_email_done(message_id, "not_a_receipt")
        return f"NOT_A_RECEIPT: {(receipt.invalid_reason or '')[:100]}"

    deadline = compute_deadline(receipt, sender_email=record["from"])
    order_pk = store.upsert_order(receipt, deadline)
    store.mark_email_done(message_id, "valid_receipt", order_pk=order_pk)
    return f"SAVED: {order_pk} | deadline={deadline.return_deadline} | source={deadline.source}"


@tool
def list_expiring_orders(within_days: int = 7) -> str:
    """List orders whose return deadline falls within the next N days, including today.

    Args:
        within_days: Look-ahead window in days (1 to 60).
    """
    within_days = max(1, min(within_days, 60))
    today = _today()
    end = today + timedelta(days=within_days)

    hits = [
        o for o in _get_store().list_orders()
        if o.get("return_deadline")
        and today.isoformat() <= o["return_deadline"] <= end.isoformat()
    ]
    if not hits:
        return f"NONE: no return deadlines between {today} and {end}"

    hits.sort(key=lambda o: o["return_deadline"])
    return "\n".join(
        f"{o['merchant']} | order {o['order_number']} | deadline {o['return_deadline']} "
        f"(source: {o['deadline_source']}) | items: {', '.join(i for i in o['items'] if 'fee' not in i.lower())[:160]}"
        for o in hits
    )
