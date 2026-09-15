"""
Deadline computation.

Deliberately NOT a model call for the common cases. Priority order:
  1. stated_in_email  — the email itself said a deadline; trust it verbatim.
  2. policy_table      — merchant is one of our hand-verified 5; use it.
  3. model_estimate    — merchant unknown to the policy table; ask the
                          model to estimate, clearly labeled as a guess.

This function only handles the first two, deterministically, with zero
model cost. The model_estimate path is a separate function (Stage 2
step 3, not yet built) that gets called only when this returns "unknown"
— which should be rare given the policy table now covers every merchant
that showed up meaningfully in a real 12-month inbox scan.
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

    # Priority 1: the email stated its own deadline. Trust it, but only
    # if extraction also gave us an order_date to anchor against — a
    # stated window with no date to compute from isn't usable yet. (This
    # path is a stub: real implementation needs a second, small model
    # call to parse the stated text into an actual number of days, or a
    # direct date. None of the 4 verified merchants' real emails stated
    # a deadline directly, so this is untested against real data so far.)
    if receipt.stated_return_window_text and receipt.order_date:
        return DeadlineResult(
            return_deadline=None,  # TODO: parse stated_return_window_text
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

    # Priority 3: no policy match and no stated deadline — this is where
    # a model_estimate call belongs. Not implemented yet (Stage 2 step 3).
    return DeadlineResult(
        return_deadline=None,
        source="unknown",
        source_detail=(
            "No policy table match and no order_date to compute from. "
            "Needs model_estimate fallback (not yet implemented)."
        ),
    )
