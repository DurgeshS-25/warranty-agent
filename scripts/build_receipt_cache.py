"""
Stage 2, step 2: build the local receipt cache.

Pulls real email bodies (not just headers this time) for the 5 known
merchants, strips HTML down to plain text with BeautifulSoup, and saves
each as a JSON file under cache/. This is the ONE time this project
should call Gmail with a live, non-trivial query — every prompt
iteration after this reads from these cached files instead.

Why strip HTML before anything else: raw receipt HTML can run ~40k
tokens once you count every inline style, tracking pixel, and nested
table Gmail-friendly email templates use. The actual useful content
(merchant, item, price, order number) is usually under 1k tokens. Feeding
the model 40k tokens of table markup to extract 1k tokens of signal is
pure wasted spend, and Stage 1's cost rules exist specifically to prevent
this kind of thing.

Run:
    python scripts/build_receipt_cache.py
"""

import hashlib
import json
import os
import time
from pathlib import Path

from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

REQUEST_DELAY_SECONDS = 0.15
MAX_RETRIES = 5
MAX_PER_MERCHANT = 15  # plenty for prompt-tuning; this isn't production ingestion
CACHE_DIR = Path("cache")

TOKEN_PATH = os.environ.get("GMAIL_TOKEN_PATH", "./token.json")
CREDENTIALS_PATH = os.environ.get("GMAIL_CREDENTIALS_PATH", "./credentials.json")
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Merchant -> Gmail search query. Domain filter narrows to the sender;
# the keyword filter is restricted to the SUBJECT line specifically
# (subject:(...)), not the whole email body. An earlier version matched
# keywords anywhere in the email, which let marketing emails through —
# e.g. a promotional email saying "track your orders" in the footer, or
# dbrand's comedic marketing copy that happens to say "order" repeatedly
# as a joke. Real transactional subjects ("Your receipt from...", "Order
# confirmation #...") are much more distinctive than body text.
MERCHANT_QUERIES = {
    "apple": 'from:(email.apple.com OR orders.apple.com OR applepay.apple.com) '
             'subject:(receipt OR invoice)',
    "best_buy": 'from:emailinfo.bestbuy.com '
                'subject:(receipt OR invoice OR "order confirmation" OR "thank you for your order" OR order OR pickup)',
    "target": 'from:(oe.target.com OR oe1.target.com) '
              'subject:(order OR receipt OR pickup)',
    "new_balance": 'from:(receipts.newbalance.com OR nbstores.newbalance.com) '
                   'subject:(order OR receipt)',
    "dbrand": 'from:dbrand.com '
              'subject:(receipt OR invoice OR "order confirmation" OR shipped)',
}


def get_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def with_retry(fn, *args, **kwargs):
    from googleapiclient.errors import HttpError

    for attempt in range(MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except HttpError as e:
            is_rate_limit = e.resp.status == 403 and "rateLimitExceeded" in str(e)
            if is_rate_limit and attempt < MAX_RETRIES - 1:
                backoff = (2 ** attempt) * 1.0
                print(f"    (rate limited, waiting {backoff:.0f}s...)")
                time.sleep(backoff)
                continue
            raise


def extract_html_body(payload: dict) -> str:
    """Walk the (possibly nested multipart) message payload and pull out
    the HTML body if present, else fall back to plain text."""
    import base64

    def find_part(parts, mime_type):
        for part in parts:
            if part.get("mimeType") == mime_type:
                return part
            if "parts" in part:
                found = find_part(part["parts"], mime_type)
                if found:
                    return found
        return None

    parts = payload.get("parts", [payload])
    part = find_part(parts, "text/html") or find_part(parts, "text/plain")
    if not part:
        return ""

    data = part.get("body", {}).get("data", "")
    if not data:
        return ""
    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")


def strip_html(raw_html: str) -> str:
    """The actual cost-saving step: collapse a receipt email from
    potentially tens of thousands of tokens of table/style markup down
    to the readable text a model would actually need."""
    soup = BeautifulSoup(raw_html, "lxml")

    # Remove elements that are pure noise for extraction purposes —
    # tracking pixels, embedded styles/scripts contribute zero signal.
    for tag in soup(["script", "style", "img"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    # Collapse the blank-line explosion that comes from stripping nested
    # table cells — makes the cached file actually readable when you
    # open it to sanity-check, not just model-input-shaped.
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def main() -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    service = get_service()

    total_cached = 0

    for merchant_key, query in MERCHANT_QUERIES.items():
        print(f"\n--- {merchant_key} ---")
        print(f"Query: {query}")

        results = with_retry(
            service.users().messages().list(
                userId="me", q=query, maxResults=MAX_PER_MERCHANT
            ).execute
        )
        messages = results.get("messages", [])
        print(f"Found {len(messages)} messages (capped at {MAX_PER_MERCHANT})")

        for msg_ref in messages:
            msg = with_retry(
                service.users().messages().get(
                    userId="me", id=msg_ref["id"], format="full"
                ).execute
            )
            time.sleep(REQUEST_DELAY_SECONDS)

            headers = {
                h["name"]: h["value"] for h in msg["payload"]["headers"]
            }
            raw_html = extract_html_body(msg["payload"])
            stripped_text = strip_html(raw_html)

            record = {
                "message_id": msg["id"],
                "merchant_key": merchant_key,
                "from": headers.get("From", ""),
                "subject": headers.get("Subject", ""),
                "date": headers.get("Date", ""),
                "stripped_text": stripped_text,
                "stripped_char_count": len(stripped_text),
                "raw_char_count": len(raw_html),
            }

            # Filename by content hash, not just message ID, so re-running
            # this script is naturally idempotent — same email, same file.
            file_hash = hashlib.sha256(msg["id"].encode()).hexdigest()[:12]
            out_path = CACHE_DIR / f"{merchant_key}_{file_hash}.json"
            out_path.write_text(json.dumps(record, indent=2))

            reduction = (
                100 * (1 - len(stripped_text) / max(len(raw_html), 1))
            )
            print(
                f"  cached {out_path.name} "
                f"({len(raw_html)} chars -> {len(stripped_text)} chars, "
                f"{reduction:.0f}% smaller)"
            )
            total_cached += 1

    print(f"\nDone. {total_cached} receipts cached under {CACHE_DIR}/")
    print("Every prompt-tuning run from here on should read from this "
          "folder, not call Gmail again.")


if __name__ == "__main__":
    main()
