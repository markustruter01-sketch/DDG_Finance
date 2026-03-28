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

@saas_router.get("/insights")
async def saas_insights() -> dict:
    """
    Live insight data for the public SaaS dashboard.

    Reads from kraken-bot/paper_portfolio.json (always-fresh, written every cycle)
    and the shared sentiment cache. All data is public — no trading-private info.

    Returns:
      portfolio   — equity, cash, deployed %, position count
      symbols     — 10-symbol universe with held/watching status + entry data
      sentiment   — crypto + market Fear & Greed index
      cycle_count — how many bot cycles have run (data freshness proxy)
    """
    import json as _json
    import os as _os

    # ── Paper portfolio ───────────────────────────────────────────────────────
    _pp_path = _os.path.join(
        _os.path.dirname(__file__), "..", "kraken-bot", "paper_portfolio.json"
    )
    try:
        with open(_pp_path) as _f:
            pp = _json.load(_f)
    except Exception:
        pp = {"cash_usd": 0.0, "positions": {}, "all_trades": [], "starting_balance_usd": 100_000}

    positions: dict = pp.get("positions", {})
    cash: float     = pp.get("cash_usd", 0.0)
    start_bal: float = pp.get("starting_balance_usd", 100_000)
    deployed: float  = sum(p.get("size_usd", 0) for p in positions.values())
    equity: float    = cash + deployed
    cycle_count: int = len(pp.get("all_trades", [])) // max(len(positions) or 1, 1)

    # ── Symbol universe ───────────────────────────────────────────────────────
    _UNIVERSE = [
        ("BTC/USD", "Bitcoin"),   ("ETH/USD", "Ethereum"),
        ("SOL/USD", "Solana"),    ("XRP/USD", "Ripple"),
        ("ADA/USD", "Cardano"),   ("AVAX/USD", "Avalanche"),
        ("LINK/USD", "Chainlink"),("DOT/USD", "Polkadot"),
        ("ATOM/USD", "Cosmos"),   ("LTC/USD", "Litecoin"),
    ]
    symbol_rows = []
    for sym, label in _UNIVERSE:
        if sym in positions:
            p = positions[sym]
            symbol_rows.append({
                "symbol":    sym,
                "base":      sym.split("/")[0],
                "label":     label,
                "status":    "held",
                "side":      p.get("side", "long"),
                "entry_price": p.get("entry_price"),
                "size_usd":  p.get("size_usd"),
                "entry_time": p.get("entry_time"),
            })
        else:
            symbol_rows.append({
                "symbol":    sym,
                "base":      sym.split("/")[0],
                "label":     label,
                "status":    "watching",
                "side":      None,
                "entry_price": None,
                "size_usd":  None,
                "entry_time": None,
            })

    # ── Sentiment (uses shared cache — very cheap) ────────────────────────────
    try:
        from data.sentiment import get_sentiment as _get_sent
        sent = _get_sent()
        cfg = sent.get("crypto_fear_greed", {})
        mfg = sent.get("market_fear_greed", {})
        crypto_val   = cfg.get("value", 50)
        crypto_label = cfg.get("label", "Neutral")
        market_val   = mfg.get("value", 50)
        market_label = mfg.get("label", "Neutral")
    except Exception:
        crypto_val, crypto_label = 50, "Neutral"
        market_val, market_label = 50, "Neutral"

    total_pnl_pct = round((equity - start_bal) / start_bal * 100, 2) if start_bal else 0

    return {
        "portfolio": {
            "equity":          round(equity, 2),
            "cash":            round(cash, 2),
            "deployed":        round(deployed, 2),
            "positions_count": len(positions),
            "deployed_pct":    round(deployed / equity * 100, 1) if equity > 0 else 0,
            "total_pnl_pct":   total_pnl_pct,
            "starting_balance": start_bal,
        },
        "symbols":  symbol_rows,
        "sentiment": {
            "crypto": {"value": crypto_val, "label": crypto_label},
            "market": {"value": market_val, "label": market_label},
        },
        "cycle_count":  cycle_count,
        "last_updated": datetime.now(tz=timezone.utc).isoformat(),
    }


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


# ══════════════════════════════════════════════════════════════════════════════
# Stage 5 — 1-Click Execution Middleware
# ══════════════════════════════════════════════════════════════════════════════
#
# Two execution modes:
#   PAPER — writes to saas_paper_portfolio.json (no real money, default)
#   LIVE  — executes on the user's real Kraken account via ccxt
#
# API key handling:
#   Keys are sent in the request body (HTTPS transport only).
#   Never stored server-side in the current build; Stage 6+ adds encrypted
#   per-user key vaults in PostgreSQL.
#
# ══════════════════════════════════════════════════════════════════════════════

import json as _json_trade
import os as _os_trade
import asyncio as _asyncio

_SAAS_PAPER_PATH = _os_trade.path.join(
    _os_trade.path.dirname(__file__), "..", "kraken-bot", "saas_paper_portfolio.json"
)
_SAAS_STARTING_BALANCE = 10_000.0   # $10K demo paper capital


# ── Paper portfolio helpers ────────────────────────────────────────────────────

def _load_saas_paper() -> dict:
    try:
        with open(_SAAS_PAPER_PATH) as f:
            return _json_trade.load(f)
    except Exception:
        return {
            "cash_usd":            _SAAS_STARTING_BALANCE,
            "starting_balance_usd": _SAAS_STARTING_BALANCE,
            "positions":           {},
            "trades":              [],
        }


def _save_saas_paper(portfolio: dict) -> None:
    with open(_SAAS_PAPER_PATH, "w") as f:
        _json_trade.dump(portfolio, f, indent=2, default=str)


def _fetch_price(symbol: str) -> float:
    """Fetch last price from Kraken public REST (no auth needed)."""
    import ccxt
    ex = ccxt.kraken()
    ticker = ex.fetch_ticker(symbol)
    return float(ticker["last"])


# ── Pydantic request models ────────────────────────────────────────────────────

class TradeExecuteRequest(BaseModel):
    symbol:     str             # e.g. "BTC/USD"
    side:       str             # "long" or "short"
    size_pct:   float = 10.0   # % of SaaS paper equity to deploy
    use_live:   bool  = False   # when True + keys provided → real Kraken trade
    api_key:    str | None = None
    api_secret: str | None = None


class TradeCloseRequest(BaseModel):
    symbol:     str
    use_live:   bool  = False
    api_key:    str | None = None
    api_secret: str | None = None


# ── Paper execution helpers ────────────────────────────────────────────────────

def _paper_execute(req: TradeExecuteRequest) -> dict:
    try:
        price = _fetch_price(req.symbol)
    except Exception as e:
        return {"status": "error", "message": f"Price fetch failed: {e}"}

    pp       = _load_saas_paper()
    cash     = float(pp.get("cash_usd", 0))
    positions: dict = pp.get("positions", {})
    deployed = sum(float(p.get("size_usd", 0)) for p in positions.values())
    equity   = cash + deployed

    if req.symbol in positions:
        return {"status": "error", "message": f"Position already open for {req.symbol}. Close it first."}

    size_usd = equity * (min(max(req.size_pct, 1), 25) / 100)
    if size_usd > cash:
        size_usd = cash          # use all available cash
    if size_usd < 5:
        return {"status": "error", "message": "Insufficient cash. Minimum position is $5."}

    fee         = round(size_usd * 0.0026, 4)   # Kraken taker ~0.26%
    size_units  = size_usd / price

    positions[req.symbol] = {
        "side":        req.side,
        "entry_price": round(price, 6),
        "size_usd":    round(size_usd, 2),
        "size_units":  round(size_units, 8),
        "entry_time":  datetime.now(tz=timezone.utc).isoformat(),
        "entry_fee":   fee,
    }
    pp["cash_usd"]  = round(cash - size_usd - fee, 2)
    pp["positions"] = positions
    pp.setdefault("trades", []).append({
        "action":   "open",
        "symbol":   req.symbol,
        "side":     req.side,
        "size_usd": round(size_usd, 2),
        "price":    round(price, 6),
        "fee":      fee,
        "time":     datetime.now(tz=timezone.utc).isoformat(),
    })
    _save_saas_paper(pp)

    return {
        "status":         "executed",
        "mode":           "paper",
        "symbol":         req.symbol,
        "side":           req.side,
        "size_usd":       round(size_usd, 2),
        "fill_price":     round(price, 6),
        "fee":            fee,
        "cash_remaining": pp["cash_usd"],
    }


def _paper_close(req: TradeCloseRequest) -> dict:
    try:
        price = _fetch_price(req.symbol)
    except Exception as e:
        return {"status": "error", "message": f"Price fetch failed: {e}"}

    pp        = _load_saas_paper()
    positions: dict = pp.get("positions", {})

    if req.symbol not in positions:
        return {"status": "error", "message": f"No open position for {req.symbol}."}

    pos        = positions[req.symbol]
    entry_p    = float(pos["entry_price"])
    size_units = float(pos["size_units"])
    orig_usd   = float(pos["size_usd"])
    side       = pos.get("side", "long")

    close_val = size_units * price
    fee       = round(close_val * 0.0026, 4)

    if side == "long":
        pnl = round((price - entry_p) / entry_p * orig_usd, 2)
    else:
        pnl = round((entry_p - price) / entry_p * orig_usd, 2)

    del positions[req.symbol]
    pp["cash_usd"]  = round(float(pp.get("cash_usd", 0)) + close_val - fee, 2)
    pp["positions"] = positions
    pp.setdefault("trades", []).append({
        "action":     "close",
        "symbol":     req.symbol,
        "pnl":        pnl,
        "exit_price": round(price, 6),
        "fee":        fee,
        "time":       datetime.now(tz=timezone.utc).isoformat(),
    })
    _save_saas_paper(pp)

    return {
        "status":     "closed",
        "mode":       "paper",
        "symbol":     req.symbol,
        "pnl":        pnl,
        "fill_price": round(price, 6),
        "fee":        fee,
        "cash_now":   pp["cash_usd"],
    }


# ── Live execution helpers (user's own Kraken account) ────────────────────────

async def _live_execute(req: TradeExecuteRequest) -> dict:
    def _run() -> dict:
        import ccxt
        try:
            ex       = ccxt.kraken({"apiKey": req.api_key, "secret": req.api_secret})
            balance  = ex.fetch_balance()
            usd_free = float(balance.get("USD", {}).get("free", 0))
            ticker   = ex.fetch_ticker(req.symbol)
            price    = float(ticker["last"])
            size_usd = min(usd_free * (min(max(req.size_pct, 1), 25) / 100), usd_free)
            amount   = size_usd / price

            if req.side == "long":
                order = ex.create_market_buy_order(req.symbol, amount)
            else:
                order = ex.create_market_sell_order(req.symbol, amount, params={"leverage": 2})

            return {
                "status":     "executed",
                "mode":       "live",
                "symbol":     req.symbol,
                "side":       req.side,
                "order_id":   order.get("id"),
                "fill_price": order.get("average") or round(price, 6),
                "size_usd":   round(size_usd, 2),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    return await _asyncio.to_thread(_run)


async def _live_close(req: TradeCloseRequest) -> dict:
    def _run() -> dict:
        import ccxt
        try:
            ex   = ccxt.kraken({"apiKey": req.api_key, "secret": req.api_secret})
            base = req.symbol.split("/")[0]
            bal  = ex.fetch_balance()
            amt  = float(bal.get(base, {}).get("free", 0))
            if amt <= 0:
                return {"status": "error", "message": f"No {base} balance to close."}
            order = ex.create_market_sell_order(req.symbol, amt)
            return {
                "status":     "closed",
                "mode":       "live",
                "symbol":     req.symbol,
                "order_id":   order.get("id"),
                "fill_price": order.get("average"),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    return await _asyncio.to_thread(_run)


# ── Trade endpoints ────────────────────────────────────────────────────────────

@saas_router.get("/trade/portfolio")
async def saas_trade_portfolio() -> dict:
    """Returns the user's SaaS paper portfolio (separate from the bot's portfolio)."""
    pp        = _load_saas_paper()
    positions: dict = pp.get("positions", {})
    cash      = float(pp.get("cash_usd", 0))
    start     = float(pp.get("starting_balance_usd", _SAAS_STARTING_BALANCE))
    deployed  = sum(float(p.get("size_usd", 0)) for p in positions.values())
    equity    = cash + deployed
    pnl_pct   = round((equity - start) / start * 100, 2) if start else 0

    return {
        "equity":           round(equity, 2),
        "cash":             round(cash, 2),
        "deployed":         round(deployed, 2),
        "starting_balance": start,
        "pnl_pct":          pnl_pct,
        "positions":        positions,
        "positions_count":  len(positions),
        "recent_trades":    list(reversed(pp.get("trades", [])))[:10],
    }


@saas_router.post("/trade/execute")
async def saas_trade_execute(req: TradeExecuteRequest) -> dict:
    """
    1-Click trade execution.

    use_live=False (default) → paper trade against SaaS demo portfolio ($10K).
    use_live=True + api_key + api_secret → real Kraken trade on user's account.
    """
    if req.side not in ("long", "short"):
        return {"status": "error", "message": "side must be 'long' or 'short'."}
    if req.use_live and req.api_key and req.api_secret:
        return await _live_execute(req)
    return await _asyncio.to_thread(_paper_execute, req)


@saas_router.post("/trade/close")
async def saas_trade_close(req: TradeCloseRequest) -> dict:
    """Close an open position (paper or live)."""
    if req.use_live and req.api_key and req.api_secret:
        return await _live_close(req)
    return await _asyncio.to_thread(_paper_close, req)
