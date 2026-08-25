"""
analysis/system_snapshot.py — Stage-Based Codebase Collector for Claude Audit
===============================================================================
Provides per-stage file collectors for the Claude multi-stage audit system.
Each stage is sized to fit completely within Claude's ~200k token context window
(target ≤ 160k tokens of code content per stage, leaving room for system
prompt + response).

Stage ordering (critical systems first):
  Stage 1  — analysis/           (AI decisions, fleet commander, signal guard)
  Stage 2  — core/ + execution/  (trading engine, risk, executor)
  Stage 3  — routes/             (all API endpoints)
  Stage 4  — infrastructure      (main.py, db/, data/, portfolio/, notifications/,
                                  config/, tests/, scripts/)
  Stage 5  — dashboard logic     (pages/, hooks/, lib/)
  Stage 6  — dashboard components A (first ~60 component files alphabetically)
  Stage 7  — dashboard components B + SaaS (remaining components + all SaaS TS)
  Stage 8  — live synthesis      (live DB data + all prior stage summaries)

No file content is truncated within a stage — each stage is sized so that
every file it covers can be delivered in full.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

_REPO_ROOT = Path(__file__).parent.parent.parent
_TRADING_PLATFORM = _REPO_ROOT / "trading-platform"
_DASHBOARD_SRC = _REPO_ROOT / "artifacts" / "dashboard" / "src"

_LOG_DIR = _TRADING_PLATFORM / "logs"


def _read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"[ERROR reading {path}: {exc}]"


def _collect_py(directory: Path, subdirs: list[str] | None = None) -> list[tuple[str, str]]:
    """Collect Python files from given subdirs (or entire directory if None)."""
    files: list[tuple[str, str]] = []
    targets = [directory / s for s in subdirs] if subdirs else [directory]
    for target in targets:
        if not target.exists():
            continue
        for f in sorted(target.rglob("*.py")):
            if "__pycache__" in str(f):
                continue
            files.append((str(f.relative_to(_REPO_ROOT)), _read_file(f)))
    return files


def _collect_ts(directory: Path) -> list[tuple[str, str]]:
    """Collect TypeScript/TSX files from a directory."""
    if not directory.exists():
        return []
    all_files = sorted(directory.rglob("*.ts")) + sorted(directory.rglob("*.tsx"))
    out = []
    for f in all_files:
        if "node_modules" in str(f) or "__pycache__" in str(f):
            continue
        out.append((str(f.relative_to(_REPO_ROOT)), _read_file(f)))
    return out


def _format(files: list[tuple[str, str]]) -> str:
    """Format file list into a single string with TOC + full content of each file."""
    toc = "=== FILE INVENTORY ===\n"
    toc += "\n".join(f"  {i+1:3d}. {rel}" for i, (rel, _) in enumerate(files))
    toc += f"\n=== TOTAL: {len(files)} files ===\n"

    parts = [toc]
    for rel, content in files:
        parts.append(f"\n\n{'=' * 80}\nFILE: {rel}\n{'=' * 80}\n{content}")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Stage builders — no truncation, each stage pre-measured to fit in context
# ---------------------------------------------------------------------------

def build_stage_1_analysis() -> str:
    """Stage 1: analysis/ — AI decisions, fleet commander, signal guard, backtester."""
    return _format(_collect_py(_TRADING_PLATFORM, ["analysis"]))


def build_stage_2_core_execution() -> str:
    """Stage 2: core/ + execution/ — trading engine, scheduler, risk, executor."""
    return _format(
        _collect_py(_TRADING_PLATFORM, ["core"])
        + _collect_py(_TRADING_PLATFORM, ["execution"])
    )


def build_stage_3_routes() -> str:
    """Stage 3: routes/ — all API endpoints and route handlers."""
    return _format(_collect_py(_TRADING_PLATFORM, ["routes"]))


def build_stage_4_infrastructure() -> str:
    """Stage 4: main.py, db/, data/, portfolio/, notifications/, config/, tests/, scripts/."""
    files: list[tuple[str, str]] = []
    for f in sorted(_TRADING_PLATFORM.glob("*.py")):
        if "__pycache__" not in str(f):
            files.append((str(f.relative_to(_REPO_ROOT)), _read_file(f)))
    for sd in ["db", "data", "portfolio", "notifications", "config", "tests", "scripts", "api"]:
        files += _collect_py(_TRADING_PLATFORM, [sd])
    shared = _REPO_ROOT / "shared"
    if shared.exists():
        for f in sorted(shared.rglob("*.py")):
            if "__pycache__" not in str(f):
                files.append((str(f.relative_to(_REPO_ROOT)), _read_file(f)))
    return _format(files)


def build_stage_5_dashboard_logic() -> str:
    """Stage 5: dashboard pages/, hooks/, lib/ — the logic layer of the frontend."""
    files: list[tuple[str, str]] = []
    for subdir in ["pages", "hooks", "lib"]:
        d = _DASHBOARD_SRC / subdir
        files += _collect_ts(d)
    root_ts = [f for f in sorted(_DASHBOARD_SRC.glob("*.ts")) + sorted(_DASHBOARD_SRC.glob("*.tsx"))
               if "node_modules" not in str(f)]
    for f in root_ts:
        files.append((str(f.relative_to(_REPO_ROOT)), _read_file(f)))
    return _format(files)


def build_stage_6_dashboard_components_a() -> str:
    """Stage 6: dashboard/components — first 60 files alphabetically."""
    comp_dir = _DASHBOARD_SRC / "components"
    all_files = _collect_ts(comp_dir)
    return _format(all_files[:60])


def build_stage_7_dashboard_components_b() -> str:
    """Stage 7: dashboard/components — remaining files (after first 60)."""
    comp_dir = _DASHBOARD_SRC / "components"
    all_files = _collect_ts(comp_dir)
    return _format(all_files[60:])


def build_stage_8_live_synthesis(prior_stage_summaries: dict[str, str] | None = None) -> str:
    """
    Stage 8: live system data + summaries from all completed prior stages.
    No source code — this stage synthesises findings into a master verdict.
    """
    parts: list[str] = []

    if prior_stage_summaries:
        parts.append("=== PRIOR STAGE AUDIT SUMMARIES ===\n")
        for stage_id, summary in sorted(prior_stage_summaries.items()):
            parts.append(f"--- {stage_id} ---\n{summary}\n")
    else:
        parts.append("[No prior stage summaries available — running cold synthesis]\n")

    parts.append("\n" + collect_live_data())
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Live data collector
# ---------------------------------------------------------------------------

def _run_query(cur: Any, label: str, sql: str, parts: list[str], handler: Any) -> bool:
    """Execute a single DB query with isolated error handling."""
    try:
        cur.execute(sql)
        rows = cur.fetchall()
        handler(rows, parts)
        return True
    except Exception as exc:
        parts.append(f"\n[{label} query failed: {exc}]")
        logger.warning(f"SystemSnapshot | {label} query failed: {exc}")
        return False


def collect_live_data() -> str:
    """
    Collect live system data: trades (last 200 per bot via window function),
    positions, P&L summary, 48-hour error logs, audit history, learning journal,
    hardcoded rules, adaptive parameters.

    Each DB query has its own error boundary.
    """
    parts: list[str] = []
    query_failures = 0

    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            parts.append("[HEALTH=UNKNOWN] DB unavailable — live data omitted")
            return "\n".join(parts)

        with get_conn() as conn:
            with conn.cursor() as cur:

                def _bot_pnl(rows: list, out: list) -> None:
                    if not rows:
                        return
                    out.append("\n=== BOT P&L SUMMARY ===")
                    for row in rows:
                        bot_id, total, wins, losses, pnl, avg, worst, best = row
                        wr = wins / total * 100 if total > 0 else 0
                        out.append(
                            f"  {bot_id}: trades={total} win_rate={wr:.1f}% "
                            f"total_pnl=${pnl:.2f} avg=${avg:.2f} best=${best:.2f} worst=${worst:.2f}"
                        )

                query_failures += not _run_query(cur, "bot_pnl_summary", """
                    SELECT bot_id, COUNT(*) as total_trades,
                           COUNT(*) FILTER (WHERE pnl_usd > 0) as wins,
                           COUNT(*) FILTER (WHERE pnl_usd <= 0) as losses,
                           COALESCE(SUM(pnl_usd), 0) as total_pnl,
                           COALESCE(AVG(pnl_usd), 0) as avg_pnl,
                           COALESCE(MIN(pnl_usd), 0) as worst_trade,
                           COALESCE(MAX(pnl_usd), 0) as best_trade
                    FROM kraken_trades GROUP BY bot_id ORDER BY bot_id
                """, parts, _bot_pnl)

                try:
                    cur.execute("""
                        SELECT bot_id, symbol, side, entry_price, exit_price,
                               pnl_pct, pnl_usd, reason, closed_at
                        FROM (
                            SELECT *, ROW_NUMBER() OVER (
                                PARTITION BY bot_id ORDER BY closed_at DESC
                            ) AS rn FROM kraken_trades
                        ) ranked WHERE rn <= 200
                        ORDER BY bot_id, closed_at DESC
                    """)
                    cols = [d[0] for d in cur.description]
                    trades = [dict(zip(cols, r)) for r in cur.fetchall()]
                    if trades:
                        for t in trades:
                            if t.get("closed_at"):
                                t["closed_at"] = str(t["closed_at"])[:19]
                        parts.append(f"\n=== LAST 200 TRADES PER BOT ({len(trades)} total records) ===")
                        parts.append(json.dumps(trades, indent=2, default=str))
                except Exception as exc:
                    query_failures += 1
                    parts.append(f"\n[kraken_trades per-bot query failed: {exc}]")
                    logger.warning(f"SystemSnapshot | kraken_trades query failed: {exc}")

                def _heartbeats(rows: list, out: list) -> None:
                    if not rows:
                        return
                    out.append("\n=== BOT HEARTBEATS ===")
                    for hb in rows:
                        out.append(
                            f"  bot_id={hb[1]} status={hb[2]} equity=${hb[3]:.2f} "
                            f"positions={hb[4]} cycles={hb[5]} paused={hb[6]} updated={str(hb[8])[:19]}"
                        )

                query_failures += not _run_query(cur, "kraken_heartbeat", """
                    SELECT id, bot_id, status, equity_usd, position_count, cycle_count,
                           bot_paused, circuit_breaker, last_updated
                    FROM kraken_heartbeat ORDER BY id
                """, parts, _heartbeats)

                def _portfolios(rows: list, out: list) -> None:
                    if not rows:
                        return
                    out.append("\n=== CURRENT OPEN POSITIONS (KRAKEN) ===")
                    for pid, cash, pos in rows:
                        pos_data = pos if isinstance(pos, dict) else json.loads(pos or "{}")
                        out.append(f"  portfolio id={pid} cash=${cash:.2f} open_positions={len(pos_data)}")
                        if pos_data:
                            out.append(f"  positions: {json.dumps(pos_data, default=str)[:1000]}")

                query_failures += not _run_query(cur, "kraken_portfolio",
                    "SELECT id, cash_usd, positions FROM kraken_portfolio ORDER BY id",
                    parts, _portfolios)

                def _alpaca(rows: list, out: list) -> None:
                    if not rows:
                        return
                    out.append("\n=== ACTIVE ALPACA (ORACLE) POSITIONS ===")
                    for t in rows:
                        out.append(
                            f"  {t[0]} pnl={t[1]}% status={t[2]} date={str(t[3])[:19]} "
                            f"regime={t[4]} exit={t[5]}"
                        )

                query_failures += not _run_query(cur, "alpaca_trades", """
                    SELECT ticker, pnl_percentage, status, date, regime_at_entry, exit_reason
                    FROM trades WHERE status = 'Active'
                    ORDER BY date DESC LIMIT 20
                """, parts, _alpaca)

                def _errors(rows: list, out: list) -> None:
                    if rows:
                        out.append("\n=== ERROR/ALERT LOGS (LAST 48h) ===")
                        for e in rows:
                            out.append(f"  [{str(e[0])[:19]}] {e[1]} [{e[2]}] {e[3]}: {e[4][:200]}")
                    else:
                        out.append("\n=== ERROR/ALERT LOGS (LAST 48h) ===\n  No errors logged.")

                query_failures += not _run_query(cur, "system_degradations", """
                    SELECT ts, component, severity, error_type, message
                    FROM system_degradations
                    WHERE ts >= NOW() - INTERVAL '48 hours'
                    ORDER BY ts DESC LIMIT 100
                """, parts, _errors)

                def _learnings(rows: list, out: list) -> None:
                    if not rows:
                        return
                    out.append("\n=== LEARNING JOURNAL (TOP INSIGHTS) ===")
                    for l in rows:
                        out.append(f"  [{l[1]}/{l[2]}] conf={l[4]:.2f} count={l[3]}: {l[0][:200]}")

                query_failures += not _run_query(cur, "llm_learnings", """
                    SELECT insight_text, regime, category, confirmed_count, confidence_score
                    FROM llm_learnings WHERE confidence_score >= 0.5
                    ORDER BY confidence_score DESC, confirmed_count DESC LIMIT 30
                """, parts, _learnings)

                def _rules(rows: list, out: list) -> None:
                    if not rows:
                        return
                    out.append("\n=== HARDCODED RULES (ACTIVE) ===")
                    for r in rows:
                        out.append(f"  {r[0]} [{r[1]}] exit={r[2]} count={r[3]}: {r[4][:200]}")

                query_failures += not _run_query(cur, "hardcoded_rules", """
                    SELECT ticker, regime, exit_reason, failure_count, rule_text
                    FROM hardcoded_rules WHERE active = TRUE
                    ORDER BY failure_count DESC LIMIT 30
                """, parts, _rules)

    except Exception as exc:
        query_failures += 1
        parts.append(f"\n[HEALTH=UNKNOWN] Live data connection error: {exc}")
        logger.warning(f"SystemSnapshot | live data connection failed: {exc}")

    if query_failures:
        parts.insert(0, f"[HEALTH=UNKNOWN] {query_failures} live-data collection query failure(s)")

    try:
        from analysis.fleet_commander import get_last_fleet_audit, get_fleet_audit_history
        audit = get_last_fleet_audit()
        if audit.get("status") == "ok":
            parts.append("\n=== LAST FLEET COMMANDER AUDIT ===")
            parts.append(f"  verdict={audit.get('overall_verdict')} "
                        f"generated={str(audit.get('generated_at', ''))[:19]}")
            parts.append(f"  critique: {audit.get('critique_summary', '')[:500]}")
            if audit.get("critique_flags"):
                for flag in audit["critique_flags"][:10]:
                    parts.append(f"  FLAG: {flag}")
        history = get_fleet_audit_history()
        if history:
            parts.append(f"\n=== FLEET AUDIT HISTORY ({len(history)} entries) ===")
            for h in history[-5:]:
                parts.append(
                    f"  [{str(h.get('generated_at',''))[:19]}] verdict={h.get('overall_verdict')} "
                    f"flags={len(h.get('critique_flags', []))}"
                )
    except Exception as exc:
        parts.append(f"\n[Fleet audit history unavailable: {exc}]")

    return "\n".join(parts)
