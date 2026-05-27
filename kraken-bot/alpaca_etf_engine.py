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
When activating a new bot, run this SQL BEFORE flipping BOT_PAUSED=False:
  UPDATE kraken_heartbeat
  SET bot_id = '<new_bot_id>', bot_display_name = '<new_display_name>'
  WHERE id = <db_id>;
This prevents the dashboard showing the old paused bot name while the new bot trades.
Week 2: bot2_spy_qqq (db_id=1) | Week 3: bot4_sector (db_id=3)
Week 4: bot7_macro_bond (db_id=7) | Week 5: bot5_defensive (db_id=4)
"""
from __future__ import annotations

import logging
import os
import sys
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
                            entry_price     NUMERIC       NOT NULL,
                            entry_atr       NUMERIC,
                            notional_usd    NUMERIC       NOT NULL,
                            stop_price      NUMERIC,
                            tp1_price       NUMERIC,
                            tp2_price       NUMERIC,
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
                    """)
                conn.commit()
            logger.info("EtfEngine | alpaca_etf_positions schema verified")
        except Exception as exc:
            logger.error(f"EtfEngine | _ensure_schema failed: {exc}")

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account(self) -> dict:
        acc = self.api.get_account()
        return {
            "equity":       float(acc.equity),
            "cash":         float(acc.cash),
            "buying_power": float(acc.buying_power),
        }

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

    # ── Orders ────────────────────────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        side: str,
        notional: float,
    ) -> Optional[dict]:
        """Place a fractional notional market order. side must be 'buy' or 'sell'.
        Uses time_in_force="day" when NYSE is open; "opg" (at-the-open) when closed
        so off-hours orders queue for next open instead of being rejected.
        """
        tif = "day" if _nyse_is_open() else "opg"
        logger.info(f"EtfEngine | Submitting {side.upper()} {symbol} notional=${notional:,.2f} tif={tif}")
        try:
            order = self.api.submit_order(
                symbol=symbol,
                notional=round(notional, 2),
                side=side,
                type="market",
                time_in_force=tif,
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

    def close_position(self, symbol: str) -> bool:
        """Close entire position in a symbol."""
        try:
            self.api.close_position(symbol)
            logger.info(f"EtfEngine | CLOSED position: {symbol}")
            return True
        except Exception as exc:
            logger.error(f"EtfEngine | Close failed {symbol}: {exc}")
            return False

    def close_partial(self, symbol: str, qty: float) -> bool:
        """Close a specific quantity (for tiered profit-taking scale-outs).
        Uses "day" when NYSE is open; "opg" when closed so partial exits
        queue for next open rather than being silently rejected.
        """
        tif = "day" if _nyse_is_open() else "opg"
        try:
            self.api.submit_order(
                symbol=symbol,
                qty=round(qty, 8),
                side="sell",
                type="market",
                time_in_force=tif,
            )
            logger.info(f"EtfEngine | PARTIAL CLOSE: {symbol} qty={qty:.4f} tif={tif}")
            return True
        except Exception as exc:
            logger.error(f"EtfEngine | Partial close failed {symbol} qty={qty}: {exc}")
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
                               min_hold_until, status, opened_at
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
    ) -> None:
        """Insert a new position record into alpaca_etf_positions."""
        _ensure_tp()
        min_hold_until = datetime.now(timezone.utc) + timedelta(days=min_hold_days)
        try:
            from db.postgres import get_conn, is_pg_available
            if not is_pg_available():
                return
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO alpaca_etf_positions
                            (bot_id, symbol, direction, qty,
                             entry_price, entry_atr, notional_usd,
                             stop_price, tp1_price, tp2_price,
                             min_hold_until, status, opened_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'open',NOW())
                    """, (
                        bot_id, symbol, direction, qty,
                        entry_price, entry_atr, notional_usd,
                        stop_price, tp1_price, tp2_price,
                        min_hold_until,
                    ))
                conn.commit()
            logger.info(f"EtfEngine | DB: recorded open {bot_id}/{symbol}")
        except Exception as exc:
            logger.error(f"EtfEngine | record_open failed: {exc}")
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
            logger.warning(f"EtfEngine | log_trade mirror failed (non-fatal): {_lt_exc}")

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
                            closed_at    = NOW(),
                            exit_reason  = %s,
                            realised_pnl = %s
                        WHERE bot_id = %s AND symbol = %s AND status = 'open'
                    """, (exit_reason, realised_pnl, bot_id, symbol))
                conn.commit()
            logger.info(f"EtfEngine | DB: recorded close {bot_id}/{symbol} — {exit_reason}")
        except Exception as exc:
            logger.error(f"EtfEngine | record_close failed: {exc}")
        # Mirror close to trades table
        try:
            from db.postgres import get_conn as _gc
            from analysis.trade_journal import close_trade as _ct
            with _gc() as _c:
                with _c.cursor() as _cur:
                    _cur.execute(
                        "SELECT trade_id, intended_price FROM trades "
                        "WHERE ticker = %s AND asset_class = 'momentum_etf' AND status = 'Active' "
                        "ORDER BY date DESC LIMIT 1",
                        (symbol,),
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
                )
                logger.info(f"EtfEngine | close_trade: updated trades row for {bot_id}/{symbol}")
        except Exception as _ct_exc:
            logger.warning(f"EtfEngine | close_trade mirror failed (non-fatal): {_ct_exc}")

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
            logger.warning(f"EtfEngine | reconcile_etf_trades failed (non-fatal): {exc}")

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
        live = next((p for p in live_positions if p["symbol"] == symbol), None)
        if not live:
            return None

        current = live["current_price"]
        entry   = float(db_position["entry_price"])

        # Update trailing stop (ratchet upward)
        self.update_trailing_stop(bot_id, symbol, current, trail_pct)

        # Re-read stop_price after update
        fresh = self.get_db_positions(bot_id)
        db_pos_fresh = next((p for p in fresh if p["symbol"] == symbol), db_position)

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
            scale_qty = qty * 0.333
            if scale_qty > 0:
                if self.close_partial(symbol, scale_qty):
                    self.mark_scaled_out(bot_id, symbol, tier=2)
                    logger.info(f"EtfEngine | TP2 scale-out: {symbol} {scale_qty:.4f} shares")
            return None  # Position still open (partial close)

        # 4. TP1 scale-out
        if self.check_tp1_hit(db_pos_fresh, current):
            qty = float(db_position.get("qty", 0))
            scale_qty = qty * 0.333
            if scale_qty > 0:
                if self.close_partial(symbol, scale_qty):
                    self.mark_scaled_out(bot_id, symbol, tier=1)
                    logger.info(f"EtfEngine | TP1 scale-out: {symbol} {scale_qty:.4f} shares")
            return None  # Position still open (partial close)

        return None  # Hold
