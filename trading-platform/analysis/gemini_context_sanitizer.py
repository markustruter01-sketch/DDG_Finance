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
TOKEN_BUDGET:     int = 900_000
CHUNK_THRESHOLD:  int = int(TOKEN_BUDGET * 0.80)   # 720_000 chars before chunking
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


def sanitize_daily_context(raw_dict: dict) -> str:
    """
    Convert raw trading data into a compact, sanitized JSON string suitable
    for inclusion in a Gemini prompt.

    Steps
    -----
    1. Clean each value recursively (strip markup, round floats, drop empties).
    2. Deduplicate news headlines (exact-match; keep first occurrence).
    3. Serialise to compact JSON (no indent, sorted keys for diff stability).

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
    # Deep-clean the payload
    cleaned: dict[str, Any] = {}
    for key, val in raw_dict.items():
        cv = _clean_value(val)
        if cv is not None:
            cleaned[key] = cv

    # Deduplicate news headlines (exact match)
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
