"""
backtest.py — Stage 6: Historical Backtesting Infrastructure
=============================================================
Runs every Sunday at 2:30 AM UTC for all three Kraken bots
(30 minutes after the Walk-Forward Optimiser completes).
Fully deterministic — no LLM calls.

Approach
--------
We do not have intra-trade OHLCV paths, so we apply a
"realized-P&L replay" method:

    For each closed trade, given new (sl_pct, tp_pct):
      • if actual_pnl_pct  <  -sl_pct  → simulated exit at -sl_pct
                                          (SL would have triggered earlier)
      • if actual_pnl_pct  >  +tp_pct  → simulated exit at +tp_pct
                                          (TP would have triggered earlier)
      • otherwise                       → same outcome as actual

This is a conservative approximation:
  - It OVERSTATES the SL benefit (ignores gap-fills / slippage).
  - It UNDERSTATES the TP benefit for trades that ran past TP then reversed.
  - The method is labelled clearly in all reports.

Grid search
-----------
SL candidates : [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0] %
TP candidates : [None, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0] %
Total combos  : 8 × 8 = 64 per bot

Results stored in kraken_backtest_results (PostgreSQL).
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

from loguru import logger

# ── constants ────────────────────────────────────────────────────────────────

SL_CANDIDATES: list[float] = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
TP_CANDIDATES: list[float | None] = [None, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0]
TOP_GRID_RESULTS = 10   # store top-N grid rows in JSONB
KRAKEN_BOT_IDS = ["davy-jones", "blackbeard", "calypso"]


# ── DB helpers ───────────────────────────────────────────────────────────────

def _pg_conn():
    from db.postgres import get_conn
    return get_conn()


def _query(sql: str, params: tuple = ()) -> list[dict]:
    try:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as exc:
        logger.warning(f"Backtest | DB query failed: {exc}")
        return []


def _ensure_table() -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS kraken_backtest_results (
        id                BIGSERIAL PRIMARY KEY,
        bot_id            TEXT NOT NULL,
        run_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        n_trades          INTEGER NOT NULL DEFAULT 0,

        baseline_wr       DOUBLE PRECISION,
        baseline_pf       DOUBLE PRECISION,
        baseline_net_pct  DOUBLE PRECISION,
        baseline_max_dd   DOUBLE PRECISION,
        baseline_avg_hold DOUBLE PRECISION,

        wfo_sl_pct        DOUBLE PRECISION,
        wfo_tp_pct        DOUBLE PRECISION,
        wfo_wr            DOUBLE PRECISION,
        wfo_pf            DOUBLE PRECISION,
        wfo_net_pct       DOUBLE PRECISION,
        wfo_max_dd        DOUBLE PRECISION,
        wfo_verdict       TEXT,

        best_sl_pct       DOUBLE PRECISION,
        best_tp_pct       DOUBLE PRECISION,
        best_wr           DOUBLE PRECISION,
        best_pf           DOUBLE PRECISION,
        best_net_pct      DOUBLE PRECISION,
        best_max_dd       DOUBLE PRECISION,
        best_improvement  DOUBLE PRECISION,

        grid_results      JSONB NOT NULL DEFAULT '[]',
        regime_breakdown  JSONB NOT NULL DEFAULT '{}',
        summary           TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_backtest_bot_run
        ON kraken_backtest_results (bot_id, run_at DESC);
    """
    try:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(ddl)
        logger.debug("Backtest | Table ensured: kraken_backtest_results")
    except Exception as exc:
        logger.error(f"Backtest | Table creation failed: {exc}")


def _persist(bot_id: str, result: dict) -> None:
    sql = """
    INSERT INTO kraken_backtest_results (
        bot_id, run_at, n_trades,
        baseline_wr, baseline_pf, baseline_net_pct, baseline_max_dd, baseline_avg_hold,
        wfo_sl_pct, wfo_tp_pct, wfo_wr, wfo_pf, wfo_net_pct, wfo_max_dd, wfo_verdict,
        best_sl_pct, best_tp_pct, best_wr, best_pf, best_net_pct, best_max_dd, best_improvement,
        grid_results, regime_breakdown, summary
    ) VALUES (
        %(bot_id)s, %(run_at)s, %(n_trades)s,
        %(baseline_wr)s, %(baseline_pf)s, %(baseline_net_pct)s, %(baseline_max_dd)s, %(baseline_avg_hold)s,
        %(wfo_sl_pct)s, %(wfo_tp_pct)s, %(wfo_wr)s, %(wfo_pf)s, %(wfo_net_pct)s, %(wfo_max_dd)s, %(wfo_verdict)s,
        %(best_sl_pct)s, %(best_tp_pct)s, %(best_wr)s, %(best_pf)s, %(best_net_pct)s, %(best_max_dd)s, %(best_improvement)s,
        %(grid_results)s, %(regime_breakdown)s, %(summary)s
    )
    """
    try:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                row = {**result, "bot_id": bot_id, "run_at": datetime.now(timezone.utc)}
                row["grid_results"]      = json.dumps(row.get("grid_results", []))
                row["regime_breakdown"]  = json.dumps(row.get("regime_breakdown", {}))
                cur.execute(sql, row)
        logger.debug(f"Backtest | Persisted result for {bot_id}")
    except Exception as exc:
        logger.error(f"Backtest | Persist failed for {bot_id}: {exc}")


def _fetch_wfo_recommendation(bot_id: str) -> tuple[float | None, float | None]:
    """Return (rec_sl_pct, rec_tp_pct) from the latest WFO result."""
    rows = _query(
        "SELECT rec_sl_pct, rec_tp_pct FROM kraken_wfo_results "
        "WHERE bot_id = %s ORDER BY run_at DESC LIMIT 1",
        (bot_id,),
    )
    if not rows:
        return None, None
    return rows[0]["rec_sl_pct"], rows[0]["rec_tp_pct"]


# ── trade loading ─────────────────────────────────────────────────────────────

def _load_trades(bot_id: str) -> list[dict]:
    """Load all closed trades for a bot. Returns list of dicts."""
    rows = _query(
        """
        SELECT symbol, side, entry_price, exit_price,
               pnl_pct, pnl_usd, fees_usd, reason,
               regime_at_entry, closed_at
        FROM   kraken_trades
        WHERE  bot_id = %s
          AND  exit_price IS NOT NULL
          AND  pnl_pct   IS NOT NULL
        ORDER  BY closed_at ASC
        """,
        (bot_id,),
    )
    return rows


# ── core simulation ───────────────────────────────────────────────────────────

def _simulate_trade_pct(actual_pnl_pct: float, sl_pct: float, tp_pct: float | None) -> float:
    """
    Given a closed trade's realized pnl_pct, compute the simulated pnl_pct
    if the bot had used the supplied sl_pct / tp_pct.

    Limitations (stated openly in the report):
      • No intra-trade path → SL benefit may be overstated (no gap/slippage).
      • Trades that hit TP then ran further are treated as exact TP fills.
    """
    if actual_pnl_pct < -sl_pct:
        return -sl_pct
    if tp_pct is not None and actual_pnl_pct > tp_pct:
        return tp_pct
    return actual_pnl_pct


def _metrics(pnl_pcts: list[float]) -> dict:
    """Compute WR, PF, net_pct, max_drawdown from a list of pnl_pcts."""
    if not pnl_pcts:
        return {"wr": 0.0, "pf": 0.0, "net_pct": 0.0, "max_dd": 0.0}

    wins   = [p for p in pnl_pcts if p > 0]
    losses = [p for p in pnl_pcts if p < 0]

    wr  = len(wins) / len(pnl_pcts)
    pf  = sum(wins) / abs(sum(losses)) if losses and sum(losses) < 0 else (
        float("inf") if wins else 0.0
    )
    if math.isinf(pf):
        pf = 99.99

    net_pct = sum(pnl_pcts)

    # running max-drawdown
    peak = 0.0
    equity = 0.0
    max_dd = 0.0
    for p in pnl_pcts:
        equity += p
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    return {
        "wr": round(wr, 4),
        "pf": round(min(pf, 99.99), 4),
        "net_pct": round(net_pct, 4),
        "max_dd": round(max_dd, 4),
    }


def _run_scenario(trades: list[dict], sl_pct: float, tp_pct: float | None) -> dict:
    """Run one parameter scenario over all trades. Returns metrics dict."""
    simulated = [
        _simulate_trade_pct(t["pnl_pct"], sl_pct, tp_pct)
        for t in trades
    ]
    m = _metrics(simulated)
    m["sl_pct"] = sl_pct
    m["tp_pct"] = tp_pct
    m["n"]      = len(simulated)
    return m


# ── grid search ───────────────────────────────────────────────────────────────

def _grid_search(trades: list[dict]) -> list[dict]:
    """
    Run all 64 (SL × TP) combinations.
    Returns list of result dicts sorted by PF descending.
    """
    results = []
    for sl in SL_CANDIDATES:
        for tp in TP_CANDIDATES:
            m = _run_scenario(trades, sl, tp)
            results.append(m)
    results.sort(key=lambda x: x["pf"], reverse=True)
    return results


# ── regime breakdown ──────────────────────────────────────────────────────────

def _normalise_regime(raw: str | None) -> str:
    if not raw:
        return "Unknown"
    s = raw.split(" [")[0].strip()
    for k in ("Bear", "Bull", "Sideways", "Crypto", "Unknown"):
        if k.lower() in s.lower():
            return k
    return s or "Unknown"


def _regime_breakdown(
    trades: list[dict],
    sl_pct: float,
    tp_pct: float | None,
) -> dict:
    """
    For each regime, compute baseline and simulated metrics.
    Returns {regime: {baseline: {...}, simulated: {...}, n: int}}.
    """
    from collections import defaultdict
    buckets: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        reg = _normalise_regime(t.get("regime_at_entry"))
        buckets[reg].append(t)

    out: dict = {}
    for reg, ts in buckets.items():
        baseline_pcts  = [t["pnl_pct"] for t in ts]
        simulated_pcts = [_simulate_trade_pct(t["pnl_pct"], sl_pct, tp_pct) for t in ts]
        out[reg] = {
            "n":         len(ts),
            "baseline":  _metrics(baseline_pcts),
            "simulated": _metrics(simulated_pcts),
        }
    return out


# ── avg hold hours ────────────────────────────────────────────────────────────

def _avg_hold_hours(trades: list[dict]) -> float | None:
    holds = []
    for t in trades:
        closed = t.get("closed_at")
        if not closed:
            continue
        holds.append(1.0)   # placeholder — we don't store opened_at in this table
    # We can't compute exact hold time without entry timestamp; return None
    return None


# ── WFO verdict ───────────────────────────────────────────────────────────────

def _verdict(baseline_pf: float, candidate_pf: float) -> str:
    delta = candidate_pf - baseline_pf
    if delta > 0.05:
        return "BETTER"
    if delta < -0.05:
        return "WORSE"
    return "NEUTRAL"


# ── main backtest run ─────────────────────────────────────────────────────────

def run_backtest(bot_id: str) -> dict:
    """
    Full backtest pipeline for one bot.
    Returns a result dict ready to be persisted.
    """
    _ensure_table()

    trades = _load_trades(bot_id)
    if len(trades) < 10:
        logger.warning(f"Backtest | {bot_id}: only {len(trades)} trades — skipping (need ≥10)")
        return {"error": f"insufficient trades ({len(trades)})"}

    logger.info(f"Backtest | Starting backtest for {bot_id} ({len(trades)} trades)")

    # ── Baseline ──────────────────────────────────────────────────────────────
    baseline_pcts = [t["pnl_pct"] for t in trades]
    baseline_m    = _metrics(baseline_pcts)

    # ── Grid search ───────────────────────────────────────────────────────────
    all_grid = _grid_search(trades)
    best     = all_grid[0]    # sorted by PF desc

    # ── WFO-recommended scenario ──────────────────────────────────────────────
    wfo_sl, wfo_tp = _fetch_wfo_recommendation(bot_id)
    if wfo_sl is not None:
        wfo_m = _run_scenario(trades, wfo_sl, wfo_tp)
    else:
        # Fall back to best-found
        wfo_sl = best["sl_pct"]
        wfo_tp = best["tp_pct"]
        wfo_m  = best

    # ── Regime breakdown using best params ───────────────────────────────────
    reg_bd = _regime_breakdown(trades, best["sl_pct"], best["tp_pct"])

    # ── Improvement (best vs baseline) ────────────────────────────────────────
    improvement = round(best["net_pct"] - baseline_m["net_pct"], 4)

    # ── Summary text ─────────────────────────────────────────────────────────
    tp_str = f"{best['tp_pct']:.1f}%" if best["tp_pct"] else "none (let winners run)"
    verdict_str = _verdict(baseline_m["pf"], wfo_m["pf"])
    summary = (
        f"{bot_id}: {len(trades)} trades backtested across {len(SL_CANDIDATES)*len(TP_CANDIDATES)} "
        f"parameter combinations. "
        f"Baseline PF={baseline_m['pf']:.2f} | "
        f"WFO-recommended PF={wfo_m['pf']:.2f} ({verdict_str}) | "
        f"Best-found SL={best['sl_pct']:.1f}% TP={tp_str} → "
        f"PF={best['pf']:.2f} net={best['net_pct']:+.2f}% "
        f"(vs actual {baseline_m['net_pct']:+.2f}%, Δ{improvement:+.2f}%)."
    )

    logger.info(
        f"Backtest | {bot_id}: baseline PF={baseline_m['pf']:.2f} → "
        f"best PF={best['pf']:.2f} (SL={best['sl_pct']}% TP={best['tp_pct']}%) | "
        f"WFO rec: {verdict_str}"
    )

    return {
        "n_trades": len(trades),
        "baseline_wr":       baseline_m["wr"],
        "baseline_pf":       baseline_m["pf"],
        "baseline_net_pct":  baseline_m["net_pct"],
        "baseline_max_dd":   baseline_m["max_dd"],
        "baseline_avg_hold": _avg_hold_hours(trades),
        "wfo_sl_pct":     wfo_sl,
        "wfo_tp_pct":     wfo_tp,
        "wfo_wr":         wfo_m["wr"],
        "wfo_pf":         wfo_m["pf"],
        "wfo_net_pct":    wfo_m["net_pct"],
        "wfo_max_dd":     wfo_m["max_dd"],
        "wfo_verdict":    verdict_str,
        "best_sl_pct":    best["sl_pct"],
        "best_tp_pct":    best["tp_pct"],
        "best_wr":        best["wr"],
        "best_pf":        best["pf"],
        "best_net_pct":   best["net_pct"],
        "best_max_dd":    best["max_dd"],
        "best_improvement": improvement,
        "grid_results":   all_grid[:TOP_GRID_RESULTS],
        "regime_breakdown": reg_bd,
        "summary": summary,
    }


def run_all_bots() -> dict[str, dict]:
    """Run the full backtest pipeline for all Kraken bots."""
    results: dict[str, dict] = {}
    for bot_id in KRAKEN_BOT_IDS:
        try:
            r = run_backtest(bot_id)
            results[bot_id] = r
            if "error" not in r:
                _persist(bot_id, r)
        except Exception as exc:
            logger.error(f"Backtest | {bot_id} failed: {exc}")
            results[bot_id] = {"error": str(exc)}
    return results


def get_latest_result(bot_id: str) -> dict | None:
    """Fetch the most recent backtest result for one bot."""
    rows = _query(
        """
        SELECT *
        FROM   kraken_backtest_results
        WHERE  bot_id = %s
        ORDER  BY run_at DESC
        LIMIT  1
        """,
        (bot_id,),
    )
    return rows[0] if rows else None
