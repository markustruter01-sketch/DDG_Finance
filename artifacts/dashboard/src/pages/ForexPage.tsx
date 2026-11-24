import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/hooks/use-trading-client";
import { useLeaderboard } from "@/hooks/use-leaderboard";
import { Shell, Status } from "@/components/Shell";
import { rebase, returnSince, sharedStart } from "@/lib/curves";
import { Loading } from "@/components/Motion";

// The Forex AI council's record: every day's news, each AI's call and strategy,
// the final decision and why, and how each AI and each strategy has scored.
// Read-only; every value comes from the append-only decision ledger.

type Call = { pair: string; direction: string; strategy?: string | null; conviction?: number | null;
  reason?: string | null; why_not_others?: string | null;
  expected_move_pct?: number | null; horizon_days?: number | null; expected_path?: string | null };
type Decision = Call & { stop_atr_multiple?: number; sided_with?: string; baseline?: string;
  votes?: Record<string, string>; outcome?: string; half_size?: boolean };
type DaySummary = { trading_day: string; status: string; low_confidence: boolean; news_count: number;
  errors: number; trades: Call[]; executed: boolean };
type DayDetail = DaySummary & {
  pack_version: number; council_version?: number; record_sha256: string;
  news: { source: string; about: string; title: string; hours_ago: number }[];
  news_sources: { name: string; status: string }[];
  members: Record<string, { provider?: string; model?: string; calls: Call[] }>;
  decisions: Decision[]; errors_list: string[]; execution: Record<string, unknown> | null;
};
type Cell = { calls: number; hit_rate_pct: number | null; avg_return_pct: number | null };
type PredCell = { predictions: number; direction_right_pct: number | null; avg_predicted_pct: number | null;
  avg_actual_pct: number | null; avg_miss_pct: number | null };
type Scorecard = { days: Record<string, number>; sources: Record<string, Record<string, Cell>>;
  strategies?: Record<string, Record<string, Cell>>; convictions?: Record<string, Record<string, Cell>>; predictions?: Record<string, PredCell>; note: string; computed_at?: string };

const PAGE = 10;
const SOURCE_NAME: Record<string, string> = {
  member_1: "Member 1", member_2: "Member 2", member_3: "Member 3", decision_maker: "Final call", baseline: "Baseline rule",
};
const STRATEGY_NAME: Record<string, string> = {
  trend: "Trend", carry: "Carry", mean_reversion: "Mean reversion", event: "News / event", stay_out: "Stay out",
};
const CONVICTION_NAME: Record<string, string> = { "1": "1 · unsure", "2": "2", "3": "3", "4": "4", "5": "5 · very sure" };
const SIDED: Record<string, string> = { member_1: "Member 1", member_2: "Member 2", both: "Both", neither: "Neither" };
// Council v3 vote ("3-0" full size, "2-1" half size, "split" stay out); older days show who the decider sided with.
const voteText = (x: Decision) =>
  !x.outcome ? `Decider sided with ${SIDED[x.sided_with ?? ""] ?? "—"}`
    : x.outcome === "split" ? "Split · stay out"
    : `${x.outcome}${x.direction === "flat" ? "" : x.half_size ? " · half size" : " · full size"}`;

const errorText = (e: unknown) => (e instanceof Error ? e.message : "Request failed");
const callText = (c?: Call) =>
  !c ? "—" : c.direction === "flat" ? "Stay out" : `${c.direction === "long" ? "Buy" : "Sell"} · ${STRATEGY_NAME[c.strategy ?? ""] ?? "—"}${c.conviction ? ` · ${c.conviction}/5` : ""}`;
const signed = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
// "Expects +0.80% in 5 days: drifts lower…" — the AI's own prediction of how the trade plays out.
const predictionText = (c?: Call) =>
  c?.expected_move_pct === undefined || c?.expected_move_pct === null || !c.horizon_days ? null
    : `Expects ${signed(c.expected_move_pct)} in ${c.horizon_days} day${c.horizon_days > 1 ? "s" : ""}${c.expected_path ? `: ${c.expected_path}` : ""}`;
const Prediction = ({ c }: { c?: Call }) => { const t = predictionText(c); return t ? <div className="note">{t}</div> : null; };
const pctText = (v: number | null | undefined, places = 1) => (v === null || v === undefined ? "—" : `${v.toFixed(places)}%`);

function ScoreTable({ title, rows, names }: { title: string; rows: Record<string, Record<string, Cell>>; names: Record<string, string> }) {
  return (
    <div className="table-scroll">
      <table className="ng">
        <thead><tr><th>{title}</th>{["1d", "5d", "20d"].map((h) => <th key={h} className="money">After {h.replace("d", " day")}{h === "1d" ? "" : "s"}</th>)}</tr></thead>
        <tbody>
          {Object.entries(rows).map(([key, byH]) => (
            <tr key={key}>
              <td>{names[key] ?? key}</td>
              {["1d", "5d", "20d"].map((h) => (
                <td key={h} className="money">
                  {byH[h]?.calls ? <>{pctText(byH[h].hit_rate_pct)} of {byH[h].calls}<div className="note">avg {pctText(byH[h].avg_return_pct, 2)}</div></> : "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}


// Overview first (approved design 20 Nov): the account, the question this page
// answers (is the AI beating the same rules without AI?), and what is open now.
type BoardRow = { id: string; name: string; return_pct: number | null; worst_fall_pct: number | null; curve: [string, number][] };
type OpenTrades = { nav: number; balance: number; margin_used: number;
  open: { pair: string; side: string; units: number; entry: number | null; stop: number | null; unrealized_usd: number | null }[] };
const LINES = [{ id: "forex_ai", name: "AI council (real account)", color: "var(--ng-gain, #2fb768)" },
  { id: "FX-BT1", name: "FX-BT1 · same rules, no AI", color: "rgba(255,255,255,0.75)" },
  { id: "FX-TREND", name: "Simple trend", color: "rgba(255,255,255,0.4)" }];
const tone = (v: number | null | undefined) => (v == null || v === 0 ? "" : v > 0 ? "gain" : "loss");

function ForexOverview() {
  const board = useLeaderboard<{ rows: BoardRow[] }>();
  const cost = useQuery({ queryKey: ["forex-council-costs"], queryFn: async () => (await api.get("/forex-council/costs")).data as { months: { month: string; usd: number; calls: number; unpriced: number }[] } });
  const thisMonth = cost.data?.months[0];
  const open = useQuery({ queryKey: ["forex-open"], queryFn: async () => (await api.get("/forex/open")).data as OpenTrades, refetchInterval: 5 * 60_000 });
  const rows = Object.fromEntries((board.data?.rows ?? []).map((r) => [r.id, r]));
  const me = rows.forex_ai, bt1 = rows["FX-BT1"];
  // Compared only over the days both lines have (the real account starts 9 Nov, FX-BT1 on 19 Nov).
  const from = me && bt1 ? sharedStart(me.curve, bt1.curve) : null;
  const meR = from && me ? returnSince(me.curve, from) : null, btR = from && bt1 ? returnSince(bt1.curve, from) : null;
  const gap = meR != null && btR != null ? meR - btR : null;
  const days = new Map<string, Record<string, number | string>>();
  for (const l of LINES) for (const [d, v] of from ? rebase(rows[l.id]?.curve ?? [], from) : []) days.set(d, { ...(days.get(d) ?? { d }), [l.id]: v });
  const data = [...days.values()].sort((a, b) => String(a.d).localeCompare(String(b.d)));
  const o = open.data;
  return (<>
    <section className="glass panel league-kpis" aria-label="Forex at a glance">
      <div className="stat"><span className="label">Account value</span><span className="num-sm">{o ? `$${o.nav.toLocaleString("en-AU", { maximumFractionDigits: 0 })}` : "—"}</span><span className="small">OANDA practice, now</span></div>
      <div className="stat"><span className="label">Return since start</span><span className={`num-sm ${tone(me?.return_pct)}`}>{me?.return_pct == null ? "—" : signed(me.return_pct)}</span><span className="small">since 9 Nov, after costs</span></div>
      <div className="stat"><span className="label">vs no-AI rules</span><span className={`num-sm ${tone(gap)}`}>{gap == null ? "—" : `${gap > 0 ? "+" : ""}${gap.toFixed(2)} pts`}</span><span className="small">against FX-BT1, since {from ?? "—"}</span></div>
      <div className="stat"><span className="label">Worst fall</span><span className="num-sm">{me?.worst_fall_pct == null ? "—" : `${me.worst_fall_pct.toFixed(2)}%`}</span><span className="small">since start</span></div>
      <div className="stat"><span className="label">AI cost</span><span className="num-sm">{thisMonth ? `US$${thisMonth.usd.toFixed(2)}` : "—"}</span><span className="small">{thisMonth ? `${thisMonth.month} · ${thisMonth.calls} calls${thisMonth.unpriced ? ` · ${thisMonth.unpriced} unpriced` : ""}` : "no council days yet"}</span></div>
      <div className="stat"><span className="label">Open trades</span><span className="num-sm">{o ? o.open.length : "—"}</span><span className="small">{o ? `$${o.margin_used.toLocaleString("en-AU", { maximumFractionDigits: 0 })} margin used` : "OANDA unreadable"}</span></div>
    </section>
    <div className="me-two" style={{ gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)" }}>
      <section className="glass panel" aria-label="Does the AI add anything">
        <div className="panel-head"><h2>Does the AI add anything?</h2><span className="label">return since {from ?? "—"} (first shared day), same costs</span></div>
        <div style={{ height: 240 }}>
          {data.length < 2 ? <div className="empty">Not enough days to draw yet.</div> : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <XAxis dataKey="d" tick={{ fill: "rgba(255,255,255,0.62)", fontSize: 11 }} minTickGap={40} />
                <YAxis tick={{ fill: "rgba(255,255,255,0.62)", fontSize: 11 }} width={44} unit="%" />
                <Tooltip contentStyle={{ background: "#141518", border: "1px solid rgba(255,255,255,0.1)" }} formatter={(v: number) => `${v.toFixed(2)}%`} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                {LINES.map((l) => <Line key={l.id} dataKey={l.id} name={l.name} stroke={l.color} strokeWidth={l.id === "forex_ai" ? 2 : 1.4} dot={false} connectNulls />)}
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </section>
      <section className="glass panel" aria-label="Open now">
        <div className="panel-head"><h2>Open now</h2><span className="label">straight from OANDA</span></div>
        {open.isError && <Status tone="problem" word="OANDA unreadable" />}
        {o && !o.open.length && <div className="empty">No open trades.</div>}
        {o && o.open.length > 0 && (
          <table className="ng"><tbody>{o.open.map((t) => (
            <tr key={t.pair}><td>{t.pair.replace("_", "/")}<div className="note">{t.side} · {t.units.toLocaleString("en-AU")} units{t.stop ? ` · stop ${t.stop}` : " · no stop"}</div></td>
              <td><span className={tone(t.unrealized_usd)}>{t.unrealized_usd == null ? "—" : `${t.unrealized_usd > 0 ? "+" : t.unrealized_usd < 0 ? "−" : ""}$${Math.abs(t.unrealized_usd).toFixed(0)}`}</span></td></tr>
          ))}</tbody></table>
        )}
      </section>
    </div>
    <div className="fold">detail</div>
  </>);
}

// Three panels side by side: AI record, strategy record, predictions. A dash = not enough days yet.
function ScorecardPanels() {
  const card = useQuery({
    queryKey: ["forex-council", "scorecard"],
    queryFn: async () => (await api.get("/forex-council/scorecard")).data as Scorecard,
    staleTime: 10 * 60_000,
  });
  if (card.isLoading) return <section className="glass panel"><div className="note"><Loading>Scoring…</Loading></div></section>;
  if (card.isError || !card.data) return <section className="glass panel"><Status tone="problem" word={`Scorecard unavailable: ${errorText(card.error)}`} /></section>;
  const c = card.data;
  return (
    <div className="forex-score">
      <section className="glass panel" aria-label="Scorecard by AI">
        <div className="panel-head"><h2>Scorecard · by AI</h2><span className="label">{c.days.logged ?? 0} days logged</span></div>
        <ScoreTable title="AI" rows={c.sources} names={SOURCE_NAME} />
        <div className="note">How often each call moved the right way, and the average move. {c.note} A dash means not enough days have passed yet.</div>
      </section>
      {c.strategies && (
        <section className="glass panel" aria-label="Scorecard by strategy">
          <div className="panel-head"><h2>By strategy and how sure</h2><span className="label">Final calls</span></div>
          <ScoreTable title="Strategy" rows={c.strategies} names={STRATEGY_NAME} />
          {c.convictions && <ScoreTable title="How sure (1-5)" rows={c.convictions} names={CONVICTION_NAME} />}
          <div className="note">Strategies are recorded from 6 Nov 2026. If surer calls win more often, bigger sizing on them can be tested later.</div>
        </section>
      )}
      {c.predictions && (
        <section className="glass panel" aria-label="Predictions">
          <div className="panel-head"><h2>Predictions</h2><span className="label">Predicted vs actual move</span></div>
          <div className="table-scroll">
            <table className="ng">
              <thead><tr><th>AI</th><th className="money">Checked</th><th className="money">Way right</th>
                <th className="money">Predicted</th><th className="money">Actual</th><th className="money">Miss</th></tr></thead>
              <tbody>
                {Object.entries(c.predictions).map(([key, p]) => (
                  <tr key={key}>
                    <td>{SOURCE_NAME[key] ?? key}</td>
                    <td className="money">{p.predictions || "—"}</td>
                    <td className="money">{pctText(p.direction_right_pct)}</td>
                    <td className="money">{p.avg_predicted_pct === null ? "—" : signed(p.avg_predicted_pct)}</td>
                    <td className="money">{p.avg_actual_pct === null ? "—" : signed(p.avg_actual_pct)}</td>
                    <td className="money">{pctText(p.avg_miss_pct, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="note">Each prediction is checked once its own horizon has passed. Predictions start 6 Nov 2026.</div>
        </section>
      )}
    </div>
  );
}

const useDay = (day: string) => useQuery({
  queryKey: ["forex-council", "day", day],
  queryFn: async () => (await api.get(`/forex-council/day/${day}`)).data as DayDetail,
});

function NewsPanel({ day }: { day: string }) {
  const d = useDay(day).data;
  if (!d) return null;
  return (
    <section className="glass panel" aria-label={`News on ${day}`}>
      <div className="panel-head"><h2>What the AIs read · {day}</h2><span className="label">{d.news.length} headlines</span></div>
      {d.pack_version < 2 && <div className="note">Before 6 Nov the council saw prices only, no news.</div>}
      {d.news.length > 0 && (
        <ul className="list">
          {d.news.map((n, i) => (
            <li key={i}><span className="label" style={{ minWidth: 48 }}>{n.about}</span><span className="grow small">{n.title}</span>
              <span className="note" style={{ whiteSpace: "nowrap" }}>{n.source} · {n.hours_ago} h ago</span></li>
          ))}
        </ul>
      )}
      {d.news_sources.length > 0 && <div className="note">Sources: {d.news_sources.map((s) => `${s.name} ${s.status}`).join(" · ")}</div>}
    </section>
  );
}

function DayDetailPanel({ day }: { day: string }) {
  const detail = useDay(day);
  if (detail.isLoading) return <div className="note"><Loading>Reading {day}…</Loading></div>;
  if (detail.isError || !detail.data) return <Status tone="problem" word={`Could not read ${day}: ${errorText(detail.error)}`} />;
  const d = detail.data;
  const roles = ["member_1", "member_2", "member_3"].filter((r) => r !== "member_3" || (d.council_version ?? 2) >= 3);
  const byPair = (calls?: Call[]) => Object.fromEntries((calls ?? []).map((c) => [c.pair, c]));
  const memberCalls = Object.fromEntries(roles.map((r) => [r, byPair(d.members[r]?.calls)]));
  return (
    <>
      <section className="glass panel" aria-label={`Decisions on ${day}`}>
        <div className="panel-head">
          <h2>{day} · decisions</h2>
          <span className="label">
            {d.status === "shadow" ? "Decided" : "No trades"}{d.low_confidence ? " · an AI missing" : ""}
            {d.executed ? " · carried out" : ""}
          </span>
        </div>
        <div className="table-scroll">
          <table className="ng">
            <thead><tr><th>Pair</th><th>Final call</th><th>Why</th><th>Why this strategy</th><th>Vote</th>
              {roles.map((r) => <th key={r}>{SOURCE_NAME[r]}{d.members[r]?.model ? ` · ${d.members[r]?.model}` : ""}</th>)}<th>Baseline</th></tr></thead>
            <tbody>
              {d.decisions.map((x) => (
                <tr key={x.pair}>
                  <td>{x.pair.replace("_", "/")}</td>
                  <td>{callText(x)}{x.stop_atr_multiple ? <div className="note">stop {x.stop_atr_multiple}× daily range</div> : null}<Prediction c={x} /></td>
                  <td className="small">{x.reason || "—"}</td>
                  <td className="small">{x.why_not_others || (d.pack_version < 2 ? "Not recorded before 6 Nov" : "—")}</td>
                  <td style={{ whiteSpace: "nowrap" }}>{voteText(x)}</td>
                  {roles.map((r) => {
                    const c = memberCalls[r][x.pair];
                    return <td key={r} className="small">{callText(c)}<div className="note">{c?.reason ?? ""}</div>{c?.why_not_others ? <div className="note">Why: {c.why_not_others}</div> : null}<Prediction c={c} /></td>;
                  })}
                  <td>{x.baseline === "flat" ? "Stay out" : x.baseline === "long" ? "Buy" : x.baseline === "short" ? "Sell" : "—"}</td>
                </tr>
              ))}
              {!d.decisions.length && <tr><td colSpan={6 + roles.length} className="note">No final decision this day.{d.errors_list.length ? ` ${d.errors_list.join(" · ")}` : ""}</td></tr>}
            </tbody>
          </table>
        </div>
        {d.errors_list.length > 0 && d.decisions.length > 0 && <div className="note">Notes: {d.errors_list.join(" · ")}</div>}
        <div className="note">Record fingerprint {d.record_sha256.slice(0, 16)}… (the ledger can't be edited)</div>
      </section>

    </>
  );
}

export default function ForexPage() {
  const [page, setPage] = useState(0);
  const [picked, setPicked] = useState<string | null>(null);
  const days = useQuery({
    queryKey: ["forex-council", "days"],
    queryFn: async () => (await api.get("/forex-council/days", { params: { limit: 400 } })).data as { days: DaySummary[] },
    refetchInterval: 5 * 60_000,
  });
  const all = days.data?.days ?? [];
  const pages = Math.max(1, Math.ceil(all.length / PAGE));
  const current = Math.min(page, pages - 1);
  const shown = all.slice(current * PAGE, (current + 1) * PAGE);
  const selected = picked ?? all[0]?.trading_day ?? null;

  return (
    <Shell>
      <main className="controls forex">
        <div className="page-head">
          <h1 className="page-title">Forex · AI council</h1>
          <button className="btn" onClick={() => days.refetch()}>
            <RefreshCw size={15} aria-hidden="true" /> {days.isFetching ? "Refreshing" : "Refresh"}
          </button>
        </div>
        <p className="small" style={{ margin: 0 }}>Three AIs vote every New York trading day on 7 US-dollar pairs. Practice money on OANDA.</p>

        <ForexOverview />
        <p className="small" style={{ margin: 0 }} aria-label="How the council works">
          Every New York trading day, three AIs each read the prices and the day's central-bank and world news, and on
          their own pick a direction and strategy for every currency pair, say why it beat the others and predict how
          the trade will play out. Then they vote: 3-0 trades full size, 2-1 half size, a three-way split stays out.
          Rules then size every trade and attach a stop. Paper money on the OANDA practice account.
        </p>
        <ScorecardPanels />

        <div className="forex-days">
        <section className="glass panel" aria-label="Days">
          <div className="panel-head"><h2>Days</h2><span className="label">Newest first · pick a day</span></div>
          {days.isLoading && <div className="note"><Loading>Reading the ledger…</Loading></div>}
          {days.isError && <Status tone="problem" word={`Ledger unreadable: ${errorText(days.error)}`} />}
          <div className="table-scroll">
            <table className="ng">
              <thead><tr><th>Day</th><th>Result</th><th>Trades</th><th>News</th></tr></thead>
              <tbody>
                {shown.map((d) => (
                  <tr key={d.trading_day} onClick={() => setPicked(d.trading_day)} style={{ cursor: "pointer", background: d.trading_day === selected ? "rgba(255,255,255,0.05)" : undefined }}>
                    <td><button className="btn" style={{ minHeight: 30 }} onClick={() => setPicked(d.trading_day)} aria-pressed={d.trading_day === selected}>{d.trading_day}</button></td>
                    <td>{d.status === "shadow" ? "Decided" : "No trades"}{d.low_confidence ? " · 1 AI missing" : ""}{d.errors ? ` · ${d.errors} note${d.errors > 1 ? "s" : ""}` : ""}</td>
                    <td className="small">{d.trades.length ? d.trades.map((t) => `${t.pair.replace("_", "/")} ${t.direction === "long" ? "buy" : "sell"}${t.strategy ? ` (${STRATEGY_NAME[t.strategy] ?? t.strategy})` : ""}`).join(" · ") : "None"}</td>
                    <td>{d.news_count || "—"}</td>
                  </tr>
                ))}
                {!days.isLoading && !all.length && <tr><td colSpan={4} className="note">No council days logged yet.</td></tr>}
              </tbody>
            </table>
          </div>
          {pages > 1 && (
            <div style={{ display: "flex", gap: 12, justifyContent: "flex-end", alignItems: "center" }}>
              <button className="btn" disabled={current === 0} onClick={() => setPage(current - 1)}>Newer</button>
              <span className="note">Page {current + 1} of {pages}</span>
              <button className="btn" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>Older</button>
            </div>
          )}
        </section>

        {selected && <DayDetailPanel day={selected} />}
        </div>
        {selected && <NewsPanel day={selected} />}
      </main>
    </Shell>
  );
}
