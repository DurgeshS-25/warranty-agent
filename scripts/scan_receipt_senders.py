"""
Stage 2, step 1: survey your inbox for likely receipt emails and group
them by sender, so the policy-table retailer list is based on who
actually emails you receipts — not a guess.

This is deliberately cheap: metadata only (From, Subject, Date), no
message bodies fetched. It exists to answer one question: "which ~10-15
retailers should get a hardcoded return-policy entry?"

Run:
    python scripts/scan_receipt_senders.py
"""

import os
import re
import time
from collections import defaultdict

from dotenv import load_dotenv

load_dotenv()

# Small pause between requests to stay under Gmail's per-second burst
# limit. This alone usually prevents the 403 rateLimitExceeded error;
# the retry logic below is a second layer of protection if it still fires.
REQUEST_DELAY_SECONDS = 0.15
MAX_RETRIES = 5

# Broad on purpose — catches most e-commerce transactional email without
# requiring exact wording. False positives (e.g. a newsletter that
# happens to say "your order") are fine; we're eyeballing the output,
# not trusting it blindly.
SEARCH_QUERY = (
    '(receipt OR "order confirmation" OR "your order" OR "order number" '
    'OR invoice OR "has shipped" OR delivered) newer_than:365d'
)

MAX_MESSAGES = 500  # one page's worth; enough to see real patterns

TOKEN_PATH = os.environ.get("GMAIL_TOKEN_PATH", "./token.json")
CREDENTIALS_PATH = os.environ.get("GMAIL_CREDENTIALS_PATH", "./credentials.json")
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


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


def extract_domain(from_header: str) -> str:
    """Pull a normalized sender domain out of a From header for grouping."""
    match = re.search(r"@([\w.-]+)", from_header)
    return match.group(1).lower() if match else from_header.lower()


def get_message_headers_with_retry(service, message_id: str) -> dict:
    """Fetch From/Subject for one message, retrying with backoff on
    Gmail's rate-limit error (HTTP 403, reason rateLimitExceeded)."""
    from googleapiclient.errors import HttpError

    for attempt in range(MAX_RETRIES):
        try:
            msg = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=message_id,
                    format="metadata",
                    metadataHeaders=["From", "Subject"],
                )
                .execute()
            )
            return {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        except HttpError as e:
            is_rate_limit = e.resp.status == 403 and "rateLimitExceeded" in str(e)
            if is_rate_limit and attempt < MAX_RETRIES - 1:
                backoff = (2 ** attempt) * 1.0  # 1s, 2s, 4s, 8s...
                print(f"    (rate limited, waiting {backoff:.0f}s...)")
                time.sleep(backoff)
                continue
            raise


def main() -> None:
    service = get_service()

    print(f"Searching: {SEARCH_QUERY}\n")
    results = (
        service.users()
        .messages()
        .list(userId="me", q=SEARCH_QUERY, maxResults=MAX_MESSAGES)
        .execute()
    )
    messages = results.get("messages", [])
    print(f"Found {len(messages)} candidate messages. Fetching headers...\n")

    by_domain = defaultdict(list)

    for i, msg_ref in enumerate(messages):
        headers = get_message_headers_with_retry(service, msg_ref["id"])
        time.sleep(REQUEST_DELAY_SECONDS)
        from_header = headers.get("From", "unknown")
        subject = headers.get("Subject", "(no subject)")
        domain = extract_domain(from_header)
        by_domain[domain].append(subject)

        if (i + 1) % 50 == 0:
            print(f"  ...{i + 1}/{len(messages)} processed")

    print("\n" + "=" * 60)
    print("SENDER DOMAINS BY FREQUENCY (candidates for the policy table)")
    print("=" * 60)

    ranked = sorted(by_domain.items(), key=lambda kv: len(kv[1]), reverse=True)

    for domain, subjects in ranked:
        print(f"\n{domain}  ({len(subjects)} emails)")
        for subject in subjects[:3]:
            print(f"    - {subject}")
        if len(subjects) > 3:
            print(f"    ... and {len(subjects) - 3} more")


if __name__ == "__main__":
    main()