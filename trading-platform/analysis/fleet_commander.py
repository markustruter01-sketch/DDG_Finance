"""
analysis/fleet_commander.py — Claude Fleet Commander (All-Bot Audit)
====================================================================
Runs 6× daily via APScheduler.  Fetches the full export report covering
all 6 bots, sends it to Claude for adversarial fleet-wide audit, and
returns structured parameter adjustment recommendations.

Schedule (ET):  04:15, 09:45, 12:00, 15:00, 17:00, 22:00
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import threading

import requests
from loguru import logger
from pydantic import BaseModel, Field, field_validator

from analysis.gemini_auditor import _GeminiAuditResponse, _GeminiCondition

_LOG_DIR = Path(__file__).parent.parent / "logs"
_FLEET_AUDIT_FILE = _LOG_DIR / "fleet_audit.json"
_FLEET_HISTORY_FILE = _LOG_DIR / "fleet_audit_history.json"
_LOG_DIR.mkdir(exist_ok=True)

_MAX_HISTORY = 24


class KrakenBotParams(BaseModel):
    bot_id: str = ""
    ZSCORE_ENTRY: float | None = None
    ZSCORE_EXIT: float | None = None
    STOP_LOSS_PCT: float | None = None
    TRAIL_PCT: float | None = None
    MIN_NET_PROFIT_PCT: float | None = None
    reasoning: str = ""


class OracleParamRec(BaseModel):
    conviction_threshold: float | None = None
    max_positions: int | None = None
    cash_reserve_pct: float | None = None
    reasoning: str = ""


class NavigatorParamRec(BaseModel):
    position_size_usd: float | None = None
    reasoning: str = ""


class FleetCommanderResponse(BaseModel):
    vetoed_tickers: list[str] = Field(default_factory=list)
    conditions: list[_GeminiCondition] = Field(default_factory=list)
    kraken_param_adjustments: list[KrakenBotParams] = Field(default_factory=list)
    oracle_param_adjustment: OracleParamRec | None = None
    navigator_param_adjustment: NavigatorParamRec | None = None
    critique_summary: str = ""
    critique_flags: list[str] = Field(default_factory=list)
    overall_verdict: str = "CLEAN"
    bot_verdicts: dict[str, str] = Field(default_factory=dict)

    @field_validator("overall_verdict")
    @classmethod
    def _valid_verdict(cls, v: str) -> str:
        valid = {"CLEAN", "CAUTION", "HOLD"}
        v = v.upper().strip()
        return v if v in valid else "CAUTION"

    @field_validator("vetoed_tickers")
    @classmethod
    def _upper_tickers(cls, lst: list[str]) -> list[str]:
        return [str(t).upper().strip().replace("/", "") for t in lst if t]


_FLEET_SYSTEM_PROMPT = """\
You are the FLEET COMMANDER — a Senior Quantitative Risk Auditor performing an
adversarial audit of an entire AI trading fleet.  Your job is to find problems
and recommend precise parameter adjustments.

FLEET COMPOSITION (6 bots, ~$600K total paper capital)
======================================================
Bot #1 — Oracle/Alpaca (equities + crypto)
  • Alpaca paper-trading, 15-minute cycle
  • Claude (claude-sonnet) assigns conviction scores and writes trade theses
  • 10-slot portfolio with 60% cash ring-fence
  • Kill switch at 5% daily drawdown

Bot #2 — Davy Jones (Kraken crypto, conservative, ATR stop 1.5×)
Bot #3 — Blackbeard (Kraken crypto, aggressive, ATR stop 2.0×)
Bot #4 — Calypso (Kraken crypto, balanced, ATR stop 2.0×)
  • All three use z-score mean-reversion strategy on BTC, ETH, SOL, DOT, LINK, AVAX, MATIC, ADA
  • Adaptive parameters: ZSCORE_ENTRY, ZSCORE_EXIT, STOP_LOSS_PCT, TRAIL_PCT, MIN_NET_PROFIT_PCT

Bot #5 — Apex Predator (options, paper trading)
Bot #6 — Navigator (forex, paper trading)

YOUR AUDIT TARGETS (look hard for each)
========================================
1. Cross-bot correlation risk — multiple bots holding the same losing asset
2. Conviction inflation — scores clustered above 0.85 with mediocre outcomes
3. Regime contradiction — regime label vs equity trajectory mismatch
4. Stop-loss effectiveness — are stops firing too often or too rarely per bot?
5. Position sizing violations — any bot exceeding its risk allocation
6. Data anomalies — impossible PnL, stale data, duplicate entries
7. Kraken parameter drift — any bot's adaptive params drifted to extreme bounds
8. Win rate divergence — identify which bots need tighter/looser entry thresholds
9. Overconcentration — single asset consuming too much of any bot's allocation

PARAMETER BOUNDS (your recommendations MUST stay within these)
==============================================================
Kraken bots:
ZSCORE_ENTRY:       [0.70, 1.50]  step=0.05
ZSCORE_EXIT:        [0.10, 0.55]  step=0.02
STOP_LOSS_PCT:      [0.008, 0.040] step=0.002
TRAIL_PCT:          [0.030, 0.100] step=0.005
MIN_NET_PROFIT_PCT: [0.006, 0.020] step=0.001

Oracle (#1 Alpaca bot):
conviction_threshold: [0.60, 0.95]  step=0.05  (lower = more trades, higher = selective)
max_positions:        [1, 10]        step=1     (concurrent equity positions)
cash_reserve_pct:     [0.30, 0.80]  step=0.05  (fraction kept as cash/SGOV)

Navigator (#6 forex bot):
position_size_usd: [5000, 25000] step=1000  (per-trade notional USD)

OUTPUT FORMAT (strict JSON, no markdown fences)
===============================================
{
  "vetoed_tickers": ["TICKER1"],
  "conditions": [
    {"type": "vpin_threshold", "value": 0.7},
    {"type": "max_conviction_cap", "value": 0.85},
    {"type": "news_blacklist", "ticker": "META"}
  ],
  "kraken_param_adjustments": [
    {
      "bot_id": "davy_jones",
      "ZSCORE_ENTRY": 1.10,
      "STOP_LOSS_PCT": 0.020,
      "reasoning": "Win rate 35% with profit factor 0.8 — tighten entry threshold"
    },
    {
      "bot_id": "blackbeard",
      "TRAIL_PCT": 0.065,
      "reasoning": "Trailing stop firing 45% of exits with thin avg win — give more room"
    }
  ],
  "oracle_param_adjustment": {
    "conviction_threshold": 0.80,
    "max_positions": null,
    "cash_reserve_pct": null,
    "reasoning": "Conviction inflation detected — raise threshold to improve signal quality"
  },
  "navigator_param_adjustment": {
    "position_size_usd": null,
    "reasoning": "Navigator performing within expected bounds — no change needed"
  },
  "critique_summary": "<2-4 sentence fleet-wide assessment>",
  "critique_flags": ["<specific issue 1>", "<specific issue 2>"],
  "overall_verdict": "CLEAN | CAUTION | HOLD",
  "bot_verdicts": {
    "oracle": "CLEAN",
    "davy_jones": "CAUTION",
    "blackbeard": "CLEAN",
    "calypso": "CLEAN",
    "apex_predator": "CLEAN",
    "navigator": "CLEAN"
  }
}

RULES
=====
• CRITICAL: Use the pre-computed summary metrics (Win Rate, Win/Loss counts, Total P&L) from each bot's overview section. DO NOT attempt to count individual trade rows or calculate your own metrics — the pre-computed values are authoritative and your manual counting WILL be wrong.
• When citing win rates in your reasoning, use the EXACT percentage from the "Win / Loss" line in the report.
• Only recommend param changes when data clearly supports it — do not change params for bots performing well
• kraken_param_adjustments: only include bots that NEED changes.  Omit bots that are fine.
• bot_id values: "davy_jones", "blackbeard", "calypso" (exact strings)
• vetoed_tickers: symbols that must NOT be traded today (Alpaca bot)
• overall_verdict: CLEAN = fleet healthy; CAUTION = proceed with reduced risk; HOLD = suspend until human review
• Be specific — cite ticker names, PnL values, win rates when available
• If data is sparse or all bots are performing well, output verdict=CLEAN with empty adjustment lists
• Return ONLY the JSON object — no explanation, no code fences
"""


def _fetch_export_report() -> str | None:
    try:
        resp = requests.get("http://localhost:8000/trading-api/export/report", timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("report", "")
    except Exception as exc:
        logger.warning(f"FleetCommander | Failed to fetch export report: {exc}")
    return None


def _call_fleet_claude(report_text: str) -> tuple[FleetCommanderResponse, dict]:
    from analysis.claude_client import call_claude_with_usage

    user_content = f"FLEET DIAGNOSTIC REPORT\n{'='*60}\n{report_text}"

    try:
        raw, token_usage = call_claude_with_usage(
            system_prompt=_FLEET_SYSTEM_PROMPT,
            user_prompt=user_content,
            temperature=0.7,
            max_tokens=8192,
            call_type="fleet_commander",
            expect_json=True,
            smart=True,
        )
    except Exception as exc:
        raise RuntimeError(f"Claude API call failed: {exc}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Claude returned non-JSON: {raw[:200]}") from exc

    try:
        result = FleetCommanderResponse(**parsed)
        return result, token_usage
    except Exception as exc:
        raise RuntimeError(f"Fleet Commander response validation failed: {exc}") from exc


def _write_fleet_audit(result: FleetCommanderResponse, token_usage: dict,
                        elapsed: float, generated_at: datetime) -> None:
    import tempfile

    payload = {
        "generated_at": generated_at.isoformat(),
        "valid_until": (generated_at + timedelta(hours=6)).isoformat(),
        "overall_verdict": result.overall_verdict,
        "bot_verdicts": result.bot_verdicts,
        "vetoed_tickers": result.vetoed_tickers,
        "conditions": [c.model_dump(exclude_none=True) for c in result.conditions],
        "kraken_param_adjustments": [p.model_dump(exclude_none=True) for p in result.kraken_param_adjustments],
        "oracle_param_adjustment": result.oracle_param_adjustment.model_dump(exclude_none=True) if result.oracle_param_adjustment else None,
        "navigator_param_adjustment": result.navigator_param_adjustment.model_dump(exclude_none=True) if result.navigator_param_adjustment else None,
        "critique_summary": result.critique_summary,
        "critique_flags": result.critique_flags,
        "token_usage": token_usage,
        "elapsed_seconds": round(elapsed, 1),
    }

    serialised = json.dumps(payload, indent=2, default=str)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=_FLEET_AUDIT_FILE.parent, prefix=".fleet_audit_", suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            f.write(serialised)
        os.replace(tmp_path, _FLEET_AUDIT_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    _append_history(payload)


def _append_history(entry: dict) -> None:
    history = []
    if _FLEET_HISTORY_FILE.exists():
        try:
            history = json.loads(_FLEET_HISTORY_FILE.read_text())
        except Exception:
            history = []

    history.append(entry)
    if len(history) > _MAX_HISTORY:
        history = history[-_MAX_HISTORY:]

    _FLEET_HISTORY_FILE.write_text(json.dumps(history, indent=2, default=str))


_daily_token_usage: dict[str, int] = {
    "date": "",
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "call_count": 0,
}


def _track_tokens(usage: dict) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _daily_token_usage["date"] != today:
        _daily_token_usage["date"] = today
        _daily_token_usage["prompt_tokens"] = 0
        _daily_token_usage["completion_tokens"] = 0
        _daily_token_usage["total_tokens"] = 0
        _daily_token_usage["call_count"] = 0

    _daily_token_usage["call_count"] += 1
    _daily_token_usage["prompt_tokens"]     += usage.get("prompt_tokens", 0)
    _daily_token_usage["completion_tokens"] += usage.get("completion_tokens", 0)
    _daily_token_usage["total_tokens"]      += usage.get("total_tokens", 0)


def get_token_usage() -> dict:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _daily_token_usage["date"] != today:
        return {"date": today, "prompt_tokens": 0, "completion_tokens": 0,
                "total_tokens": 0, "call_count": 0}
    return dict(_daily_token_usage)


_run_lock = threading.Lock()


def run_fleet_commander() -> dict[str, Any]:
    if not _run_lock.acquire(blocking=False):
        logger.info("FleetCommander | Already running — skipping duplicate trigger")
        return {"status": "skipped", "reason": "already_running"}

    try:
        return _run_fleet_commander_locked()
    finally:
        _run_lock.release()


def _run_fleet_commander_locked() -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    logger.info("FleetCommander | Starting fleet-wide audit")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.warning("FleetCommander | ANTHROPIC_API_KEY not set — skipping")
        return {"status": "skipped", "reason": "env_vars_missing"}

    report = _fetch_export_report()
    if not report:
        logger.warning("FleetCommander | No export report available — skipping")
        return {"status": "skipped", "reason": "no_report"}

    logger.info(f"FleetCommander | Report size: {len(report):,} chars")

    try:
        result, token_usage = _call_fleet_claude(report)
    except RuntimeError as exc:
        logger.warning(f"FleetCommander | Claude call failed: {exc} — aborting (fail-open)")
        return {"status": "failed", "reason": str(exc)}

    _track_tokens(token_usage)

    from analysis.fleet_enforcer import enforce_fleet_recommendations
    enforcement = enforce_fleet_recommendations(result)

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()

    try:
        _write_fleet_audit(result, token_usage, elapsed, started_at)
    except Exception as exc:
        logger.warning(f"FleetCommander | Failed to write audit file: {exc}")

    try:
        _record_intervention(result, started_at)
    except Exception as exc:
        logger.warning(f"FleetCommander | Failed to record intervention: {exc}")

    logger.info(
        f"FleetCommander | Complete in {elapsed:.1f}s — "
        f"verdict={result.overall_verdict} "
        f"vetoed={result.vetoed_tickers} "
        f"param_changes={len(result.kraken_param_adjustments)} "
        f"flags={len(result.critique_flags)} "
        f"tokens={token_usage.get('total_tokens', 0)}"
    )

    return {
        "status": "ok",
        "overall_verdict": result.overall_verdict,
        "bot_verdicts": result.bot_verdicts,
        "vetoed_tickers": result.vetoed_tickers,
        "condition_count": len(result.conditions),
        "param_adjustments": len(result.kraken_param_adjustments),
        "flag_count": len(result.critique_flags),
        "critique_summary": result.critique_summary,
        "enforcement": enforcement,
        "token_usage": token_usage,
        "elapsed_seconds": round(elapsed, 1),
        "generated_at": started_at.isoformat(),
    }


def get_last_fleet_audit() -> dict[str, Any]:
    if not _FLEET_AUDIT_FILE.exists():
        return {
            "status": "not_run",
            "message": "Fleet Commander has not run yet",
            "file_exists": False,
        }

    try:
        data = json.loads(_FLEET_AUDIT_FILE.read_text())
        data["status"] = "ok"
        data["file_exists"] = True
        return data
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Could not parse fleet_audit.json: {exc}",
            "file_exists": True,
        }


def _record_intervention(result: FleetCommanderResponse, generated_at: datetime) -> None:
    import psycopg2
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return
    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT total_equity FROM equity_snapshots WHERE ts <= %s ORDER BY ts DESC LIMIT 1",
                (generated_at,)
            )
            eq_row = cur.fetchone()
            equity = eq_row[0] if eq_row else None

            cur.execute(
                """INSERT INTO ai_interventions
                    (ts, source, overall_verdict, bot_verdicts, param_changes,
                     vetoed_tickers, critique_summary, critique_flags, conditions, equity_at_time)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    generated_at, "fleet_commander", result.overall_verdict,
                    json.dumps(result.bot_verdicts),
                    json.dumps([p.model_dump(exclude_none=True) for p in result.kraken_param_adjustments]),
                    json.dumps(result.vetoed_tickers),
                    result.critique_summary,
                    json.dumps(result.critique_flags),
                    json.dumps([c.model_dump(exclude_none=True) for c in result.conditions]),
                    equity,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def get_fleet_audit_history() -> list[dict]:
    if not _FLEET_HISTORY_FILE.exists():
        return []
    try:
        return json.loads(_FLEET_HISTORY_FILE.read_text())
    except Exception:
        return []
