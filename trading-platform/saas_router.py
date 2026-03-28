"""
saas_router.py  —  Public SaaS Platform API
=============================================
This is the dedicated backend router for System B: the public-facing SaaS
platform (AlgoEdge). All routes here are served under the /saas-api prefix.

This is completely isolated from the private trading dashboard routes which
live under /trading-api in main.py. They share the same FastAPI process
(and therefore the same trading logic engine) but have fully separate
route namespaces and, eventually, separate authentication middleware.

Route map (Stage 2):
  GET  /saas-api/health             — Liveness probe
  GET  /saas-api/config             — Public runtime config (DEV_MODE flag, version)
  POST /saas-api/dev-mode/toggle    — Flip DEV_MODE at runtime (dev convenience only)

Future stages will add:
  POST /saas-api/auth/signup        — User registration
  POST /saas-api/auth/login         — User login / session
  GET  /saas-api/insights           — Factual Insight Cards (RSI math, probability data)
  POST /saas-api/trade/execute      — 1-click trade execution (Stage 5)
  GET/POST /saas-api/settings/keys  — User API key management
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel


# ── Configuration ─────────────────────────────────────────────────────────────

# Stage 3 will build full auth. For now this flag bypasses it entirely
# so development is frictionless. Set to False before going to production.
DEV_MODE: bool = True

SAAS_VERSION: str = "0.1.0"
SAAS_API_PREFIX: str = "/saas-api"


# ── Router ────────────────────────────────────────────────────────────────────

saas_router = APIRouter(prefix=SAAS_API_PREFIX, tags=["SaaS Platform"])


# ── Response models ───────────────────────────────────────────────────────────

class SaasHealthResponse(BaseModel):
    status: str
    version: str
    timestamp: str
    dev_mode: bool


class SaasConfigResponse(BaseModel):
    version: str
    dev_mode: bool
    auth_required: bool
    supported_exchanges: list[str]
    risk_model: str


class SaasUserResponse(BaseModel):
    id: str
    name: str
    email: str
    role: str          # "developer" | "user" | "admin"
    dev_mode: bool     # flag so the frontend knows this is a mock session


# ── Mock dev user ──────────────────────────────────────────────────────────────
# Used when DEV_MODE=True so the frontend has a fully-populated user object
# without implementing real auth. Stage 4/5 will add real login + sessions.

DEV_USER: dict = {
    "id":       "dev-local-001",
    "name":     "Dev User",
    "email":    "dev@local",
    "role":     "developer",
    "dev_mode": True,
}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@saas_router.get("/auth/me", response_model=SaasUserResponse)
async def auth_me() -> dict:
    """
    Returns the current authenticated user.

    DEV_MODE=True  → returns the mock Dev User (200) — auth bypass active.
    DEV_MODE=False → raises 401; frontend renders the LoginGate.

    Stage 4 replaces this with real session/JWT validation.
    """
    from fastapi import HTTPException
    if DEV_MODE:
        return DEV_USER
    raise HTTPException(status_code=401, detail="Not authenticated. Enable dev mode or sign in.")


@saas_router.post("/dev-mode/toggle", response_model=SaasConfigResponse)
async def toggle_dev_mode() -> dict:
    """
    Toggle DEV_MODE at runtime.

    Intended for developer use only — allows switching between 'auth bypassed'
    and 'auth required' states without restarting the server.

    NOTE: This mutates module-level state. In a multi-worker production deploy
    the toggle only affects the worker that handles the request. This is fine
    since DEV_MODE should always be False in production (set at startup).
    """
    global DEV_MODE
    DEV_MODE = not DEV_MODE
    return {
        "version":             SAAS_VERSION,
        "dev_mode":            DEV_MODE,
        "auth_required":       not DEV_MODE,
        "supported_exchanges": ["kraken", "alpaca"],
        "risk_model":          "15_pct_equity_per_signal",
    }


@saas_router.get("/health", response_model=SaasHealthResponse)
async def saas_health() -> dict:
    """
    Liveness probe for the public SaaS API.
    Also exposes the DEV_MODE flag so the frontend can adjust its behaviour.
    """
    return {
        "status":    "online",
        "version":   SAAS_VERSION,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "dev_mode":  DEV_MODE,
    }


@saas_router.get("/config", response_model=SaasConfigResponse)
async def saas_config() -> dict:
    """
    Public runtime configuration consumed by the SaaS frontend on startup.

    dev_mode:           True  → auth is bypassed; mock 'Dev User' session active
    auth_required:      Inverse of dev_mode — when True, login/signup gates access
    supported_exchanges: Exchanges users can connect their API keys for
    risk_model:         The equity-allocation rule applied to all 1-click trades
    """
    return {
        "version":             SAAS_VERSION,
        "dev_mode":            DEV_MODE,
        "auth_required":       not DEV_MODE,
        "supported_exchanges": ["kraken", "alpaca"],
        "risk_model":          "15_pct_equity_per_signal",
    }
