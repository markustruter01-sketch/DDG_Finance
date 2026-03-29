"""
adaptive_params.py — Self-tuning parameter layer for Davy Jones' Portfolio.

Every ADAPT_EVERY_HOURS hours (default: 6), this module reads the closed-trade
history from paper_portfolio.json, computes performance metrics over the last
LOOKBACK_TRADES trades, and nudges the active trading parameters within their
safe bounds.

Parameters that adapt:
  ZSCORE_ENTRY       — Entry sensitivity (raise if win rate poor, lower if strong)
  ZSCORE_EXIT        — Exit threshold (lower to let winners run, raise to bank sooner)
  STOP_LOSS_PCT      — Hard stop (tighten if stop-outs are too frequent or large)
  TRAIL_PCT          — Trailing stop (widen if trailing fires before full reversion)
  MIN_NET_PROFIT_PCT — Floor profit gate (raise if break-even exits are common)

All parameters stay within ±40% of their factory defaults and always above the
minimum fee floor so the bot never exits at a guaranteed loss.

The current adapted values are written to adaptive_params.json after each
evaluation so they survive restarts and are visible on the dashboard.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("kraken_adaptive")

# ── PostgreSQL helpers (optional — gracefully absent if DB not available) ─────

def _pg_save(payload: dict) -> None:
    """Write adaptive params to PostgreSQL kraken_adaptive_params table."""
    try:
        import psycopg2, psycopg2.extras
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            return
        conn = psycopg2.connect(db_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS kraken_adaptive_params (
                        id          SERIAL PRIMARY KEY,
                        params      JSONB NOT NULL,
                        metrics     JSONB,
                        reasons     JSONB,
                        adapted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        lookback_n  INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                cur.execute("DELETE FROM kraken_adaptive_params")
                cur.execute(
                    """
                    INSERT INTO kraken_adaptive_params
                        (params, metrics, reasons, adapted_at, lookback_n)
                    VALUES (%s, %s, %s, NOW(), %s)
                    """,
                    (
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
    """Load adaptive params from PostgreSQL if a row exists with n > 0."""
    try:
        import psycopg2, psycopg2.extras
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            return None
        conn = psycopg2.connect(db_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT params, metrics, reasons, adapted_at, lookback_n
                    FROM kraken_adaptive_params
                    ORDER BY id DESC LIMIT 1
                    """
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return None
        params  = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        metrics = row[1] if isinstance(row[1], dict) else json.loads(row[1] or "{}")
        n = (metrics or {}).get("n", row[4] or 0)
        if n == 0:
            return None
        logger.info(f"Adaptive | Loaded params from PostgreSQL (n={n})")
        return params
    except Exception as exc:
        logger.debug(f"Adaptive | pg_load skipped: {exc}")
        return None

# ── Defaults (mirrors config.py) ──────────────────────────────────────────────
DEFAULTS = {
    "ZSCORE_ENTRY":       1.0,
    "ZSCORE_EXIT":        0.3,
    "STOP_LOSS_PCT":      0.02,
    "TRAIL_PCT":          0.05,
    "MIN_NET_PROFIT_PCT": 0.008,
}

# ── Safe bounds: param never moves outside [min, max] ─────────────────────────
BOUNDS = {
    "ZSCORE_ENTRY":       (0.7,   1.5),
    "ZSCORE_EXIT":        (0.10,  0.55),
    "STOP_LOSS_PCT":      (0.010, 0.040),
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

    wins   = [t for t in recent if t.get("pnl_pct", 0) > 0]
    losses = [t for t in recent if t.get("pnl_pct", 0) <= 0]

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

    # Consecutive losses at the tail of the sequence
    consec_losses = 0
    for t in reversed(recent):
        if t.get("pnl_pct", 0) <= 0:
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
    # 1. Try PostgreSQL first (survives container restarts and redeploys)
    pg = _pg_load()
    if pg:
        return pg
    # 2. Fall back to JSON file
    if PARAMS_FILE.exists():
        try:
            data = json.loads(PARAMS_FILE.read_text())
            return data.get("params")
        except Exception:
            pass
    return None


def _save(params: dict, metrics: dict | None) -> None:
    payload = {
        "params":       params,
        "defaults":     DEFAULTS,
        "bounds":       {k: list(v) for k, v in BOUNDS.items()},
        "reasons":      dict(_last_reason),
        "metrics":      metrics,
        "adapted_at":   datetime.now(timezone.utc).isoformat(),
        "lookback_n":   metrics["n"] if metrics else 0,
    }
    try:
        PARAMS_FILE.write_text(json.dumps(payload, indent=2))
    except Exception as exc:
        logger.warning(f"Adaptive | could not save params file: {exc}")
    # Also persist to PostgreSQL so redeploys can recover adapted values
    _pg_save(payload)


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def initialise() -> None:
    """
    Call once at bot startup. Loads persisted params if they exist, otherwise
    starts from factory defaults and writes an initial snapshot.
    """
    global _active
    persisted = _load_persisted()
    if persisted:
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

    try:
        raw = json.loads(PORTFOLIO_FILE.read_text())
    except Exception as exc:
        logger.warning(f"Adaptive | could not read portfolio: {exc}")
        return False

    trades = raw.get("closed_trades", [])
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


def status_snapshot() -> dict:
    """Return a dashboard-friendly snapshot of the adaptive parameter state."""
    return {
        "active":       dict(_active),
        "defaults":     dict(DEFAULTS),
        "reasons":      dict(_last_reason),
        "adapted_at":   datetime.fromtimestamp(_last_adapted_at, tz=timezone.utc).isoformat()
                        if _last_adapted_at else None,
        "next_adapt_in_hours": max(
            0,
            round(
                ADAPT_EVERY_HOURS
                - (datetime.now(timezone.utc).timestamp() - _last_adapted_at) / 3600,
                1
            )
        ) if _last_adapted_at else ADAPT_EVERY_HOURS,
    }
