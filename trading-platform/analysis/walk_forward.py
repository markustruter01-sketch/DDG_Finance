"""
walk_forward.py — Stage 5: Walk-Forward Parameter Optimiser
=============================================================
Runs every Sunday at 2:00 AM UTC for all three Kraken bots.
Fully deterministic — no LLM calls.

Approach
--------
Since entry_zscore is not reliably populated in the trade log, the optimiser
uses what IS available: pnl_pct, pnl_usd, fees_usd, regime_at_entry, reason
(stop / take_profit / trail / timeout), symbol, side, and closed_at.

Sliding 7-day windows are analysed to produce:

  1. Per-window performance metrics (WR, PF, avg win/loss %)
  2. Recommended stop-loss %   — median |pnl_pct| of trades that hit the stop
  3. Recommended take-profit % — median pnl_pct of TP-exited winners
  4. Regime ranking            — which regime has the best PF across windows
  5. Focus symbols             — consistent top performers across windows
  6. Avoid symbols             — consistent worst performers across windows
  7. Stability score           — how consistent WR/PF are across windows (0–100)
  8. Out-of-sample validation  — did the prior window's top symbols stay top?

Results are stored in kraken_wfo_results (JSONB) and surfaced by the
portfolio report section.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from statistics import median, stdev
from typing import Any

from loguru import logger

# ── constants ──────────────────────────────────────────────────────────────

WINDOW_DAYS  = 7    # in-sample window length
STEP_DAYS    = 3    # how far the window moves each iteration
MIN_TRADES   = 5    # minimum trades to score a window
TOP_N_SYMBOLS = 3   # how many focus/avoid symbols to recommend


# ── DB helpers ──────────────────────────────────────────────────────────────

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
        logger.warning(f"WFO | DB query failed: {exc}")
        return []


def _ensure_table() -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS kraken_wfo_results (
        id                      BIGSERIAL PRIMARY KEY,
        bot_id                  TEXT NOT NULL,
        run_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        data_from               TIMESTAMPTZ,
        data_to                 TIMESTAMPTZ,
        total_trades            INTEGER NOT NULL DEFAULT 0,
        windows_analysed        INTEGER NOT NULL DEFAULT 0,
        overall_confidence      TEXT NOT NULL DEFAULT 'LOW',
        stability_score         INTEGER NOT NULL DEFAULT 0,
        rec_sl_pct              DOUBLE PRECISION,
        rec_tp_pct              DOUBLE PRECISION,
        rec_best_regime         TEXT,
        rec_worst_regime        TEXT,
        rec_focus_symbols       JSONB NOT NULL DEFAULT '[]',
        rec_avoid_symbols       JSONB NOT NULL DEFAULT '[]',
        window_results          JSONB NOT NULL DEFAULT '[]',
        regime_breakdown        JSONB NOT NULL DEFAULT '{}',
        oos_validation          JSONB NOT NULL DEFAULT '{}',
        summary                 TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_kraken_wfo_bot ON kraken_wfo_results (bot_id, run_at DESC);
    """
    try:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(ddl)
            conn.commit()
    except Exception as exc:
        logger.warning(f"WFO | _ensure_table failed: {exc}")


# ── core math ───────────────────────────────────────────────────────────────

def _profit_factor(trades: list[dict]) -> float:
    gross_profit = sum(t["pnl_usd"] for t in trades if t["pnl_usd"] > 0)
    gross_loss   = abs(sum(t["pnl_usd"] for t in trades if t["pnl_usd"] <= 0))
    if gross_loss == 0:
        return 9.99 if gross_profit > 0 else 1.0
    return min(gross_profit / gross_loss, 9.99)


def _win_rate(trades: list[dict]) -> float:
    if not trades:
        return 0.0
    return sum(1 for t in trades if t["pnl_usd"] > 0) / len(trades)


def _avg_win_pct(trades: list[dict]) -> float | None:
    wins = [t["pnl_pct"] for t in trades if t["pnl_usd"] > 0]
    return sum(wins) / len(wins) if wins else None


def _avg_loss_pct(trades: list[dict]) -> float | None:
    losses = [t["pnl_pct"] for t in trades if t["pnl_usd"] <= 0]
    return sum(losses) / len(losses) if losses else None


def _symbol_pf(trades: list[dict]) -> dict[str, float]:
    """Return profit factor per symbol (only symbols with >= 2 trades)."""
    from collections import defaultdict
    buckets: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        buckets[t["symbol"]].append(t)
    result = {}
    for sym, ts in buckets.items():
        if len(ts) >= 2:
            result[sym] = _profit_factor(ts)
    return result


def _regime_pf(trades: list[dict]) -> dict[str, dict]:
    """Return metrics per regime."""
    from collections import defaultdict
    buckets: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        r = (t.get("regime_at_entry") or "Unknown").split(" [")[0].strip()
        buckets[r].append(t)
    result = {}
    for reg, ts in buckets.items():
        if ts:
            result[reg] = {
                "n":   len(ts),
                "pf":  round(_profit_factor(ts), 3),
                "wr":  round(_win_rate(ts), 3),
                "net": round(sum(t["pnl_usd"] for t in ts), 2),
            }
    return result


# ── per-window analysis ──────────────────────────────────────────────────────

def _analyse_window(trades: list[dict], label: str) -> dict:
    n = len(trades)
    if n < MIN_TRADES:
        return {"label": label, "n": n, "skipped": True, "reason": f"< {MIN_TRADES} trades"}

    pf   = _profit_factor(trades)
    wr   = _win_rate(trades)
    aw   = _avg_win_pct(trades)
    al   = _avg_loss_pct(trades)
    sym_pf = _symbol_pf(trades)

    # Exit reason distribution
    reasons: dict[str, int] = {}
    for t in trades:
        r = (t.get("reason") or "unknown").lower()
        reasons[r] = reasons.get(r, 0) + 1
    dominant_exit = max(reasons, key=reasons.get) if reasons else "unknown"

    # SL and TP magnitudes (to derive parameter recommendations)
    stop_losses   = [abs(t["pnl_pct"]) for t in trades if t["pnl_usd"] < 0 and "stop" in (t.get("reason") or "")]
    tp_wins       = [t["pnl_pct"] for t in trades if t["pnl_usd"] > 0 and ("take_profit" in (t.get("reason") or "") or "tp" in (t.get("reason") or ""))]
    timeout_losses = [abs(t["pnl_pct"]) for t in trades if t["pnl_usd"] < 0 and "timeout" in (t.get("reason") or "")]
    trail_wins    = [t["pnl_pct"] for t in trades if t["pnl_usd"] > 0 and "trail" in (t.get("reason") or "")]

    sl_median  = round(median(stop_losses), 3)  if stop_losses  else None
    tp_median  = round(median(tp_wins + trail_wins), 3) if (tp_wins or trail_wins) else None

    top_symbols    = sorted(sym_pf, key=sym_pf.get, reverse=True)[:TOP_N_SYMBOLS]
    bottom_symbols = sorted(sym_pf, key=sym_pf.get)[:TOP_N_SYMBOLS]

    return {
        "label":           label,
        "n":               n,
        "pf":              round(pf, 3),
        "wr":              round(wr, 3),
        "avg_win_pct":     round(aw, 3) if aw is not None else None,
        "avg_loss_pct":    round(al, 3) if al is not None else None,
        "dominant_exit":   dominant_exit,
        "exit_reasons":    reasons,
        "sl_median_pct":   sl_median,
        "tp_median_pct":   tp_median,
        "top_symbols":     top_symbols,
        "bottom_symbols":  bottom_symbols,
        "symbol_pf":       {k: round(v, 3) for k, v in sym_pf.items()},
        "regime_pf":       _regime_pf(trades),
        "n_stop_exits":    len(stop_losses),
        "n_tp_exits":      len(tp_wins),
        "n_trail_exits":   len(trail_wins),
        "n_timeout_exits": len(timeout_losses),
        "net_usd":         round(sum(t["pnl_usd"] for t in trades), 2),
    }


# ── out-of-sample validation ─────────────────────────────────────────────────

def _validate_oos(window_results: list[dict]) -> dict:
    """
    Check: did the top symbols from window[n] remain top in window[n+1]?
    Returns a dict with hit_rate (0–1) and n_comparisons.
    """
    if len(window_results) < 2:
        return {"hit_rate": None, "n_comparisons": 0, "detail": "< 2 windows"}

    hits = 0
    total = 0
    detail_lines = []
    for i in range(len(window_results) - 1):
        w_in  = window_results[i]
        w_oos = window_results[i + 1]
        if w_in.get("skipped") or w_oos.get("skipped"):
            continue
        prior_top = set(w_in.get("top_symbols", []))
        oos_top   = set(w_oos.get("top_symbols", []))
        overlap = len(prior_top & oos_top)
        hits  += overlap
        total += len(prior_top) if prior_top else 1
        detail_lines.append(
            f"  Win{i+1}→Win{i+2}: {overlap}/{len(prior_top)} top symbols carried over"
        )

    hit_rate = round(hits / total, 3) if total > 0 else 0.0
    return {
        "hit_rate":      hit_rate,
        "n_comparisons": total,
        "detail":        detail_lines,
    }


# ── stability score ───────────────────────────────────────────────────────────

def _stability_score(window_results: list[dict]) -> int:
    """
    Score 0–100: how consistent is WR and PF across windows?
    Uses coefficient of variation (lower CV → higher score).
    """
    valid = [w for w in window_results if not w.get("skipped")]
    if len(valid) < 2:
        return 0

    wrs = [w["wr"] for w in valid]
    pfs = [min(w["pf"], 5.0) for w in valid]

    def cv(vals):
        if not vals or len(vals) < 2:
            return 1.0
        m = sum(vals) / len(vals)
        if m == 0:
            return 1.0
        return stdev(vals) / m

    wr_cv  = cv(wrs)
    pf_cv  = cv(pfs)
    avg_cv = (wr_cv + pf_cv) / 2

    # CV of 0 → score 100; CV of 1+ → score 0
    score = max(0, int((1 - min(avg_cv, 1.0)) * 100))
    return score


# ── derive recommendations ────────────────────────────────────────────────────

def _derive_recommendations(window_results: list[dict], all_trades: list[dict]) -> dict:
    valid_wins = [w for w in window_results if not w.get("skipped")]

    # --- Recommended SL% (median across windows that have stop data) ---
    sl_values = [w["sl_median_pct"] for w in valid_wins if w.get("sl_median_pct") is not None]
    rec_sl = round(median(sl_values), 2) if sl_values else None

    # --- Recommended TP% ---
    tp_values = [w["tp_median_pct"] for w in valid_wins if w.get("tp_median_pct") is not None]
    rec_tp = round(median(tp_values), 2) if tp_values else None

    # --- Focus symbols: appear in top_symbols in most windows ---
    from collections import Counter
    top_counts: Counter = Counter()
    for w in valid_wins:
        for sym in w.get("top_symbols", []):
            top_counts[sym] += 1
    bottom_counts: Counter = Counter()
    for w in valid_wins:
        for sym in w.get("bottom_symbols", []):
            bottom_counts[sym] += 1

    # A symbol qualifies as "focus" if it appeared in top in ≥50% of windows
    n_valid = len(valid_wins)
    focus_threshold = max(1, n_valid // 2)
    focus_symbols  = [sym for sym, cnt in top_counts.most_common(TOP_N_SYMBOLS) if cnt >= focus_threshold]
    avoid_symbols  = [sym for sym, cnt in bottom_counts.most_common(TOP_N_SYMBOLS) if cnt >= focus_threshold]

    # --- Best regime (highest median PF across windows) ---
    regime_agg: dict[str, list[float]] = {}
    for w in valid_wins:
        for reg, metrics in w.get("regime_pf", {}).items():
            regime_agg.setdefault(reg, []).append(metrics["pf"])
    regime_med_pf = {r: median(pfs) for r, pfs in regime_agg.items() if pfs}
    rec_best_regime  = max(regime_med_pf, key=regime_med_pf.get) if regime_med_pf else None
    rec_worst_regime = min(regime_med_pf, key=regime_med_pf.get) if regime_med_pf else None

    return {
        "rec_sl_pct":         rec_sl,
        "rec_tp_pct":         rec_tp,
        "rec_focus_symbols":  focus_symbols,
        "rec_avoid_symbols":  avoid_symbols,
        "rec_best_regime":    rec_best_regime,
        "rec_worst_regime":   rec_worst_regime,
    }


# ── confidence level ──────────────────────────────────────────────────────────

def _confidence(n_valid_windows: int, stability: int, oos: dict) -> str:
    hit_rate = oos.get("hit_rate")
    if n_valid_windows >= 3 and stability >= 60:
        if hit_rate is None or hit_rate >= 0.40:
            return "HIGH"
        return "MEDIUM"
    if n_valid_windows >= 2 and stability >= 30:
        return "MEDIUM"
    return "LOW"


# ── summary text ──────────────────────────────────────────────────────────────

def _build_summary(bot_id: str, n_trades: int, n_windows: int, recs: dict,
                   stability: int, confidence: str, oos: dict) -> str:
    lines = [
        f"Walk-Forward Analysis for {bot_id}",
        f"Data: {n_trades} trades | {n_windows} windows | Stability: {stability}/100 | Confidence: {confidence}",
    ]
    if recs["rec_sl_pct"] is not None:
        lines.append(f"Recommended SL  : {recs['rec_sl_pct']:.2f}% (median observed stop exit)")
    if recs["rec_tp_pct"] is not None:
        lines.append(f"Recommended TP  : {recs['rec_tp_pct']:.2f}% (median observed TP exit)")
    if recs["rec_best_regime"]:
        lines.append(f"Best regime     : {recs['rec_best_regime']}")
    if recs["rec_worst_regime"]:
        lines.append(f"Worst regime    : {recs['rec_worst_regime']}")
    if recs["rec_focus_symbols"]:
        lines.append(f"Focus symbols   : {', '.join(recs['rec_focus_symbols'])}")
    if recs["rec_avoid_symbols"]:
        lines.append(f"Avoid symbols   : {', '.join(recs['rec_avoid_symbols'])}")
    oos_hit = oos.get("hit_rate")
    if oos_hit is not None:
        lines.append(f"OOS symbol carry-over: {oos_hit:.0%}")
    return "\n".join(lines)


# ── main entry point ──────────────────────────────────────────────────────────

def run_wfo(bot_id: str) -> dict[str, Any]:
    """
    Run walk-forward optimisation for one Kraken bot.
    Loads all closed trades, builds sliding 7-day windows, derives
    parameter recommendations, persists to DB, and returns the result.
    """
    _ensure_table()
    logger.info(f"WFO | Starting walk-forward analysis for {bot_id}")

    # Load all closed trades
    trades = _query(
        """
        SELECT symbol, side, pnl_pct, pnl_usd, fees_usd, reason,
               regime_at_entry, closed_at
        FROM   kraken_trades
        WHERE  bot_id = %s
          AND  pnl_usd IS NOT NULL
        ORDER  BY closed_at ASC
        """,
        (bot_id,),
    )

    if not trades:
        logger.warning(f"WFO | {bot_id}: no trade data — skipping")
        result = _empty_result(bot_id)
        _persist(bot_id, result)
        return result

    # Date bounds
    data_from = trades[0]["closed_at"]
    data_to   = trades[-1]["closed_at"]
    total_span_days = (data_to - data_from).days if hasattr(data_to, "days") else 0

    # Build sliding windows
    window_results: list[dict] = []
    cursor = data_from.replace(tzinfo=timezone.utc) if data_from.tzinfo is None else data_from
    end_bound = data_to.replace(tzinfo=timezone.utc) if data_to.tzinfo is None else data_to

    while cursor + timedelta(days=WINDOW_DAYS) <= end_bound + timedelta(days=1):
        w_start = cursor
        w_end   = cursor + timedelta(days=WINDOW_DAYS)
        w_trades = [
            t for t in trades
            if _as_utc(t["closed_at"]) >= w_start and _as_utc(t["closed_at"]) < w_end
        ]
        label = f"{w_start.strftime('%m-%d')} → {w_end.strftime('%m-%d')}"
        window_results.append(_analyse_window(w_trades, label))
        cursor += timedelta(days=STEP_DAYS)

    # Also add a final "last 7 days" window to anchor recency
    recent_cutoff = end_bound - timedelta(days=WINDOW_DAYS)
    recent_trades = [t for t in trades if _as_utc(t["closed_at"]) >= recent_cutoff]
    recent_label  = f"Most recent {WINDOW_DAYS}d"
    if recent_trades and (not window_results or window_results[-1]["label"] != recent_label):
        window_results.append(_analyse_window(recent_trades, recent_label))

    n_valid  = sum(1 for w in window_results if not w.get("skipped"))
    stability = _stability_score(window_results)
    oos       = _validate_oos(window_results)
    recs      = _derive_recommendations(window_results, trades)
    confidence = _confidence(n_valid, stability, oos)
    regime_breakdown = _regime_pf(trades)

    summary = _build_summary(
        bot_id, len(trades), n_valid, recs, stability, confidence, oos
    )

    result = {
        "bot_id":              bot_id,
        "run_at":              datetime.now(timezone.utc).isoformat(),
        "data_from":           data_from.isoformat() if hasattr(data_from, "isoformat") else str(data_from),
        "data_to":             data_to.isoformat()   if hasattr(data_to,   "isoformat") else str(data_to),
        "total_trades":        len(trades),
        "windows_analysed":    n_valid,
        "overall_confidence":  confidence,
        "stability_score":     stability,
        "regime_breakdown":    regime_breakdown,
        "oos_validation":      oos,
        "window_results":      window_results,
        "summary":             summary,
        **recs,
    }

    _persist(bot_id, result)
    logger.info(
        f"WFO | {bot_id}: {len(trades)} trades | {n_valid} windows | "
        f"stability={stability}/100 | confidence={confidence}"
    )
    return result


def _as_utc(dt) -> datetime:
    if dt is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _empty_result(bot_id: str) -> dict:
    return {
        "bot_id":              bot_id,
        "run_at":              datetime.now(timezone.utc).isoformat(),
        "data_from":           None,
        "data_to":             None,
        "total_trades":        0,
        "windows_analysed":    0,
        "overall_confidence":  "LOW",
        "stability_score":     0,
        "rec_sl_pct":          None,
        "rec_tp_pct":          None,
        "rec_best_regime":     None,
        "rec_worst_regime":    None,
        "rec_focus_symbols":   [],
        "rec_avoid_symbols":   [],
        "window_results":      [],
        "regime_breakdown":    {},
        "oos_validation":      {},
        "summary":             "No trade data available.",
    }


def _persist(bot_id: str, result: dict) -> None:
    sql = """
    INSERT INTO kraken_wfo_results (
        bot_id, run_at, data_from, data_to, total_trades,
        windows_analysed, overall_confidence, stability_score,
        rec_sl_pct, rec_tp_pct, rec_best_regime, rec_worst_regime,
        rec_focus_symbols, rec_avoid_symbols,
        window_results, regime_breakdown, oos_validation, summary
    ) VALUES (
        %s, NOW(), %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    """
    try:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (
                    bot_id,
                    result.get("data_from"),
                    result.get("data_to"),
                    result.get("total_trades", 0),
                    result.get("windows_analysed", 0),
                    result.get("overall_confidence", "LOW"),
                    result.get("stability_score", 0),
                    result.get("rec_sl_pct"),
                    result.get("rec_tp_pct"),
                    result.get("rec_best_regime"),
                    result.get("rec_worst_regime"),
                    json.dumps(result.get("rec_focus_symbols", [])),
                    json.dumps(result.get("rec_avoid_symbols", [])),
                    json.dumps(result.get("window_results", [])),
                    json.dumps(result.get("regime_breakdown", {})),
                    json.dumps(result.get("oos_validation", {})),
                    result.get("summary", ""),
                ))
            conn.commit()
        logger.debug(f"WFO | Persisted result for {bot_id}")
    except Exception as exc:
        logger.warning(f"WFO | Failed to persist result for {bot_id}: {exc}")


def run_all_bots() -> dict[str, dict]:
    """Run WFO for all Kraken-based bots. Called by Sunday scheduler."""
    bot_ids = ["davy-jones", "blackbeard", "calypso"]
    results = {}
    for bid in bot_ids:
        try:
            results[bid] = run_wfo(bid)
        except Exception as exc:
            logger.error(f"WFO | {bid}: analysis failed: {exc}")
            results[bid] = {"error": str(exc)}
    return results


def get_latest_result(bot_id: str) -> dict | None:
    """Load the most recent WFO result for one bot."""
    rows = _query(
        """
        SELECT bot_id, run_at, total_trades, windows_analysed, overall_confidence,
               stability_score, rec_sl_pct, rec_tp_pct, rec_best_regime, rec_worst_regime,
               rec_focus_symbols, rec_avoid_symbols, window_results,
               regime_breakdown, oos_validation, summary
        FROM   kraken_wfo_results
        WHERE  bot_id = %s
        ORDER  BY run_at DESC
        LIMIT  1
        """,
        (bot_id,),
    )
    return rows[0] if rows else None
