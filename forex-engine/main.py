"""
main.py — The Navigator: Forex Swing-Trading Engine Entry Point
================================================================
Runs the 4-hour trading cycle in a continuous loop.
"""

import os
import sys
import time

from loguru import logger

_ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

_REPO_ROOT = os.path.join(_ENGINE_DIR, "..")
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from forex_config import (
    BOT_DISPLAY_NAME, BOT_ID, BOT_STRATEGY_LABEL,
    PAPER_TRADING, PAPER_STARTING_BALANCE,
    CYCLE_INTERVAL_HOURS, PAIRS, PAIR_LABELS,
)
import forex_nav_db as _db
from forex_engine import run_cycle

CYCLE_INTERVAL_SECONDS = CYCLE_INTERVAL_HOURS * 3600
INITIAL_DELAY_SECONDS = 30

logger.info("=" * 65)
logger.info(f"  {BOT_DISPLAY_NAME.upper()}  —  FOREX SWING-TRADING ENGINE")
logger.info(f"  Bot ID: {BOT_ID} | Strategy: {BOT_STRATEGY_LABEL}")
if PAPER_TRADING:
    logger.info(f"  *** PAPER TRADING MODE — Simulated ${PAPER_STARTING_BALANCE:,.0f} ***")
else:
    logger.info("  *** LIVE TRADING MODE ***")
logger.info(f"  Pairs: {', '.join(PAIR_LABELS.get(p, p) for p in PAIRS)}")
logger.info(f"  Cycle: Every {CYCLE_INTERVAL_HOURS} hours")
logger.info("=" * 65)

_db.ensure_schema()
_db.ensure_vault_table()
logger.info("DB | Forex PostgreSQL tables ready")


def main():
    logger.info(f"Navigator | Starting in {INITIAL_DELAY_SECONDS}s...")
    time.sleep(INITIAL_DELAY_SECONDS)

    while True:
        try:
            logger.info("Navigator | Starting trading cycle...")
            result = run_cycle()
            status = result.get("status", "unknown")
            logger.info(f"Navigator | Cycle complete — status: {status}")
        except Exception as exc:
            logger.error(f"Navigator | Cycle crashed: {exc}")

        logger.info(f"Navigator | Sleeping {CYCLE_INTERVAL_HOURS}h until next cycle...")
        time.sleep(CYCLE_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
