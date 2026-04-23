"""
claude_context.py — Generates a concise Claude briefing for new sessions.
GET /trading-api/claude-context
"""
from fastapi import APIRouter
from datetime import datetime, timezone

claude_context_router = APIRouter()


@claude_context_router.get("/claude-context")
async def get_claude_context():
    """
    Returns a structured Claude briefing prompt.
    Paste the 'prompt' field at the start of any new Claude session.
    """
    from db.postgres import get_conn, is_pg_available

    sections = []

    sections.append("""You are continuing work on the Quant Terminal — an 8-bot algorithmic trading platform built on Replit. Here is the current system state:

PLATFORM OVERVIEW
- Language: Python (FastAPI backend) + React/TypeScript dashboard
- Exchange connections: Alpaca (US stocks), Kraken (crypto), OANDA (forex paper)
- All bots running paper trading
- Reserved VM on Replit (0.5 vCPU / 2 GiB RAM) — always on
- In-process watchdog on all bots (auto-restart on crash)
- UptimeRobot monitoring health endpoint every 5 minutes
- Review flags system active — check dashboard for due dates
""")

    if not is_pg_available():
        sections.append("DATABASE: Unavailable at report time\n")
    else:
        with get_conn() as conn:
            with conn.cursor() as cur:

                # Fleet equity
                cur.execute("""
                    SELECT alpaca_equity, kraken_equity, forex_equity,
                           poseidon_equity, kraken_current_equity, total_equity, ts
                    FROM equity_snapshots ORDER BY ts DESC LIMIT 1
                """)
                eq = cur.fetchone()
                if eq:
                    def _fmt(v): return f"${v:>10,.2f}" if v is not None else "       N/A"
                    total = eq[5] or 0
                    sections.append(f"""FLEET EQUITY (as of {str(eq[6])[:19]} UTC)
- Oracle (Alpaca):     {_fmt(eq[0])}
- Kraken fleet:        {_fmt(eq[1])}
- Navigator (Forex):   {_fmt(eq[2])}
- Poseidon:            {_fmt(eq[3])}
- Kraken Current:      {_fmt(eq[4])}
- TOTAL:               {_fmt(eq[5])} (started $800,000)
- P&L:                 ${total-800000:>+10,.2f} ({(total-800000)/800000*100:+.2f}%)
""")

                # Bot status
                cur.execute("""
                    SELECT id, bot_id, equity_usd, status, bot_paused,
                           EXTRACT(EPOCH FROM (NOW()-last_updated))/60 as mins_ago
                    FROM kraken_heartbeat ORDER BY id
                """)
                rows = cur.fetchall()
                sections.append("BOT STATUS")
                for r in rows:
                    stale = "STALE" if (r[5] or 9999) > 30 else "OK"
                    paused = " PAUSED" if r[4] else ""
                    sections.append(
                        f"  [{stale}] #{r[0]} {r[1]:<22} ${r[2]:>10,.2f}  "
                        f"{r[3]}{paused}  ({int(r[5] or 0)}m ago)"
                    )
                sections.append("")

                # Active positions
                cur.execute("""
                    SELECT COUNT(*) FROM trades WHERE status = 'Active'
                """)
                oracle_active = cur.fetchone()[0]

                cur.execute("""
                    SELECT bot_id, COUNT(*) as cnt
                    FROM kraken_trades WHERE closed_at IS NULL
                    GROUP BY bot_id ORDER BY bot_id
                """)
                kraken_pos = cur.fetchall()

                sections.append("OPEN POSITIONS")
                sections.append(f"  Oracle active positions: {oracle_active}")
                for r in kraken_pos:
                    sections.append(f"  {r[0]}: {r[1]} open")
                sections.append("")

                # Recent performance
                cur.execute("""
                    SELECT bot_id,
                        COUNT(*) as trades,
                        SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
                        ROUND(AVG(pnl_usd)::numeric, 2) as avg_pnl,
                        ROUND(SUM(pnl_usd)::numeric, 2) as total_pnl
                    FROM kraken_trades
                    WHERE closed_at > NOW() - INTERVAL '7 days'
                    GROUP BY bot_id ORDER BY bot_id
                """)
                rows = cur.fetchall()
                sections.append("KRAKEN BOT PERFORMANCE (last 7 days)")
                for r in rows:
                    wr = r[2] / r[1] * 100 if r[1] else 0
                    avg_s   = f"${r[3]:>8.2f}" if r[3] is not None else "      N/A"
                    total_s = f"${r[4]:>9.2f}" if r[4] is not None else "       N/A"
                    sections.append(
                        f"  {r[0]:<22} {r[1]:>3} trades  "
                        f"WR={wr:>5.1f}%  avg={avg_s}  total={total_s}"
                    )
                sections.append("")

                # Math audit
                cur.execute("""
                    SELECT status, COUNT(DISTINCT (bot_id, formula_name)) as cnt
                    FROM math_audit_log
                    WHERE audit_timestamp > NOW() - INTERVAL '1 hour'
                    GROUP BY status
                """)
                audit = {r[0]: r[1] for r in cur.fetchall()}
                sections.append(
                    f"MATH AUDIT (last hour): "
                    f"PASS={audit.get('PASS', 0)} "
                    f"WARN={audit.get('WARN', 0)} "
                    f"FAIL={audit.get('FAIL', 0)}"
                )
                sections.append("")

                # Review flags
                cur.execute("""
                    SELECT title, due_date, priority,
                           due_date - CURRENT_DATE as days_until
                    FROM review_flags
                    WHERE status = 'pending'
                    ORDER BY due_date ASC
                """)
                flags = cur.fetchall()
                if flags:
                    sections.append("ACTIVE REVIEW FLAGS")
                    for f in flags:
                        overdue = "OVERDUE" if f[3] < 0 else f"{f[3]}d"
                        sections.append(
                            f"  [{f[2].upper()}] {f[0]} — due {f[1]} ({overdue})"
                        )
                    sections.append("")

                # Navigator positions
                cur.execute("""
                    SELECT pair, direction, entry_price, pnl_usd
                    FROM forex_trades
                    WHERE status = 'open'
                    ORDER BY entry_time DESC
                """)
                nav_pos = cur.fetchall()
                if nav_pos:
                    sections.append("NAVIGATOR OPEN POSITIONS")
                    for p in nav_pos:
                        entry = f"{p[2]:.5f}" if p[2] is not None else "N/A"
                        pnl   = f"${p[3]:.2f}" if p[3] is not None else "N/A"
                        sections.append(
                            f"  {p[0]} {p[1]} entry={entry} P&L={pnl}"
                        )
                    sections.append("")

    sections.append("""KNOWN ARCHITECTURE
- Oracle: STF v1.0 — EMA20/50 + ADX>=25 + RSI 40-75 | Trail 2.5xATR | Stop 2.0xATR
- Davy Jones: Mean reversion | Z-score + RSI 40/60 | Conservative sizing
- Blackbeard: Mean reversion | Z-score + RSI 30/70 | Aggressive sizing | Perf breaker active
- Calypso: Mean reversion | Z-score + RSI 35/65 | EMA 50/200 | Dead zone fixed
- Apex Predator: Momentum | RSI 45/55 | EMA 20/50 4H | VPIN 0.80
- Navigator: H4 Forex swing | RSI 30/70 | EMA 50/200 trend filter | ATR min 8 pips | Per-pair cooldown
- Poseidon: Dual-TF Momentum | EMA21/55 4H + RSI 38-58 1H + Volume 1.5x | NEW Apr 23 2026
- Kraken Current: EMA20/100 + ADX + Hurst trend following | 4h cycle

RECENT MAJOR CHANGES (Apr 2026)
- 68 bugs fixed across two audit rounds
- Calypso: 5 strategy fixes including dead zone elimination
- Navigator: 4 entry fixes + per-pair cooldown
- Poseidon: Complete strategy replacement (pairs -> momentum)
- Oracle: Trail trigger 1.5->2.5xATR, profit-gated exits
- All bots: In-process watchdog, DB-backed state, fleet halt
- Fee drag confirmed: Kraken bots NOT live-capital ready (need 40%+ WR over 60 trades)

REVIEW FLAGS DUE
- Apr 30: Blackbeard WR check (currently 24.4% — if still <35%, hard pause)
- May 6:  Calypso 2-week post-fix review (baseline: 20.6% WR, -$89/trade)
- May 7:  Oracle exit validation (need 30 clean trades with closed_at)
- May 15: Navigator 30-trade post-fix validation
- Jun 1:  Live capital readiness assessment

TO START A NEW CLAUDE SESSION: Upload the latest PDF report AND paste the output of this endpoint. Claude will have full context immediately.
""")

    prompt = "\n".join(sections)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prompt": prompt,
        "instructions": "Paste the 'prompt' field at the start of any new Claude session, then upload the latest PDF report.",
    }
