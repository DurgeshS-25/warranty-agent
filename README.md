# Warranty / Return-Window Agent

A background agent that watches my own Gmail for purchase receipts, works
out each item's return/warranty deadline, and stays completely silent
until something is genuinely about to expire — then sends one digest
email with a recommendation. No dashboard to check, no chatbot to ask.

> Status: Stage 1 (credentials + verification). Demo below will be filled
> in as later stages land.

## Demo

<!-- TODO Stage 5: replace with actual screen recording / gif showing
     the agent running and a real digest email arriving -->

## Why this exists

Return windows are the kind of deadline that's easy to lose track of
because nothing reminds you until it's too late. This agent runs on a
schedule, reads receipts, and only interrupts you when a decision
actually needs making — which is the pattern I think most "background
agent" use cases should follow, instead of another app to remember to open.

## Design decisions (and why)

- **Return windows are almost never stated in the receipt email.**
  So deadlines come from three sources, in priority order, and every
  computed deadline is tagged with which one produced it:
  `stated_in_email` → `policy_table` (hardcoded, ~10-15 retailers I
  actually buy from) → `model_estimate` (labeled, never presented as fact).
- **Confident cases are handled silently; ambiguous ones escalate with a
  recommendation attached.** The agent doesn't ask "what should I do
  about X" — it says "X expires in 5 days, source: policy_table,
  recommend returning it."
- **Cost discipline was a first-class constraint, not an afterthought.**
  See `docs/` for the running log of every stage, including the specific
  choices made to keep this under $10 total (HTML stripped before it
  ever reaches the model, prompt iteration against a local cache instead
  of live Gmail calls, explicit loop-iteration caps, cheap model for
  iteration / Sonnet only for validation).

## Explicitly out of scope

Filing returns, browser automation, multi-user support, a web UI beyond
a bare read-only list, PDF/image attachment parsing, warranty
registration, price-drop tracking, subscription detection. Kept small on
purpose — see `docs/stage1_setup.md` for the reasoning.

## Stack

Strands Agents SDK · Amazon Bedrock · Gmail API (read-only) · DynamoDB ·
SES · EventBridge · AgentCore Runtime (Lambda fallback)

## Architecture

<!-- TODO Stage 4: diagram goes here -->

## Setup

```bash
git clone <this-repo>
cd warranty-agent
pip install -r requirements.txt
cp .env.example .env   # fill in AWS_REGION, BEDROCK_MODEL_ID, etc.
```

Stage 1 verification (do these before writing any agent code):

```bash
python scripts/verify_bedrock.py
python scripts/verify_gmail_oauth.py
```

Full walkthrough: [`docs/stage1_setup.md`](docs/stage1_setup.md)

## Cost

Target: under $10 total. Actual breakdown tracked in `docs/` as stages land.

## Build log

- [Stage 1 — Credentials & verification](docs/stage1_setup.md)

## License

Apache 2.0 — see [LICENSE](LICENSE).
