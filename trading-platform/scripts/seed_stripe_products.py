#!/usr/bin/env python3
"""
seed_stripe_products.py  —  Create AlgoEdge products and prices in Stripe
=========================================================================
Run once in development:
  cd trading-platform && python3 scripts/seed_stripe_products.py

Creates 3 products (one per tier) each with 2 prices:
  4-week billing (28-day recurring)
  Annual billing (365-day recurring, 20% discount)

Products are tagged with metadata so the SaaS router can identify them:
  metadata.algoedge_tier  = "tier1" | "tier2" | "tier3"
  metadata.billing_cycle  = "4w"    | "annual"  (on price objects)

Running this script a second time is safe — it skips tiers that already exist.
"""

from __future__ import annotations

import os
import sys

# ── Setup path so we can import saas_stripe from parent ──────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import stripe
from dotenv import load_dotenv

load_dotenv()

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
if not STRIPE_SECRET_KEY:
    print("ERROR: STRIPE_SECRET_KEY not set")
    sys.exit(1)

stripe.api_key = STRIPE_SECRET_KEY
print(f"Stripe key prefix: {STRIPE_SECRET_KEY[:8]}…")

TIER_DEFINITIONS = {
    "tier1": {
        "name":          "AlgoEdge Crypto Engine",
        "description":   "24/7 RSI+Z-score mean-reversion signals across 10 crypto markets. 1-click Kraken execution.",
        "amount_4w":     1996,     # $19.96
        "amount_annual": 20758,    # $207.58 (20% off × 13 cycles)
    },
    "tier2": {
        "name":          "AlgoEdge Equities Engine",
        "description":   "AI-driven US equity signals powered by Groq Llama 3.3 70B. Alpaca paper + live execution.",
        "amount_4w":     3996,     # $39.96
        "amount_annual": 41516,    # $415.16
    },
    "tier3": {
        "name":          "AlgoEdge Combined Hub",
        "description":   "Full access: Crypto Engine + Equities Engine + unified dashboard. Best value.",
        "amount_4w":     5196,     # $51.96
        "amount_annual": 53958,    # $539.58
    },
}


def _product_exists(tier: str) -> bool:
    try:
        products = stripe.Product.search(
            query=f"metadata['algoedge_tier']:'{tier}'"
        )
        return bool(products.data)
    except Exception:
        products = stripe.Product.list(active=True, limit=50)
        for p in products.data:
            if p.metadata.get("algoedge_tier") == tier:
                return True
        return False


def seed() -> None:
    for tier_id, meta in TIER_DEFINITIONS.items():
        if _product_exists(tier_id):
            print(f"  {tier_id} — already exists, skipping")
            continue

        print(f"\n  Creating {tier_id} — {meta['name']} …")

        product = stripe.Product.create(
            name=meta["name"],
            description=meta["description"],
            metadata={"algoedge_tier": tier_id},
        )
        print(f"    Product: {product.id}")

        # 4-week price
        price_4w = stripe.Price.create(
            product=product.id,
            currency="usd",
            unit_amount=meta["amount_4w"],
            recurring={
                "interval":       "day",
                "interval_count": 28,
            },
            metadata={
                "algoedge_tier": tier_id,
                "billing_cycle": "4w",
            },
        )
        print(f"    4-week price: {price_4w.id}  (${meta['amount_4w']/100:.2f})")

        # Annual price
        price_annual = stripe.Price.create(
            product=product.id,
            currency="usd",
            unit_amount=meta["amount_annual"],
            recurring={
                "interval":       "day",
                "interval_count": 365,
            },
            metadata={
                "algoedge_tier": tier_id,
                "billing_cycle": "annual",
            },
        )
        print(f"    Annual price: {price_annual.id}  (${meta['amount_annual']/100:.2f})")

    print("\n✓ Seed complete\n")


if __name__ == "__main__":
    seed()
