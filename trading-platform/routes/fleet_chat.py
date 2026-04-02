"""Fleet Commander interactive chat routes.

Endpoints:
  POST /fleet-commander/chat         — send a message or quick-action to Gemini
  POST /fleet-commander/chat/approve — accept/decline a pending recommendation
  GET  /fleet-commander/chat/history — paginated conversation log
  GET  /fleet-commander/params       — current Kraken adaptive params for all bots
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from analysis.gemini_auditor import _gemini_api_key, _GEMINI_MODEL
from analysis.fleet_enforcer import (
    BOUNDS, STEPS, BOT_ID_TO_DB_ID,
    _load_current_kraken_params, _write_kraken_params, _clamp, _limit_step,
)
from db.postgres import is_pg_available, get_conn

fleet_chat_router = APIRouter()

_GOOGLE_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

QUICK_ACTIONS = {
    "conservative": {
        "label": "Go Conservative",
        "prompt": (
            "The operator wants the fleet to shift to a CONSERVATIVE posture. "
            "For all Kraken bots, recommend tighter entry thresholds (higher ZSCORE_ENTRY), "
            "tighter stop losses (lower STOP_LOSS_PCT), and smaller trailing stops. "
            "Explain your reasoning based on current fleet data."
        ),
    },
    "aggressive": {
        "label": "Go Aggressive",
        "prompt": (
            "The operator wants the fleet to shift to an AGGRESSIVE posture. "
            "For all Kraken bots, recommend looser entry thresholds (lower ZSCORE_ENTRY), "
            "wider stop losses (higher STOP_LOSS_PCT), and wider trailing stops. "
            "Explain your reasoning based on current fleet data."
        ),
    },
    "tighten_stops": {
        "label": "Tighten Stops",
        "prompt": (
            "The operator wants to tighten stop-loss levels across the Kraken fleet. "
            "Recommend lower STOP_LOSS_PCT and TRAIL_PCT values for bots that currently "
            "have wider stops. Explain which bots need adjustment and why."
        ),
    },
    "best_params": {
        "label": "Activate Best Parameters",
        "prompt": (
            "Analyze all three Kraken bots' recent performance and identify the best-performing "
            "parameter set. Recommend applying similar parameters to the underperforming bots "
            "(within ±1 step of their current values). Explain your analysis."
        ),
    },
    "reset_defaults": {
        "label": "Reset to Defaults",
        "system": True,
    },
    "pause_losing": {
        "label": "Pause Losing Bots",
        "system": True,
    },
}

def _load_bot_defaults() -> dict[str, dict]:
    """Pull factory defaults from kraken-bot/config.py BOT_PROFILES."""
    import importlib.util, pathlib
    cfg_path = pathlib.Path(__file__).resolve().parent.parent.parent / "kraken-bot" / "config.py"
    defaults = {}
    try:
        spec = importlib.util.spec_from_file_location("kraken_config", cfg_path)
        mod = importlib.util.module_from_spec(spec)
        import sys as _sys
        import os as _os
        _orig_argv = _sys.argv
        _orig_bot = _os.environ.get("BOT_ID")
        try:
            _sys.argv = ["config"]
            _os.environ["BOT_ID"] = "davy-jones"
            spec.loader.exec_module(mod)
        finally:
            _sys.argv = _orig_argv
            if _orig_bot is not None:
                _os.environ["BOT_ID"] = _orig_bot
            else:
                _os.environ.pop("BOT_ID", None)

        profiles = getattr(mod, "BOT_PROFILES", {})
        key_map = {"davy-jones": "davy_jones", "blackbeard": "blackbeard", "calypso": "calypso"}
        adaptive_keys = {"ZSCORE_ENTRY", "ZSCORE_EXIT", "STOP_LOSS_PCT", "TRAIL_PCT", "MIN_NET_PROFIT_PCT"}
        for profile_key, our_key in key_map.items():
            p = profiles.get(profile_key, {})
            d = {}
            for k in adaptive_keys:
                if k in p:
                    d[k] = p[k]
            if "ZSCORE_EXIT" not in d:
                d["ZSCORE_EXIT"] = 0.30
            if "TRAIL_PCT" not in d:
                d["TRAIL_PCT"] = 0.05
            if "MIN_NET_PROFIT_PCT" not in d:
                d["MIN_NET_PROFIT_PCT"] = 0.008
            defaults[our_key] = d
    except Exception as exc:
        logger.warning(f"FleetChat | Could not load kraken config.py defaults: {exc}")
        defaults = {
            "davy_jones": {"ZSCORE_ENTRY": 1.0, "ZSCORE_EXIT": 0.30, "STOP_LOSS_PCT": 0.015, "TRAIL_PCT": 0.05, "MIN_NET_PROFIT_PCT": 0.008},
            "blackbeard": {"ZSCORE_ENTRY": 0.8, "ZSCORE_EXIT": 0.30, "STOP_LOSS_PCT": 0.020, "TRAIL_PCT": 0.05, "MIN_NET_PROFIT_PCT": 0.008},
            "calypso": {"ZSCORE_ENTRY": 0.6, "ZSCORE_EXIT": 0.30, "STOP_LOSS_PCT": 0.025, "TRAIL_PCT": 0.05, "MIN_NET_PROFIT_PCT": 0.008},
        }
    return defaults

_BOT_DEFAULTS: dict[str, dict] = _load_bot_defaults()

_CHAT_SYSTEM_PROMPT = """\
You are the FLEET COMMANDER — an AI fleet management assistant for a quantitative trading platform.
You have direct control over 3 Kraken crypto bots (Davy Jones, Blackbeard, Calypso) and advisory
control over Oracle (Alpaca equities — you can veto tickers but Groq manages strategy).
Apex Predator (options) and Navigator (forex) can only be put on HOLD.

PARAMETER BOUNDS (your recommendations MUST stay within these):
ZSCORE_ENTRY:       [0.70, 1.50]  step=0.05
ZSCORE_EXIT:        [0.10, 0.55]  step=0.02
STOP_LOSS_PCT:      [0.008, 0.040] step=0.002
TRAIL_PCT:          [0.030, 0.100] step=0.005
MIN_NET_PROFIT_PCT: [0.006, 0.020] step=0.001

RULES:
- Maximum ±1 step change per parameter per approval cycle
- Always explain your reasoning with specific data
- Be concise but thorough
- When recommending parameter changes, output a JSON block with this format:

```json
{"recommendations": [{"bot_id": "davy_jones", "params": {"ZSCORE_ENTRY": 1.05}, "reasoning": "..."}]}
```

- If no parameter changes are needed, say so clearly
- Respond conversationally but precisely — this is a trading command center
"""


def _ensure_chat_table() -> None:
    if not is_pg_available():
        return
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS fleet_commander_chat (
                        id          TEXT PRIMARY KEY,
                        ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        role        TEXT NOT NULL,
                        content     TEXT NOT NULL,
                        source      TEXT NOT NULL DEFAULT 'user',
                        metadata    JSONB DEFAULT '{}'
                    );
                    CREATE INDEX IF NOT EXISTS idx_fleet_chat_ts ON fleet_commander_chat (ts DESC);
                """)
    except Exception as exc:
        logger.warning(f"FleetChat | Table creation failed: {exc}")


_ensure_chat_table()


def _save_message(role: str, content: str, source: str = "user", metadata: dict | None = None) -> str:
    msg_id = str(uuid.uuid4())
    if not is_pg_available():
        return msg_id
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO fleet_commander_chat (id, role, content, source, metadata)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (msg_id, role, content, source, json.dumps(metadata or {})),
                )
    except Exception as exc:
        logger.warning(f"FleetChat | save_message failed: {exc}")
    return msg_id


def _get_history(limit: int = 50) -> list[dict]:
    if not is_pg_available():
        return []
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, ts, role, content, source, metadata
                       FROM fleet_commander_chat ORDER BY ts DESC LIMIT %s""",
                    (limit,),
                )
                rows = cur.fetchall()
        return [
            {
                "id": r[0], "ts": r[1].isoformat(), "role": r[2],
                "content": r[3], "source": r[4], "metadata": r[5] or {},
            }
            for r in reversed(rows)
        ]
    except Exception as exc:
        logger.warning(f"FleetChat | get_history failed: {exc}")
        return []


async def _get_fleet_context() -> str:
    """Build fleet context using gemini_context_sanitizer for token-safe assembly."""
    from analysis.gemini_context_sanitizer import sanitize_daily_context, estimate_tokens

    raw_data: dict[str, Any] = {}

    for bot_id, db_id in BOT_ID_TO_DB_ID.items():
        params = _load_current_kraken_params(db_id)
        if params:
            raw_data[f"kraken_{bot_id}_params"] = params
            raw_data[f"kraken_{bot_id}_defaults"] = _BOT_DEFAULTS.get(bot_id, {})

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT symbol, side, entry_price, exit_price, pnl_pct, pnl_usd, reason, closed_at, bot_id
                       FROM kraken_trades WHERE closed_at > NOW() - INTERVAL '48 hours'
                       ORDER BY closed_at DESC LIMIT 50"""
                )
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
                if rows:
                    for r in rows:
                        if r.get("closed_at"):
                            r["closed_at"] = r["closed_at"].isoformat()
                    raw_data["recent_kraken_trades"] = rows
    except Exception as exc:
        logger.debug(f"FleetChat | context: kraken_trades query failed: {exc}")

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                for bot_id, db_id in BOT_ID_TO_DB_ID.items():
                    cur.execute(
                        "SELECT equity_usd, position_count, cycle_count, status FROM kraken_heartbeat WHERE id = %s",
                        (db_id,),
                    )
                    hb = cur.fetchone()
                    if hb:
                        raw_data[f"kraken_{bot_id}_heartbeat"] = {
                            "equity": hb[0], "positions": hb[1], "cycles": hb[2], "status": hb[3],
                        }
    except Exception as exc:
        logger.debug(f"FleetChat | context: kraken_heartbeat query failed: {exc}")

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT ticker, side, entry_price, exit_price, pnl_pct, pnl_usd, strategy, closed_at
                       FROM trade_journal WHERE closed_at > NOW() - INTERVAL '48 hours'
                       ORDER BY closed_at DESC LIMIT 20"""
                )
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
                if rows:
                    for r in rows:
                        if r.get("closed_at"):
                            r["closed_at"] = r["closed_at"].isoformat()
                    raw_data["recent_equity_trades"] = rows
    except Exception as exc:
        logger.debug(f"FleetChat | context: trade_journal query failed: {exc}")

    try:
        from forex_db import get_conn as forex_conn
        with forex_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT pair, side, entry_price, current_price, pnl_pct, status
                       FROM forex_positions WHERE status = 'open'
                       ORDER BY opened_at DESC LIMIT 10"""
                )
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
                if rows:
                    raw_data["forex_open_positions"] = rows
    except Exception as exc:
        logger.debug(f"FleetChat | context: forex_positions query failed: {exc}")

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT total_equity, alpaca_equity, kraken_equity,
                              COALESCE(options_equity, 0) AS options_equity,
                              COALESCE(forex_equity, 0) AS forex_equity, ts
                       FROM equity_curve ORDER BY ts DESC LIMIT 1"""
                )
                row = cur.fetchone()
                if row:
                    raw_data["latest_equity_snapshot"] = {
                        "total": float(row[0]) if row[0] else None,
                        "alpaca": float(row[1]) if row[1] else None,
                        "kraken": float(row[2]) if row[2] else None,
                        "options": float(row[3]) if row[3] else None,
                        "forex": float(row[4]) if row[4] else None,
                        "ts": row[5].isoformat() if row[5] else None,
                    }
    except Exception as exc:
        logger.debug(f"FleetChat | context: equity_curve query failed: {exc}")

    context_blocks = ["kraken_trades", "kraken_heartbeat", "equity_trades", "forex", "equity_snapshot"]
    missing = [b for b in context_blocks if not any(b.replace("_", "") in k.replace("_", "") for k in raw_data)]
    if missing:
        raw_data["_context_missing"] = missing
        logger.info(f"FleetChat | context assembly: missing blocks: {missing}")

    if not raw_data:
        return "No fleet data available."

    sanitized = sanitize_daily_context(raw_data)
    tokens = estimate_tokens(sanitized)
    if tokens > 8000:
        sanitized = sanitized[:32000] + "\n[... truncated for chat context ...]"

    return sanitized


async def _call_gemini_chat(messages: list[dict], fleet_context: str) -> str:
    api_key = _gemini_api_key()
    url = f"{_GOOGLE_GEMINI_BASE}/models/{_GEMINI_MODEL}:generateContent"

    contents = []
    for msg in messages[-10:]:
        contents.append({
            "role": "user" if msg["role"] == "user" else "model",
            "parts": [{"text": msg["content"]}],
        })

    body = {
        "system_instruction": {
            "parts": [{"text": _CHAT_SYSTEM_PROMPT + f"\n\nCURRENT FLEET DATA:\n{fleet_context}"}]
        },
        "contents": contents,
        "generationConfig": {
            "maxOutputTokens": 2048,
            "temperature": 0.7,
        },
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            url,
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            json=body,
        )

    if resp.status_code != 200:
        raise RuntimeError(f"Gemini HTTP {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _extract_recommendations(text: str) -> list[dict] | None:
    import re
    match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
    if not match:
        match = re.search(r'(\{"recommendations"\s*:\s*\[.*?\]\s*\})', text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(1))
        recs = parsed.get("recommendations", [])
        if not isinstance(recs, list) or not recs:
            return None
        return recs
    except (json.JSONDecodeError, KeyError):
        return None


def _build_param_snippet() -> str:
    """Build compact per-bot param + W/L snippet for quick-action prompts."""
    lines = []
    for bot_key, db_id in BOT_ID_TO_DB_ID.items():
        params = _load_current_kraken_params(db_id)
        if not params:
            continue
        bot_name = bot_key.replace("_", "-")
        param_str = " ".join(f"{k}={v:.3f}" if "PCT" in k else f"{k}={v:.2f}" for k, v in sorted(params.items()))
        wl_str = ""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT COUNT(*) FILTER (WHERE pnl_pct > 0),
                                  COUNT(*) FILTER (WHERE pnl_pct <= 0),
                                  COALESCE(SUM(pnl_usd), 0)
                           FROM kraken_trades WHERE bot_id = %s
                           AND closed_at > NOW() - INTERVAL '24 hours'""",
                        (bot_name,),
                    )
                    w, l, pnl = cur.fetchone()
                    wl_str = f" | 24h: W={w} L={l} PnL=${pnl:.2f}"
        except Exception:
            pass
        lines.append(f"  {bot_name}: {param_str}{wl_str}")
    return "\n".join(lines) if lines else "No bot data available."


class ChatRequest(BaseModel):
    message: str = ""
    quick_action: str | None = None


class ApproveRequest(BaseModel):
    message_id: str
    approved: bool


@fleet_chat_router.post("/fleet-commander/chat", tags=["Fleet Commander"])
async def fleet_chat(request: ChatRequest) -> dict:
    if request.quick_action:
        action = QUICK_ACTIONS.get(request.quick_action)
        if not action:
            raise HTTPException(400, f"Unknown quick action: {request.quick_action}")

        if request.quick_action == "pause_losing":
            return await _handle_pause_losing()

        if request.quick_action == "reset_defaults":
            return await _handle_reset_defaults()

        param_snippet = _build_param_snippet()
        user_text = f"[Quick Action: {action['label']}]\n{action['prompt']}\n\nCurrent per-bot snapshot:\n{param_snippet}"
    elif request.message.strip():
        user_text = request.message.strip()
    else:
        raise HTTPException(400, "Provide either a message or quick_action")

    user_id = _save_message("user", user_text, source="manual_chat")

    fleet_context = await _get_fleet_context()

    history = _get_history(limit=20)

    try:
        reply_text = await _call_gemini_chat(
            [{"role": m["role"], "content": m["content"]} for m in history],
            fleet_context,
        )
    except Exception as exc:
        logger.error(f"FleetChat | Gemini call failed: {exc}")
        error_reply = f"Fleet Commander is temporarily unavailable: {exc}"
        _save_message("assistant", error_reply, source="system")
        return {"reply": error_reply, "has_recommendations": False, "message_id": user_id}

    recommendations = _extract_recommendations(reply_text)
    metadata: dict[str, Any] = {}
    if recommendations:
        metadata["pending_recommendations"] = recommendations
        metadata["status"] = "pending_approval"

    reply_id = _save_message("assistant", reply_text, source="gemini", metadata=metadata)

    return {
        "reply": reply_text,
        "has_recommendations": bool(recommendations),
        "recommendations": recommendations,
        "message_id": reply_id,
    }


@fleet_chat_router.post("/fleet-commander/chat/approve", tags=["Fleet Commander"])
async def fleet_chat_approve(request: ApproveRequest) -> dict:
    if not is_pg_available():
        raise HTTPException(503, "Database unavailable")

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT metadata FROM fleet_commander_chat WHERE id = %s",
                    (request.message_id,),
                )
                row = cur.fetchone()
    except Exception as exc:
        raise HTTPException(500, f"DB error: {exc}")

    if not row:
        raise HTTPException(404, "Message not found")

    meta = row[0] or {}
    recs = meta.get("pending_recommendations", [])
    if not recs:
        raise HTTPException(400, "No pending recommendations on this message")

    if not request.approved:
        _save_message("user", "[Declined recommendations]", source="manual_chat")
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    meta["status"] = "declined"
                    cur.execute(
                        "UPDATE fleet_commander_chat SET metadata = %s WHERE id = %s",
                        (json.dumps(meta), request.message_id),
                    )
        except Exception:
            pass
        return {"status": "declined", "changes_applied": []}

    changes_applied = []
    changes_failed = []

    for rec in recs:
        bot_id = rec.get("bot_id", "").lower().strip()
        db_id = BOT_ID_TO_DB_ID.get(bot_id)
        if not db_id:
            changes_failed.append({"bot_id": bot_id, "reason": "unknown_bot_id"})
            continue

        current = _load_current_kraken_params(db_id)
        if not current:
            changes_failed.append({"bot_id": bot_id, "reason": "no_existing_params"})
            continue

        new_params = dict(current)
        param_changes = rec.get("params", {})
        applied = {}

        for pname, target in param_changes.items():
            if pname not in BOUNDS:
                continue
            cur_val = current.get(pname)
            if cur_val is None:
                continue
            new_val = _limit_step(cur_val, float(target), pname)
            new_params[pname] = new_val
            applied[pname] = {"before": cur_val, "after": new_val}

        if applied:
            reasoning = rec.get("reasoning", "Manual chat approval")
            ok = _write_kraken_params(db_id, bot_id, new_params, f"manual_chat: {reasoning}")
            if ok:
                changes_applied.append({"bot_id": bot_id, "changes": applied})
            else:
                changes_failed.append({"bot_id": bot_id, "reason": "db_write_failed"})

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                meta["status"] = "approved"
                meta["applied"] = changes_applied
                cur.execute(
                    "UPDATE fleet_commander_chat SET metadata = %s WHERE id = %s",
                    (json.dumps(meta), request.message_id),
                )
    except Exception:
        pass

    summary = f"[Approved] Applied {len(changes_applied)} parameter update(s)"
    if changes_failed:
        summary += f", {len(changes_failed)} failed"
    _save_message("user", summary, source="manual_chat", metadata={"approval": changes_applied})

    return {
        "status": "approved",
        "changes_applied": changes_applied,
        "changes_failed": changes_failed,
    }


@fleet_chat_router.get("/fleet-commander/chat/history", tags=["Fleet Commander"])
async def fleet_chat_history(limit: int = 50) -> dict:
    history = _get_history(limit=min(limit, 200))
    return {"messages": history, "count": len(history)}


@fleet_chat_router.get("/fleet-commander/params", tags=["Fleet Commander"])
async def fleet_params() -> dict:
    result = {}
    for bot_id, db_id in BOT_ID_TO_DB_ID.items():
        params = _load_current_kraken_params(db_id)
        defaults = _BOT_DEFAULTS.get(bot_id, {})
        result[bot_id] = {
            "current": params or defaults,
            "defaults": defaults,
            "bounds": {k: {"min": v[0], "max": v[1], "step": STEPS[k]} for k, v in BOUNDS.items()},
        }
    return {"bots": result}


async def _handle_pause_losing() -> dict:
    if not is_pg_available():
        return {"reply": "Database unavailable — cannot check bot performance.", "has_recommendations": False}

    bot_map = [("davy-jones", "davy_jones"), ("blackbeard", "blackbeard"), ("calypso", "calypso")]
    losing_bots = []
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                for bot_name, profile_key in bot_map:
                    cur.execute(
                        """SELECT COUNT(*) FILTER (WHERE pnl_pct > 0) AS wins,
                                  COUNT(*) FILTER (WHERE pnl_pct <= 0) AS losses,
                                  COALESCE(SUM(pnl_usd), 0) AS total_pnl
                           FROM kraken_trades WHERE bot_id = %s
                           AND closed_at > NOW() - INTERVAL '24 hours'""",
                        (bot_name,),
                    )
                    row = cur.fetchone()
                    if row and row[2] < 0:
                        losing_bots.append(bot_name)
    except Exception as exc:
        logger.warning(f"FleetChat | pause_losing query failed: {exc}")

    if not losing_bots:
        reply = "All Kraken bots are profitable or neutral in the last 24 hours. No bots paused."
        _save_message("user", "[Quick Action: Pause Losing Bots]", source="manual_chat")
        _save_message("assistant", reply, source="system")
        return {"reply": reply, "has_recommendations": False}

    paused = []
    for bid in losing_bots:
        try:
            from routes.kraken import kraken_toggle_auto_trading, KrakenControlRequest
            req = KrakenControlRequest(bot_paused=True)
            result = await kraken_toggle_auto_trading(req, bot_id=bid)
            paused.append(bid)
            logger.info(f"FleetChat | Paused {bid} via /kraken/auto-trading: {result}")
        except Exception as exc:
            logger.warning(f"FleetChat | pause {bid} failed: {exc}")

    reply = f"Paused {len(paused)} losing bot(s): {', '.join(paused)}. They had negative PnL in the last 24h."
    _save_message("user", "[Quick Action: Pause Losing Bots]", source="manual_chat")
    _save_message("assistant", reply, source="system", metadata={"paused_bots": paused})
    return {"reply": reply, "has_recommendations": False, "paused_bots": paused}


async def _handle_reset_defaults() -> dict:
    reset_results = []
    for bot_id, defaults in _BOT_DEFAULTS.items():
        db_id = BOT_ID_TO_DB_ID.get(bot_id)
        if not db_id:
            continue
        current = _load_current_kraken_params(db_id)
        if not current:
            continue

        new_params = dict(current)
        changes = {}
        for pname, default_val in defaults.items():
            cur_val = current.get(pname)
            if cur_val is None:
                continue
            stepped = _limit_step(cur_val, default_val, pname)
            if stepped != cur_val:
                new_params[pname] = stepped
                changes[pname] = {"before": cur_val, "after": stepped, "target_default": default_val}

        if changes:
            ok = _write_kraken_params(db_id, bot_id, new_params, "manual_chat: reset_to_defaults")
            if ok:
                reset_results.append({"bot_id": bot_id, "changes": changes})

    if not reset_results:
        reply = "All bots are already at or within one step of their default parameters."
    else:
        details = []
        for r in reset_results:
            detail_parts = [f"{k}: {v['before']:.4f} → {v['after']:.4f}" for k, v in r["changes"].items()]
            details.append(f"**{r['bot_id']}**: {', '.join(detail_parts)}")
        reply = "Reset parameters one step toward defaults (max ±1 step per cycle):\n" + "\n".join(details)
        reply += "\n\nRun again to continue stepping toward defaults."

    _save_message("user", "[Quick Action: Reset to Defaults]", source="manual_chat")
    _save_message("assistant", reply, source="system", metadata={"reset_results": reset_results})
    return {"reply": reply, "has_recommendations": False, "reset_results": reset_results}
