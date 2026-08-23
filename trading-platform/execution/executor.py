"""
Trade Executor — Converts Allocations → Alpaca Orders
--------------------------------------------------------
v4.3 — Leveraged Risk Satellite + SPY EMA Anchor

Takes the validated RegimeAnalysisOutput (or CryptoAnalysisOutput) from the
analysis phase and executes each slot:

  1. Fetch current account equity + cash balance.
  2. Liquidate positions no longer in today's plan (exits).
  3. For each active slot, compute notional USD from kelly_fraction × equity.
  4. ── POSITION SIZING CAP ────────────────────────────────────────────────
     Hard cap: max notional per position = equity × 15%.
     If LLM requests more, cap at the 15% limit and leave remainder in cash.
     ──────────────────────────────────────────────────────────────────────
  5. ── MARGIN BLOCK ───────────────────────────────────────────────────────
     Track remaining cash across slot executions.
     If remaining_cash ≤ 0: BLOCK trade (no margin allowed).
     If notional > remaining_cash: cap notional to remaining_cash.
     ──────────────────────────────────────────────────────────────────────
  6. Skip zero-kelly slots.  SGOV slots with non-zero kelly (injected by
     the leveraged risk fence sweep) ARE executed to buy SGOV explicitly.
  7. ── RISK OVERLAY ───────────────────────────────────────────────────────
     IF Z-Score > 2.0 OR RSI(14) > 75 → asset is OVERHEATED:
       • Cut notional by 50%.  Reroute 50% to SGOV.
       • After fill: place ATR ratchet stop (2.0× std / 1.5× for LETFs).
     ──────────────────────────────────────────────────────────────────────
  8. Place market buy orders.
  9. Log every new trade to the SQLite journal for the RAG loop.
  10. Capture intended_price and actual_fill_price for slippage tracking.
  11. ── HIGH-YIELD VAULT ────────────────────────────────────────────────
     After all orders complete, run the profit sweep → JEPQ.
     Vault shares are never liquidated by this executor.
     ──────────────────────────────────────────────────────────────────────

Universe (v4.3):
  Equities:       SPY, QQQ, XLK, XLF, XLV, XLE, IWM   (DAY orders, min $100)
  Safe Havens:    TLT, IEF, GLD, SLV                    (DAY orders, min $100)
  Commodities:    USO, PDBC                              (DAY orders, min $100)
  Crypto Spot:    BTC/USD, ETH/USD                       (GTC orders, min $25)
  Leveraged Risk: TQQQ, SOXL, UPRO  ← NEW               (DAY orders, min $100,
                  Bull-only, 20% total cap, 1.5× ATR stop)
  Cash:           SGOV  (zero-kelly slots skipped; non-zero kelly slots bought)
  Vault:          JEPQ  (profit sweep only, LLM cannot sell)
"""

import math
import os
import sys
import time

from loguru import logger

# ── Shared core library ────────────────────────────────────────────────────────
_REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from shared.risk_profile import RiskProfile
from shared.exit_bracket import ExitBracket

from analysis.schemas import (
    RegimeAnalysisOutput, RegimeAllocationSlot,
    CryptoAnalysisOutput, CryptoAllocationSlot,
    is_crypto_pair,
    LEVERAGED_RISK_TICKERS,
)
from analysis.trade_journal import log_trade, update_trade_fill_price, update_trade_qty, close_trade
from execution.broker import (
    close_position,
    get_account,
    get_latest_price,
    get_order,
    get_positions,
    place_order,
    place_stop_order,
)
from execution.algo_scanner import MAX_LONG_SLOTS, MAX_SHORT_SLOTS
from execution.compliance import check_wash_sale, DRIP_ENABLED
from execution.ratchet_stop import initialise_ratchet_stop, delete_stop
from data.yfinance_client import get_cached_market_data
from portfolio.var_calculator import compute_daily_var

logger.info(f"Executor | DRIP_ENABLED={DRIP_ENABLED} (vault dividends accumulate as cash)")

MIN_NOTIONAL_USD    = 500.0
MIN_NOTIONAL_CRYPTO = 500.0
CASH_TICKER         = "SGOV"
VAULT_TICKER        = "JEPQ"

KNOWN_CRYPTO_SYMBOLS = {"BTCUSD", "ETHUSD"}

MAX_POSITION_PCT    = 0.15   # 15 % hard cap per individual position (v4.4)
MAX_LEVERAGED_PCT   = 0.20   # 20 % combined cap for leveraged_risk group

OVERHEATED_Z_THRESHOLD  = 2.0
OVERHEATED_RSI_THRESHOLD = 75.0
OVERHEAT_CUT_RATIO      = 0.50   # 50 % cut for overheated asset
OVERHEAT_STOP_PCT       = 0.02   # 2 % stop loss below fill price


def _normalize_symbol(ticker: str) -> str:
    return ticker.replace("/", "") if is_crypto_pair(ticker) else ticker


def _get_heat_metrics(ticker: str) -> dict:
    """Pull Z-score, RSI, is_overheated from the most recent market-data cache."""
    market_data = get_cached_market_data()
    if market_data is None:
        return {"z_score_200d": None, "rsi_14d": None, "is_overheated": False}
    d = market_data.get("by_ticker", {}).get(ticker, {})
    return {
        "z_score_200d":  d.get("z_score_200d"),
        "rsi_14d":       d.get("rsi_14d"),
        "is_overheated": bool(d.get("is_overheated", False)),
    }


def execute_allocations(
    output: RegimeAnalysisOutput | CryptoAnalysisOutput,
    dry_run: bool = False,
    regime_label: str | None = None,
    reserved_cash: float = 0.0,
    additional_protected: frozenset | None = None,
) -> dict:
    logger.info("=" * 60)
    logger.info("EXECUTION CYCLE STARTING")
    logger.info("=" * 60)

    acct = get_account()
    equity = acct["equity"]
    raw_cash = acct["cash"]
    max_position_usd = round(equity * MAX_POSITION_PCT, 2)

    current_positions = {p["symbol"]: p for p in get_positions()}
    logger.info(f"Current open positions: {list(current_positions.keys()) or 'none'}")

    # DB-backed active ticker guard — prevents duplicate positions when Alpaca
    # position feed lags behind order placement (race condition) or when the
    # allocator returns the same ticker across multiple slots.
    _db_active_tickers: set[str] = set()
    try:
        from db.postgres import get_conn, is_pg_available
        if is_pg_available():
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT DISTINCT ticker FROM trades WHERE status = 'Active'"
                    )
                    _db_active_tickers = {row[0] for row in cur.fetchall()}
    except Exception as _dat_exc:
        logger.warning(f"Executor | Could not load active tickers from DB: {_dat_exc}")

    # ── RiskProfile enforcement ───────────────────────────────────────────────
    # Build a RiskProfile using live account data and the Alpaca platform
    # constants (60/40 ring-fence, 15% per-position cap, 18% reserve).
    # Oracle v3.0: SGOV and JEPQ are no longer protected — existing positions
    # in those tickers will be treated as stale and closed on the next cycle.
    _SAFE_TICKERS: frozenset[str] = frozenset({"JEPQ"})  # JEPQ vault protected from stale rotation
    _deployed_usd = sum(
        p.get("market_value", 0.0)
        for p in current_positions.values()
        if p.get("symbol") not in _SAFE_TICKERS
    )
    _risk_profile = RiskProfile(
        total_equity=equity,
        deployed_usd=max(_deployed_usd, 0.0),
        ring_fenced_pct=0.60,
        deployable_pct=0.40,
        max_position_pct=MAX_POSITION_PCT,
        daily_loss_limit_pct=0.05,
        reserve_pct=0.18,
        name="alpaca",
    )
    if _risk_profile.is_breached():
        logger.warning(
            f"RiskProfile | Reserve breach detected before execution: "
            f"deployed=${_risk_profile.deployed_usd:,.2f} "
            f"ceiling=${_risk_profile.active_ceiling_usd():,.2f} "
            f"buffer=${_risk_profile.reserve_buffer_usd():,.2f} "
            f"— new positions will still be size-capped but breach is logged"
        )
    else:
        logger.info(
            f"RiskProfile | {_risk_profile.deployed_pct():.1f}% of ceiling deployed "
            f"(${_risk_profile.deployed_usd:,.0f} / ${_risk_profile.active_ceiling_usd():,.0f}) "
            f"| buffer=${_risk_profile.reserve_buffer_usd():,.0f}"
        )

    is_crypto_only = isinstance(output, CryptoAnalysisOutput)

    # Merge STF-protected positions: open trend positions that the exit manager
    # has NOT scheduled for exit are kept running and must never be stale-rotated.
    protected_symbols: set[str] = set(additional_protected or frozenset())

    active_tickers_raw = {
        a.ticker for a in output.allocations
        if a.ticker != CASH_TICKER and a.kelly_fraction > 0
    }
    active_symbols = {_normalize_symbol(t) for t in active_tickers_raw}

    # ── MARGIN BLOCK: compute available cash including exit proceeds ─────────
    # Positions being exited this cycle free up cash. Add their market value to
    # the settled cash balance so that the margin block is evaluated AFTER exits.
    # Oracle v3.1: SGOV no longer has a blanket exclusion from stale liquidation.
    # If SGOV is legitimately in the plan (non-zero kelly momentum slot), it will
    # be in active_symbols and excluded by the first condition.  Legacy SGOV held
    # from a previous strategy (zero signals / vault cash overflow) must be sold
    # so that Oracle has free capital to deploy into momentum signals.
    stale_symbols = {
        sym for sym in current_positions
        if sym not in active_symbols
        and sym not in protected_symbols
        and (not is_crypto_only or sym in KNOWN_CRYPTO_SYMBOLS)
    }
    # Audit fix H9: do NOT credit projected exit_proceeds before the exit
    # orders actually fill. Previously we credited the full market_value of
    # every stale_symbol — if an exit hung, partial-filled, or was skipped by
    # the min-hold gate inside _close_stale_positions, subsequent buy orders
    # sized against phantom cash and could push the account into margin.
    # We now seed remaining_cash from confirmed cash only; after
    # _close_stale_positions runs we re-add proceeds for symbols whose close
    # order was actually submitted (see post-close recompute below).
    projected_exit_proceeds = sum(
        current_positions[sym]["market_value"]
        for sym in stale_symbols
        if current_positions[sym]["market_value"] > 0
    )
    remaining_cash = max(raw_cash, 0.0)
    # Hard cap: can never spend more than total equity (prevents cross-day margin)
    remaining_cash = min(remaining_cash, equity)
    exit_proceeds = 0.0  # populated post-close (H9)

    # ── Afterhours capital holdback ──────────────────────────────────────────
    # If any afterhours crypto positions were unresolved at market reopen, their
    # capital is ring-fenced and cannot be redeployed into equity this cycle.
    if reserved_cash > 0:
        _before_holdback = remaining_cash
        remaining_cash = max(remaining_cash - reserved_cash, 0.0)
        logger.warning(
            f"Afterhours holdback | Reserved ${reserved_cash:,.2f} from unresolved crypto exits — "
            f"deployable cash reduced from ${_before_holdback:,.2f} to ${remaining_cash:,.2f}"
        )

    logger.info(
        f"Account equity: ${equity:,.2f} | settled_cash: ${raw_cash:,.2f} | "
        f"projected_exit_proceeds: ${projected_exit_proceeds:,.2f} (NOT yet credited \u2014 H9) | "
        f"available_cash: ${remaining_cash:,.2f} | "
        f"max_position (15%): ${max_position_usd:,.2f}"
    )

    if remaining_cash <= 0:
        logger.warning(
            f"MARGIN BLOCK | Available cash (incl. exit proceeds) is ${remaining_cash:,.2f} ≤ $0. "
            f"All new buy orders blocked to prevent margin trading."
        )

    results = {
        "equity":           equity,
        "dry_run":          dry_run,
        "crypto_only":      is_crypto_only,
        "placed":           [],
        "skipped":          [],
        "closed":           [],
        "errors":           [],
        "risk_overrides":   [],
        "vault_sweep":      None,
        "margin_blocks":    0,
        "cap_overrides":    0,
    }

    # ── Historical VaR Circuit Breaker ───────────────────────────────────────
    # Compute 1-day 95% VaR via historical simulation on the current positions.
    # If VaR exceeds the daily_loss_limit_pct, block all NEW entries this cycle.
    # Existing positions continue to run under ratchet stops — no forced exits.
    _risk_positions = [
        {"symbol": sym, "market_value": pos.get("market_value", 0.0)}
        for sym, pos in current_positions.items()
        if sym not in _SAFE_TICKERS
    ]
    # compute_daily_var returns VaR as a fraction of *invested* capital (not total equity).
    # Convert to USD and compare against the USD limit derived from total equity so that
    # partial deployment (e.g. 30% invested) doesn't erroneously trip the breaker.
    #   var_usd       = var_pct × invested_usd
    #   limit_usd     = daily_loss_limit_pct × total_equity
    _invested_usd  = sum(abs(float(p.get("market_value", 0.0) or 0.0)) for p in _risk_positions)
    try:
        _var_pct = compute_daily_var(_risk_positions, confidence=0.95)
    except Exception as _ve:
        logger.debug(f"Executor | VaR computation failed (non-fatal): {_ve}")
        _var_pct = 0.0

    _var_usd       = _var_pct * _invested_usd
    _var_limit_usd = _risk_profile.daily_loss_limit_pct * equity

    _var_tripped = (_var_limit_usd > 0) and (_var_usd > _var_limit_usd)
    if _var_tripped:
        logger.warning(
            f"VaR Circuit Breaker | 1-day 95% historical VaR = ${_var_usd:,.2f} "
            f"({_var_pct*100:.2f}% of ${_invested_usd:,.0f} invested) "
            f"exceeds daily limit ${_var_limit_usd:,.2f} "
            f"({_risk_profile.daily_loss_limit_pct*100:.0f}% of equity) "
            f"— all new entries BLOCKED this cycle | reason: var_circuit_breaker"
        )
    elif _var_usd > 0:
        logger.info(
            f"VaR | 1-day 95% historical VaR = ${_var_usd:,.2f} "
            f"({_var_pct*100:.2f}% of invested) — "
            f"limit ${_var_limit_usd:,.2f} ({_risk_profile.daily_loss_limit_pct*100:.0f}% of equity) — within bounds"
        )

    results = _close_stale_positions(
        current_positions, active_symbols, protected_symbols,
        results, dry_run, crypto_only=is_crypto_only,
    )

    # Audit fix H9: now that exits have been placed, credit proceeds ONLY for
    # symbols whose close_position() actually returned an order object.
    # Symbols that were skipped (min-hold gate) or errored out contribute $0.
    # In dry-run mode, credit projected proceeds since no real orders were placed.
    if dry_run:
        confirmed_exit_proceeds = projected_exit_proceeds
    else:
        confirmed_exit_proceeds = 0.0
        for _c in results.get("closed", []):
            _csym = _c.get("symbol")
            if _c.get("dry_run"):
                continue
            if not _c.get("order"):
                continue
            if _csym in current_positions:
                _mv = current_positions[_csym].get("market_value", 0.0) or 0.0
                if _mv > 0:
                    confirmed_exit_proceeds += float(_mv)
    remaining_cash = min(max(raw_cash, 0.0) + confirmed_exit_proceeds, equity)
    if reserved_cash > 0:
        remaining_cash = max(remaining_cash - reserved_cash, 0.0)
    exit_proceeds = confirmed_exit_proceeds  # for downstream telemetry/log

    if confirmed_exit_proceeds < projected_exit_proceeds - 0.01:
        logger.warning(
            f"H9 | Exit shortfall: projected ${projected_exit_proceeds:,.2f} but only "
            f"${confirmed_exit_proceeds:,.2f} of close orders confirmed — "
            f"sized buys will use the smaller (safer) cash figure."
        )
    logger.info(
        f"H9 | Post-close cash: settled=${raw_cash:,.2f} + "
        f"confirmed_exit_proceeds=${confirmed_exit_proceeds:,.2f} "
        f"(projected was ${projected_exit_proceeds:,.2f}) "
        f"\u2192 deployable=${remaining_cash:,.2f}"
    )

    # ── Oracle position-cap gate: counts from live Alpaca (source of truth) ──
    # Positive qty = long; negative qty = short.  Queried once per cycle; local
    # counters are incremented after each placement so multiple entries within
    # one cycle also respect the cap without re-querying Alpaca.
    _live_longs  = sum(1 for p in current_positions.values() if float(p.get("qty", 0)) > 0)
    _live_shorts = sum(1 for p in current_positions.values() if float(p.get("qty", 0)) < 0)
    logger.info(
        f"Cap gate | live_longs={_live_longs}/{MAX_LONG_SLOTS}  "
        f"live_shorts={_live_shorts}/{MAX_SHORT_SLOTS}  "
        f"available: long={max(0, MAX_LONG_SLOTS - _live_longs)}  "
        f"short={max(0, MAX_SHORT_SLOTS - _live_shorts)}"
    )

    # ── SPY regime gate (belt-and-suspenders, independent of scanner) ─────────
    # Recomputes SPY 200SMA + 5d brake from the same momentum cache.
    # Fail-safe: default to BLOCKED if cache is missing or data is too short.
    _exec_regime_long_ok = False
    try:
        from data.yfinance_client import get_cached_momentum_data as _get_mom_cache
        _mom_cache = _get_mom_cache()
        if _mom_cache:
            _exec_spy_closes = (_mom_cache.get("by_ticker", {}).get("SPY", {}).get("closes") or [])
            if len(_exec_spy_closes) >= 201:
                _exec_spy_close  = float(_exec_spy_closes[-1])
                _exec_spy_200sma = float(sum(_exec_spy_closes[-200:]) / 200)
                _exec_spy_5d_ret = float(_exec_spy_closes[-1]) / float(_exec_spy_closes[-6]) - 1
                _exec_regime_long_ok = (_exec_spy_close > _exec_spy_200sma) and (_exec_spy_5d_ret > -0.03)
                if not _exec_regime_long_ok:
                    _exec_conds = []
                    if _exec_spy_close <= _exec_spy_200sma:
                        _exec_conds.append(f"SPY {_exec_spy_close:.2f} ≤ 200SMA {_exec_spy_200sma:.2f}")
                    if _exec_spy_5d_ret <= -0.03:
                        _exec_conds.append(f"5d {_exec_spy_5d_ret:+.1%} ≤ -3%")
                    logger.warning(
                        f"Executor | REGIME GATE: longs blocked — {' + '.join(_exec_conds)}"
                    )
                else:
                    logger.info(
                        f"Executor | REGIME GATE: longs OK — "
                        f"SPY {_exec_spy_close:.2f} > 200SMA {_exec_spy_200sma:.2f}, "
                        f"5d {_exec_spy_5d_ret:+.1%} > -3%"
                    )
            else:
                logger.warning(
                    f"Executor | REGIME GATE: insufficient SPY data "
                    f"({len(_exec_spy_closes)} bars) — defaulting to BLOCKED (fail-safe)"
                )
        else:
            logger.warning(
                "Executor | REGIME GATE: momentum cache empty — defaulting to BLOCKED (fail-safe)"
            )
    except Exception as _rge:
        logger.warning(
            f"Executor | REGIME GATE: check failed ({_rge}) — defaulting to BLOCKED (fail-safe)"
        )

    # ── MSE CRISIS gate (belt-and-suspenders, independent of scanner) ─────────
    # Scanner already filters signals; executor re-checks as safety net.
    # CRISIS (SPY 20d return <= -12%): block ALL momentum_equity entries both sides.
    # Exception: TLT/GLD/IEF pass through as longs (already 0.5× sized by scanner).
    _exec_crisis_active   = True   # fail-safe: block entries until SPY data confirms NOT in crisis
    _exec_crisis_20d_ret: float | None = None
    _EXEC_MSE_SAFE_HAVENS = frozenset({"TLT", "GLD", "IEF"})
    try:
        if _mom_cache:
            _exec_spy_c = (_mom_cache.get("by_ticker", {}).get("SPY", {}).get("closes") or [])
            if len(_exec_spy_c) >= 21:
                _exec_crisis_20d_ret = float(_exec_spy_c[-1]) / float(_exec_spy_c[-21]) - 1
                _exec_crisis_active  = _exec_crisis_20d_ret <= -0.12
                if _exec_crisis_active:
                    logger.warning(
                        f"Executor | CRISIS GATE: SPY 20d {_exec_crisis_20d_ret:+.1%} <= -12% "
                        f"— momentum_equity entries blocked except "
                        f"{sorted(_EXEC_MSE_SAFE_HAVENS)}"
                    )
                else:
                    logger.debug(
                        f"Executor | CRISIS GATE: not active "
                        f"(SPY 20d={_exec_crisis_20d_ret:+.1%})"
                    )
            else:
                logger.warning(
                    f"Executor | CRISIS GATE: insufficient SPY data "
                    f"({len(_exec_spy_c)} bars, need 21) — fail-safe CRISIS active"
                )
        else:
            logger.warning(
                "Executor | CRISIS GATE: momentum cache empty — fail-safe CRISIS active"
            )
    except Exception as _cre:
        logger.warning(
            f"Executor | CRISIS GATE: check failed ({_cre}) — fail-safe CRISIS active"
        )

    for slot in sorted(output.allocations, key=lambda x: x.slot):
        _regime_for_slot = regime_label or (output.regime if hasattr(output, "regime") else None)
        _slot_asset = getattr(slot, "asset_class", None)
        _slot_side  = getattr(slot, "side", None)

        # ── Regime gate (belt-and-suspenders, longs only) ───────────────────────
        if _slot_asset == "momentum_equity" and _slot_side == "long" and not _exec_regime_long_ok:
            logger.warning(
                f"Regime gate | Slot {slot.slot}: {slot.ticker} → SKIP "
                f"(longs blocked by market regime)"
            )
            results["skipped"].append({
                "slot":   slot.slot,
                "ticker": slot.ticker,
                "reason": "regime_gate_long",
            })
            continue

        # ── CRISIS gate (belt-and-suspenders, momentum_equity only) ───────────
        if _exec_crisis_active and _slot_asset == "momentum_equity":
            if _slot_side == "short":
                logger.warning(
                    f"CRISIS gate | Slot {slot.slot}: {slot.ticker} → SKIP "
                    f"(shorts blocked during CRISIS)"
                )
                results["skipped"].append({
                    "slot":   slot.slot,
                    "ticker": slot.ticker,
                    "reason": "crisis_gate_short",
                })
                continue
            if _slot_side == "long" and slot.ticker not in _EXEC_MSE_SAFE_HAVENS:
                logger.warning(
                    f"CRISIS gate | Slot {slot.slot}: {slot.ticker} → SKIP "
                    f"(non-safe-haven long blocked during CRISIS)"
                )
                results["skipped"].append({
                    "slot":   slot.slot,
                    "ticker": slot.ticker,
                    "reason": "crisis_gate_non_safe_haven",
                })
                continue

        # ── Hard cap gate — refuse to exceed MAX_LONG_SLOTS / MAX_SHORT_SLOTS ─
        if _slot_asset == "momentum_equity":
            if _slot_side == "long" and _live_longs >= MAX_LONG_SLOTS:
                logger.warning(
                    f"Cap gate | Slot {slot.slot}: {slot.ticker} → SKIP "
                    f"(longs {_live_longs}/{MAX_LONG_SLOTS} — cap reached)"
                )
                results["skipped"].append({
                    "slot":   slot.slot,
                    "ticker": slot.ticker,
                    "reason": f"cap_gate_long ({_live_longs}/{MAX_LONG_SLOTS})",
                })
                continue
            if _slot_side == "short" and _live_shorts >= MAX_SHORT_SLOTS:
                logger.warning(
                    f"Cap gate | Slot {slot.slot}: {slot.ticker} → SKIP "
                    f"(shorts {_live_shorts}/{MAX_SHORT_SLOTS} — cap reached)"
                )
                results["skipped"].append({
                    "slot":   slot.slot,
                    "ticker": slot.ticker,
                    "reason": f"cap_gate_short ({_live_shorts}/{MAX_SHORT_SLOTS})",
                })
                continue

        _placed_before = len(results["placed"])
        results, remaining_cash = _execute_slot(
            slot, equity, max_position_usd, remaining_cash,
            current_positions, results, dry_run,
            var_tripped=_var_tripped,
            regime_at_entry=str(_regime_for_slot) if _regime_for_slot else None,
            db_active_tickers=_db_active_tickers,
        )
        if len(results["placed"]) > _placed_before:
            _db_active_tickers.add(_normalize_symbol(slot.ticker))
            if _slot_asset == "momentum_equity":
                if _slot_side == "long":
                    _live_longs += 1
                elif _slot_side == "short":
                    _live_shorts += 1

    # Oracle v3.0: vault sweep disabled — JEPQ physical buy removed.
    # Profit reserve is tracked as a DB ledger via add_oracle_profit_contribution()
    # called from the post-mortem after each winning trade closes.

    logger.info("=" * 60)
    logger.info("EXECUTION CYCLE COMPLETE")
    logger.info(
        f"  Placed:  {len(results['placed'])} orders | "
        f"Closed: {len(results['closed'])} positions | "
        f"Skipped: {len(results['skipped'])} | "
        f"Errors: {len(results['errors'])} | "
        f"Risk overrides: {len(results['risk_overrides'])} | "
        f"Cap overrides: {results['cap_overrides']} | "
        f"Margin blocks: {results['margin_blocks']}"
    )
    logger.info("=" * 60)

    return results


MIN_HOLD_HOURS = 4.0   # minimum time a position must be held before stale-rotation close


def _hours_since_entry(entry_time_raw) -> float | None:
    """Return hours held for a position, or None if entry_time is unavailable."""
    if not entry_time_raw:
        return None
    try:
        from datetime import datetime, timezone as _tz
        if isinstance(entry_time_raw, str):
            entry_dt = datetime.fromisoformat(entry_time_raw.replace("Z", "+00:00"))
        elif isinstance(entry_time_raw, datetime):
            entry_dt = entry_time_raw
        else:
            return None
        if entry_dt.tzinfo is None:
            entry_dt = entry_dt.replace(tzinfo=_tz.utc)
        return (datetime.now(_tz.utc) - entry_dt).total_seconds() / 3600.0
    except Exception:
        return None


def _close_stale_positions(
    current_positions: dict,
    active_symbols: set,
    protected_symbols: set,
    results: dict,
    dry_run: bool,
    crypto_only: bool = False,
) -> dict:
    stale = []
    for sym in current_positions:
        if sym in active_symbols:
            continue
        if sym in protected_symbols:
            logger.debug(f"Vault position {sym} is protected — never closing")
            continue
        if crypto_only and sym not in KNOWN_CRYPTO_SYMBOLS:
            continue
        stale.append(sym)

    if not stale:
        logger.info("No stale positions to close")
        return results

    for symbol in stale:
        pos = current_positions[symbol]

        # ── Minimum hold time gate (4 hours) ────────────────────────────────
        # Prevents stale-rotation closes from churning positions on every 15-min
        # cycle.  Positions held < MIN_HOLD_HOURS are protected from rotation
        # exits (stop/take-profit still fire independently through Alpaca orders).
        _hours_held = _hours_since_entry(pos.get("entry_time"))
        if _hours_held is not None and _hours_held < MIN_HOLD_HOURS:
            logger.info(
                f"Min-hold gate | {symbol} held {_hours_held:.1f}h < {MIN_HOLD_HOURS:.0f}h — "
                f"skipping stale-rotation close (SL/TP still active via broker orders)"
            )
            continue

        logger.warning(
            f"Closing stale position: {symbol} | "
            f"held={f'{_hours_held:.1f}h' if _hours_held else 'unknown'} | "
            f"value=${pos['market_value']:,.2f} | "
            f"P&L={pos['unrealized_pl']:+.2f}"
        )
        if dry_run:
            results["closed"].append({"symbol": symbol, "action": "would_close", "dry_run": True})
            continue
        try:
            order = close_position(symbol)
            results["closed"].append({"symbol": symbol, "order": order})
            # Remove any persisted ratchet stop for this position
            try:
                delete_stop(symbol)
            except Exception:
                pass
            # Record realized P&L in the trade journal
            try:
                realized_usd = float(pos.get("unrealized_pl", 0) or 0)
                cost_basis   = float(pos.get("cost_basis", 0) or 0)
                pnl_pct      = (realized_usd / abs(cost_basis) * 100) if cost_basis else 0.0
                # Look up the active trade_id for this ticker
                _trade_id: str | None = None
                _entry_time = None
                try:
                    from db.postgres import is_pg_available, get_conn as _gc
                    if is_pg_available():
                        with _gc() as _c:
                            with _c.cursor() as _cur:
                                _cur.execute(
                                    "SELECT trade_id, date FROM trades "
                                    "WHERE ticker = %s AND status = 'Active' "
                                    "ORDER BY date DESC LIMIT 1",
                                    (symbol,)
                                )
                                _row = _cur.fetchone()
                                if _row:
                                    _trade_id = _row[0]
                                    _entry_time = _row[1]
                except Exception as _le:
                    logger.debug(f"Executor | trade_id lookup failed for {symbol}: {_le}")
                if _trade_id:
                    from datetime import datetime, timezone as _tz
                    _hours = None
                    if _entry_time:
                        try:
                            _now = datetime.now(_tz.utc)
                            if hasattr(_entry_time, "tzinfo") and _entry_time.tzinfo:
                                _hours = (_now - _entry_time).total_seconds() / 3600
                            else:
                                _hours = (_now - _entry_time.replace(tzinfo=_tz.utc)).total_seconds() / 3600
                        except Exception:
                            pass
                    close_trade(
                        trade_id=_trade_id,
                        pnl_percentage=round(pnl_pct, 4),
                        realized_pnl=round(realized_usd, 2),
                        exit_reason="algo_cover",
                        time_in_trade_hours=round(_hours, 2) if _hours else None,
                        bot_id="oracle",
                    )
                    logger.info(
                        f"Trade journal | Recorded close for {symbol}: "
                        f"pnl={pnl_pct:+.2f}% / ${realized_usd:+.2f}"
                    )
            except Exception as _je:
                logger.warning(f"Executor | close_trade journal write failed for {symbol}: {_je}")
                # B-5 fix: direct Discord alert + tag the trade row for audit/dedup.
                try:
                    from notifications.discord import notify_capital_risk
                    notify_capital_risk(
                        f"🔴 {symbol}: Alpaca closed but trade journal write FAILED"
                        f" — DB may still show Active, manual check needed",
                        symbol=symbol,
                    )
                except Exception:
                    pass
                if _trade_id:
                    try:
                        from db.postgres import _acquire_healthy_conn
                        _conn = _acquire_healthy_conn()
                        with _conn.cursor() as _cur:
                            _cur.execute(
                                "UPDATE trades SET exit_reason='journal_write_failed'"
                                " WHERE trade_id=%s",
                                (_trade_id,),
                            )
                        _conn.commit()
                        _conn.close()
                    except Exception as _ue:
                        logger.error(
                            f"Executor | Could not tag trade_id={_trade_id} exit_reason: {_ue}"
                        )
        except Exception as exc:
            logger.error(f"Failed to close {symbol}: {exc}")
            results["errors"].append({"symbol": symbol, "error": str(exc)})

    return results


def _execute_slot(
    slot: RegimeAllocationSlot | CryptoAllocationSlot,
    equity: float,
    max_position_usd: float,
    remaining_cash: float,
    current_positions: dict,
    results: dict,
    dry_run: bool,
    var_tripped: bool = False,
    regime_at_entry: str | None = None,
    db_active_tickers: set = frozenset(),
) -> tuple[dict, float]:
    ticker = slot.ticker
    symbol = _normalize_symbol(ticker)
    is_crypto = is_crypto_pair(ticker)

    # Zero-kelly slots are always skipped (SGOV placeholders from conviction threshold)
    if slot.kelly_fraction == 0.0:
        logger.info(f"Slot {slot.slot}: {ticker:10s} → SKIP (zero kelly)")
        results["skipped"].append({"slot": slot.slot, "ticker": ticker, "reason": "zero_kelly"})
        return results, remaining_cash

    # ── VaR Circuit Breaker — block ALL new entries when tripped ─────────────
    # When VaR exceeds the daily loss limit, every new allocation is suspended
    # for this cycle.  SGOV (kelly=0) is already caught by the zero-kelly check
    # above; other tickers including defensive/vault allocations are skipped here.
    if var_tripped:
        logger.info(
            f"Slot {slot.slot}: {ticker:10s} → SKIP "
            f"(var_circuit_breaker — new entries blocked)"
        )
        results["skipped"].append({
            "slot":   slot.slot,
            "ticker": ticker,
            "reason": "var_circuit_breaker",
        })
        return results, remaining_cash

    # ── SGOV with non-zero kelly: Leveraged Fence Sweep ─────────────────────
    # These slots are injected by the allocator when the leveraged_risk group
    # exceeds the 20% cap. Buy SGOV directly — no heat/wash-sale checks needed.
    if ticker == CASH_TICKER:
        notional_usd = min(equity * slot.kelly_fraction, max(remaining_cash, 0.0))
        if notional_usd >= MIN_NOTIONAL_USD:
            logger.info(
                f"Slot {slot.slot}: {CASH_TICKER:10s} → SGOV SWEEP "
                f"(leveraged fence excess kelly={slot.kelly_fraction:.1%}, ${notional_usd:,.2f})"
            )
            if not dry_run:
                try:
                    order = place_order(ticker=CASH_TICKER, notional_usd=notional_usd)
                    log_trade(
                        trade_id=order["id"],
                        ticker=CASH_TICKER,
                        asset_class="cash",
                        conviction_score=1.0,
                        original_thesis=slot.thesis,
                        regime_at_entry=regime_at_entry,
                    )
                    results["placed"].append({
                        "slot":         slot.slot,
                        "ticker":       CASH_TICKER,
                        "notional_usd": notional_usd,
                        "order_id":     order["id"],
                        "reason":       "leveraged_fence_sweep",
                    })
                    remaining_cash -= notional_usd
                except Exception as exc:
                    logger.warning(f"SGOV fence sweep failed for slot {slot.slot}: {exc}")
                    results["errors"].append({
                        "slot": slot.slot, "ticker": CASH_TICKER, "error": str(exc),
                    })
            else:
                results["placed"].append({
                    "slot":         slot.slot,
                    "ticker":       CASH_TICKER,
                    "notional_usd": notional_usd,
                    "reason":       "leveraged_fence_sweep",
                    "dry_run":      True,
                })
                remaining_cash -= notional_usd
        else:
            results["skipped"].append({
                "slot": slot.slot, "ticker": CASH_TICKER,
                "reason": f"sgov_sweep_below_min (${notional_usd:.2f})",
            })
        return results, remaining_cash

    notional_usd = equity * slot.kelly_fraction
    min_notional = MIN_NOTIONAL_CRYPTO if is_crypto else MIN_NOTIONAL_USD

    # ── STEP 2: 10% Hard Cap ────────────────────────────────────────────────
    if notional_usd > max_position_usd:
        logger.warning(
            f"📏 Cap Override | Slot {slot.slot}: {ticker} | "
            f"LLM requested ${notional_usd:,.2f} (kelly={slot.kelly_fraction:.1%}) → "
            f"capped at ${max_position_usd:,.2f} (10% of equity). "
            f"${notional_usd - max_position_usd:,.2f} left in cash."
        )
        notional_usd = max_position_usd
        results["cap_overrides"] += 1

    # ── STEP 3: Margin Block ─────────────────────────────────────────────────
    if remaining_cash <= 0:
        logger.warning(
            f"🚫 Margin Block | Slot {slot.slot}: {ticker} | "
            f"No cash remaining (${remaining_cash:,.2f}). Trade blocked."
        )
        results["margin_blocks"] += 1
        results["skipped"].append({
            "slot": slot.slot, "ticker": ticker,
            "reason": f"margin_block (remaining_cash=${remaining_cash:,.2f})",
        })
        return results, remaining_cash

    # ── STEP 3a: 5% Cash Floor Gate ─────────────────────────────────────────
    # FIX (Issue #7): Never deploy when available cash < 5% of equity.
    # This prevents Oracle from going margin-negative (cash < $0) by stopping
    # new entries once the cash cushion is nearly exhausted.
    _cash_floor = equity * 0.05
    if remaining_cash < _cash_floor:
        logger.warning(
            f"🛑 Cash Gate | Slot {slot.slot}: {ticker} | "
            f"Remaining cash ${remaining_cash:,.2f} < 5% floor ${_cash_floor:,.2f} "
            f"(equity=${equity:,.2f}). Blocking new entry to preserve cash cushion."
        )
        results["margin_blocks"] += 1
        results["skipped"].append({
            "slot": slot.slot, "ticker": ticker,
            "reason": f"cash_gate_5pct (remaining=${remaining_cash:,.2f}, floor=${_cash_floor:,.2f})",
        })
        return results, remaining_cash

    if notional_usd > remaining_cash:
        logger.warning(
            f"💰 Cash Cap | Slot {slot.slot}: {ticker} | "
            f"notional ${notional_usd:,.2f} > remaining cash ${remaining_cash:,.2f}. "
            f"Capping to available cash."
        )
        notional_usd = remaining_cash

    if notional_usd < min_notional:
        logger.info(
            f"Slot {slot.slot}: {ticker:10s} → SKIP "
            f"(${notional_usd:.2f} < ${min_notional} min notional)"
        )
        results["skipped"].append({
            "slot": slot.slot, "ticker": ticker,
            "reason": f"below_min_notional (${notional_usd:.2f})",
        })
        return results, remaining_cash

    # Primary guard: Alpaca broker position feed
    if symbol in current_positions:
        existing_value = current_positions[symbol]["market_value"]
        target_value   = notional_usd
        diff_pct = abs(target_value - existing_value) / existing_value if existing_value > 0 else 1.0

        if diff_pct < 0.10:
            logger.info(
                f"Slot {slot.slot}: {ticker:10s} → HOLD "
                f"(existing=${existing_value:,.2f}, target=${target_value:,.2f}, diff={diff_pct:.1%})"
            )
            results["skipped"].append({"slot": slot.slot, "ticker": ticker,
                                       "reason": f"already_held_within_10pct (diff={diff_pct:.1%})"})
            return results, remaining_cash

    # Secondary guard: DB active trades table — catches race conditions where
    # Alpaca position feed hasn't updated yet after a recent order placement.
    if symbol in db_active_tickers:
        logger.info(
            f"Slot {slot.slot}: {ticker:10s} → SKIP (active_in_db — Alpaca feed may be lagging)"
        )
        results["skipped"].append({"slot": slot.slot, "ticker": ticker,
                                   "reason": "active_in_db_dedup"})
        return results, remaining_cash

    heat = _get_heat_metrics(ticker)
    overheated = heat["is_overheated"]
    z_score    = heat["z_score_200d"]
    rsi        = heat["rsi_14d"]

    sgov_notional = 0.0

    if overheated:
        original_notional = notional_usd
        notional_usd  = round(notional_usd * OVERHEAT_CUT_RATIO, 2)
        sgov_notional = round(original_notional - notional_usd, 2)
        trigger = []
        if z_score is not None and z_score > OVERHEATED_Z_THRESHOLD:
            trigger.append(f"Z-score={z_score:+.2f} > {OVERHEATED_Z_THRESHOLD}")
        if rsi is not None and rsi > OVERHEATED_RSI_THRESHOLD:
            trigger.append(f"RSI={rsi:.1f} > {OVERHEATED_RSI_THRESHOLD}")
        logger.warning(
            f"⚠ Risk Overlay | {ticker} OVERHEATED ({', '.join(trigger)}) — "
            f"cutting ${original_notional:,.2f} → ${notional_usd:,.2f} "
            f"(${sgov_notional:,.2f} rerouted to {CASH_TICKER})"
        )
        results["risk_overrides"].append({
            "slot":              slot.slot,
            "ticker":            ticker,
            "z_score":           z_score,
            "rsi":               rsi,
            "original_notional": original_notional,
            "cut_notional":      notional_usd,
            "sgov_rerouted":     sgov_notional,
        })

    logger.info(
        f"Slot {slot.slot}: {ticker:10s} | "
        f"kelly={slot.kelly_fraction:.1%} | "
        f"notional=${notional_usd:,.2f} | "
        f"conv={slot.conviction_score:.0%}"
        + (f" | ⚠ OVERHEATED (2% stop)" if overheated else "")
    )

    # ── STEP 5: Wash-Sale Compliance Check ──────────────────────────────────
    # Before placing any buy, verify we're not repurchasing a substantially
    # identical security within 30 days of a realised loss.
    if not is_crypto:  # wash-sale rule applies to securities, not crypto
        ws = check_wash_sale(ticker)
        if ws["blocked"]:
            logger.warning(
                f"⚖ Wash-Sale Block | Slot {slot.slot}: {ticker} — {ws['reason']}"
            )
            results["skipped"].append({
                "slot":   slot.slot,
                "ticker": ticker,
                "reason": f"wash_sale_compliance: {ws['reason']}",
            })
            return results, remaining_cash

    intended_price = get_latest_price(ticker)
    if intended_price:
        logger.info(f"  → Intended price (pre-order snapshot): ${intended_price:.4f}")

    if dry_run:
        results["placed"].append({
            "slot":           slot.slot,
            "ticker":         ticker,
            "notional_usd":   notional_usd,
            "kelly":          slot.kelly_fraction,
            "conviction":     slot.conviction_score,
            "intended_price": intended_price,
            "overheated":     overheated,
            "dry_run":        True,
        })
        if overheated and sgov_notional >= 1.0:
            results["placed"].append({
                "slot":         f"{slot.slot}a",
                "ticker":       CASH_TICKER,
                "notional_usd": sgov_notional,
                "reason":       "overheat_reroute",
                "dry_run":      True,
            })
        remaining_cash -= notional_usd
        return results, remaining_cash

    try:
        order = place_order(ticker=ticker, notional_usd=notional_usd)
        order_id = order["id"]
        # Prefer filled_qty if already available; fall back to requested qty.
        # For notional orders qty may be None/0 at placement — _poll_fill_price
        # will update it once the fill confirms.
        _order_qty = order.get("filled_qty") or order.get("qty") or None

        log_trade(
            trade_id=order_id,
            ticker=ticker,
            asset_class=slot.asset_class,
            conviction_score=slot.conviction_score,
            original_thesis=slot.thesis,
            intended_price=intended_price,
            regime_at_entry=regime_at_entry,
            qty=_order_qty,
        )
        logger.info(f"  → Logged to journal: trade_id={order_id}")

        # Record immutable entry timestamp for 5-day inverse ETF exit rule.
        # ON CONFLICT DO NOTHING: only the FIRST open timestamps — ratchet
        # updates and re-runs never overwrite it.
        try:
            from db.postgres import record_position_entry
            record_position_entry(ticker, entry_price=intended_price)
        except Exception as _et_exc:
            # B-12 fix: debug→warning + degradation so this is grep-visible.
            # 5-day inverse-ETF exit rule is blind for this position until resolved.
            logger.warning(
                f"Executor | record_position_entry failed for {ticker}: {_et_exc} "
                f"— 5-day inverse-ETF exit rule blind for this position"
            )
            try:
                from core.degradation_tracker import record_degradation
                record_degradation(
                    component="executor_entry",
                    severity="medium",
                    error_type="entry_timestamp_lost",
                    message=f"entry_timestamp_lost — 5-day inverse-ETF rule blind for {ticker}",
                    detail=str(_et_exc)[:300],
                )
            except Exception:
                pass

        remaining_cash -= notional_usd

        actual_fill_price, poll_status = _poll_fill_price(order_id, ticker)

        if poll_status in ("canceled", "rejected", "expired"):
            try:
                from analysis.trade_journal import delete_trade
                delete_trade(order_id)
                logger.warning(
                    f"Executor | Order {order_id} {poll_status} by Alpaca for {ticker} — "
                    f"DB row deleted to prevent phantom-Active drift"
                )
            except Exception as exc:
                logger.error(f"Executor | Failed to rollback DB row for {order_id}: {exc}")
        elif poll_status == "timeout":
            logger.warning(
                f"Executor | Fill poll timed out for {ticker} order {order_id} after 60s. "
                f"Order may still fill — DB row left Active with NULL fill_price. "
                f"Will need post-hoc reconciliation."
            )

        slippage_info = ""
        if actual_fill_price and intended_price:
            slippage_pct = (actual_fill_price - intended_price) / intended_price * 100
            slippage_info = f" | slippage={slippage_pct:+.4f}%"

        result_entry = {
            "slot":              slot.slot,
            "ticker":            ticker,
            "notional_usd":      notional_usd,
            "order_id":          order_id,
            "order_status":      order["status"],
            "intended_price":    intended_price,
            "actual_fill_price": actual_fill_price,
            "overheated":        overheated,
        }
        results["placed"].append(result_entry)
        logger.info(
            f"  → Fill price: ${actual_fill_price or 'pending'}{slippage_info} | "
            f"remaining cash: ${remaining_cash:,.2f}"
        )

        if actual_fill_price and actual_fill_price > 0 and poll_status not in ("canceled", "rejected", "expired"):
            _place_ratchet_stop(ticker, notional_usd, actual_fill_price, results, dry_run)

        if overheated and sgov_notional >= MIN_NOTIONAL_USD:
            _reroute_to_sgov(slot, sgov_notional, results, regime_at_entry=regime_at_entry)

    except Exception as exc:
        logger.error(f"Slot {slot.slot}: order failed for {ticker}: {exc}")
        results["errors"].append({
            "slot":   slot.slot,
            "ticker": ticker,
            "error":  str(exc),
        })

    return results, remaining_cash


def _place_ratchet_stop(
    ticker: str,
    notional_usd: float,
    fill_price: float,
    results: dict,
    dry_run: bool = False,
) -> None:
    """
    ATR Ratchet Stop — replaces the static 2% stop.
    Leveraged ETFs (TQQQ/SOXL/UPRO) use 1.5×ATR (auto-detected in ratchet_stop module).
    Standard tickers use 2.0×ATR(14).
    The stop is persisted and can only be ratcheted UP on future cycles.
    Falls back to a 2% static stop (FALLBACK_STOP_PCT) if ATR is unavailable.

    ExitBracket is used to compute the expected stop/take-profit/trail levels
    for logging and audit purposes.  The actual stop order placement delegates to
    initialise_ratchet_stop() in ratchet_stop.py (the existing source of truth for
    ATR computation and GTC order management).
    """
    from execution.ratchet_stop import FALLBACK_STOP_PCT, ATR_MULTIPLIER, LEVERAGED_ATR_MULTIPLIER

    raw_qty  = notional_usd / fill_price
    qty      = math.floor(raw_qty)           # whole shares only — Alpaca GTC rejects fractional qty
    is_letf  = ticker in LEVERAGED_RISK_TICKERS
    atr_mult = LEVERAGED_ATR_MULTIPLIER if is_letf else ATR_MULTIPLIER
    mult_label = f"{atr_mult}×ATR {'[LETF tighter stop]' if is_letf else ''}"

    if qty < 1:
        logger.error(
            f"Risk Overlay | {ticker}: sub-1-share after floor "
            f"(notional=${notional_usd:.2f} / fill=${fill_price:.4f} = {raw_qty:.4f}) "
            f"— GTC stop cannot be placed"
        )
        try:
            from core.degradation_tracker import record_degradation
            record_degradation(
                component="oracle_stop",
                severity="high",
                error_type="sub_1_share_no_broker_stop",
                message=f"{ticker}: sub-1-share ({raw_qty:.4f} shares) — broker GTC stop not placed",
            )
        except Exception:
            pass
        return

    # ── ExitBracket: compute expected exit levels for logging ─────────────────
    # The ATR value is not yet known (initialise_ratchet_stop fetches it); use
    # the fixed-percentage fallback for the bracket preview.
    _bracket = ExitBracket(
        entry_price=fill_price,
        direction="long",
        stop_loss_pct=FALLBACK_STOP_PCT,
        take_profit_pct=FALLBACK_STOP_PCT * 3,  # 3:1 risk-reward target
        trail_pct=FALLBACK_STOP_PCT * 2.5,
        atr=None,
        atr_multiplier=atr_mult,
    )
    _sl_preview, _tp_preview, _trail_preview = _bracket.compute()
    logger.warning(
        f"⚠ Risk Overlay | Initialising ATR ratchet stop for {ticker}: "
        f"fill=${fill_price:.4f} qty={qty:.6f} | multiplier={mult_label} | "
        f"bracket preview → SL=${_sl_preview:.4f} TP=${_tp_preview:.4f} "
        f"trail@${_trail_preview:.4f} (ATR-based stop will override if available)"
    )
    try:
        stop_result = initialise_ratchet_stop(
            ticker=ticker,
            fill_price=fill_price,
            qty=qty,
            dry_run=dry_run,
        )
        if stop_result:
            _stop_data = {
                "stop_order":            stop_result.get("order"),
                "stop_price":            stop_result.get("stop_price"),
                "atr":                   stop_result.get("atr"),
                "exit_bracket_preview":  _bracket.to_dict(),
            }
            if results.get("risk_overrides"):
                results["risk_overrides"][-1].update(_stop_data)
            else:
                results.setdefault("ratchet_stop_results", []).append(
                    {"ticker": ticker, **_stop_data}
                )
    except Exception as exc:
        logger.error(f"Risk Overlay | Ratchet stop init failed for {ticker}: {exc} — position unprotected")
        try:
            from core.degradation_tracker import record_degradation
            record_degradation(
                component="oracle_stop",
                severity="high",
                error_type="broker_stop_rejected",
                message=f"{ticker}: executor GTC stop placement failed — position unprotected",
                detail=str(exc)[:500],
            )
        except Exception:
            pass
        # B-3 fix: direct Discord alert — fires even if degradation tracker is down.
        try:
            from notifications.discord import notify_capital_risk
            notify_capital_risk(
                f"🔴 {ticker}: ratchet stop init FAILED after buy — position unprotected until next cycle",
                symbol=ticker,
            )
        except Exception:
            pass
        if results.get("risk_overrides"):
            results["risk_overrides"][-1]["stop_order_error"] = str(exc)


def _reroute_to_sgov(
    slot: RegimeAllocationSlot | CryptoAllocationSlot,
    sgov_notional: float,
    results: dict,
    regime_at_entry: str | None = None,
) -> None:
    """Buy SGOV with the capital cut from an overheated slot."""
    logger.info(f"  → Risk reroute: buying {CASH_TICKER} ${sgov_notional:,.2f}")
    try:
        sgov_order = place_order(ticker=CASH_TICKER, notional_usd=sgov_notional)
        log_trade(
            trade_id=sgov_order["id"],
            ticker=CASH_TICKER,
            asset_class="cash",
            conviction_score=1.0,
            original_thesis=f"Risk overlay reroute from overheated slot {slot.slot} ({slot.ticker})",
            regime_at_entry=regime_at_entry,
        )
        results["placed"].append({
            "slot":       f"{slot.slot}a",
            "ticker":     CASH_TICKER,
            "notional_usd": sgov_notional,
            "order_id":   sgov_order["id"],
            "reason":     "overheat_reroute",
        })
    except Exception as exc:
        logger.warning(f"Risk reroute to {CASH_TICKER} failed: {exc}")
        results["errors"].append({"ticker": CASH_TICKER, "error": f"SGOV reroute failed: {exc}"})


def _poll_fill_price(order_id: str, ticker: str, max_wait: float = 60.0) -> tuple[float | None, str]:
    start = time.time()
    poll_interval = 0.5

    while (time.time() - start) < max_wait:
        try:
            order_data = get_order(order_id)
            fill_price = order_data.get("filled_avg_price")
            if fill_price is not None:
                update_trade_fill_price(order_id, fill_price)
                _filled_qty = order_data.get("filled_qty")
                if _filled_qty:
                    update_trade_qty(order_id, float(_filled_qty))
                return (fill_price, "filled")
            terminal_status = order_data.get("status")
            if terminal_status in ("canceled", "expired", "rejected"):
                logger.warning(f"Order {order_id} ({ticker}) ended with status={terminal_status}")
                return (None, terminal_status)
        except Exception as exc:
            logger.warning(f"Poll fill price error for {ticker}: {exc}")
        time.sleep(poll_interval)

    logger.warning(f"Fill price not available within {max_wait}s for {ticker} (order_id={order_id})")
    return (None, "timeout")


# ── Afterhours Capital Guard ───────────────────────────────────────────────

AFTERHOURS_CASH_CAP: float = 0.80   # Deploy at most 80% of idle cash after-hours


def get_afterhours_available_cash() -> float:
    """
    Return the capital available for afterhours crypto deployment.

    Formula (per spec):
        min(settled_cash, total_equity * AFTERHOURS_CASH_CAP)

    SGOV holdings are noted but the formula uses the raw settled_cash from
    Alpaca (which already excludes SGOV market value — SGOV is held in the
    account's portfolio but the cash balance reflects liquid cash only).
    The cap (default 80%) prevents the cycle from deploying more than
    80% of total equity, providing a minimum buffer.

    Returns 0.0 on any error so the afterhours cycle can gracefully skip.
    """
    try:
        acct = get_account()
        equity = acct["equity"]
        raw_cash = acct["cash"]

        settled_cash = max(raw_cash, 0.0)
        cap_limit = equity * AFTERHOURS_CASH_CAP
        available = min(settled_cash, cap_limit)

        positions = get_positions()
        sgov_value = sum(
            p.get("market_value", 0.0)
            for p in positions
            if p.get("symbol") == "SGOV"
        )

        logger.info(
            f"Afterhours capital guard | equity=${equity:,.2f} "
            f"settled_cash=${settled_cash:,.2f} sgov_held=${sgov_value:,.2f} "
            f"cap_limit(80%)=${cap_limit:,.2f} available=${available:,.2f}"
        )
        return available
    except Exception as exc:
        logger.error(f"Afterhours capital guard | Failed to compute available cash: {exc}")
        return 0.0
