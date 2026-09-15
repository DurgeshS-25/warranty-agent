"""
Extraction prompt.

Does not ask the model to identify the merchant — that's already known
deterministically from the sender domain.
"""

EXTRACTION_PROMPT_TEMPLATE = """You are extracting structured data from a purchase receipt email. The email has already had its HTML stripped to plain text.

Return ONLY a JSON object (no markdown fences, no commentary before or after) with exactly these fields:

{{
  "is_valid_receipt": true or false,
  "invalid_reason": string or null,
  "order_number": string or null,
  "order_date": "YYYY-MM-DD" or null,
  "items": [{{"description": string, "price": number or null, "sku": string or null}}],
  "total_amount": number or null,
  "currency": string or null (default "USD"),
  "stated_return_window_text": string or null,
  "extraction_notes": string or null
}}

Rules:
- is_valid_receipt is false if this email does NOT actually contain a purchase
  (e.g. it's a review-request nudge, a marketing email, or a shipping-status
  ping with no item/price/order-number information). When false, leave the
  other fields at their default (null / empty list) — do NOT invent plausible
  values to fill them in.
- If a field's value isn't clearly present in the email, use null. Never guess
  or fabricate a value. A missing order_number is far better than a wrong one.
- CRITICAL: only include items that were ACTUALLY PURCHASED in this order.
  Retail emails frequently include sections like "Perfect pairings for your
  order", "You may also like", "Recommended for you", "Get X with select Y",
  or similar cross-sell/upsell sections listing OTHER products the retailer
  is trying to sell — these are NOT part of the order and must NOT appear in
  items. A reliable signal: the email's own Order Summary / Subtotal line
  often states the real item count (e.g. "Subtotal (1 item)") — if the number
  of items you're about to list doesn't match that count, re-read the email
  and remove whichever items came from a recommendation/upsell section rather
  than the actual order summary.
- The exception: a genuine "free gift with purchase" that ships as part of
  THIS order (price $0 or "FREE", explicitly tied to the paid item, e.g.
  "Gift with the purchase of: [item]") DOES belong in items — that's a real
  part of the order, unlike a cross-sell recommendation.
- If total_amount is stated and your extracted items' prices don't roughly
  sum to it, mention this discrepancy in extraction_notes rather than
  silently including items that don't belong.
- stated_return_window_text should be the exact text ONLY if the email states
  a SPECIFIC deadline or number of days (e.g. "return within 30 days"). Generic
  return-policy boilerplate with no specific day count (e.g. "returns must be
  in new condition, see our website for details") does NOT count — leave this
  null in that case, since there's no actual deadline to extract from it.
- order_date should be the purchase/order date, not a delivery estimate or
  "get it by" date.

Email content:
---
{email_text}
---

JSON:"""


def build_prompt(email_text: str) -> str:
    return EXTRACTION_PROMPT_TEMPLATE.format(email_text=email_text)
