"""
System Degradation Tracker
---------------------------
Records every detected system failure or health degradation into PostgreSQL.
Provides a structured event log and copy-paste bug report for operator review.

Usage:
    from core.degradation_tracker import record_degradation, get_recent_events, build_bug_report

    record_degradation(
        component="groq",
        severity="error",
        error_type="rate_limit",
        message="Groq TPD rate limit exceeded",
        detail="Used 99912/100000 tokens",
    )
"""
from __future__ import annotations

import traceback
from datetime import datetime, timezone
from typing import Optional

from loguru import logger


# ── De-duplication: suppress identical events within a rolling window ───────
# Per-(component, error_type) base TTL in seconds.
# Stale-type events on persistent services: 30 min (first alert + 3 escalations = ~4 records/9h).
# HTTP error events need fast re-alerting: 5 min.
# Everything else defaults to 15 min.
_EVENT_TTL: dict[tuple[str, str], int] = {
    ("kraken_api",    "stale"):  1800,  # 30 min — stale data fires every 2 min when bot is unhealthy
    ("platform_core", "stale"):  1800,  # 30 min — scheduler stall persists for hours
    ("http",          "500"):     300,  # 5 min  — server errors may be transient; re-alert quickly
    ("http",          "503"):     300,  # 5 min  — service-unavailable (e.g. AI rate-limit)
}
_DEFAULT_TTL = 900   # 15 min for all other (component, error_type) pairs
_MAX_TTL     = 14400  # cap escalation at 4 h

# key → last recorded timestamp
_recent_keys: dict[str, float] = {}
# key → how many times this event has been recorded (drives escalation)
_escalation_counts: dict[str, int] = {}


def _dedup_key(component: str, error_type: str) -> str:
    # Key is intentionally stable — it does NOT include message text.
    # Messages for persistent incidents often contain volatile numeric values
    # (e.g. "status file is 147s old") that change every poll cycle.  Including
    # them would create a fresh key each cycle, bypassing TTL/escalation logic
    # entirely.  Diagnostic context goes into the `detail` DB column instead.
    return f"{component}::{error_type}"


def _should_record(component: str, error_type: str, message: str) -> bool:
    import time
    key = _dedup_key(component, error_type)
    now = time.time()
    last = _recent_keys.get(key, 0)

    base_ttl = _EVENT_TTL.get((component, error_type), _DEFAULT_TTL)
    count    = _escalation_counts.get(key, 0)
    # Each prior recording doubles the quiet window (2⁰=1× … 2²=4× etc.)
    ttl = min(base_ttl * (2 ** count), _MAX_TTL)

    if (now - last) < ttl:
        return False

    _recent_keys[key] = now
    _escalation_counts[key] = count + 1
    return True


def reset_dedup_key(component: str, error_type: str, message: str = "") -> None:
    """Reset escalation state for a component/error_type when it resolves."""
    key = _dedup_key(component, error_type)
    _recent_keys.pop(key, None)
    _escalation_counts.pop(key, None)


# ── Public API ───────────────────────────────────────────────────────────────

def record_degradation(
    component: str,
    severity: str,
    error_type: str,
    message: str,
    detail: Optional[str] = None,
) -> bool:
    """
    Persist a degradation event.
    Returns True if written, False if skipped (de-dup) or PG unavailable.
    Severity: 'critical' | 'error' | 'warning'
    Component: 'platform_core' | 'data_pipeline' | 'kraken_api' | 'groq'
               | 'alpaca' | 'http' | 'database' | 'scheduler'
    """
    if not _should_record(component, error_type, message):
        return False

    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return False

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO system_degradations
                        (component, severity, error_type, message, detail)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (component, severity, error_type, message[:500], detail[:2000] if detail else None),
                )
        logger.debug(f"[DEGRADATION] Recorded: [{severity}] {component}/{error_type} — {message[:80]}")
        return True
    except Exception as exc:
        logger.debug(f"[DEGRADATION] Failed to record event: {exc}")
        return False


def record_exception(
    component: str,
    severity: str,
    error_type: str,
    message: str,
    exc: Exception,
) -> bool:
    """Convenience wrapper that captures the traceback as detail."""
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return record_degradation(component, severity, error_type, message, detail=detail[:2000])


def mark_resolved(component: str, error_type: str) -> None:
    """
    Mark the most recent unresolved event for (component, error_type) as resolved.
    Called from the auto-heal success path.
    Also clears the in-memory escalation state so the next fresh occurrence of
    the same signature starts with the base TTL rather than an elevated window.
    """
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE system_degradations
                    SET resolved_at = NOW()
                    WHERE component = %s
                      AND error_type = %s
                      AND resolved_at IS NULL
                      AND ts = (
                            SELECT MAX(ts) FROM system_degradations
                            WHERE component = %s AND error_type = %s AND resolved_at IS NULL
                          )
                    """,
                    (component, error_type, component, error_type),
                )
    except Exception as exc:
        logger.debug(f"[DEGRADATION] mark_resolved failed: {exc}")

    # Reset in-memory escalation so a later independent incident is not
    # suppressed by the elevated TTL carried over from the resolved one.
    # Key is stable (component::error_type only), so a direct pop is sufficient.
    key = _dedup_key(component, error_type)
    _recent_keys.pop(key, None)
    _escalation_counts.pop(key, None)
    logger.debug(f"[DEGRADATION] Escalation state cleared for {component}/{error_type}")


# ── Queries ──────────────────────────────────────────────────────────────────

def get_recent_events(
    limit: int = 100,
    hours: int = 48,
    component: Optional[str] = None,
    unresolved_only: bool = False,
) -> list[dict]:
    """Return recent degradation events as a list of dicts, newest first."""
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return []

        clauses = ["ts >= NOW() - INTERVAL '%s hours'"]
        params: list = [hours]

        if component:
            clauses.append("component = %s")
            params.append(component)
        if unresolved_only:
            clauses.append("resolved_at IS NULL")

        where = " AND ".join(clauses)
        params.append(limit)

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, ts AT TIME ZONE 'UTC' AS ts,
                           component, severity, error_type, message, detail, resolved_at
                    FROM system_degradations
                    WHERE {where}
                    ORDER BY ts DESC
                    LIMIT %s
                    """,
                    params,
                )
                rows = cur.fetchall()

        cols = ["id", "ts", "component", "severity", "error_type", "message", "detail", "resolved_at"]
        result = []
        for row in rows:
            d = dict(zip(cols, row))
            d["ts"] = d["ts"].isoformat() + "Z"
            if d["resolved_at"]:
                d["resolved_at"] = d["resolved_at"].isoformat() + "Z"
            result.append(d)
        return result
    except Exception as exc:
        logger.error(f"[DEGRADATION] get_recent_events failed: {exc}")
        return []


def get_stats(hours: int = 24) -> dict:
    """Return aggregate counts per component+severity for the last N hours."""
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return {}

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT component, severity, COUNT(*) AS cnt
                    FROM system_degradations
                    WHERE ts >= NOW() - INTERVAL '%s hours'
                    GROUP BY component, severity
                    ORDER BY cnt DESC
                    """,
                    (hours,),
                )
                rows = cur.fetchall()

        stats: dict = {}
        for comp, sev, cnt in rows:
            stats.setdefault(comp, {})[sev] = cnt
        return stats
    except Exception as exc:
        logger.error(f"[DEGRADATION] get_stats failed: {exc}")
        return {}


# ── Bug report builder ───────────────────────────────────────────────────────

def build_bug_report(hours: int = 24) -> str:
    """
    Generate a plain-text bug report the operator can paste directly to the AI.
    Includes a summary, component stats, and the last 30 unique events.
    """
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    events = get_recent_events(limit=50, hours=hours)
    stats = get_stats(hours=hours)

    lines: list[str] = [
        "=" * 60,
        f"SYSTEM DEGRADATION REPORT — {now_str}",
        f"Window: last {hours}h  |  Total events: {len(events)}",
        "=" * 60,
        "",
    ]

    # ── Summary by component ─────────────────────────────────────────────
    if stats:
        lines.append("COMPONENT SUMMARY")
        lines.append("-" * 40)
        for comp, sev_map in sorted(stats.items()):
            parts = []
            for sev in ("critical", "error", "warning"):
                if sev in sev_map:
                    parts.append(f"{sev}×{sev_map[sev]}")
            lines.append(f"  {comp:<20} {' | '.join(parts)}")
        lines.append("")

    # ── Event timeline ───────────────────────────────────────────────────
    lines.append("RECENT EVENTS (newest first)")
    lines.append("-" * 40)
    if not events:
        lines.append("  No events recorded in this window.")
    else:
        seen_signatures: set[str] = set()
        shown = 0
        for ev in events:
            sig = f"{ev['component']}::{ev['error_type']}::{ev['message'][:60]}"
            if sig in seen_signatures:
                continue
            seen_signatures.add(sig)
            ts = ev["ts"][:19].replace("T", " ")
            resolved = " [RESOLVED]" if ev["resolved_at"] else ""
            sev_tag = ev["severity"].upper()
            lines.append(f"[{ts}] [{sev_tag}] {ev['component']} / {ev['error_type']}{resolved}")
            lines.append(f"  {ev['message']}")
            if ev.get("detail"):
                detail_lines = ev["detail"].strip().splitlines()
                for dl in detail_lines[:4]:
                    lines.append(f"    {dl}")
                if len(detail_lines) > 4:
                    lines.append(f"    ... ({len(detail_lines) - 4} more lines)")
            lines.append("")
            shown += 1
            if shown >= 30:
                break

    lines.append("=" * 60)
    lines.append("END OF REPORT — paste this to the AI for diagnosis")
    lines.append("=" * 60)
    return "\n".join(lines)
