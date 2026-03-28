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
     Hard cap: max notional per position = equity × 10%.
     If LLM requests more, cap at the 10% limit and leave remainder in cash.
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

import time

from loguru import logger

from analysis.schemas import (
    RegimeAnalysisOutput, RegimeAllocationSlot,
    CryptoAnalysisOutput, CryptoAllocationSlot,
    is_crypto_pair,
    LEVERAGED_RISK_TICKERS,
)
from analysis.trade_journal import log_trade, update_trade_fill_price
from execution.broker import (
    close_position,
    get_account,
    get_latest_price,
    get_order,
    get_positions,
    place_order,
    place_stop_order,
)
from execution.compliance import check_wash_sale, DRIP_ENABLED
from execution.ratchet_stop import initialise_ratchet_stop, delete_stop
from data.yfinance_client import get_cached_market_data

logger.info(f"Executor | DRIP_ENABLED={DRIP_ENABLED} (vault dividends accumulate as cash)")

MIN_NOTIONAL_USD    = 100.0
MIN_NOTIONAL_CRYPTO = 25.0
CASH_TICKER         = "SGOV"
VAULT_TICKER        = "JEPQ"

KNOWN_CRYPTO_SYMBOLS = {"BTCUSD", "ETHUSD"}

MAX_POSITION_PCT    = 0.10   # 10 % hard cap per position
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

    is_crypto_only = isinstance(output, CryptoAnalysisOutput)

    protected_symbols = {_normalize_symbol(VAULT_TICKER)}

    active_tickers_raw = {
        a.ticker for a in output.allocations
        if a.ticker != CASH_TICKER and a.kelly_fraction > 0
    }
    active_symbols = {_normalize_symbol(t) for t in active_tickers_raw}

    # ── MARGIN BLOCK: compute available cash including exit proceeds ─────────
    # Positions being exited this cycle free up cash. Add their market value to
    # the settled cash balance so that the margin block is evaluated AFTER exits.
    stale_symbols = {
        sym for sym in current_positions
        if sym not in active_symbols
        and sym != CASH_TICKER
        and sym not in protected_symbols
        and (not is_crypto_only or sym in KNOWN_CRYPTO_SYMBOLS)
    }
    exit_proceeds = sum(
        current_positions[sym]["market_value"]
        for sym in stale_symbols
        if current_positions[sym]["market_value"] > 0
    )
    remaining_cash = max(raw_cash, 0.0) + exit_proceeds
    # Hard cap: can never spend more than total equity (prevents cross-day margin)
    remaining_cash = min(remaining_cash, equity)

    logger.info(
        f"Account equity: ${equity:,.2f} | settled_cash: ${raw_cash:,.2f} | "
        f"exit_proceeds: ${exit_proceeds:,.2f} | "
        f"available_cash: ${remaining_cash:,.2f} | "
        f"max_position (10%): ${max_position_usd:,.2f}"
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

    results = _close_stale_positions(
        current_positions, active_symbols, protected_symbols,
        results, dry_run, crypto_only=is_crypto_only,
    )

    for slot in sorted(output.allocations, key=lambda x: x.slot):
        results, remaining_cash = _execute_slot(
            slot, equity, max_position_usd, remaining_cash,
            current_positions, results, dry_run,
        )

    results = _run_vault_sweep(equity, results, dry_run)

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
        if sym in active_symbols or sym == CASH_TICKER:
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
        logger.warning(
            f"Closing stale position: {symbol} | "
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
) -> tuple[dict, float]:
    ticker = slot.ticker
    symbol = _normalize_symbol(ticker)
    is_crypto = is_crypto_pair(ticker)

    # Zero-kelly slots are always skipped (SGOV placeholders from conviction threshold)
    if slot.kelly_fraction == 0.0:
        logger.info(f"Slot {slot.slot}: {ticker:10s} → SKIP (zero kelly)")
        results["skipped"].append({"slot": slot.slot, "ticker": ticker, "reason": "zero_kelly"})
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

    if symbol in current_positions:
        existing_value = current_positions[symbol]["market_value"]
        target_value   = notional_usd
        diff_pct = abs(target_value - existing_value) / existing_value if existing_value > 0 else 1.0

        if diff_pct < 0.10:
            logger.info(
                f"Slot {slot.slot}: {ticker:10s} → HOLD "
                f"(existing=${existing_value:,.2f}, target=${target_value:,.2f}, diff={diff_pct:.1%})"
            )
            results["skipped"].append({
                "slot": slot.slot, "ticker": ticker,
                "reason": f"already_held_within_10pct (diff={diff_pct:.1%})",
            })
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

        log_trade(
            trade_id=order_id,
            ticker=ticker,
            asset_class=slot.asset_class,
            conviction_score=slot.conviction_score,
            original_thesis=slot.thesis,
            intended_price=intended_price,
        )
        logger.info(f"  → Logged to journal: trade_id={order_id}")

        remaining_cash -= notional_usd

        actual_fill_price = _poll_fill_price(order_id, ticker)
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

        try:
            from notifications.discord import notify_trade_placed
            notify_trade_placed(
                ticker=ticker, side="buy", notional=notional_usd,
                conviction=slot.conviction_score, thesis=slot.thesis,
                overheated=overheated,
            )
        except Exception:
            pass

        if overheated and actual_fill_price and actual_fill_price > 0:
            _place_ratchet_stop(ticker, notional_usd, actual_fill_price, results, dry_run)

        if overheated and sgov_notional >= MIN_NOTIONAL_USD:
            _reroute_to_sgov(slot, sgov_notional, results)

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
    Falls back to a 2% static stop if ATR is unavailable.
    """
    qty     = notional_usd / fill_price
    is_letf = ticker in LEVERAGED_RISK_TICKERS
    mult_label = "1.5×ATR [LETF tighter stop]" if is_letf else "2.0×ATR"
    logger.warning(
        f"⚠ Risk Overlay | Initialising ATR ratchet stop for {ticker}: "
        f"fill=${fill_price:.4f} qty={qty:.6f} | multiplier={mult_label}"
    )
    try:
        stop_result = initialise_ratchet_stop(
            ticker=ticker,
            fill_price=fill_price,
            qty=qty,
            dry_run=dry_run,
        )
        if stop_result:
            results["risk_overrides"][-1]["stop_order"] = stop_result.get("order")
            results["risk_overrides"][-1]["stop_price"] = stop_result.get("stop_price")
            results["risk_overrides"][-1]["atr"]        = stop_result.get("atr")
    except Exception as exc:
        logger.warning(f"Risk Overlay | Ratchet stop init failed for {ticker}: {exc} — position unprotected")
        results["risk_overrides"][-1]["stop_order_error"] = str(exc)


def _reroute_to_sgov(
    slot: RegimeAllocationSlot | CryptoAllocationSlot,
    sgov_notional: float,
    results: dict,
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


def _run_vault_sweep(equity: float, results: dict, dry_run: bool) -> dict:
    """Run the profit sweep after all allocations are executed."""
    try:
        from execution.profit_sweep import run_profit_sweep
        sweep = run_profit_sweep(current_equity=equity, dry_run=dry_run)
        results["vault_sweep"] = sweep
        if sweep.get("swept"):
            logger.info(
                f"Vault | Swept ${sweep['sweep_amount']:,.2f} → {sweep.get('vault_symbol', 'JEPQ')} "
                f"(total vaulted: ${sweep.get('total_vaulted_usd', 0):,.2f})"
            )
        elif sweep.get("reason") == "first_run_hwm_initialised":
            logger.info(f"Vault | High Water Mark initialised at ${sweep['hwm']:,.2f}")
        else:
            logger.debug(f"Vault | No sweep: {sweep.get('reason')}")
    except Exception as exc:
        logger.error(f"Vault | Sweep failed: {exc}")
        results["vault_sweep"] = {"swept": False, "reason": f"error: {exc}"}
    return results


def _poll_fill_price(order_id: str, ticker: str, max_wait: float = 5.0) -> float | None:
    start = time.time()
    poll_interval = 0.5

    while (time.time() - start) < max_wait:
        try:
            order_data = get_order(order_id)
            fill_price = order_data.get("filled_avg_price")
            if fill_price is not None:
                update_trade_fill_price(order_id, fill_price)
                return fill_price
            if order_data.get("status") in ("canceled", "expired", "rejected"):
                logger.warning(f"Order {order_id} ({ticker}) ended with status={order_data['status']}")
                return None
        except Exception as exc:
            logger.warning(f"Poll fill price error for {ticker}: {exc}")
        time.sleep(poll_interval)

    logger.warning(f"Fill price not available within {max_wait}s for {ticker} (order_id={order_id})")
    return None
