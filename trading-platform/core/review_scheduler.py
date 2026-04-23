"""
review_scheduler.py — Scheduled performance review flags.

Writes review_flags DB rows that surface as dashboard notifications
when performance checks are due. Claude reads these flags in future
audit sessions to know what to check.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone, date, timedelta

logger = logging.getLogger("review_scheduler")


def _upsert_flag(
    flag_key: str,
    title: str,
    description: str,
    due_date: date,
    priority: str = "medium",
) -> None:
    """Insert or update a review flag. Never overwrites a resolved flag."""
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO review_flags
                        (flag_key, title, description, due_date, priority, status)
                    VALUES (%s, %s, %s, %s, %s, 'pending')
                    ON CONFLICT (flag_key) DO UPDATE SET
                        title       = EXCLUDED.title,
                        description = EXCLUDED.description,
                        due_date    = EXCLUDED.due_date,
                        priority    = EXCLUDED.priority
                    WHERE review_flags.status = 'pending'
                """, (flag_key, title, description, due_date, priority))
            conn.commit()
    except Exception as exc:
        logger.debug(f"ReviewScheduler | upsert_flag failed: {exc}")


def _resolve_flag_if_condition(flag_key: str, condition: bool, note: str = "") -> None:
    """Auto-resolve a flag if a condition is met."""
    if not condition:
        return
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE review_flags
                    SET status = 'auto_resolved',
                        resolved_at = NOW(),
                        resolved_note = %s
                    WHERE flag_key = %s AND status = 'pending'
                """, (note, flag_key))
            conn.commit()
    except Exception as exc:
        logger.debug(f"ReviewScheduler | resolve failed: {exc}")


def run_scheduled_checks() -> None:
    """
    Run all scheduled review checks. Called once daily at market close.
    Creates/updates flags based on current bot performance data.
    """
    today = date.today()
    logger.info("ReviewScheduler | Running scheduled checks...")

    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return

        with get_conn() as conn:
            with conn.cursor() as cur:

                # ── CHECK 1: Blackbeard Apr 30 review ────────────────────────
                cur.execute("""
                    SELECT
                        COUNT(*) as trades,
                        SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins
                    FROM kraken_trades
                    WHERE bot_id = 'blackbeard'
                    AND closed_at > NOW() - INTERVAL '30 days'
                """)
                row = cur.fetchone()
                bb_trades = row[0] or 0
                bb_wins = row[1] or 0
                bb_wr = (bb_wins / bb_trades * 100) if bb_trades > 0 else 0

                _upsert_flag(
                    flag_key="blackbeard_apr30_review",
                    title="Blackbeard 30-Day Performance Review",
                    description=(
                        f"Check Blackbeard win rate after Apr 17 catastrophe rolls out "
                        f"of the 30-day window. Current: {bb_wr:.1f}% on {bb_trades} trades. "
                        f"If still below 35%, hard pause like Calypso. "
                        f"Run: SELECT COUNT(*), SUM(CASE WHEN pnl_usd>0 THEN 1 ELSE 0 END) "
                        f"FROM kraken_trades WHERE bot_id='blackbeard' "
                        f"AND closed_at > NOW() - INTERVAL '30 days';"
                    ),
                    due_date=date(2026, 4, 30),
                    priority="high" if bb_wr < 35 else "medium",
                )
                _resolve_flag_if_condition(
                    "blackbeard_apr30_review",
                    condition=bb_wr >= 40 and bb_trades >= 30,
                    note=f"Auto-resolved: WR={bb_wr:.1f}% on {bb_trades} trades — above 40% threshold"
                )

                # ── CHECK 2: Oracle exit logic validation ────────────────────
                cur.execute("""
                    SELECT
                        COUNT(*) as trades,
                        ROUND(AVG(realized_pnl)::numeric, 2) as avg_pnl,
                        SUM(CASE WHEN status='Closed_Win' THEN 1 ELSE 0 END) as wins
                    FROM trades
                    WHERE status IN ('Closed_Win', 'Closed_Loss')
                    AND closed_at IS NOT NULL
                    AND time_in_trade_hours IS NOT NULL
                """)
                row = cur.fetchone()
                oracle_clean_trades = row[0] or 0
                oracle_avg_pnl = float(row[1]) if row[1] else 0
                oracle_wins = row[2] or 0
                oracle_wr = (oracle_wins / oracle_clean_trades * 100) if oracle_clean_trades > 0 else 0

                _upsert_flag(
                    flag_key="oracle_exit_validation_may07",
                    title="Oracle Exit Logic Validation (30 Clean Trades)",
                    description=(
                        f"Validate whether trail trigger 2.5xATR + profit-gated EMA/ADX exits "
                        f"improved Oracle expectancy. Need 30+ clean trades with closed_at timestamp. "
                        f"Current: {oracle_clean_trades} clean trades, WR={oracle_wr:.1f}%, "
                        f"avg P&L=${oracle_avg_pnl:.2f}. "
                        f"Target: avg_pnl > $0 sustained over 30 trades. "
                        f"Report these numbers back to Claude."
                    ),
                    due_date=date(2026, 5, 7),
                    priority="high" if oracle_clean_trades < 30 else "medium",
                )
                _resolve_flag_if_condition(
                    "oracle_exit_validation_may07",
                    condition=oracle_clean_trades >= 30 and oracle_avg_pnl > 0,
                    note=f"Auto-resolved: {oracle_clean_trades} trades, avg=${oracle_avg_pnl:.2f} positive"
                )

                # ── CHECK 3: Calypso 2-week performance review ───────────────
                cur.execute("""
                    SELECT
                        COUNT(*) as trades,
                        SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
                        ROUND(SUM(pnl_usd)::numeric, 2) as total_pnl
                    FROM kraken_trades
                    WHERE bot_id = 'calypso'
                    AND closed_at > NOW() - INTERVAL '14 days'
                """)
                row = cur.fetchone()
                cal_trades = row[0] or 0
                cal_wins = row[1] or 0
                cal_pnl = float(row[2]) if row[2] else 0
                cal_wr = (cal_wins / cal_trades * 100) if cal_trades > 0 else 0

                _upsert_flag(
                    flag_key="calypso_may06_review",
                    title="Calypso 2-Week Post-Fix Review",
                    description=(
                        f"Compare Calypso performance against pre-fix baseline: "
                        f"20.6% WR, -$89/trade, -$3,030 total. "
                        f"Current (14d): {cal_trades} trades, WR={cal_wr:.1f}%, "
                        f"total P&L=${cal_pnl:.2f}. "
                        f"5 fixes applied: dead zone eliminated, volume 1.5x, "
                        f"EMA 50/200, spread gate, VPIN 0.75. "
                        f"Report these numbers back to Claude."
                    ),
                    due_date=date(2026, 5, 6),
                    priority="high",
                )
                _resolve_flag_if_condition(
                    "calypso_may06_review",
                    condition=cal_wr >= 40 and cal_trades >= 20,
                    note=f"Auto-resolved: WR={cal_wr:.1f}% on {cal_trades} trades — above 40%"
                )

                # ── CHECK 4: Navigator 30-trade validation ───────────────────
                cur.execute("""
                    SELECT COUNT(*) as trades,
                           SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins
                    FROM forex_trades
                    WHERE status = 'closed'
                    AND exit_time > (
                        SELECT MIN(exit_time) FROM forex_trades
                        WHERE status = 'closed' AND exit_time > '2026-04-22'
                    )
                """)
                row = cur.fetchone()
                nav_trades = row[0] or 0
                nav_wins = row[1] or 0
                nav_wr = (nav_wins / nav_trades * 100) if nav_trades > 0 else 0

                _upsert_flag(
                    flag_key="navigator_may15_review",
                    title="Navigator Post-Fix 30-Trade Validation",
                    description=(
                        f"Navigator had 9.1% WR before fixes. 4 entry fixes applied Apr 22: "
                        f"RSI 30/70, EMA 50/200 trend filter, ATR minimum 8 pips, "
                        f"per-pair cooldown after 3 losses. "
                        f"Post-fix trades so far: {nav_trades}, WR={nav_wr:.1f}%. "
                        f"Need 30 trades to validate. "
                        f"Report win rate and avg P&L in pips back to Claude."
                    ),
                    due_date=date(2026, 5, 15),
                    priority="medium",
                )
                _resolve_flag_if_condition(
                    "navigator_may15_review",
                    condition=nav_trades >= 30 and nav_wr >= 40,
                    note=f"Auto-resolved: {nav_trades} post-fix trades, WR={nav_wr:.1f}%"
                )

                # ── CHECK 5: Fee drag live readiness ─────────────────────────
                cur.execute("""
                    SELECT bot_id,
                        SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END)::float
                        / NULLIF(COUNT(*), 0) as wr
                    FROM kraken_trades
                    WHERE closed_at > NOW() - INTERVAL '30 days'
                    GROUP BY bot_id
                """)
                rows = cur.fetchall()
                bots_above_40 = sum(1 for r in rows if (r[1] or 0) >= 0.40)
                total_bots = len(rows)

                _upsert_flag(
                    flag_key="live_capital_readiness_jun01",
                    title="Live Capital Readiness Assessment",
                    description=(
                        f"Fee drag model shows Kraken bots need 40%+ WR to break even "
                        f"on 0.52% round-trip fees. Currently {bots_above_40}/{total_bots} "
                        f"Kraken bots are above 40% WR over 30 days. "
                        f"Do not deploy live capital until at least 3/4 core Kraken bots "
                        f"sustain 40%+ WR over 60 trades. "
                        f"Run full fee drag model before any live deployment decision."
                    ),
                    due_date=date(2026, 6, 1),
                    priority="high" if bots_above_40 < 3 else "medium",
                )

    except Exception as exc:
        logger.error(f"ReviewScheduler | Checks failed: {exc}")

    logger.info("ReviewScheduler | Checks complete")
