"""
analysis/gemini_auditor.py  —  Gemini Daily Self-Critic Auditor
================================================================
Runs once per day at 04:15 AM ET (before market open) via the APScheduler
job registered in core/scheduler.py.

Responsibilities
----------------
  1. Fetches the previous day's trade records, equity snapshots, system
     degradations and performance summary from PostgreSQL.
  2. Sanitizes and compacts the payload (gemini_context_sanitizer).
  3. If the payload exceeds 80 % of the token budget, chunks the equity
     time-series into 8-hour windows and calls Gemini once per chunk,
     then merges the results (union of vetoed tickers / conditions).
  4. Calls Gemini (gemini-3-flash-preview) with an adversarial "Self-Critic"
     system prompt that looks for:
       • Conviction-score inflation or inconsistency
       • Regime-label contradictions vs. equity/PnL behaviour
       • Position-sizing violations relative to risk profile
       • Repeated ticker vetoes (wash-sale blindness)
       • Data-quality anomalies (impossible PnL, stale equity)
  5. Parses and validates the JSON response (Pydantic).
  6. Atomically writes logs/veto_conditions.json (temp-file + rename).

Fail-open behaviour
-------------------
  If Gemini is unavailable, the DB query fails, or the response cannot be
  parsed, the function logs a WARNING and exits cleanly — no partial file
  is written and the previous veto_conditions.json is left untouched.

Output schema (veto_conditions.json)
-------------------------------------
{
    "generated_at":   "<ISO-8601 UTC>",
    "valid_until":    "<ISO-8601 UTC>",        # generated_at + 24 h
    "vetoed_tickers": ["AAPL", "TSLA"],        # uppercase symbols
    "conditions": [
        {"type": "vpin_threshold",      "value":  0.7},
        {"type": "news_blacklist",       "ticker": "META"},
        {"type": "max_conviction_cap",  "value":  0.85}
    ],
    "critique_summary": "<2–4 sentence prose summary>",
    "critique_flags":   ["<issue 1>", "<issue 2>"],
    "overall_verdict":  "CAUTION" | "CLEAN" | "HOLD"
}
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import requests
from loguru import logger
from pydantic import BaseModel, Field, field_validator

from analysis.gemini_context_sanitizer import (
    TOKEN_BUDGET,
    CHUNK_THRESHOLD,
    sanitize_daily_context,
    estimate_tokens,
    chunk_by_hours,
)

# ── Output directory ───────────────────────────────────────────────────────────
_LOG_DIR    = Path(__file__).parent.parent / "logs"
_VETO_FILE  = _LOG_DIR / "veto_conditions.json"
_LOG_DIR.mkdir(exist_ok=True)

# ── Gemini model ───────────────────────────────────────────────────────────────
_GEMINI_MODEL          = "gemini-3-flash-preview"
_GEMINI_CALL_DELAY_SEC = 300.0      # 5-minute spacing between chunk calls (rate limit safety)

# ── Lookback window ────────────────────────────────────────────────────────────
_LOOKBACK_HOURS = 28                # yesterday + a few pre-market hours of today


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 ── Pydantic response model
# ══════════════════════════════════════════════════════════════════════════════

class _GeminiCondition(BaseModel):
    type:   str
    value:  float | str | None = None
    ticker: str | None         = None

    @field_validator("type")
    @classmethod
    def _type_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("condition.type must not be empty")
        return v.strip()


class _GeminiAuditResponse(BaseModel):
    vetoed_tickers:  list[str]           = Field(default_factory=list)
    conditions:      list[_GeminiCondition] = Field(default_factory=list)
    critique_summary: str                = ""
    critique_flags:  list[str]           = Field(default_factory=list)
    overall_verdict: str                 = "CLEAN"

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


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 ── System prompt
# ══════════════════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """\
You are a Senior Quantitative Risk Auditor performing a DAILY SELF-CRITIC review
of an automated AI trading platform.  Your role is ADVERSARIAL — your job is to
find problems, not to validate good work.

Platform description
--------------------
• Alpaca paper-trading (equities + ETFs) + Alpaca crypto, 15-minute cycle
• Groq Llama-3.3-70B assigns conviction scores (0–1) and writes trade theses
• Regime detection: Bull / Bear / Sideways / Crypto
• 10-slot portfolio with ring-fenced 60 % cash
• Kill switch at 5 % daily drawdown

Your audit targets (look hard for each)
----------------------------------------
1. Conviction inflation — scores clustered above 0.85 with mediocre outcomes
2. Regime contradiction — regime label inconsistent with equity trajectory or
   drawdown magnitude
3. Wash-sale blindness — same ticker appearing in losses then wins within 30 d
4. Data anomalies — impossible PnL (> 20 % in a single 15-min cycle), stale
   equity curve (no updates for > 2 hours during market hours), duplicate rows
5. Overconcentration — single ticker consuming > 15 % of the allocation budget
6. Repeated system degradations — same component failing > 3× in one day
7. Thesis quality — hindsight language, vague rationale, copy-pasted text

Output format (strict JSON, no markdown fences)
-----------------------------------------------
{
  "vetoed_tickers":  ["TICKER1", "TICKER2"],
  "conditions": [
    {"type": "vpin_threshold",     "value": 0.7},
    {"type": "max_conviction_cap", "value": 0.85},
    {"type": "news_blacklist",     "ticker": "META"}
  ],
  "critique_summary": "<2–4 sentence overall assessment>",
  "critique_flags":   ["<specific issue 1>", "<specific issue 2>"],
  "overall_verdict":  "CLEAN" | "CAUTION" | "HOLD"
}

Rules
-----
• vetoed_tickers  : symbols that must NOT be traded today (use CAUTION sparingly)
• conditions      : structured risk rules to override system defaults today
• overall_verdict : CLEAN = all good; CAUTION = proceed with reduced size;
                    HOLD = suspend trading until human review
• Be specific — cite ticker names, timestamps, exact PnL values when available
• If data is too sparse to audit, output verdict=CLEAN with empty lists
• Return ONLY the JSON object — no explanation, no code fences
"""


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 ── Gemini REST client (direct Google API, user's own key)
# ══════════════════════════════════════════════════════════════════════════════

_GOOGLE_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _gemini_base_url() -> str:
    """Return the Gemini REST base URL (direct Google API, user's own key)."""
    return _GOOGLE_GEMINI_BASE


def _gemini_api_key() -> str:
    """Return the Gemini API key from GOOGLE_GEMINI_API_KEY env var."""
    key = os.environ.get("GOOGLE_GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError(
            "No Gemini API key available — set GOOGLE_GEMINI_API_KEY"
        )
    return key


def _is_daily_quota_error(status_code: int, body: str) -> bool:
    """Return True when the 429 is a daily/billing cap (retrying won't help)."""
    if status_code != 429:
        return False
    body_lower = body.lower()
    return any(
        phrase in body_lower
        for phrase in ("billing", "plan", "exceeded your current quota", "quota_exceeded")
    )


def _gemini_retry_wait(attempt: int) -> float:
    """Exponential backoff in seconds: 30 → 60 → 120."""
    return 30.0 * (2 ** attempt)


def _call_gemini(user_payload: str, system_prompt: str | None = None) -> _GeminiAuditResponse:
    """
    Send a single audit request to Gemini and return a validated response model.

    Retries up to 3 times with exponential backoff on transient 429 rate-limit
    errors.  Daily/billing quota exhaustion is detected immediately and raises
    without retrying so the caller can fail-open fast.

    Raises RuntimeError on HTTP/parse errors so callers can handle fail-open.
    """
    import time as _time

    api_key = _gemini_api_key()
    prompt = system_prompt or _SYSTEM_PROMPT

    url = f"{_gemini_base_url()}/models/{_GEMINI_MODEL}:generateContent"
    body = {
        "system_instruction": {
            "parts": [{"text": prompt}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": user_payload}]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "maxOutputTokens": 8192,
            "temperature": 0.7,
        },
    }

    _MAX_RETRIES = 3
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = requests.post(
                url,
                headers={
                    "Content-Type":   "application/json",
                    "x-goog-api-key": api_key,
                },
                json=body,
                timeout=90,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"Gemini HTTP request failed: {exc}") from exc

        if resp.status_code == 200:
            break

        if _is_daily_quota_error(resp.status_code, resp.text):
            raise RuntimeError(
                "Gemini daily quota reached — the AI assistant will be "
                "available again tomorrow. No retry attempted."
            )

        if resp.status_code == 429 and attempt < _MAX_RETRIES:
            wait = _gemini_retry_wait(attempt)
            logger.warning(
                f"Gemini rate-limited (attempt {attempt + 1}/{_MAX_RETRIES}), "
                f"retrying in {wait:.0f}s…"
            )
            _time.sleep(wait)
            continue

        raise RuntimeError(
            f"Gemini returned HTTP {resp.status_code}: {resp.text[:300]}"
        )

    token_usage = {}
    try:
        data = resp.json()
        token_usage = data.get("usageMetadata", {})
        raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, ValueError) as exc:
        raise RuntimeError(f"Unexpected Gemini response structure: {exc}") from exc

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Gemini returned non-JSON: {raw_text[:200]}") from exc

    try:
        result = _GeminiAuditResponse(**parsed)
        result._token_usage = token_usage
        return result
    except Exception as exc:
        raise RuntimeError(f"Gemini response failed Pydantic validation: {exc}") from exc


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 ── Database data fetcher
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_audit_data(since: datetime) -> dict[str, Any]:
    """
    Pull previous-day trade and system data from PostgreSQL.

    Parameters
    ----------
    since : datetime
        UTC cut-off; only records on or after this timestamp are fetched.

    Returns
    -------
    dict
        Keys: trades, equity_curve, degradations, performance
    """
    from db.postgres import get_conn, is_pg_available

    if not is_pg_available():
        logger.warning("GeminiAuditor | PostgreSQL unavailable — skipping DB fetch")
        return {}

    since_str = since.isoformat()

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:

                # ── Trades ─────────────────────────────────────────────────
                cur.execute(
                    """
                    SELECT trade_id, date, ticker, asset_class,
                           conviction_score, original_thesis,
                           pnl_percentage, status,
                           intended_price, actual_fill_price
                    FROM trades
                    WHERE date >= %s::date - INTERVAL '1 day'
                    ORDER BY date DESC
                    LIMIT 200
                    """,
                    (since_str,),
                )
                cols   = [d[0] for d in cur.description]
                trades = [dict(zip(cols, row)) for row in cur.fetchall()]

                # ── Equity curve ────────────────────────────────────────────
                cur.execute(
                    """
                    SELECT snapshot_ts AS ts,
                           NULL::DOUBLE PRECISION AS alpaca_equity,
                           NULL::DOUBLE PRECISION AS kraken_equity,
                           SUM(equity_usd)::DOUBLE PRECISION AS total_equity,
                           NULL::TEXT AS regime,
                           'fleet_equity_snapshots'::TEXT AS source
                    FROM fleet_equity_snapshots
                    WHERE snapshot_ts >= %s
                      AND bot_id IN ('oracle', 'spy_qqq_trend', 'jerome_macro')
                    GROUP BY snapshot_ts
                    ORDER BY snapshot_ts ASC
                    LIMIT 500
                    """,
                    (since_str,),
                )
                cols        = [d[0] for d in cur.description]
                equity_rows = [dict(zip(cols, row)) for row in cur.fetchall()]

                # Convert timestamps to strings for JSON serialisation
                for row in equity_rows:
                    if isinstance(row.get("ts"), datetime):
                        row["ts"] = row["ts"].isoformat()

                # ── System degradations ─────────────────────────────────────
                cur.execute(
                    """
                    SELECT ts, component, severity, error_type, message
                    FROM system_degradations
                    WHERE ts >= %s
                    ORDER BY ts DESC
                    LIMIT 100
                    """,
                    (since_str,),
                )
                cols   = [d[0] for d in cur.description]
                degs   = [dict(zip(cols, row)) for row in cur.fetchall()]
                for row in degs:
                    if isinstance(row.get("ts"), datetime):
                        row["ts"] = row["ts"].isoformat()

                # ── Performance snapshots ───────────────────────────────────
                cur.execute(
                    """
                    SELECT date, equity, daily_pnl_pct, cumulative_pnl_pct,
                           win_rate, trades_placed
                    FROM performance_snapshots
                    ORDER BY date DESC
                    LIMIT 14
                    """,
                )
                cols  = [d[0] for d in cur.description]
                perf  = [dict(zip(cols, row)) for row in cur.fetchall()]
                for row in perf:
                    if hasattr(row.get("date"), "isoformat"):
                        row["date"] = str(row["date"])

        return {
            "trades":       trades,
            "equity_curve": equity_rows,
            "degradations": degs,
            "performance":  perf,
        }

    except Exception as exc:
        logger.warning(f"GeminiAuditor | DB fetch error: {exc}")
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 ── Chunked merge helper
# ══════════════════════════════════════════════════════════════════════════════

def _merge_responses(responses: list[_GeminiAuditResponse]) -> _GeminiAuditResponse:
    """
    Merge multiple chunk-level responses into a single consolidated result.

    Merging rules
    -------------
    • vetoed_tickers : union of all sets
    • conditions     : union, deduplicated by (type, value, ticker)
    • critique_flags : all flags concatenated
    • critique_summary: summary from the chunk with the most flags
    • overall_verdict : highest severity wins (HOLD > CAUTION > CLEAN)
    """
    if not responses:
        return _GeminiAuditResponse()
    if len(responses) == 1:
        return responses[0]

    _SEVERITY = {"CLEAN": 0, "CAUTION": 1, "HOLD": 2}
    _REVERSE  = {0: "CLEAN", 1: "CAUTION", 2: "HOLD"}

    tickers:    set[str]       = set()
    cond_keys:  set[tuple]     = set()
    conditions: list[_GeminiCondition] = []
    flags:      list[str]      = []
    max_severity               = 0
    best_summary               = ""
    most_flags                 = 0

    for r in responses:
        tickers.update(r.vetoed_tickers)
        for c in r.conditions:
            key = (c.type, c.value, c.ticker)
            if key not in cond_keys:
                cond_keys.add(key)
                conditions.append(c)
        flags.extend(r.critique_flags)
        sev = _SEVERITY.get(r.overall_verdict, 1)
        if sev > max_severity:
            max_severity = sev
        if len(r.critique_flags) > most_flags:
            most_flags    = len(r.critique_flags)
            best_summary  = r.critique_summary

    return _GeminiAuditResponse(
        vetoed_tickers  = sorted(tickers),
        conditions      = conditions,
        critique_summary= best_summary,
        critique_flags  = flags,
        overall_verdict = _REVERSE.get(max_severity, "CAUTION"),
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 ── Atomic file writer
# ══════════════════════════════════════════════════════════════════════════════

def _write_veto_file(result: _GeminiAuditResponse, generated_at: datetime) -> None:
    """
    Atomically write the veto_conditions.json file.

    Uses a temp-file + rename strategy so the executor never reads a
    partially-written file (POSIX rename is atomic on the same filesystem).
    """
    valid_until = generated_at + timedelta(hours=24)
    payload = {
        "generated_at":   generated_at.isoformat(),
        "valid_until":    valid_until.isoformat(),
        "vetoed_tickers": result.vetoed_tickers,
        "conditions":     [c.model_dump(exclude_none=True) for c in result.conditions],
        "critique_summary": result.critique_summary,
        "critique_flags": result.critique_flags,
        "overall_verdict": result.overall_verdict,
    }
    serialised = json.dumps(payload, indent=2, default=str)

    # Write to temp file in the same directory as the target, then rename.
    # Using the target file's parent ensures the rename is always on the same
    # filesystem (no cross-device link error).
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=_VETO_FILE.parent, prefix=".veto_conditions_", suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            f.write(serialised)
        os.replace(tmp_path, _VETO_FILE)  # atomic rename
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 ── Public entry point
# ══════════════════════════════════════════════════════════════════════════════

def run_daily_self_critic() -> dict[str, Any]:
    """
    Main entry point — called by the 04:15 ET scheduler job.

    Returns a status dict suitable for logging and the admin API endpoint.

    On any error, logs a WARNING and returns a failure dict without writing
    the veto file (fail-open: trading proceeds normally).
    """
    started_at = datetime.now(timezone.utc)
    logger.info("GeminiAuditor | Starting daily self-critic run")

    if not (os.environ.get("AI_INTEGRATIONS_GEMINI_API_KEY") or os.environ.get("GOOGLE_GEMINI_API_KEY")):
        logger.warning("GeminiAuditor | No Gemini API key set — skipping")
        return {"status": "skipped", "reason": "env_vars_missing"}

    # ── Fetch DB data ─────────────────────────────────────────────────────────
    since = started_at - timedelta(hours=_LOOKBACK_HOURS)
    audit_data = _fetch_audit_data(since)

    if not audit_data:
        logger.warning("GeminiAuditor | No data fetched from DB — skipping")
        return {"status": "skipped", "reason": "no_data"}

    # ── Sanitize context ──────────────────────────────────────────────────────
    full_context = sanitize_daily_context(audit_data)
    token_est    = estimate_tokens(full_context)
    logger.info(f"GeminiAuditor | Context size: {len(full_context):,} chars "
                f"≈ {token_est:,} tokens (budget={TOKEN_BUDGET:,})")

    # ── Choose single-call vs chunked path ────────────────────────────────────
    responses: list[_GeminiAuditResponse] = []

    if token_est < CHUNK_THRESHOLD:
        # ── Single call ───────────────────────────────────────────────────────
        logger.info("GeminiAuditor | Payload within budget — single Gemini call")
        try:
            resp = _call_gemini(full_context)
            responses.append(resp)
        except RuntimeError as exc:
            logger.warning(f"GeminiAuditor | Gemini call failed: {exc} — aborting (fail-open)")
            return {"status": "failed", "reason": str(exc)}

    else:
        # ── Chunked path ──────────────────────────────────────────────────────
        # Primary time-series for chunking: equity_curve.
        # Fallback: if equity_curve is absent or has no parseable timestamps,
        # use trade records (also time-ordered).
        equity_records = audit_data.get("equity_curve", [])
        chunks = chunk_by_hours(equity_records, hours_per_chunk=8, ts_key="ts")

        if not chunks:
            # Try falling back to trades (keyed by "date", not "ts")
            trade_records = audit_data.get("trades", [])
            chunks = chunk_by_hours(trade_records, hours_per_chunk=8, ts_key="date")

        if not chunks:
            # Both time-series sources are empty or un-timestamped — treat
            # the full context as a single oversized chunk and let Gemini
            # handle it (it will stay within model context limits at 720K+ chars).
            logger.warning(
                "GeminiAuditor | No chunkable time-series found — "
                "sending full context as single chunk"
            )
            chunks = [equity_records or audit_data.get("trades", [])]

        num_chunks = len(chunks)
        logger.info(
            f"GeminiAuditor | Adaptive chunking: splitting into {num_chunks} 8-hour blocks "
            f"(inter-chunk delay: {_GEMINI_CALL_DELAY_SEC:.0f}s)"
        )

        for idx, chunk in enumerate(chunks, start=1):
            # Reconstruct the full data dict with the current chunk's time-series
            # so Gemini sees trades, degradations and performance in every call.
            chunk_data = {
                **audit_data,
                "equity_curve": chunk,
                "_chunk_info": f"{idx}/{num_chunks}",
            }
            chunk_ctx = sanitize_daily_context(chunk_data)
            logger.info(
                f"GeminiAuditor | Block {idx}/{num_chunks}: "
                f"{estimate_tokens(chunk_ctx):,} tokens"
            )
            try:
                resp = _call_gemini(chunk_ctx)
                responses.append(resp)
            except RuntimeError as exc:
                logger.warning(
                    f"GeminiAuditor | Block {idx} Gemini call failed: {exc} — aborting"
                )
                return {"status": "failed", "reason": str(exc), "chunk": idx}

            if idx < num_chunks:
                time.sleep(_GEMINI_CALL_DELAY_SEC)

    # ── Merge + write ─────────────────────────────────────────────────────────
    final = _merge_responses(responses)

    try:
        _write_veto_file(final, generated_at=started_at)
    except Exception as exc:
        logger.warning(f"GeminiAuditor | Failed to write veto file: {exc} — aborting")
        return {"status": "failed", "reason": f"write_error: {exc}"}

    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
    logger.info(
        f"GeminiAuditor | Complete in {elapsed:.1f}s — "
        f"verdict={final.overall_verdict} "
        f"vetoed={final.vetoed_tickers} "
        f"flags={len(final.critique_flags)}"
    )

    return {
        "status":          "ok",
        "overall_verdict": final.overall_verdict,
        "vetoed_tickers":  final.vetoed_tickers,
        "condition_count": len(final.conditions),
        "flag_count":      len(final.critique_flags),
        "elapsed_seconds": round(elapsed, 1),
        "generated_at":    started_at.isoformat(),
    }


def get_last_gemini_audit() -> dict[str, Any]:
    """
    Return the contents of the most recent veto_conditions.json, or a
    'not_run' status if the file does not exist.

    Used by the GET /admin/gemini-audit-status endpoint.
    """
    if not _VETO_FILE.exists():
        return {
            "status":       "not_run",
            "message":      "Gemini self-critic has not run yet today",
            "file_exists":  False,
        }

    try:
        data = json.loads(_VETO_FILE.read_text())
        data["status"]      = "ok"
        data["file_exists"] = True
        return data
    except Exception as exc:
        return {
            "status":       "error",
            "message":      f"Could not parse veto_conditions.json: {exc}",
            "file_exists":  True,
        }
