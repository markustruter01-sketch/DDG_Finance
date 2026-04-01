"""
options_engine.py — The Apex Predator: Pure Quant Options Engine (Bot #5)
=========================================================================
A 100% LLM-free options trading bot that exploits Implied Volatility
compression and technical breakouts using hard-coded math.

Strategy: Volatility Squeeze → Long Straddle
  1. Scan highly liquid options chains (SPY, QQQ, NVDA, TSLA)
  2. Calculate Implied Volatility Rank (IVR) — must be < 20
  3. Detect Bollinger Band Squeeze — 20-day bandwidth at 6-month low
  4. When BOTH conditions met → construct Long Straddle (ATM Call + ATM Put, 30-45 DTE)
  5. Size via Half-Kelly Criterion

Capital Fence: 5% of total global account equity.
Execution Window: 3:30 PM EST daily.
Paper Trading: Simulated execution with real market data.
"""

import os
import sys
import json
import math
import time
import sqlite3
import threading
from datetime import datetime, timedelta, date, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from loguru import logger

_REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from config.settings import settings
from execution.resilience import alpaca_retry

from alpaca.trading.client import TradingClient
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, OptionChainRequest, OptionSnapshotRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

WATCHLIST = [
    "SPY", "QQQ", "IWM", "DIA",
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO",
    "AMD", "NFLX", "CRM", "ORCL", "ADBE", "INTC", "MU", "QCOM",
    "CSCO", "TXN", "AMAT", "LRCX", "KLAC", "MRVL", "SNPS", "CDNS",
    "ARM", "PLTR", "COIN", "SHOP", "SNOW", "CRWD", "DDOG", "NET",
    "PANW", "ZS", "FTNT", "UBER", "ABNB", "DASH", "RBLX", "SPOT",
    "JPM", "BAC", "GS", "MS", "C", "WFC", "SCHW", "BLK",
    "V", "MA", "AXP", "PYPL",
    "JNJ", "UNH", "LLY", "PFE", "ABBV", "MRK", "TMO", "ABT",
    "AMGN", "GILD", "MRNA", "BIIB", "REGN", "VRTX", "ISRG", "MDT",
    "XOM", "CVX", "COP", "SLB", "OXY", "EOG", "MPC", "PSX",
    "FSLR", "ENPH",
    "BA", "CAT", "DE", "GE", "HON", "RTX", "LMT", "MMM",
    "WMT", "COST", "HD", "LOW", "TGT", "NKE", "SBUX", "MCD",
    "DIS", "CMCSA", "T", "VZ",
    "GLD", "SLV", "USO", "TLT",
]
CAPITAL_FENCE_PCT = 0.05
IVR_THRESHOLD = 20
BB_PERIOD = 20
BB_STD = 2.0
BB_LOOKBACK_DAYS = 126
TARGET_DTE_MIN = 30
TARGET_DTE_MAX = 45
MIN_TRADES_FOR_KELLY = 10
DEFAULT_RISK_PCT = 0.01
EXECUTION_HOUR_ET = 15
EXECUTION_MINUTE_ET = 30

MAX_LOSS_PCT = 0.50
PROFIT_TARGET_PCT = 1.00
MIN_DTE_EXIT = 7

PAPER_MODE = True
PAPER_CAPITAL = 100_000.00

CB_LOSS_THRESHOLD = 0.30

STATE_DIR = Path(__file__).parent / "_options_state"
STATE_DIR.mkdir(exist_ok=True)
STATE_FILE = STATE_DIR / "state.json"
POSITIONS_FILE = STATE_DIR / "positions.json"
PENDING_FILE = STATE_DIR / "pending.json"
TRADES_DB = STATE_DIR / "trades.db"

_lock = threading.Lock()

_trading_client: TradingClient | None = None
_option_data_client: OptionHistoricalDataClient | None = None
_stock_data_client: StockHistoricalDataClient | None = None


def _get_trading_client() -> TradingClient:
    global _trading_client
    if _trading_client is None:
        _trading_client = TradingClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
            paper=True,
        )
    return _trading_client


def _get_option_client() -> OptionHistoricalDataClient:
    global _option_data_client
    if _option_data_client is None:
        _option_data_client = OptionHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
        )
    return _option_data_client


def _get_stock_client() -> StockHistoricalDataClient:
    global _stock_data_client
    if _stock_data_client is None:
        _stock_data_client = StockHistoricalDataClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
        )
    return _stock_data_client


def _init_trades_db():
    conn = sqlite3.connect(str(TRADES_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS options_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            strategy TEXT NOT NULL,
            entry_date TEXT NOT NULL,
            exit_date TEXT,
            call_symbol TEXT,
            put_symbol TEXT,
            call_strike REAL,
            put_strike REAL,
            expiry TEXT,
            total_premium REAL NOT NULL,
            exit_value REAL,
            pnl REAL,
            pnl_pct REAL,
            status TEXT DEFAULT 'open',
            entry_ivr REAL,
            entry_bandwidth REAL,
            exit_reason TEXT
        )
    """)
    conn.commit()
    conn.close()


_init_trades_db()

try:
    _conn = sqlite3.connect(str(TRADES_DB))
    _cols = [r[1] for r in _conn.execute("PRAGMA table_info(options_trades)").fetchall()]
    if "exit_reason" not in _cols:
        _conn.execute("ALTER TABLE options_trades ADD COLUMN exit_reason TEXT")
        _conn.commit()
        logger.info("Options | Migrated options_trades: added exit_reason column")
    _conn.close()
except Exception as _mig_err:
    logger.warning(f"Options | Schema migration failed: {_mig_err}")


def _load_json(path: Path, default=None):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return default if default is not None else {}


def _save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, default=str))


def _get_state() -> dict:
    default = {
        "status": "idle",
        "paused": False,
        "last_scan": None,
        "last_scan_results": [],
        "capital_fence_pct": CAPITAL_FENCE_PCT,
        "fenced_capital": 0.0,
        "total_equity": 0.0,
        "paper_mode": PAPER_MODE,
        "paper_equity": PAPER_CAPITAL if PAPER_MODE else 0.0,
        "cycle_count": 0,
        "total_trades": 0,
        "total_wins": 0,
        "total_pnl": 0.0,
        "error": None,
        "circuit_breaker_active": False,
        "circuit_breaker_reason": None,
        "circuit_breaker_tripped_at": None,
        "circuit_breaker_resets_at": None,
    }
    return _load_json(STATE_FILE, default)


def _save_state(state: dict):
    _save_json(STATE_FILE, state)


def _get_positions() -> list:
    return _load_json(POSITIONS_FILE, [])


def _save_positions(positions: list):
    _save_json(POSITIONS_FILE, positions)


def _get_pending() -> list:
    return _load_json(PENDING_FILE, [])


def _save_pending(pending: list):
    _save_json(PENDING_FILE, pending)


@alpaca_retry
def _fetch_account_equity() -> float:
    if PAPER_MODE:
        state = _load_json(STATE_FILE, {})
        equity = state.get("paper_equity", PAPER_CAPITAL)
        return float(equity)
    acct = _get_trading_client().get_account()
    return float(acct.equity)


def _submit_option_order(option_symbol: str, qty: int, side: OrderSide) -> dict | None:
    if PAPER_MODE:
        logger.info(f"Options | PAPER ORDER: {side.name} {qty}x {option_symbol}")
        return {"paper": True, "symbol": option_symbol, "qty": qty, "side": side.name}
    try:
        client = _get_trading_client()
        order_req = MarketOrderRequest(
            symbol=option_symbol,
            qty=qty,
            side=side,
            time_in_force=TimeInForce.DAY,
        )
        order = client.submit_order(order_req)
        logger.info(f"Options | LIVE ORDER submitted: {side.name} {qty}x {option_symbol} → {order.id}")
        return {
            "order_id": str(order.id),
            "symbol": option_symbol,
            "qty": qty,
            "side": side.name,
            "status": str(order.status),
        }
    except Exception as e:
        logger.error(f"Options | ORDER FAILED: {side.name} {qty}x {option_symbol}: {e}")
        return None


@alpaca_retry
def _fetch_stock_bars(symbol: str, days: int) -> list[dict]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=int(days * 1.5))
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        feed="iex",
    )
    bars = _get_stock_client().get_stock_bars(request)
    result = []
    for bar in bars[symbol]:
        result.append({
            "timestamp": str(bar.timestamp),
            "close": float(bar.close),
            "high": float(bar.high),
            "low": float(bar.low),
            "volume": float(bar.volume),
        })
    return result[-days:] if len(result) > days else result


def _compute_bollinger_bandwidth(closes: list[float], period: int = BB_PERIOD, std_mult: float = BB_STD) -> list[float]:
    if len(closes) < period:
        return []
    bandwidths = []
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1: i + 1]
        sma = np.mean(window)
        std = np.std(window, ddof=1)
        upper = sma + std_mult * std
        lower = sma - std_mult * std
        bw = ((upper - lower) / sma) * 100 if sma > 0 else 0
        bandwidths.append(bw)
    return bandwidths


def _is_bollinger_squeeze(closes: list[float]) -> tuple[bool, float, float]:
    if len(closes) < BB_LOOKBACK_DAYS:
        return False, 0.0, 0.0

    bandwidths = _compute_bollinger_bandwidth(closes)
    if len(bandwidths) < 2:
        return False, 0.0, 0.0

    current_bw = bandwidths[-1]
    min_bw_6m = min(bandwidths) if bandwidths else current_bw

    is_squeeze = current_bw <= min_bw_6m * 1.05
    return is_squeeze, current_bw, min_bw_6m


@alpaca_retry
def _fetch_option_chain(symbol: str) -> list[dict]:
    try:
        request = OptionChainRequest(
            underlying_symbol=symbol,
        )
        snapshots = _get_option_client().get_option_chain(request)

        results = []
        for contract_symbol, snapshot in snapshots.items():
            greeks = snapshot.greeks if hasattr(snapshot, 'greeks') and snapshot.greeks else None
            quote = snapshot.latest_quote if hasattr(snapshot, 'latest_quote') else None
            trade = snapshot.latest_trade if hasattr(snapshot, 'latest_trade') else None
            results.append({
                "symbol": contract_symbol,
                "iv": float(snapshot.implied_volatility) if hasattr(snapshot, 'implied_volatility') and snapshot.implied_volatility else None,
                "delta": float(greeks.delta) if greeks and hasattr(greeks, 'delta') and greeks.delta is not None else None,
                "gamma": float(greeks.gamma) if greeks and hasattr(greeks, 'gamma') and greeks.gamma is not None else None,
                "theta": float(greeks.theta) if greeks and hasattr(greeks, 'theta') and greeks.theta is not None else None,
                "vega": float(greeks.vega) if greeks and hasattr(greeks, 'vega') and greeks.vega is not None else None,
                "bid": float(quote.bid_price) if quote and hasattr(quote, 'bid_price') and quote.bid_price else 0,
                "ask": float(quote.ask_price) if quote and hasattr(quote, 'ask_price') and quote.ask_price else 0,
                "last_price": float(trade.price) if trade and hasattr(trade, 'price') and trade.price else 0,
                "volume": int(trade.size) if trade and hasattr(trade, 'size') and trade.size else 0,
                "open_interest": int(snapshot.open_interest) if hasattr(snapshot, 'open_interest') and snapshot.open_interest else 0,
            })
        return results
    except Exception as e:
        logger.warning(f"Options | Failed to fetch chain for {symbol}: {e}")
        return []


def _parse_option_symbol(symbol: str) -> dict:
    try:
        parts = symbol
        underlying_end = 0
        for i, c in enumerate(parts):
            if c.isdigit():
                underlying_end = i
                break
        underlying = parts[:underlying_end]
        rest = parts[underlying_end:]
        date_str = rest[:6]
        option_type = rest[6]
        strike_str = rest[7:]
        strike = float(strike_str) / 1000
        expiry = datetime.strptime(date_str, "%y%m%d").date()
        return {
            "underlying": underlying,
            "expiry": expiry,
            "type": "call" if option_type == "C" else "put",
            "strike": strike,
        }
    except Exception:
        return {"underlying": "", "expiry": date.today(), "type": "unknown", "strike": 0}


def _compute_ivr(chain: list[dict]) -> float:
    ivs = [c["iv"] for c in chain if c["iv"] is not None and c["iv"] > 0]
    if len(ivs) < 10:
        return 50.0

    current_iv = np.median(ivs)
    iv_min = np.percentile(ivs, 5)
    iv_max = np.percentile(ivs, 95)

    if iv_max - iv_min < 0.001:
        return 50.0

    ivr = ((current_iv - iv_min) / (iv_max - iv_min)) * 100
    return max(0, min(100, ivr))


def _find_atm_straddle(chain: list[dict], spot_price: float, min_dte: int = TARGET_DTE_MIN, max_dte: int = TARGET_DTE_MAX) -> Optional[dict]:
    today = date.today()
    calls = []
    puts = []

    for contract in chain:
        parsed = _parse_option_symbol(contract["symbol"])
        dte = (parsed["expiry"] - today).days
        if dte < min_dte or dte > max_dte:
            continue

        mid_price = (contract["bid"] + contract["ask"]) / 2 if contract["bid"] > 0 and contract["ask"] > 0 else contract["last_price"]
        if mid_price <= 0:
            continue

        entry = {
            **contract,
            **parsed,
            "dte": dte,
            "mid_price": mid_price,
            "distance": abs(parsed["strike"] - spot_price),
        }

        if parsed["type"] == "call":
            calls.append(entry)
        elif parsed["type"] == "put":
            puts.append(entry)

    if not calls or not puts:
        return None

    calls.sort(key=lambda x: (x["distance"], x["dte"]))
    puts.sort(key=lambda x: (x["distance"], x["dte"]))

    best_call = calls[0]

    matching_puts = [p for p in puts if p["expiry"] == best_call["expiry"] and abs(p["strike"] - best_call["strike"]) < 0.01]
    if not matching_puts:
        matching_puts = [p for p in puts if p["expiry"] == best_call["expiry"]]
        if not matching_puts:
            return None
        matching_puts.sort(key=lambda x: x["distance"])

    best_put = matching_puts[0]

    total_premium = best_call["mid_price"] + best_put["mid_price"]

    return {
        "call": {
            "symbol": best_call["symbol"],
            "strike": best_call["strike"],
            "expiry": str(best_call["expiry"]),
            "dte": best_call["dte"],
            "mid_price": best_call["mid_price"],
            "iv": best_call["iv"],
            "delta": best_call["delta"],
            "gamma": best_call["gamma"],
            "theta": best_call["theta"],
            "vega": best_call["vega"],
            "bid": best_call["bid"],
            "ask": best_call["ask"],
        },
        "put": {
            "symbol": best_put["symbol"],
            "strike": best_put["strike"],
            "expiry": str(best_put["expiry"]),
            "dte": best_put["dte"],
            "mid_price": best_put["mid_price"],
            "iv": best_put["iv"],
            "delta": best_put["delta"],
            "gamma": best_put["gamma"],
            "theta": best_put["theta"],
            "vega": best_put["vega"],
            "bid": best_put["bid"],
            "ask": best_put["ask"],
        },
        "total_premium_per_contract": total_premium,
        "premium_usd": total_premium * 100,
    }


def _get_historical_stats() -> tuple[float, float]:
    conn = sqlite3.connect(str(TRADES_DB))
    rows = conn.execute(
        "SELECT pnl FROM options_trades WHERE status = 'closed' AND pnl IS NOT NULL"
    ).fetchall()
    conn.close()

    if len(rows) < MIN_TRADES_FOR_KELLY:
        return 0.5, 1.0

    pnls = [r[0] for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [abs(p) for p in pnls if p < 0]

    win_rate = len(wins) / len(pnls) if pnls else 0.5
    avg_win = np.mean(wins) if wins else 1.0
    avg_loss = np.mean(losses) if losses else 1.0
    win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 1.0

    return win_rate, win_loss_ratio


def _half_kelly(win_rate: float, win_loss_ratio: float) -> float:
    b = win_loss_ratio
    p = win_rate
    kelly = (p * (b + 1) - 1) / b if b > 0 else 0
    half_kelly = kelly / 2
    return max(0.0, min(half_kelly, 0.25))


def _compute_position_size(fenced_capital: float, premium_per_contract_usd: float) -> tuple[int, float]:
    if premium_per_contract_usd <= 0 or fenced_capital <= 0:
        return 0, 0.0

    win_rate, wl_ratio = _get_historical_stats()
    kelly_fraction = _half_kelly(win_rate, wl_ratio)

    if kelly_fraction <= 0:
        risk_amount = fenced_capital * DEFAULT_RISK_PCT
    else:
        risk_amount = fenced_capital * kelly_fraction

    contracts = int(risk_amount / premium_per_contract_usd)
    if contracts < 1:
        return 0, 0.0

    total_cost = contracts * premium_per_contract_usd

    while total_cost > fenced_capital * 0.5 and contracts > 1:
        contracts -= 1
        total_cost = contracts * premium_per_contract_usd

    return contracts, total_cost


def _compute_next_trading_open(after_dt: datetime) -> str | None:
    try:
        import requests, pytz
        from config.settings import settings
        headers = {
            "APCA-API-KEY-ID": settings.alpaca_api_key,
            "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
        }
        et = pytz.timezone("America/New_York")
        after_date = after_dt.astimezone(et).date()
        start_date = after_date + timedelta(days=1)
        end_date = start_date + timedelta(days=10)
        r = requests.get(
            "https://paper-api.alpaca.markets/v2/calendar",
            headers=headers,
            params={"start": start_date.isoformat(), "end": end_date.isoformat()},
            timeout=5,
        )
        r.raise_for_status()
        days = r.json()
        if days:
            cal_date = days[0].get("date", "")
            cal_open = days[0].get("open", "09:30")
            open_naive = datetime.strptime(f"{cal_date} {cal_open}", "%Y-%m-%d %H:%M")
            open_et = et.localize(open_naive)
            return open_et.astimezone(timezone.utc).isoformat()
    except Exception as exc:
        logger.warning(f"Options | Calendar lookup failed ({exc}) — using 24h fallback")
    fallback = after_dt + timedelta(hours=24)
    wd = fallback.weekday()
    if wd == 5:
        fallback += timedelta(days=2)
    elif wd == 6:
        fallback += timedelta(days=1)
    return fallback.isoformat()


def _options_cb_cooldown_expired(resets_at_iso: str | None) -> bool:
    if not resets_at_iso:
        return False
    try:
        resets_at = datetime.fromisoformat(resets_at_iso)
        return datetime.now(timezone.utc) >= resets_at
    except Exception:
        return False


def _check_options_circuit_breaker(state: dict, positions: list, deployed_capital: float):
    if deployed_capital <= 0 or not positions:
        return

    current_value = sum(p.get("current_value", p.get("total_cost", 0)) for p in positions)
    unrealized_loss = deployed_capital - current_value

    if unrealized_loss > 0 and deployed_capital > 0:
        loss_pct = unrealized_loss / deployed_capital
        if loss_pct >= CB_LOSS_THRESHOLD:
            now = datetime.now(timezone.utc)
            resets_at = _compute_next_trading_open(now)
            state["circuit_breaker_active"] = True
            state["circuit_breaker_reason"] = (
                f"Unrealized loss {loss_pct:.1%} exceeds {CB_LOSS_THRESHOLD:.0%} threshold "
                f"(deployed ${deployed_capital:,.2f}, current value ${current_value:,.2f})"
            )
            state["circuit_breaker_tripped_at"] = now.isoformat()
            state["circuit_breaker_resets_at"] = resets_at
            _save_state(state)
            logger.warning(f"Options | CIRCUIT BREAKER TRIPPED — {state['circuit_breaker_reason']} — resets at {resets_at}")


def scan_for_setups() -> list[dict]:
    state = _get_state()
    if state.get("paused"):
        logger.info("Options | Bot is paused, skipping scan")
        return []

    if state.get("circuit_breaker_active"):
        resets_at = state.get("circuit_breaker_resets_at")
        if resets_at and _options_cb_cooldown_expired(resets_at):
            state["circuit_breaker_active"] = False
            state["circuit_breaker_reason"] = None
            state["circuit_breaker_tripped_at"] = None
            state["circuit_breaker_resets_at"] = None
            _save_state(state)
            logger.info("Options | Circuit breaker RESET — next trading day reached")

    if state.get("circuit_breaker_active"):
        logger.warning("Options | Circuit breaker active — skipping scan")
        state["status"] = "circuit_breaker"
        state["last_scan"] = datetime.now(timezone.utc).isoformat()
        _save_state(state)
        return []

    setups = []
    scan_results = []

    try:
        total_equity = _fetch_account_equity()
        fenced_capital = total_equity * CAPITAL_FENCE_PCT
        state["total_equity"] = total_equity
        state["fenced_capital"] = fenced_capital

        existing_positions = _get_positions()
        pending_trades = _get_pending()
        deployed_capital = sum(p.get("total_cost", 0) for p in existing_positions)
        reserved_capital = sum(p.get("total_cost", 0) for p in pending_trades)
        available_capital = fenced_capital - deployed_capital - reserved_capital

        if existing_positions:
            try:
                update_position_values()
                existing_positions = _get_positions()
                deployed_capital = sum(p.get("total_cost", 0) for p in existing_positions)
            except Exception as exc:
                logger.debug(f"Options | Position value refresh failed before CB check: {exc}")

        _check_options_circuit_breaker(state, existing_positions, deployed_capital)
        if state.get("circuit_breaker_active"):
            state["status"] = "circuit_breaker"
            state["last_scan"] = datetime.now(timezone.utc).isoformat()
            _save_state(state)
            return []

        if available_capital <= 0:
            logger.info(f"Options | Capital fully deployed (${deployed_capital:,.2f} / ${fenced_capital:,.2f})")
            state["status"] = "capital_full"
            state["last_scan"] = datetime.now(timezone.utc).isoformat()
            _save_state(state)
            return []

        for idx, symbol in enumerate(WATCHLIST):
            try:
                if idx > 0 and idx % 5 == 0:
                    time.sleep(1.5)
                logger.info(f"Options | Scanning {symbol} ({idx+1}/{len(WATCHLIST)})...")

                bars = _fetch_stock_bars(symbol, BB_LOOKBACK_DAYS)
                if len(bars) < BB_PERIOD:
                    logger.warning(f"Options | {symbol}: insufficient bar data ({len(bars)} bars)")
                    scan_results.append({
                        "symbol": symbol,
                        "status": "insufficient_data",
                        "bars": len(bars),
                    })
                    continue

                closes = [b["close"] for b in bars]
                spot_price = closes[-1]
                is_squeeze, current_bw, min_bw = _is_bollinger_squeeze(closes)

                chain = _fetch_option_chain(symbol)
                ivr = _compute_ivr(chain) if chain else 50.0

                result = {
                    "symbol": symbol,
                    "spot_price": spot_price,
                    "bollinger_bandwidth": round(current_bw, 4),
                    "bollinger_min_6m": round(min_bw, 4),
                    "is_squeeze": is_squeeze,
                    "ivr": round(ivr, 2),
                    "ivr_pass": ivr < IVR_THRESHOLD,
                    "chain_size": len(chain),
                    "signal": is_squeeze and ivr < IVR_THRESHOLD,
                    "status": "signal" if (is_squeeze and ivr < IVR_THRESHOLD) else "no_signal",
                }
                scan_results.append(result)

                if is_squeeze and ivr < IVR_THRESHOLD:
                    logger.info(f"Options | SIGNAL: {symbol} IVR={ivr:.1f} BW={current_bw:.4f} (min={min_bw:.4f})")

                    straddle = _find_atm_straddle(chain, spot_price)
                    if straddle:
                        contracts, total_cost = _compute_position_size(
                            available_capital, straddle["premium_usd"]
                        )
                        if contracts > 0:
                            win_rate, wl_ratio = _get_historical_stats()
                            setup = {
                                "id": f"{symbol}-{int(time.time())}",
                                "symbol": symbol,
                                "strategy": "long_straddle",
                                "spot_price": spot_price,
                                "call": straddle["call"],
                                "put": straddle["put"],
                                "contracts": contracts,
                                "premium_per_contract": straddle["premium_usd"],
                                "total_cost": total_cost,
                                "ivr": round(ivr, 2),
                                "bollinger_bandwidth": round(current_bw, 4),
                                "kelly_fraction": round(_half_kelly(win_rate, wl_ratio), 4),
                                "win_rate": round(win_rate, 4),
                                "wl_ratio": round(wl_ratio, 4),
                                "fenced_capital": fenced_capital,
                                "available_capital": available_capital,
                                "scanned_at": datetime.now(timezone.utc).isoformat(),
                                "status": "pending_approval",
                            }
                            setups.append(setup)
                            available_capital -= total_cost
                else:
                    logger.debug(f"Options | {symbol}: no signal (IVR={ivr:.1f}, squeeze={is_squeeze})")

            except Exception as e:
                logger.error(f"Options | Error scanning {symbol}: {e}")
                scan_results.append({"symbol": symbol, "status": "error", "error": str(e)})

        if setups:
            pending = _get_pending()
            pending.extend(setups)
            _save_pending(pending)
            logger.info(f"Options | {len(setups)} new setup(s) queued for approval")

        state["status"] = "scan_complete"
        state["last_scan"] = datetime.now(timezone.utc).isoformat()
        state["last_scan_results"] = scan_results
        state["cycle_count"] = state.get("cycle_count", 0) + 1
        state["error"] = None

    except Exception as e:
        logger.error(f"Options | Scan failed: {e}")
        state["status"] = "error"
        state["error"] = str(e)

    _save_state(state)
    return setups


def approve_trade(trade_id: str) -> dict:
    with _lock:
        state = _get_state()

        if state.get("circuit_breaker_active"):
            resets_at = state.get("circuit_breaker_resets_at")
            if resets_at and _options_cb_cooldown_expired(resets_at):
                state["circuit_breaker_active"] = False
                state["circuit_breaker_reason"] = None
                state["circuit_breaker_tripped_at"] = None
                state["circuit_breaker_resets_at"] = None
                _save_state(state)
                logger.info("Options | Circuit breaker RESET — next trading day reached (at approve)")

        positions = _get_positions()
        if positions:
            try:
                update_position_values()
                positions = _get_positions()
            except Exception:
                pass
        deployed = sum(p.get("total_cost", 0) for p in positions)
        if not state.get("circuit_breaker_active"):
            _check_options_circuit_breaker(state, positions, deployed)

        if state.get("circuit_breaker_active"):
            return {"error": "Circuit breaker is active — new trade approvals blocked"}

        pending = _get_pending()
        trade = None
        remaining = []
        for p in pending:
            if p["id"] == trade_id:
                trade = p
            else:
                remaining.append(p)

        if not trade:
            return {"error": f"Trade {trade_id} not found in pending queue"}

        try:
            total_equity = _fetch_account_equity()
        except Exception:
            total_equity = _get_state().get("total_equity", 0)
        fenced_capital = total_equity * CAPITAL_FENCE_PCT
        positions = _get_positions()
        deployed = sum(p.get("total_cost", 0) for p in positions)
        available = fenced_capital - deployed
        trade_cost = trade.get("total_cost", 0)
        if trade_cost > available:
            return {"error": f"Capital fence breach: trade costs ${trade_cost:,.2f} but only ${available:,.2f} available within 5% fence (${fenced_capital:,.2f})"}

        _save_pending(remaining)

        call_order = _submit_option_order(
            trade["call"]["symbol"], trade["contracts"], OrderSide.BUY
        )
        put_order = _submit_option_order(
            trade["put"]["symbol"], trade["contracts"], OrderSide.BUY
        )

        if not PAPER_MODE and (call_order is None or put_order is None):
            _save_pending(pending)
            return {"error": "Order submission failed — trade returned to pending queue"}

        position = {
            **trade,
            "status": "open",
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "current_value": trade["total_cost"],
            "unrealized_pnl": 0.0,
            "unrealized_pnl_pct": 0.0,
            "call_order": call_order,
            "put_order": put_order,
        }

        positions = _get_positions()
        positions.append(position)
        _save_positions(positions)

        conn = sqlite3.connect(str(TRADES_DB))
        conn.execute("""
            INSERT INTO options_trades
            (symbol, strategy, entry_date, call_symbol, put_symbol,
             call_strike, put_strike, expiry, total_premium, status,
             entry_ivr, entry_bandwidth)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
        """, (
            trade["symbol"],
            trade["strategy"],
            datetime.now(timezone.utc).isoformat(),
            trade["call"]["symbol"],
            trade["put"]["symbol"],
            trade["call"]["strike"],
            trade["put"]["strike"],
            trade["call"]["expiry"],
            trade["total_cost"],
            trade["ivr"],
            trade["bollinger_bandwidth"],
        ))
        conn.commit()
        conn.close()

        state = _get_state()
        state["total_trades"] = state.get("total_trades", 0) + 1
        if PAPER_MODE:
            state["paper_equity"] = state.get("paper_equity", PAPER_CAPITAL) - trade["total_cost"]
        _save_state(state)

        logger.info(f"Options | Trade APPROVED: {trade['symbol']} straddle @ ${trade['total_cost']:,.2f} ({'PAPER' if PAPER_MODE else 'LIVE'})")
        return {"status": "approved", "position": position}


def reject_trade(trade_id: str) -> dict:
    with _lock:
        pending = _get_pending()
        remaining = [p for p in pending if p["id"] != trade_id]
        if len(remaining) == len(pending):
            return {"error": f"Trade {trade_id} not found"}
        _save_pending(remaining)
        return {"status": "rejected", "trade_id": trade_id}


def close_position_by_id(position_id: str, exit_value: Optional[float] = None, exit_reason: Optional[str] = None) -> dict:
    with _lock:
        positions = _get_positions()
        pos = None
        remaining = []
        for p in positions:
            if p["id"] == position_id:
                pos = p
            else:
                remaining.append(p)

        if not pos:
            return {"error": f"Position {position_id} not found"}

        contracts = pos.get("contracts", 1)
        call_close = _submit_option_order(
            pos["call"]["symbol"], contracts, OrderSide.SELL
        )
        put_close = _submit_option_order(
            pos["put"]["symbol"], contracts, OrderSide.SELL
        )

        if not PAPER_MODE and (call_close is None or put_close is None):
            return {"error": "Close order submission failed — position remains open"}

        _save_positions(remaining)

        total_cost = pos.get("total_cost", 0)
        if exit_value is None:
            exit_value = pos.get("current_value", total_cost)

        pnl = exit_value - total_cost
        pnl_pct = (pnl / total_cost * 100) if total_cost > 0 else 0

        conn = sqlite3.connect(str(TRADES_DB))
        conn.execute("""
            UPDATE options_trades
            SET status = 'closed', exit_date = ?, exit_value = ?, pnl = ?, pnl_pct = ?, exit_reason = ?
            WHERE call_symbol = ? AND status = 'open'
        """, (
            datetime.now(timezone.utc).isoformat(),
            exit_value,
            pnl,
            pnl_pct,
            exit_reason or "manual",
            pos["call"]["symbol"],
        ))
        conn.commit()
        conn.close()

        state = _get_state()
        state["total_pnl"] = state.get("total_pnl", 0) + pnl
        if pnl > 0:
            state["total_wins"] = state.get("total_wins", 0) + 1
        if PAPER_MODE:
            state["paper_equity"] = state.get("paper_equity", PAPER_CAPITAL) + exit_value
        _save_state(state)

        reason_tag = f" [{exit_reason}]" if exit_reason else ""
        logger.info(f"Options | Position CLOSED{reason_tag}: {pos['symbol']} PnL=${pnl:,.2f} ({pnl_pct:+.1f}%) ({'PAPER' if PAPER_MODE else 'LIVE'})")

        if pnl > 0:
            try:
                from notifications.alert_manager import enqueue_profitable_trade
                enqueue_profitable_trade(
                    bot_name="Apex Predator (Options)",
                    symbol=pos["symbol"],
                    pnl_pct=pnl_pct,
                    pnl_usd=pnl,
                    reason="straddle_exit",
                )
            except Exception:
                pass

        return {"status": "closed", "pnl": pnl, "pnl_pct": pnl_pct}


def _compute_dte(expiry_str: str) -> int:
    try:
        expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
        today = datetime.now(timezone.utc).date()
        return (expiry_date - today).days
    except Exception:
        return 999


def _check_exits():
    positions = _get_positions()
    if not positions:
        return

    for pos in list(positions):
        pos_id = pos.get("id")
        total_cost = pos.get("total_cost", 0)
        current_value = pos.get("current_value", total_cost)

        if total_cost <= 0:
            continue

        loss_pct = (total_cost - current_value) / total_cost
        if loss_pct >= MAX_LOSS_PCT:
            logger.warning(f"Options | STOP-LOSS triggered for {pos['symbol']}: lost {loss_pct*100:.1f}% (threshold {MAX_LOSS_PCT*100:.0f}%)")
            close_position_by_id(pos_id, exit_value=current_value, exit_reason="stop-loss")
            continue

        gain_pct = (current_value - total_cost) / total_cost
        if gain_pct >= PROFIT_TARGET_PCT:
            logger.info(f"Options | PROFIT-TARGET triggered for {pos['symbol']}: gained {gain_pct*100:.1f}% (threshold {PROFIT_TARGET_PCT*100:.0f}%)")
            close_position_by_id(pos_id, exit_value=current_value, exit_reason="profit-target")
            continue

        expiry = pos.get("call", {}).get("expiry") or pos.get("put", {}).get("expiry")
        if expiry:
            dte = _compute_dte(expiry)
            if dte <= MIN_DTE_EXIT:
                logger.info(f"Options | DTE-EXPIRY exit for {pos['symbol']}: {dte} DTE remaining (threshold {MIN_DTE_EXIT})")
                close_position_by_id(pos_id, exit_value=current_value, exit_reason="dte-expiry")
                continue


def update_position_values():
    positions = _get_positions()
    if not positions:
        return

    for pos in positions:
        try:
            call_sym = pos["call"]["symbol"]
            put_sym = pos["put"]["symbol"]

            try:
                call_snap = _get_option_client().get_option_snapshot(call_sym)
                put_snap = _get_option_client().get_option_snapshot(put_sym)

                call_mid = 0
                put_mid = 0
                if call_snap and hasattr(call_snap, 'latest_quote') and call_snap.latest_quote:
                    call_mid = (float(call_snap.latest_quote.bid_price or 0) + float(call_snap.latest_quote.ask_price or 0)) / 2
                if put_snap and hasattr(put_snap, 'latest_quote') and put_snap.latest_quote:
                    put_mid = (float(put_snap.latest_quote.bid_price or 0) + float(put_snap.latest_quote.ask_price or 0)) / 2

                current_value = (call_mid + put_mid) * 100 * pos.get("contracts", 1)
                pos["current_value"] = current_value
                pos["unrealized_pnl"] = current_value - pos["total_cost"]
                pos["unrealized_pnl_pct"] = (pos["unrealized_pnl"] / pos["total_cost"] * 100) if pos["total_cost"] > 0 else 0

                if hasattr(call_snap, 'greeks') and call_snap.greeks:
                    pos["call"]["delta"] = float(call_snap.greeks.delta) if call_snap.greeks.delta else None
                    pos["call"]["gamma"] = float(call_snap.greeks.gamma) if call_snap.greeks.gamma else None
                    pos["call"]["theta"] = float(call_snap.greeks.theta) if call_snap.greeks.theta else None
                if hasattr(put_snap, 'greeks') and put_snap.greeks:
                    pos["put"]["delta"] = float(put_snap.greeks.delta) if put_snap.greeks.delta else None
                    pos["put"]["gamma"] = float(put_snap.greeks.gamma) if put_snap.greeks.gamma else None
                    pos["put"]["theta"] = float(put_snap.greeks.theta) if put_snap.greeks.theta else None

            except Exception as e:
                logger.debug(f"Options | Could not update greeks for {pos['symbol']}: {e}")

        except Exception as e:
            logger.warning(f"Options | Error updating position {pos.get('symbol', '?')}: {e}")

    _save_positions(positions)

    _check_exits()


def toggle_pause() -> dict:
    state = _get_state()
    state["paused"] = not state.get("paused", False)
    _save_state(state)
    return {"paused": state["paused"]}


def get_full_state() -> dict:
    state = _get_state()
    positions = _get_positions()
    pending = _get_pending()

    deployed = sum(p.get("total_cost", 0) for p in positions)
    current_value = sum(p.get("current_value", 0) for p in positions)
    unrealized_pnl = current_value - deployed

    state["positions_count"] = len(positions)
    state["pending_count"] = len(pending)
    state["deployed_capital"] = deployed
    state["current_value"] = current_value
    state["unrealized_pnl"] = unrealized_pnl
    state["paper_mode"] = PAPER_MODE
    if PAPER_MODE:
        state["paper_equity"] = state.get("paper_equity", PAPER_CAPITAL)
        state["total_equity"] = state["paper_equity"]
        state["fenced_capital"] = state["total_equity"] * CAPITAL_FENCE_PCT

    state.setdefault("circuit_breaker_active", False)
    state.setdefault("circuit_breaker_reason", None)

    return state


def run_scheduled_scan():
    logger.info("Options | === Scheduled 3:30 PM ET scan starting ===")
    try:
        scan_for_setups()
        update_position_values()
    except Exception as e:
        logger.error(f"Options | Scheduled scan error: {e}")
        state = _get_state()
        state["error"] = str(e)
        _save_state(state)
