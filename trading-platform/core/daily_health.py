"""Daily health check: one short Discord message each morning.

Markus, 10 Nov 2026 (finance-2027-plan.md, Step 2 item 13): a daily automatic
health check. Sent at 08:40 Brisbane (after the US close and the Forex council
run), every day, from the published deployment only. Read-only: it runs the
standing invariants and reads bot pause state; it never touches orders.

Verdict "All good" only when every invariant passes, no bot is paused, the kill
switch is not tripped and no high-severity alarm is open. Anything else lists
exactly what needs a look.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from loguru import logger

from core.invariants import UNRESOLVED_HIGH_SEVERITIES

# Plain-English names for the standing invariants (core/invariants.py).
CHECK_NAMES = {
    "strategy_positions_have_covering_stops": "Every holding has its stop",
    "crypto_market_value_within_fleet_cap": "Crypto within the fleet cap",
    "bot_cycle_success_freshness": "Bots cycling on time",
    "recent_reconciliation_is_clean": "Broker and ledger agree",
    "zero_unresolved_high_severity_degradations": "No open alarms",
    "kill_switch_runtime_matches_config": "Kill switch armed as configured",
    "ledger_and_broker_positions_have_matching_symbols": "Same holdings at broker and ledger",
    "ledger_and_broker_quantities_match": "Same quantities at broker and ledger",
    "published_runner_has_recent_durable_cycle": "Live runner cycled recently",
    "runner_heartbeat_is_fresh": "Live runner heartbeat fresh",
}


def summarize(report: dict[str, Any], *, pause_states: dict[str, bool] | None,
              unresolved: list[dict[str, Any]] | None, kill_switch_tripped: bool,
              oanda_retries: tuple[int, int] | None = None) -> tuple[bool, list[str]]:
    """Pure: (all_good, lines) from an invariants report and current state.
    DRIFT is inside its allowed band: shown as a note, never fails the verdict."""
    problems: list[str] = []
    notes: list[str] = []
    if kill_switch_tripped:
        problems.append("🔴 Kill switch is TRIPPED: bots stay paused until it is reset")
    paused = sorted(b for b, p in (pause_states or {}).items() if p)
    if paused:
        problems.append(f"Paused: {', '.join(paused)}")
    checks = report.get("results", [])
    for r in checks:
        line = f"{CHECK_NAMES.get(r['name'], r['name'])}: {r['message']}"[:300]
        if r["status"] in ("DRIFT", "CLOSED"):      # CLOSED: forex weekend, OANDA not checked
            notes.append(f"ℹ️ {line}")
        elif r["status"] != "PASS":
            problems.append(f"{'❓' if r['status'] == 'UNKNOWN' else '❌'} {line}")
    open_alarms = Counter(str(e.get("error_type")) for e in (unresolved or [])
                          if str(e.get("severity", "")).lower() in UNRESOLVED_HIGH_SEVERITIES
                          and e.get("error_type") != "zero_unresolved_high_severity_degradations")
    if open_alarms:
        problems.append("Open alarms: " + ", ".join(f"{t} ×{n}" for t, n in open_alarms.most_common(6)))
    if oanda_retries and sum(oanda_retries):
        recovered, failed = oanda_retries
        notes.append(f"ℹ️ OANDA answered 401 {recovered + failed}× in 24 h: {recovered} fixed by one retry, "
                     f"{failed} failed again")
    passed = sum(1 for r in checks if r["status"] in {"PASS", "DRIFT"})
    return (not problems), [f"{passed}/{len(checks)} safety checks pass"] + problems + notes


def oanda_retry_counts(get_conn=None) -> tuple[int, int] | None:
    """(recovered, failed again) OANDA 401 retries in the last 24 h, from runtime_log."""
    from core.oanda_client import RETRY_LOG_PREFIX
    try:
        if get_conn is None:
            from db.postgres import get_conn
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT count(*) FILTER (WHERE message LIKE %s), count(*) FILTER (WHERE message LIKE %s)
                   FROM runtime_log WHERE ts > now() - interval '24 hours'""",
                (f"{RETRY_LOG_PREFIX} | recovered%", f"{RETRY_LOG_PREFIX} | failed again%"))
            recovered, failed = cur.fetchone()
        return int(recovered), int(failed)
    except Exception as exc:                          # a note only: never block the health message
        logger.debug(f"Daily health | OANDA retry count skipped: {type(exc).__name__}")
        return None


def run_and_send() -> dict[str, Any]:
    from core.invariants import collect_inputs, run_all_invariants
    from core.kill_switch import latch_tripped
    from notifications.discord import COLOR_AMBER, COLOR_GREEN, _embed, _send_async

    inputs = collect_inputs()
    report = run_all_invariants(inputs)
    ok, lines = summarize(report, pause_states=inputs.pause_states,
                          unresolved=inputs.unresolved_degradations,
                          kill_switch_tripped=latch_tripped(), oanda_retries=oanda_retry_counts())
    title = "DDG Finance · daily health: ✅ All good" if ok else "DDG Finance · daily health: ⚠️ Needs a look"
    _send_async({"embeds": [_embed(title, "\n".join(lines), COLOR_GREEN if ok else COLOR_AMBER)]},
                alert_type="daily_health", title=title)
    logger.info(f"Daily health | ok={ok} | {' | '.join(lines)}")
    return {"ok": ok, "lines": lines}
