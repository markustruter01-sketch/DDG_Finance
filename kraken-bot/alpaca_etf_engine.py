"""
alpaca_etf_engine.py — Shared execution engine for Alpaca ETF momentum bots.

Used by:
  Bot #2 (bot2_spy_qqq.py)    — SPY/QQQ long-only trend follower
  Bot #4 (bot4_sector.py)     — SPDR sector momentum rotation
  Bot #5 (bot5_defensive.py)  — Defensive risk-off allocation

Each bot supplies its own universe + entry rules via the ETF_ENGINE_CONFIG dict.
This module owns: Alpaca execution, position tracking (alpaca_etf_positions table),
ATR stops, trailing stop updates, tiered profit-taking, and heartbeat writes.

ACTIVATION NOTE (important — do this at each staggered launch):
When activating a new bot, run this SQL BEFORE resuming it (bots_state.paused = false):
  UPDATE kraken_heartbeat
  SET bot_id = '<new_bot_id>', bot_display_name = '<new_display_name>'
  WHERE id = <db_id>;
This prevents the dashboard showing the old paused bot name while the new bot trades.
Week 2: bot2_spy_qqq (db_id=1) | Week 3: bot4_sector (db_id=3)
Week 4: bot7_macro_bond (db_id=7) | Week 5: bot5_defensive (db_id=4)
"""
from __future__ import annotations

import logging
import math
import os
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from jerome_alpaca import _nyse_is_open

logger = logging.getLogger("etf_engine")

_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0"}

# ── Path helper ───────────────────────────────────────────────────────────────

def _tp_path() -> str:
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trading-platform")
    )

def _ensure_tp() -> None:
    tp = _tp_path()
    if tp not in sys.path:
        sys.path.insert(0, tp)


_ensure_tp()
from core.order_ids import submit_with_unique_client_order_id
from core.symbols import canonical_symbol, same_symbol
from core.cash_park import is_cash_park


# ── Yahoo Finance OHLCV fetcher ───────────────────────────────────────────────

def _yahoo_daily_ohlcv(ticker: str, days: int = 250) -> Optional[dict]:
    """
    Fetch daily OHLCV from Yahoo Finance v8 API.
    Returns {'opens', 'highs', 'lows', 'closes', 'volumes'} or None.
    Uses direct HTTP — no yfinance library (unreliable in this environment).
    """
    import requests
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"range": f"{days}d", "interval": "1d"}
    try:
        resp = requests.get(url, params=params, headers=_YAHOO_HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        result = data.get("chart", {}).get("result")
        if not result:
            return None
        quotes = result[0].get("indicators", {}).get("quote", [{}])[0]
        # Strip None entries by zipping all arrays together and filtering
        opens  = quotes.get("open",   [])
        highs  = quotes.get("high",   [])
        lows   = quotes.get("low",    [])
        closes = quotes.get("close",  [])
        vols   = quotes.get("volume", [])
        zipped = [
            (o, h, l, c, v)
            for o, h, l, c, v in zip(opens, highs, lows, closes, vols)
            if None not in (o, h, l, c)
        ]
        if not zipped:
            return None
        o, h, l, c, v = zip(*zipped)
        return {
            "opens":   list(o),
            "highs":   list(h),
            "lows":    list(l),
            "closes":  list(c),
            "volumes": list(v),
        }
    except Exception as exc:
        logger.debug(f"EtfEngine | Yahoo OHLCV fetch failed for {ticker}: {exc}")
        return None


# ── Technical indicators ──────────────────────────────────────────────────────

def calculate_ema(prices: list[float], period: int) -> Optional[float]:
    """
    Standard EMA (exponential weighted moving average).
    Returns most recent EMA value or None if insufficient data.
    """
    if len(prices) < period:
        return None
    k = 2.0 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = price * k + ema * (1 - k)
    return ema


def calculate_atr(highs: list[float], lows: list[float], closes: list[float],
                  period: int = 14) -> Optional[float]:
    """
    Wilder's ATR — same implementation as the rest of the fleet.
    Returns most recent ATR or None if insufficient data.
    """
    if len(closes) < period + 1 or len(highs) < period + 1 or len(lows) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        high, low, prev_close = highs[i], lows[i], closes[i - 1]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if len(trs) < period:
        return None
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def check_trend_direction(
    symbol: str,
    ema_fast: int = 50,
    ema_slow: int = 200,
) -> str:
    """
    Fetch daily closes and compare EMA_fast vs EMA_slow.
    Returns 'up' (fast > slow), 'down' (fast < slow), or 'flat' (within 0.1%).
    Returns 'unknown' if data unavailable.
    """
    ohlcv = _yahoo_daily_ohlcv(symbol, days=max(ema_slow + 10, 250))
    if not ohlcv:
        return "unknown"
    closes = ohlcv["closes"]
    fast = calculate_ema(closes, ema_fast)
    slow = calculate_ema(closes, ema_slow)
    if fast is None or slow is None:
        return "unknown"
    if slow == 0:
        return "unknown"
    diff_pct = (fast - slow) / slow * 100
    if diff_pct > 0.1:
        return "up"
    if diff_pct < -0.1:
        return "down"
    return "flat"


# ── Alpaca wrapper ────────────────────────────────────────────────────────────

class AlpacaEtfEngine:
    """
    Handles all Alpaca interactions for ETF momentum bots.
    Wraps execution, position management, DB writes, and heartbeat.

    All three ETF bots (#2, #4, #5) share this engine.
    Bot identity is passed per-call via bot_id + db_id parameters.
    """

    def __init__(self, api_key: str, secret_key: str,
                 base_url: str = "https://paper-api.alpaca.markets"):
        import alpaca_trade_api as tradeapi
        self.api = tradeapi.REST(api_key, secret_key, base_url=base_url)
        logger.info("AlpacaEtfEngine | Connected to Alpaca paper account")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create alpaca_etf_positions if it doesn't exist. Idempotent — safe to call on every startup."""
        _ensure_tp()
        try:
            from db.postgres import get_conn, is_pg_available
            if not is_pg_available():
                return
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS alpaca_etf_positions (
                            id              BIGSERIAL     PRIMARY KEY,
                            bot_id          TEXT          NOT NULL,
                            symbol          TEXT          NOT NULL,
                            direction       TEXT          NOT NULL DEFAULT 'long',
                            qty             NUMERIC       NOT NULL,
                            current_qty     NUMERIC,
                            entry_price     NUMERIC       NOT NULL,
                            entry_atr       NUMERIC,
                            notional_usd    NUMERIC       NOT NULL,
                            stop_price      NUMERIC,
                            tp1_price       NUMERIC,
                            tp2_price       NUMERIC,
                            stop_order_id   TEXT,
                            scaled_out_tp1  BOOLEAN       DEFAULT FALSE,
                            scaled_out_tp2  BOOLEAN       DEFAULT FALSE,
                            min_hold_until  TIMESTAMPTZ,
                            status          TEXT          NOT NULL DEFAULT 'open',
                            opened_at       TIMESTAMPTZ   DEFAULT NOW(),
                            closed_at       TIMESTAMPTZ,
                            exit_reason     TEXT,
                            realised_pnl    NUMERIC
                        );
                        CREATE INDEX IF NOT EXISTS idx_etf_pos_status
                            ON alpaca_etf_positions (bot_id, status, opened_at);
                        ALTER TABLE alpaca_etf_positions
                            ADD COLUMN IF NOT EXISTS stop_order_id TEXT;
                        ALTER TABLE alpaca_etf_positions
                            ADD COLUMN IF NOT EXISTS current_qty NUMERIC;
                        CREATE TABLE IF NOT EXISTS regional_scan_log (
                            id              BIGSERIAL PRIMARY KEY,
                            ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            bot_id          TEXT NOT NULL,
                            symbol          TEXT NOT NULL,
                            regime          TEXT,
                            should_enter    BOOLEAN,
                            shares          NUMERIC,
                            notional        NUMERIC,
                            notional_pct    NUMERIC,
                            corr_result     TEXT,
                            final_decision  TEXT NOT NULL,
                            drop_reason     TEXT,
                            order_id        TEXT,
                            order_outcome   TEXT
                        );
                        CREATE INDEX IF NOT EXISTS idx_regional_scan_log_lookup
                            ON regional_scan_log (bot_id, ts DESC, symbol);
                    """)
                conn.commit()
            logger.info("EtfEngine | alpaca_etf_positions schema verified")
        except Exception as exc:
            logger.error(f"EtfEngine | _ensure_schema failed: {exc}")

        # Bug-1 backfill (idempotent): rows opened before TP logic was added have
        # NULL tp1_price/tp2_price. Compute from entry_price + constants.
        # WHERE guard ensures this runs once per affected row and is a no-op thereafter.
        try:
            from db.postgres import get_conn, is_pg_available
            if not is_pg_available():
                return
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE alpaca_etf_positions
                        SET tp1_price = ROUND((entry_price * 1.06)::numeric, 2),
                            tp2_price = ROUND((entry_price * 1.12)::numeric, 2)
                        WHERE (tp1_price IS NULL OR tp2_price IS NULL)
                          AND status = 'open'
                    """)
                    rows = cur.rowcount
                conn.commit()
            if rows:
                logger.info(f"EtfEngine | TP backfill: updated {rows} row(s) with missing tp1/tp2 prices")
        except Exception as exc:
            logger.warning(f"EtfEngine | TP backfill failed (non-fatal): {exc}")

        self._backfill_current_qty()

    def _backfill_current_qty(self) -> None:
        """Repair safe current_qty mismatches from closed and scaled-out state."""
        _ensure_tp()
        closed_updated = 0
        open_updated = 0
        open_unresolved = 0
        scaled_out_updated = 0
        scaled_out_unresolved = 0

        try:
            from db.postgres import get_conn, is_pg_available
            if not is_pg_available():
                return

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, bot_id, symbol, status
                        FROM alpaca_etf_positions
                        WHERE current_qty IS NULL
                          AND status IN ('open', 'closed')
                        ORDER BY id
                        """
                    )
                    pending_rows = cur.fetchall()
                    open_rows = [
                        row for row in pending_rows
                        if row[3] == "open"
                    ]

                    cur.execute(
                        """
                        SELECT id, bot_id, symbol, qty, current_qty
                        FROM alpaca_etf_positions
                        WHERE status = 'open'
                          AND (scaled_out_tp1 IS TRUE OR scaled_out_tp2 IS TRUE)
                          AND current_qty = qty
                        ORDER BY id
                        """
                    )
                    scaled_out_rows = cur.fetchall()

                    cur.execute(
                        """
                        UPDATE alpaca_etf_positions
                        SET current_qty = 0
                        WHERE status = 'closed'
                          AND current_qty IS DISTINCT FROM 0
                        """
                    )
                    closed_updated = cur.rowcount

                    if open_rows or scaled_out_rows:
                        try:
                            # self.api is the Alpaca REST client created at startup;
                            # list_positions() performs a broker GET only.
                            broker_positions = self.api.list_positions()
                            broker_by_symbol = {
                                canonical_symbol(position.symbol): str(position.qty)
                                for position in broker_positions
                                if canonical_symbol(getattr(position, "symbol", ""))
                            }
                        except Exception as exc:
                            open_unresolved = len(open_rows)
                            scaled_out_unresolved = len(scaled_out_rows)
                            logger.error(
                                f"EtfEngine | current_qty broker read failed; "
                                f"left {open_unresolved} NULL row(s) and "
                                f"{scaled_out_unresolved} scaled-out row(s) unchanged: {exc!r}"
                            )
                            self._record_current_qty_degradation(
                                error_type="etf_current_qty_broker_read_failed",
                                message=(
                                    "ETF current_qty backfill broker read failed; "
                                    f"left {open_unresolved} NULL row(s) and "
                                    f"{scaled_out_unresolved} scaled-out row(s) unchanged"
                                ),
                                detail=repr(exc),
                            )
                        else:
                            for row_id, bot_id, symbol, _status in open_rows:
                                broker_qty = broker_by_symbol.get(
                                    canonical_symbol(symbol)
                                )
                                if broker_qty is None:
                                    open_unresolved += 1
                                    logger.error(
                                        f"EtfEngine | current_qty broker position "
                                        f"missing for {bot_id}/{symbol}; row {row_id} "
                                        "left NULL"
                                    )
                                    self._record_current_qty_degradation(
                                        error_type="etf_current_qty_broker_position_missing",
                                        message=(
                                            "ETF current_qty backfill broker position "
                                            f"missing for {bot_id}/{symbol}; row {row_id} "
                                            "left NULL"
                                        ),
                                        detail=f"row_id={row_id}; symbol={symbol}",
                                        bot_id=bot_id,
                                    )
                                    continue

                                cur.execute(
                                    """
                                    UPDATE alpaca_etf_positions
                                    SET current_qty = %s
                                    WHERE id = %s
                                      AND current_qty IS NULL
                                    """,
                                    (broker_qty, row_id),
                                )
                                open_updated += cur.rowcount

                            for row_id, bot_id, symbol, entry_qty, _current_qty in scaled_out_rows:
                                broker_qty = broker_by_symbol.get(
                                    canonical_symbol(symbol)
                                )
                                if broker_qty is None:
                                    scaled_out_unresolved += 1
                                    logger.error(
                                        f"EtfEngine | current_qty scaled-out repair "
                                        f"broker position missing for {bot_id}/{symbol}; "
                                        f"row {row_id} left unchanged"
                                    )
                                    self._record_current_qty_degradation(
                                        error_type="etf_current_qty_broker_position_missing",
                                        message=(
                                            "ETF current_qty scaled-out repair broker "
                                            f"position missing for {bot_id}/{symbol}; "
                                            f"row {row_id} left unchanged"
                                        ),
                                        detail=f"row_id={row_id}; symbol={symbol}",
                                        bot_id=bot_id,
                                    )
                                    continue

                                cur.execute(
                                    """
                                    UPDATE alpaca_etf_positions
                                    SET current_qty = %s
                                    WHERE id = %s
                                      AND status = 'open'
                                      AND current_qty = qty
                                      AND qty = %s
                                    """,
                                    (broker_qty, row_id, entry_qty),
                                )
                                scaled_out_updated += cur.rowcount

                conn.commit()

            logger.info(
                "EtfEngine | current_qty backfill: "
                f"closed updated={closed_updated}, "
                f"open updated={open_updated}, "
                f"scaled-out updated={scaled_out_updated}, "
                f"open unresolved={open_unresolved}, "
                f"scaled-out unresolved={scaled_out_unresolved}"
            )
        except Exception as exc:
            logger.error(f"EtfEngine | current_qty backfill failed (non-fatal): {exc!r}")

    def _sync_current_qty_after_sale(self, bot_id: str, symbol: str) -> bool:
        """Persist the broker residual after a confirmed partial/full sale."""
        try:
            broker_positions = self.api.list_positions()
            broker_by_symbol = {
                canonical_symbol(getattr(position, "symbol", "")): str(position.qty)
                for position in broker_positions
                if canonical_symbol(getattr(position, "symbol", ""))
            }
            broker_qty = broker_by_symbol.get(canonical_symbol(symbol), "0")

            from db.postgres import get_conn, is_pg_available
            if not is_pg_available():
                raise RuntimeError("database unavailable for current_qty sale sync")

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, symbol
                        FROM alpaca_etf_positions
                        WHERE bot_id = %s AND status = 'open'
                        ORDER BY id
                        """,
                        (bot_id,),
                    )
                    matching_ids = [
                        row_id
                        for row_id, db_symbol in cur.fetchall()
                        if canonical_symbol(db_symbol) == canonical_symbol(symbol)
                    ]
                    for row_id in matching_ids:
                        cur.execute(
                            """
                            UPDATE alpaca_etf_positions
                            SET current_qty = %s
                            WHERE id = %s
                              AND bot_id = %s
                              AND status = 'open'
                            """,
                            (broker_qty, row_id, bot_id),
                        )
                conn.commit()
            logger.info(
                f"EtfEngine | current_qty sale sync: "
                f"{bot_id}/{symbol}={broker_qty}"
            )
            return True
        except Exception as exc:
            logger.error(
                f"EtfEngine | current_qty sale sync failed for "
                f"{bot_id}/{symbol}: {exc!r}"
            )
            self._record_current_qty_degradation(
                error_type="etf_current_qty_sync_failed",
                message=(
                    f"ETF current_qty sale sync failed for {bot_id}/{symbol}; "
                    "left current_qty unchanged"
                ),
                detail=repr(exc),
                bot_id=bot_id,
            )
            return False

    @staticmethod
    def _record_current_qty_degradation(
        *,
        error_type: str,
        message: str,
        detail: str,
        bot_id: Optional[str] = None,
    ) -> None:
        try:
            from core.degradation_tracker import record_degradation

            record_degradation(
                component="alpaca",
                severity="error",
                error_type=error_type,
                message=message,
                detail=detail,
                bot_id=bot_id,
            )
        except Exception as exc:
            logger.error(
                f"EtfEngine | failed to record current_qty degradation: {exc!r}"
            )

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account(self) -> dict:
        acc = self.api.get_account()
        account = {
            "equity":       float(acc.equity),
            "cash":         float(acc.cash),
            "buying_power": float(acc.buying_power),
        }
        if getattr(acc, "long_market_value", None) is not None:
            account["long_market_value"] = float(acc.long_market_value)
        return account

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_positions(self) -> list[dict]:
        """Live Alpaca positions."""
        positions = self.api.list_positions()
        result = []
        for p in positions:
            entry   = float(p.avg_entry_price)
            current = float(p.current_price)
            side    = p.side
            unrealised_pct = (
                (current - entry) / entry * 100
                if side == "long"
                else (entry - current) / entry * 100
            )
            result.append({
                "symbol":             p.symbol,
                "direction":          side,
                "qty":                float(p.qty),
                "entry_price":        entry,
                "current_price":      current,
                "unrealised_pnl_usd": float(p.unrealized_pl),
                "unrealised_pct":     round(unrealised_pct, 3),
                "market_value":       float(p.market_value),
            })
        return result

    def get_strategy_positions(self, bot_id: str) -> list[dict]:
        """Live positions for this engine; vault symbols cannot collide with strategy symbols."""
        return self.get_positions()

    # ── Orders ────────────────────────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        side: str,
        notional: float,
    ) -> Optional[dict]:
        """Place a fractional notional market order. side must be 'buy' or 'sell'.
        Always uses time_in_force="day" — Alpaca rejects fractional (notional)
        orders with tif="opg". A pre-market DAY order queues for the 09:30 open,
        achieving the same effect without the rejection.
        """
        tif = "day"
        logger.info(f"EtfEngine | Submitting {side.upper()} {symbol} notional=${notional:,.2f} tif={tif}")
        try:
            order, _ = submit_with_unique_client_order_id(
                lambda client_order_id: self.api.submit_order(
                    symbol=symbol,
                    notional=round(notional, 2),
                    side=side,
                    type="market",
                    time_in_force=tif,
                    client_order_id=client_order_id,
                ),
                f"etf-{side}-{symbol}",
            )
            logger.info(
                f"EtfEngine | ORDER PLACED: {side.upper()} {symbol} "
                f"notional=${notional:,.2f} order_id={order.id}"
            )
            return {"order_id": order.id, "symbol": symbol,
                    "side": side, "notional": notional}
        except Exception as exc:
            logger.error(f"EtfEngine | Order failed {side} {symbol}: {exc}")
            return None

    def buy_market(self, symbol: str, shares: float) -> Optional[dict]:
        """Place a whole-share market buy order.
        Always uses time_in_force="day" — Alpaca rejects fractional qty orders
        with tif="opg". A pre-market DAY order queues for the 09:30 open.
        """
        tif = "day"
        qty = math.floor(abs(float(shares)))
        logger.info(f"EtfEngine | Submitting BUY {symbol} qty={qty} tif={tif}")
        try:
            order, _ = submit_with_unique_client_order_id(
                lambda client_order_id: self.api.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side="buy",
                    type="market",
                    time_in_force=tif,
                    client_order_id=client_order_id,
                ),
                f"etf-buy-{symbol}",
            )
            logger.info(
                f"EtfEngine | ORDER PLACED: BUY {symbol} "
                f"qty={qty} order_id={order.id}"
            )
            return {"order_id": order.id, "symbol": symbol,
                    "side": "buy", "qty": qty}
        except Exception as exc:
            logger.error(f"EtfEngine | buy_market failed {symbol}: {exc}")
            return None

    def poll_entry_order(
        self,
        order_id: str,
        *,
        max_polls: int = 20,
        interval_seconds: float = 3.0,
    ) -> dict:
        """Poll a new entry order, returning the broker's final observed fill state."""
        terminal = {"filled", "canceled", "expired", "rejected", "done_for_day"}
        latest = None
        for poll_number in range(max_polls):
            try:
                latest = self.api.get_order(order_id)
            except Exception as exc:
                logger.warning(
                    f"EtfEngine | entry status poll failed order_id={order_id} "
                    f"poll={poll_number + 1}/{max_polls}: {exc}"
                )
                latest = None
            if latest is not None:
                status = str(getattr(latest, "status", "")).lower()
                if status == "filled" or status in terminal - {"filled"}:
                    break
            if poll_number < max_polls - 1:
                time.sleep(interval_seconds)

        if latest is None:
            try:
                latest = self.api.get_order(order_id)
            except Exception as exc:
                logger.error(f"EtfEngine | final entry status fetch failed {order_id}: {exc}")
                return {
                    "order_id": order_id,
                    "status": "unknown",
                    "filled_qty": 0.0,
                    "filled_avg_price": None,
                }

        status = str(getattr(latest, "status", "")).lower()
        filled_qty = float(getattr(latest, "filled_qty", 0) or 0)
        filled_avg_price = getattr(latest, "filled_avg_price", None)
        return {
            "order_id": order_id,
            "status": status,
            "filled_qty": filled_qty,
            "filled_avg_price": (
                float(filled_avg_price) if filled_avg_price is not None else None
            ),
            "raw_order": latest,
        }

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an entry order, returning whether the broker request succeeded."""
        try:
            self.api.cancel_order(order_id)
            return True
        except Exception as exc:
            logger.error(f"EtfEngine | cancel order failed {order_id}: {exc}")
            return False

    def record_scan_decision(
        self,
        *,
        bot_id: str,
        symbol: str,
        regime: Optional[str],
        should_enter: bool,
        shares: float,
        notional: Optional[float],
        notional_pct: Optional[float],
        corr_result: Optional[str],
        final_decision: str,
        drop_reason: Optional[str],
    ) -> Optional[int]:
        """Persist one auditable regional scan decision."""
        _ensure_tp()
        try:
            from db.postgres import get_conn, is_pg_available
            if not is_pg_available():
                return None
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO regional_scan_log
                            (bot_id, symbol, regime, should_enter, shares,
                             notional, notional_pct, corr_result,
                             final_decision, drop_reason)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        RETURNING id
                        """,
                        (
                            bot_id, symbol, regime, should_enter, shares,
                            notional, notional_pct, corr_result,
                            final_decision, drop_reason,
                        ),
                    )
                    row = cur.fetchone()
                conn.commit()
            return int(row[0]) if row else None
        except Exception as exc:
            logger.error(f"EtfEngine | scan log insert failed for {bot_id}/{symbol}: {exc}")
            return None

    def record_scan_outcome(
        self,
        scan_id: Optional[int],
        *,
        order_id: Optional[str],
        order_outcome: str,
    ) -> None:
        """Attach the final broker outcome to a candidate scan record."""
        if scan_id is None:
            return
        _ensure_tp()
        try:
            from db.postgres import get_conn, is_pg_available
            if not is_pg_available():
                return
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE regional_scan_log
                           SET order_id=%s, order_outcome=%s
                         WHERE id=%s
                        """,
                        (order_id, order_outcome, scan_id),
                    )
                conn.commit()
        except Exception as exc:
            logger.error(f"EtfEngine | scan outcome update failed id={scan_id}: {exc}")

    def close_position(
        self,
        symbol: str,
        *,
        bot_id: Optional[str] = None,
        stop_order_id: Optional[str] = None,
        stop_price: Optional[float] = None,
    ) -> bool:
        """Close entire position in a symbol."""
        self._last_close_deferred_market_closed = False
        try:
            live = next((p for p in self.get_positions() if same_symbol(p["symbol"], symbol)), None)
            if not live or abs(float(live["qty"])) < 1e-6:
                logger.info(f"EtfEngine | {symbol}: position is already flat/dust")
                return True
        except Exception as exc:
            raw_error = repr(exc)
            logger.error(f"EtfEngine | Close failed {symbol}: {raw_error}")
            self._persist_close_failure(bot_id, symbol, raw_error)
            return False
        if bot_id and not self.is_market_open():
            self._last_close_deferred_market_closed = True
            logger.info(f"EtfEngine | Full close deferred — market closed; {symbol} stop stays active")
            return False
        if bot_id and self._has_pending_owned_exit(bot_id, symbol):
            logger.warning(f"EtfEngine | Full close already pending for {symbol}; awaiting broker")
            return False
        if bot_id and not self._cancel_owned_stop(bot_id, symbol, stop_order_id):
            logger.error(f"EtfEngine | Full close blocked — {symbol} stop still active")
            return False
        try:
            order, _ = submit_with_unique_client_order_id(
                lambda client_order_id: self.api.submit_order(
                    symbol=symbol,
                    qty=round(abs(float(live["qty"])), 8),
                    side="sell",
                    type="market",
                    time_in_force="day",
                    client_order_id=client_order_id,
                ),
                self._exit_client_order_prefix(bot_id, symbol) if bot_id else f"etf-exit-{symbol}",
            )
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                live = next((p for p in self.get_positions() if same_symbol(p["symbol"], symbol)), None)
                if not live or abs(float(live["qty"])) < 1e-8:
                    logger.info(f"EtfEngine | CLOSED position: {symbol}")
                    return True
                time.sleep(1)

            # The caller must retain the DB row unless Alpaca confirms flat.
            # Cancel an unfilled residual close before restoring stop coverage.
            if getattr(order, "id", None) and not self._cancel_and_confirm_order(order.id):
                logger.critical(
                    f"EtfEngine | {symbol}: close order {order.id} still active; "
                    "refusing overlapping replacement stop"
                )
                return False
            if bot_id and stop_price is not None:
                self.ensure_protective_stop(bot_id, symbol, stop_price)
            logger.error(f"EtfEngine | Full close unfilled after 30s: {symbol}; stop restored")
            return False
        except Exception as exc:
            raw_error = repr(exc)
            logger.error(f"EtfEngine | Close failed {symbol}: {raw_error}")
            self._persist_close_failure(bot_id, symbol, raw_error)
            # The broker may have accepted the sell even though the client lost
            # the response. Do not submit an overlapping stop until that order
            # can be resolved by the next reconciliation cycle.
            # B-6 fix: alert inside the engine so ANY caller gets the Discord ping
            # even if it forgot to check the return value.
            try:
                from notifications.discord import notify_capital_risk
                notify_capital_risk(
                    f"🔴 {symbol}: ETF close_position FAILED at broker",
                    symbol=symbol,
                )
            except Exception:
                pass
            return False

    @staticmethod
    def _persist_close_failure(
        bot_id: Optional[str],
        symbol: str,
        raw_error: str,
    ) -> None:
        """Persist the complete broker close error without truncation."""
        try:
            _ensure_tp()
            from db.postgres import get_conn, is_pg_available
            if not is_pg_available():
                return
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO system_degradations
                            (component, severity, error_type, message, detail)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            bot_id or "unknown",
                            "critical",
                            "close_failed",
                            raw_error,
                            f"symbol={symbol}",
                        ),
                    )
        except Exception as db_exc:
            logger.error(
                f"EtfEngine | Failed to persist close error for "
                f"{bot_id}/{symbol}: {db_exc!r}"
            )

    # ── Broker-native stop protection ─────────────────────────────────────────

    @staticmethod
    def _whole_stop_qty(position_qty: float) -> int:
        """Alpaca only permits GTC equity stops for whole-share quantities."""
        return math.floor(abs(float(position_qty)))

    def _store_stop_order_id(
        self,
        bot_id: str,
        symbol: str,
        order_id: str,
        stop_price: Optional[float] = None,
    ) -> None:
        """Persist the broker stop reference for reconciliation.

        ``ensure_protective_stop`` is also the restart-safe replacement path.
        Persist both fields after every successful no-op, replacement, or fresh
        placement so a broker-native change cannot leave stale ledger metadata.
        """
        _ensure_tp()
        try:
            from db.postgres import get_conn, is_pg_available
            if not is_pg_available():
                return
            with get_conn() as conn:
                with conn.cursor() as cur:
                    if stop_price is None:
                        cur.execute("""
                            UPDATE alpaca_etf_positions
                               SET stop_order_id = %s
                             WHERE bot_id = %s
                               AND symbol = %s
                               AND status = 'open'
                        """, (order_id, bot_id, symbol))
                    else:
                        cur.execute("""
                            UPDATE alpaca_etf_positions
                               SET stop_order_id = %s,
                                   stop_price = %s
                             WHERE bot_id = %s
                               AND symbol = %s
                               AND status = 'open'
                        """, (order_id, stop_price, bot_id, symbol))
                    if cur.rowcount != 1:
                        logger.error(
                            f"EtfEngine | Stop ledger update affected {cur.rowcount} "
                            f"rows for {bot_id}/{symbol}"
                        )
                conn.commit()
        except Exception as exc:
            logger.error(
                f"EtfEngine | Failed to persist stop reference for "
                f"{bot_id}/{symbol}: {exc}"
            )

    @staticmethod
    def _stop_client_order_id(bot_id: str, symbol: str) -> str:
        """Stable owner marker used to avoid touching another strategy's order."""
        _ensure_tp()
        from core.order_ids import make_client_order_id
        return make_client_order_id(f"etf-stop-{bot_id}-{symbol}")

    @staticmethod
    def _exit_client_order_prefix(bot_id: str, symbol: str) -> str:
        """Bot/symbol ownership prefix used to fence reconciliation during exits."""
        return f"etf-exit-{bot_id}-{symbol}-".lower()[:36]

    def _new_exit_client_order_id(self, bot_id: str, symbol: str) -> str:
        """Unique Alpaca client ID for an exit, retaining the owner prefix."""
        _ensure_tp()
        from core.order_ids import make_client_order_id
        return make_client_order_id(self._exit_client_order_prefix(bot_id, symbol))

    def _has_pending_owned_exit(self, bot_id: str, symbol: str) -> bool:
        """Return True while an owned market exit could still reduce the position."""
        exit_prefix = self._exit_client_order_prefix(bot_id, symbol)
        try:
            from core.order_ids import client_order_id_matches_prefix
            return any(
                same_symbol(order.symbol, symbol)
                and order.side == "sell"
                and order.type == "market"
                and client_order_id_matches_prefix(
                    getattr(order, "client_order_id", ""),
                    exit_prefix,
                )
                for order in self.api.list_orders(status="open", limit=100, nested=True)
            )
        except Exception as exc:
            logger.error(f"EtfEngine | Exit fence query failed for {bot_id}/{symbol}: {exc}")
            # Fail closed: do not create another sell order while order status is unknown.
            return True

    def _find_owned_stop(
        self,
        bot_id: str,
        symbol: str,
        stop_order_id: Optional[str],
    ):
        """Find this bot's stop by DB identity first, then owner prefix."""
        def _is_stop(order) -> bool:
            if (
                order.symbol != symbol
                or order.side != "sell"
                or order.type not in {"stop", "stop_limit", "trailing_stop"}
            ):
                return False
            return True

        def _has_owner_prefix(order) -> bool:
            client_order_id = str(getattr(order, "client_order_id", "")).lower()
            from core.order_ids import client_order_id_matches_prefix
            return (
                client_order_id_matches_prefix(
                    client_order_id,
                    f"etf-stop-{bot_id}-{symbol}",
                )
                or (
                    bot_id == "bot2_spy_qqq"
                    and client_order_id_matches_prefix(
                        client_order_id,
                        f"etf-protect-{symbol}",
                    )
                )
            )

        if stop_order_id:
            try:
                order = self.api.get_order(stop_order_id)
                if (
                    str(order.status).lower() in {"new", "accepted", "pending_new"}
                    and _is_stop(order)
                ):
                    return order
                logger.error(
                    f"EtfEngine | Recorded stop {stop_order_id} is not an active "
                    f"{bot_id}/{symbol} sell-stop; refusing to mutate it"
                )
            except Exception as exc:
                logger.warning(f"EtfEngine | Cannot read recorded stop {stop_order_id}: {exc}")

        for order in self.api.list_orders(status="open", limit=100, nested=True):
            if _is_stop(order) and _has_owner_prefix(order):
                return order
        return None

    def _cancel_owned_stop(
        self,
        bot_id: str,
        symbol: str,
        stop_order_id: Optional[str],
    ) -> bool:
        """Cancel and confirm cancellation of this bot's protective stop only."""
        order = self._find_owned_stop(bot_id, symbol, stop_order_id)
        if not order:
            return True
        if self._cancel_and_confirm_order(order.id):
            logger.info(f"EtfEngine | Protective stop cancelled: {symbol} id={order.id}")
            return True
        logger.error(f"EtfEngine | Stop cancellation failed for {symbol}: id={order.id}")
        return False

    def _cancel_and_confirm_order(self, order_id: str, timeout_seconds: int = 5) -> bool:
        """Cancel an order and wait for Alpaca's terminal cancellation state."""
        try:
            self.api.cancel_order(order_id)
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                refreshed = self.api.get_order(order_id)
                if str(refreshed.status).lower() in {"canceled", "expired", "rejected"}:
                    return True
                time.sleep(0.25)
            logger.error(f"EtfEngine | Order cancellation unconfirmed: id={order_id}")
        except Exception as exc:
            logger.error(f"EtfEngine | Order cancellation failed id={order_id}: {exc}")
        return False

    def _wait_for_shares_free(
        self,
        symbol: str,
        qty: int,
        *,
        attempts: int = 5,
        interval_seconds: float = 2.0,
    ) -> bool:
        """Wait for broker-held shares to be released before a replacement submit."""
        for attempt in range(attempts):
            try:
                position = self.api.get_position(symbol)
                qty_available = getattr(position, "qty_available", None)
                active_sell = any(
                    same_symbol(order.symbol, symbol)
                    and str(order.side).lower() == "sell"
                    for order in self.api.list_orders(status="open", limit=100, nested=True)
                )
                if not active_sell and (
                    qty_available is None or float(qty_available) >= float(qty)
                ):
                    return True
            except Exception as exc:
                logger.warning(
                    f"EtfEngine | {symbol}: share-release poll {attempt + 1}/{attempts} "
                    f"failed: {exc!r}"
                )
            if attempt < attempts - 1:
                time.sleep(interval_seconds)
        return False

    def ensure_protective_stop(
        self,
        bot_id: str,
        symbol: str,
        stop_price: float,
        stop_order_id: Optional[str] = None,
    ) -> Optional[str]:
        """Create or reconcile the broker-native GTC stop for a live long ETF.

        The Alpaca API rejects fractional GTC stops. The protective order therefore
        covers the safely rounded-down whole-share portion; all future ETF entries
        use whole-share sizing so they are fully covered.
        """
        if is_cash_park(symbol):
            logger.debug(f"EtfEngine | {symbol}: cash-park exemption — no protective stop")
            return None
        if self._has_pending_owned_exit(bot_id, symbol):
            logger.warning(
                f"EtfEngine | {symbol}: protective-stop update deferred while owned exit is working"
            )
            return None
        broker_stop = float(stop_price)
        stop_qty = 0
        try:
            live = next((p for p in self.get_positions() if same_symbol(p["symbol"], symbol)), None)
            if not live:
                logger.info(f"EtfEngine | {symbol}: stop pending — broker position not filled yet")
                return None

            position_qty = float(live["qty"])
            stop_qty = self._whole_stop_qty(position_qty)
            if stop_qty < 1:
                logger.warning(
                    f"EtfEngine | {symbol}: cannot place GTC stop for fractional-only "
                    f"position qty={position_qty:.8f}"
                )
                return None

            broker_stop = round(broker_stop, 2)
            if broker_stop <= 0:
                raise ValueError(f"invalid stop price {stop_price}")

            existing_stop = self._find_owned_stop(bot_id, symbol, stop_order_id)
            if existing_stop:
                order = existing_stop
                order_qty = self._whole_stop_qty(float(order.qty or 0))
                order_stop = float(getattr(order, "stop_price", 0) or 0)
                stop_delta = (
                    abs(broker_stop - order_stop) / order_stop
                    if order_stop > 0 else float("inf")
                )
                logger.info(
                    f"EtfEngine | {symbol}: stop comparison "
                    f"desired=${broker_stop:.2f} active=${order_stop:.2f} "
                    f"delta={stop_delta:.3%}"
                )
                if stop_delta <= 0.005:
                    self._store_stop_order_id(
                        bot_id, symbol, order.id, stop_price=order_stop
                    )
                    logger.info(
                        f"EtfEngine | {symbol}: stop within 0.5% — "
                        "leaving existing stop untouched"
                    )
                    return order.id

            if existing_stop:
                try:
                    order = self.api.replace_order(
                        existing_stop.id,
                        qty=stop_qty,
                        stop_price=broker_stop,
                        time_in_force="gtc",
                    )
                    self._store_stop_order_id(
                        bot_id, symbol, order.id, stop_price=broker_stop
                    )
                    logger.info(
                        f"EtfEngine | PROTECTIVE STOP REPLACED: {symbol} "
                        f"qty={stop_qty} stop=${broker_stop:.2f} id={order.id}"
                    )
                    return order.id
                except Exception as replace_exc:
                    # Only fall back to a fresh submit when the original order
                    # is already terminal or no longer exists at the broker.
                    try:
                        current = self.api.get_order(existing_stop.id)
                        current_status = (
                            str(current.status).lower().rsplit(".", 1)[-1]
                        )
                        order_gone = current_status in {
                            "canceled", "expired", "rejected", "done_for_day"
                        }
                    except Exception:
                        order_gone = True
                    if not order_gone:
                        if current_status not in {
                            "new",
                            "partially_filled",
                            "accepted",
                            "pending_new",
                            "accepted_for_bidding",
                            "pending_cancel",
                            "pending_replace",
                        }:
                            raise replace_exc
                        try:
                            broker_position = next(
                                (
                                    position
                                    for position in self.api.list_positions()
                                    if same_symbol(position.symbol, symbol)
                                ),
                                None,
                            )
                            covered = False
                            if broker_position is not None:
                                position_asset_class = broker_position.asset_class
                                order_asset_class = current.asset_class
                                if not position_asset_class or not order_asset_class:
                                    raise ValueError(
                                        "broker position or stop is missing asset_class"
                                    )
                                position_snapshot = {
                                    "symbol": broker_position.symbol,
                                    "side": str(broker_position.side).lower().rsplit(".", 1)[-1],
                                    "qty": broker_position.qty,
                                    "asset_class": position_asset_class,
                                }
                                order_snapshot = {
                                    "symbol": current.symbol,
                                    "side": str(current.side).lower().rsplit(".", 1)[-1],
                                    "type": str(current.type).lower().rsplit(".", 1)[-1],
                                    "qty": current.qty,
                                    "asset_class": order_asset_class,
                                }
                                current_stop_price = float(current.stop_price or 0)
                                if current_stop_price <= 0:
                                    raise ValueError(
                                        "broker stop is missing a valid stop_price"
                                    )
                                from core.kill_switch import _covers

                                covered = _covers(position_snapshot, order_snapshot)
                        except Exception:
                            # Failed or incomplete verification follows the
                            # existing critical failure path.
                            raise replace_exc

                        if covered:
                            logger.warning(
                                f"EtfEngine | {symbol}: stop ratchet deferred; "
                                f"existing_stop_id={current.id} "
                                f"existing_stop_price=${current_stop_price:.2f} "
                                f"desired_stop_price=${broker_stop:.2f}"
                            )
                            from core.degradation_tracker import record_degradation

                            degradation_component = (
                                "spy_qqq_trend"
                                if bot_id == "bot2_spy_qqq"
                                else bot_id
                            )
                            record_degradation(
                                component=degradation_component,
                                severity="warning",
                                error_type="protective_stop_ratchet_deferred",
                                message=(
                                    f"{symbol} stop ratchet deferred; existing stop "
                                    "remains active and covers the live broker position"
                                ),
                                detail=(
                                    f"existing_stop_id={current.id}; "
                                    f"existing_stop_price={current_stop_price}; "
                                    f"desired_stop_price={broker_stop}; "
                                    f"qty={position_snapshot['qty']}"
                                ),
                                bot_id=bot_id,
                            )
                            return current.id
                        raise replace_exc
                    logger.warning(
                        f"EtfEngine | {symbol}: replace_order found terminal/missing "
                        f"stop {existing_stop.id}; guarded fresh submit follows: "
                        f"{replace_exc!r}"
                    )
                    if not self._wait_for_shares_free(symbol, stop_qty):
                        raise RuntimeError(
                            f"replace_order failed ({replace_exc!r}); "
                            "shares were not released for guarded fresh submit"
                        ) from replace_exc

            order, _ = submit_with_unique_client_order_id(
                lambda client_order_id: self.api.submit_order(
                    symbol=symbol,
                    qty=stop_qty,
                    side="sell",
                    type="stop",
                    time_in_force="gtc",
                    stop_price=broker_stop,
                    client_order_id=client_order_id,
                ),
                f"etf-stop-{bot_id}-{symbol}",
            )
            self._store_stop_order_id(
                bot_id, symbol, order.id, stop_price=broker_stop
            )
            residual = position_qty - stop_qty
            residual_note = (
                f" (fractional residual {residual:.8f} shares cannot use GTC)"
                if residual > 0 else ""
            )
            logger.info(
                f"EtfEngine | PROTECTIVE STOP PLACED: {symbol} "
                f"qty={stop_qty} stop=${broker_stop:.2f} id={order.id}{residual_note}"
            )
            return order.id
        except Exception as exc:
            raw_error = repr(exc)
            logger.error(
                f"EtfEngine | CRITICAL: protective stop failed for {symbol}: {raw_error}"
            )
            try:
                _ensure_tp()
                from db.postgres import get_conn, is_pg_available
                if is_pg_available():
                    degradation_component = (
                        "spy_qqq_trend" if bot_id == "bot2_spy_qqq" else bot_id
                    )
                    with get_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                INSERT INTO system_degradations
                                    (component, severity, error_type, message, detail)
                                VALUES (%s, %s, %s, %s, %s)
                                """,
                                (
                                    degradation_component,
                                    "critical",
                                    "protective_stop_failed",
                                    raw_error,
                                    f"symbol={symbol}; stop_price={broker_stop}; "
                                    f"qty={stop_qty}",
                                ),
                            )
            except Exception as db_exc:
                logger.error(
                    f"EtfEngine | Failed to persist protective-stop error for "
                    f"{bot_id}/{symbol}: {db_exc!r}"
                )
            try:
                from notifications.discord import notify_capital_risk
                notify_capital_risk(
                    f"🔴 {symbol}: protective GTC stop FAILED — {raw_error} "
                    "— position may be naked",
                    symbol=symbol,
                )
            except Exception:
                pass
            return None

    def _await_fill_and_protect(
        self,
        bot_id: str,
        symbol: str,
        stop_price: float,
        order_id: str,
        timeout_seconds: int = 25 * 60 * 60,
    ) -> None:
        """Poll a submitted DAY entry through the next session, then place its stop."""
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                order = self.api.get_order(order_id)
                status = str(order.status).lower()
                if float(getattr(order, "filled_qty", 0) or 0) > 0:
                    self.ensure_protective_stop(bot_id, symbol, stop_price)
                if status == "filled":
                    return
                if status in {"canceled", "rejected", "expired"}:
                    logger.error(
                        f"EtfEngine | {symbol}: entry {order_id} ended {status}; "
                        f"no protective stop required"
                    )
                    return
            except Exception as exc:
                logger.warning(f"EtfEngine | stop-fill monitor error for {symbol}: {exc}")
            time.sleep(5)
        logger.error(
            f"EtfEngine | CRITICAL: {symbol} entry {order_id} did not fill within "
            f"{timeout_seconds}s; stop reconciliation remains pending"
        )
        try:
            from notifications.discord import notify_capital_risk
            notify_capital_risk(
                f"🔴 {symbol}: entry fill monitor timed out — protective stop reconciliation pending",
                symbol=symbol,
            )
        except Exception:
            pass

    def arm_protective_stop_after_fill(
        self,
        bot_id: str,
        symbol: str,
        stop_price: float,
        order_id: str,
    ) -> None:
        """Attach a GTC stop immediately after a successful entry fill.

        A market-order fill is handled synchronously when already available. For a
        queued DAY order, a daemon monitor stays alive through the next session and
        attaches the stop as soon as the broker reports a partial or full fill.
        Every strategy cycle also reconciles as a restart-safe backstop.
        """
        try:
            order = self.api.get_order(order_id)
            if float(getattr(order, "filled_qty", 0) or 0) > 0:
                self.ensure_protective_stop(bot_id, symbol, stop_price)
            if str(order.status).lower() == "filled":
                return
        except Exception as exc:
            logger.warning(f"EtfEngine | Could not read entry {order_id} for {symbol}: {exc}")

        logger.info(f"EtfEngine | {symbol}: entry pending — monitoring for protective stop")
        threading.Thread(
            target=self._await_fill_and_protect,
            args=(bot_id, symbol, stop_price, order_id),
            name=f"etf-stop-{symbol}",
            daemon=True,
        ).start()

    def reconcile_protective_stops(
        self,
        bot_id: str,
        db_positions: list[dict],
    ) -> None:
        """Ensure every live DB-tracked long has the recorded stop at Alpaca."""
        for position in db_positions:
            if position.get("direction", "long") != "long":
                continue
            symbol = position.get("symbol", "")
            if is_cash_park(symbol):
                logger.debug(f"EtfEngine | {symbol}: cash-park exemption — skip stop reconciliation")
                continue
            if math.floor(abs(float(position.get("qty", 0) or 0))) < 1:
                logger.debug(f"EtfEngine | {symbol}: sub-1-share position — skip stop reconciliation")
                continue
            stop_price = position.get("stop_price")
            if stop_price is None:
                logger.error(
                    f"EtfEngine | CRITICAL: {bot_id}/{symbol} has no DB stop price"
                )
                continue
            if self._has_pending_owned_exit(bot_id, symbol):
                logger.warning(
                    f"EtfEngine | {symbol}: exit is working; stop reconciliation deferred"
                )
                continue
            self.ensure_protective_stop(
                bot_id,
                symbol,
                float(stop_price),
                position.get("stop_order_id"),
            )

    def close_partial(
        self,
        symbol: str,
        qty: float,
        *,
        bot_id: Optional[str] = None,
        stop_order_id: Optional[str] = None,
        stop_price: Optional[float] = None,
    ) -> bool:
        """Close a specific quantity (for tiered profit-taking scale-outs).
        A protected position is only scaled while the market is open so a
        cancelled stop is never left off overnight behind a queued sell.
        """
        if bot_id and not self.is_market_open():
            logger.info(f"EtfEngine | Partial close deferred — market closed; {symbol} stop stays active")
            return False
        if bot_id and self._has_pending_owned_exit(bot_id, symbol):
            logger.warning(f"EtfEngine | Partial close already pending for {symbol}; awaiting broker")
            return False
        tif = "day"
        if bot_id and not self._cancel_owned_stop(bot_id, symbol, stop_order_id):
            logger.error(f"EtfEngine | Partial close blocked — {symbol} stop still active")
            return False
        try:
            order, _ = submit_with_unique_client_order_id(
                lambda client_order_id: self.api.submit_order(
                    symbol=symbol,
                    qty=round(qty, 8),
                    side="sell",
                    type="market",
                    time_in_force=tif,
                    client_order_id=client_order_id,
                ),
                self._exit_client_order_prefix(bot_id, symbol) if bot_id else f"etf-exit-{symbol}",
            )
            logger.info(f"EtfEngine | PARTIAL CLOSE: {symbol} qty={qty:.4f} tif={tif}")
            deadline = time.monotonic() + 20
            filled_qty = 0.0
            while time.monotonic() < deadline:
                refreshed = self.api.get_order(order.id)
                filled_qty = float(getattr(refreshed, "filled_qty", 0) or 0)
                status = str(refreshed.status).lower()
                if status == "filled":
                    if bot_id:
                        self._sync_current_qty_after_sale(bot_id, symbol)
                    if bot_id and stop_price is not None:
                        self.ensure_protective_stop(bot_id, symbol, stop_price)
                    return True
                if status in {"canceled", "rejected", "expired"}:
                    break
                time.sleep(0.5)

            # Never re-arm a stop while an exit remainder is still working:
            # cancel it first, then size stop coverage to the live residual.
            if not self._cancel_and_confirm_order(order.id):
                logger.critical(
                    f"EtfEngine | {symbol}: partial-exit order {order.id} still active; "
                    "refusing overlapping replacement stop"
                )
                if bot_id and filled_qty > 0:
                    self._sync_current_qty_after_sale(bot_id, symbol)
                return False
            if bot_id and stop_price is not None:
                self.ensure_protective_stop(bot_id, symbol, stop_price)
            if filled_qty > 0:
                if bot_id:
                    self._sync_current_qty_after_sale(bot_id, symbol)
                logger.warning(
                    f"EtfEngine | Partial close {symbol} filled {filled_qty} before timeout; "
                    f"residual reprotected"
                )
                return True
            logger.error(f"EtfEngine | Partial close {symbol} unfilled; stop restored")
            return False
        except Exception as exc:
            logger.error(f"EtfEngine | Partial close failed {symbol} qty={qty}: {exc}")
            # A transport exception can happen after Alpaca accepted the sell.
            # Leave reconciliation state intact and avoid overlapping sell risk.
            return False

    # ── Market hours ──────────────────────────────────────────────────────────

    def is_market_open(self) -> bool:
        try:
            clock = self.api.get_clock()
            return clock.is_open
        except Exception as exc:
            logger.warning(f"EtfEngine | Clock check failed: {exc} — assuming closed")
            return False

    # ── Stop / TP checks ──────────────────────────────────────────────────────

    def check_stop_hit(self, db_position: dict, current_price: float) -> bool:
        """
        Returns True if current_price has hit the trailing stop.
        stop_price is stored in alpaca_etf_positions and updated by update_trailing_stop().
        """
        stop = db_position.get("stop_price")
        if stop and current_price <= float(stop):
            return True
        return False

    def update_trailing_stop(
        self,
        bot_id: str,
        symbol: str,
        current_price: float,
        trail_pct: float = 0.08,
    ) -> None:
        """
        Ratchet trailing stop upward if current_price justifies a higher stop.
        New stop = current_price * (1 - trail_pct). Only moves upward, never down.
        """
        new_stop = current_price * (1 - trail_pct)
        _ensure_tp()
        try:
            from db.postgres import get_conn, is_pg_available
            if not is_pg_available():
                return
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE alpaca_etf_positions
                        SET stop_price = GREATEST(stop_price, %s)
                        WHERE bot_id = %s AND symbol = %s AND status = 'open'
                    """, (new_stop, bot_id, symbol))
                conn.commit()
        except Exception as exc:
            logger.error(f"EtfEngine | Trailing stop update failed: {exc}")

    def check_tp1_hit(self, db_position: dict, current_price: float) -> bool:
        """Returns True if tp1_price reached and scale-out not yet done."""
        tp1 = db_position.get("tp1_price")
        scaled = db_position.get("scaled_out_tp1", False)
        return tp1 is not None and not scaled and current_price >= float(tp1)

    def check_tp2_hit(self, db_position: dict, current_price: float) -> bool:
        """Returns True if tp2_price reached and scale-out not yet done."""
        tp2 = db_position.get("tp2_price")
        scaled = db_position.get("scaled_out_tp2", False)
        return tp2 is not None and not scaled and current_price >= float(tp2)

    def check_min_hold(self, db_position: dict) -> bool:
        """Returns True if minimum hold period has elapsed (safe to exit)."""
        min_hold_until = db_position.get("min_hold_until")
        if not min_hold_until:
            return True
        now = datetime.now(timezone.utc)
        if isinstance(min_hold_until, str):
            from datetime import datetime as _dt
            min_hold_until = _dt.fromisoformat(min_hold_until)
        if min_hold_until.tzinfo is None:
            min_hold_until = min_hold_until.replace(tzinfo=timezone.utc)
        return now >= min_hold_until

    # ── DB writes ─────────────────────────────────────────────────────────────

    def get_db_positions(self, bot_id: str) -> list[dict]:
        """Read all open positions for this bot from alpaca_etf_positions table."""
        _ensure_tp()
        try:
            from db.postgres import get_conn, is_pg_available
            if not is_pg_available():
                return []
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, bot_id, symbol, direction, qty,
                               entry_price, entry_atr, notional_usd,
                               stop_price, tp1_price, tp2_price,
                               scaled_out_tp1, scaled_out_tp2,
                                min_hold_until, status, opened_at, stop_order_id
                        FROM alpaca_etf_positions
                        WHERE bot_id = %s AND status = 'open'
                        ORDER BY opened_at DESC
                    """, (bot_id,))
                    cols = [d[0] for d in cur.description]
                    return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception as exc:
            logger.error(f"EtfEngine | get_db_positions failed: {exc}")
            return []

    def record_open(
        self,
        bot_id: str,
        symbol: str,
        direction: str,
        qty: float,
        entry_price: float,
        entry_atr: Optional[float],
        notional_usd: float,
        stop_price: float,
        tp1_price: float,
        tp2_price: float,
        min_hold_days: int,
    ) -> bool:
        """Insert a new position record; return whether primary persistence succeeded."""
        _ensure_tp()
        min_hold_until = datetime.now(timezone.utc) + timedelta(days=min_hold_days)
        try:
            from db.postgres import get_conn, is_pg_available
            if not is_pg_available():
                logger.error(f"EtfEngine | record_open unavailable for {bot_id}/{symbol}")
                return False
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO alpaca_etf_positions
                            (bot_id, symbol, direction, qty, current_qty,
                             entry_price, entry_atr, notional_usd,
                             stop_price, tp1_price, tp2_price,
                             min_hold_until, status, opened_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'open',NOW())
                    """, (
                        bot_id, symbol, direction, qty, qty,
                        entry_price, entry_atr, notional_usd,
                        stop_price, tp1_price, tp2_price,
                        min_hold_until,
                    ))
                conn.commit()
            logger.info(f"EtfEngine | DB: recorded open {bot_id}/{symbol}")
        except Exception as exc:
            logger.error(f"EtfEngine | record_open failed: {exc}")
            return False
        # Mirror to trades table so /journal and reporting pick it up
        try:
            from analysis.trade_journal import log_trade as _lt
            _lt(
                trade_id=f"ETF-{bot_id}-{symbol}-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
                ticker=symbol,
                asset_class="momentum_etf",
                conviction_score=0.0,
                original_thesis=(
                    f"ETF Trend Long {bot_id}: entry={entry_price:.2f} "
                    f"stop={stop_price:.2f} notional=${notional_usd:,.0f}"
                ),
                intended_price=entry_price,
            )
            logger.info(f"EtfEngine | log_trade: recorded trades row for {bot_id}/{symbol}")
        except Exception as _lt_exc:
            # B-10 fix: warning→error so grep finds mirror failures.
            logger.error(f"EtfEngine | log_trade mirror failed: {_lt_exc}")
        return True

    def record_resize(
        self,
        bot_id: str,
        symbol: str,
        added_qty: float,
        broker_qty: float,
        avg_entry_price: float,
    ) -> bool:
        """A position grew (sleeve rebalance buy): update its single open row.
        qty (entry size) grows by the fill; current_qty becomes the broker
        quantity; entry_price is the broker's average. Refuses unless exactly
        one open row exists for the symbol."""
        _ensure_tp()
        try:
            from db.postgres import get_conn, is_pg_available
            if not is_pg_available():
                logger.error(f"EtfEngine | record_resize unavailable for {bot_id}/{symbol}")
                return False
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE alpaca_etf_positions
                           SET qty          = qty + %s,
                               current_qty  = %s,
                               entry_price  = %s,
                               notional_usd = %s
                         WHERE bot_id = %s AND symbol = %s AND status = 'open'
                    """, (added_qty, broker_qty, avg_entry_price,
                          broker_qty * avg_entry_price, bot_id, symbol))
                    if cur.rowcount != 1:
                        conn.rollback()
                        logger.error(
                            f"EtfEngine | record_resize matched {cur.rowcount} rows for "
                            f"{bot_id}/{symbol}; nothing written"
                        )
                        return False
                conn.commit()
            logger.info(f"EtfEngine | DB: resized {bot_id}/{symbol} +{added_qty} -> {broker_qty}")
            return True
        except Exception as exc:
            logger.error(f"EtfEngine | record_resize failed: {exc}")
            return False

    def record_close(
        self,
        bot_id: str,
        symbol: str,
        exit_reason: str,
        realised_pnl: Optional[float] = None,
    ) -> None:
        """Mark position as closed in alpaca_etf_positions."""
        _ensure_tp()
        try:
            from db.postgres import get_conn, is_pg_available
            if not is_pg_available():
                return
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE alpaca_etf_positions
                        SET status       = 'closed',
                            current_qty  = 0,
                            closed_at    = NOW(),
                            exit_reason  = %s,
                            realised_pnl = %s
                        WHERE bot_id = %s AND symbol = %s AND status = 'open'
                        RETURNING id
                    """, (exit_reason, realised_pnl, bot_id, symbol))
                    closed_row = cur.fetchone()
                conn.commit()
            logger.info(f"EtfEngine | DB: recorded close {bot_id}/{symbol} — {exit_reason}")
        except Exception as exc:
            logger.error(f"EtfEngine | record_close failed: {exc}")
            closed_row = None
        # Mirror close to trades table
        try:
            from db.postgres import get_conn as _gc
            from analysis.trade_journal import close_trade as _ct
            with _gc() as _c:
                with _c.cursor() as _cur:
                    _cur.execute(
                        "SELECT trade_id, intended_price FROM trades "
                        "WHERE ticker = %s AND asset_class = 'momentum_etf' AND status = 'Active' "
                        "AND LEFT(trade_id, LENGTH(%s)) = %s "
                        "ORDER BY date DESC LIMIT 1",
                        (symbol, f"ETF-{bot_id}-{symbol}-", f"ETF-{bot_id}-{symbol}-"),
                    )
                    _row = _cur.fetchone()
            if _row:
                _tid, _entry = _row[0], float(_row[1] or 0)
                # Use ±1.0 sentinel (supported by close_trade) when full cost basis unavailable
                _pnl_pct = (1.0 if (realised_pnl or 0) >= 0 else -1.0)
                _ct(
                    trade_id=_tid,
                    pnl_percentage=_pnl_pct,
                    realized_pnl=realised_pnl,
                    exit_reason=exit_reason,
                    bot_id=bot_id,
                )
                logger.info(f"EtfEngine | close_trade: updated trades row for {bot_id}/{symbol}")
        except Exception as _ct_exc:
            # B-10 fix: warning→error so grep finds mirror failures.
            logger.error(f"EtfEngine | close_trade mirror failed: {_ct_exc}")

    def reconcile_etf_trades(self, bot_id: str) -> None:
        """Mirror of Oracle reconciler for ETF bots.

        For every open alpaca_etf_positions row that has no matching Active row
        in the trades table (asset_class='momentum_etf'), insert one via log_trade().
        Runs every cycle — idempotent, non-fatal.
        """
        try:
            from db.postgres import get_conn, is_pg_available
            if not is_pg_available():
                return

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT symbol, entry_price, notional_usd FROM alpaca_etf_positions "
                        "WHERE bot_id = %s AND status = 'open'",
                        (bot_id,),
                    )
                    open_etf = {
                        row[0]: (float(row[1] or 0), float(row[2] or 0))
                        for row in cur.fetchall()
                    }

            if not open_etf:
                return

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT ticker FROM trades "
                        "WHERE status = 'Active' AND asset_class = 'momentum_etf'"
                    )
                    active_tickers = {row[0] for row in cur.fetchall()}

            from analysis.trade_journal import log_trade as _lt
            for sym, (entry_px, notional) in open_etf.items():
                if sym in active_tickers:
                    continue
                _lt(
                    trade_id=f"RECON-ETF-{bot_id}-{sym}-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
                    ticker=sym,
                    asset_class="momentum_etf",
                    conviction_score=0.0,
                    original_thesis=f"Reconciled: {bot_id} ETF position had no trades row",
                    intended_price=entry_px or None,
                )
                logger.info(
                    f"EtfEngine | Reconciler: inserted trades row for "
                    f"{bot_id}/{sym} (entry={entry_px:.2f})"
                )
        except Exception as exc:
            # B-9 fix: self-healing layer failing must be visible — escalate to ERROR
            # + record degradation so it surfaces in the dashboard audit trail.
            logger.error(f"EtfEngine | reconcile_etf_trades FAILED — self-healing layer down: {exc}")
            try:
                from core.degradation_tracker import record_degradation
                record_degradation(
                    component="etf_reconciler",
                    severity="medium",
                    error_type="etf_reconciler_failed",
                    message=f"ETF reconciler failed for bot_id={bot_id}: {str(exc)[:200]}",
                    detail=str(exc)[:500],
                )
            except Exception:
                pass

    def mark_scaled_out(self, bot_id: str, symbol: str, tier: int) -> None:
        """Mark tp1 or tp2 scale-out as done (tier=1 or tier=2)."""
        _ensure_tp()
        col = "scaled_out_tp1" if tier == 1 else "scaled_out_tp2"
        try:
            from db.postgres import get_conn, is_pg_available
            if not is_pg_available():
                return
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE alpaca_etf_positions SET {col} = TRUE "
                        f"WHERE bot_id = %s AND symbol = %s AND status = 'open'",
                        (bot_id, symbol),
                    )
                conn.commit()
        except Exception as exc:
            logger.error(f"EtfEngine | mark_scaled_out failed: {exc}")

    # ── Heartbeat ─────────────────────────────────────────────────────────────

    def update_heartbeat(self, db_id: int, equity: float, position_count: int) -> None:
        """
        Update kraken_heartbeat row for this bot.

        ACTIVATION REMINDER: When activating each new bot, first run:
          UPDATE kraken_heartbeat
          SET bot_id = '<new_bot_id>', bot_display_name = '<new_display_name>'
          WHERE id = <db_id>;
        This syncs the heartbeat row to the new bot identity before it starts trading.
        """
        _ensure_tp()
        try:
            from db.postgres import get_conn, is_pg_available
            if not is_pg_available():
                return
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE kraken_heartbeat
                        SET equity_usd     = %s,
                            position_count = %s,
                            status         = 'running',
                            last_updated   = NOW()
                        WHERE id = %s
                    """, (equity, position_count, db_id))
                conn.commit()
        except Exception as exc:
            logger.error(f"EtfEngine | Heartbeat update failed: {exc}")

    # ── Convenience: exit check for a single position ─────────────────────────

    def run_exit_checks(
        self,
        bot_id: str,
        db_position: dict,
        live_positions: list[dict],
        trail_pct: float = 0.08,
    ) -> Optional[str]:
        """
        Run all exit checks for one DB position against live Alpaca data.
        Returns exit_reason string if should exit, None if hold.
        Caller must execute the close and record_close() after receiving a reason.

        Checks (in order):
          1. Trailing stop (always enforced, ignores min_hold)
          2. Minimum hold — if not elapsed, skip TP checks
          3. TP2 scale-out (33%) — mark only, don't close full position
          4. TP1 scale-out (33%) — mark only, don't close full position
          5. Returns None (hold)
        """
        symbol = db_position["symbol"]
        live = next((p for p in live_positions if same_symbol(p["symbol"], symbol)), None)
        if not live:
            return None

        current = live["current_price"]
        entry   = float(db_position["entry_price"])

        # Update trailing stop (ratchet upward)
        self.update_trailing_stop(bot_id, symbol, current, trail_pct)

        # Re-read and broker-sync the ratcheted stop before any exit decision.
        fresh = self.get_db_positions(bot_id)
        db_pos_fresh = next((p for p in fresh if same_symbol(p["symbol"], symbol)), db_position)
        self.ensure_protective_stop(
            bot_id,
            symbol,
            float(db_pos_fresh["stop_price"]),
            db_pos_fresh.get("stop_order_id"),
        )

        # 1. Hard trailing stop (overrides min_hold)
        if self.check_stop_hit(db_pos_fresh, current):
            pct = (current - entry) / entry * 100
            return f"trailing_stop ({pct:+.2f}%)"

        # 2. Min hold — skip TP checks if not elapsed
        if not self.check_min_hold(db_pos_fresh):
            return None

        # 3. TP2 scale-out
        if self.check_tp2_hit(db_pos_fresh, current):
            qty = float(db_position.get("qty", 0))
            scale_qty = math.floor(qty * 0.333)
            if scale_qty > 0:
                if self.close_partial(
                    symbol,
                    scale_qty,
                    bot_id=bot_id,
                    stop_order_id=db_pos_fresh.get("stop_order_id"),
                    stop_price=float(db_pos_fresh["stop_price"]),
                ):
                    self.mark_scaled_out(bot_id, symbol, tier=2)
                    logger.info(f"EtfEngine | TP2 scale-out: {symbol} {scale_qty:.4f} shares")
                else:
                    # B-7 fix: alert on TP failure; scaled_out_tp2 NOT set so next
                    # cycle retries the partial close automatically.
                    try:
                        from notifications.discord import notify_capital_risk
                        notify_capital_risk(
                            f"⚠️ {symbol}: TP scale-out FAILED — position stays full size",
                            symbol=symbol,
                        )
                    except Exception:
                        pass
            return None  # Position still open (partial close)

        # 4. TP1 scale-out
        if self.check_tp1_hit(db_pos_fresh, current):
            qty = float(db_position.get("qty", 0))
            scale_qty = math.floor(qty * 0.333)
            if scale_qty > 0:
                if self.close_partial(
                    symbol,
                    scale_qty,
                    bot_id=bot_id,
                    stop_order_id=db_pos_fresh.get("stop_order_id"),
                    stop_price=float(db_pos_fresh["stop_price"]),
                ):
                    self.mark_scaled_out(bot_id, symbol, tier=1)
                    logger.info(f"EtfEngine | TP1 scale-out: {symbol} {scale_qty:.4f} shares")
                else:
                    # B-7 fix: same — scaled_out_tp1 NOT set, retries next cycle.
                    try:
                        from notifications.discord import notify_capital_risk
                        notify_capital_risk(
                            f"⚠️ {symbol}: TP scale-out FAILED — position stays full size",
                            symbol=symbol,
                        )
                    except Exception:
                        pass
            return None  # Position still open (partial close)

        return None  # Hold
