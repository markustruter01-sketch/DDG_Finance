"""
saas_stripe.py  —  AlgoEdge Stripe Integration (Python)
=========================================================
Central place for all Stripe SDK initialisation and helpers.

Environment variables (set as Replit secrets):
  STRIPE_SECRET_KEY          sk_test_... or sk_live_...
  STRIPE_PUBLISHABLE_KEY     pk_test_... or pk_live_...
  STRIPE_WEBHOOK_SECRET      whsec_...

Tier definitions:
  tier1 — Crypto Engine     $19.96 every 4 weeks  (RSI+Z crypto signals, Kraken access)
  tier2 — Equities Engine   $39.96 every 4 weeks  (AI equity signals, Alpaca access)
  tier3 — Combined Hub      $51.96 every 4 weeks  (everything — Kraken + Alpaca)

Annual pricing (20% discount, billed as one payment every 52 weeks):
  tier1 — $207.58 / year  ($19.96 × 13 × 0.80)
  tier2 — $415.16 / year  ($39.96 × 13 × 0.80)
  tier3 — $539.58 / year  ($51.96 × 13 × 0.80)

Billing interval: Stripe `day`-based recurring prices (28 days).
"""

from __future__ import annotations

import os
from typing import Literal

import stripe
from loguru import logger

# ── SDK initialisation ────────────────────────────────────────────────────────

STRIPE_SECRET_KEY      = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET  = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
    logger.info(f"Stripe | SDK initialised — key prefix: {STRIPE_SECRET_KEY[:8]}…")
else:
    logger.warning("Stripe | STRIPE_SECRET_KEY not set — payment features disabled")

# ── Tier metadata ─────────────────────────────────────────────────────────────

TierID = Literal["tier1", "tier2", "tier3"]

TIERS: dict[TierID, dict] = {
    "tier1": {
        "name":             "Crypto Engine",
        "display_price":    "$4.99 / week",
        "billing_label":    "Billed upfront as $19.96 every 4 weeks",
        "amount_4w":        1996,         # cents — $19.96
        "amount_annual":    20758,        # cents — $207.58 (20% off)
        "interval_days":    28,
        "features": [
            "10-symbol mean-reversion bot (24/7 Kraken)",
            "RSI + Z-score dual-signal alerts",
            "1-click trade execution (Kraken)",
            "Live insight dashboard",
            "Up to 10 simultaneous positions",
        ],
        "exchange_access":  ["kraken"],
    },
    "tier2": {
        "name":             "Equities Engine",
        "display_price":    "$9.99 / week",
        "billing_label":    "Billed upfront as $39.96 every 4 weeks",
        "amount_4w":        3996,         # cents — $39.96
        "amount_annual":    41516,        # cents — $415.16 (20% off)
        "interval_days":    28,
        "features": [
            "AI-driven US equity signals (Alpaca)",
            "Groq Llama 3.3 70B market analysis",
            "Profit vault + ratchet stop system",
            "Economic calendar integration",
            "Post-mortem trade analytics",
        ],
        "exchange_access":  ["alpaca"],
    },
    "tier3": {
        "name":             "Combined Hub",
        "display_price":    "$12.99 / week",
        "billing_label":    "Billed upfront as $51.96 every 4 weeks",
        "amount_4w":        5196,         # cents — $51.96
        "amount_annual":    53958,        # cents — $539.58 (20% off)
        "interval_days":    28,
        "features": [
            "Everything in Crypto Engine",
            "Everything in Equities Engine",
            "Combined unified dashboard",
            "Cross-asset portfolio analytics",
            "Priority signal delivery",
        ],
        "exchange_access":  ["kraken", "alpaca"],
        "badge":            "Most Popular",
    },
}

# ── Price ID cache (populated by seed script / on startup) ────────────────────
# Maps tier → billing_cycle → Stripe price ID (price_...)
# Populated at runtime via load_price_ids() which reads from Stripe metadata.

_price_ids: dict[str, dict[str, str]] = {
    "tier1": {"4w": "", "annual": ""},
    "tier2": {"4w": "", "annual": ""},
    "tier3": {"4w": "", "annual": ""},
}


def load_price_ids() -> bool:
    """
    Scan active Stripe products for our tier products (matched by metadata.algoedge_tier)
    and cache the associated price IDs.  Called once on startup.

    Returns True if all 6 price IDs were found, False otherwise.
    """
    if not STRIPE_SECRET_KEY:
        return False
    try:
        products = stripe.Product.list(active=True, limit=20)
        found = 0
        for product in products.auto_paging_iter():
            tier = product.metadata.get("algoedge_tier")
            if tier not in _price_ids:
                continue
            prices = stripe.Price.list(product=product.id, active=True)
            for price in prices.auto_paging_iter():
                cycle = price.metadata.get("billing_cycle")
                if cycle in ("4w", "annual"):
                    _price_ids[tier][cycle] = price.id
                    found += 1
        logger.info(f"Stripe | Loaded {found}/6 price IDs from Stripe")
        return found == 6
    except Exception as exc:
        logger.error(f"Stripe | load_price_ids failed: {exc}")
        return False


def get_price_id(tier: TierID, cycle: str) -> str | None:
    """Return the cached Stripe price ID for a given tier and billing cycle."""
    return _price_ids.get(tier, {}).get(cycle) or None


# ── Webhook signature verification ────────────────────────────────────────────

def verify_webhook(payload: bytes, sig_header: str) -> stripe.Event:
    """
    Verify and parse an incoming Stripe webhook event.
    Raises stripe.error.SignatureVerificationError on invalid signature.
    """
    return stripe.Webhook.construct_event(
        payload, sig_header, STRIPE_WEBHOOK_SECRET
    )


# ── Access control helpers ────────────────────────────────────────────────────

def tier_unlocks_kraken(tier: TierID | None) -> bool:
    """True if this tier grants Kraken 1-click execution access."""
    return tier in ("tier1", "tier3")


def tier_unlocks_alpaca(tier: TierID | None) -> bool:
    """True if this tier grants Alpaca trading access."""
    return tier in ("tier2", "tier3")


def tier_display_name(tier: TierID | None) -> str:
    if tier is None:
        return "Free"
    return TIERS.get(tier, {}).get("name", tier)
