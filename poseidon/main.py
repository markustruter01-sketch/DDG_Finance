"""
main.py — Poseidon Bot
Bot #7: Statistical Arbitrage / Pairs Trading on Kraken
15-minute cycle | $100,000 paper capital
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loguru import logger

# ── Path setup ────────────────────────────────────────────────────────────────
_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.join(_DIR, "..")
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_TRADING_PLATFORM = os.path.join(_REPO_ROOT, "trading-platform")
if _TRADING_PLATFORM not in sys.path:
    sys.path.append(_TRADING_PLATFORM)

from config import (
    BOT_ID, DISPLAY_NAME, DB_ID,
    PAPER_STARTING_BALANCE, PAPER_FEE_PCT, LOOP_SLEEP_SECONDS,
    FALLBACK_PAIR_SETS,
    UNIVERSE_SIZE, MIN_PAIR_CORR, ADF_PVALUE_MAX_DISCOVERY,
    MAX_UNIVERSE_PAIRS, DISCOVERY_HOURS, DISCOVERY_DAILY_DAYS,
    ZSCORE_ENTRY, ZSCORE_EXIT, ZSCORE_STOP,
    HURST_MAX, ADF_PVALUE_MAX, HEDGE_RATIO_STABILITY,
    POSITION_VALUE_PCT, MAX_POSITIONS, MAX_HOLD_HOURS,
    HEDGE_RATIO_RECALC_HOURS, OLS_LOOKBACK_DAYS,
    ZSCORE_LOOKBACK_HOURS, SPREAD_HISTORY_HOURS,
    CB_CONSECUTIVE_LOSSES, CB_PAUSE_HOURS,
    KRAKEN_API_KEY, KRAKEN_SECRET_KEY,
    STATUS_FILE, LIVE_STATE_FILE,
)
from pairs_engine import (
    ols_hedge_ratio, calculate_spread_series, calculate_zscore,
    hurst_exponent, adf_pvalue, is_hedge_ratio_stable,
    evaluate_pair_signal, calculate_pair_sizes,
)
from paper_portfolio import PairPosition, PaperPortfolio
from db_utils import (
    ensure_poseidon_tables, write_heartbeat, write_portfolio,
    upsert_pair_params, record_trade, get_pair_params, get_all_pair_params,
    check_and_clear_force_refresh,
)
import market_universe as _mu
from pair_discovery import discover_pairs

# ── Exchange setup ────────────────────────────────────────────────────────────
try:
    import ccxt
    exchange = ccxt.kraken({
        "apiKey": KRAKEN_API_KEY,
        "secret": KRAKEN_SECRET_KEY,
        "enableRateLimit": True,
    })
    logger.info(f"Poseidon | Exchange: Kraken (paper trading mode)")
except Exception as e:
    logger.error(f"Poseidon | ccxt init failed: {e}")
    exchange = None

PORTFOLIO_FILE = os.path.join(_DIR, "poseidon_paper_portfolio.json")
portfolio = PaperPortfolio(PORTFOLIO_FILE, PAPER_STARTING_BALANCE)

_cycle = 0
_circuit_breaker_until: datetime | None = None
_last_hedge_recalc: dict[int, datetime] = {}
_hedge_ratio_history: dict[int, list[float]] = {}
_pair_params_cache: dict[int, dict] = {}

# ── Dynamic pair universe ──────────────────────────────────────────────────────
_active_pairs: list[dict] = []          # populated by run_pair_discovery()
_last_discovery: datetime | None = None  # timestamp of last successful discovery


def _fetch_daily_closes_for_discovery(symbols: list[str]) -> dict[str, list[float]]:
    """
    Fetch DISCOVERY_DAILY_DAYS of daily closes for all symbols in the universe.
    Used only during pair discovery (not the hot 15-min cycle path).
    """
    if exchange is None:
        return {}
    closes: dict[str, list[float]] = {}
    limit = DISCOVERY_DAILY_DAYS + 5
    for sym in symbols:
        try:
            bars = exchange.fetch_ohlcv(sym, "1d", limit=limit)
            if bars and len(bars) >= 10:
                closes[sym] = [float(b[4]) for b in bars if b[4] and b[4] > 0]
        except Exception as e:
            logger.debug(f"Poseidon discovery | daily OHLCV failed for {sym}: {e}")
    return closes


def run_pair_discovery() -> bool:
    """
    Full pair discovery: CoinGecko top-250 → Kraken intersection →
    correlation screen → ADF gate → update _active_pairs.
    Returns True on success, False on failure (falls back to FALLBACK_PAIR_SETS).
    """
    global _active_pairs, _last_discovery

    logger.info(
        f"Poseidon | Starting pair discovery "
        f"(top {UNIVERSE_SIZE} coins, corr≥{MIN_PAIR_CORR}, ADF<{ADF_PVALUE_MAX_DISCOVERY})"
    )

    # Step 1: Get market universe
    universe = _mu.get_kraken_universe(exchange, n=UNIVERSE_SIZE) if exchange else []
    if not universe:
        logger.warning("Poseidon | Universe fetch failed — keeping current pairs")
        if not _active_pairs:
            _active_pairs = list(FALLBACK_PAIR_SETS)
        return False

    logger.info(f"Poseidon | Universe: {len(universe)} symbols from top-{UNIVERSE_SIZE}")

    # Step 2: Fetch daily closes for all universe symbols
    logger.info("Poseidon | Fetching daily closes for pair discovery...")
    daily_closes = _fetch_daily_closes_for_discovery(universe)
    logger.info(f"Poseidon | Daily close data available for {len(daily_closes)}/{len(universe)} symbols")

    # Step 3: Discover cointegrated pairs
    discovered = discover_pairs(
        symbols=universe,
        daily_closes=daily_closes,
        min_corr=MIN_PAIR_CORR,
        adf_pvalue_max=ADF_PVALUE_MAX_DISCOVERY,
        max_pairs=MAX_UNIVERSE_PAIRS,
    )

    if discovered:
        _active_pairs = discovered
        _last_discovery = datetime.now(timezone.utc)
        # Clear stale hedge ratio caches so they recalculate for new pairs
        _last_hedge_recalc.clear()
        _pair_params_cache.clear()
        logger.info(
            f"Poseidon | Discovery complete — {len(_active_pairs)} tradeable pairs "
            f"from {len(universe)}-symbol universe"
        )
        for p in _active_pairs[:10]:  # log top 10
            logger.info(
                f"  Pair {p['pair_set_id']}: {p['asset_a']}/{p['asset_b']} "
                f"corr={p.get('corr', '?')} ADF={p.get('adf_p', '?')}"
            )
        return True
    else:
        logger.warning(
            "Poseidon | Discovery found 0 cointegrated pairs — "
            "using fallback pair set"
        )
        if not _active_pairs:
            _active_pairs = list(FALLBACK_PAIR_SETS)
        return False


def maybe_run_discovery(force: bool = False):
    """Run discovery if not done yet or if DISCOVERY_HOURS have elapsed."""
    global _last_discovery
    now = datetime.now(timezone.utc)
    if (
        force
        or _last_discovery is None
        or (now - _last_discovery).total_seconds() >= DISCOVERY_HOURS * 3600
    ):
        run_pair_discovery()


# ── Market data ───────────────────────────────────────────────────────────────

def fetch_ohlcv(symbol: str, timeframe: str = "1h", limit: int = 60 * 24 * OLS_LOOKBACK_DAYS + 10) -> list:
    """Fetch OHLCV from Kraken. Returns list of [ts, o, h, l, c, v]."""
    if exchange is None:
        return []
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        return bars or []
    except Exception as e:
        logger.warning(f"Poseidon | fetch_ohlcv {symbol} failed: {e}")
        return []


def fetch_current_price(symbol: str) -> float | None:
    """Fetch latest price from Kraken."""
    if exchange is None:
        return None
    try:
        ticker = exchange.fetch_ticker(symbol)
        return float(ticker.get("last") or ticker.get("close") or 0)
    except Exception as e:
        logger.warning(f"Poseidon | price fetch {symbol} failed: {e}")
        return None


def get_hourly_closes(symbol: str, limit: int) -> list[float]:
    """Get list of hourly close prices."""
    bars = fetch_ohlcv(symbol, "1h", limit + 10)
    if not bars:
        return []
    return [float(b[4]) for b in bars[-limit:] if b[4] and b[4] > 0]


# ── Hedge ratio management ────────────────────────────────────────────────────

def recalculate_hedge_ratio(pair: dict) -> dict | None:
    """
    Run OLS regression on 60 days of hourly data.
    Returns hedge ratio and spread statistics.
    """
    ps_id = pair["pair_set_id"]
    asset_a = pair["asset_a"]
    asset_b = pair["asset_b"]
    limit = OLS_LOOKBACK_DAYS * 24 + 10

    prices_a = get_hourly_closes(asset_a, limit)
    prices_b = get_hourly_closes(asset_b, limit)

    if len(prices_a) < 100 or len(prices_b) < 100:
        logger.warning(f"Poseidon | Pair {ps_id}: insufficient data for OLS ({len(prices_a)}/{len(prices_b)} bars)")
        return None

    # Use matching length
    n = min(len(prices_a), len(prices_b))
    prices_a = prices_a[-n:]
    prices_b = prices_b[-n:]

    import math as _math
    # Zip-align before taking logs so log_a[i] and log_b[i] always correspond
    # to the same bar; independent filtering can produce lists of different
    # lengths if one asset has a zero/missing price the other doesn't.
    aligned_logs = [
        (_math.log(pa), _math.log(pb))
        for pa, pb in zip(prices_a, prices_b)
        if pa > 0 and pb > 0
    ]
    log_a = [t[0] for t in aligned_logs]
    log_b = [t[1] for t in aligned_logs]

    hedge = ols_hedge_ratio(log_a, log_b)
    spreads = calculate_spread_series(prices_a, prices_b, hedge)

    if not spreads:
        return None

    spread_mean = sum(spreads) / len(spreads)
    variance = sum((s - spread_mean) ** 2 for s in spreads) / len(spreads)
    spread_std = math.sqrt(variance) if variance > 0 else 0.001

    h = hurst_exponent(spreads)
    adf_p = adf_pvalue(spreads)

    # 30-day average hedge ratio from history
    hist = _hedge_ratio_history.get(ps_id, [])
    hist.append(hedge)
    if len(hist) > 30:
        hist = hist[-30:]
    _hedge_ratio_history[ps_id] = hist
    hr_30d_avg = sum(hist) / len(hist) if hist else hedge

    hr_stable = is_hedge_ratio_stable(hedge, hr_30d_avg, HEDGE_RATIO_STABILITY)
    # Hurst removed from is_tradeable gate — ADF is the sole stationarity gate for pairs trading
    is_tradeable = (adf_p < ADF_PVALUE_MAX and hr_stable)

    notes = []
    # Hurst logged for observability only — no longer gates entry
    notes.append(f"Hurst={h:.3f} (info only)")
    if adf_p >= ADF_PVALUE_MAX:
        notes.append(f"ADF={adf_p:.3f}≥{ADF_PVALUE_MAX} (non-stationary)")
    if not hr_stable:
        notes.append(f"HR_drift={(abs(hedge-hr_30d_avg)/hr_30d_avg*100 if hr_30d_avg else 0):.1f}%")

    upsert_pair_params(
        ps_id, asset_a, asset_b, hedge, hr_30d_avg,
        spread_mean, spread_std, h, adf_p, is_tradeable,
        notes="; ".join(notes) if notes else "OK"
    )

    _pair_params_cache[ps_id] = {
        "hedge_ratio": hedge,
        "hedge_ratio_30d_avg": hr_30d_avg,
        "spread_mean": spread_mean,
        "spread_std": spread_std,
        "hurst": h,
        "adf_pvalue": adf_p,
        "is_tradeable": is_tradeable,
        "prices_a": prices_a,
        "prices_b": prices_b,
    }

    logger.info(
        f"Poseidon | Pair {ps_id} ({asset_a}/{asset_b}) | "
        f"HR={hedge:.4f} H={h:.3f} ADF={adf_p:.3f} tradeable={is_tradeable}"
    )
    return _pair_params_cache[ps_id]


def maybe_recalculate_hedge_ratios(force: bool = False):
    """Recalculate hedge ratios every HEDGE_RATIO_RECALC_HOURS hours."""
    now = datetime.now(timezone.utc)
    for pair in _active_pairs:
        ps_id = pair["pair_set_id"]
        last_recalc = _last_hedge_recalc.get(ps_id)
        if force or last_recalc is None or (now - last_recalc).total_seconds() >= HEDGE_RATIO_RECALC_HOURS * 3600:
            logger.info(f"Poseidon | Recalculating hedge ratio for pair {ps_id}...")
            result = recalculate_hedge_ratio(pair)
            if result:
                _last_hedge_recalc[ps_id] = now


# ── Circuit breaker ───────────────────────────────────────────────────────────

def is_circuit_breaker_active() -> bool:
    global _circuit_breaker_until
    if _circuit_breaker_until is None:
        return False
    if datetime.now(timezone.utc) < _circuit_breaker_until:
        return True
    _circuit_breaker_until = None
    return False


def check_circuit_breaker():
    global _circuit_breaker_until
    if portfolio.consecutive_losses >= CB_CONSECUTIVE_LOSSES:
        until = datetime.now(timezone.utc) + timedelta(hours=CB_PAUSE_HOURS)
        _circuit_breaker_until = until
        logger.warning(f"Poseidon | Circuit breaker: {portfolio.consecutive_losses} consecutive losses. Paused until {until.isoformat()}")


# ── Exit monitoring ───────────────────────────────────────────────────────────

def check_exits(current_prices: dict[str, float]):
    """Check all open positions for exit conditions."""
    for ps_id, pos in list(portfolio.positions.items()):
        price_a = current_prices.get(pos.asset_a)
        price_b = current_prices.get(pos.asset_b)
        if price_a is None or price_b is None:
            continue

        params = _pair_params_cache.get(ps_id)
        hedge = params["hedge_ratio"] if params else pos.entry_hedge_ratio

        # Compute current Z-score
        prices_a = get_hourly_closes(pos.asset_a, ZSCORE_LOOKBACK_HOURS + 10)
        prices_b = get_hourly_closes(pos.asset_b, ZSCORE_LOOKBACK_HOURS + 10)
        if len(prices_a) >= 10 and len(prices_b) >= 10:
            spreads = calculate_spread_series(prices_a, prices_b, hedge)
            current_z = calculate_zscore(spreads, ZSCORE_LOOKBACK_HOURS)
        else:
            current_z = None

        reason = None

        # Check exit conditions
        if current_z is not None:
            if abs(current_z) <= ZSCORE_EXIT:
                reason = "mean_reversion_complete"
            elif abs(current_z) >= ZSCORE_STOP:
                reason = "stop_loss_zscore"

        # Time-based exit
        if pos.holding_hours() >= MAX_HOLD_HOURS:
            reason = "timeout_72h"

        # Hedge ratio breakdown
        if params:
            current_hr = params["hedge_ratio"]
            if not is_hedge_ratio_stable(current_hr, pos.entry_hedge_ratio, 0.25):
                reason = "hedge_ratio_breakdown"

        if reason:
            trade = portfolio.close_position(ps_id, price_a, price_b, reason)
            if trade:
                record_trade(trade)
                logger.info(f"Poseidon | Exited pair {ps_id}: {reason} Z={f'{current_z:.2f}' if current_z is not None else 'N/A'}")


# ── Entry scan ────────────────────────────────────────────────────────────────

def scan_for_entries(current_prices: dict[str, float]):
    """Scan all pair sets for entry signals."""
    if is_circuit_breaker_active():
        logger.info("Poseidon | Circuit breaker active — skipping entry scan")
        return

    if not portfolio.can_open(MAX_POSITIONS):
        logger.info(f"Poseidon | Max positions ({MAX_POSITIONS}) reached — skipping entry scan")
        return

    for pair in _active_pairs:
        ps_id = pair["pair_set_id"]
        asset_a = pair["asset_a"]
        asset_b = pair["asset_b"]

        # Skip if already in this pair
        if ps_id in portfolio.positions:
            continue

        params = _pair_params_cache.get(ps_id)
        if not params or not params.get("is_tradeable"):
            logger.debug(f"Poseidon | Pair {ps_id} not tradeable — skipping")
            continue

        hedge = params["hedge_ratio"]
        hr_avg = params["hedge_ratio_30d_avg"]
        prices_a = params.get("prices_a", [])
        prices_b = params.get("prices_b", [])

        if len(prices_a) < ZSCORE_LOOKBACK_HOURS or len(prices_b) < ZSCORE_LOOKBACK_HOURS:
            continue

        signal = evaluate_pair_signal(
            prices_a, prices_b, hedge, hr_avg,
            zscore_entry=ZSCORE_ENTRY,
            zscore_lookback=ZSCORE_LOOKBACK_HOURS,
            hurst_max=HURST_MAX,
            adf_max=ADF_PVALUE_MAX,
            hedge_stability=HEDGE_RATIO_STABILITY,
        )

        _z = signal.get("zscore")
        _h = signal.get("hurst")
        _adf = signal.get("adf_pvalue")
        _z_str = f"{_z:.2f}" if _z is not None else "N/A"
        _h_str = f"{_h:.3f}" if _h is not None else "N/A"
        _adf_str = f"{_adf:.3f}" if _adf is not None else "N/A"
        logger.info(
            f"Poseidon | Pair {ps_id} ({asset_a}/{asset_b}): "
            f"Z={_z_str} H={_h_str} ADF={_adf_str} signal={signal.get('signal')}"
        )

        if not signal.get("signal"):
            continue

        price_a = current_prices.get(asset_a)
        price_b = current_prices.get(asset_b)
        if not price_a or not price_b:
            continue

        current_equity = portfolio.equity(current_prices)
        sizes = calculate_pair_sizes(current_equity, price_a, price_b, hedge, POSITION_VALUE_PCT)

        if signal["signal"] == "long_a_short_b":
            leg_a_side, leg_b_side = "long", "short"
        else:
            leg_a_side, leg_b_side = "short", "long"

        pos = PairPosition(
            pair_set_id=ps_id,
            asset_a=asset_a,
            asset_b=asset_b,
            direction=signal["signal"],
            leg_a_side=leg_a_side,
            leg_b_side=leg_b_side,
            leg_a_units=sizes["leg_a_units"],
            leg_b_units=sizes["leg_b_units"],
            leg_a_entry=price_a,
            leg_b_entry=price_b,
            position_value=sizes["position_value"],
            entry_zscore=signal["zscore"],
            hedge_ratio=hedge,
        )

        opened = portfolio.open_position(pos)
        if opened and not portfolio.can_open(MAX_POSITIONS):
            break  # reached max positions


# ── Live state write ──────────────────────────────────────────────────────────

def write_live_state(current_prices: dict[str, float], equity: float):
    state = {
        "bot_id": BOT_ID,
        "display_name": DISPLAY_NAME,
        "equity": equity,
        "cash": portfolio.cash,
        "open_positions": len(portfolio.positions),
        "positions": {},
        "pair_params": get_all_pair_params(),
        "circuit_breaker": _circuit_breaker_until.isoformat() if _circuit_breaker_until else None,
        "cycle": _cycle,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    for ps_id, pos in portfolio.positions.items():
        pa = current_prices.get(pos.asset_a, pos.leg_a_entry)
        pb = current_prices.get(pos.asset_b, pos.leg_b_entry)
        pnl = pos.current_pnl(pa, pb)
        state["positions"][ps_id] = {
            **pos.to_dict(),
            "current_price_a": pa,
            "current_price_b": pb,
            **pnl,
        }
    _live_path = Path(LIVE_STATE_FILE)
    _live_path.parent.mkdir(parents=True, exist_ok=True)
    _tmp = _live_path.with_suffix(".tmp")
    _tmp.write_text(json.dumps(state, indent=2, default=str))
    _tmp.replace(_live_path)


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    global _cycle
    logger.info(f"""
=================================================================
  PAPER TRADING MODE  —  {DISPLAY_NAME}
  Bot ID: {BOT_ID} (DB id={DB_ID}) | Strategy: Statistical Arbitrage / Pairs Trading
  Simulated ${PAPER_STARTING_BALANCE:,.0f} account | 15-min cycle
=================================================================
""")

    # Ensure DB tables exist
    ensure_poseidon_tables()

    # Run pair discovery (blocking at startup — builds universe from top-250)
    logger.info(f"Poseidon | Running startup pair discovery (top {UNIVERSE_SIZE} coins)...")
    maybe_run_discovery(force=True)

    # Initial hedge ratio calculation for discovered pairs
    logger.info(f"Poseidon | Calculating hedge ratios for {len(_active_pairs)} discovered pairs...")
    maybe_recalculate_hedge_ratios(force=True)

    while True:
        _cycle += 1
        cycle_start = datetime.now(timezone.utc)
        logger.info(f"Poseidon | === Cycle #{_cycle} starting at {cycle_start.isoformat()[:19]} UTC ===")

        # Self-healing kick: API can set force_refresh=TRUE to prompt re-discovery
        if check_and_clear_force_refresh():
            logger.info("Poseidon | force_refresh flag detected — re-running pair discovery")
            maybe_run_discovery(force=True)

        try:
            # Check if discovery needs to run (every 24h)
            maybe_run_discovery()

            # Fetch current prices for all assets in the active pair universe
            all_symbols = set()
            for pair in _active_pairs:
                all_symbols.add(pair["asset_a"])
                all_symbols.add(pair["asset_b"])

            current_prices: dict[str, float] = {}
            for sym in all_symbols:
                price = fetch_current_price(sym)
                if price and price > 0:
                    current_prices[sym] = price

            logger.info(
                f"Poseidon | Prices fetched for {len(current_prices)}/{len(all_symbols)} symbols "
                f"| Active pairs: {len(_active_pairs)}"
            )

            # Compute equity
            equity = portfolio.equity(current_prices)

            # Maybe recalculate hedge ratios (every 24h)
            maybe_recalculate_hedge_ratios()

            # Check exits first
            check_exits(current_prices)

            # Check circuit breaker
            check_circuit_breaker()

            # Scan for entries
            scan_for_entries(current_prices)

            # Update DB
            write_heartbeat(equity, len(portfolio.positions), _cycle)
            write_portfolio(equity, portfolio.cash, len(portfolio.positions))
            write_live_state(current_prices, equity)

            logger.info(
                f"Poseidon | Cycle #{_cycle} complete | "
                f"equity=${equity:,.2f} | positions={len(portfolio.positions)}/{MAX_POSITIONS} | "
                f"CB={'active' if is_circuit_breaker_active() else 'off'}"
            )

        except Exception as e:
            logger.error(f"Poseidon | Cycle #{_cycle} error: {e}")
            try:
                write_heartbeat(portfolio.equity({}), len(portfolio.positions), _cycle, status="error", error=str(e))
            except Exception:
                pass

        elapsed = (datetime.now(timezone.utc) - cycle_start).total_seconds()
        sleep_time = max(1, LOOP_SLEEP_SECONDS - elapsed)
        logger.info(f"Poseidon | Sleeping {sleep_time:.0f}s until next cycle")
        time.sleep(sleep_time)


if __name__ == "__main__":
    main()
