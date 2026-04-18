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
                    FROM   kraken_trades
                    WHERE  bot_id = %s
                      AND  closed_at >= '2026-04-13 00:00:00+00'
                    ORDER  BY closed_at ASC
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

            wins = [t for t in all_trades if (t.get("pnl_usd") or 0) > 0]
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

                    # All-time trade count and win count (no date filter)
                    _fsc.execute(
                        "SELECT COUNT(*), "
                        "SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) "
                        "FROM kraken_trades WHERE bot_id = %s",
                        (_bid,)
                    )
                    _tr = _fsc.fetchone()
                    if _tr:
                        trades_count = int(_tr[0] or 0)
                        wins_count = int(_tr[1] or 0)

                    # Total PnL = equity - starting (includes unrealized gains from open positions)
                    pnl = eq - starting

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

            # ── Bot #7 Poseidon ────────────────────────────────────────────────
            try:
                ps_eq = 100_000.0
                ps_cash = 0.0
                with _fsconn.cursor() as _psc:
                    _psc.execute("SELECT equity_usd, cash_usd FROM poseidon_portfolio WHERE id = 7")
                    _psr = _psc.fetchone()
                    if _psr:
                        ps_eq = float(_psr[0] or 100_000)
                        ps_cash = float(_psr[1] or 0)
                    _psc.execute(
                        "SELECT COUNT(*), "
                        "SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) "
                        "FROM poseidon_trades"
                    )
                    _ptr = _psc.fetchone()
                    ps_trades = int(_ptr[0] or 0) if _ptr else 0
                    ps_wins   = int(_ptr[1] or 0) if _ptr else 0
                    # Total PnL = equity - starting (includes unrealized from open positions)
                    ps_pnl = ps_eq - 100_000.0
                total_equity += ps_eq
                total_cash   += ps_cash
                total_starting += 100_000.0
                total_trades += ps_trades
                total_wins   += ps_wins
                total_pnl_usd += ps_pnl
                bots_out.append({
                    "bot_id": "poseidon",
                    "display_name": "Poseidon",
                    "equity_usd": round(ps_eq, 2),
                    "cash_usd": round(ps_cash, 2),
                    "starting_balance_usd": 100_000.0,
                    "trades": ps_trades,
                    "wins": ps_wins,
                    "pnl_usd": round(ps_pnl, 2),
                })
            except Exception as _ps_exc:
                logger.warning(f"[fleet-summary] Poseidon read failed: {_ps_exc}")
                total_starting += 100_000.0
                bots_out.append({"bot_id": "poseidon", "display_name": "Poseidon",
                                  "equity_usd": 100_000.0, "cash_usd": 0.0,
                                  "starting_balance_usd": 100_000.0, "trades": 0, "wins": 0, "pnl_usd": 0.0})

            # ── Bot #8 Kraken Current ──────────────────────────────────────────
            try:
                kc_eq = 100_000.0
                kc_cash = 0.0
                with _fsconn.cursor() as _kcc:
                    _kcc.execute("SELECT equity_usd, cash_usd FROM kraken_current_portfolio WHERE id = 8")
                    _kcr = _kcc.fetchone()
                    if _kcr:
                        kc_eq = float(_kcr[0] or 100_000)
                        kc_cash = float(_kcr[1] or 0)
                    _kcc.execute(
                        "SELECT COUNT(*), "
                        "SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) "
                        "FROM kraken_current_trades"
                    )
                    _ktr = _kcc.fetchone()
                    kc_trades = int(_ktr[0] or 0) if _ktr else 0
                    kc_wins   = int(_ktr[1] or 0) if _ktr else 0
                    # Total PnL = equity - starting (includes unrealized from open positions)
                    kc_pnl = kc_eq - 100_000.0
                total_equity += kc_eq
                total_cash   += kc_cash
                total_starting += 100_000.0
                total_trades += kc_trades
                total_wins   += kc_wins
                total_pnl_usd += kc_pnl
                bots_out.append({
                    "bot_id": "kraken-current",
                    "display_name": "Kraken Current",
                    "equity_usd": round(kc_eq, 2),
                    "cash_usd": round(kc_cash, 2),
                    "starting_balance_usd": 100_000.0,
                    "trades": kc_trades,
                    "wins": kc_wins,
                    "pnl_usd": round(kc_pnl, 2),
                })
            except Exception as _kc_exc:
                logger.warning(f"[fleet-summary] KrakenCurrent read failed: {_kc_exc}")
                total_starting += 100_000.0
                bots_out.append({"bot_id": "kraken-current", "display_name": "Kraken Current",
                                  "equity_usd": 100_000.0, "cash_usd": 0.0,
                                  "starting_balance_usd": 100_000.0, "trades": 0, "wins": 0, "pnl_usd": 0.0})

            return {
                "total_equity_usd": round(total_equity, 2),
                "total_cash_usd": round(total_cash, 2),
                "total_starting_usd": round(total_starting, 2),
                "total_trades": total_trades,
                "total_wins": total_wins,
                "total_pnl_usd": round(total_pnl_usd, 2),
                "bot_count": len(bots_out),
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
    strategy_trades = [t for t in recent_trades if t.get("reason") != "rebalance_liquidation"]
    rebalance_trades = [t for t in recent_trades if t.get("reason") == "rebalance_liquidation"]
    wins          = [t for t in strategy_trades if (t.get("pnl_usd") or 0) > 0]
    losses        = [t for t in strategy_trades if (t.get("pnl_usd") or 0) <= 0]
    win_rate      = (len(wins) / len(strategy_trades) * 100) if strategy_trades else None

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
        "calypso": ("Calypso", "a disciplined 24/7 crypto mean-reversion trading AI — a mythical sea goddess who waits for the perfect storm: Z-score ≥2.0 dislocation, VPIN below threshold, and RSI extreme simultaneously, then strikes with market-cap tiered precision sizing and ATR-anchored exits"),
    }
    persona_name, persona_desc = _persona_map.get(bid, ("Kraken Bot", "a 24/7 crypto mean-reversion trading AI"))

    rebalance_note = ""
    if rebalance_trades:
        rebalance_note = (
            f"\nNOTE: {len(rebalance_trades)} trades were closed by operator Force Rebalance "
            f"(not strategy exits). Exclude these from win/loss analysis.\n"
        )

    user_prompt = f"""
{persona_name}'s current open positions (Kraken 24/7 mean-reversion crypto bot, {profile.get('strategy_label', '')} strategy):
{pos_text}

Recent wins (reinforcing behaviour):
{wins_text}

Recent losses (behavioural corrections needed):
{losses_text}
{rebalance_note}
Signal scanner snapshot:
{signal_text}

Statistics: {len(strategy_trades)} strategy trades{f', win rate {win_rate:.0f}%' if win_rate is not None else ''}{f' | {len(rebalance_trades)} force-rebalanced (excluded)' if rebalance_trades else ''}
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
                        FROM   kraken_trades
                        WHERE  bot_id = %s
                          AND  closed_at >= '2026-04-13 00:00:00+00'
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

    strategy_only = [t for t in trades if t.get("reason") != "rebalance_liquidation"]
    rebalance_count = len(trades) - len(strategy_only)

    pnl_list = [t.get("pnl_pct", 0) for t in strategy_only]
    pnl_usd  = [t.get("pnl_usd", 0) for t in strategy_only]
    wins     = [u for u in pnl_usd if u > 0]
    losses   = [u for u in pnl_usd if u <= 0]
    win_rate = (len(wins) / len(strategy_only)) * 100 if strategy_only else 0

    total_pnl_pct_all = sum(t.get("pnl_pct", 0) for t in trades)
    total_pnl_usd_all = sum(t.get("pnl_usd", 0) for t in trades)

    by_symbol: dict[str, dict] = {}
    for t in strategy_only:
        sym = t.get("symbol", "UNKNOWN")
        if sym not in by_symbol:
            by_symbol[sym] = {"trades": 0, "wins": 0, "total_pnl_pct": 0.0, "total_pnl_usd": 0.0}
        by_symbol[sym]["trades"]        += 1
        by_symbol[sym]["total_pnl_pct"] += t.get("pnl_pct", 0)
        by_symbol[sym]["total_pnl_usd"] += t.get("pnl_usd", 0)
        if (t.get("pnl_usd") or 0) > 0:
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
        "total_trades":    len(strategy_only),
        "rebalance_trades": rebalance_count,
        "win_count":       len(wins),
        "loss_count":      len(losses),
        "win_rate_pct":    round(win_rate, 1),
        "total_pnl_pct":   round(sum(pnl_list), 2) if pnl_list else 0,
        "total_pnl_usd":   round(sum(pnl_usd), 2) if pnl_usd else 0,
        "total_pnl_pct_incl_rebalance": round(total_pnl_pct_all, 2),
        "total_pnl_usd_incl_rebalance": round(total_pnl_usd_all, 2),
        "best_trade_pct":  round(max(pnl_list), 2) if pnl_list else 0,
        "worst_trade_pct": round(min(pnl_list), 2) if pnl_list else 0,
        "avg_trade_pct":   round(sum(pnl_list) / len(pnl_list), 2) if pnl_list else 0,
        "by_symbol":       by_symbol,
        "recent_trades":   trades,
        "current_equity":  current_equity,
        "cycle_count":     cycle_count,
        "bot_status":      bot_status,
    }


# ── Stage 6: OHLCV Data Ingestion Endpoints ────────────────────────────────────

@kraken_router.get("/kraken/ohlcv/status", tags=["Kraken Analytics"])
async def kraken_ohlcv_status() -> dict:
    """
    Return current OHLCV data coverage per pair and timeframe.
    Shows how many candles are stored and the date range covered.
    """
    try:
        from analysis.ingest_kraken_ohlcv import get_coverage_status
        coverage = get_coverage_status()
        total_candles = sum(r["total_candles"] for r in coverage)
        return {
            "status": "ok",
            "total_candles": total_candles,
            "coverage": coverage,
            "note": (
                "1d timeframe: ~720 daily candles ≈ 2 years (April 2024 → present). "
                "1h timeframe: ~720 hourly candles ≈ 30 days. "
                "Primary backtest uses 1d data for pre-live-period validation."
            ),
        }
    except Exception as exc:
        logger.error(f"OHLCV Status | Error: {exc}")
        return {"status": "error", "error": str(exc)}


@kraken_router.post("/kraken/ohlcv/ingest", tags=["Kraken Analytics"])
async def kraken_ohlcv_ingest(
    pairs: list[str] | None = None,
    timeframes: list[str] | None = None,
) -> dict:
    """
    Trigger a manual OHLCV data refresh from the Kraken public REST API.
    Fetches daily (1d) and hourly (1h) candles for all 5 configured pairs.

    Optional query params:
      pairs      — subset of pairs to ingest (default: all 5)
      timeframes — subset of timeframes ('1d', '1h') (default: both)
    """
    import asyncio
    try:
        from analysis.ingest_kraken_ohlcv import (
            run_ingest, PAIRS as ALL_PAIRS, TIMEFRAMES as ALL_TFS,
        )

        pairs_cfg = ALL_PAIRS
        tfs_cfg   = ALL_TFS

        if pairs:
            pairs_cfg = [p for p in ALL_PAIRS if p["display"] in pairs]
        if timeframes:
            tfs_cfg = [t for t in ALL_TFS if t["label"] in timeframes]

        logger.info(f"OHLCV | Manual ingest triggered via API — pairs={[p['display'] for p in pairs_cfg]}")
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, lambda: run_ingest(pairs_cfg, tfs_cfg))

        summary = []
        for key, r in results.items():
            if "error" in r:
                summary.append({"key": key, "status": "error", "error": r["error"]})
            else:
                rng = r.get("range")
                summary.append({
                    "key":       key,
                    "status":    "ok",
                    "pair":      r.get("pair"),
                    "timeframe": r.get("timeframe"),
                    "fetched":   r.get("fetched", 0),
                    "inserted":  r.get("inserted", 0),
                    "total":     r.get("total", 0),
                    "from":      rng[0] if rng else None,
                    "to":        rng[1] if rng else None,
                })

        total_inserted = sum(r.get("inserted", 0) for r in results.values() if "error" not in r)
        return {
            "status":         "ok",
            "total_inserted": total_inserted,
            "results":        summary,
        }
    except Exception as exc:
        logger.error(f"OHLCV Ingest | Error: {exc}")
        return {"status": "error", "error": str(exc)}


# ── Stage 6: True Price Backtest Endpoints ────────────────────────────────────

@kraken_router.post("/kraken/backtest/run", tags=["Kraken Analytics"])
async def kraken_backtest_run(bot_id: str | None = None) -> dict:
    """
    Trigger the true price-based backtester immediately.

    Replays historical OHLCV candles through the strategy logic for each bot.
    If historical_prices is empty, data is ingested automatically first.

    Optional:
      bot_id — run for one specific bot (default: all three bots)
    """
    import asyncio
    try:
        from analysis.backtester_kraken import run_backtest, run_all_bots, KRAKEN_BOT_IDS
        loop = asyncio.get_event_loop()

        if bot_id:
            if bot_id not in KRAKEN_BOT_IDS:
                return {"status": "error", "error": f"Unknown bot_id: {bot_id}. Valid: {KRAKEN_BOT_IDS}"}
            logger.info(f"Backtest | Manual run triggered via API for {bot_id}")
            result = await loop.run_in_executor(None, lambda: run_backtest(bot_id))
            results = {bot_id: result}
        else:
            logger.info("Backtest | Manual run triggered via API for all bots")
            results = await loop.run_in_executor(None, run_all_bots)

        summary = {}
        for bid, r in results.items():
            if "error" in r:
                summary[bid] = {"status": "error", "error": r["error"]}
            else:
                summary[bid] = {
                    "status":        "ok",
                    "strategy":      r.get("summary", "")[:120],
                    "sim_trades":    r.get("sim_trades", r.get("n_trades", 0)),
                    "wr_pct":        round(r.get("baseline_wr", 0) * 100, 1),
                    "pf":            r.get("baseline_pf"),
                    "net_pct":       r.get("baseline_net_pct"),
                    "max_dd":        r.get("baseline_max_dd"),
                    "sharpe":        r.get("sharpe_ratio"),
                    "data_from":     r.get("data_from"),
                    "data_to":       r.get("data_to"),
                    "timeframe":     r.get("timeframe_used"),
                    "candles_used":  r.get("candles_used"),
                    "per_pair":      r.get("per_pair_results", {}),
                }

        return {"status": "ok", "results": summary}

    except Exception as exc:
        logger.error(f"Backtest Run | Error: {exc}")
        return {"status": "error", "error": str(exc)}


@kraken_router.get("/kraken/backtest/results", tags=["Kraken Analytics"])
async def kraken_backtest_results(bot_id: str | None = None) -> dict:
    """
    Return the most recent backtest results for all bots (or one specific bot).
    """
    try:
        from analysis.backtester_kraken import get_latest_result, KRAKEN_BOT_IDS

        bots = [bot_id] if bot_id else KRAKEN_BOT_IDS
        results = {}
        for bid in bots:
            r = get_latest_result(bid)
            if r:
                r_out = dict(r)
                for f in ("run_at", "data_from", "data_to"):
                    if r_out.get(f) and hasattr(r_out[f], "isoformat"):
                        r_out[f] = r_out[f].isoformat()
                results[bid] = r_out
            else:
                results[bid] = None

        return {"status": "ok", "results": results}
    except Exception as exc:
        logger.error(f"Backtest Results | Error: {exc}")
        return {"status": "error", "error": str(exc)}
