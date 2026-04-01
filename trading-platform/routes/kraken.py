"""Kraken bot routes: bots, status, fleet-summary, commentary, auto-trading, performance."""

from __future__ import annotations

import asyncio
import json as _json
import os
import time
from pathlib import Path as _Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from loguru import logger

from routes._deps import (
    COMMENTARY_TTL_SECONDS,
    KRAKEN_BOT_PROFILES,
    _kraken_commentary_cache,
    _kraken_commentary_caches,
    _kraken_commentary_round_robin_idx,
    _resolve_bot,
    _persist_commentary_caches,
)

kraken_router = APIRouter()


@kraken_router.get("/kraken/bots", tags=["Kraken Bot"])
async def kraken_bots_list() -> dict:
    return {"bots": KRAKEN_BOT_PROFILES}


@kraken_router.get("/kraken/status", tags=["Kraken Bot"])
async def kraken_status(bot_id: str | None = None) -> dict:
    import psycopg2 as _pg2, psycopg2.extras as _pg2x

    bid, profile = _resolve_bot(bot_id)
    db_id = profile["db_id"]
    display_name = profile["display_name"]
    strategy_label = profile["strategy_label"]

    live_state_file = _Path(f"../kraken-bot/{bid}_live_state.json")
    if not live_state_file.exists() and bid == "davy-jones":
        live_state_file = _Path("../kraken-bot/live_state.json")

    _live_telemetry: dict = {
        "signals":        [],
        "microstructure": {},
        "thinking_text":  "",
        "adaptive_params": {},
    }
    _live_open_positions: list = []
    try:
        if live_state_file.exists():
            _ls = _json.loads(live_state_file.read_text())
            _live_telemetry["signals"]         = _ls.get("signals", [])
            _live_telemetry["microstructure"]  = _ls.get("microstructure", {})
            _live_telemetry["thinking_text"]   = _ls.get("thinking_text", "")
            _live_telemetry["adaptive_params"] = _ls.get("adaptive_params", {})
            _live_open_positions = _ls.get("open_positions", [])
    except Exception:
        pass

    _not_started = {
        "bot_id": bid, "bot_name": display_name, "strategy_label": strategy_label,
        "status": "not_started",
        "last_updated": None, "cycle_count": 0, "total_equity_usd": 0,
        "circuit_breaker": {"active": False, "paused_until": None},
        "position_count": 0, "open_positions": [], "deployed_usd": 0,
        "deployed_pct": 0, "cash_usd": 0, "error": None,
        "recent_trades": [], "paper_summary": None, **_live_telemetry,
    }

    _dburl = os.environ.get("DATABASE_URL")
    if not _dburl:
        return _not_started

    try:
        _pgconn = _pg2.connect(_dburl)
        try:
            with _pgconn.cursor(cursor_factory=_pg2x.RealDictCursor) as _hc:
                _hc.execute("SELECT * FROM kraken_heartbeat WHERE id = %s", (db_id,))
                _hrow = _hc.fetchone()

            if not _hrow:
                return _not_started

            hb = dict(_hrow)
            if hb.get("last_updated"):
                hb["last_updated"] = hb["last_updated"].isoformat()
            if isinstance(hb.get("circuit_breaker"), str):
                hb["circuit_breaker"] = _json.loads(hb["circuit_breaker"])

            cash_usd      = 0.0
            starting      = 100_000.0
            _db_positions: list = []
            with _pgconn.cursor() as _pc:
                _pc.execute(
                    "SELECT starting_balance_usd, cash_usd, positions FROM kraken_portfolio WHERE id = %s",
                    (db_id,)
                )
                _pr = _pc.fetchone()
                if _pr:
                    starting, cash_usd, _pos_raw = _pr
                    if isinstance(_pos_raw, str):
                        _pos_raw = _json.loads(_pos_raw)
                    if isinstance(_pos_raw, dict):
                        for _sym, _pdata in _pos_raw.items():
                            _entry = dict(_pdata)
                            _entry.setdefault("symbol", _sym)
                            _db_positions.append(_entry)
                    elif isinstance(_pos_raw, list):
                        _db_positions = _pos_raw

            open_positions: list = _live_open_positions if _live_open_positions else _db_positions

            with _pgconn.cursor(cursor_factory=_pg2x.RealDictCursor) as _tc:
                _tc.execute(
                    """
                    SELECT symbol, side, entry_price, exit_price, pnl_pct, pnl_usd,
                           fees_usd, reason, closed_at, paper
                    FROM   kraken_trades WHERE bot_id = %s ORDER BY closed_at ASC
                    """,
                    (bid,)
                )
                _all_rows = _tc.fetchall()

            all_trades = []
            for r in _all_rows:
                d = dict(r)
                if d.get("closed_at"):
                    d["closed_at"] = d["closed_at"].isoformat()
                all_trades.append(d)

            wins = [t for t in all_trades if (t.get("pnl_pct") or 0) > 0]
            paper_summary = {
                "starting_balance_usd": starting,
                "cash_usd":             round(cash_usd, 2),
                "total_trades":         len(all_trades),
                "win_count":            len(wins),
                "loss_count":           len(all_trades) - len(wins),
                "all_time_pnl_usd":     round(sum((t.get("pnl_usd") or 0) for t in all_trades), 2),
                "all_time_pnl_pct":     round(sum((t.get("pnl_pct") or 0) for t in all_trades), 2),
            }

            equity       = round(hb.get("equity_usd", 0), 2)
            deployed_usd = equity - cash_usd if equity > cash_usd else 0.0
            deployed_pct = round((deployed_usd / equity) * 100, 1) if equity > 0 else 0.0

            return {
                "bot_id":               bid,
                "bot_name":             display_name,
                "strategy_label":       strategy_label,
                "paper_trading":        hb.get("paper_trading", True),
                "bot_paused":           hb.get("bot_paused", False),
                "status":               hb.get("status", "not_started"),
                "last_updated":         hb.get("last_updated"),
                "cycle_count":          hb.get("cycle_count", 0),
                "total_equity_usd":     equity,
                "position_count":       hb.get("position_count", 0),
                "circuit_breaker":      hb.get("circuit_breaker") or {"active": False, "paused_until": None},
                "error":                hb.get("error"),
                "cash_usd":             round(cash_usd, 2),
                "open_positions":       open_positions,
                "deployed_usd":         round(deployed_usd, 2),
                "deployed_pct":         deployed_pct,
                "deployable_ceiling_pct": 80,
                "cash_reserve_pct":     20,
                "max_positions":        10,
                "recent_trades":        all_trades[-50:],
                "paper_summary":        paper_summary,
                **_live_telemetry,
            }
        finally:
            _pgconn.close()
    except Exception as exc:
        logger.warning(f"[kraken/status] DB read failed: {exc}")
        return {
            "bot_id": bid, "bot_name": display_name, "strategy_label": strategy_label,
            "status": "db_unavailable",
            "last_updated": None, "cycle_count": 0, "total_equity_usd": 0,
            "circuit_breaker": {"active": False, "paused_until": None},
            "position_count": 0, "open_positions": [], "deployed_usd": 0,
            "deployed_pct": 0, "cash_usd": 0, "error": str(exc),
            "recent_trades": [], "paper_summary": None, **_live_telemetry,
        }


@kraken_router.get("/kraken/fleet-summary", tags=["Kraken Bot"])
async def kraken_fleet_summary() -> dict:
    import psycopg2 as _pg2fs, psycopg2.extras as _pg2fsx

    _dburlfs = os.environ.get("DATABASE_URL")
    if not _dburlfs:
        return {"total_equity_usd": 0, "total_cash_usd": 0, "total_starting_usd": 0,
                "total_trades": 0, "total_wins": 0, "total_pnl_usd": 0, "bot_count": 0, "bots": []}

    try:
        _fsconn = _pg2fs.connect(_dburlfs)
        try:
            bots_out = []
            total_equity = 0.0
            total_cash = 0.0
            total_starting = 0.0
            total_trades = 0
            total_wins = 0
            total_pnl_usd = 0.0

            for _bid, _prof in KRAKEN_BOT_PROFILES.items():
                _dbid = _prof["db_id"]
                eq = 0.0
                cash = 0.0
                starting = 100_000.0
                trades_count = 0
                wins_count = 0
                pnl = 0.0

                with _fsconn.cursor() as _fsc:
                    _fsc.execute("SELECT equity_usd FROM kraken_heartbeat WHERE id = %s", (_dbid,))
                    _hr = _fsc.fetchone()
                    if _hr:
                        eq = float(_hr[0] or 0)

                    _fsc.execute("SELECT starting_balance_usd, cash_usd FROM kraken_portfolio WHERE id = %s", (_dbid,))
                    _pr = _fsc.fetchone()
                    if _pr:
                        starting = float(_pr[0] or 100_000)
                        cash = float(_pr[1] or 0)

                    _fsc.execute(
                        "SELECT COUNT(*), "
                        "SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END), "
                        "COALESCE(SUM(pnl_usd), 0) "
                        "FROM kraken_trades WHERE bot_id = %s",
                        (_bid,)
                    )
                    _tr = _fsc.fetchone()
                    if _tr:
                        trades_count = int(_tr[0] or 0)
                        wins_count = int(_tr[1] or 0)
                        pnl = float(_tr[2] or 0)

                total_equity += eq
                total_cash += cash
                total_starting += starting
                total_trades += trades_count
                total_wins += wins_count
                total_pnl_usd += pnl

                bots_out.append({
                    "bot_id": _bid,
                    "display_name": _prof["display_name"],
                    "equity_usd": round(eq, 2),
                    "cash_usd": round(cash, 2),
                    "starting_balance_usd": round(starting, 2),
                    "trades": trades_count,
                    "wins": wins_count,
                    "pnl_usd": round(pnl, 2),
                })

            return {
                "total_equity_usd": round(total_equity, 2),
                "total_cash_usd": round(total_cash, 2),
                "total_starting_usd": round(total_starting, 2),
                "total_trades": total_trades,
                "total_wins": total_wins,
                "total_pnl_usd": round(total_pnl_usd, 2),
                "bot_count": len(KRAKEN_BOT_PROFILES),
                "bots": bots_out,
            }
        finally:
            _fsconn.close()
    except Exception as exc:
        logger.warning(f"[kraken/fleet-summary] DB read failed: {exc}")
        return {"total_equity_usd": 0, "total_cash_usd": 0, "total_starting_usd": 0,
                "total_trades": 0, "total_wins": 0, "total_pnl_usd": 0,
                "bot_count": 0, "bots": [], "error": str(exc)}


@kraken_router.get("/kraken/commentary", tags=["Kraken Bot"])
async def kraken_commentary(force: bool = False, bot_id: str | None = None) -> dict:
    import routes._deps as _deps

    bid, profile = _resolve_bot(bot_id)
    db_id = profile["db_id"]
    display_name = profile["display_name"]

    bot_cache = _deps._kraken_commentary_caches.get(bid, {"text": None, "generated_at": None, "ts": 0})

    now = time.time()
    cache_age = now - bot_cache["ts"]

    if not force and bot_cache["text"] and cache_age < COMMENTARY_TTL_SECONDS:
        return {
            "bot_id": bid,
            "commentary": bot_cache["text"],
            "generated_at": bot_cache["generated_at"],
            "cached": True,
            "cache_age_seconds": int(cache_age),
        }

    from analysis.groq_budget import budget as _groq_budget
    if not _groq_budget.can_call_commentary("kraken", force=force):
        if bot_cache["text"]:
            return {
                "bot_id": bid,
                "commentary": bot_cache["text"],
                "generated_at": bot_cache["generated_at"],
                "cached": True,
                "cache_age_seconds": int(cache_age),
                "throttled": True,
                "budget_exhausted": _groq_budget.budget_exhausted(),
            }
        _exhausted = _groq_budget.budget_exhausted()
        return {
            "bot_id": bid,
            "commentary": "AI narrative paused — daily token budget reached. Trades are running normally; all entry/exit decisions are purely algorithmic (Z-score, RSI, VPIN) and never depend on this commentary. Narrative resumes tomorrow at midnight UTC.",
            "generated_at": None,
            "cached": False,
            "cache_age_seconds": 0,
            "throttled": True,
            "budget_exhausted": _exhausted,
        }

    bot_ids_list = list(KRAKEN_BOT_PROFILES.keys())
    if not force:
        rr_bot = bot_ids_list[_deps._kraken_commentary_round_robin_idx % len(bot_ids_list)]
        if bid != rr_bot and bot_cache["text"]:
            return {
                "bot_id": bid,
                "commentary": bot_cache["text"],
                "generated_at": bot_cache["generated_at"],
                "cached": True,
                "cache_age_seconds": int(cache_age),
                "round_robin_skip": True,
            }

    import psycopg2 as _pg2c, psycopg2.extras as _pg2cx
    kdata: dict = {}
    recent_trades: list[dict] = []

    _dburl = os.environ.get("DATABASE_URL")
    if _dburl:
        try:
            _kcpgconn = _pg2c.connect(_dburl)
            try:
                with _kcpgconn.cursor(cursor_factory=_pg2cx.RealDictCursor) as _kcc:
                    _kcc.execute("SELECT * FROM kraken_heartbeat WHERE id = %s", (db_id,))
                    _khr = _kcc.fetchone()
                    if _khr:
                        kdata = {
                            "status":           _khr["status"],
                            "cycle_count":      _khr["cycle_count"],
                            "total_equity_usd": _khr["equity_usd"],
                            "open_positions":   [],
                        }

                with _kcpgconn.cursor(cursor_factory=_pg2cx.RealDictCursor) as _kct:
                    _kct.execute(
                        """
                        SELECT symbol, side, entry_price, exit_price, pnl_pct, pnl_usd,
                               fees_usd, reason, closed_at, paper
                        FROM   kraken_trades WHERE bot_id = %s ORDER BY closed_at ASC
                        """,
                        (bid,)
                    )
                    for _r in _kct.fetchall():
                        _d = dict(_r)
                        if _d.get("closed_at"):
                            _d["closed_at"] = _d["closed_at"].isoformat()
                        recent_trades.append(_d)
            finally:
                _kcpgconn.close()
        except Exception as exc:
            logger.debug(f"Kraken commentary: DB read failed: {exc}")

    if not kdata:
        return {
            "bot_id": bid,
            "commentary": f"{display_name} is still getting started — bot hasn't run yet. Check back shortly.",
            "generated_at": None,
            "cached": False,
            "cache_age_seconds": 0,
            "unavailable": True,
        }

    _lsf = _Path(f"../kraken-bot/{bid}_live_state.json")
    if not _lsf.exists() and bid == "davy-jones":
        _lsf = _Path("../kraken-bot/live_state.json")
    _live: dict = {}
    try:
        if _lsf.exists():
            _live = _json.loads(_lsf.read_text())
    except Exception:
        pass

    positions     = _live.get("open_positions", kdata.get("open_positions", []))
    signals       = _live.get("signals", kdata.get("signals", []))
    wins          = [t for t in recent_trades if t.get("pnl_pct", 0) > 0]
    losses        = [t for t in recent_trades if t.get("pnl_pct", 0) <= 0]
    win_rate      = (len(wins) / len(recent_trades) * 100) if recent_trades else None

    pos_text = "\n".join(
        f"  {p.get('side','').upper()} {p['symbol']}: "
        f"entry ${p.get('entry_price', 0):.4f}, now ${p.get('current_price', 0):.4f}, "
        f"P&L {p.get('pnl_pct', 0):+.2f}%"
        for p in positions
    ) or "  (no open positions)"

    wins_text = "\n".join(
        f"  WIN: {t['symbol']} {t.get('pnl_pct', 0):+.2f}% ({t.get('side', '')})"
        for t in wins[-3:]
    ) or "  (none yet)"

    losses_text = "\n".join(
        f"  LOSS: {t['symbol']} {t.get('pnl_pct', 0):+.2f}% ({t.get('side', '')})"
        for t in losses[-3:]
    ) or "  (none yet)"

    signal_text = "\n".join(
        f"  {s['symbol']}: RSI={s.get('rsi', 0):.1f} Z={s.get('z_score', 0):+.2f} → {s.get('signal_type', 'watching')}"
        for s in signals[:6]
    ) or "  (scanning markets)"

    try:
        from data.sentiment import get_sentiment
        sent = get_sentiment()
        cfg  = sent.get("crypto_fear_greed", {})
        sentiment_line = f"Crypto Fear&Greed: {cfg.get('value','?')} ({cfg.get('label','?')})"
    except Exception:
        sentiment_line = ""

    _persona_map = {
        "davy-jones": ("Davy Jones", "a relentless 24/7 crypto mean-reversion trading AI with the soul of a seasoned sailor who reads market currents like ocean tides"),
        "blackbeard": ("Blackbeard", "an aggressive 24/7 crypto mean-reversion trading AI who attacks weak signals like a pirate raiding merchant ships — tight entry thresholds, higher risk tolerance, bigger positions"),
        "calypso": ("Calypso", "the most aggressive 24/7 crypto mean-reversion trading AI — a mythical sea goddess who bends markets to her will with the tightest entry thresholds, smallest cash reserves, and maximum position sizing"),
    }
    persona_name, persona_desc = _persona_map.get(bid, ("Kraken Bot", "a 24/7 crypto mean-reversion trading AI"))

    user_prompt = f"""
{persona_name}'s current open positions (Kraken 24/7 mean-reversion crypto bot, {profile.get('strategy_label', '')} strategy):
{pos_text}

Recent wins (reinforcing behaviour):
{wins_text}

Recent losses (behavioural corrections needed):
{losses_text}

Signal scanner snapshot:
{signal_text}

Statistics: {len(recent_trades)} total trades{f', win rate {win_rate:.0f}%' if win_rate is not None else ''}
Equity: ${kdata.get('total_equity_usd', 0):,.2f} | Deployed: {kdata.get('deployed_pct', 0):.0f}% of {kdata.get('deployable_ceiling_pct', 80)}% ceiling
Cycle #{kdata.get('cycle_count', 0)} | Cash reserve: {kdata.get('cash_reserve_pct', 20)}%
{sentiment_line}
"""

    system_prompt = (
        f"You are '{persona_name}' — {persona_desc}. In exactly 3 punchy sentences: "
        "(1) your sharpest read on the current crypto signals and any open positions, "
        "(2) one concrete learning from your recent wins or losses, "
        "(3) one specific behavioural adjustment you're making going forward. "
        "Reference specific coin names, RSI levels, or Z-scores when available. "
        "Direct, confident, nautical flair optional. Plain text only, no markdown."
    )

    def _blocking_call() -> tuple[str, int]:
        from groq import Groq
        from config.settings import settings as _settings
        client = Groq(api_key=_settings.groq_api_key)
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.72,
            max_tokens=180,
        )
        tokens = resp.usage.total_tokens if resp.usage else 0
        return resp.choices[0].message.content.strip(), tokens

    try:
        loop = asyncio.get_event_loop()
        commentary, tokens_used = await loop.run_in_executor(None, _blocking_call)
        _groq_budget.consume(tokens_used, call_type="commentary")
        if not force:
            _groq_budget.record_commentary_call("kraken")
            _deps._kraken_commentary_round_robin_idx += 1
        from datetime import datetime, timezone
        generated_at = datetime.now(timezone.utc).isoformat()
        new_cache = {"text": commentary, "generated_at": generated_at, "ts": now}
        _deps._kraken_commentary_caches[bid] = new_cache
        if bid == "davy-jones":
            _deps._kraken_commentary_cache.update(new_cache)
        _persist_commentary_caches()
        logger.info(f"Kraken AI commentary regenerated for {bid} (force={force}, tokens={tokens_used})")
        return {"bot_id": bid, "commentary": commentary, "generated_at": generated_at, "cached": False, "cache_age_seconds": 0}
    except Exception as exc:
        logger.error(f"Kraken AI commentary generation failed for {bid}: {exc}")
        bot_cache["ts"] = now - COMMENTARY_TTL_SECONDS + 300
        _deps._kraken_commentary_caches[bid] = bot_cache
        if bot_cache["text"]:
            return {
                "bot_id": bid,
                "commentary": bot_cache["text"],
                "generated_at": bot_cache["generated_at"],
                "cached": True,
                "cache_age_seconds": int(cache_age),
                "error": str(exc),
            }
        return {
            "bot_id": bid,
            "commentary": f"{persona_name}'s AI is resting — daily token limit reached. The seas will clear by tomorrow.",
            "generated_at": None,
            "cached": False,
            "cache_age_seconds": 0,
            "error": str(exc),
            "unavailable": True,
        }


@kraken_router.get("/kraken/auto-trading", tags=["Kraken Bot"])
async def kraken_auto_trading_status(bot_id: str | None = None) -> dict:
    bid, _ = _resolve_bot(bot_id)
    ctrl = _Path(f"../kraken-bot/{bid}_control.json")
    if not ctrl.exists() and bid == "davy-jones":
        ctrl = _Path("../kraken-bot/control.json")
    if not ctrl.exists():
        return {"bot_id": bid, "bot_paused": False}
    try:
        return {"bot_id": bid, "bot_paused": bool(_json.loads(ctrl.read_text()).get("bot_paused", False))}
    except Exception:
        return {"bot_id": bid, "bot_paused": False}


class KrakenControlRequest(BaseModel):
    bot_paused: bool


@kraken_router.post("/kraken/auto-trading", tags=["Kraken Bot"])
async def kraken_toggle_auto_trading(request: KrakenControlRequest, bot_id: str | None = None) -> dict:
    bid, _ = _resolve_bot(bot_id)
    ctrl = _Path(f"../kraken-bot/{bid}_control.json")
    ctrl.write_text(_json.dumps({"bot_paused": request.bot_paused}, indent=2))
    logger.info(f"Kraken bot {bid} {'PAUSED' if request.bot_paused else 'RESUMED'} via dashboard toggle")
    return {"bot_id": bid, "bot_paused": request.bot_paused, "message": f"Kraken bot {bid} paused" if request.bot_paused else f"Kraken bot {bid} resumed"}


@kraken_router.get("/kraken/performance", tags=["Kraken Bot"])
async def kraken_performance(bot_id: str | None = None) -> dict:
    import psycopg2 as _pg2, psycopg2.extras as _pg2x

    bid, profile = _resolve_bot(bot_id)
    db_id = profile["db_id"]

    empty: dict = {
        "bot_id":          bid,
        "data_source":     "postgresql:kraken_trades",
        "exchange":        "Kraken (crypto, independent from Alpaca)",
        "has_data":        False,
        "total_trades":    0,
        "win_count":       0,
        "loss_count":      0,
        "win_rate_pct":    None,
        "total_pnl_pct":   None,
        "total_pnl_usd":   None,
        "best_trade_pct":  None,
        "worst_trade_pct": None,
        "avg_trade_pct":   None,
        "by_symbol":       {},
        "recent_trades":   [],
        "current_equity":  0,
        "cycle_count":     0,
        "bot_status":      "not_started",
    }

    trades: list[dict] = []
    current_equity = 0
    cycle_count    = 0
    bot_status     = "not_started"

    _dburl = os.environ.get("DATABASE_URL")
    if _dburl:
        try:
            _pgconn = _pg2.connect(_dburl)
            try:
                with _pgconn.cursor(cursor_factory=_pg2x.RealDictCursor) as _tc:
                    _tc.execute(
                        """
                        SELECT symbol, side, entry_price, exit_price, pnl_pct, pnl_usd,
                               fees_usd, reason, closed_at, paper
                        FROM   kraken_trades WHERE bot_id = %s
                        ORDER  BY closed_at ASC
                        """,
                        (bid,)
                    )
                    for r in _tc.fetchall():
                        d = dict(r)
                        if d.get("closed_at"):
                            d["closed_at"] = d["closed_at"].isoformat()
                        trades.append(d)

                with _pgconn.cursor() as _hc:
                    _hc.execute(
                        "SELECT equity_usd, cycle_count, status FROM kraken_heartbeat WHERE id = %s",
                        (db_id,)
                    )
                    _hr = _hc.fetchone()
                    if _hr:
                        current_equity = _hr[0] or 0
                        cycle_count    = _hr[1] or 0
                        bot_status     = _hr[2] or "not_started"
            finally:
                _pgconn.close()
        except Exception as exc:
            logger.warning(f"[kraken/performance] DB read failed: {exc}")
            empty["bot_status"]     = bot_status
            empty["current_equity"] = current_equity
            empty["cycle_count"]    = cycle_count
            return empty

    if not trades:
        empty["bot_status"]     = bot_status
        empty["current_equity"] = current_equity
        empty["cycle_count"]    = cycle_count
        return empty

    pnl_list = [t.get("pnl_pct", 0) for t in trades]
    pnl_usd  = [t.get("pnl_usd", 0) for t in trades]
    wins     = [p for p in pnl_list if p > 0]
    losses   = [p for p in pnl_list if p <= 0]
    win_rate = (len(wins) / len(trades)) * 100 if trades else 0

    by_symbol: dict[str, dict] = {}
    for t in trades:
        sym = t.get("symbol", "UNKNOWN")
        if sym not in by_symbol:
            by_symbol[sym] = {"trades": 0, "wins": 0, "total_pnl_pct": 0.0, "total_pnl_usd": 0.0}
        by_symbol[sym]["trades"]        += 1
        by_symbol[sym]["total_pnl_pct"] += t.get("pnl_pct", 0)
        by_symbol[sym]["total_pnl_usd"] += t.get("pnl_usd", 0)
        if (t.get("pnl_pct") or 0) > 0:
            by_symbol[sym]["wins"] += 1

    for sym in by_symbol:
        n = by_symbol[sym]["trades"]
        by_symbol[sym]["win_rate_pct"]  = round((by_symbol[sym]["wins"] / n) * 100, 1) if n else 0
        by_symbol[sym]["total_pnl_pct"] = round(by_symbol[sym]["total_pnl_pct"], 2)
        by_symbol[sym]["total_pnl_usd"] = round(by_symbol[sym]["total_pnl_usd"], 2)

    return {
        "bot_id":          bid,
        "data_source":     "postgresql:kraken_trades",
        "exchange":        "Kraken (crypto, independent from Alpaca)",
        "has_data":        True,
        "total_trades":    len(trades),
        "win_count":       len(wins),
        "loss_count":      len(losses),
        "win_rate_pct":    round(win_rate, 1),
        "total_pnl_pct":   round(sum(pnl_list), 2),
        "total_pnl_usd":   round(sum(pnl_usd), 2),
        "best_trade_pct":  round(max(pnl_list), 2),
        "worst_trade_pct": round(min(pnl_list), 2),
        "avg_trade_pct":   round(sum(pnl_list) / len(pnl_list), 2),
        "by_symbol":       by_symbol,
        "recent_trades":   trades,
        "current_equity":  current_equity,
        "cycle_count":     cycle_count,
        "bot_status":      bot_status,
    }
