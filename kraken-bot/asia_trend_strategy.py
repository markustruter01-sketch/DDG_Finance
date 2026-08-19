"""
asia_trend_strategy.py — Asia-Pacific ETF trend-following strategy.

Takes over the oracle slot (Stage 3B). Uses the same shared validated trend
engine as bot2_spy_qqq and latam_trend_strategy (EMA50/200 + TP scale-outs +
trailing stop + 3-day exit) with all three Stage 1 risk modules wired:
  - vol_scaled_size  (target_vol=0.12, hard cap 25%)
  - regional_regime  (per-ETF on each Asia ETF's own price history)
  - corr_cap_check   (cross-bot AND within-Asia — EWY/EWT are both
                      semiconductor plays; ρ>0.75 blocks the weaker one)

Universe: ASIA_PACIFIC = ["EWY", "EWT", "INDA", "EWJ", "EWM", "VNM"]
bot_id stays "oracle" (frozen — DB, dashboard, fleet equity all key on it).
Alpaca account: ALPACA_API_KEY / ALPACA_SECRET_KEY (oracle paper account).

Wired into runner.py:
    ("oracle", "asia_trend_strategy", "run_asia_cycle")

Called every LOOP_SLEEP_SECONDS (3600s = hourly).
Entry gate: fires in a window before NYSE close (19:40–20:00 UTC = ~3:40–4 PM ET).
Exit management runs every cycle.

KEY DIFFERENCE vs LatAm: corr cap includes within-Asia held ETFs (not just
cross-bot). EWY (Korea) and EWT (Taiwan) are both semiconductor-heavy with
ρ≈0.80 — the cap must block the weaker if both signal at the same time.
"""
from __future__ import annotations

import logging
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Optional

logger = logging.getLogger("asia.trend")

# ── Path injection ─────────────────────────────────────────────────────────────

def _add_trading_platform_to_path() -> None:
    tp = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trading-platform")
    )
    if tp not in sys.path:
        sys.path.insert(0, tp)


_add_trading_platform_to_path()

from alpaca_etf_engine import (  # noqa: E402
    AlpacaEtfEngine,
    calculate_ema,
    calculate_atr,
    _yahoo_daily_ohlcv,
)

# ── Constants ──────────────────────────────────────────────────────────────────

UNIVERSE          = ["EWY", "EWT", "INDA", "EWJ", "EWM", "VNM"]
BOT_ID            = "oracle"              # frozen — never change

EMA_FAST          = 50
EMA_SLOW          = 200
TRAIL_STOP_PCT    = 0.08
MAX_3DAY_DROP_PCT = 0.05
VOL_TARGET_VOL    = 0.12    # 12% annualised vol per position
VOL_SIZE_CAP      = 0.25    # hard cap 25%
MIN_HOLD_DAYS     = 5
MAX_DEPLOYMENT    = 0.80    # never deploy more than 80% of equity
CASH_RESERVE      = 0.20    # minimum 20% cash always
MAX_POSITIONS     = 4       # 6-ETF universe; max 3–4 concurrent

# TP targets for tiered scale-out (from entry price — mirrors bot2 / LatAm)
TP1_PCT = 0.06   # +6%  → scale out 33%
TP2_PCT = 0.12   # +12% → scale out another 33%

# Entry gate: fire once per day in the pre-close window 19:40–20:00 UTC
ENTRY_HOUR_UTC    = 19
ENTRY_MIN_START   = 40
ENTRY_MIN_END     = 60      # 19:40–19:59 UTC = ~3:40–4 PM ET

# Once-per-day gate state
_last_entry_scan_date: Optional[date] = None

# ── Stage 1 risk module imports with fail-safe stubs ──────────────────────────

try:
    from core.vol_targeting import vol_scaled_size as _vol_scaled_size_real
    _VOL_TARGETING_OK = True
except Exception as _vt_err:
    _VOL_TARGETING_OK = False
    logger.error(f"Asia | vol_targeting import FAILED — sizing disabled: {_vt_err}")
    def _vol_scaled_size_real(*a, **kw) -> int: return 0  # type: ignore[misc]

try:
    from core.regional_regime import regional_regime as _regional_regime_real
    _REGIME_OK = True
except Exception as _rr_err:
    _REGIME_OK = False
    logger.error(f"Asia | regional_regime import FAILED — defaulting CRISIS: {_rr_err}")
    def _regional_regime_real(etf: str) -> dict:  # type: ignore[misc]
        return {"regime": "CRISIS", "source": "stub"}

try:
    from core.correlation_cap import (
        corr_cap_check as _corr_cap_check_real,
        fetch_price_history as _fetch_price_history,
    )
    _CORR_CAP_OK = True
except Exception as _cc_err:
    _CORR_CAP_OK = False
    logger.error(f"Asia | correlation_cap import FAILED — cap disabled: {_cc_err}")
    def _corr_cap_check_real(*a, **kw): return False, "fail_safe_blocked"  # type: ignore[misc]
    def _fetch_price_history(tickers, days=90): return {}            # type: ignore[misc]


def _vol_scaled_size(equity: float, etf: str, price: float) -> int:
    """Wrapper: returns 0 (fail-CLOSED) if module unavailable or any error."""
    if not _VOL_TARGETING_OK:
        return 0
    try:
        return _vol_scaled_size_real(equity, etf, price,
                                     target_vol=VOL_TARGET_VOL)
    except Exception as exc:
        logger.error(f"Asia | vol_scaled_size({etf}) error: {exc}")
        return 0


def _regional_regime(etf: str) -> dict:
    """Per-ETF regime on that ETF's own price history. Fail-CLOSED → CRISIS."""
    if not _REGIME_OK:
        return {"regime": "CRISIS", "source": "stub"}
    try:
        return _regional_regime_real(etf)
    except Exception as exc:
        logger.error(f"Asia | regional_regime({etf}) error: {exc}")
        return {"regime": "CRISIS", "source": "error"}


def _corr_cap_check(candidate: str, held_etfs: list[str]) -> tuple[bool, str]:
    """
    Cross-bot + within-Asia correlation cap. Fetches 90d price history for all
    tickers, then delegates to corr_cap_check(). Returns (allowed, reason).

    IMPORTANT: held_etfs includes BOTH cross-bot holdings AND other Asia ETFs
    already held in this strategy. This is intentional — EWY (Korea) and EWT
    (Taiwan) are both semiconductor-heavy with ρ≈0.80 and the cap must block
    the weaker if both signal simultaneously.

    Uses max_correlated=1 (stricter than the LatAm default of 2) because Asia
    ETFs within the universe can be highly correlated. max_correlated=1 means:
    block if the candidate is correlated (ρ>0.75) with ANY single held ETF.
    This enforces the semiconductor redundancy rule (EWY/EWT cannot coexist)
    while still allowing distinct-factor pairs like EWJ + EWM.

    Missing data → ρ=0 → allowed (fail-open on data gaps; an allow mistake is
    less harmful than blocking a valid entry).
    """
    if not _CORR_CAP_OK or not held_etfs:
        return True, "no_held_etfs"
    try:
        all_tickers   = [candidate] + held_etfs
        price_history = _fetch_price_history(all_tickers, days=90)
        return _corr_cap_check_real(
            candidate, held_etfs, price_history,
            max_correlated=1,   # stricter: any 1 correlated partner blocks
        )
    except Exception as exc:
        logger.error(f"Asia | corr_cap_check({candidate}) error — fail-CLOSED: {exc}")
        return False, "fail_safe_blocked"


# ── Cross-bot held-ETF helper ─────────────────────────────────────────────────

def _get_cross_bot_held_etfs(exclude_bot_id: str = BOT_ID) -> list[str]:
    """
    Return all ETF symbols currently held by OTHER bots (alpaca_etf_positions).
    Used so the Asia corr cap also sees US Core + LatAm holdings.
    """
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return []
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT symbol
                    FROM   alpaca_etf_positions
                    WHERE  status   = 'open'
                      AND  bot_id  != %s
                """, (exclude_bot_id,))
                return [row[0] for row in cur.fetchall()]
    except Exception as exc:
        logger.warning(f"Asia | _get_cross_bot_held_etfs failed: {exc}")
        return []


# ── Entry rules ───────────────────────────────────────────────────────────────

def _should_enter(symbol: str) -> tuple[bool, dict]:
    """
    Entry criteria (same validated logic as bot2_spy_qqq and LatAm):
      1. EMA-50 > EMA-200  (uptrend)
      2. EMA-50 sloping up (today > 5 bars ago)
      3. Latest close > EMA-50

    Returns (should_enter, context-dict).
    """
    ohlcv = _yahoo_daily_ohlcv(symbol, days=250)
    if not ohlcv or len(ohlcv["closes"]) < EMA_SLOW + 5:
        logger.warning(f"Asia | {symbol}: insufficient OHLCV data for trend check")
        return False, {}

    closes  = ohlcv["closes"]
    highs   = ohlcv["highs"]
    lows    = ohlcv["lows"]
    current = closes[-1]

    ema_fast_now  = calculate_ema(closes, EMA_FAST)
    ema_slow_now  = calculate_ema(closes, EMA_SLOW)
    ema_fast_prev = calculate_ema(closes[:-5], EMA_FAST)
    atr           = calculate_atr(highs, lows, closes, period=14)

    if any(v is None for v in (ema_fast_now, ema_slow_now, ema_fast_prev, atr)):
        logger.warning(f"Asia | {symbol}: indicator calculation failed")
        return False, {}

    fast_above_slow  = ema_fast_now > ema_slow_now
    fast_sloping_up  = ema_fast_now > ema_fast_prev
    price_above_fast = current > ema_fast_now

    logger.info(
        f"Asia | {symbol} entry check — "
        f"price={current:.2f} EMA50={ema_fast_now:.2f} EMA200={ema_slow_now:.2f} "
        f"fast_above_slow={fast_above_slow} fast_up={fast_sloping_up} "
        f"price_above_fast={price_above_fast}"
    )

    if fast_above_slow and fast_sloping_up and price_above_fast:
        return True, {
            "current_price": current,
            "ema_fast":      ema_fast_now,
            "ema_slow":      ema_slow_now,
            "atr":           atr,
        }
    return False, {}


# ── Exit rules ─────────────────────────────────────────────────────────────────

def _should_exit_trend(symbol: str) -> tuple[bool, str]:
    """
    Trend-based exit: price closes below EMA-50 OR 5% cumulative 3-day drop.
    Trailing stop is handled by AlpacaEtfEngine.run_exit_checks().
    """
    ohlcv = _yahoo_daily_ohlcv(symbol, days=80)
    if not ohlcv or len(ohlcv["closes"]) < 4:
        return False, ""

    closes  = ohlcv["closes"]
    current = closes[-1]

    # Exit 1: price below EMA-50
    ema_fast_now = calculate_ema(
        closes[-EMA_FAST:] if len(closes) >= EMA_FAST else closes, EMA_FAST
    )
    if ema_fast_now and current < ema_fast_now:
        return True, f"price_below_ema50 (price={current:.2f} ema50={ema_fast_now:.2f})"

    # Exit 2: true 3-day cumulative drop — last 3 bars only
    if len(closes) >= 4:
        three_day_chg = (closes[-1] - closes[-4]) / closes[-4]
        if three_day_chg <= -MAX_3DAY_DROP_PCT:
            return True, f"3day_drop_{three_day_chg * 100:.1f}%"

    return False, ""


# ── Safe-close wrapper ────────────────────────────────────────────────────────

def _safe_close(engine: AlpacaEtfEngine, symbol: str, exit_reason: str,
                realised_pnl: Optional[float], bot_id: str) -> bool:
    """
    Close broker position. Returns True iff the position was actually closed.
    Sends Discord + degradation alerts on failure (C-1 pattern from bot2/LatAm).
    """
    try:
        db_pos = next((p for p in engine.get_db_positions(bot_id) if p["symbol"] == symbol), {})
        closed = engine.close_position(
            symbol,
            bot_id=bot_id,
            stop_order_id=db_pos.get("stop_order_id"),
            stop_price=float(db_pos["stop_price"]) if db_pos.get("stop_price") is not None else None,
        )
        if not closed:
            raise RuntimeError("close_position() returned False/None")
        return True
    except Exception as exc:
        logger.error(f"Asia | _safe_close({symbol}): {exc}")
        try:
            from notifications.discord import notify_capital_risk
            notify_capital_risk(
                f"🔴 Asia {symbol} ({exit_reason}): close_position() FAILED — "
                f"position remains **open at Alpaca**. DB row stays Active so next cycle retries.",
                symbol=symbol,
            )
        except Exception as _da:
            logger.error(f"Asia | Discord alert failed for {symbol}: {_da}")
        try:
            from core.degradation_tracker import record_degradation
            record_degradation(
                component="oracle",
                severity="critical",
                error_type="close_position_failed",
                message=(
                    f"{symbol} ({exit_reason}): close_position() returned False — "
                    f"position open at broker, DB stays Active, retry next cycle"
                ),
            )
        except Exception:
            pass
        return False


# ── Entry gate ────────────────────────────────────────────────────────────────

def _in_entry_window(now: Optional[datetime] = None) -> bool:
    """True if we are in the pre-close entry window AND haven't entered today."""
    global _last_entry_scan_date
    if now is None:
        now = datetime.now(timezone.utc)
    in_window = (
        now.hour == ENTRY_HOUR_UTC
        and ENTRY_MIN_START <= now.minute < ENTRY_MIN_END
    )
    already_ran = (_last_entry_scan_date == now.date())
    return in_window and not already_ran


# ── Main cycle ─────────────────────────────────────────────────────────────────

def run_asia_cycle(profile: dict, db_id: int) -> None:
    """
    Asia-Pacific ETF trend cycle. Called from runner.py on the oracle thread.
    Runs every LOOP_SLEEP_SECONDS (3600 = hourly); entry gate fires once/day at close.
    """
    global _last_entry_scan_date

    # Pause guard — always first
    if profile.get("BOT_PAUSED", False):
        logger.info("Asia | BOT_PAUSED=True — skipping cycle")
        return

    logger.info(
        f"Asia | === ASIA-PACIFIC TREND CYCLE — "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} ==="
    )

    # Alpaca connection
    try:
        engine = AlpacaEtfEngine(
            api_key    = profile.get("ALPACA_API_KEY", ""),
            secret_key = profile.get("ALPACA_SECRET_KEY", ""),
            base_url   = profile.get("ALPACA_BASE_URL",
                                     "https://paper-api.alpaca.markets"),
        )
    except Exception as exc:
        logger.error(f"Asia | Alpaca connection failed: {exc}")
        return

    account = engine.get_account()
    equity  = account["equity"]
    logger.info(
        f"Asia | Equity=${equity:,.2f} cash=${account['cash']:,.2f} "
        f"buying_power=${account['buying_power']:,.2f}"
    )

    live_positions = engine.get_positions()
    db_positions   = engine.get_db_positions(BOT_ID)
    engine.reconcile_protective_stops(BOT_ID, db_positions)

    logger.info(
        f"Asia | Positions: {len(live_positions)} live, {len(db_positions)} in DB"
    )

    # ── Exit checks ─────────────────────────────────────────────────────────
    # Multi-lot deduplication: process primary (earliest) lot fully,
    # secondary lots get trailing-stop DB updates only (mirrors bot2/LatAm pattern).
    _lots_by_sym: dict[str, list[dict]] = defaultdict(list)
    for _dp in db_positions:
        _lots_by_sym[_dp["symbol"]].append(_dp)
    for _sym in _lots_by_sym:
        _lots_by_sym[_sym].sort(key=lambda p: p.get("opened_at") or "")

    _closed_this_cycle: set[str] = set()

    for db_pos in db_positions:
        symbol     = db_pos["symbol"]
        lots       = _lots_by_sym[symbol]
        is_primary = (db_pos is lots[0])

        # Secondary lot already resolved by primary close this cycle
        if symbol in _closed_this_cycle:
            engine.record_close(BOT_ID, symbol, "multi_lot_primary_closed", None)
            logger.info(f"Asia | {symbol}: secondary lot DB-closed (primary closed Alpaca)")
            continue

        if not is_primary:
            live_p = next((p for p in live_positions if p["symbol"] == symbol), None)
            if live_p:
                engine.update_trailing_stop(
                    BOT_ID, symbol, live_p["current_price"], TRAIL_STOP_PCT
                )
            logger.info(f"Asia | {symbol}: secondary lot — TP skipped, trailing stop updated")
            continue

        # 1. Engine handles trailing stop + TP scale-outs (primary lot)
        exit_reason = engine.run_exit_checks(
            bot_id        = BOT_ID,
            db_position   = db_pos,
            live_positions= live_positions,
            trail_pct     = TRAIL_STOP_PCT,
        )
        if exit_reason:
            logger.info(f"Asia | EXIT {symbol}: {exit_reason}")
            live = next((p for p in live_positions if p["symbol"] == symbol), None)
            realised_pnl = live["unrealised_pnl_usd"] if live else None
            if _safe_close(engine, symbol, exit_reason, realised_pnl, BOT_ID):
                engine.record_close(BOT_ID, symbol, exit_reason, realised_pnl)
                _closed_this_cycle.add(symbol)
            live_positions = engine.get_positions()
            continue

        # 2. Trend-based exit (after min-hold)
        if engine.check_min_hold(db_pos):
            trend_exit, trend_reason = _should_exit_trend(symbol)
            if trend_exit:
                logger.info(f"Asia | TREND EXIT {symbol}: {trend_reason}")
                live = next((p for p in live_positions if p["symbol"] == symbol), None)
                realised_pnl = live["unrealised_pnl_usd"] if live else None
                if _safe_close(engine, symbol, trend_reason, realised_pnl, BOT_ID):
                    engine.record_close(BOT_ID, symbol, trend_reason, realised_pnl)
                    _closed_this_cycle.add(symbol)
                live_positions = engine.get_positions()

    # ── Entry scan (once per day, pre-close window) ──────────────────────────
    live_positions = engine.get_positions()

    # Empty-response guard: skip entry if Alpaca returns [] but DB has open rows
    _db_open_rows = engine.get_db_positions(BOT_ID)
    if not live_positions and _db_open_rows:
        _open_syms = [p["symbol"] for p in _db_open_rows]
        logger.warning(
            f"Asia | ENTRY GUARD: Alpaca returned 0 positions but DB has "
            f"{len(_db_open_rows)} open row(s) {_open_syms} — "
            f"skipping entry scan this cycle (likely transient API empty)"
        )
        try:
            from core.degradation_tracker import record_degradation
            record_degradation(
                component="oracle",
                severity="warning",
                error_type="alpaca_empty_response_guard",
                message=f"Asia entry guard: Alpaca empty but DB has {len(_db_open_rows)} rows — {_open_syms}",
            )
        except Exception:
            pass
        return

    if not _in_entry_window():
        logger.info("Asia | Outside entry window — exit-only cycle complete")
        # Park idle cash after exit-only cycle
        try:
            from sgov_parking import park_idle_cash as _sgov_park
            _exit_acct = engine.get_account()
            _sgov_park(engine, "Asia", engine.get_positions(), _exit_acct["cash"])
        except Exception as _sp_exc:
            logger.debug(f"Asia | SGOV park (exit-only path) error (non-fatal): {_sp_exc}")
        return

    logger.info("Asia | === ENTRY SCAN (pre-close window) ===")
    _last_entry_scan_date = datetime.now(timezone.utc).date()

    # Exclude SGOV cash-park from position counts, deployment math, and corr-cap.
    # This must happen AFTER the empty-response guard so that a SGOV-only account
    # doesn't falsely trigger the guard (Alpaca returning only SGOV ≠ API empty).
    from sgov_parking import filter_alpha_positions as _filter_alpha
    live_positions = _filter_alpha(live_positions)

    # Position cap
    current_count  = len(live_positions)
    currently_held = {p["symbol"] for p in live_positions}

    # Deployment guard
    deployed_notional = sum(p.get("market_value", 0) for p in live_positions)
    deployed_pct      = deployed_notional / equity if equity > 0 else 1.0
    if deployed_pct >= MAX_DEPLOYMENT:
        logger.info(
            f"Asia | Deployment cap reached: {deployed_pct:.1%} >= {MAX_DEPLOYMENT:.0%} — "
            f"skipping entry scan"
        )
        return

    # Cross-bot held ETFs for portfolio-level correlation cap
    cross_bot_held = _get_cross_bot_held_etfs(exclude_bot_id=BOT_ID)
    logger.info(f"Asia | Cross-bot held ETFs for corr-cap: {cross_bot_held}")

    candidates: list[dict] = []

    def _log_scan(
        symbol: str,
        *,
        regime: Optional[str],
        should_enter: bool,
        shares: float = 0,
        notional: Optional[float] = None,
        notional_pct: Optional[float] = None,
        corr_result: Optional[str] = None,
        final_decision: str = "DROPPED",
        drop_reason: Optional[str] = None,
    ) -> Optional[int]:
        return engine.record_scan_decision(
            bot_id=BOT_ID,
            symbol=symbol,
            regime=regime,
            should_enter=should_enter,
            shares=shares,
            notional=notional,
            notional_pct=notional_pct,
            corr_result=corr_result,
            final_decision=final_decision,
            drop_reason=drop_reason,
        )

    for symbol in UNIVERSE:
        if symbol in currently_held:
            logger.info(f"Asia | {symbol}: already held — skip")
            _log_scan(symbol, regime="HELD", should_enter=False, drop_reason="SHOULD_ENTER")
            continue

        if current_count >= MAX_POSITIONS:
            logger.info(f"Asia | Max positions ({MAX_POSITIONS}) reached — skip remaining")
            _log_scan(symbol, regime=None, should_enter=False, drop_reason="DEPLOYMENT")
            continue

        # ── Stage 1A: Per-ETF regional regime gate ────────────────────────
        regime_info = _regional_regime(symbol)
        regime      = regime_info.get("regime", "CRISIS")
        if regime in ("BEAR", "CRISIS"):
            logger.info(
                f"Asia | {symbol}: regime={regime} — blocked "
                f"(EMA50<EMA200 or CRISIS) [{regime_info.get('source', '?')}]"
            )
            _log_scan(symbol, regime=regime, should_enter=False, drop_reason="REGIME")
            continue
        logger.info(f"Asia | {symbol}: regime={regime} ✓")

        # ── Entry signal ─────────────────────────────────────────────────
        should_enter, ctx = _should_enter(symbol)
        if not should_enter:
            logger.info(f"Asia | {symbol}: no entry signal")
            _log_scan(symbol, regime=regime, should_enter=False, drop_reason="SHOULD_ENTER")
            continue

        entry_price = ctx["current_price"]

        # ── Stage 1B: Vol-scaled size ────────────────────────────────────
        shares = _vol_scaled_size(equity, symbol, entry_price)
        if shares <= 0:
            logger.warning(
                f"Asia | {symbol}: vol_scaled_size returned {shares} — "
                f"fail-CLOSED or too small, skipping"
            )
            _log_scan(
                symbol, regime=regime, should_enter=True, drop_reason="VOL_SIZE"
            )
            continue

        notional     = shares * entry_price
        notional_pct = notional / equity if equity > 0 else 1.0

        # Hard cap pre-flight (double-check)
        if notional_pct > VOL_SIZE_CAP:
            logger.warning(
                f"Asia | {symbol}: notional cap override "
                f"({notional_pct:.1%} > {VOL_SIZE_CAP:.0%}) — skipping"
            )
            _log_scan(
                symbol, regime=regime, should_enter=True, shares=shares,
                notional=notional, notional_pct=notional_pct,
                drop_reason="NOTIONAL_CAP",
            )
            continue

        # Deployment headroom check
        if deployed_pct + notional_pct > MAX_DEPLOYMENT:
            logger.info(
                f"Asia | {symbol}: would exceed MAX_DEPLOYMENT "
                f"({deployed_pct:.1%}+{notional_pct:.1%}>{MAX_DEPLOYMENT:.0%}) — skip"
            )
            _log_scan(
                symbol, regime=regime, should_enter=True, shares=shares,
                notional=notional, notional_pct=notional_pct,
                drop_reason="DEPLOYMENT",
            )
            continue

        # ── Stage 1C: Cross-bot + within-Asia correlation cap ────────────
        # Unlike LatAm (where EWZ/EWW/ECH are designed to be held together),
        # Asia ETFs can be highly correlated within the universe. EWY (Korea)
        # and EWT (Taiwan) are both semiconductor-heavy with ρ≈0.80 — the cap
        # must block the weaker when both signal at the same time.
        # Solution: include currently_held Asia ETFs in the cap check too.
        all_held = cross_bot_held + list(currently_held)
        allowed, reason = _corr_cap_check(symbol, all_held)
        if not allowed:
            logger.info(
                f"Asia | {symbol}: corr_cap blocked — {reason}"
            )
            _log_scan(
                symbol, regime=regime, should_enter=True, shares=shares,
                notional=notional, notional_pct=notional_pct,
                corr_result=reason, drop_reason="CORR_CAP",
            )
            continue

        logger.info(
            f"Asia | {symbol}: CANDIDATE ✓ — "
            f"regime={regime} signal=BULL shares={shares} "
            f"notional=${notional:,.0f} ({notional_pct:.1%})"
        )
        scan_id = _log_scan(
            symbol,
            regime=regime,
            should_enter=True,
            shares=shares,
            notional=notional,
            notional_pct=notional_pct,
            corr_result="allowed",
            final_decision="CANDIDATE",
        )
        candidates.append({
            "symbol":      symbol,
            "shares":      shares,
            "notional":    notional,
            "entry_price": entry_price,
            "regime":      regime,
            "ctx":         ctx,
            "scan_id":     scan_id,
        })

    # Sort by price momentum (strongest uptrend first; simple proxy: price vs EMA50)
    candidates.sort(
        key=lambda c: (c["ctx"]["current_price"] - c["ctx"]["ema_fast"])
                      / c["ctx"]["ema_fast"],
        reverse=True,
    )

    # Sell SGOV first to free cash before placing any entry orders
    if candidates:
        try:
            from sgov_parking import unpark_for_entry as _sgov_unpark
            _all_pos_with_sgov = engine.get_positions()
            _sgov_unpark(engine, "Asia", _all_pos_with_sgov)
        except Exception as _up_exc:
            logger.debug(f"Asia | SGOV unpark error (non-fatal): {_up_exc}")

    for cand in candidates:
        if current_count >= MAX_POSITIONS:
            break
        symbol      = cand["symbol"]
        shares      = cand["shares"]
        notional    = cand["notional"]
        entry_price = cand["entry_price"]
        scan_id     = cand.get("scan_id")

        logger.info(
            f"Asia | ENTERING {symbol}: {shares} shares @ "
            f"~${entry_price:.2f} = ${notional:,.0f}"
        )

        try:
            order = engine.buy_market(symbol, shares)
            if order:
                fill = engine.poll_entry_order(order["order_id"])
                filled_qty = fill["filled_qty"]
                filled_price = fill["filled_avg_price"]
                status = fill["status"]

                if status == "filled" and filled_qty > 0 and filled_price:
                    actual_notional = filled_qty * filled_price
                    recorded = engine.record_open(
                        bot_id         = BOT_ID,
                        symbol         = symbol,
                        direction      = "long",
                        qty            = filled_qty,
                        entry_price    = filled_price,
                        entry_atr      = cand["ctx"].get("atr"),
                        notional_usd   = actual_notional,
                        stop_price     = filled_price * (1 - TRAIL_STOP_PCT),
                        tp1_price      = filled_price * (1 + TP1_PCT),
                        tp2_price      = filled_price * (1 + TP2_PCT),
                        min_hold_days  = MIN_HOLD_DAYS,
                    )
                    engine.arm_protective_stop_after_fill(
                        BOT_ID, symbol, filled_price * (1 - TRAIL_STOP_PCT),
                        order["order_id"]
                    )
                    engine.record_scan_outcome(
                        scan_id, order_id=order["order_id"], order_outcome="FILLED"
                    )
                    if not recorded:
                        raise RuntimeError(
                            f"{symbol}: entry DB record failed after broker fill; "
                            "protective stop armed, manual reconciliation required"
                        )
                    logger.info(
                        f"Asia | {symbol}: FILLED qty={filled_qty} "
                        f"@ ${filled_price:.4f} + DB record created ✅"
                    )
                    current_count  += 1
                    currently_held.add(symbol)
                    deployed_pct   += actual_notional / equity
                    live_positions = engine.get_positions()
                elif filled_qty > 0 and filled_price:
                    engine.cancel_order(order["order_id"])
                    actual_notional = filled_qty * filled_price
                    recorded = engine.record_open(
                        bot_id=BOT_ID, symbol=symbol, direction="long",
                        qty=filled_qty, entry_price=filled_price,
                        entry_atr=cand["ctx"].get("atr"),
                        notional_usd=actual_notional,
                        stop_price=filled_price * (1 - TRAIL_STOP_PCT),
                        tp1_price=filled_price * (1 + TP1_PCT),
                        tp2_price=filled_price * (1 + TP2_PCT),
                        min_hold_days=MIN_HOLD_DAYS,
                    )
                    engine.record_scan_outcome(
                        scan_id, order_id=order["order_id"], order_outcome="PARTIAL"
                    )
                    logger.warning(
                        f"Asia | {symbol}: PARTIAL qty={filled_qty} "
                        f"@ ${filled_price:.4f}; remainder canceled"
                    )
                    if not recorded:
                        raise RuntimeError(
                            f"{symbol}: partial-fill DB record failed; manual reconciliation required"
                        )
                    engine.arm_protective_stop_after_fill(
                        BOT_ID, symbol, filled_price * (1 - TRAIL_STOP_PCT),
                        order["order_id"]
                    )
                    current_count += 1
                    currently_held.add(symbol)
                    deployed_pct += actual_notional / equity
                    live_positions = engine.get_positions()
                else:
                    engine.cancel_order(order["order_id"])
                    engine.record_scan_outcome(
                        scan_id, order_id=order["order_id"], order_outcome="UNFILLED"
                    )
                    logger.warning(
                        f"Asia | ENTRY UNFILLED {symbol} — cancelling, no DB row"
                    )
                    try:
                        from core.degradation_tracker import record_degradation
                        record_degradation(
                            component="oracle",
                            severity="high",
                            error_type="entry_order_unfilled",
                            message=f"Asia {symbol}: order {order['order_id']} "
                                    f"status={status}; canceled without DB row",
                        )
                    except Exception:
                        pass
            else:
                logger.error(f"Asia | {symbol}: buy_market() returned falsy — no DB record written")
                engine.record_scan_outcome(
                    scan_id, order_id=None, order_outcome="UNFILLED"
                )
        except Exception as exc:
            engine.record_scan_outcome(
                scan_id, order_id=order.get("order_id") if order else None,
                order_outcome="UNFILLED",
            )
            logger.error(f"Asia | {symbol}: entry FAILED: {exc}")
            try:
                from notifications.discord import notify_capital_risk
                notify_capital_risk(
                    f"🔴 Asia {symbol}: entry order FAILED — {exc}",
                    symbol=symbol,
                )
            except Exception:
                pass
            try:
                from core.degradation_tracker import record_degradation
                record_degradation(
                    component="oracle",
                    severity="high",
                    error_type="entry_order_failed",
                    message=f"Asia {symbol}: entry failed — {str(exc)[:200]}",
                )
            except Exception:
                pass

    # Park idle cash in SGOV after all entry/exit logic completes
    try:
        from sgov_parking import park_idle_cash as _sgov_park
        _park_acct = engine.get_account()
        _sgov_park(engine, "Asia", engine.get_positions(), _park_acct["cash"])
    except Exception as _park_exc:
        logger.debug(f"Asia | SGOV park error (non-fatal): {_park_exc}")

    logger.info(f"Asia | Cycle complete. Positions: {current_count}")
