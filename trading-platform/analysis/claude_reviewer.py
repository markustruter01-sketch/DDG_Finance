"""
analysis/claude_reviewer.py — Claude Multi-Stage Audit Engine
=============================================================
Performs staged deep reviews of the trading platform codebase and live system
using Claude claude-3-5-sonnet-20241022.

MANUAL-ONLY: Never called by any scheduler or cron. Triggered only via the
dashboard button (POST /trading-api/claude-review/trigger/{stage_id}).

8 audit stages — critical systems first:
  Stage 1  s1_analysis         — Analysis Engine (AI decisions, fleet commander)
  Stage 2  s2_core_execution   — Core & Execution (trading engine, risk, executor)
  Stage 3  s3_routes           — API Routes (all endpoints)
  Stage 4  s4_infrastructure   — Infrastructure (main.py, db, data, portfolio…)
  Stage 5  s5_dashboard_logic  — Dashboard Logic (pages, hooks, lib)
  Stage 6  s6_components_a     — Dashboard Components A (first 60 alphabetically)
  Stage 7  s7_components_b     — Dashboard Components B (remaining)
  Stage 8  s8_synthesis        — Live Synthesis (live data + all prior summaries → master verdict)

Each stage has its own 23-hour cooldown, result file, and run state.
A single global lock prevents concurrent stage runs.

Results stored in:
  logs/claude_stage_{stage_id}.json  — per-stage last result
  logs/claude_review_history.json    — combined history across all stages
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

_HISTORY_FILE = _LOG_DIR / "claude_review_history.json"
_MAX_HISTORY = 500
_HISTORY_RETENTION_DAYS = 30
_COOLDOWN_HOURS = 23
_CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-3-5-sonnet-20241022")
_INPUT_COST_PER_1K = 0.003
_OUTPUT_COST_PER_1K = 0.015

_run_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Stage definitions — ordered by criticality (most critical first)
# ---------------------------------------------------------------------------

AUDIT_STAGES: dict[str, dict] = {
    "s1_analysis": {
        "id": "s1_analysis",
        "order": 1,
        "name": "Stage 1: Analysis Engine",
        "description": "AI decisions, fleet commander, regime detection, signal guard, backtester, learning system",
        "is_synthesis": False,
    },
    "s2_core_execution": {
        "id": "s2_core_execution",
        "order": 2,
        "name": "Stage 2: Core & Execution",
        "description": "Trading engine, scheduler, risk management, order executor, paper trading",
        "is_synthesis": False,
    },
    "s3_routes": {
        "id": "s3_routes",
        "order": 3,
        "name": "Stage 3: API Routes",
        "description": "All API endpoints, authentication, portfolio routes, fleet chat, kraken routes",
        "is_synthesis": False,
    },
    "s4_infrastructure": {
        "id": "s4_infrastructure",
        "order": 4,
        "name": "Stage 4: Infrastructure",
        "description": "main.py, database layer, data providers, portfolio management, notifications, config, tests",
        "is_synthesis": False,
    },
    "s5_dashboard_logic": {
        "id": "s5_dashboard_logic",
        "order": 5,
        "name": "Stage 5: Dashboard Logic",
        "description": "Dashboard pages, data hooks, utility library (TypeScript/React)",
        "is_synthesis": False,
    },
    "s6_components_a": {
        "id": "s6_components_a",
        "order": 6,
        "name": "Stage 6: Dashboard Components A",
        "description": "First 60 dashboard React components (alphabetical order)",
        "is_synthesis": False,
    },
    "s7_components_b": {
        "id": "s7_components_b",
        "order": 7,
        "name": "Stage 7: Dashboard Components B",
        "description": "Remaining dashboard React components",
        "is_synthesis": False,
    },
    "s8_synthesis": {
        "id": "s8_synthesis",
        "order": 8,
        "name": "Stage 8: Live Synthesis",
        "description": "Synthesises all stage findings + live DB data into master system verdict",
        "is_synthesis": True,
    },
}

_stage_run_states: dict[str, dict[str, Any]] = {
    sid: {"in_progress": False, "run_id": None, "started_at": None, "error": None}
    for sid in AUDIT_STAGES
}

_BUILDER_MAP = {
    "s1_analysis": "build_stage_1_analysis",
    "s2_core_execution": "build_stage_2_core_execution",
    "s3_routes": "build_stage_3_routes",
    "s4_infrastructure": "build_stage_4_infrastructure",
    "s5_dashboard_logic": "build_stage_5_dashboard_logic",
    "s6_components_a": "build_stage_6_dashboard_components_a",
    "s7_components_b": "build_stage_7_dashboard_components_b",
}

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_STAGE_REVIEW_SYSTEM = """\
You are a Senior Quantitative Systems Auditor performing a targeted deep review of a specific \
module in a live AI trading platform.

You are reviewing: {stage_name}
Module coverage: {stage_description}

Identify all of the following that apply to this module:
1. BUGS — logic errors, edge cases, unsafe patterns, division-by-zero, type mismatches
2. PARAMETER ISSUES — miscalibrated values, contradictory or out-of-range settings
3. RISK PATTERNS — code paths that could cause runaway losses, silent failures, missed safeguards
4. DATA INTEGRITY — stale data risks, incorrect calculations, P&L computation errors
5. CONCURRENCY — race conditions, thread safety violations, lock misuse
6. API ISSUES — unprotected endpoints, missing validation, poor error handling (routes stages)
7. UI ISSUES — incorrect data display, broken state, misleading labels (frontend stages)

Return ONLY a JSON object with EXACTLY this schema (no markdown fences, no explanation):
{{
  "stage_verdict": "PASS | NEEDS_ATTENTION | CRITICAL",
  "summary": "<2–4 sentence overall assessment of this code area>",
  "critical_issues": [
    {{"file": "<filename>", "function": "<function or component name>", "issue": "<description>", "recommendation": "<specific fix>"}}
  ],
  "high_issues": [
    {{"file": "<filename>", "function": "<function or component name>", "issue": "<description>", "recommendation": "<specific fix>"}}
  ],
  "medium_issues": [
    {{"file": "<filename>", "function": "<function or component name>", "issue": "<description>", "recommendation": "<specific fix>"}}
  ],
  "parameter_concerns": [
    {{"file": "<filename>", "issue": "<description>", "recommendation": "<specific fix>"}}
  ],
  "key_risks": ["<risk 1>", "<risk 2>"],
  "positive_notes": ["<something done well>"]
}}

Rules:
- stage_verdict MUST be CRITICAL if any critical_issues exist; NEEDS_ATTENTION if any high_issues exist; otherwise PASS
- Only flag genuine issues — not stylistic preferences
- Cite exact file names and function/component names
- Return ONLY the JSON object
"""

_SYNTHESIS_SYSTEM = """\
You are the Chief Risk Officer of an AI trading fleet performing a comprehensive system review.
You have been given:
1. Findings from all completed audit stages (Analysis Engine, Core/Execution, API Routes, Infrastructure, Frontend)
2. Complete live system data: trade history, positions, P&L, errors, learning journal, parameters

Produce a comprehensive structured report in JSON with EXACTLY this schema:
{
  "system_health_verdict": "HEALTHY | DEGRADED | CRITICAL",
  "health_summary": "<2-4 sentence overall assessment>",
  "per_bot_assessment": [
    {
      "bot_id": "oracle|davy_jones|blackbeard|calypso|apex_predator|navigator",
      "verdict": "GOOD | WARNING | CRITICAL",
      "win_rate_assessment": "<brief assessment>",
      "pnl_assessment": "<brief assessment>",
      "parameter_assessment": "<brief assessment>",
      "flags": ["<specific issue>"]
    }
  ],
  "code_issues": [
    {
      "severity": "CRITICAL | HIGH | MEDIUM | LOW",
      "file": "<filename>",
      "function": "<function/component name>",
      "issue": "<concise description>",
      "recommendation": "<specific fix>"
    }
  ],
  "parameter_recommendations": [
    {
      "bot_id": "<bot_id>",
      "parameter": "<param_name>",
      "current_value": "<value or unknown>",
      "recommended_value": "<value>",
      "reasoning": "<data-driven reason>"
    }
  ],
  "cross_bot_risks": ["<risk description>"],
  "frontend_ui_issues": ["<issue description>"],
  "action_items": [
    {
      "priority": 1,
      "category": "CODE | PARAMETER | RISK | UI | MONITORING",
      "action": "<specific actionable step>",
      "impact": "<expected impact>"
    }
  ],
  "stage_key_findings": {
    "<stage_name>": ["<top finding 1>", "<top finding 2>"]
  }
}

Rules:
- action_items ranked by priority (1 = most urgent)
- per_bot_assessment must cover all active bots found in the live data
- Use exact data from the live system where available
- Return ONLY the JSON object — no markdown fences, no explanation
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_stage_file(stage_id: str) -> Path:
    return _LOG_DIR / f"claude_stage_{stage_id}.json"


def _get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable not set")
    return key


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens / 1000 * _INPUT_COST_PER_1K) + (output_tokens / 1000 * _OUTPUT_COST_PER_1K)


def _call_claude(system_prompt: str, user_content: str, max_tokens: int = 6000) -> tuple[str, dict]:
    import anthropic
    client = anthropic.Anthropic(api_key=_get_api_key())
    message = client.messages.create(
        model=_CLAUDE_MODEL,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    usage = {
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
        "total_tokens": message.usage.input_tokens + message.usage.output_tokens,
    }
    usage["estimated_cost_usd"] = round(_estimate_cost(usage["input_tokens"], usage["output_tokens"]), 4)
    return message.content[0].text if message.content else "", usage


def _parse_json_response(raw: str) -> dict:
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        import re
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
    return {"raw_response": raw}


def _write_stage_result(stage_id: str, payload: dict) -> None:
    stage_file = _get_stage_file(stage_id)
    serialised = json.dumps(payload, indent=2, default=str)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=_LOG_DIR, prefix=f".claude_{stage_id}_", suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w") as f:
            f.write(serialised)
        os.replace(tmp_path, stage_file)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    history: list[dict] = []
    if _HISTORY_FILE.exists():
        try:
            history = json.loads(_HISTORY_FILE.read_text())
        except Exception:
            history = []
    summary_entry = {
        "stage_id": stage_id,
        "stage_name": payload.get("stage_name"),
        "run_id": payload.get("run_id"),
        "generated_at": payload.get("generated_at"),
        "status": payload.get("status"),
        "stage_verdict": payload.get("stage_verdict") or payload.get("system_health_verdict"),
        "summary": (payload.get("summary") or payload.get("health_summary", ""))[:300],
        "total_tokens": payload.get("total_tokens"),
        "estimated_cost_usd": payload.get("estimated_cost_usd"),
        "elapsed_seconds": payload.get("elapsed_seconds"),
        "summary_log": payload.get("summary_log", ""),
    }
    history.append(summary_entry)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_HISTORY_RETENTION_DAYS)).isoformat()
    history = [h for h in history if (h.get("generated_at") or "") >= cutoff]
    if len(history) > _MAX_HISTORY:
        history = history[-_MAX_HISTORY:]
    _HISTORY_FILE.write_text(json.dumps(history, indent=2, default=str))


# ---------------------------------------------------------------------------
# Public read APIs
# ---------------------------------------------------------------------------

def _get_stage_cooldown(stage_id: str) -> dict:
    stage_file = _get_stage_file(stage_id)
    if not stage_file.exists():
        return {"locked": False, "next_available": None, "seconds_remaining": 0}
    try:
        data = json.loads(stage_file.read_text())
        ts = data.get("generated_at")
        if not ts:
            return {"locked": False, "next_available": None, "seconds_remaining": 0}
        last_run = datetime.fromisoformat(ts)
        if last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=timezone.utc)
        next_available = last_run + timedelta(hours=_COOLDOWN_HOURS)
        now = datetime.now(timezone.utc)
        if now >= next_available:
            return {"locked": False, "next_available": next_available.isoformat(), "seconds_remaining": 0}
        remaining = (next_available - now).total_seconds()
        return {"locked": True, "next_available": next_available.isoformat(), "seconds_remaining": int(remaining)}
    except Exception:
        return {"locked": False, "next_available": None, "seconds_remaining": 0}


def get_all_stages_status() -> list[dict]:
    """Returns status summary for all 8 stages (used by GET /claude-review/stages)."""
    stages = []
    for stage_id, meta in sorted(AUDIT_STAGES.items(), key=lambda x: x[1]["order"]):
        stage_file = _get_stage_file(stage_id)
        last_result: dict | None = None
        if stage_file.exists():
            try:
                data = json.loads(stage_file.read_text())
                verdict = data.get("stage_verdict") or data.get("system_health_verdict")
                last_result = {
                    "status": data.get("status"),
                    "generated_at": data.get("generated_at"),
                    "elapsed_seconds": data.get("elapsed_seconds"),
                    "total_tokens": data.get("total_tokens"),
                    "estimated_cost_usd": data.get("estimated_cost_usd"),
                    "stage_verdict": verdict,
                    "summary": (data.get("summary") or data.get("health_summary", ""))[:300],
                    "critical_count": len(data.get("critical_issues", [])),
                    "high_count": len(data.get("high_issues", [])),
                    "medium_count": len(data.get("medium_issues", [])),
                }
            except Exception:
                pass

        stages.append({
            "id": stage_id,
            "order": meta["order"],
            "name": meta["name"],
            "description": meta["description"],
            "is_synthesis": meta["is_synthesis"],
            "last_result": last_result,
            "cooldown": _get_stage_cooldown(stage_id),
            "run_state": dict(_stage_run_states[stage_id]),
        })
    return stages


def get_stage_full_result(stage_id: str) -> dict:
    """Returns full stored result for a specific stage."""
    if stage_id not in AUDIT_STAGES:
        return {"status": "error", "message": f"Unknown stage: {stage_id}"}
    stage_file = _get_stage_file(stage_id)
    if not stage_file.exists():
        return {"status": "not_run", "message": f"{AUDIT_STAGES[stage_id]['name']} has not run yet"}
    try:
        data = json.loads(stage_file.read_text())
        data.setdefault("status", "ok")
        return data
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def get_stage_run_state(stage_id: str) -> dict:
    return dict(_stage_run_states.get(stage_id, {}))


def get_review_history() -> list[dict]:
    if not _HISTORY_FILE.exists():
        return []
    try:
        return json.loads(_HISTORY_FILE.read_text())
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Stage execution
# ---------------------------------------------------------------------------

def _run_stage_locked(stage_id: str, run_id: str) -> None:
    meta = AUDIT_STAGES[stage_id]
    started_at = datetime.now(timezone.utc)
    _stage_run_states[stage_id].update({
        "in_progress": True,
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "error": None,
    })

    try:
        import analysis.system_snapshot as snap

        logger.info(f"ClaudeReviewer | Stage {stage_id} ({meta['name']}) — building snapshot...")
        snap_start = time.time()

        if meta["is_synthesis"]:
            prior_summaries: dict[str, str] = {}
            for sid, smeta in AUDIT_STAGES.items():
                if sid == stage_id:
                    continue
                sf = _get_stage_file(sid)
                if sf.exists():
                    try:
                        d = json.loads(sf.read_text())
                        verdict = d.get("stage_verdict", "N/A")
                        crit = len(d.get("critical_issues", []))
                        high = len(d.get("high_issues", []))
                        med = len(d.get("medium_issues", []))
                        risks = "; ".join(d.get("key_risks", [])[:5])
                        prior_summaries[smeta["name"]] = (
                            f"Verdict: {verdict}\n"
                            f"Summary: {(d.get('summary') or '')[:500]}\n"
                            f"Critical: {crit}  High: {high}  Medium: {med}\n"
                            f"Key risks: {risks}"
                        )
                    except Exception:
                        pass
            code_content = snap.build_stage_8_live_synthesis(prior_summaries)
            system_prompt = _SYNTHESIS_SYSTEM
            user_prompt = (
                "You have been given summaries from all completed audit stages plus live system data. "
                "Produce the comprehensive structured master verdict JSON as specified.\n\n"
                + code_content
            )
            max_tokens = 8192
        else:
            builder = getattr(snap, _BUILDER_MAP[stage_id])
            code_content = builder()
            system_prompt = _STAGE_REVIEW_SYSTEM.format(
                stage_name=meta["name"],
                stage_description=meta["description"],
            )
            user_prompt = (
                f"Review the following source code for: {meta['description']}.\n"
                "Identify all bugs, risks, parameter issues, and problems. Cite file and function names.\n\n"
                "SOURCE CODE:\n" + code_content
            )
            max_tokens = 6000

        snap_elapsed = time.time() - snap_start
        logger.info(
            f"ClaudeReviewer | Stage {stage_id} snapshot built in {snap_elapsed:.1f}s — "
            f"{len(user_prompt):,} chars input"
        )

        call_start = time.time()
        response, usage = _call_claude(system_prompt, user_prompt, max_tokens=max_tokens)
        call_elapsed = time.time() - call_start

        logger.info(
            f"ClaudeReviewer | Stage {stage_id} API call complete in {call_elapsed:.1f}s — "
            f"tokens={usage['total_tokens']} cost=${usage['estimated_cost_usd']:.4f}"
        )

        parsed = _parse_json_response(response)

        verdict = parsed.get("stage_verdict") or parsed.get("system_health_verdict", "UNKNOWN")
        crit_n = len(parsed.get("critical_issues", []))
        high_n = len(parsed.get("high_issues", []))
        med_n = len(parsed.get("medium_issues", []))
        summary_text = (parsed.get("summary") or parsed.get("health_summary", ""))[:200]
        summary_log = (
            f"{meta['name']} | verdict={verdict} critical={crit_n} high={high_n} medium={med_n} | {summary_text}"
        )
        logger.info(f"ClaudeReviewer | AUDIT LOG: {summary_log}")

        total_elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()

        payload: dict = {
            "stage_id": stage_id,
            "stage_name": meta["name"],
            "run_id": run_id,
            "generated_at": started_at.isoformat(),
            "model": _CLAUDE_MODEL,
            "elapsed_seconds": round(total_elapsed, 1),
            "total_input_tokens": usage["input_tokens"],
            "total_output_tokens": usage["output_tokens"],
            "total_tokens": usage["total_tokens"],
            "estimated_cost_usd": usage["estimated_cost_usd"],
            "status": "ok",
            "summary_log": summary_log,
        }
        payload.update(parsed)

        _write_stage_result(stage_id, payload)

    except Exception as exc:
        elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
        logger.error(f"ClaudeReviewer | Stage {stage_id} failed after {elapsed:.1f}s: {exc}")
        _stage_run_states[stage_id]["error"] = str(exc)
        error_payload = {
            "stage_id": stage_id,
            "stage_name": meta["name"],
            "run_id": run_id,
            "generated_at": started_at.isoformat(),
            "status": "failed",
            "error": str(exc),
            "elapsed_seconds": round(elapsed, 1),
            "summary_log": f"{meta['name']} | FAILED: {exc}",
        }
        try:
            _write_stage_result(stage_id, error_payload)
        except Exception:
            pass

    finally:
        _stage_run_states[stage_id].update({"in_progress": False})


def trigger_stage(stage_id: str, run_id: str) -> None:
    """Entry point called from background thread. Never called by any scheduler."""
    if not _run_lock.acquire(blocking=False):
        logger.info(f"ClaudeReviewer | Audit already running — skipping trigger for stage={stage_id}")
        return
    try:
        _run_stage_locked(stage_id, run_id)
    finally:
        _run_lock.release()
