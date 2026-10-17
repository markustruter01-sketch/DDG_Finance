"""Forex AI council (Phase 4, SHADOW ONLY): two council members and a decision-maker.

Security plan (registered plan item 8) enforced here:
- One-way HTTPS only, plain httpx, hard-coded host allowlist, no redirects.
- Each provider call gets only its own key, sent in a header, never in a URL.
  Errors are sanitised so a key can never reach a log.
- Outbound pack is built from typed fields only: shuffled pair labels, rounded
  relative numbers, no dates, no account data. A scanner blocks any call whose
  payload contains key-, URL- or email-like text.
- Replies are data: strict JSON, every field enum- or range-checked, reasons
  capped and stripped. Only structured fields pass from council to decision-maker.
- Any failure fails closed: no AI decision means no trade for that pair/day.

This module never places orders and never touches the database.
"""

from __future__ import annotations

import json
import os
import random
import re
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from forex_quant_desk import FOREX_PAIRS

# ── Registered configuration ────────────────────────────────────────────────

ALLOWED_HOSTS = frozenset(
    {"api.groq.com", "openrouter.ai", "generativelanguage.googleapis.com"}
)
TIMEOUT_SECONDS = 90.0
# Explicit client name: some provider firewalls reject default library agents.
USER_AGENT = "ddg-forex-council/1.0"
MAX_RESPONSE_CHARS = 20_000
REASON_MAX_CHARS = 200
DIRECTIONS = ("long", "short", "flat")
CONVICTION_RANGE = (1, 5)
STOP_ATR_RANGE = (1.0, 4.0)

PROVIDERS: dict[str, dict[str, Any]] = {
    "member_1": {
        "provider": "groq",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        # llama-3.3-70b-versatile no longer offered on this Groq account (404,
        # 10 Oct 2026). Pending Markus's confirmation: OpenAI open-weight model.
        "model": "openai/gpt-oss-120b",
        "key_env": "GROQ_API_KEY",
        "max_tokens": 4000,
    },
    "member_2": {
        "provider": "openrouter",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        # Registered plan item 1 (amended 10 Oct 2026, Markus option A).
        "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
        # Pinned host (OpenRouter provider tag); fallbacks off. Empty = refuse.
        "provider_only": ["nvidia"],
        "key_env": "OPENROUTER_API_KEY",
        # Reasoning model: room for its answer after any hidden reasoning.
        "max_tokens": 4000,
    },
    "decision_maker": {
        "provider": "gemini",
        "url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        "model": "gemini-3-flash-preview",
        "key_env": "GOOGLE_GEMINI_API_KEY",
        # Gemini 3 counts hidden thinking against this cap; 1500 truncated the
        # JSON in the 11 Oct dry run.
        "max_tokens": 8192,
    },
}


class CouncilError(RuntimeError):
    """A council step failed; the message is safe to log."""


# ── Outbound pack (allowlist) ───────────────────────────────────────────────

PACK_PAIR_FIELDS = (
    "label", "trend", "momentum_63d_pct", "momentum_20d_pct", "atr_pct",
    "realised_vol_pct", "carry_long_pct", "carry_short_pct", "spread_to_atr",
    "open_position",
)
PACK_TOP_FIELDS = ("pairs", "calendar", "news")

_BLOCK_PATTERNS = (
    re.compile(r"(sk|gsk|rk|pk)[-_][A-Za-z0-9]{8,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{10,}"),
    re.compile(r"(ghp|gho|github_pat)_[A-Za-z0-9_]{10,}"),
    re.compile(r"[a-z]+://", re.IGNORECASE),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    re.compile(r"[A-Za-z0-9+/=_\-]{40,}"),
    re.compile(r"\b(19|20)\d\d-\d\d-\d\d\b"),
    re.compile(r"\b(EUR|USD|JPY|GBP|AUD|CAD|CHF|NZD)\b"),
)


def _pct(value: float | None, places: int = 2) -> float | None:
    return None if value is None else round(value * 100, places)


def build_pack(
    sheet_rows: list[dict[str, Any]],
    open_positions: dict[str, str] | None = None,
    *,
    rng: random.Random | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Return (anonymised pack, label -> pair map). The map never leaves DDG."""
    usable = [row for row in sheet_rows if "error" not in row]
    labels = [chr(ord("A") + i) for i in range(len(usable))]
    (rng or random.SystemRandom()).shuffle(usable)
    open_positions = open_positions or {}
    pairs, label_map = [], {}
    for label, row in zip(labels, usable):
        label_map[label] = row["pair"]
        carry = row["carry"]
        pairs.append({
            "label": label,
            "trend": row["trend"],
            "momentum_63d_pct": _pct(row["momentum_return"]),
            "momentum_20d_pct": _pct(row["short_momentum_return"]),
            "atr_pct": _pct(row["atr_pct"], 3),
            "realised_vol_pct": _pct(row["realised_vol"], 1),
            "carry_long_pct": _pct(carry["long_rate"]),
            "carry_short_pct": _pct(carry["short_rate"]),
            "spread_to_atr": None if row["spread_to_atr"] is None else round(row["spread_to_atr"], 3),
            "open_position": open_positions.get(row["pair"], "none"),
        })
    pairs.sort(key=lambda p: p["label"])
    pack = {"pairs": pairs, "calendar": "unavailable", "news": "unavailable"}
    validate_pack(pack)
    return pack, label_map


def validate_pack(pack: dict[str, Any]) -> None:
    """Block any pack that is not exactly the registered shape."""
    if tuple(pack.keys()) != PACK_TOP_FIELDS:
        raise CouncilError("pack has fields outside the allowlist")
    for pair in pack["pairs"]:
        if tuple(pair.keys()) != PACK_PAIR_FIELDS:
            raise CouncilError("pack pair has fields outside the allowlist")
        if not re.fullmatch(r"[A-G]", pair["label"]):
            raise CouncilError("pack label must be a single letter A-G")
        if pair["trend"] not in ("up", "down", "flat"):
            raise CouncilError("pack trend outside allowed values")
        if pair["open_position"] not in ("none", "long", "short"):
            raise CouncilError("pack open_position outside allowed values")
        for field in PACK_PAIR_FIELDS[2:9]:
            value = pair[field]
            if value is not None and not isinstance(value, (int, float)):
                raise CouncilError(f"pack {field} must be a number or null")
    for field in ("calendar", "news"):
        if pack[field] != "unavailable":
            raise CouncilError(f"pack {field} must be 'unavailable' until a source is approved")
    scan_outbound(json.dumps(pack))


def scan_outbound(text: str) -> None:
    for pattern in _BLOCK_PATTERNS:
        if pattern.search(text):
            raise CouncilError("outbound payload blocked by the secret/identity scanner")


# ── Prompts ─────────────────────────────────────────────────────────────────

_COMMON = (
    "You are a currency analyst. You get a table of anonymised currency pairs "
    "(labels A-G) with relative numbers only: trend vs a long average, 63-day and "
    "20-day returns in percent, average daily range (atr_pct), realised volatility, "
    "annual financing for holding long or short in percent, spread relative to the "
    "daily range, and any open position. Holding period is days to weeks. "
    "Use only the numbers given. Reply with JSON only, no other text."
)

COUNCIL_SYSTEM = _COMMON + (
    ' Give one call per label: {"calls":[{"label":"A","direction":"long|short|flat",'
    '"conviction":1-5,"reason":"max 200 characters"}]}.'
)

DECISION_SYSTEM = _COMMON + (
    " You also get two independent council views per label. Make the final call per label. "
    'Reply: {"decisions":[{"label":"A","direction":"long|short|flat","conviction":1-5,'
    '"stop_atr_multiple":1.0-4.0,"sided_with":"member_1|member_2|both|neither",'
    '"reason":"max 200 characters, say why this view over the other"}]}.'
)


# ── Reply validation ────────────────────────────────────────────────────────

_STRIP = re.compile(r"(https?://\S+|www\.\S+|`+|<[^>]*>|[{}\[\]])", re.IGNORECASE)


_REDACT = re.compile(
    r"\b(EUR|USD|JPY|GBP|AUD|CAD|CHF|NZD|(19|20)\d\d-\d\d-\d\d)\b|[A-Za-z0-9+/=_\-]{40,}"
)


def clean_reason(value: Any) -> str:
    """Strip links/code and redact currency codes, dates and long tokens, so a
    model's text can neither de-anonymise the pack nor smuggle data onward."""
    text = _STRIP.sub("", str(value or "")).replace("\n", " ")
    text = _REDACT.sub("[x]", text).strip()
    return text[:REASON_MAX_CHARS]


def _int_in(value: Any, lo: int, hi: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise CouncilError(f"{field} must be an integer {lo}-{hi}")
    return value


def parse_council_reply(raw: str, labels: list[str]) -> list[dict[str, Any]]:
    data = _json_object(raw)
    calls = data.get("calls")
    if set(data) != {"calls"} or not isinstance(calls, list):
        raise CouncilError("council reply must be {calls:[...]}")
    parsed = {}
    for call in calls:
        if not isinstance(call, dict) or set(call) != {"label", "direction", "conviction", "reason"}:
            raise CouncilError("council call has wrong fields")
        if call["label"] not in labels or call["label"] in parsed:
            raise CouncilError("council call label unknown or repeated")
        if call["direction"] not in DIRECTIONS:
            raise CouncilError("council direction invalid")
        parsed[call["label"]] = {
            "label": call["label"],
            "direction": call["direction"],
            "conviction": _int_in(call["conviction"], *CONVICTION_RANGE, "conviction"),
            "reason": clean_reason(call["reason"]),
        }
    if set(parsed) != set(labels):
        raise CouncilError("council reply must cover every label exactly once")
    return [parsed[label] for label in labels]


def parse_decision_reply(raw: str, labels: list[str]) -> list[dict[str, Any]]:
    data = _json_object(raw)
    decisions = data.get("decisions")
    if set(data) != {"decisions"} or not isinstance(decisions, list):
        raise CouncilError("decision reply must be {decisions:[...]}")
    keys = {"label", "direction", "conviction", "stop_atr_multiple", "sided_with", "reason"}
    parsed = {}
    for item in decisions:
        if not isinstance(item, dict) or set(item) != keys:
            raise CouncilError("decision has wrong fields")
        if item["label"] not in labels or item["label"] in parsed:
            raise CouncilError("decision label unknown or repeated")
        if item["direction"] not in DIRECTIONS:
            raise CouncilError("decision direction invalid")
        if item["sided_with"] not in ("member_1", "member_2", "both", "neither"):
            raise CouncilError("decision sided_with invalid")
        stop = item["stop_atr_multiple"]
        if isinstance(stop, bool) or not isinstance(stop, (int, float)) or not (
            STOP_ATR_RANGE[0] <= stop <= STOP_ATR_RANGE[1]
        ):
            raise CouncilError("stop_atr_multiple out of range")
        parsed[item["label"]] = {
            "label": item["label"],
            "direction": item["direction"],
            "conviction": _int_in(item["conviction"], *CONVICTION_RANGE, "conviction"),
            "stop_atr_multiple": float(stop),
            "sided_with": item["sided_with"],
            "reason": clean_reason(item["reason"]),
        }
    if set(parsed) != set(labels):
        raise CouncilError("decision reply must cover every label exactly once")
    return [parsed[label] for label in labels]


def _json_object(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str) or len(raw) > MAX_RESPONSE_CHARS:
        raise CouncilError("reply missing or too long")
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(text)
    except ValueError:
        # Tolerate prose around a single JSON object; the schema check that
        # follows still rejects anything that is not exactly the right shape.
        start, end = text.find("{"), text.rfind("}")
        try:
            data = json.loads(text[start:end + 1]) if 0 <= start < end else None
        except ValueError:
            data = None
        if data is None:
            raise CouncilError(f"reply is not valid JSON (length {len(text)})") from None
    if not isinstance(data, dict):
        raise CouncilError("reply must be a JSON object")
    return data


# ── Provider calls (one-way, allowlisted) ───────────────────────────────────

Transport = Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]


def _http_post(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    if urlparse(url).hostname not in ALLOWED_HOSTS or not url.startswith("https://"):
        raise CouncilError("destination host is not on the allowlist")
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
            response = client.post(url, headers=headers, json=body)
    except Exception as exc:
        # Only the exception's class name (e.g. ReadTimeout, ConnectError) is kept:
        # it says why the call failed without carrying URLs, headers or keys.
        raise CouncilError(f"provider request failed ({type(exc).__name__})") from None
    if not 200 <= response.status_code < 300:
        raise CouncilError(f"provider returned HTTP {response.status_code}")
    try:
        payload = response.json()
    except Exception:
        raise CouncilError("provider returned invalid JSON") from None
    if not isinstance(payload, dict):
        raise CouncilError("provider returned an invalid response")
    return payload


def _request(role: str, system: str, user: str) -> tuple[str, dict[str, str], dict[str, Any]]:
    cfg = PROVIDERS[role]
    if not cfg["model"]:
        raise CouncilError(f"{role} model not configured")
    key = os.environ.get(cfg["key_env"], "").strip()
    if not key:
        raise CouncilError(f"{role} key not configured")
    if cfg["provider"] == "gemini":
        url = cfg["url"].format(model=cfg["model"])
        headers = {
            "x-goog-api-key": key,
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.2,
                "maxOutputTokens": cfg["max_tokens"],
            },
        }
        return url, headers, body
    body = {
        "model": cfg["model"],
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": cfg["max_tokens"],
    }
    if cfg["provider"] == "openrouter":
        if not cfg["provider_only"]:
            raise CouncilError("member_2 hosts not pinned; refusing to route")
        # The pinned endpoint does not list response_format; the strict parser
        # still rejects anything that is not the exact JSON schema.
        body["provider"] = {"only": list(cfg["provider_only"]), "allow_fallbacks": False}
        body["include_reasoning"] = False
    else:
        body["response_format"] = {"type": "json_object"}
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    return cfg["url"], headers, body


def _reply_text(provider: str, payload: dict[str, Any]) -> tuple[str, dict[str, int | None]]:
    try:
        if provider == "gemini":
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
            meta = payload.get("usageMetadata") or {}
            usage = {"in": meta.get("promptTokenCount"), "out": meta.get("candidatesTokenCount")}
        else:
            text = payload["choices"][0]["message"]["content"]
            meta = payload.get("usage") or {}
            usage = {"in": meta.get("prompt_tokens"), "out": meta.get("completion_tokens")}
    except (KeyError, IndexError, TypeError):
        raise CouncilError(f"provider reply missing message text ({_reply_hint(payload)})") from None
    if not isinstance(text, str) or not text.strip():
        raise CouncilError(f"provider reply text is empty ({_reply_hint(payload)})")
    return text[:MAX_RESPONSE_CHARS], usage


def _reply_hint(payload: dict[str, Any]) -> str:
    """Safe, short reason for an empty reply: finish reason and provider error
    code only (never content)."""
    hint = []
    try:
        hint.append(f"finish={payload['choices'][0].get('finish_reason')}")
    except (KeyError, IndexError, TypeError, AttributeError):
        pass
    try:
        hint.append(f"finish={payload['candidates'][0].get('finishReason')}")
    except (KeyError, IndexError, TypeError, AttributeError):
        pass
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        hint.append(f"error_code={str(error.get('code'))[:40]}")
    return ", ".join(hint) or "no detail"


def call_model(
    role: str, system: str, user: str, *, transport: Transport | None = None,
) -> dict[str, Any]:
    """One provider call. Returns a ledger-ready record; raises CouncilError."""
    url, headers, body = _request(role, system, user)
    scan_outbound(user)
    # At most one retry (framework token-discipline rule 7).
    for attempt in (1, 2):
        try:
            payload = (transport or _http_post)(url, headers, body)
            text, usage = _reply_text(PROVIDERS[role]["provider"], payload)
            break
        except CouncilError:
            if attempt == 2:
                raise
    return {
        "role": role,
        "provider": PROVIDERS[role]["provider"],
        "model": PROVIDERS[role]["model"],
        "request": {"system": system, "user": user},
        "raw": text,
        "usage": usage,
    }


# ── One shadow cycle ────────────────────────────────────────────────────────

def _call_and_parse(role, system, user, parse, labels, record, transport):
    """Call a model and parse its reply; on a malformed reply, ask once more
    (one format-repair attempt). Every attempt is kept in the record."""
    for attempt in (1, 2):
        call = call_model(role, system, user, transport=transport)
        call["attempt"] = attempt
        record["calls"].append(call)
        try:
            return parse(call["raw"], labels)
        except CouncilError as exc:
            if attempt == 2:
                raise
            record["errors"].append(f"{role}: attempt 1 {exc}; retrying once")

def run_council(
    sheet_rows: list[dict[str, Any]],
    open_positions: dict[str, str] | None = None,
    *,
    transport: Transport | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Run members 1 and 2, then the decision-maker. Never raises; every failure
    is recorded and fails closed. Returns the full cycle record for the ledger."""
    record: dict[str, Any] = {"calls": [], "errors": [], "decisions": [], "status": "no_trade"}
    baseline = {r["pair"]: r["baseline"]["direction"] for r in sheet_rows}
    record["baseline"] = baseline
    try:
        pack, label_map = build_pack(sheet_rows, open_positions, rng=rng)
    except CouncilError as exc:
        record["errors"].append(f"pack: {exc}")
        return record
    record["pack"], record["label_map"] = pack, label_map
    labels = sorted(label_map)
    if not labels:
        record["errors"].append("pack: no usable pairs")
        return record
    user = json.dumps(pack, separators=(",", ":"))

    views: dict[str, list[dict[str, Any]]] = {}
    for role in ("member_1", "member_2"):
        try:
            views[role] = _call_and_parse(
                role, COUNCIL_SYSTEM, user, parse_council_reply, labels, record, transport,
            )
        except CouncilError as exc:
            record["errors"].append(f"{role}: {exc}")
    if not views:
        record["errors"].append("both council members unavailable: no new trades")
        return record
    record["low_confidence"] = len(views) == 1

    council_input = json.dumps(
        {"pack": pack, "council": {role: views[role] for role in views}},
        separators=(",", ":"),
    )
    try:
        decisions = _call_and_parse(
            "decision_maker", DECISION_SYSTEM, council_input, parse_decision_reply,
            labels, record, transport,
        )
    except CouncilError as exc:
        record["errors"].append(f"decision_maker: {exc}; no new trades")
        return record

    record["decisions"] = [
        {**d, "pair": label_map[d["label"]], "baseline": baseline[label_map[d["label"]]]}
        for d in decisions
    ]
    record["status"] = "shadow"
    return record
