"""
Hardcoded return-policy table.

This is the highest-confidence source of return-window data in the whole
project — it deliberately overrides anything the model might guess.
Every entry here was checked against the retailer's own policy page
(see `source_url`) on `verified_on`. These policies change without much
notice (Target's Apple-product window, for instance, has moved before),
so treat `verified_on` as an expiry warning, not decoration — recheck
before trusting an entry that's more than a few months stale.

Retailer selection was NOT a guess: it came from scripts/scan_receipt_senders.py
run against 12 months of real inbox data (Stage 2, step 1). Domains that
showed up frequently but aren't merchandise purchases (rides, food
delivery, job applications, subscriptions) were deliberately excluded —
"return window" doesn't apply to an Uber ride.
"""

from datetime import date
from typing import NamedTuple


class ReturnPolicy(NamedTuple):
    merchant: str
    # All known sending domains for this merchant's receipt emails —
    # matched against the email's From header to identify the merchant.
    # Kept as a tuple, not a single domain, because real receipt senders
    # fragment across subdomains (Apple alone uses three).
    sender_domains: tuple[str, ...]
    return_window_days: int
    window_starts_from: str  # "delivery" | "shipment" | "purchase"
    notes: str
    source_url: str
    verified_on: date


POLICY_TABLE: dict[str, ReturnPolicy] = {
    "apple": ReturnPolicy(
        merchant="Apple",
        sender_domains=("email.apple.com", "orders.apple.com", "applepay.apple.com"),
        return_window_days=14,
        window_starts_from="delivery",
        notes=(
            "Apple's own direct-purchase policy (apple.com / Apple Store). "
            "Does NOT apply to Apple products bought through a third-party "
            "retailer like Target or Best Buy — those follow the retailer's "
            "own (usually shorter) Apple-specific window instead."
        ),
        source_url="https://www.apple.com/shop/help/returns_refund",
        verified_on=date(2026, 9, 15),
    ),
    "best_buy": ReturnPolicy(
        merchant="Best Buy",
        sender_domains=("emailinfo.bestbuy.com",),
        return_window_days=15,
        window_starts_from="purchase",
        notes=(
            "Sender domain is emailinfo.bestbuy.com — NOT email.bestbuy.com, "
            "which is the marketing/promo domain and sends zero real "
            "receipts. Found this the hard way: an initial cache-building "
            "pass filtered on the wrong domain and returned 0 real Best Buy "
            "emails despite Best Buy clearly being a real merchant here. "
            "Standard/non-member window. My Best Buy Plus/Total members get "
            "60 days instead — this table has no way to know the person's "
            "membership tier, so 15 days is the safe (shorter) default. "
            "Cell phones/tablets are 14 days regardless of tier."
        ),
        source_url="https://www.bestbuy.com/site/help-topics/return-exchange-policy/pcmcat260800050014.c",
        verified_on=date(2026, 9, 15),
    ),
    "target": ReturnPolicy(
        merchant="Target",
        sender_domains=("oe.target.com", "oe1.target.com"),
        return_window_days=90,
        window_starts_from="purchase",
        notes=(
            "90 days is the STANDARD window only. Electronics drop to 30 "
            "days, Apple/Beats products to 15 days, mobile phones to 14 "
            "days. This table has no per-item-category detection yet, so "
            "the 90-day default will be WRONG (too generous) for "
            "electronics purchases — flagged as a known gap, see "
            "docs/stage2_extraction.md."
        ),
        source_url="https://www.target.com/c/return-policy/-/N-4tstt",
        verified_on=date(2026, 9, 15),
    ),
    "new_balance": ReturnPolicy(
        merchant="New Balance",
        sender_domains=("receipts.newbalance.com", "nbstores.newbalance.com"),
        return_window_days=45,
        window_starts_from="shipment",
        notes="Online orders: 45 days from ship date, not delivery date.",
        source_url="https://www.newbalance.com/returns/",
        verified_on=date(2026, 9, 15),
    ),
    "dbrand": ReturnPolicy(
        merchant="dbrand",
        sender_domains=("dbrand.com",),
        return_window_days=30,
        window_starts_from="delivery",
        notes=(
            "Applied/used skins are non-returnable regardless of window — "
            "this table can't detect 'applied vs. unapplied', so treat "
            "dbrand escalations as lower-confidence than the window alone "
            "suggests."
        ),
        source_url="https://dbrand.com/about/return-policy",
        verified_on=date(2026, 9, 15),
    ),
}


def match_policy(sender_email: str) -> ReturnPolicy | None:
    """Given a raw From-header email address, return the matching policy
    entry, or None if no known retailer matches (caller should fall back
    to the model-estimate path in that case, tagged accordingly)."""
    sender_email = sender_email.lower()
    for policy in POLICY_TABLE.values():
        if any(domain in sender_email for domain in policy.sender_domains):
            return policy
    return None
