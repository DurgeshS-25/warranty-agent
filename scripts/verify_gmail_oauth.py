"""
Stage 1 verification script #2.

Purpose: prove the Google OAuth consent flow works end-to-end with the
gmail.readonly scope only, before any extraction logic exists. This script
lists the subjects of your 5 most recent emails and does NOTHING else —
no reading of bodies, no writes, no sends. That's deliberate: the smallest
possible proof that read-only access works.

First run opens a browser for you to approve consent (you, as the sole
Testing-mode test user). It then saves a token.json so you don't have to
re-approve every run. Note: in Testing mode, Google expires that refresh
token after 7 days of the app being unpublished — expect to redo this
consent step periodically until/unless you move the app out of Testing.

Run:
    pip install -r requirements.txt
    # Place your OAuth client file (downloaded from Google Cloud Console)
    # at ./credentials.json, or point GMAIL_CREDENTIALS_PATH at it in .env
    python scripts/verify_gmail_oauth.py
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Read-only. Do not widen this scope — the whole point of this project's
# OAuth setup is that it can never modify or send mail.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

CREDENTIALS_PATH = os.environ.get("GMAIL_CREDENTIALS_PATH", "./credentials.json")
TOKEN_PATH = os.environ.get("GMAIL_TOKEN_PATH", "./token.json")


def fail(message: str) -> None:
    print(f"FAILED: {message}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        fail("Dependencies missing. Run: pip install -r requirements.txt")
        return

    if not os.path.exists(CREDENTIALS_PATH):
        fail(
            f"No OAuth client file at {CREDENTIALS_PATH}. Download it from "
            "Google Cloud Console > APIs & Services > Credentials > your "
            "Desktop app client > Download JSON, and save it there."
        )
        return

    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                # Testing-mode refresh tokens expire after 7 days — this is
                # the expected failure mode, not a bug. Just redo consent.
                creds = None

        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_PATH, SCOPES
            )
            print("Opening browser for consent (gmail.readonly only)...")
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as token_file:
            token_file.write(creds.to_json())

    service = build("gmail", "v1", credentials=creds)

    print("Fetching 5 most recent message subjects (read-only)...")
    results = (
        service.users()
        .messages()
        .list(userId="me", maxResults=5)
        .execute()
    )
    messages = results.get("messages", [])

    if not messages:
        print("No messages found (mailbox may be empty). Auth still worked.")
        return

    for msg_ref in messages:
        msg = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=msg_ref["id"],
                format="metadata",
                metadataHeaders=["Subject", "From"],
            )
            .execute()
        )
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        print(f"  - {headers.get('From', '?')}: {headers.get('Subject', '(no subject)')}")

    print("SUCCESS: Gmail read-only OAuth is working.")


if __name__ == "__main__":
    main()
