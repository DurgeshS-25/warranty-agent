"""
Stage 1 verification script #1.

Purpose: prove that (a) your IAM user has bedrock:InvokeModel permission,
(b) you've enabled access to a specific model in the Bedrock console, and
(c) your credentials are wired up correctly — before any agent code exists.

This does NOT use the Strands SDK. It's a raw boto3 call on purpose: if
something breaks, you want to know whether the problem is "my AWS setup"
or "my SDK usage," and this script only tests the former.

Run:
    pip install -r requirements.txt
    cp .env.example .env   # then fill in AWS_REGION and BEDROCK_MODEL_ID
    python scripts/verify_bedrock.py
"""

import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()

REGION = os.environ.get("AWS_REGION")
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID")


def fail(message: str) -> None:
    print(f"FAILED: {message}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if not REGION:
        fail("AWS_REGION is not set. Add it to your .env file.")
    if not MODEL_ID:
        fail(
            "BEDROCK_MODEL_ID is not set. Go to the Bedrock console > "
            "Model access, copy the exact model ID string, and put it in .env. "
            "Do not guess this value."
        )

    try:
        import boto3
        from botocore.exceptions import ClientError, NoCredentialsError
    except ImportError:
        fail("boto3 not installed. Run: pip install -r requirements.txt")
        return

    try:
        client = boto3.client("bedrock-runtime", region_name=REGION)
    except NoCredentialsError:
        fail(
            "No AWS credentials found. Run `aws configure` with the IAM "
            "user's access key, or check ~/.aws/credentials."
        )
        return

    # Minimal, cheap request — a few tokens, just to prove the round trip works.
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 20,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
    }

    print(f"Region:   {REGION}")
    print(f"Model ID: {MODEL_ID}")
    print("Invoking model...")

    try:
        response = client.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps(body),
        )
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "AccessDeniedException":
            fail(
                "AccessDeniedException. Two likely causes:\n"
                "  1. Your IAM user/policy doesn't grant bedrock:InvokeModel.\n"
                "  2. You haven't enabled access to this specific model in "
                "the Bedrock console (Model access page) yet.\n"
                f"Full error: {e}"
            )
        elif error_code == "ValidationException":
            fail(
                "ValidationException — usually means BEDROCK_MODEL_ID is "
                f"wrong or not available in region {REGION}.\nFull error: {e}"
            )
        else:
            fail(f"{error_code}: {e}")
        return

    payload = json.loads(response["body"].read())
    text = payload.get("content", [{}])[0].get("text", "")

    print(f"Model replied: {text!r}")
    print("SUCCESS: Bedrock credentials and model access are working.")


if __name__ == "__main__":
    main()
