"""
adaptive_params.py — Self-tuning parameter layer for Davy Jones' Portfolio.

Every ADAPT_EVERY_HOURS hours (default: 6), this module reads the closed-trade
history from kraken_trades (PostgreSQL), computes performance metrics over the
last LOOKBACK_TRADES trades, and nudges the active trading parameters within
their safe bounds.

Parameters that adapt:
  ZSCORE_ENTRY       — Entry sensitivity (raise if win rate poor, lower if strong)
  ZSCORE_EXIT        — Exit threshold (lower to let winners run, raise to bank sooner)
  STOP_LOSS_PCT      — Hard stop (tighten if stop-outs are too frequent or large)
  TRAIL_PCT          — Trailing stop (widen if trailing fires before full reversion)
  MIN_NET_PROFIT_PCT — Floor profit gate (raise if break-even exits are common)

All parameters stay within ±40% of their factory defaults and always above the
minimum fee floor so the bot never exits at a guaranteed loss.

PRIMARY STATE: PostgreSQL kraken_adaptive_params table (single-row, id=1 UPSERT).
FALLBACK LOAD: adaptive_params.json — read ONCE at startup migration only, then
               the file is no longer written or read in the primary code path.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("kraken_adaptive")

# ── PostgreSQL helpers ────────────────────────────────────────────────────────

def _pg_save(payload: dict) -> None:
    """Upsert adaptive params into kraken_adaptive_params (keyed by bot's db_id)."""
    try:
        from config import BOT_DB_ID, BOT_ID
        import psycopg2
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            return
        conn = psycopg2.connect(db_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kraken_adaptive_params
                        (id, bot_id, params, metrics, reasons, adapted_at, lookback_n)
                    VALUES (%s, %s, %s, %s, %s, NOW(), %s)
                    ON CONFLICT (id) DO UPDATE SET
                        bot_id     = EXCLUDED.bot_id,
                        params     = EXCLUDED.params,
                        metrics    = EXCLUDED.metrics,
                        reasons    = EXCLUDED.reasons,
                        adapted_at = NOW(),
                        lookback_n = EXCLUDED.lookback_n
                    """,
                    (
                        BOT_DB_ID,
                        BOT_ID,
                        json.dumps(payload.get("params", {})),
                        json.dumps(payload.get("metrics")),
                        json.dumps(payload.get("reasons", {})),
                        payload.get("lookback_n", 0),
                    ),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.debug(f"Adaptive | pg_save skipped: {exc}")


def _pg_load() -> dict | None:
    """Load adaptive params from kraken_adaptive_params (keyed by bot's db_id)."""
    try:
        from config import BOT_DB_ID
        import psycopg2
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            return None
        conn = psycopg2.connect(db_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT params, metrics, lookback_n
                    FROM   kraken_adaptive_params
                    WHERE  id = %s
                    """,
                    (BOT_DB_ID,)
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return None
        params  = row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}")
        metrics = row[1] if isinstance(row[1], dict) else json.loads(row[1] or "{}")
        n = (metrics or {}).get("n", row[2] or 0)
        if n == 0:
            return None
        logger.info(f"Adaptive | Loaded params from PostgreSQL (n={n})")
        return params
    except Exception as exc:
        logger.debug(f"Adaptive | pg_load skipped: {exc}")
        return None


def migrate_adaptive_from_json(params_file: "str | Path") -> None:
    """
    One-time bootstrap: seed kraken_adaptive_params from adaptive_params.json
    if the DB row is missing and the file exists.  Called once at bot startup.
    """
    params_file = Path(params_file)
    if not params_file.exists():
        return
    from config import BOT_DB_ID
    try:
        import psycopg2
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            return
        conn = psycopg2.connect(db_url)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT lookback_n FROM kraken_adaptive_params WHERE id = %s", (BOT_DB_ID,))
                existing = cur.fetchone()
        finally:
            conn.close()
        if existing and existing[0] and existing[0] > 0:
            logger.debug("Adaptive | migrate_adaptive_from_json: DB row exists — skipping")
            return
    except Exception:
        return
    # Seed from JSON
    try:
        data = json.loads(params_file.read_text())
        payload = {
            "params":    data.get("params", {}),
            "metrics":   data.get("metrics"),
            "reasons":   data.get("reasons", {}),
            "lookback_n": (data.get("metrics") or {}).get("n", 0),
        }
        _pg_save(payload)
        logger.info(f"Adaptive | Migrated adaptive params from {params_file} to PostgreSQL")
    except Exception as exc:
        logger.warning(f"Adaptive | migrate_adaptive_from_json failed: {exc}")

# ── Defaults (loaded from bot profile in config.py) ──────────────────────────
from config import ZSCORE_ENTRY as _CFG_ZE, STOP_LOSS_PCT as _CFG_SL
DEFAULTS = {
    "ZSCORE_ENTRY":       _CFG_ZE,
    "ZSCORE_EXIT":        0.3,
    "STOP_LOSS_PCT":      _CFG_SL,
    "TRAIL_PCT":          0.05,
    "MIN_NET_PROFIT_PCT": 0.008,
}

# ── Safe bounds: param never moves outside [min, max] ─────────────────────────
BOUNDS = {
    "ZSCORE_ENTRY":       (0.7,   1.5),
    "ZSCORE_EXIT":        (0.10,  0.55),
    "STOP_LOSS_PCT":      (0.008, 0.040),
    "TRAIL_PCT":          (0.030, 0.100),
    "MIN_NET_PROFIT_PCT": (0.006, 0.020),
}

# ── Step sizes applied per evaluation ─────────────────────────────────────────
STEPS = {
    "ZSCORE_ENTRY":       0.05,
    "ZSCORE_EXIT":        0.02,
    "STOP_LOSS_PCT":      0.002,
    "TRAIL_PCT":          0.005,
    "MIN_NET_PROFIT_PCT": 0.001,
}

# ── Operational config ────────────────────────────────────────────────────────
LOOKBACK_TRADES   = 30   # Evaluate on the most recent N closed trades.
MIN_TRADES        = 10   # Need at least this many trades before adapting.
ADAPT_EVERY_HOURS = 6    # Re-evaluate every 6 hours.
PARAMS_FILE       = Path("kraken-bot/adaptive_params.json")
PORTFOLIO_FILE    = Path("kraken-bot/paper_portfolio.json")

# Fee floor: MIN_NET_PROFIT_PCT must always exceed 2× trade fee to avoid
# exiting at a guaranteed loss.
FEE_PCT           = 0.0026   # Kraken taker fee per side
FEE_FLOOR         = FEE_PCT * 2 + 0.001   # round-trip + 0.1% safety buffer


# ══════════════════════════════════════════════════════════════════════════════
# Internal state
# ══════════════════════════════════════════════════════════════════════════════

_active: dict[str, float] = dict(DEFAULTS)
_last_adapted_at: float   = 0.0
_last_reason: dict[str, str] = {}


def _clamp(name: str, value: float) -> float:
    lo, hi = BOUNDS[name]
    return max(lo, min(hi, value))


def _nudge(params: dict, name: str, direction: int, reason: str) -> None:
    """
    Adjust params[name] by one step in direction (+1 or -1).
    Records the human-readable reason for the change.
    """
    old   = params[name]
    delta = direction * STEPS[name]
    new   = _clamp(name, round(old + delta, 6))
    if new != old:
        params[name] = new
        _last_reason[name] = f"{'+' if direction > 0 else ''}{delta:+.4f} → {new:.4f}  [{reason}]"
        logger.info(f"Adaptive | {name}: {old:.4f} → {new:.4f}  ({reason})")
    else:
        _last_reason[name] = f"at bound ({old:.4f})  [{reason}]"


# ══════════════════════════════════════════════════════════════════════════════
# Metrics
# ══════════════════════════════════════════════════════════════════════════════

def _compute_metrics(trades: list[dict]) -> dict:
    """
    Summarise the last LOOKBACK_TRADES closed trades into actionable metrics.
    """
    recent = trades[-LOOKBACK_TRADES:]
    n      = len(recent)

    wins   = [t for t in recent if (t.get("pnl_usd", 0) or 0) >= 0]
    losses = [t for t in recent if (t.get("pnl_usd", 0) or 0) < 0]

    win_rate   = len(wins) / n if n else 0
    avg_win    = sum(t["pnl_pct"] for t in wins)   / len(wins)   if wins   else 0
    avg_loss   = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0

    # Exit-reason breakdown
    def _rate(reason_substr: str) -> float:
        count = sum(1 for t in recent if reason_substr in (t.get("reason") or ""))
        return count / n if n else 0

    stop_loss_rate    = _rate("stop_loss")
    trailing_rate     = _rate("trailing")
    reversion_rate    = _rate("mean_reversion")

    consec_losses = 0
    for t in reversed(recent):
        if (t.get("pnl_usd", 0) or 0) < 0:
            consec_losses += 1
        else:
            break

    # Profit factor (gross wins / gross losses)
    gross_win  = sum(t["pnl_pct"] for t in wins)          if wins   else 0
    gross_loss = abs(sum(t["pnl_pct"] for t in losses))   if losses else 1
    profit_factor = gross_win / gross_loss if gross_loss else float("inf")

    return {
        "n":               n,
        "win_rate":        round(win_rate, 4),
        "avg_win_pct":     round(avg_win, 4),
        "avg_loss_pct":    round(avg_loss, 4),
        "stop_loss_rate":  round(stop_loss_rate, 4),
        "trailing_rate":   round(trailing_rate, 4),
        "reversion_rate":  round(reversion_rate, 4),
        "consec_losses":   consec_losses,
        "profit_factor":   round(profit_factor, 3),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Adaptation rules
# ══════════════════════════════════════════════════════════════════════════════

def _apply_rules(params: dict, m: dict) -> None:
    """
    Apply one round of adaptation rules based on metrics m.
    Each rule adjusts at most one parameter by one step so that changes are
    gradual and easy to audit.
    """
    n          = m["n"]
    win_rate   = m["win_rate"]
    avg_win    = m["avg_win_pct"]
    avg_loss   = m["avg_loss_pct"]
    sl_rate    = m["stop_loss_rate"]
    trail_rate = m["trailing_rate"]
    rev_rate   = m["reversion_rate"]
    pf         = m["profit_factor"]
    consec     = m["consec_losses"]

    if n < MIN_TRADES:
        logger.info(f"Adaptive | only {n} trades — skipping adaptation (need ≥{MIN_TRADES})")
        return

    # ── ZSCORE_ENTRY ─────────────────────────────────────────────────────────
    # Poor win rate: raise the bar so we only enter stronger setups.
    if win_rate < 0.40 and pf < 1.0:
        _nudge(params, "ZSCORE_ENTRY", +1,
               f"low win rate {win_rate:.0%} + profit factor {pf:.2f} — require stronger divergence")
    # Strong win rate AND we have room to enter more setups: lower threshold.
    elif win_rate > 0.65 and pf > 1.5 and params["ZSCORE_ENTRY"] > DEFAULTS["ZSCORE_ENTRY"]:
        _nudge(params, "ZSCORE_ENTRY", -1,
               f"strong win rate {win_rate:.0%} + profit factor {pf:.2f} — allow earlier entries")

    # ── ZSCORE_EXIT ──────────────────────────────────────────────────────────
    # Mean-reversion exits dominating but average win is small: let winners run.
    if rev_rate > 0.50 and avg_win < 1.0:
        _nudge(params, "ZSCORE_EXIT", -1,
               f"reversion exits {rev_rate:.0%} of closes but avg win only {avg_win:.2f}% — let winners run")
    # Average win is healthy and trailing fires a lot: can tighten exit to bank sooner.
    elif avg_win > 2.5 and trail_rate < 0.20 and params["ZSCORE_EXIT"] < DEFAULTS["ZSCORE_EXIT"] + STEPS["ZSCORE_EXIT"]:
        _nudge(params, "ZSCORE_EXIT", +1,
               f"avg win {avg_win:.2f}% is strong — bank earlier on reversion signal")

    # ── STOP_LOSS_PCT ────────────────────────────────────────────────────────
    # Stop-outs are more than half of all exits AND losses are deep: tighten.
    if sl_rate > 0.50 and avg_loss < -2.0:
        _nudge(params, "STOP_LOSS_PCT", -1,
               f"stop-outs = {sl_rate:.0%} of exits, avg loss {avg_loss:.2f}% — tighten hard stop")
    # Stop-loss rarely fires AND wins dominate: can afford slightly wider stop.
    elif sl_rate < 0.15 and win_rate > 0.60 and params["STOP_LOSS_PCT"] < DEFAULTS["STOP_LOSS_PCT"]:
        _nudge(params, "STOP_LOSS_PCT", +1,
               f"stop-loss rarely fires ({sl_rate:.0%}) and win rate {win_rate:.0%} — restore headroom")

    # ── TRAIL_PCT ────────────────────────────────────────────────────────────
    # Trailing stop fires a lot before full mean-reversion AND wins are thin.
    if trail_rate > 0.40 and avg_win < 1.5:
        _nudge(params, "TRAIL_PCT", +1,
               f"trailing exits {trail_rate:.0%}, avg win only {avg_win:.2f}% — give more room before trailing out")
    # Trailing fires rarely AND we're leaving profit (high avg win): tighten to protect gains.
    elif trail_rate < 0.10 and avg_win > 3.0:
        _nudge(params, "TRAIL_PCT", -1,
               f"trailing rarely fires ({trail_rate:.0%}), avg win {avg_win:.2f}% — protect profits tighter")

    # ── MIN_NET_PROFIT_PCT ───────────────────────────────────────────────────
    # Many consecutive losses suggests bad entry conditions: raise the floor.
    if consec >= 4:
        _nudge(params, "MIN_NET_PROFIT_PCT", +1,
               f"{consec} consecutive losses — raise profit floor to filter weak reversion signals")
    # Profit factor is healthy and we're in a good run: restore fee-floor minimum.
    elif pf > 2.0 and params["MIN_NET_PROFIT_PCT"] > DEFAULTS["MIN_NET_PROFIT_PCT"]:
        _nudge(params, "MIN_NET_PROFIT_PCT", -1,
               f"profit factor {pf:.2f} — relax profit floor back toward default")

    # Safety: MIN_NET_PROFIT_PCT must never fall below fee floor
    if params["MIN_NET_PROFIT_PCT"] < FEE_FLOOR:
        params["MIN_NET_PROFIT_PCT"] = round(FEE_FLOOR, 6)
        logger.warning(f"Adaptive | MIN_NET_PROFIT_PCT clamped to fee floor {FEE_FLOOR:.4f}")


# ══════════════════════════════════════════════════════════════════════════════
# Persistence
# ══════════════════════════════════════════════════════════════════════════════

def _load_persisted() -> dict | None:
    """
    Load previously adapted params from PostgreSQL only.
    PRIMARY (and only) source: kraken_adaptive_params (id=1).
    Returns None if no row exists or DB is unavailable — caller falls back to factory defaults.
    """
    return _pg_load()


def _save(params: dict, metrics: dict | None) -> None:
    """Persist adapted params to PostgreSQL (primary). JSON file is NOT written."""
    # Embed _er_at so the streak-reset survives restarts
    params_with_meta = dict(params)
    if _last_emergency_rebalance_at is not None:
        params_with_meta["_er_at"] = _last_emergency_rebalance_at.isoformat()
    payload = {
        "params":       params_with_meta,
        "defaults":     DEFAULTS,
        "bounds":       {k: list(v) for k, v in BOUNDS.items()},
        "reasons":      dict(_last_reason),
        "metrics":      metrics,
        "adapted_at":   datetime.now(timezone.utc).isoformat(),
        "lookback_n":   metrics["n"] if metrics else 0,
    }
    _pg_save(payload)


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def initialise() -> None:
    """
    Call once at bot startup. Loads persisted params if they exist, otherwise
    starts from factory defaults and writes an initial snapshot.
    """
    global _active, _last_emergency_rebalance_at
    persisted = _load_persisted()
    if persisted:
        # Restore last emergency rebalance timestamp from embedded _er_at field
        er_at_iso = persisted.pop("_er_at", None)
        if er_at_iso:
            try:
                _last_emergency_rebalance_at = datetime.fromisoformat(er_at_iso)
                logger.info(f"Adaptive | Restored last emergency rebalance at {er_at_iso}")
            except Exception:
                pass
        # Validate each key is still within current bounds before trusting it
        clean = {}
        for k, default in DEFAULTS.items():
            raw = persisted.get(k, default)
            clean[k] = _clamp(k, raw)
        _active = clean
        logger.info("Adaptive | Loaded persisted params: " +
                    ", ".join(f"{k}={v:.4f}" for k, v in _active.items()))
    else:
        _active = dict(DEFAULTS)
        _save(_active, None)
        logger.info("Adaptive | No persisted params found — starting from factory defaults")


def get_last_emergency_rebalance_at() -> "datetime | None":
    """Return the UTC datetime of the last emergency rebalance, or None if never run."""
    return _last_emergency_rebalance_at


def _load_trades_for_adaptation() -> list[dict]:
    """
    Load closed trade history from PostgreSQL only (kraken_trades table).
    Returns empty list if DB is unavailable — adaptation is skipped until DB recovers.
    """
    try:
        import db as _db
        return _db.load_all_trades()
    except Exception as exc:
        logger.debug(f"Adaptive | DB trade load skipped: {exc}")
        return []


def maybe_adapt() -> bool:
    """
    Called from the main loop every cycle. Only does real work every
    ADAPT_EVERY_HOURS hours. Returns True if an adaptation was performed.
    """
    global _active, _last_adapted_at

    now = datetime.now(timezone.utc).timestamp()
    if now - _last_adapted_at < ADAPT_EVERY_HOURS * 3600:
        return False

    _last_adapted_at = now

    trades = _load_trades_for_adaptation()
    if len(trades) < MIN_TRADES:
        logger.info(f"Adaptive | {len(trades)} trades (need ≥{MIN_TRADES}) — no adaptation yet")
        _save(_active, {"n": len(trades)})
        return False

    metrics    = _compute_metrics(trades)
    new_params = dict(_active)
    _apply_rules(new_params, metrics)
    _active = new_params
    _save(_active, metrics)

    logger.info(
        f"Adaptive | Evaluation complete on {metrics['n']} trades | "
        f"win_rate={metrics['win_rate']:.0%} avg_win={metrics['avg_win_pct']:.2f}% "
        f"sl_rate={metrics['stop_loss_rate']:.0%} pf={metrics['profit_factor']:.2f}"
    )
    return True


def get_active_params() -> dict[str, float]:
    """Return a copy of the current active parameters."""
    return dict(_active)


# Timestamp of the last emergency Gemini rebalance (None if never triggered).
_last_emergency_rebalance_at: datetime | None = None

# Absolute safety floors/ceilings for 5× expanded bounds.
_EMERGENCY_FLOORS = {
    "ZSCORE_ENTRY":       0.30,
    "ZSCORE_EXIT":        0.05,
    "STOP_LOSS_PCT":      0.004,
    "TRAIL_PCT":          0.015,
    "MIN_NET_PROFIT_PCT": FEE_FLOOR,
}
_EMERGENCY_CEILINGS = {
    "ZSCORE_ENTRY":       3.00,
    "ZSCORE_EXIT":        1.50,
    "STOP_LOSS_PCT":      0.15,
    "TRAIL_PCT":          0.30,
    "MIN_NET_PROFIT_PCT": 0.08,
}


def gemini_emergency_rebalance(
    consecutive_losses: int,
    losing_positions: list[dict] | None = None,
) -> dict[str, float]:
    """
    Triggered when the losing-streak limit is hit instead of shutting the bot down.

    - Computes 5× expanded parameter bounds (Gemini gets 5× more adjustment room).
    - Calls Gemini via the Replit proxy to propose new parameter values.
    - Persists the result to PostgreSQL so the next cycle picks them up immediately.
    - Returns the new active params dict.
    """
    global _active, _last_emergency_rebalance_at

    # ── 5× expanded bounds ───────────────────────────────────────────────────
    expanded_bounds: dict[str, tuple[float, float]] = {}
    for name in DEFAULTS:
        lo, hi   = BOUNDS[name]
        default  = DEFAULTS[name]
        lo_dev   = default - lo      # normal downward room from default
        hi_dev   = hi - default      # normal upward room from default
        exp_lo   = max(_EMERGENCY_FLOORS[name],   default - 5.0 * lo_dev)
        exp_hi   = min(_EMERGENCY_CEILINGS[name], default + 5.0 * hi_dev)
        expanded_bounds[name] = (round(exp_lo, 6), round(exp_hi, 6))

    # ── Metrics for context ───────────────────────────────────────────────────
    trades  = _load_trades_for_adaptation()
    metrics = _compute_metrics(trades) if len(trades) >= MIN_TRADES else None

    # ── Build Gemini prompt ───────────────────────────────────────────────────
    params_desc = "\n".join(
        f"  {k}: current={_active.get(k, DEFAULTS[k]):.4f}  "
        f"default={DEFAULTS[k]:.4f}  "
        f"normal_range=[{BOUNDS[k][0]:.4f},{BOUNDS[k][1]:.4f}]  "
        f"EMERGENCY_range=[{expanded_bounds[k][0]:.4f},{expanded_bounds[k][1]:.4f}]"
        for k in DEFAULTS
    )

    metrics_desc = ""
    if metrics:
        metrics_desc = (
            f"\nRecent performance (last {metrics['n']} trades):\n"
            f"  win_rate={metrics['win_rate']:.0%}  profit_factor={metrics['profit_factor']:.2f}\n"
            f"  avg_win={metrics['avg_win_pct']:.2f}%  avg_loss={metrics['avg_loss_pct']:.2f}%\n"
            f"  stop_loss_rate={metrics['stop_loss_rate']:.0%}  "
            f"trailing_rate={metrics['trailing_rate']:.0%}"
        )

    positions_desc = ""
    if losing_positions:
        positions_desc = f"\nLosing positions being closed ({len(losing_positions)}):\n"
        for p in losing_positions:
            positions_desc += (
                f"  {p.get('symbol')} {str(p.get('side','')).upper()}  "
                f"entry={p.get('entry_price', 0):.4f}  "
                f"unrealized_pnl={p.get('unrealized_pnl_pct', 0):.2f}%\n"
            )

    system_prompt = (
        "You are an emergency trading parameter optimizer for a 24/7 cryptocurrency "
        "mean-reversion bot running on Kraken. The bot has hit its losing-streak "
        "circuit breaker. Your job is to propose new parameters that stop the losses "
        "and help the bot recover.\n\n"
        "This is an EMERGENCY rebalance — you have 5× the normal parameter range. "
        "Make decisive, meaningful changes that directly address the losing streak.\n\n"
        "Return ONLY a valid JSON object with exactly these numeric keys:\n"
        "  ZSCORE_ENTRY, ZSCORE_EXIT, STOP_LOSS_PCT, TRAIL_PCT, MIN_NET_PROFIT_PCT\n\n"
        "Parameter meanings:\n"
        "  ZSCORE_ENTRY      — entry z-score threshold (higher = more selective entries)\n"
        "  ZSCORE_EXIT       — exit z-score on mean reversion (lower = let winners run)\n"
        "  STOP_LOSS_PCT     — hard stop fraction (e.g. 0.02 = 2% loss cut)\n"
        "  TRAIL_PCT         — trailing stop fraction (higher = more room before trailing)\n"
        "  MIN_NET_PROFIT_PCT — minimum net profit required to exit (filters weak signals)\n\n"
        "All values MUST be within the EMERGENCY_range bounds. "
        "Return ONLY the JSON object — no explanation, no markdown."
    )

    user_prompt = (
        f"EMERGENCY REBALANCE — {consecutive_losses} consecutive losing trades.\n\n"
        f"Current parameters and available ranges:\n{params_desc}\n"
        f"{metrics_desc}{positions_desc}\n"
        "Diagnose what is causing the losing streak from the metrics, then propose new "
        "parameter values within EMERGENCY_range that will stop the losses. "
        "You have 5× the normal adjustment room — use it decisively."
    )

    # ── Call Gemini ───────────────────────────────────────────────────────────
    try:
        from analysis.groq_client import call_groq
        raw = call_groq(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=8192,
            call_type="emergency_rebalance",
        )
        proposed = json.loads(raw)
    except Exception as exc:
        logger.error(
            f"Adaptive | Emergency Gemini rebalance failed: {exc} — current params unchanged"
        )
        return dict(_active)

    # ── Validate and apply ────────────────────────────────────────────────────
    new_params = dict(_active)
    reasons: dict[str, str] = {}
    for name, (exp_lo, exp_hi) in expanded_bounds.items():
        if name not in proposed:
            continue
        try:
            raw_val = float(proposed[name])
        except (TypeError, ValueError):
            continue
        clamped = max(exp_lo, min(exp_hi, raw_val))
        old = new_params[name]
        new_params[name] = round(clamped, 6)
        if clamped != old:
            reasons[name] = (
                f"Emergency rebalance ({consecutive_losses} losses): "
                f"{old:.4f} → {clamped:.4f} "
                f"[Gemini={raw_val:.4f}, 5× bounds=[{exp_lo:.4f},{exp_hi:.4f}]]"
            )
            logger.warning(
                f"Adaptive | EMERGENCY {name}: {old:.4f} → {clamped:.4f}  "
                f"(Gemini proposed {raw_val:.4f}, 5× bounds=[{exp_lo:.4f},{exp_hi:.4f}])"
            )

    # Safety: MIN_NET_PROFIT_PCT must never fall below fee floor
    if new_params.get("MIN_NET_PROFIT_PCT", 0) < FEE_FLOOR:
        new_params["MIN_NET_PROFIT_PCT"] = round(FEE_FLOOR, 6)

    _active = new_params
    _last_reason.update(reasons)
    _last_emergency_rebalance_at = datetime.now(tz=timezone.utc)
    _save(_active, metrics)

    logger.warning(
        f"Adaptive | EMERGENCY REBALANCE COMPLETE ({consecutive_losses} consecutive losses): "
        + ", ".join(f"{k}={v:.4f}" for k, v in _active.items())
    )
    return dict(_active)


def status_snapshot() -> dict:
    """Return a dashboard-friendly snapshot of the adaptive parameter state."""
    return {
        "active":       dict(_active),
        "defaults":     dict(DEFAULTS),
        "reasons":      dict(_last_reason),
        "adapted_at":   datetime.fromtimestamp(_last_adapted_at, tz=timezone.utc).isoformat()
                        if _last_adapted_at else None,
        "last_emergency_rebalance_at": (
            _last_emergency_rebalance_at.isoformat()
            if _last_emergency_rebalance_at else None
        ),
        "next_adapt_in_hours": max(
            0,
            round(
                ADAPT_EVERY_HOURS
                - (datetime.now(timezone.utc).timestamp() - _last_adapted_at) / 3600,
                1
            )
        ) if _last_adapted_at else ADAPT_EVERY_HOURS,
    }
