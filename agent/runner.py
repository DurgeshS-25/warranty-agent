"""
Builds and runs the Strands agent with hard budget caps, then prints a
readable trace of every tool call (reconstructed from the message history).
"""

import json
import os
import re

from dotenv import load_dotenv
from strands import Agent
from strands.models import BedrockModel
from strands.tools.executors import SequentialToolExecutor

from agent.tools import list_expiring_orders, list_new_emails, process_email

load_dotenv()

REGION = os.environ.get("AWS_REGION")

# Hard caps: the circuit breaker the budget alarm cannot be.
# 10 emails max per run + list + expiring + final answer ~= 13 turns.
MAX_TURNS = 16
MAX_TOTAL_TOKENS = 60_000

SYSTEM_PROMPT = """You run the daily return-window check for one person's receipts.

Steps, in order:
1. Call list_new_emails.
2. If there are new emails, call process_email once per message_id, one at a time.
3. Call list_expiring_orders with the look-ahead window you are given.
4. Write a final report.

Rules:
- Never invent or estimate a deadline. Report only what the tools return.
- Write "Nothing expiring." ONLY if the tool result starts with NONE. Otherwise copy every result line into your report unchanged.
- Otherwise list each expiring order: merchant, order number, deadline, deadline source.
- If any tool returns ERROR, mention it in one line.
- Be brief."""


def build_agent() -> Agent:
    model = BedrockModel(
        model_id=os.environ["BEDROCK_MODEL_ID"],  # us.-prefixed Haiku profile
        region_name=REGION,
        temperature=0,
        max_tokens=1000,
    )
    return Agent(
        model=model,
        tools=[list_new_emails, process_email, list_expiring_orders],
        system_prompt=SYSTEM_PROMPT,
        tool_executor=SequentialToolExecutor(),  # no concurrent order merges
        callback_handler=None,                   # no streaming noise
    )


def print_trace(agent: Agent) -> int:
    print("\n=== Tool-call trace ===")
    calls = 0
    for message in agent.messages:
        for block in message.get("content", []):
            if "toolUse" in block:
                calls += 1
                tu = block["toolUse"]
                print(f"[{calls}] CALL {tu['name']}({json.dumps(tu['input'])})")
            elif "toolResult" in block:
                text = "".join(c.get("text", "") for c in block["toolResult"].get("content", []))
                print(f"      -> {text[:160]!r}")
    return calls


def run_check(within_days: int = 7) -> None:
    agent = build_agent()
    result = agent(
        f"Run the check. Look-ahead window: {within_days} days.",
        limits={"turns": MAX_TURNS, "total_tokens": MAX_TOTAL_TOKENS},
    )

    calls = print_trace(agent)

    expiring = last_expiring_result(agent)
    print("\n=== Authoritative result (from tool, not model) ===")
    print(expiring or "list_expiring_orders was never called")
    if expiring and not expiring.startswith("NONE") and "nothing expiring" in str(result).lower():
        print("WARNING: model report contradicts tool output. Trust the tool result above.")

    print("\n=== DIGEST (deterministic, built from tool output) ===")
    if expiring and not expiring.startswith("NONE"):
        print(expiring)
    else:
        print("Nothing expiring.")

    print("\n=== Model commentary (advisory only) ===")
    report = re.sub(r"<thinking>.*?</thinking>", "", str(result), flags=re.DOTALL)
    print(report.strip())

    print("\n=== Run stats ===")
    print(f"tool calls: {calls}")
    print(f"stop reason: {result.stop_reason}")
    usage = getattr(result.metrics, "accumulated_usage", None)
    if usage:
        print(f"tokens: {usage}")
    if str(result.stop_reason).startswith("limit_"):
        print("WARNING: hit a budget cap; the run was cut short.")


def last_expiring_result(agent: Agent) -> str | None:
    """Raw text of the last list_expiring_orders result: the source of truth."""
    ids, text = set(), None
    for message in agent.messages:
        for block in message.get("content", []):
            if "toolUse" in block and block["toolUse"]["name"] == "list_expiring_orders":
                ids.add(block["toolUse"]["toolUseId"])
            elif "toolResult" in block and block["toolResult"].get("toolUseId") in ids:
                text = "".join(c.get("text", "") for c in block["toolResult"].get("content", []))
    return text
