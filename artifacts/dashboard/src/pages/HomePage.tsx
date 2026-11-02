/**
 * DDG Finance home (Night Glass v5): one screen on desktop, stacked on phones.
 * All money and return figures are server values (Rule 27); the client only
 * formats them, sums market values for the holdings mix and divides equity by
 * fleet equity for allocation shares. The bottom-right pair is FLEET-V1's two
 * accounts: signal, targets, drawdown mode and return against SPY since cutover.
 */
import { useMemo, type ReactNode } from "react";
import { Download } from "lucide-react";
import {
  Area, AreaChart, Bar, BarChart, Cell, Pie, PieChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Shell, Status } from "@/components/Shell";
import { useFleetData, fmtEq, getBotStatus, type BotSlice, type LivePos } from "@/hooks/useFleetData";
import { useBotRegistry, useFleetHistory } from "@/hooks/use-portfolio";
import { useRiskMetrics } from "@/hooks/use-performance";
import { useExportReport } from "@/hooks/use-report";
import { useBotHistory, type BotDay } from "@/hooks/use-bot-history";
import { botColor } from "@/lib/bot-identity";
import { useFleetV1State } from "@/hooks/use-fleet-v1";
import { FleetAccountPanel } from "@/components/FleetV1";

// Chart colours = the brand four (same values as styles/night-glass/tokens.css).
// Each account has its own colour (lib/bot-identity BOT_COLORS). Only losses get a
// status colour (amber, a thin line, never a fill); gains stay plain. The fleet
// total is white. Holdings mix (not accounts) uses fading whites.
const FLEET = "#FFFFFF";
const AXIS = "rgba(255,255,255,0.62)";
const HAIRLINE = "rgba(255,255,255,0.10)";
const NEUTRALS = [1, 0.62, 0.38, 0.22, 0.14].map((a) => `rgba(255,255,255,${a})`);

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
const line = (v: number | null | undefined) => (v == null || v === 0 ? "" : v > 0 ? "gain" : "loss");
const shortDate = (d: string) =>
  new Date(`${d}T00:00:00Z`).toLocaleDateString("en-AU", { day: "numeric", month: "short", timeZone: "UTC" });

/** Break the line where daily records stop for more than a week. */
function withGaps<T extends { date: string }>(rows: T[], key: keyof T): Array<T | Record<string, unknown>> {
  const out: Array<T | Record<string, unknown>> = [];
  rows.forEach((r, i) => {
    if (i && Date.parse(r.date) - Date.parse(rows[i - 1].date) > 7 * 86_400_000) out.push({ date: r.date, [key]: null });
    out.push(r);
  });
  return out;
}

// ── Building blocks ──────────────────────────────────────────────────────────
function Panel({ title, aside, className = "", children }: {
  title: string; aside?: ReactNode; className?: string; children: ReactNode;
}) {
  return (
    <section className={`glass panel ${className}`} aria-label={title}>
      <div className="panel-head"><h2>{title}</h2>{aside}</div>
      {children}
    </section>
  );
}

const Empty = ({ children }: { children: ReactNode }) => <div className="empty">{children}</div>;

function Stat({ label, value, sub, mark }: { label: string; value: string | null; sub?: ReactNode; mark?: string }) {
  return (
    <div className="stat">
      <span className="label">{label}</span>
      <span className="num-sm"><span className={mark}>{value ?? "—"}</span></span>
      {sub != null && <span className="note">{sub}</span>}
    </div>
  );
}

type TipRow = { name?: string; value?: number | string | null; payload?: Record<string, unknown> };
function Tip({ active, payload, label, fmt, title }: {
  active?: boolean; payload?: TipRow[]; label?: string;
  fmt: (v: number, row: TipRow) => string; title?: (label: string, row?: TipRow) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tip">
      {label != null && <span className="label">{title ? title(String(label), payload[0]) : String(label)}</span>}
      {payload.filter((p) => p.value != null).map((p, i) => (
        <div key={i} className="tab">{fmt(Number(p.value), p)}</div>
      ))}
    </div>
  );
}

function Donut({ data, center, total }: { data: { name: string; value: number; color: string }[]; center: ReactNode; total: number }) {
  return (
    <div className="donut">
      <div className="donut-chart">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="name" innerRadius="70%" outerRadius="96%"
              paddingAngle={2} stroke="none" isAnimationActive={false}>
              {data.map((d) => <Cell key={d.name} fill={d.color} />)}
            </Pie>
            <Tooltip content={<Tip fmt={(v, r) => `${r.name}: ${fmtEq(v)}`} />} />
          </PieChart>
        </ResponsiveContainer>
        <div className="donut-center">{center}</div>
      </div>
      <ul className="list donut-legend">
        {data.map((d) => (
          <li key={d.name}>
            <i style={{ background: d.color }} aria-hidden="true" />
            <span className="grow small">{d.name}</span>
            <span className="tab">{total > 0 ? `${((d.value / total) * 100).toFixed(0)}%` : "—"}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── Engine card ──────────────────────────────────────────────────────────────
interface Engine {
  id: string; name: string; subtitle: string; shade: string; paused: boolean;
  slice?: BotSlice; history: BotDay[]; strategyCount?: number;
}

function EngineCard({ e, mktOpen }: { e: Engine; mktOpen: boolean }) {
  const latest = e.history.at(-1);
  const status = e.paused ? { tone: "late" as const, word: "Paused" }
    : !e.slice ? { tone: "none" as const, word: "No data" }
      : getBotStatus(e.slice, mktOpen) === "DOWN" ? { tone: "problem" as const, word: "Stale" }
        : { tone: "ok" as const, word: mktOpen ? "Running" : "Market closed" };
  const curve = withGaps(e.history.filter((d) => d.equity != null).map((d) => ({ date: d.date, equity: d.equity as number })), "equity");
  const deployed = latest?.deployed_pct;
  const dayRet = latest?.daily_return == null ? null : latest.daily_return * 100;
  return (
    <article className="glass panel engine" aria-label={`${e.name} engine`}>
      <div className="panel-head">
        <div className="engine-name">
          <h3 className="card-title"><span className="dot" style={{ background: e.shade, marginRight: 8, verticalAlign: "middle" }} aria-hidden="true" />{e.name}</h3>
          <div className="note clamp" title={e.subtitle}>{e.subtitle}</div>
        </div>
        <Status tone={status.tone} word={status.word} />
      </div>
      {e.slice ? (
        <div className="stat">
          <span className="num">{money(e.slice.equity)}</span>
          <span className="small tab">
            <span className={line(e.slice.pnl)}>{signedMoney(e.slice.pnl) ?? "—"}</span> · {signedPct(e.slice.pnl_pct) ?? "—"} since start
          </span>
        </div>
      ) : (
        <div className="note">{e.paused ? "Shadow test only. No orders are placed." : "No equity reported yet."}</div>
      )}
      <div className="chart engine-chart">
        {curve.length > 1 ? (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={curve} margin={{ top: 4, right: 2, bottom: 0, left: 2 }}>
              <YAxis hide domain={["dataMin", "dataMax"]} />
              <XAxis dataKey="date" hide />
              <Tooltip content={<Tip title={shortDate} fmt={(v) => fmtEq(v)} />} cursor={{ stroke: HAIRLINE }} />
              <Area type="monotone" dataKey="equity" stroke={e.shade} strokeWidth={1.5} fill="none" isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        ) : <Empty>Daily history starts after the first daily close.</Empty>}
      </div>
      <div className="engine-invested">
        <span className="label">Invested</span>
        <span className="small tab">{deployed == null ? "—" : `${(deployed * 100).toFixed(0)}%`}</span>
      </div>
      <div className="meter" role="meter" aria-label="Share invested" aria-valuemin={0} aria-valuemax={100}
        aria-valuenow={deployed == null ? undefined : Math.round(deployed * 100)}>
        <i style={{ width: `${Math.max(0, Math.min(1, deployed ?? 0)) * 100}%`, background: e.shade }} />
      </div>
      <div className="engine-stats">
        <Stat label="Positions" value={String(e.strategyCount ?? e.slice?.positions ?? latest?.positions ?? "—")} />
        <Stat label="Last day" value={signedPct(dayRet)} />
        <Stat label="Win rate" value={e.slice?.win_rate == null ? null : `${(e.slice.win_rate * 100).toFixed(0)}%`} />
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

export default function HomePage() {
  const { fleet, total, allPos, positionsByBot, regime, mktOpen } = useFleetData();
  const registry = useBotRegistry();
  const fleetHistory = useFleetHistory();
  const botHistory = useBotHistory(90);
  const risk = useRiskMetrics();
  const fleetV1 = useFleetV1State();
  const report = useExportReport();

  const engines: Engine[] = useMemo(() => {
    const bots = (registry.data?.bots ?? [])
      .filter((b) => b.status !== "retired")
      .sort((a, b) => a.display_order - b.display_order);
    return bots.map((b) => ({
      id: b.id,
      name: b.display_name,
      subtitle: b.subtitle || b.strategy_label,
      shade: botColor(b.id),
      paused: b.status === "paused",
      slice: (fleet as Record<string, BotSlice | undefined> | undefined)?.[b.id],
      history: botHistory.data?.bots?.[b.id] ?? [],
      strategyCount: (positionsByBot as Record<string, { strategy_count: number }> | undefined)?.[b.id]?.strategy_count,
    }));
  }, [registry.data, fleet, botHistory.data, positionsByBot]);

  const allocation = engines
    .filter((e) => e.slice?.equity != null && e.slice.equity > 0)
    .map((e) => ({ name: e.name, value: e.slice!.equity, color: e.shade }));
  const allocTotal = allocation.reduce((s, d) => s + d.value, 0);

  const holdings = HOLDING_GROUPS.map((name, i) => ({
    name,
    color: NEUTRALS[i % NEUTRALS.length],
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

  const r = risk.data;
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

  const reportButton = (
    <button className="btn glass" onClick={downloadReport} disabled={report.isPending} title="Download the full text report">
      <Download size={15} aria-hidden="true" /> {report.isPending ? "Preparing" : "Report"}
    </button>
  );

  return (
    <Shell home fit actions={reportButton}>
      <section className="glass panel home-summary" aria-label="Fleet summary">
        <div className="stat home-hero">
          <span className="label">Fleet equity · paper</span>
          <span className="display">{money(total?.equity) ?? "—"}</span>
          <span className="small tab">
            <span className={line(total?.pnl)}>{signedMoney(total?.pnl) ?? "—"}</span> · {signedPct(total?.pnl_pct) ?? "—"} since start
          </span>
        </div>
        <div className="home-stats">
          <Stat label="Last 24 hours" value={signedMoney(total?.pnl_24h)} mark={line(total?.pnl_24h)}
            sub={total?.pnl_24h_pct == null ? "vs prior close" : `${signedPct(total.pnl_24h_pct)} vs prior close`} />
          <Stat label="Annual return" value={signedPct(r?.annualised_return_pct, 1)}
            sub={r?.insufficient_data ? "Short history" : "annualised"} />
          <Stat label="Sharpe" value={r?.sharpe_ratio == null ? null : r.sharpe_ratio.toFixed(2)} sub="risk-adjusted" />
          <Stat label="Worst fall" value={r?.max_drawdown_pct == null ? null : `−${Math.abs(r.max_drawdown_pct).toFixed(1)}%`} sub="peak to trough" />
          <Stat label="Volatility" value={r?.volatility_annual_pct == null ? null : `${r.volatility_annual_pct.toFixed(1)}%`} sub="annualised" />
          <Stat label="Open positions" value={total?.positions == null ? null : String(total.positions)}
            sub={`${new Set(allPos.map((p) => p.symbol)).size} symbols`} />
          <Stat label="Market regime" value={regime ? regime.charAt(0) + regime.slice(1).toLowerCase() : null}
            sub={mktOpen ? "US session open" : "US session closed"} />
        </div>
      </section>

      <div className="home-main">
        <div className="home-left">
          <Panel title="Fleet equity · daily close" className="fleet-panel" aside={
            <span className="label">{fleetCurve.length ? `${shortDate(fleetCurve[0].date)} – ${shortDate(fleetCurve.at(-1)!.date)}` : ""}</span>
          }>
            <div className="chart">
              {fleetCurve.length > 1 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={fleetCurve} margin={{ top: 10, right: 6, bottom: 0, left: 6 }}>
                    <XAxis dataKey="date" tickFormatter={shortDate} minTickGap={48} tick={{ fill: AXIS, fontSize: 11 }}
                      axisLine={{ stroke: HAIRLINE }} tickLine={false} />
                    <YAxis domain={["dataMin", "dataMax"]} width={64} tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
                      tick={{ fill: AXIS, fontSize: 11 }} axisLine={false} tickLine={false} />
                    <Tooltip content={<Tip title={shortDate} fmt={(v) => `Fleet equity ${fmtEq(v)}`} />} cursor={{ stroke: HAIRLINE }} />
                    {joins.map((j) => (
                      <ReferenceLine key={j.name} x={fleetCurve.find((p) => p.date >= j.date)?.date} stroke={AXIS}
                        strokeDasharray="3 4" label={{ value: `${j.name} account added`, position: "insideTopRight", fill: AXIS, fontSize: 11 }} />
                    ))}
                    <Area type="monotone" dataKey="equity" stroke={FLEET} strokeWidth={1.5} fill="none" isAnimationActive={false} />
                  </AreaChart>
                </ResponsiveContainer>
              ) : <Empty>No fleet history yet. The first point is saved at tonight's close.</Empty>}
            </div>
          </Panel>
          <div className="engines">
            {engines.length
              ? engines.map((e) => <EngineCard key={e.id} e={e} mktOpen={mktOpen} />)
              : <Empty>{registry.isError ? "Engine list unavailable. Check the trading API." : "Loading engines…"}</Empty>}
          </div>
        </div>

        <div className="home-right">
          <div className="pair">
            <Panel title="Allocation by engine">
              {allocation.length ? (
                <Donut data={allocation} total={allocTotal}
                  center={<><span className="label">Total</span><span className="num-sm">{fmtEq(allocTotal)}</span></>} />
              ) : <Empty>No engine equity reported yet.</Empty>}
            </Panel>
            <Panel title="Holdings mix">
              {holdings.length ? (
                <Donut data={holdings} total={holdingsTotal}
                  center={<><span className="label">Held</span><span className="num-sm">{fmtEq(holdingsTotal)}</span></>} />
              ) : <Empty>No open holdings.</Empty>}
            </Panel>
          </div>

          <Panel title="Daily return by engine" aside={returnEngines.length ? (
            <span className="key">{returnEngines.map((e) => <span key={e.id}><i style={{ background: e.shade }} />{e.name}</span>)}</span>
          ) : undefined}>
            <div className="chart">
              {dailyReturns.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={dailyReturns} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} barGap={1} barCategoryGap="22%">
                    <XAxis dataKey="date" tickFormatter={shortDate} minTickGap={28} tick={{ fill: AXIS, fontSize: 10 }}
                      axisLine={{ stroke: HAIRLINE }} tickLine={false} />
                    <YAxis width={44} tickFormatter={(v: number) => `${v.toFixed(1)}%`} tick={{ fill: AXIS, fontSize: 10 }}
                      axisLine={false} tickLine={false} />
                    <ReferenceLine y={0} stroke={HAIRLINE} />
                    <Tooltip cursor={{ fill: "rgba(255,255,255,0.04)" }} content={<Tip title={shortDate}
                      fmt={(v, row) => `${engines.find((e) => e.id === row.name)?.name ?? row.name}: ${signedPct(v)}`} />} />
                    {returnEngines.map((e) => (
                      <Bar key={e.id} dataKey={e.id} name={e.id} fill={e.shade} isAnimationActive={false} />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              ) : <Empty>Daily returns appear after two daily closes.</Empty>}
            </div>
          </Panel>

          <div className="pair">
            {fleetV1.data ? fleetV1.data.accounts.map((a) => (
              <FleetAccountPanel key={a.bot_id} account={a} state={fleetV1.data!} />
            )) : (
              <Panel title="FLEET-V1">
                <Empty>{fleetV1.isError ? "FLEET-V1 state unavailable. Check the trading API." : "Reading FLEET-V1 state…"}</Empty>
              </Panel>
            )}
          </div>
        </div>
      </div>
    </Shell>
  );
}
