"""Fleet Commander interactive chat routes.

Endpoints:
  POST /fleet-commander/chat         — send a message or quick-action to Gemini
  POST /fleet-commander/chat/approve — accept/decline a pending recommendation
  GET  /fleet-commander/chat/history — paginated conversation log
  GET  /fleet-commander/params       — current Kraken adaptive params for all bots
  POST /fleet-commander/code-audit   — crawl monorepo source, send to Gemini, return Replit prompts
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from core.bot_registry import display_label

from analysis.gemini_auditor import (
    _gemini_api_key,
    _gemini_base_url,
    _GEMINI_MODEL,
    _is_daily_quota_error,
    _gemini_retry_wait,
)
# fleet_enforcer imports — used for MANUAL operator-approved parameter writes via chat UI only.
# Automatic enforcement in run_fleet_commander() is permanently disabled.
# This import path remains intentionally active for human-in-the-loop overrides.
from analysis.fleet_enforcer import (
    BOUNDS, STEPS, BOT_ID_TO_DB_ID, FEE_FLOOR,
    _load_current_kraken_params, _write_kraken_params, _clamp, _limit_step,
)
from db.postgres import is_pg_available, get_conn

fleet_chat_router = APIRouter()

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
            "Perform a full diagnostic of all three Kraken bots. For each bot: "
            "1) Identify shortcomings (poor win rate, excessive drawdown, bad entry/exit timing). "
            "2) Compare parameters against the best-performing bot's config. "
            "3) Propose specific parameter fixes for underperforming bots "
            "(within ±1 step of their current values per approval cycle). "
            "Explain your reasoning for each proposed change."
        ),
    },
    "reset_defaults": {
        "label": "Reset to Defaults",
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
            _os.environ["BOT_ID"] = "oracle"
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
control over __ORACLE_DISPLAY_LABEL__ (Alpaca equities — you can veto tickers but Groq manages strategy).
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
""".replace("__ORACLE_DISPLAY_LABEL__", display_label("oracle"))




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
                    """SELECT symbol AS ticker, side, entry_price, exit_price, pnl_pct, pnl_usd,
                              NULL::text AS strategy, closed_at
                       FROM kraken_trades WHERE closed_at > NOW() - INTERVAL '48 hours'
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
                    """SELECT SUM(equity_usd)::DOUBLE PRECISION AS total_equity,
                              NULL::DOUBLE PRECISION AS alpaca_equity,
                              NULL::DOUBLE PRECISION AS kraken_equity,
                              NULL::DOUBLE PRECISION AS options_equity,
                              NULL::DOUBLE PRECISION AS forex_equity,
                              MAX(snapshot_ts) AS ts,
                              'fleet_equity_snapshots'::TEXT AS source
                       FROM fleet_equity_snapshots
                       WHERE bot_id IN ('oracle', 'spy_qqq_trend', 'jerome_macro')
                         AND snapshot_ts = (
                             SELECT MAX(snapshot_ts)
                             FROM fleet_equity_snapshots
                             WHERE bot_id IN ('oracle', 'spy_qqq_trend', 'jerome_macro')
                         )"""
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
                        "source": row[6] if row[6] else "pipeline",
                    }
    except Exception as exc:
        logger.debug(f"FleetChat | context: equity_snapshots query failed: {exc}")

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT ts, pool, bot_id, amount_usd, reason
                       FROM capital_injections
                       ORDER BY ts DESC LIMIT 20"""
                )
                cols = [d[0] for d in cur.description]
                cap_rows = [dict(zip(cols, r)) for r in cur.fetchall()]
                if cap_rows:
                    for r in cap_rows:
                        if r.get("ts"):
                            r["ts"] = r["ts"].isoformat()
                    reset_events = [r for r in cap_rows if "EQUITY_RESET" in (r.get("reason") or "")]
                    other_events  = [r for r in cap_rows if "EQUITY_RESET" not in (r.get("reason") or "")]
                    raw_data["capital_events_WARNING"] = (
                        "IMPORTANT: The following capital events are OPERATOR ACTIONS, "
                        "not trading gains/losses. Exclude them from P&L analysis."
                    )
                    if reset_events:
                        raw_data["equity_baseline_resets"] = [
                            {
                                "date": r["ts"][:10],
                                "bot": r["bot_id"],
                                "pool": r["pool"],
                                "adjustment_usd": float(r["amount_usd"] or 0),
                                "explanation": r["reason"],
                            }
                            for r in reset_events
                        ]
                    if other_events:
                        raw_data["other_capital_events"] = [
                            {
                                "date": r["ts"][:10],
                                "bot": r["bot_id"],
                                "pool": r["pool"],
                                "amount_usd": float(r["amount_usd"] or 0),
                                "reason": r["reason"],
                            }
                            for r in other_events
                        ]
    except Exception as exc:
        logger.debug(f"FleetChat | context: capital_injections query failed: {exc}")

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
    url = f"{_gemini_base_url()}/models/{_GEMINI_MODEL}:generateContent"

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

    _MAX_RETRIES = 3
    for attempt in range(_MAX_RETRIES + 1):
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                url,
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
                json=body,
            )

        if resp.status_code == 200:
            break

        if _is_daily_quota_error(resp.status_code, resp.text):
            raise RuntimeError(
                "Gemini daily quota reached — Fleet Commander will be back online "
                "tomorrow. Your Google API free tier renews at midnight Pacific."
            )

        if resp.status_code == 429 and attempt < _MAX_RETRIES:
            wait = _gemini_retry_wait(attempt)
            logger.warning(
                f"FleetChat | Gemini rate-limited (attempt {attempt + 1}/{_MAX_RETRIES}), "
                f"retrying in {wait:.0f}s…"
            )
            await asyncio.sleep(wait)
            continue

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
                        """SELECT COUNT(*) FILTER (WHERE pnl_usd > 0),
                                  COUNT(*) FILTER (WHERE pnl_usd <= 0),
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
        exc_str = str(exc)
        if "daily quota" in exc_str.lower() or "quota reached" in exc_str.lower():
            error_reply = exc_str
        else:
            error_reply = f"Fleet Commander is temporarily unavailable — please try again shortly."
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
            if pname == "MIN_NET_PROFIT_PCT" and new_val < FEE_FLOOR:
                new_val = round(FEE_FLOOR, 6)
            new_params[pname] = new_val
            applied[pname] = {"before": cur_val, "after": new_val}

        if applied:
            reasoning = rec.get("reasoning", "Manual chat approval")
            logger.warning(
                "FleetChat | Operator-approved parameter write via chat UI — "
                "this bypasses automatic enforcement guards. "
                "Verify recommended values before approving."
            )
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
            if pname == "MIN_NET_PROFIT_PCT" and stepped < FEE_FLOOR:
                stepped = round(FEE_FLOOR, 6)
            if stepped != cur_val:
                new_params[pname] = stepped
                changes[pname] = {"before": cur_val, "after": stepped, "target_default": default_val}

        if changes:
            logger.warning(
                "FleetChat | Operator-approved parameter write via chat UI — "
                "this bypasses automatic enforcement guards. "
                "Verify recommended values before approving."
            )
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


# ---------------------------------------------------------------------------
# Code Audit — crawl monorepo source, review with Gemini, return Replit prompts
# ---------------------------------------------------------------------------

_CODE_AUDIT_CACHE_PATH = pathlib.Path("/tmp/fleet_code_audit_latest.json")

_AUDIT_EXTENSIONS = {".py", ".ts", ".tsx", ".js"}
_AUDIT_CONFIG_FILES = {
    "pyproject.toml", "package.json", "tsconfig.json", "tsconfig.base.json",
    "pnpm-workspace.yaml", ".env.example",
}
_AUDIT_SKIP_DIRS = {
    "node_modules", "__pycache__", ".git", "dist", "build", ".next", "coverage",
    "attached_assets", "data", "screenshots", "sedwfJKhP", ".venv", "venv",
    ".local",
}
_AUDIT_SKIP_PATTERNS = {
    ".min.js", ".min.css", ".map", ".lock", ".csv", ".png", ".jpg", ".jpeg",
    ".gif", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".eot",
}

_MAX_FILE_BYTES = 60_000
_CHUNK_CHARS = 700_000

_CODE_AUDIT_CHUNK_SYSTEM_PROMPT = """\
You are a senior software engineer performing a code audit of a quantitative trading platform monorepo.
Review the provided source files (chunk {chunk_num} of {total_chunks}) and identify real problems —
security vulnerabilities, performance bugs, architectural weaknesses, and missing error handling.

OUTPUT FORMAT — return a JSON array of finding objects only. No other text.

[
  {{
    "severity": "critical|high|medium|low",
    "category": "Security|Performance|Bug|Architecture|Error Handling|Code Quality|Testing",
    "title": "Short title (≤ 10 words)",
    "file": "relative/path/to/file.py",
    "prompt": "Complete Replit agent instruction including file path and exact change needed."
  }}
]

Rules:
- Each prompt must be self-contained and actionable immediately by a Replit agent.
- Include the exact file path in every prompt field.
- Return ONLY real, high-impact issues. No trivial style suggestions.
- Return an empty array [] if you find no noteworthy issues in this chunk.
- Return valid JSON only — no markdown, no extra text.
"""

_CODE_AUDIT_SYNTHESIS_PROMPT = """\
You are a senior software engineer. Below are raw code audit findings from multiple passes over a
quantitative trading platform monorepo. Deduplicate, rank by severity, and produce the final report.

OUTPUT FORMAT — respond in exactly this structure:

Start with: "I found N issues across the full codebase. Here are your Replit prompts to fix them:"

Then for each finding (ordered critical → high → medium → low):

**#N — [Category] Short title**
> "Complete Replit agent instruction including the file path and exact change needed."

Rules:
- Remove exact duplicates, keep the most informative description of near-duplicates.
- Aim for 5–15 total findings. Drop low-value items if there are too many.
- Do not add findings that were not in the input.
- Output only the formatted list. No other commentary.

RAW FINDINGS:
{findings_json}
"""


def _collect_source_files(repo_root: pathlib.Path) -> list[tuple[str, str]]:
    """Walk the entire monorepo and collect (rel_path, content) for all relevant source files.

    Files larger than _MAX_FILE_BYTES are included but truncated at that limit.
    ALL eligible files are collected — no total-size cap is enforced here; chunking
    is handled by the caller (_build_audit_chunks).
    """
    files: list[tuple[str, str]] = []

    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in _AUDIT_SKIP_DIRS and not d.startswith(".")
        )

        rel_dir = pathlib.Path(dirpath).relative_to(repo_root)

        for fname in sorted(filenames):
            fpath = pathlib.Path(dirpath) / fname
            rel_path = str(rel_dir / fname)

            suffix = fpath.suffix.lower()
            skip = any(rel_path.endswith(p) for p in _AUDIT_SKIP_PATTERNS)
            if skip:
                continue

            is_source = suffix in _AUDIT_EXTENSIONS
            is_config = fname in _AUDIT_CONFIG_FILES

            if not is_source and not is_config:
                continue

            try:
                raw = fpath.read_bytes()
                if len(raw) > _MAX_FILE_BYTES:
                    content = raw[:_MAX_FILE_BYTES].decode("utf-8", errors="replace") + "\n[... file truncated at 60KB ...]"
                else:
                    content = raw.decode("utf-8", errors="replace")
            except Exception:
                continue

            files.append((rel_path, content))

    return files


def _build_audit_chunks(files: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    """Split file list into chunks that each fit within _CHUNK_CHARS."""
    chunks: list[list[tuple[str, str]]] = []
    current_chunk: list[tuple[str, str]] = []
    current_size = 0

    for rel_path, content in files:
        entry_size = len(rel_path) + len(content) + 30
        if current_chunk and current_size + entry_size > _CHUNK_CHARS:
            chunks.append(current_chunk)
            current_chunk = []
            current_size = 0
        current_chunk.append((rel_path, content))
        current_size += entry_size

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def _build_chunk_prompt(files: list[tuple[str, str]], chunk_num: int, total_chunks: int) -> str:
    system = _CODE_AUDIT_CHUNK_SYSTEM_PROMPT.format(chunk_num=chunk_num, total_chunks=total_chunks)
    parts = [
        f"Audit chunk {chunk_num}/{total_chunks}. "
        "Review these source files and return a JSON array of findings:\n\n"
    ]
    for rel_path, content in files:
        parts.append(f"--- FILE: {rel_path} ---\n{content}\n\n")
    return system, "".join(parts)


async def _call_gemini_chunk_audit(system_prompt: str, user_prompt: str) -> list[dict]:
    api_key = _gemini_api_key()
    url = f"{_gemini_base_url()}/models/{_GEMINI_MODEL}:generateContent"

    body = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"maxOutputTokens": 4096, "temperature": 0.2},
    }

    _MAX_RETRIES = 3
    for attempt in range(_MAX_RETRIES + 1):
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                url,
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
                json=body,
            )

        if resp.status_code == 200:
            break

        if _is_daily_quota_error(resp.status_code, resp.text):
            raise RuntimeError(
                "Gemini daily quota reached — code audit unavailable until tomorrow."
            )

        if resp.status_code == 429 and attempt < _MAX_RETRIES:
            wait = _gemini_retry_wait(attempt)
            logger.warning(
                f"CodeAudit | Gemini rate-limited (attempt {attempt + 1}/{_MAX_RETRIES}), "
                f"retrying in {wait:.0f}s…"
            )
            await asyncio.sleep(wait)
            continue

        raise RuntimeError(f"Gemini HTTP {resp.status_code}: {resp.text[:400]}")

    text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

    cleaned = text
    if cleaned.startswith("```"):
        cleaned = "\n".join(cleaned.split("\n")[1:])
        if cleaned.endswith("```"):
            cleaned = cleaned[: cleaned.rfind("```")]

    try:
        findings = json.loads(cleaned)
        if isinstance(findings, list):
            return findings
    except (json.JSONDecodeError, KeyError):
        pass
    return []


async def _call_gemini_synthesis(all_findings: list[dict]) -> str:
    api_key = _gemini_api_key()
    url = f"{_gemini_base_url()}/models/{_GEMINI_MODEL}:generateContent"

    findings_json = json.dumps(all_findings, indent=2)
    user_prompt = _CODE_AUDIT_SYNTHESIS_PROMPT.format(findings_json=findings_json)

    body = {
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"maxOutputTokens": 4096, "temperature": 0.3},
    }

    _MAX_RETRIES = 3
    for attempt in range(_MAX_RETRIES + 1):
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                url,
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
                json=body,
            )

        if resp.status_code == 200:
            break

        if _is_daily_quota_error(resp.status_code, resp.text):
            raise RuntimeError(
                "Gemini daily quota reached — audit synthesis unavailable until tomorrow."
            )

        if resp.status_code == 429 and attempt < _MAX_RETRIES:
            wait = _gemini_retry_wait(attempt)
            logger.warning(
                f"AuditSynth | Gemini rate-limited (attempt {attempt + 1}/{_MAX_RETRIES}), "
                f"retrying in {wait:.0f}s…"
            )
            await asyncio.sleep(wait)
            continue

        raise RuntimeError(f"Gemini HTTP {resp.status_code}: {resp.text[:400]}")

    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def _load_cached_audit() -> dict | None:
    try:
        if _CODE_AUDIT_CACHE_PATH.exists():
            return json.loads(_CODE_AUDIT_CACHE_PATH.read_text())
    except Exception:
        pass
    return None


def _save_cached_audit(result: dict) -> None:
    try:
        _CODE_AUDIT_CACHE_PATH.write_text(json.dumps(result))
    except Exception as exc:
        logger.warning(f"CodeAudit | cache write failed: {exc}")


@fleet_chat_router.post("/fleet-commander/code-audit", tags=["Fleet Commander"])
async def fleet_code_audit() -> dict:
    """Crawl ALL monorepo source files, audit in chunks via Gemini, synthesise findings."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent.parent

    logger.info("CodeAudit | Starting full source collection…")
    files = _collect_source_files(repo_root)
    if not files:
        raise HTTPException(500, "No source files found to audit")

    chunks = _build_audit_chunks(files)
    total_chunks = len(chunks)
    logger.info(f"CodeAudit | {len(files)} files split into {total_chunks} chunk(s) for Gemini")

    all_findings: list[dict] = []
    for i, chunk_files in enumerate(chunks, start=1):
        logger.info(f"CodeAudit | Processing chunk {i}/{total_chunks} ({len(chunk_files)} files)…")
        try:
            system_prompt, user_prompt = _build_chunk_prompt(chunk_files, i, total_chunks)
            chunk_findings = await _call_gemini_chunk_audit(system_prompt, user_prompt)
            logger.info(f"CodeAudit | Chunk {i} returned {len(chunk_findings)} finding(s)")
            all_findings.extend(chunk_findings)
        except Exception as exc:
            logger.warning(f"CodeAudit | Chunk {i} failed: {exc} — continuing")

    if not all_findings:
        reply_text = "I found 0 issues. The codebase appears clean across all scanned files."
    else:
        logger.info(f"CodeAudit | Synthesising {len(all_findings)} raw finding(s) into final report…")
        try:
            reply_text = await _call_gemini_synthesis(all_findings)
        except Exception as exc:
            logger.error(f"CodeAudit | Synthesis failed: {exc}")
            raise HTTPException(502, f"Gemini synthesis failed: {exc}")

    ts = datetime.now(timezone.utc).isoformat()
    cached = {"text": reply_text, "ts": ts, "file_count": len(files), "chunk_count": total_chunks}
    _save_cached_audit(cached)

    _save_message("user", "[Quick Action: Code Audit]", source="manual_chat")
    _save_message(
        "assistant",
        reply_text,
        source="gemini",
        metadata={"audit": True, "ts": ts, "file_count": len(files), "chunk_count": total_chunks},
    )

    return {"text": reply_text, "ts": ts, "file_count": len(files), "chunk_count": total_chunks}


@fleet_chat_router.get("/fleet-commander/code-audit/latest", tags=["Fleet Commander"])
async def fleet_code_audit_latest() -> dict:
    """Return the most recent code audit result without re-running."""
    cached = _load_cached_audit()
    if not cached:
        raise HTTPException(404, "No audit has been run yet")
    return cached
