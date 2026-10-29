/**
 * DDG Finance home: one screen, brand "Glacier Glitch" v3.1.
 * All money and return figures are server values (Rule 27); the client only
 * formats them, sums market values for the holdings mix and divides equity
 * by fleet equity for allocation shares.
 */
import { useMemo } from "react";
import { Download, Moon, Sun } from "lucide-react";
import {
  Area, AreaChart, Bar, BarChart, Cell, Pie, PieChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import "@/styles/brand.css";
import "@/styles/brand-home.css";
import { useFleetData, fmtEq, getBotStatus, type BotSlice, type LivePos } from "@/hooks/useFleetData";
import { useBotRegistry, useFleetHistory } from "@/hooks/use-portfolio";
import { useRiskMetrics } from "@/hooks/use-performance";
import { useRecentTrades } from "@/hooks/use-journal";
import { useExportReport } from "@/hooks/use-report";
import { useBotHistory, type BotDay } from "@/hooks/use-bot-history";
import { useMode, type CHART } from "@/lib/brand-theme";

type Chart = (typeof CHART)["light"] | (typeof CHART)["dark"];

// ── Formatting (display only) ────────────────────────────────────────────────
const money = (v: number | null | undefined) => (v == null ? null : fmtEq(v));
function signedMoney(v: number | null | undefined) {
  if (v == null) return null;
  const abs = Math.abs(v);
  const s = abs >= 1000 ? `$${(abs / 1000).toFixed(1)}k` : `$${abs.toFixed(0)}`;
  return `${v >= 0 ? "+" : "−"}${s}`;
}
const signedPct = (v: number | null | undefined, digits = 2) =>
  v == null || !Number.isFinite(v) ? null : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(digits)}%`;
const tone = (v: number | null | undefined) => (v == null ? "" : v >= 0 ? "ddg-up" : "ddg-down");
const utcTime = (iso?: string | null) => (iso ? `${new Date(iso).toISOString().slice(11, 16)} UTC` : null);
/** Insert an empty point where daily records stop for more than a week, so
 *  the line breaks instead of drawing a straight bridge over missing days. */
function withGaps<T extends { date: string }>(rows: T[], key: keyof T): Array<T | Record<string, unknown>> {
  const out: Array<T | Record<string, unknown>> = [];
  rows.forEach((r, i) => {
    if (i && Date.parse(r.date) - Date.parse(rows[i - 1].date) > 7 * 86_400_000) out.push({ date: r.date, [key]: null, gap: true });
    out.push(r);
  });
  return out;
}

const shortDate = (d: string) =>
  new Date(`${d}T00:00:00Z`).toLocaleDateString("en-AU", { day: "numeric", month: "short", timeZone: "UTC" });

function tooltipStyle(chart: Chart) {
  return {
    contentStyle: {
      background: "var(--ddg-tooltip)", border: "1px solid var(--ddg-border)", borderRadius: 12,
      backdropFilter: "blur(20px)", color: "var(--ddg-text)", fontFamily: "var(--ddg-font-body)", fontSize: 12,
    },
    labelStyle: { color: chart.text, fontFamily: "var(--ddg-font-mono)", fontSize: 11 },
    itemStyle: { color: "var(--ddg-text)" },
    cursor: { stroke: chart.hairline, fill: chart.hairline },
  };
}

// ── Building blocks ──────────────────────────────────────────────────────────
function Panel({ label, aside, children, className = "" }: {
  label: string; aside?: React.ReactNode; children: React.ReactNode; className?: string;
}) {
  return (
    <section className={`ddg-glass bh-panel ${className}`} aria-label={label}>
      <div className="bh-panel-head">
        <span className="ddg-label">{label}</span>
        {aside && <span className="ddg-label" style={{ letterSpacing: "0.04em" }}>{aside}</span>}
      </div>
      {children}
    </section>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="bh-empty ddg-small">{children}</div>;
}

function Status({ kind, word }: { kind: "ok" | "warn" | "bad" | ""; word: string }) {
  return <span className="ddg-chip"><span className={`ddg-dot ${kind}`} />{word}</span>;
}

function Kpi({ label, value, sub, valueClass = "" }: {
  label: string; value: string | null; sub?: React.ReactNode; valueClass?: string;
}) {
  return (
    <div className="bh-kpi">
      <div className="ddg-label">{label}</div>
      <div className={`ddg-data ${valueClass}`}>{value ?? "—"}</div>
      {sub != null && <div className="ddg-small">{sub}</div>}
    </div>
  );
}

function Donut({ data, chart, center, total }: {
  data: { name: string; value: number }[]; chart: Chart; center: React.ReactNode; total: number;
}) {
  return (
    <div className="bh-donut">
      <div className="bh-donut-chart">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="name" innerRadius="64%" outerRadius="96%"
              paddingAngle={2} stroke="none" isAnimationActive={false}>
              {data.map((d, i) => <Cell key={d.name} fill={chart.series[i % chart.series.length]} />)}
            </Pie>
            <Tooltip {...tooltipStyle(chart)} formatter={(v: number) => fmtEq(v)} />
          </PieChart>
        </ResponsiveContainer>
        <div className="bh-donut-center">{center}</div>
      </div>
      <div className="bh-legend">
        {data.map((d, i) => (
          <div className="bh-legend-row" key={d.name}>
            <i style={{ background: chart.series[i % chart.series.length] }} />
            <span>{d.name}</span>
            <strong>{total > 0 ? `${((d.value / total) * 100).toFixed(0)}%` : "—"}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Engine card ──────────────────────────────────────────────────────────────
interface Engine {
  id: string; name: string; subtitle: string; series: string; paused: boolean;
  slice?: BotSlice; history: BotDay[]; strategyCount?: number;
}

function EngineCard({ e, chart, mktOpen }: { e: Engine; chart: Chart; mktOpen: boolean }) {
  const latest = e.history.at(-1);
  const status = e.paused
    ? { kind: "warn" as const, word: "Paused" }
    : !e.slice
      ? { kind: "" as const, word: "No data" }
      : getBotStatus(e.slice, mktOpen) === "DOWN"
        ? { kind: "bad" as const, word: "Stale" }
        : mktOpen ? { kind: "ok" as const, word: "Running" } : { kind: "" as const, word: "Closed" };
  const curve = withGaps(e.history.filter((d) => d.equity != null).map((d) => ({ date: d.date, equity: d.equity as number })), "equity");
  const deployed = latest?.deployed_pct;
  const dayRet = latest?.daily_return == null ? null : latest.daily_return * 100;
  return (
    <article className="ddg-glass ddg-glass-card bh-engine" style={{ ["--series" as string]: e.series }} aria-label={`${e.name} engine`}>
      <div className="bh-engine-head">
        <div className="bh-engine-name">
          <h3 className="ddg-h3">{e.name}</h3>
          <div className="ddg-small" title={e.subtitle}>{e.subtitle}</div>
        </div>
        <span title={status.word === "Closed" ? "US market closed" : undefined}><Status kind={status.kind} word={status.word} /></span>
      </div>
      {e.slice ? (
        <div className="bh-engine-eq">
          <span className="ddg-data">{money(e.slice.equity)}</span>
          <span className="ddg-small">
            <span className={tone(e.slice.pnl)}>{signedMoney(e.slice.pnl)}</span> · {signedPct(e.slice.pnl_pct)} since start
          </span>
        </div>
      ) : (
        <div className="bh-engine-eq"><span className="ddg-small">
          {e.paused ? "Shadow test only. No orders are placed." : "No equity reported yet."}
        </span></div>
      )}
      <div className="bh-chart">
        {curve.length > 1 ? (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={curve} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
              <defs>
                <linearGradient id={`fill-${e.id}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={e.series} stopOpacity={0.28} />
                  <stop offset="100%" stopColor={e.series} stopOpacity={0} />
                </linearGradient>
              </defs>
              <YAxis hide domain={["dataMin", "dataMax"]} />
              <XAxis dataKey="date" hide />
              <Tooltip {...tooltipStyle(chart)} labelFormatter={shortDate} formatter={(v: number) => [fmtEq(v), "Equity"]} />
              <Area type="monotone" dataKey="equity" stroke={e.series} strokeWidth={2} strokeLinejoin="round"
                fill={`url(#fill-${e.id})`} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        ) : <Empty>Daily history starts after the first daily close.</Empty>}
      </div>
      <div className="ddg-label" style={{ fontSize: 10, display: "flex", justifyContent: "space-between" }}>
        <span>Invested</span><span>{deployed == null ? "—" : `${(deployed * 100).toFixed(0)}%`}</span>
      </div>
      <div className="bh-meter" role="meter" aria-valuemin={0} aria-valuemax={100}
        aria-valuenow={deployed == null ? undefined : Math.round(deployed * 100)} aria-label="Share invested">
        <i style={{ width: `${Math.max(0, Math.min(1, deployed ?? 0)) * 100}%` }} />
      </div>
      <div className="bh-stats">
        <div className="bh-stat"><span className="ddg-label">Positions</span>
          <strong>{e.strategyCount ?? e.slice?.positions ?? latest?.positions ?? "—"}</strong></div>
        <div className="bh-stat"><span className="ddg-label">Last day</span>
          <strong className={tone(dayRet)}>{signedPct(dayRet) ?? "—"}</strong></div>
        <div className="bh-stat"><span className="ddg-label">Win rate</span>
          <strong>{e.slice?.win_rate == null ? "—" : `${(e.slice.win_rate * 100).toFixed(0)}%`}</strong></div>
      </div>
    </article>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────
const HOLDING_GROUPS = ["Stocks & ETFs", "Crypto", "Cash park (SGOV)", "Vault (BIL, VOO)"] as const;
function holdingGroup(p: LivePos): (typeof HOLDING_GROUPS)[number] {
  if (p.symbol === "SGOV") return "Cash park (SGOV)";
  if (p.symbol === "BIL" || p.symbol === "VOO") return "Vault (BIL, VOO)";
  if (/USD$/.test(p.symbol)) return "Crypto";
  return "Stocks & ETFs";
}

export default function BrandHome({ runnerVerdict }: { runnerVerdict: "ALIVE" | "STALE" | "ABSENT" | "UNKNOWN" }) {
  const { mode, setMode, chart } = useMode();
  const { fleet, total, allPos, positionsByBot, regime, killTripped, killSwitchArmed, lastCycle, mktOpen } = useFleetData();
  const registry = useBotRegistry();
  const fleetHistory = useFleetHistory();
  const botHistory = useBotHistory(90);
  const risk = useRiskMetrics();
  const trades = useRecentTrades(10);
  const report = useExportReport();

  const engines: Engine[] = useMemo(() => {
    const bots = (registry.data?.bots ?? [])
      .filter((b) => b.status !== "retired")
      .sort((a, b) => a.display_order - b.display_order);
    return bots.map((b, i) => ({
      id: b.id,
      name: b.display_name,
      subtitle: b.subtitle || b.strategy_label,
      series: chart.series[i % chart.series.length],
      paused: b.status === "paused",
      slice: (fleet as Record<string, BotSlice | undefined> | undefined)?.[b.id],
      history: botHistory.data?.bots?.[b.id] ?? [],
      strategyCount: (positionsByBot as Record<string, { strategy_count: number }> | undefined)?.[b.id]?.strategy_count,
    }));
  }, [registry.data, fleet, botHistory.data, positionsByBot, chart]);

  const allocation = engines
    .filter((e) => e.slice?.equity != null && e.slice.equity > 0)
    .map((e) => ({ name: e.name, value: e.slice!.equity }));
  const allocTotal = allocation.reduce((s, d) => s + d.value, 0);

  const holdings = HOLDING_GROUPS.map((name) => ({
    name,
    value: allPos.filter((p) => holdingGroup(p) === name).reduce((s, p) => s + Math.abs(p.market_value ?? 0), 0),
  })).filter((d) => d.value > 0);
  const holdingsTotal = holdings.reduce((s, d) => s + d.value, 0);

  const fleetCurve = (fleetHistory.data?.history ?? []).map((p) => ({ date: p.date, equity: p.total_equity }));
  // Mark the day an engine's account first appears in the fleet total (the
  // 6 Oct step is the $100k Forex paper account joining, not a gain).
  const firsts = engines.map((e) => ({ name: e.name, date: e.history[0]?.date }))
    .filter((j): j is { name: string; date: string } => !!j.date);
  const earliest = firsts.reduce((m, j) => (j.date < m ? j.date : m), "9999");
  const joins = firsts.filter((j) =>
    j.date > earliest && fleetCurve.length > 1 && j.date > fleetCurve[0].date && j.date <= fleetCurve.at(-1)!.date);

  // Daily returns: last 15 sessions, one bar per engine that has a return.
  const returnEngines = engines.filter((e) => !e.paused && e.history.some((d) => d.daily_return));
  const dates = Array.from(new Set(returnEngines.flatMap((e) => e.history.map((d) => d.date)))).sort().slice(-15);
  const dailyReturns = dates.map((date) => {
    const row: Record<string, string | number | null> = { date };
    for (const e of returnEngines) {
      const d = e.history.find((x) => x.date === date);
      row[e.id] = d?.daily_return == null ? null : +(d.daily_return * 100).toFixed(3);
    }
    return row;
  });

  const movers = [...allPos]
    .filter((p) => p.symbol !== "SGOV" && p.symbol !== "BIL" && p.symbol !== "VOO")
    .sort((a, b) => Math.abs(b.unrealized_pl) - Math.abs(a.unrealized_pl))
    .slice(0, 8)
    .map((p) => ({ symbol: p.symbol, pl: p.unrealized_pl }));
  const closed = (trades.data?.trades ?? [])
    .filter((t) => t.pnl_usd != null)
    .slice(0, 10)
    .reverse()
    .map((t) => ({ label: `${t.symbol}`, pl: t.pnl_usd as number, when: t.closed_at }));

  const r = risk.data;
  const killWord = killTripped == null ? "Unknown" : killTripped ? "Tripped" : killSwitchArmed ? "Armed" : "Report-only";
  const killKind = killTripped == null ? "warn" : killTripped ? "bad" : killSwitchArmed ? "ok" : "warn";
  const runnerKind = runnerVerdict === "ALIVE" ? "ok" : runnerVerdict === "STALE" || runnerVerdict === "ABSENT" ? "bad" : "warn";
  const runnerWord = { ALIVE: "Runner alive", STALE: "Runner stale", ABSENT: "Runner absent", UNKNOWN: "Runner unknown" }[runnerVerdict];
  const tip = tooltipStyle(chart);

  const downloadReport = async () => {
    try {
      const result = await report.mutateAsync();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([result.report], { type: "text/plain" }));
      a.download = `ddg-finance-report-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-")}.txt`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch { /* the mutation keeps its own error state */ }
  };

  return (
    <main className="ddg-shell bh-shell">
      <div className="ddg-photo" aria-hidden="true" />
      <div className="ddg-photo-grade" aria-hidden="true" />
      <div className="bh">
        {/* Nav */}
        <header className="ddg-glass bh-nav">
          <div className="bh-brand">
            <img src="/ddg-mark-white-256.png" alt="Digital Dynamics" />
            <div>
              <div className="bh-word">Digital Dynamics</div>
              <div className="bh-sub">DDG · FINANCE</div>
            </div>
          </div>
          <span className="ddg-badge" title="All accounts are paper (simulated) trading accounts">PAPER</span>
          <div className="bh-nav-status">
            <Status kind={runnerKind} word={runnerWord} />
            <Status kind={killKind} word={`Kill switch ${killWord.toLowerCase()}`} />
            <Status kind={mktOpen ? "ok" : ""} word={mktOpen ? "US market open" : "US market closed"} />
            <span className="ddg-chip">Synced {utcTime(lastCycle) ?? "—"}</span>
          </div>
          <div className="bh-nav-actions">
            <div className="bh-toggle" role="group" aria-label="Display mode">
              <button className="ddg-btn" aria-pressed={mode === "light"} onClick={() => setMode("light")}><Sun size={14} /> Day</button>
              <button className="ddg-btn" aria-pressed={mode === "dark"} onClick={() => setMode("dark")}><Moon size={14} /> Night ops</button>
            </div>
            <button className="ddg-btn" onClick={downloadReport} disabled={report.isPending} title="Download the full text report">
              <Download size={14} /> {report.isPending ? "Preparing" : "Report"}
            </button>
          </div>
        </header>

        {/* KPI strip */}
        <section className="ddg-glass bh-kpis" aria-label="Fleet summary">
          <Kpi label="Fleet equity" value={money(total?.equity)}
            sub={<><span className={tone(total?.pnl)}>{signedMoney(total?.pnl)}</span> {signedPct(total?.pnl_pct)} since start</>} />
          <Kpi label="Last 24 hours" value={signedMoney(total?.pnl_24h)} valueClass={tone(total?.pnl_24h)}
            sub={total?.pnl_24h_pct == null ? "vs prior close" : `${signedPct(total.pnl_24h_pct)} vs prior close`} />
          <Kpi label="Annual return" value={signedPct(r?.annualised_return_pct, 1)} valueClass={tone(r?.annualised_return_pct)}
            sub={r?.insufficient_data ? "Short history" : "annualised"} />
          <Kpi label="Sharpe" value={r?.sharpe_ratio == null ? null : r.sharpe_ratio.toFixed(2)} sub="risk-adjusted" />
          <Kpi label="Max drawdown" value={r?.max_drawdown_pct == null ? null : `−${Math.abs(r.max_drawdown_pct).toFixed(1)}%`} sub="peak to trough" />
          <Kpi label="Volatility" value={r?.volatility_annual_pct == null ? null : `${r.volatility_annual_pct.toFixed(1)}%`} sub="annualised" />
          <Kpi label="Open positions" value={total?.positions == null ? null : String(total.positions)}
            sub={`${new Set(allPos.map((p) => p.symbol)).size} symbols`} />
          <Kpi label="Market regime" value={regime ? regime.charAt(0) + regime.slice(1).toLowerCase() : null}
            sub={mktOpen ? "US session open" : "US session closed"} />
        </section>

        <div className="bh-main">
          <div className="bh-left">
            {/* Fleet equity */}
            <section className="ddg-glass bh-panel" aria-label="Fleet equity history">
              <div className="bh-panel-head">
                <span className="ddg-label">Fleet equity · daily close</span>
                <span className="ddg-label" style={{ letterSpacing: "0.04em" }}>
                  {fleetCurve.length ? `${shortDate(fleetCurve[0].date)} – ${shortDate(fleetCurve.at(-1)!.date)}` : ""}
                </span>
              </div>
              <div className="bh-chart">
                {fleetCurve.length > 1 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={fleetCurve} margin={{ top: 10, right: 6, bottom: 0, left: 6 }}>
                      <defs>
                        <linearGradient id="fill-fleet" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor={chart.series[0]} stopOpacity={0.28} />
                          <stop offset="100%" stopColor={chart.series[0]} stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <XAxis dataKey="date" tickFormatter={shortDate} minTickGap={48} tick={{ fill: chart.text, fontSize: 11 }}
                        axisLine={{ stroke: chart.hairline }} tickLine={false} />
                      <YAxis domain={["dataMin", "dataMax"]} width={64} tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
                        tick={{ fill: chart.text, fontSize: 11 }} axisLine={false} tickLine={false} />
                      <Tooltip {...tip} labelFormatter={shortDate} formatter={(v: number) => [fmtEq(v), "Fleet equity"]} />
                      {joins.map((j) => (
                        <ReferenceLine key={j.name} x={fleetCurve.find((p) => p.date >= j.date)?.date} stroke={chart.text}
                          strokeDasharray="3 4" strokeOpacity={0.7}
                          label={{ value: `${j.name} paper account added`, position: "insideTopRight", fill: chart.text, fontSize: 11 }} />
                      ))}
                      <Area type="monotone" dataKey="equity" stroke={chart.series[0]} strokeWidth={2} strokeLinejoin="round"
                        fill="url(#fill-fleet)" isAnimationActive={false} />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : <Empty>No fleet history yet. The first point is saved at tonight's close.</Empty>}
              </div>
            </section>
            {/* Engines */}
            <div className="bh-engines">
              {engines.length
                ? engines.map((e) => <EngineCard key={e.id} e={e} chart={chart} mktOpen={mktOpen} />)
                : <Empty>{registry.isError ? "Engine list unavailable. Check the trading API." : "Loading engines…"}</Empty>}
            </div>
          </div>

          <div className="bh-right">
            <div className="bh-pair">
              <Panel label="Allocation by engine">
                {allocation.length ? (
                  <Donut data={allocation} chart={chart} total={allocTotal}
                    center={<><span className="ddg-label" style={{ fontSize: 10 }}>Total</span><span className="ddg-data">{fmtEq(allocTotal)}</span></>} />
                ) : <Empty>No engine equity reported yet.</Empty>}
              </Panel>
              <Panel label="Holdings mix">
                {holdings.length ? (
                  <Donut data={holdings} chart={chart} total={holdingsTotal}
                    center={<><span className="ddg-label" style={{ fontSize: 10 }}>Held</span><span className="ddg-data">{fmtEq(holdingsTotal)}</span></>} />
                ) : <Empty>No open holdings.</Empty>}
              </Panel>
            </div>

            <Panel label="Daily return by engine" aside={returnEngines.length ? (
              <span className="bh-key">{returnEngines.map((e) => <span key={e.id}><i style={{ background: e.series }} />{e.name}</span>)}</span>
            ) : undefined}>
              {dailyReturns.length ? (
                <div className="bh-chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={dailyReturns} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} barGap={1} barCategoryGap="22%">
                      <XAxis dataKey="date" tickFormatter={shortDate} minTickGap={28} tick={{ fill: chart.text, fontSize: 10 }}
                        axisLine={{ stroke: chart.hairline }} tickLine={false} />
                      <YAxis width={44} tickFormatter={(v: number) => `${v.toFixed(1)}%`} tick={{ fill: chart.text, fontSize: 10 }}
                        axisLine={false} tickLine={false} />
                      <ReferenceLine y={0} stroke={chart.hairline} />
                      <Tooltip {...tip} labelFormatter={shortDate}
                        formatter={(v: number, key: string) => [signedPct(v), engines.find((e) => e.id === key)?.name ?? key]} />
                      {returnEngines.map((e) => (
                        <Bar key={e.id} dataKey={e.id} fill={e.series} radius={[2, 2, 0, 0]} isAnimationActive={false} />
                      ))}
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : <Empty>Daily returns appear after two daily closes.</Empty>}
            </Panel>

            <div className="bh-pair">
              <Panel label="Open P&L · largest positions">
                {movers.length ? (
                  <div className="bh-chart">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={movers} layout="vertical" margin={{ top: 0, right: 8, bottom: 0, left: 0 }} barCategoryGap="18%">
                        <XAxis type="number" hide />
                        <YAxis type="category" dataKey="symbol" width={58} tick={{ fill: chart.text, fontSize: 10 }}
                          axisLine={false} tickLine={false} />
                        <ReferenceLine x={0} stroke={chart.hairline} />
                        <Tooltip {...tip} formatter={(v: number) => [signedMoney(v), "Unrealised"]} />
                        <Bar dataKey="pl" radius={3} isAnimationActive={false}>
                          {movers.map((m) => <Cell key={m.symbol} fill={m.pl >= 0 ? chart.ok : chart.bad} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                ) : <Empty>No open strategy positions.</Empty>}
              </Panel>
              <Panel label="Recent closed trades">
                {closed.length ? (
                  <div className="bh-chart">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={closed} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} barCategoryGap="20%">
                        <XAxis dataKey="label" interval="preserveStartEnd" minTickGap={4} tick={{ fill: chart.text, fontSize: 9 }}
                          axisLine={{ stroke: chart.hairline }} tickLine={false} />
                        <YAxis width={44} tickFormatter={(v: number) => signedMoney(v) ?? ""} tick={{ fill: chart.text, fontSize: 10 }}
                          axisLine={false} tickLine={false} />
                        <ReferenceLine y={0} stroke={chart.hairline} />
                        <Tooltip {...tip} formatter={(v: number) => [signedMoney(v), "Realised"]}
                          labelFormatter={(l: string, p: Array<{ payload?: { when?: string } }>) =>
                            p?.[0]?.payload?.when ? `${l} · ${new Date(p[0].payload.when).toISOString().slice(0, 16).replace("T", " ")} UTC` : l} />
                        <Bar dataKey="pl" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                          {closed.map((t, i) => <Cell key={`${t.label}-${i}`} fill={t.pl >= 0 ? chart.ok : chart.bad} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                ) : <Empty>{trades.isError ? "Trade history unavailable." : "No closed trades yet."}</Empty>}
              </Panel>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
