"""
Extraction: turn one cached email's stripped text into an ExtractedReceipt.

Uses Bedrock's Converse API (model-agnostic across Nova and Claude).
"""

import json
import os
from datetime import date, timedelta
from email.utils import parsedate_to_datetime

import boto3
from dotenv import load_dotenv

from extraction.prompts import build_prompt
from extraction.schema import ExtractedReceipt

load_dotenv()

REGION = os.environ.get("AWS_REGION")

# If the model's extracted order_date differs from the email's own send
# date by more than this many days, treat the model's value as suspect
# and override it with the email date instead. Found necessary after a
# real case: the model correctly extracted a Target order in two emails
# as 2026, then hallucinated 2020 for a third, functionally identical
# email — a 6-year error that would silently produce a wrong deadline.
# The email's own Date header is server-verified and far more trustworthy
# than a date the model read out of ambiguous receipt body text.
IMPLAUSIBLE_DATE_DRIFT_DAYS = 60


class ExtractionError(Exception):
    """Raised when the model's output can't be parsed/validated as an
    ExtractedReceipt."""


def extract_receipt(
    email_text: str,
    message_id: str,
    merchant_key: str,
    model_id: str,
    email_date_header: str | None = None,
) -> ExtractedReceipt:
    client = boto3.client("bedrock-runtime", region_name=REGION)

    prompt = build_prompt(email_text)

    response = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 800, "temperature": 0},
    )

    raw_text = response["output"]["message"]["content"][0]["text"]

    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ExtractionError(
            f"Model output wasn't valid JSON: {e}\nRaw output: {raw_text!r}"
        ) from e

    parsed["message_id"] = message_id
    parsed["merchant_key"] = merchant_key

    email_date: date | None = None
    if email_date_header:
        try:
            email_date = parsedate_to_datetime(email_date_header).date()
        except (TypeError, ValueError):
            pass

    if parsed.get("is_valid_receipt") and email_date:
        if not parsed.get("order_date"):
            # No date extracted at all — use the email's send date.
            parsed["order_date"] = email_date.isoformat()
        else:
            # A date WAS extracted — sanity-check it against the email's
            # own date rather than trusting it blindly.
            try:
                model_date = date.fromisoformat(parsed["order_date"])
                drift = abs((model_date - email_date).days)
                if drift > IMPLAUSIBLE_DATE_DRIFT_DAYS:
                    note = (
                        f"order_date overridden: model extracted "
                        f"{model_date.isoformat()}, which is {drift} days "
                        f"from the email's own send date "
                        f"({email_date.isoformat()}) — treated as an "
                        f"extraction error and replaced with the email date."
                    )
                    existing_notes = parsed.get("extraction_notes") or ""
                    parsed["extraction_notes"] = (existing_notes + " " + note).strip()
                    parsed["order_date"] = email_date.isoformat()
            except ValueError:
                parsed["order_date"] = email_date.isoformat()

    try:
        return ExtractedReceipt.model_validate(parsed)
    except Exception as e:
        raise ExtractionError(
            f"Model JSON didn't match the schema: {e}\nParsed: {parsed!r}"
        ) from e
