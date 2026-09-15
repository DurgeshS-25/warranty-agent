"""
Stage 2, step 3 (part 1): verify the deadline logic against real data,
with NO model involved yet.

This hand-fills an ExtractedReceipt using the real Best Buy order from
cache/best_buy_e38046ccf4c5.json (order date read straight from that
file's email Date header) to prove compute_deadline() works correctly
before trusting a model to produce the ExtractedReceipt automatically.
If this fails, the bug is in deadline.py or the policy table — not in
prompt engineering — and it's much faster to find it here.

Run:
    python scripts/test_deadline_logic.py
"""

from datetime import date

from extraction import ExtractedReceipt, LineItem, compute_deadline


def main() -> None:
    # Hand-transcribed from cache/best_buy_e38046ccf4c5.json — real data,
    # manually entered, zero model involvement.
    receipt = ExtractedReceipt(
        message_id="18bf285331e3d647",
        merchant_key="best_buy",
        is_valid_receipt=True,
        order_number="BBY01-806817575361",
        order_date=date(2023, 11, 21),  # from the email's Date header
        items=[
            LineItem(
                description="Logitech G PRO Lightweight Wireless Optical "
                "Ambidextrous Gaming Mouse with RGB Lighting - Black",
                price=79.99,
                sku="6265132",
            ),
            LineItem(
                description="ASUS ROG Zephyrus M16 16\" 240Hz Gaming Laptop "
                "QHD - Intel 13th Gen Core i9, 16GB, RTX 4070, 1TB SSD",
                price=1499.99,
                sku="6535501",
            ),
        ],
        total_amount=1678.73,
    )

    result = compute_deadline(receipt, sender_email="BestBuyInfo@emailinfo.bestbuy.com")

    print("Receipt:", receipt.merchant_key, receipt.order_number)
    print("Order date:", receipt.order_date)
    print()
    print("Deadline result:")
    print("  return_deadline:", result.return_deadline)
    print("  source:", result.source)
    print("  window_days:", result.window_days)
    print("  source_detail:", result.source_detail)

    assert result.source == "policy_table", "Expected a policy-table match for Best Buy"
    assert result.return_deadline == date(2023, 12, 6), (
        f"Expected 2023-12-06 (Nov 21 + 15 days), got {result.return_deadline}"
    )
    print("\nPASS — deadline logic correct against real Best Buy data.")


if __name__ == "__main__":
    main()
