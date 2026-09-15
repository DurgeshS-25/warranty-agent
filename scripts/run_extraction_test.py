"""
Stage 2, step 3 (part 2): run real extraction against the full cache.

This is the first time a model actually touches the receipt data — every
step before this (cache building, schema, deadline logic) was
deterministic. Runs Nova Lite against every cached email, computes a
deadline for each, and reports a pass/fail count.

A failure here means one of: the prompt needs work, the email genuinely
has ambiguous data, or the schema doesn't fit a real case we haven't
seen yet. All three are useful things to learn from cheap, cached data —
which is the entire reason the cache exists instead of iterating live
against Gmail.

Run:
    python scripts/run_extraction_test.py
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from extraction import ExtractionError, compute_deadline, extract_receipt

load_dotenv()

CACHE_DIR = Path("cache")
EXTRACTION_MODEL_ID = os.environ.get("BEDROCK_EXTRACTION_MODEL_ID")


def main() -> None:
    if not EXTRACTION_MODEL_ID:
        print(
            "FAILED: BEDROCK_EXTRACTION_MODEL_ID is not set in .env. "
            "This should be the Nova Lite model ID from the Bedrock "
            "Model catalog."
        )
        return

    cache_files = sorted(CACHE_DIR.glob("*.json"))
    if not cache_files:
        print(f"No cached files found in {CACHE_DIR}/. Run "
              "build_receipt_cache.py first.")
        return

    print(f"Running extraction against {len(cache_files)} cached emails "
          f"using {EXTRACTION_MODEL_ID}\n")

    successes = 0
    failures = []

    for path in cache_files:
        record = json.loads(path.read_text())

        try:
            receipt = extract_receipt(
                email_text=record["stripped_text"],
                message_id=record["message_id"],
                merchant_key=record["merchant_key"],
                model_id=EXTRACTION_MODEL_ID,
                email_date_header=record["date"],
            )
        except ExtractionError as e:
            print(f"[FAIL] {path.name}: {e}\n")
            failures.append(path.name)
            continue

        deadline = compute_deadline(receipt, sender_email=record["from"])

        status = "VALID" if receipt.is_valid_receipt else "invalid (correctly flagged)"
        print(f"[{status}] {path.name}")
        print(f"  subject: {record['subject']}")
        if receipt.is_valid_receipt:
            print(f"  order_number: {receipt.order_number}")
            print(f"  order_date: {receipt.order_date}")
            print(f"  items: {[item.description[:50] for item in receipt.items]}")
            print(f"  total_amount: {receipt.total_amount}")
            print(f"  -> deadline: {deadline.return_deadline} "
                  f"(source: {deadline.source})")
        else:
            print(f"  invalid_reason: {receipt.invalid_reason}")
        print()

        successes += 1

    print("=" * 60)
    print(f"{successes}/{len(cache_files)} extracted without error")
    if failures:
        print(f"Failed to parse/validate: {failures}")


if __name__ == "__main__":
    main()
