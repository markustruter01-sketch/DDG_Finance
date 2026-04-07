"""
analysis/gemini_context_sanitizer.py  —  Gemini Self-Critic Context Sanitizer
==============================================================================
Prepares trading platform data for the Gemini daily self-critic auditor.

Responsibilities:
  • sanitize_daily_context(raw_dict)  — compact, deduplicated text payload
  • estimate_tokens(text)             — fast character-ratio estimator
  • chunk_by_hours(records, n)        — split time-series into 8-hour windows

Token budget
------------
  TOKEN_BUDGET  = 900_000   (90 % of Gemini 1.5 Flash 1 M-token context)
  CHUNK_THRESHOLD = 720_000 (80 % of budget; triggers chunking if exceeded)

Sanitization contract
---------------------
  • Strips HTML/Markdown from thesis strings
  • Deduplicates news headlines by exact match (keeps first occurrence)
  • Truncates very long strings to _MAX_STR_LEN characters
  • Rounds floats to 4 decimal places for compactness
  • Omits None / empty values to reduce noise
"""

from __future__ import annotations

import re
import json
from datetime import datetime, timezone, timedelta
from typing import Any


# ── Token budget constants ─────────────────────────────────────────────────────
# Claude has a 200k-token context window (~4 chars/token → ~800k chars).
# TOKEN_BUDGET is set to 800k chars (200k tokens) — a reduction from the
# former Gemini 900k budget.  CHUNK_THRESHOLD triggers chunking at 80%.
TOKEN_BUDGET:     int = 800_000
CHUNK_THRESHOLD:  int = int(TOKEN_BUDGET * 0.80)   # 640_000 chars before chunking
CHARS_PER_TOKEN:  int = 4                           # conservative 4-char/token ratio
_MAX_STR_LEN:     int = 400                         # max chars for any single string field


# ── HTML / Markdown stripping ──────────────────────────────────────────────────
_HTML_TAG_RE   = re.compile(r"<[^>]+>")
_MD_BOLD_RE    = re.compile(r"\*{1,2}([^*]+)\*{1,2}")
_MD_LINK_RE    = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_WHITESPACE_RE = re.compile(r"\s{2,}")


def _strip_markup(text: str) -> str:
    """Remove HTML tags and common Markdown decorators from *text*."""
    text = _HTML_TAG_RE.sub(" ", text)
    text = _MD_BOLD_RE.sub(r"\1", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def _clean_value(v: Any) -> Any:
    """
    Recursively clean a JSON-serialisable value:
      - strip markup from strings and truncate
      - round floats to 4 dp
      - drop None / empty containers
    """
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, str):
        cleaned = _strip_markup(v)
        return cleaned[:_MAX_STR_LEN] if len(cleaned) > _MAX_STR_LEN else cleaned
    if isinstance(v, dict):
        result = {
            k: _clean_value(val)
            for k, val in v.items()
            if val is not None and val != "" and val != [] and val != {}
        }
        return result or None
    if isinstance(v, list):
        cleaned = [_clean_value(item) for item in v if item is not None]
        return cleaned or None
    return v


# ── Public helpers ─────────────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """
    Fast character-ratio token estimator.

    Uses 4 chars-per-token (conservative; GPT-4 / Gemini average is ~3.5 for
    English prose, higher for JSON with lots of punctuation).

    Parameters
    ----------
    text : str
        The serialised context string whose token count is needed.

    Returns
    -------
    int
        Estimated token count.
    """
    return len(text) // CHARS_PER_TOKEN


# ── Compact row summarizers ───────────────────────────────────────────────────
# These convert structured DB row dicts into single-line strings, drastically
# reducing token count vs. verbose JSON and removing structural noise.

def _compact_trade(row: dict) -> str:
    """Trade record → "AAPL Closed_Win +2.5% conv=0.78 [2026-03-29]"."""
    ticker  = row.get("ticker", "?")
    status  = row.get("status", "?")
    pnl     = row.get("pnl_percentage")
    conv    = row.get("conviction_score")
    date    = row.get("date", "")
    pnl_s   = f"{float(pnl):+.2f}%" if pnl is not None else "n/a"
    conv_s  = f"conv={float(conv):.2f}" if conv is not None else ""
    thesis  = row.get("original_thesis", "")
    if thesis:
        thesis = _strip_markup(str(thesis))[:120]
        thesis = f' "{thesis}"'
    return f"{ticker} {status} {pnl_s} {conv_s} [{date}]{thesis}".strip()


def _compact_equity(row: dict) -> str:
    """Equity snapshot → "2026-03-29T10:00Z eq=100000.0 reg=Bull src=pipeline"."""
    ts    = str(row.get("ts", ""))[:19]
    eq    = row.get("total_equity") or row.get("alpaca_equity")
    reg   = row.get("regime", "")
    src   = row.get("source", "")
    eq_s  = f"eq={float(eq):.2f}" if eq is not None else ""
    reg_s = f"reg={reg}" if reg else ""
    src_s = f"src={src}" if src else ""
    return " ".join(p for p in [ts, eq_s, reg_s, src_s] if p)


def _compact_degradation(row: dict) -> str:
    """Degradation event → "2026-03-29T10:00Z platform_core critical stale_data"."""
    ts       = str(row.get("ts", ""))[:19]
    comp     = row.get("component", "")
    severity = row.get("severity", "")
    err_type = row.get("error_type", "")
    msg      = _strip_markup(str(row.get("message", "")))[:80]
    return " ".join(p for p in [ts, comp, severity, err_type, f'"{msg}"'] if p)


def _compact_performance(row: dict) -> str:
    """Performance row → "2026-03-29 pnl=+1.5% wr=65% trades=5 eq=100000"."""
    date     = str(row.get("date", ""))
    pnl      = row.get("daily_pnl_pct")
    wr       = row.get("win_rate")
    trades   = row.get("trades_placed")
    equity   = row.get("equity")
    pnl_s    = f"pnl={float(pnl):+.2f}%" if pnl is not None else ""
    wr_s     = f"wr={float(wr)*100:.1f}%" if wr is not None else ""
    trades_s = f"trades={trades}" if trades is not None else ""
    eq_s     = f"eq={float(equity):.0f}" if equity is not None else ""
    return " ".join(p for p in [date, pnl_s, wr_s, trades_s, eq_s] if p)


# Mapping: key in raw_dict → compact converter function
_COMPACT_CONVERTERS: dict[str, Any] = {
    "trades":       _compact_trade,
    "equity_curve": _compact_equity,
    "degradations": _compact_degradation,
    "performance":  _compact_performance,
}


def sanitize_daily_context(raw_dict: dict) -> str:
    """
    Convert raw trading data into a compact, sanitized JSON string suitable
    for inclusion in a Gemini prompt.

    Steps
    -----
    1. For known DB-row list keys (trades, equity_curve, degradations,
       performance), replace each row dict with a compact one-line summary
       string — drastically reducing token count vs. verbose JSON.
    2. Clean all remaining values recursively (strip markup, round floats,
       drop empty/None values).
    3. Deduplicate news headlines (exact-match; keep first occurrence).
    4. Serialise to compact JSON (no indent, sorted keys for diff stability).

    Parameters
    ----------
    raw_dict : dict
        Arbitrary dict containing:
          - trades        : list of trade records
          - equity_curve  : list of equity snapshot records
          - degradations  : list of system degradation events
          - performance   : list of daily performance rows
          - news_headlines: list of str (optional)

    Returns
    -------
    str
        Compact JSON string ready for token estimation or Gemini injection.
    """
    cleaned: dict[str, Any] = {}

    for key, val in raw_dict.items():
        # ── Known DB-row lists: compact to one-liners ─────────────────────────
        if key in _COMPACT_CONVERTERS and isinstance(val, list):
            converter = _COMPACT_CONVERTERS[key]
            summaries = []
            for row in val:
                if isinstance(row, dict):
                    try:
                        summaries.append(converter(row))
                    except Exception:
                        # Fall back to light clean if converter fails
                        cv = _clean_value(row)
                        if cv:
                            summaries.append(cv)
                elif row is not None:
                    summaries.append(row)
            if summaries:
                cleaned[key] = summaries
            continue

        # ── All other values: deep-clean ──────────────────────────────────────
        cv = _clean_value(val)
        if cv is not None:
            cleaned[key] = cv

    # ── Deduplicate news headlines ────────────────────────────────────────────
    if "news_headlines" in cleaned and isinstance(cleaned["news_headlines"], list):
        seen: set[str] = set()
        deduped: list[str] = []
        for headline in cleaned["news_headlines"]:
            norm = str(headline).lower().strip()
            if norm not in seen:
                seen.add(norm)
                deduped.append(headline)
        cleaned["news_headlines"] = deduped

    return json.dumps(cleaned, separators=(",", ":"), sort_keys=True)


def chunk_by_hours(
    records: list[dict],
    hours_per_chunk: int = 8,
    ts_key: str = "ts",
) -> list[list[dict]]:
    """
    Split a chronological list of time-stamped records into fixed-duration
    windows for token-budget-safe sequential Gemini processing.

    Records without a recognisable timestamp are appended to the final chunk.

    Parameters
    ----------
    records : list[dict]
        Time-ordered list of records, each containing a timestamp field.
    hours_per_chunk : int
        Duration of each window in hours (default 8 → three windows per day).
    ts_key : str
        Name of the timestamp field inside each record (default "ts").

    Returns
    -------
    list[list[dict]]
        Non-empty sub-lists in chronological order.  Always returns at least
        one element (the full list) even when no timestamps are parseable.
    """
    if not records:
        return []

    window_delta = timedelta(hours=hours_per_chunk)
    parsed: list[tuple[datetime | None, dict]] = []
    no_ts: list[dict] = []

    for rec in records:
        raw_ts = rec.get(ts_key)
        dt: datetime | None = None
        if raw_ts is not None:
            try:
                if isinstance(raw_ts, datetime):
                    dt = raw_ts if raw_ts.tzinfo else raw_ts.replace(tzinfo=timezone.utc)
                else:
                    dt = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                dt = None
        if dt is None:
            no_ts.append(rec)
        else:
            parsed.append((dt, rec))

    if not parsed:
        return [records]  # nothing parseable → single chunk

    # Sort by timestamp
    parsed.sort(key=lambda x: x[0])  # type: ignore[index]

    chunks: list[list[dict]] = []
    current_chunk: list[dict] = []
    window_start: datetime = parsed[0][0]  # type: ignore[assignment]

    for dt, rec in parsed:
        if dt >= window_start + window_delta:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = [rec]
            window_start = dt
        else:
            current_chunk.append(rec)

    if current_chunk:
        chunks.append(current_chunk)

    # Append un-timestamped records to the last chunk
    if no_ts:
        if chunks:
            chunks[-1].extend(no_ts)
        else:
            chunks.append(no_ts)

    return [c for c in chunks if c]
