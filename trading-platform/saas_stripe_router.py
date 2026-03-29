"""
saas_stripe_router.py  —  Stripe payment & webhook routes for AlgoEdge SaaS
=============================================================================
Routes (all under /saas-api prefix via saas_router):

  GET  /saas-api/stripe/config          → publishable key + tier definitions for frontend
  GET  /saas-api/stripe/products        → live tier listing with price IDs from Stripe
  POST /saas-api/stripe/checkout        → create Stripe Checkout Session, return URL
  POST /saas-api/stripe/portal          → create Stripe Billing Portal session
  POST /saas-api/stripe/webhook         → receive & verify Stripe webhook events

Billing model:
  4-week billing:  28-day interval recurring prices
  Annual billing:  365-day interval recurring prices (20% discount)

Access provisioning (on checkout.session.completed):
  tier1 → Crypto Engine   → Kraken API access unlocked
  tier2 → Equities Engine → Alpaca API access unlocked
  tier3 → Combined Hub    → both unlocked

Proration: handled automatically by Stripe when upgrading/downgrading subscriptions.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from db.postgres import get_conn, is_pg_available

# ── Stripe import guard ────────────────────────────────────────────────────────

try:
    import stripe as _stripe_lib
    _STRIPE_OK = True
except ImportError:
    _stripe_lib = None  # type: ignore
    _STRIPE_OK = False

# ── Config from environment ────────────────────────────────────────────────────

STRIPE_SECRET_KEY      = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET  = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

if _STRIPE_OK and STRIPE_SECRET_KEY:
    _stripe_lib.api_key = STRIPE_SECRET_KEY

# ── Router ─────────────────────────────────────────────────────────────────────

stripe_bp = APIRouter(tags=["Stripe Billing"])   # mounted onto saas_router

# ── Tier definitions ───────────────────────────────────────────────────────────

TIERS = {
    "tier1": {
        "name":          "Crypto Engine",
        "display_price": "$4.99 / week",
        "billing_label": "Billed upfront as $19.96 every 4 weeks",
        "amount_4w":     1996,     # cents
        "amount_annual": 20758,    # cents  ($19.96 × 13 × 0.80)
        "exchange_access": ["kraken"],
        "features": [
            "10-symbol 24/7 Kraken mean-reversion bot",
            "RSI + Z-score dual-signal alerts",
            "1-click trade execution (Kraken)",
            "Live insight dashboard",
            "Up to 10 simultaneous positions",
        ],
    },
    "tier2": {
        "name":          "Equities Engine",
        "display_price": "$9.99 / week",
        "billing_label": "Billed upfront as $39.96 every 4 weeks",
        "amount_4w":     3996,
        "amount_annual": 41516,    # $39.96 × 13 × 0.80
        "exchange_access": ["alpaca"],
        "features": [
            "AI-driven US equity signals (Alpaca)",
            "Groq Llama 3.3 70B market analysis",
            "Profit vault + ratchet stop system",
            "Economic calendar & earnings data",
            "Post-mortem trade analytics",
        ],
    },
    "tier3": {
        "name":          "Combined Hub",
        "display_price": "$12.99 / week",
        "billing_label": "Billed upfront as $51.96 every 4 weeks",
        "amount_4w":     5196,
        "amount_annual": 53958,    # $51.96 × 13 × 0.80
        "exchange_access": ["kraken", "alpaca"],
        "badge":         "Most Popular",
        "features": [
            "Everything in Crypto Engine",
            "Everything in Equities Engine",
            "Combined unified dashboard",
            "Cross-asset portfolio analytics",
            "Priority signal delivery",
        ],
    },
}

# ── Price ID cache  (price_id → {"tier": str, "cycle": str}) ─────────────────
# Populated at startup by scanning Stripe products tagged with algoedge_tier.
_price_map: dict[str, dict] = {}          # price_id → tier/cycle
_tier_prices: dict[str, dict] = {         # tier → {"4w": price_id, "annual": price_id}
    "tier1": {"4w": "", "annual": ""},
    "tier2": {"4w": "", "annual": ""},
    "tier3": {"4w": "", "annual": ""},
}


def _meta(obj) -> dict:
    """Safely extract metadata from a Stripe object as a plain Python dict.

    Stripe v15 returns metadata as a StripeObject, not a plain dict.
    The StripeObject supports bracket access but not dict(). Use to_dict()
    on the nested metadata field to get a real Python dict.
    """
    try:
        md = obj.metadata
        if md is None:
            return {}
        # StripeObject has .to_dict() → plain Python dict
        if hasattr(md, "to_dict"):
            return md.to_dict()
        # Fallback: already a plain dict
        return dict(md)
    except Exception:
        return {}


def _reload_price_ids() -> None:
    """Scan active Stripe products and cache price IDs by tier+cycle."""
    if not _STRIPE_OK or not STRIPE_SECRET_KEY:
        return
    try:
        products = _stripe_lib.Product.list(active=True, limit=50)
        for prod in products:
            meta = _meta(prod)
            tier = meta.get("algoedge_tier")
            if tier not in _tier_prices:
                continue
            prices = _stripe_lib.Price.list(product=prod.id, active=True)
            for price in prices:
                pmeta = _meta(price)
                cycle = pmeta.get("billing_cycle")   # "4w" or "annual"
                if cycle in ("4w", "annual"):
                    _tier_prices[tier][cycle] = price.id
                    _price_map[price.id] = {"tier": tier, "cycle": cycle}
    except Exception as exc:
        print(f"[stripe] _reload_price_ids error: {exc}")


# ── DB helpers ────────────────────────────────────────────────────────────────

def _upsert_user_tier(
    customer_id: str,
    subscription_id: str,
    tier: str | None,
    billing_cycle_end: datetime | None,
) -> None:
    """Update saas_users row for the given Stripe customer."""
    if not is_pg_available():
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE saas_users
                SET  stripe_subscription_id = %s,
                     active_license_tier    = %s,
                     billing_cycle_end      = %s,
                     tier_granted_at        = NOW()
                WHERE stripe_customer_id = %s
            """, (subscription_id, tier, billing_cycle_end, customer_id))
            # If no row was updated (customer not yet in DB), create a placeholder
            if cur.rowcount == 0:
                cur.execute("""
                    INSERT INTO saas_users
                        (id, email, stripe_customer_id, stripe_subscription_id,
                         active_license_tier, billing_cycle_end, tier_granted_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (stripe_customer_id) DO UPDATE
                        SET stripe_subscription_id = EXCLUDED.stripe_subscription_id,
                            active_license_tier    = EXCLUDED.active_license_tier,
                            billing_cycle_end      = EXCLUDED.billing_cycle_end,
                            tier_granted_at        = NOW()
                """, (
                    str(uuid.uuid4()), "stripe-sync@pending",
                    customer_id, subscription_id, tier, billing_cycle_end,
                ))


def _get_or_create_customer(email: str) -> str:
    """Get Stripe customer ID from saas_users, or create one in Stripe."""
    if is_pg_available():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT stripe_customer_id FROM saas_users WHERE email = %s",
                    (email,),
                )
                row = cur.fetchone()
                if row and row[0]:
                    return row[0]

    customer = _stripe_lib.Customer.create(email=email)
    if is_pg_available():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO saas_users (id, email, stripe_customer_id)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (email) DO UPDATE
                        SET stripe_customer_id = EXCLUDED.stripe_customer_id
                """, (str(uuid.uuid4()), email, customer.id))
    return customer.id


# ── Pydantic request models ────────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    tier:      Literal["tier1", "tier2", "tier3"]
    cycle:     Literal["4w", "annual"] = "4w"
    email:     str | None = None   # pre-fill Stripe Checkout
    success_url: str | None = None
    cancel_url:  str | None = None


class PortalRequest(BaseModel):
    customer_email: str
    return_url:     str | None = None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@stripe_bp.get("/stripe/config")
async def stripe_config() -> dict:
    """
    Return the Stripe publishable key and tier definitions.
    Called by the frontend on page load to initialise Stripe.js.
    """
    _reload_price_ids()
    return {
        "publishable_key": STRIPE_PUBLISHABLE_KEY,
        "tiers":           TIERS,
        "price_ids":       _tier_prices,
    }


@stripe_bp.get("/stripe/products")
async def stripe_products() -> dict:
    """
    Return enriched tier listing with live price IDs from Stripe.
    Useful for verifying seed data.
    """
    _reload_price_ids()
    enriched = {}
    for tier_id, meta in TIERS.items():
        enriched[tier_id] = {
            **meta,
            "price_id_4w":     _tier_prices[tier_id]["4w"],
            "price_id_annual":  _tier_prices[tier_id]["annual"],
        }
    return {"tiers": enriched}


@stripe_bp.post("/stripe/checkout")
async def stripe_checkout(req: CheckoutRequest, request: Request) -> dict:
    """
    Create a Stripe Checkout Session and return the redirect URL.
    The frontend redirects the user to this URL.
    """
    if not _STRIPE_OK or not STRIPE_SECRET_KEY:
        raise HTTPException(503, "Stripe is not configured — set STRIPE_SECRET_KEY")

    _reload_price_ids()
    price_id = _tier_prices.get(req.tier, {}).get(req.cycle)

    # Determine origin for redirect URLs
    origin = request.headers.get("origin") or request.headers.get("referer", "").rstrip("/")
    success_url = req.success_url or f"{origin}/saas/dashboard?checkout=success"
    cancel_url  = req.cancel_url  or f"{origin}/saas/pricing?checkout=cancelled"

    session_kwargs: dict = {
        "mode":                 "subscription",
        "line_items":           [],
        "success_url":          success_url,
        "cancel_url":           cancel_url,
        "allow_promotion_codes": True,
        "subscription_data": {
            "metadata": {
                "algoedge_tier":  req.tier,
                "billing_cycle":  req.cycle,
            }
        },
        "metadata": {
            "algoedge_tier": req.tier,
            "billing_cycle": req.cycle,
        },
    }

    if price_id:
        session_kwargs["line_items"] = [{"price": price_id, "quantity": 1}]
    else:
        # Products not seeded yet — use price_data (dev/demo fallback)
        tier_meta  = TIERS[req.tier]
        amount_key = "amount_annual" if req.cycle == "annual" else "amount_4w"
        session_kwargs["line_items"] = [{
            "price_data": {
                "currency":   "usd",
                "unit_amount": tier_meta[amount_key],
                "product_data": {
                    "name": f"AlgoEdge {tier_meta['name']} ({req.cycle})",
                    "metadata": {
                        "algoedge_tier":  req.tier,
                        "billing_cycle":  req.cycle,
                    },
                },
                "recurring": {
                    "interval":       "day",
                    "interval_count": 28 if req.cycle == "4w" else 365,
                },
            },
            "quantity": 1,
        }]

    if req.email:
        # Try to reuse an existing customer to enable proration on upgrades
        try:
            existing = _stripe_lib.Customer.list(email=req.email, limit=1)
            if existing.data:
                session_kwargs["customer"] = existing.data[0].id
            else:
                session_kwargs["customer_email"] = req.email
        except Exception:
            session_kwargs["customer_email"] = req.email

    try:
        session = _stripe_lib.checkout.Session.create(**session_kwargs)
        return {"url": session.url, "session_id": session.id}
    except _stripe_lib.error.StripeError as exc:
        raise HTTPException(400, str(exc))


@stripe_bp.post("/stripe/portal")
async def stripe_portal(req: PortalRequest, request: Request) -> dict:
    """
    Create a Stripe Billing Portal session so users can manage/cancel subscriptions.
    """
    if not _STRIPE_OK or not STRIPE_SECRET_KEY:
        raise HTTPException(503, "Stripe is not configured")

    try:
        customers = _stripe_lib.Customer.list(email=req.customer_email, limit=1)
        if not customers.data:
            raise HTTPException(404, "No Stripe customer found for this email")
        customer_id = customers.data[0].id
    except _stripe_lib.error.StripeError as exc:
        raise HTTPException(400, str(exc))

    origin     = request.headers.get("origin") or "https://algoedge.app"
    return_url = req.return_url or f"{origin}/saas/settings"

    session = _stripe_lib.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return {"url": session.url}


@stripe_bp.post("/stripe/webhook")
async def stripe_webhook(request: Request, response: Response) -> dict:
    """
    Receive Stripe webhook events and provision/deprovision user access.

    Handled events:
      checkout.session.completed        → activate tier
      customer.subscription.updated     → update tier / billing_cycle_end
      customer.subscription.deleted     → revoke tier

    Requires raw body for signature verification — FastAPI delivers it via
    request.body() before any JSON parsing.
    """
    payload   = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not STRIPE_WEBHOOK_SECRET:
        # In dev mode without a webhook secret, accept all events (not for production)
        try:
            event = _stripe_lib.Event.construct_from(
                await request.json(), _stripe_lib.api_key
            )
        except Exception:
            raise HTTPException(400, "Invalid event payload")
    else:
        try:
            event = _stripe_lib.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
        except _stripe_lib.error.SignatureVerificationError:
            raise HTTPException(400, "Invalid webhook signature")

    event_type = event["type"]
    data_obj   = event["data"]["object"]

    # ── checkout.session.completed ─────────────────────────────────────────
    if event_type == "checkout.session.completed":
        customer_id     = data_obj.get("customer")
        subscription_id = data_obj.get("subscription")
        tier            = data_obj.get("metadata", {}).get("algoedge_tier")

        if customer_id and subscription_id and tier:
            try:
                sub = _stripe_lib.Subscription.retrieve(subscription_id)
                end_ts = sub.get("current_period_end")
                billing_end = (
                    datetime.fromtimestamp(end_ts, tz=timezone.utc) if end_ts else None
                )
            except Exception:
                billing_end = None

            _upsert_user_tier(customer_id, subscription_id, tier, billing_end)
            print(f"[stripe-webhook] checkout.session.completed → {tier} for cus:{customer_id}")

    # ── customer.subscription.updated ─────────────────────────────────────
    elif event_type == "customer.subscription.updated":
        customer_id     = data_obj.get("customer")
        subscription_id = data_obj.get("id")
        status          = data_obj.get("status")
        tier            = data_obj.get("metadata", {}).get("algoedge_tier")

        if customer_id and subscription_id:
            end_ts      = data_obj.get("current_period_end")
            billing_end = (
                datetime.fromtimestamp(end_ts, tz=timezone.utc) if end_ts else None
            )
            # Revoke access if subscription is not active
            active_tier = tier if status in ("active", "trialing") else None
            _upsert_user_tier(customer_id, subscription_id, active_tier, billing_end)
            print(f"[stripe-webhook] subscription.updated → {active_tier} status={status}")

    # ── customer.subscription.deleted ─────────────────────────────────────
    elif event_type == "customer.subscription.deleted":
        customer_id     = data_obj.get("customer")
        subscription_id = data_obj.get("id")
        if customer_id:
            _upsert_user_tier(customer_id, subscription_id or "", None, None)
            print(f"[stripe-webhook] subscription.deleted → tier revoked for cus:{customer_id}")

    return {"received": True, "type": event_type}
