"""
Kill Switch — Daily Drawdown Protection
-----------------------------------------
Monitors portfolio equity vs the opening balance at market open.
If the daily drawdown exceeds the configured threshold (default 5%),
all positions are immediately liquidated and further trading is blocked
until manually reset.

State:
    - opening_equity: captured once per trading day at first run
    - tripped:        set to True when drawdown threshold is breached

This module is designed to be called at the start of every execution
cycle by the scheduler (Phase 5).
"""

from loguru import logger

from config.settings import settings
from execution.broker import close_all_positions, get_account

_state: dict = {
    "opening_equity":      None,
    "tripped":             False,
    "drawdown_pct":        0.0,
    "pending_liquidation": False,   # set when emergency close couldn't execute (market closed)
}


def _load_state_from_db() -> None:
    """Load persisted kill switch state from DB on startup."""
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS kill_switch_state (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        tripped BOOLEAN NOT NULL DEFAULT FALSE,
                        opening_equity DOUBLE PRECISION,
                        drawdown_pct DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                        pending_liquidation BOOLEAN NOT NULL DEFAULT FALSE,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    ALTER TABLE kill_switch_state
                    ADD COLUMN IF NOT EXISTS pending_liquidation BOOLEAN NOT NULL DEFAULT FALSE
                """)
                cur.execute("SELECT tripped, opening_equity, drawdown_pct, pending_liquidation FROM kill_switch_state WHERE id = 1")
                row = cur.fetchone()
                if row:
                    _state["tripped"] = bool(row[0])
                    _state["opening_equity"] = float(row[1]) if row[1] else None
                    _state["drawdown_pct"] = float(row[2]) if row[2] else 0.0
                    _state["pending_liquidation"] = bool(row[3]) if row[3] is not None else False
            conn.commit()
    except Exception as exc:
        logger.warning(f"Kill switch | Failed to load state from DB (non-fatal): {exc}")


def _persist_state_to_db() -> None:
    """Write current kill switch state to DB."""
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO kill_switch_state (id, tripped, opening_equity, drawdown_pct, pending_liquidation)
                    VALUES (1, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        tripped = EXCLUDED.tripped,
                        opening_equity = EXCLUDED.opening_equity,
                        drawdown_pct = EXCLUDED.drawdown_pct,
                        pending_liquidation = EXCLUDED.pending_liquidation,
                        updated_at = NOW()
                """, (_state["tripped"], _state["opening_equity"], _state["drawdown_pct"], _state["pending_liquidation"]))
            conn.commit()
    except Exception as exc:
        logger.debug(f"Kill switch | State persist failed (non-fatal): {exc}")


# Load persisted state on module import
_load_state_from_db()


def reset(opening_equity: float | None = None) -> None:
    """
    Reset the kill switch state for a new trading day.
    Call this at market open each morning before the first cycle.

    Args:
        opening_equity: Override the opening balance (e.g. from DB).
                        If None, it will be fetched from Alpaca on first check.
    """
    _state["tripped"] = False
    _state["drawdown_pct"] = 0.0

    # Validate opening equity before accepting it as the daily baseline.
    # A bad API response (None, 0, or implausible value) would corrupt
    # the kill switch for the entire trading day.
    _MIN_VALID_OPENING_EQUITY = 10_000  # floor below which API data is considered corrupt
    if opening_equity is not None:
        if opening_equity < _MIN_VALID_OPENING_EQUITY:
            logger.error(
                f"Kill switch | Rejected opening_equity=${opening_equity:,.2f} — "
                f"below $10k minimum. Kill switch baseline NOT updated. "
                f"Previous baseline retained: ${_state['opening_equity']}"
            )
        else:
            # Sanity check: new opening equity must be within 40% of previous baseline.
            # This catches stale API responses, reconnection artifacts, or extreme overnight moves.
            prev = _state.get("opening_equity")
            if prev and prev > 0:
                deviation = abs(opening_equity - prev) / prev
                if deviation > 0.40:
                    logger.error(
                        f"Kill switch | Rejected opening_equity=${opening_equity:,.2f} — "
                        f"deviates {deviation:.0%} from previous baseline ${prev:,.2f} (max 40%). "
                        f"Previous baseline retained."
                    )
                else:
                    _state["opening_equity"] = opening_equity
            else:
                _state["opening_equity"] = opening_equity

    logger.info(f"Kill switch reset | opening_equity={_state['opening_equity']}")
    _persist_state_to_db()


def is_tripped() -> bool:
    """Return True if the kill switch has been triggered today."""
    return _state["tripped"]


def check(current_equity: float | None = None) -> bool:
    """
    Check whether the daily drawdown exceeds the threshold.
    If so, liquidate all positions and trip the kill switch.

    Args:
        current_equity: Current portfolio equity. Fetched from Alpaca if None.

    Returns:
        True if kill switch was triggered, False if safe.
    """
    if _state["tripped"]:
        logger.warning("Kill switch already tripped — skipping check")
        return True

    try:
        if current_equity is None:
            acct = get_account()
            current_equity = acct["equity"]

        if _state["opening_equity"] is None:
            _state["opening_equity"] = current_equity
            logger.info(f"Kill switch | Baseline set: opening_equity=${current_equity:,.2f}")
            return False

        opening = _state["opening_equity"]
        drawdown = (opening - current_equity) / opening
        _state["drawdown_pct"] = drawdown
        threshold = settings.kill_switch_drawdown_pct

        logger.info(
            f"Kill switch | equity=${current_equity:,.2f} | "
            f"opening=${opening:,.2f} | drawdown={drawdown:.2%} | "
            f"threshold={threshold:.2%}"
        )

        if drawdown >= threshold:
            logger.critical(
                f"KILL SWITCH TRIGGERED | drawdown={drawdown:.2%} >= threshold={threshold:.2%} | "
                f"Liquidating all positions immediately!"
            )
            _state["tripped"] = True
            _persist_state_to_db()
            n = close_all_positions()
            logger.critical(f"Kill switch | {n} positions liquidated. Trading halted for the day.")
            return True

        return False

    except Exception as exc:
        logger.error(f"Kill switch check failed: {exc} — trading will continue")
        return False


def manual_trip(reason: str = "manual_emergency") -> None:
    """
    Manually trip the kill switch without a drawdown check.
    Used by the emergency liquidate endpoint to halt all new trading.
    Does NOT automatically liquidate positions — the caller is responsible.
    """
    logger.critical(
        f"Kill switch MANUALLY TRIPPED | reason={reason} | Trading halted immediately."
    )
    _state["tripped"] = True
    _persist_state_to_db()


def set_pending_liquidation(value: bool = True) -> None:
    """
    Mark that an emergency liquidation is pending (orders failed because market was
    closed). The pipeline checks this at each run and force-closes all non-vault
    positions as the very first action when the market is open.
    """
    _state["pending_liquidation"] = value
    logger.critical(
        f"Kill switch | pending_liquidation={'SET' if value else 'CLEARED'}"
    )
    _persist_state_to_db()


def is_pending_liquidation() -> bool:
    """Return True if a deferred emergency close is waiting to execute."""
    return bool(_state["pending_liquidation"])


def get_state() -> dict:
    """Return current kill switch state for logging/API exposure."""
    return {
        "tripped":              _state["tripped"],
        "drawdown_pct":         round(_state["drawdown_pct"] * 100, 3),
        "opening_equity":       _state["opening_equity"],
        "threshold_pct":        settings.kill_switch_drawdown_pct * 100,
        "pending_liquidation":  _state["pending_liquidation"],
    }
