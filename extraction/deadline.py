"""
Deadline computation.

Priority order:
  1. stated_in_email  — the email itself stated an explicit deadline/day
                          count; trust it verbatim. NOTE: text merely
                          mentioning "return policy" without a specific
                          number of days does NOT count — that's
                          boilerplate, not a stated deadline, and should
                          fall through to the policy table instead.
  2. policy_table      — merchant is one of our hand-verified entries.
  3. model_estimate    — merchant unknown to the policy table.
"""

from datetime import timedelta

from extraction.schema import DeadlineResult, ExtractedReceipt
from policy import match_policy


def compute_deadline(receipt: ExtractedReceipt, sender_email: str) -> DeadlineResult:
    if not receipt.is_valid_receipt:
        return DeadlineResult(
            return_deadline=None,
            source="unknown",
            source_detail=f"Not a valid receipt: {receipt.invalid_reason}",
        )

    # Priority 1: only take this path if we can actually compute a real
    # deadline from the stated text. Parsing arbitrary stated text into a
    # date isn't implemented yet — no real cached email has needed it so
    # far (every "stated_return_window_text" seen has been generic policy
    # boilerplate with no explicit day count, e.g. New Balance's return
    # instructions, which mention no number of days at all). So this
    # branch is intentionally inert for now rather than dead-ending the
    # whole computation — it must fall through to policy_table below,
    # not return early with an unusable None deadline.
    stated_deadline = None  # TODO: implement text->date parsing when a
                             # real example actually needs it
    if stated_deadline:
        return DeadlineResult(
            return_deadline=stated_deadline,
            source="stated_in_email",
            source_detail=receipt.stated_return_window_text,
        )

    # Priority 2: policy table lookup — the common, trusted, zero-cost path.
    policy = match_policy(sender_email)
    if policy and receipt.order_date:
        deadline = receipt.order_date + timedelta(days=policy.return_window_days)
        return DeadlineResult(
            return_deadline=deadline,
            source="policy_table",
            source_detail=(
                f"{policy.merchant} standard policy: {policy.return_window_days} "
                f"days from {policy.window_starts_from}. Source: {policy.source_url} "
                f"(verified {policy.verified_on}). {policy.notes}"
            ),
            window_days=policy.return_window_days,
        )

    # Priority 3: no policy match and no stated deadline.
    return DeadlineResult(
        return_deadline=None,
        source="unknown",
        source_detail=(
            "No policy table match and no order_date to compute from. "
            "Needs model_estimate fallback (not yet implemented)."
        ),
    )
