# Stage 1 — Credentials & Verification

## Goal
Zero application code. Prove that the two external systems this project
depends on — Bedrock and Gmail — are reachable with least-privilege
credentials, before writing a single line of agent logic. If auth is
broken, you want to find that out in a 20-line script, not three days
into debugging an agent that "isn't working."

## What got built
- `LICENSE` — Apache 2.0, so the repo is legally reusable/forkable (a
  hiring manager checking your GitHub sees this as a small positive signal
  of doing things properly, not just dumping code).
- `.gitignore` — keeps `.env`, `credentials.json`, `token.json`, and the
  local receipt cache out of the public repo. The cache holds real email
  content; it should never be committed even though it's "just yours."
- `requirements.txt` / `.env.example` — dependency list and the env-var
  contract. `BEDROCK_MODEL_ID` is read from env everywhere, never
  hardcoded — see "Decisions" below.
- `scripts/verify_bedrock.py` — raw boto3 call to Bedrock (deliberately
  not using the Strands SDK yet). Confirms IAM permissions + model access
  are correct in isolation, so any problem in Stage 2 is provably an SDK
  or prompt issue, not a credentials issue.
- `scripts/verify_gmail_oauth.py` — runs the OAuth consent flow with
  `gmail.readonly` only, then lists 5 message subjects. Does not read
  bodies, does not write, does not send. Smallest possible proof that
  read-only access works.
- `infra/create_budget_alarm.sh` — AWS Budget, $10/month cap, email
  alerts at 50/80/100% of actual spend. Documented here because it must
  run **first**, before either verification script.

## Decisions made and why

**Bedrock model ID comes from env, never hardcoded.**
Model ID strings change, and typing one from memory risks either a hard
failure (annoying but safe) or, worse, silently succeeding against a
different and possibly more expensive model. The script fails loudly if
`BEDROCK_MODEL_ID` isn't set, with instructions to copy it from the
console.

**The two verification scripts test one thing each, nothing more.**
Combining "does auth work" with "does extraction work" makes failures
ambiguous. Separating them means a failure always points at exactly one
system.

**Gmail OAuth: External consent screen, Testing mode, my own address as
the only test user, Desktop app client, `gmail.readonly` scope only.**
No app verification needed at this scale — verification is an
enterprise/production concern for apps with real external users. Testing
mode's one real cost: refresh tokens expire after 7 days of the app
being unpublished, so expect to redo consent periodically. Documented in
the script itself so it isn't mistaken for a bug later.

**Budget alarm exists before any other AWS resource does.**
AWS Budgets polls spend roughly every 8 hours — it's a smoke detector,
not a circuit breaker. It won't stop a runaway loop mid-spend. The actual
circuit breaker is explicit iteration caps in the agent code (Stage 2+).
Both matter; neither substitutes for the other.

## Verification

Both must print `SUCCESS` before Stage 2 starts:

```bash
python scripts/verify_bedrock.py
python scripts/verify_gmail_oauth.py
```

## Cost so far
$0 spent on inference (no model calls yet beyond the ~20-token smoke
test in `verify_bedrock.py`, a fraction of a cent). Budget alarm active.

## Open risks carried into Stage 2
- Gmail Testing-mode token expiry (7 days) means re-auth may be needed
  mid-build — not a blocker, just a known nuisance.
- Nothing yet enforces the "only 10-15 retailers get policy-table
  treatment" boundary in code — that's a Stage 2 design task, not done here.
