"""Forex council weekly audit (registered plan item 8.9). Read-only.

Flags: a logged pack that is not the registered shape, key-like strings in any
stored outbound payload or reply, a payload the outbound scanner would now
block, and code that names a host outside ALLOWED_HOSTS or holds a key-like
string. Findings go to the degradation log, which is the existing warning
channel. Never raises, never changes the ledger.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from forex_council import ALLOWED_HOSTS, CouncilError, scan_outbound, validate_pack

KEY_PATTERNS = (
    re.compile(r"(sk|gsk|rk|pk)[-_][A-Za-z0-9]{8,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{10,}"),
    re.compile(r"(ghp|gho|github_pat)_[A-Za-z0-9_]{10,}"),
)
HOST_RE = re.compile(r"https?://([A-Za-z0-9.-]+)", re.IGNORECASE)
HERE = Path(__file__).resolve().parent
AUDITED_FILES = ("forex_council.py", "forex_ledger.py", "forex_scorecard.py", "forex_ai_strategy.py")


def _has_key(text: str) -> bool:
    return any(p.search(text) for p in KEY_PATTERNS)


def audit_records(rows: Iterable[tuple[Any, dict[str, Any]]]) -> list[str]:
    findings: list[str] = []
    for day, record in rows:
        pack = record.get("pack")
        if pack is not None:
            try:
                validate_pack(pack)
            except (CouncilError, KeyError, TypeError) as exc:
                findings.append(f"{day}: logged pack off schema ({exc})")
        for call in record.get("calls") or []:
            role = call.get("role", "?")
            req = call.get("request") or {}
            for part in ("system", "user"):
                text = req.get(part) or ""
                if _has_key(text):
                    findings.append(f"{day}: key-like string in {role} outbound {part}")
            if part_user := req.get("user"):
                try:
                    scan_outbound(part_user)
                except CouncilError:
                    findings.append(f"{day}: {role} outbound payload fails the scanner now")
            if _has_key(call.get("raw") or ""):
                findings.append(f"{day}: key-like string in {role} reply")
    return findings


def audit_source(directory: Path = HERE, files: Iterable[str] = AUDITED_FILES) -> list[str]:
    findings: list[str] = []
    for name in files:
        text = (directory / name).read_text(encoding="utf-8")
        for host in sorted(set(HOST_RE.findall(text))):
            if host.lower() not in ALLOWED_HOSTS:
                findings.append(f"{name}: host {host} is not on the allowlist")
        if _has_key(text):
            findings.append(f"{name}: key-like string in code")
    return findings


def run_weekly_audit(get_conn: Any) -> list[str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT trading_day, record FROM forex_decision_ledger ORDER BY trading_day")
            rows = [(d, r if isinstance(r, dict) else json.loads(r)) for d, r in cur.fetchall()]
    return audit_records(rows) + audit_source()
