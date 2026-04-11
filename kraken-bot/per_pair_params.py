"""
per_pair_params.py — Stage 3: Per-Pair Automatic Parameter Adjustment
=======================================================================
Computes per-pair performance statistics from recent closed trades and
derives two auto-tuned parameters for each symbol:

  1. auto_size_mult   — sizing multiplier derived from Profit Factor
  2. auto_zscore_factor — z-score threshold multiplier derived from win rate

Rules
-----
- Requires MIN_TRADES in the lookback window (default 8) before adjusting.
- Parameters are cached in the DB table `kraken_pair_params` and returned
  quickly on subsequent calls. The full recompute is triggered by the caller
  every AUTO_PARAMS_REFRESH_HOURS (default 6).
- Manual PAIR_SIZING_PENALIZED / PAIR_SIZING_BOOSTED always override
  auto_size_mult in main.py — this module only produces a recommendation.

Sizing multiplier (Profit Factor → scale):
  PF ≥ 1.5  and WR ≥ 50%   →  1.20×   (auto-boost)
  PF 1.0–1.5               →  1.00×   (neutral)
  PF 0.60–1.0              →  0.75×   (caution)
  PF 0.30–0.60             →  0.50×   (suppress)
  PF < 0.30                →  0.30×   (heavy suppress)
  < MIN_TRADES             →  1.00×   (no data)

Z-score threshold factor (win rate → multiplier on base ZSCORE_ENTRY):
  WR ≥ 55%                  →  0.90×   (lower bar — proven pair)
  WR 40–55%                 →  1.00×   (neutral)
  WR 25–40%                 →  1.15×   (raise bar)
  WR < 25%                  →  1.30×   (significantly raise bar)
  < MIN_TRADES              →  1.00×   (no data)
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

# ── constants ──────────────────────────────────────────────────────────────
LOOKBACK_DAYS: int = 30
MIN_TRADES: int = 8
AUTO_PARAMS_REFRESH_HOURS: int = 6


@dataclass
class PairStats:
    symbol: str
    bot_id: str
    trade_count: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    auto_size_mult: float = 1.0
    auto_zscore_factor: float = 1.0

    def has_data(self) -> bool:
        return self.trade_count >= MIN_TRADES


def _calc_auto_size_mult(pf: float, wr: float, n: int) -> float:
    if n < MIN_TRADES:
        return 1.0
    if pf >= 1.5 and wr >= 0.50:
        return 1.20
    if pf >= 1.0:
        return 1.00
    if pf >= 0.60:
        return 0.75
    if pf >= 0.30:
        return 0.50
    return 0.30


def _calc_auto_zscore_factor(wr: float, n: int) -> float:
    if n < MIN_TRADES:
        return 1.0
    if wr >= 0.55:
        return 0.90
    if wr >= 0.40:
        return 1.00
    if wr >= 0.25:
        return 1.15
    return 1.30


# ── DB helpers ─────────────────────────────────────────────────────────────

def _get_conn():
    """Return a psycopg2 connection via the module-level pool in db.py."""
    try:
        import db as _db_mod
        from contextlib import contextmanager
        return _db_mod._conn()
    except Exception as exc:
        raise RuntimeError(f"per_pair_params | cannot get DB connection: {exc}") from exc


def _ensure_table() -> None:
    """Create kraken_pair_params table if it doesn't exist."""
    ddl = """
    CREATE TABLE IF NOT EXISTS kraken_pair_params (
        bot_id             TEXT NOT NULL,
        symbol             TEXT NOT NULL,
        computed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        trade_count        INTEGER NOT NULL DEFAULT 0,
        win_rate           DOUBLE PRECISION NOT NULL DEFAULT 0,
        profit_factor      DOUBLE PRECISION NOT NULL DEFAULT 0,
        avg_win_pct        DOUBLE PRECISION NOT NULL DEFAULT 0,
        avg_loss_pct       DOUBLE PRECISION NOT NULL DEFAULT 0,
        auto_size_mult     DOUBLE PRECISION NOT NULL DEFAULT 1.0,
        auto_zscore_factor DOUBLE PRECISION NOT NULL DEFAULT 1.0,
        PRIMARY KEY (bot_id, symbol)
    );
    """
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(ddl)
            conn.commit()
    except Exception as exc:
        logger.warning(f"per_pair_params | _ensure_table failed: {exc}")


def compute_per_pair_stats(bot_id: str) -> dict[str, PairStats]:
    """
    Query closed trades for `bot_id` in the last LOOKBACK_DAYS days.
    Returns a dict of symbol → PairStats with auto-computed adjustments.
    """
    query = """
    SELECT
        symbol,
        COUNT(*)                                                       AS n,
        SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END)                  AS wins,
        COALESCE(SUM(CASE WHEN pnl_usd > 0 THEN pnl_pct ELSE NULL END)
                 / NULLIF(SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END), 0), 0) AS avg_win_pct,
        COALESCE(ABS(SUM(CASE WHEN pnl_usd <= 0 THEN pnl_pct ELSE NULL END))
                 / NULLIF(SUM(CASE WHEN pnl_usd <= 0 THEN 1 ELSE 0 END), 0), 0) AS avg_loss_pct,
        COALESCE(SUM(CASE WHEN pnl_usd > 0 THEN pnl_usd ELSE 0 END), 0)  AS gross_profit,
        COALESCE(ABS(SUM(CASE WHEN pnl_usd <= 0 THEN pnl_usd ELSE 0 END)), 0) AS gross_loss
    FROM  kraken_trades
    WHERE bot_id = %s
      AND closed_at >= NOW() - INTERVAL '%s days'
    GROUP BY symbol
    """
    result: dict[str, PairStats] = {}
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (bot_id, LOOKBACK_DAYS))
                for row in cur.fetchall():
                    sym, n, wins, avg_win, avg_loss, gp, gl = row
                    n = int(n)
                    wins = int(wins or 0)
                    wr = wins / n if n > 0 else 0.0
                    pf = float(gp) / float(gl) if gl and gl > 0 else (9.99 if gp > 0 else 0.0)
                    pf = min(pf, 9.99)
                    size_mult = _calc_auto_size_mult(pf, wr, n)
                    z_factor = _calc_auto_zscore_factor(wr, n)
                    ps = PairStats(
                        symbol=sym,
                        bot_id=bot_id,
                        trade_count=n,
                        win_rate=wr,
                        profit_factor=pf,
                        avg_win_pct=float(avg_win or 0),
                        avg_loss_pct=float(avg_loss or 0),
                        auto_size_mult=size_mult,
                        auto_zscore_factor=z_factor,
                    )
                    result[sym] = ps
    except Exception as exc:
        logger.warning(f"per_pair_params | compute_per_pair_stats failed: {exc}")
    return result


def upsert_pair_params(stats_dict: dict[str, PairStats]) -> None:
    """Persist computed pair params to DB (UPSERT)."""
    if not stats_dict:
        return
    _ensure_table()
    upsert_sql = """
    INSERT INTO kraken_pair_params
        (bot_id, symbol, computed_at, trade_count, win_rate, profit_factor,
         avg_win_pct, avg_loss_pct, auto_size_mult, auto_zscore_factor)
    VALUES (%s, %s, NOW(), %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (bot_id, symbol) DO UPDATE SET
        computed_at        = EXCLUDED.computed_at,
        trade_count        = EXCLUDED.trade_count,
        win_rate           = EXCLUDED.win_rate,
        profit_factor      = EXCLUDED.profit_factor,
        avg_win_pct        = EXCLUDED.avg_win_pct,
        avg_loss_pct       = EXCLUDED.avg_loss_pct,
        auto_size_mult     = EXCLUDED.auto_size_mult,
        auto_zscore_factor = EXCLUDED.auto_zscore_factor
    """
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                for ps in stats_dict.values():
                    cur.execute(upsert_sql, (
                        ps.bot_id, ps.symbol, ps.trade_count, ps.win_rate,
                        ps.profit_factor, ps.avg_win_pct, ps.avg_loss_pct,
                        ps.auto_size_mult, ps.auto_zscore_factor,
                    ))
            conn.commit()
        logger.debug(f"per_pair_params | Upserted {len(stats_dict)} pair params for {next(iter(stats_dict)).split('/')[0] if stats_dict else '?'}")
    except Exception as exc:
        logger.warning(f"per_pair_params | upsert_pair_params failed: {exc}")


def load_pair_params(bot_id: str) -> dict[str, PairStats]:
    """Load previously persisted pair params from DB. Fast fallback if compute is unavailable."""
    _ensure_table()
    query = """
    SELECT symbol, trade_count, win_rate, profit_factor,
           avg_win_pct, avg_loss_pct, auto_size_mult, auto_zscore_factor
    FROM   kraken_pair_params
    WHERE  bot_id = %s
    """
    result: dict[str, PairStats] = {}
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (bot_id,))
                for row in cur.fetchall():
                    sym, n, wr, pf, aw, al, sm, zf = row
                    result[sym] = PairStats(
                        symbol=sym,
                        bot_id=bot_id,
                        trade_count=int(n),
                        win_rate=float(wr),
                        profit_factor=float(pf),
                        avg_win_pct=float(aw),
                        avg_loss_pct=float(al),
                        auto_size_mult=float(sm),
                        auto_zscore_factor=float(zf),
                    )
    except Exception as exc:
        logger.warning(f"per_pair_params | load_pair_params failed: {exc}")
    return result


def refresh_and_get(bot_id: str) -> dict[str, PairStats]:
    """
    Full recompute: compute stats, persist to DB, return result dict.
    Called every AUTO_PARAMS_REFRESH_HOURS by main.py.
    """
    stats = compute_per_pair_stats(bot_id)
    if stats:
        upsert_pair_params(stats)
        adjusted = sum(1 for ps in stats.values() if ps.has_data())
        logger.info(
            f"AutoParams | Refreshed {len(stats)} pairs for {bot_id} — "
            f"{adjusted} with sufficient data (≥{MIN_TRADES} trades in {LOOKBACK_DAYS}d)"
        )
    else:
        logger.info(f"AutoParams | No trade data found for {bot_id} in last {LOOKBACK_DAYS} days")
    return stats
