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
    ("kraken_api",    "stale"):   300,  # 5 min — stale data during trading is critical
    ("platform_core", "stale"):   300,  # 5 min — scheduler stall needs fast re-alerting
    ("http",          "500"):     300,  # 5 min
    ("http",          "503"):     300,  # 5 min
}
_DEFAULT_TTL = 900   # 15 min for all other (component, error_type) pairs
_MAX_TTL     = 300   # cap escalation at 5 min for trading-critical components

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
    # DB update: mark the most recent open record as resolved.
    # Runs only when the database is available; escalation reset always runs.
    try:
        from db.postgres import get_conn, is_pg_available
        if is_pg_available():
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
        logger.debug(f"[DEGRADATION] mark_resolved DB update failed: {exc}")

    # Always reset in-memory escalation, even when DB is unavailable.
    # This ensures a later independent incident starts at the base TTL
    # rather than an elevated window from the now-resolved incident.
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


# ── Market-hours helper ──────────────────────────────────────────────────────

def _market_context(ts_iso: str) -> str:
    """
    Return a short label indicating whether a UTC timestamp fell during
    US stock-market hours (Mon–Fri 09:30–16:00 ET).
    """
    try:
        import datetime as _dt
        # Simple ET offset: UTC-5 (EST) / UTC-4 (EDT).
        ts_utc = _dt.datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        try:
            from zoneinfo import ZoneInfo as _ZoneInfo
            _ET_ZONE = _ZoneInfo("America/New_York")
            _et_now = datetime.now(tz=_ET_ZONE)
            et_offset = int(_et_now.utcoffset().total_seconds() // 3600)
        except Exception:
            # Fallback: approximate by month if zoneinfo unavailable
            month = datetime.now().month
            et_offset = -4 if 4 <= month <= 10 else -5
        ts_et = ts_utc + _dt.timedelta(hours=et_offset)
        weekday = ts_et.weekday()   # 0=Mon … 4=Fri
        t = ts_et.time()
        open_t  = _dt.time(9, 30)
        close_t = _dt.time(16, 0)
        if weekday < 5 and open_t <= t < close_t:
            return "MARKET OPEN"
        else:
            return "AFTER HOURS"
    except Exception:
        return ""


def _hours_ago(ts_iso: str) -> str:
    """Return a human-readable 'N h ago' or 'Xm ago' string for a UTC timestamp."""
    try:
        from datetime import datetime as _dt, timezone as _tz
        ts = _dt.fromisoformat(ts_iso.replace("Z", "+00:00"))
        delta = _dt.now(_tz.utc) - ts
        secs = int(delta.total_seconds())
        if secs < 120:
            return f"{secs}s ago"
        if secs < 7200:
            return f"{secs // 60}m ago"
        return f"{secs // 3600}h ago"
    except Exception:
        return ""


# ── Persistent (still-open) issue finder ────────────────────────────────────

def get_active_issues() -> list[dict]:
    """Return unresolved degradation events with first-seen / last-seen metadata."""
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return []
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT component, error_type, severity,
                           MIN(ts AT TIME ZONE 'UTC') AS first_seen,
                           MAX(ts AT TIME ZONE 'UTC') AS last_seen,
                           COUNT(*)                   AS occurrences,
                           (SELECT message FROM system_degradations sd2
                            WHERE sd2.component = sd.component
                              AND sd2.error_type = sd.error_type
                              AND sd2.resolved_at IS NULL
                            ORDER BY sd2.ts DESC LIMIT 1) AS last_message
                    FROM system_degradations sd
                    WHERE resolved_at IS NULL
                      AND ts >= NOW() - INTERVAL '48 hours'
                    GROUP BY component, error_type, severity
                    ORDER BY last_seen DESC
                    """,
                )
                rows = cur.fetchall()
        cols = ["component", "error_type", "severity", "first_seen", "last_seen", "occurrences", "last_message"]
        result = []
        for row in rows:
            d = dict(zip(cols, row))
            d["first_seen"] = d["first_seen"].isoformat() + "Z"
            d["last_seen"]  = d["last_seen"].isoformat() + "Z"
            result.append(d)
        return result
    except Exception:
        return []


# ── Bug report builder ───────────────────────────────────────────────────────

def build_bug_report(
    hours: int = 48,
    live_health:   dict | None = None,
    groq_budget:   dict | None = None,
    kraken_status: dict | None = None,
    market_open:   bool | None = None,
    market_next_open: str | None = None,
    heal_log:      list[dict] | None = None,
) -> str:
    """
    Generate a rich plain-text bug report for AI-assisted diagnosis.

    Includes:
    - Live system health snapshot (green/yellow/red per node)
    - Market context (open vs closed, Groq budget, Kraken positions)
    - Unresolved active issues with duration
    - Auto-heal effectiveness
    - Component summary with market-hours breakdown
    - Full event timeline with market-context annotations
    """
    from datetime import datetime as _dt, timezone as _tz
    now_utc = _dt.now(_tz.utc)
    now_str = now_utc.strftime("%Y-%m-%d %H:%M UTC")
    events  = get_recent_events(limit=100, hours=hours)
    stats   = get_stats(hours=hours)
    active  = get_active_issues()

    resolved_count   = sum(1 for e in events if e["resolved_at"])
    unresolved_count = len(events) - resolved_count

    L = []   # output lines

    # ════════════════════════════════════════════════════════════════════
    L.append("=" * 60)
    L.append(f"SYSTEM DEGRADATION REPORT — {now_str}")
    L.append(f"Window: last {hours}h  |  Total events: {len(events)}"
             f"  |  Open: {unresolved_count}  |  Resolved: {resolved_count}")
    L.append("=" * 60)
    L.append("")

    # ── LIVE SNAPSHOT ────────────────────────────────────────────────────
    if live_health:
        L.append("LIVE SYSTEM SNAPSHOT")
        L.append("-" * 40)
        nodes = live_health.get("nodes", {})
        icons = {"green": "✓", "yellow": "!", "red": "✗"}
        for name, node in nodes.items():
            lvl  = node.get("level", "?")
            icon = icons.get(lvl, "?")
            det  = node.get("detail", "")[:60]
            L.append(f"  {icon} {name:<22} [{lvl:<8}] {det}")
        L.append("")

    # ── CONTEXT ──────────────────────────────────────────────────────────
    L.append("SYSTEM CONTEXT")
    L.append("-" * 40)

    # Market state
    if market_open is not None:
        mkt_label = "OPEN" if market_open else "CLOSED"
        nxt = f"  (next open: {market_next_open})" if market_next_open and not market_open else ""
        L.append(f"  Market:      {mkt_label}{nxt}")
    else:
        L.append("  Market:      unknown")

    # Groq budget
    if groq_budget:
        used      = groq_budget.get("tokens_used_today", "?")
        limit     = groq_budget.get("daily_limit", 100000)
        remaining = groq_budget.get("tokens_remaining", "?")
        exhausted = groq_budget.get("budget_exhausted", False)
        exhausted_at = groq_budget.get("exhausted_at") or groq_budget.get("reset_at")
        budget_str = f"  Groq budget: {used:,}/{limit:,} used, {remaining:,} remaining"
        if exhausted:
            budget_str += f"  ← EXHAUSTED"
            if exhausted_at:
                budget_str += f" (at {str(exhausted_at)[:16]} UTC)"
            budget_str += "\n    → analysis_failed events during market hours are EXPECTED NOISE until midnight UTC reset"
        L.append(budget_str)
    else:
        L.append("  Groq budget: (not available)")

    # Kraken bot summary
    if kraken_status:
        keq   = kraken_status.get("total_equity_usd", 0)
        kdep  = kraken_status.get("deployed_usd", 0)
        kpct  = kraken_status.get("deployed_pct", 0)
        kpos  = kraken_status.get("position_count", 0)
        kstatus = kraken_status.get("status", "?")
        kcycle  = kraken_status.get("cycle_count", 0)
        ceiling = kraken_status.get("deployable_ceiling_pct", 80)
        L.append(f"  Kraken bot:  {kstatus.upper()} | Equity ${keq:,.0f}"
                 f" | Deployed ${kdep:,.0f} ({kpct:.0f}% of equity,"
                 f" ceiling={(ceiling * keq / 100):,.0f}) | Cycle #{kcycle}")
        # Open positions
        positions = kraken_status.get("open_positions", [])
        if positions:
            for p in positions[:6]:
                sym   = p.get("symbol", "?")
                side  = p.get("side", "?").upper()
                pnl   = p.get("unrealized_pnl_pct", 0)
                size  = p.get("size_usd", 0)
                L.append(f"    {side:<5} {sym:<12} ${size:,.0f}  P&L: {pnl:+.2f}%")
        # VPIN / microstructure
        ms = kraken_status.get("microstructure", {})
        if ms:
            high_vpin = [(sym, v.get("vpin", 0)) for sym, v in ms.items() if v.get("vpin", 0) > 0.7]
            if high_vpin:
                L.append(f"    VPIN > 0.70 on {len(high_vpin)}/{len(ms)} pairs"
                         f" (entries filtered — toxic/institutional flow)")
    else:
        L.append("  Kraken bot:  (not available)")

    L.append("")

    # ── AUTO-HEAL EFFECTIVENESS ──────────────────────────────────────────
    if heal_log:
        heal_total   = len(heal_log)
        heal_success = sum(1 for h in heal_log if h.get("success"))
        heal_rate    = f"{heal_success}/{heal_total}"
        L.append("AUTO-HEAL EFFECTIVENESS (last 20 attempts)")
        L.append("-" * 40)
        L.append(f"  Success rate: {heal_rate}"
                 + ("  ← healer working" if heal_success >= heal_total * 0.7 else "  ← healer struggling"))
        # Show the last 5 heal entries
        from datetime import datetime as _dt2, timezone as _tz2
        for h in heal_log[:5]:
            ts_raw = h.get("ts", 0)
            try:
                ts_h = _dt2.fromtimestamp(float(ts_raw), tz=_tz2.utc).strftime("%H:%M UTC")
            except Exception:
                ts_h = str(ts_raw)[:16]
            comp_h  = h.get("component", "?")
            trig_h  = h.get("triggered_by", "?")
            ok_h    = "✓" if h.get("success") else "✗"
            action_h = h.get("action") or h.get("result") or ""
            L.append(f"  {ok_h} [{ts_h}] {comp_h} ({trig_h}) — {action_h[:70]}")
        L.append("")

    # ── ACTIVE (UNRESOLVED) ISSUES ───────────────────────────────────────
    if active:
        L.append(f"ACTIVE UNRESOLVED ISSUES ({len(active)})")
        L.append("-" * 40)
        for a in active:
            dur = _hours_ago(a["first_seen"])
            lst = _hours_ago(a["last_seen"])
            sev = a["severity"].upper()
            ctx = _market_context(a["last_seen"])
            ctx_tag = f" [{ctx}]" if ctx else ""
            L.append(f"  [{sev}] {a['component']} / {a['error_type']}{ctx_tag}")
            L.append(f"    First seen: {dur}  |  Last seen: {lst}"
                     f"  |  Occurrences: {a['occurrences']}")
            if a.get("last_message"):
                L.append(f"    Latest msg: {a['last_message'][:80]}")
            L.append("")
    else:
        L.append("ACTIVE UNRESOLVED ISSUES")
        L.append("-" * 40)
        L.append("  None — all recent issues resolved.")
        L.append("")

    # ── COMPONENT SUMMARY ────────────────────────────────────────────────
    if stats:
        L.append(f"COMPONENT SUMMARY (last {hours}h)")
        L.append("-" * 40)
        for comp, sev_map in sorted(stats.items()):
            parts = []
            for sev in ("critical", "error", "warning"):
                if sev in sev_map:
                    parts.append(f"{sev}×{sev_map[sev]}")
            L.append(f"  {comp:<22} {' | '.join(parts)}")
        L.append("")

    # ── EVENT TIMELINE ───────────────────────────────────────────────────
    L.append("RECENT EVENTS (newest first, market context annotated)")
    L.append("-" * 40)
    if not events:
        L.append("  No events recorded in this window.")
    else:
        seen_sigs: set[str] = set()
        shown = 0
        for ev in events:
            sig = f"{ev['component']}::{ev['error_type']}::{ev['message'][:60]}"
            if sig in seen_sigs:
                continue
            seen_sigs.add(sig)

            ts_raw   = ev["ts"][:19].replace("T", " ")
            ctx      = _market_context(ev["ts"])
            ctx_tag  = f" [{ctx}]" if ctx else ""
            resolved = " [RESOLVED]" if ev["resolved_at"] else " [OPEN]"
            sev_tag  = ev["severity"].upper()
            ago      = _hours_ago(ev["ts"])

            L.append(f"[{ts_raw} UTC / {ago}] [{sev_tag}]{ctx_tag} {ev['component']} / {ev['error_type']}{resolved}")
            L.append(f"  {ev['message']}")

            if ev.get("detail"):
                detail_lines = ev["detail"].strip().splitlines()
                # Show up to 8 lines — enough to capture tracebacks' actual error line
                for dl in detail_lines[:8]:
                    L.append(f"    {dl}")
                if len(detail_lines) > 8:
                    L.append(f"    ... ({len(detail_lines) - 8} more lines)")
            L.append("")
            shown += 1
            if shown >= 40:
                L.append(f"  ... {len(events) - shown} more events truncated (increase hours or filter by component)")
                break

    L.append("=" * 60)
    L.append("END OF REPORT — paste this to the AI for diagnosis")
    L.append("=" * 60)
    return "\n".join(L)
