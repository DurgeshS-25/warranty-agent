"""
Extraction schema.

Shaped directly by real cached receipts (cache/*.json), not written from
assumption first. Two things in the real data forced design decisions:

1. A single Best Buy order can contain multiple distinct products
   (a mouse, a laptop, and three free-gift line items in one real
   example) — so `items` is a list, not a single description/price pair.
2. Apple sometimes splits one order into multiple separate invoice
   emails that share an order_number but have different invoice numbers.
   This schema extracts one record per EMAIL, not per ORDER — a purchase
   spanning multiple emails will produce multiple ExtractedReceipt
   objects that happen to share an order_number. Deduplication/merging
   by order_number is a Stage 3 concern (DynamoDB idempotency), not
   extraction's job.

Also real: some emails matching the domain+subject filters aren't
receipts at all (a "tell us about your experience" survey nudge with no
item/price/order-number content). `is_valid_receipt` exists specifically
because of those — the model must say "this isn't actually a receipt"
rather than inventing plausible-looking fake data to fill the schema.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str
    price: float | None = Field(
        default=None,
        description="Price for this specific line item, if stated. None "
        "for e.g. free gift-with-purchase items.",
    )
    sku: str | None = None


class ExtractedReceipt(BaseModel):
    message_id: str
    merchant_key: str = Field(
        description="Which policy-table entry this belongs to (apple, "
        "best_buy, target, new_balance, dbrand), or 'unknown' if the "
        "sender doesn't match any known merchant."
    )

    is_valid_receipt: bool = Field(
        description="False if this email matched the search filters but "
        "isn't actually a purchase receipt (a review-request nudge, a "
        "shipping-status ping with no item details, etc). When False, "
        "every field below should be left at its default/None — do not "
        "guess or fabricate values to fill the schema."
    )
    invalid_reason: str | None = Field(
        default=None,
        description="If is_valid_receipt is False, a short plain-English "
        "reason why (e.g. 'post-purchase survey email, no item or price "
        "information present').",
    )

    order_number: str | None = None
    order_date: date | None = None
    items: list[LineItem] = Field(default_factory=list)
    total_amount: float | None = None
    currency: str | None = "USD"

    stated_return_window_text: str | None = Field(
        default=None,
        description="If the email itself explicitly states a return "
        "window or deadline (rare, but happens), the exact text stating "
        "it. Do not paraphrase — capture what the email actually said, "
        "so a human could verify it. None if not stated.",
    )

    extraction_notes: str | None = Field(
        default=None,
        description="Any caveat worth surfacing — ambiguous item "
        "description, uncertain total (e.g. tax vs. no tax), multiple "
        "possible order numbers in the email, etc.",
    )


class DeadlineResult(BaseModel):
    return_deadline: date | None
    source: Literal["stated_in_email", "policy_table", "model_estimate", "unknown"]
    source_detail: str = Field(
        description="Human-readable explanation of where this deadline "
        "came from — the exact stated text, the policy table entry name "
        "+ source_url, or the model's reasoning if estimated."
    )
    window_days: int | None = None
