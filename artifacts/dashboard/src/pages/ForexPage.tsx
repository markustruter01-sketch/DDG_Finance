import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { api } from "@/hooks/use-trading-client";
import { Shell, Status } from "@/components/Shell";

// The Forex AI council's record: every day's news, each AI's call and strategy,
// the final decision and why, and how each AI and each strategy has scored.
// Read-only; every value comes from the append-only decision ledger.

type Call = { pair: string; direction: string; strategy?: string | null; conviction?: number | null;
  reason?: string | null; why_not_others?: string | null };
type Decision = Call & { stop_atr_multiple?: number; sided_with?: string; baseline?: string };
type DaySummary = { trading_day: string; status: string; low_confidence: boolean; news_count: number;
  errors: number; trades: Call[]; executed: boolean };
type DayDetail = DaySummary & {
  pack_version: number; record_sha256: string;
  news: { source: string; about: string; title: string; hours_ago: number }[];
  news_sources: { name: string; status: string }[];
  members: Record<string, { provider?: string; model?: string; calls: Call[] }>;
  decisions: Decision[]; errors_list: string[]; execution: Record<string, unknown> | null;
};
type Cell = { calls: number; hit_rate_pct: number | null; avg_return_pct: number | null };
type Scorecard = { days: Record<string, number>; sources: Record<string, Record<string, Cell>>;
  strategies?: Record<string, Record<string, Cell>>; note: string; computed_at?: string };

const PAGE = 10;
const SOURCE_NAME: Record<string, string> = {
  member_1: "Member 1", member_2: "Member 2", decision_maker: "Decider (final call)", baseline: "Baseline rule",
};
const STRATEGY_NAME: Record<string, string> = {
  trend: "Trend", carry: "Carry", mean_reversion: "Mean reversion", event: "News / event", stay_out: "Stay out",
};
const SIDED: Record<string, string> = { member_1: "Member 1", member_2: "Member 2", both: "Both", neither: "Neither" };

const errorText = (e: unknown) => (e instanceof Error ? e.message : "Request failed");
const callText = (c?: Call) =>
  !c ? "—" : c.direction === "flat" ? "Stay out" : `${c.direction === "long" ? "Buy" : "Sell"} · ${STRATEGY_NAME[c.strategy ?? ""] ?? "—"}${c.conviction ? ` · ${c.conviction}/5` : ""}`;
const pctText = (v: number | null | undefined, places = 1) => (v === null || v === undefined ? "—" : `${v.toFixed(places)}%`);

function ScoreTable({ title, rows, names }: { title: string; rows: Record<string, Record<string, Cell>>; names: Record<string, string> }) {
  return (
    <div className="table-scroll">
      <table className="ng">
        <thead><tr><th>{title}</th>{["1d", "5d", "20d"].map((h) => <th key={h} className="money">Right after {h.replace("d", " day")}{h === "1d" ? "" : "s"}</th>)}</tr></thead>
        <tbody>
          {Object.entries(rows).map(([key, byH]) => (
            <tr key={key}>
              <td>{names[key] ?? key}</td>
              {["1d", "5d", "20d"].map((h) => (
                <td key={h} className="money">
                  {byH[h]?.calls ? `${pctText(byH[h].hit_rate_pct)} of ${byH[h].calls} · avg ${pctText(byH[h].avg_return_pct, 2)}` : "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ScorecardPanel() {
  const card = useQuery({
    queryKey: ["forex-council", "scorecard"],
    queryFn: async () => (await api.get("/forex-council/scorecard")).data as Scorecard,
    staleTime: 10 * 60_000,
  });
  return (
    <section className="glass panel" aria-label="Scorecard">
      <div className="panel-head"><h2>Scorecard</h2><span className="label">Who is right · by AI and by strategy</span></div>
      {card.isLoading && <div className="note">Scoring…</div>}
      {card.isError && <Status tone="problem" word={`Scorecard unavailable: ${errorText(card.error)}`} />}
      {card.data && (
        <>
          <p className="small" style={{ margin: 0 }}>
            How often each call moved the right way, and the average move, 1, 5 and 20 trading days later.
            {" "}{card.data.days.logged ?? 0} days logged. {card.data.note}
          </p>
          <ScoreTable title="AI" rows={card.data.sources} names={SOURCE_NAME} />
          {card.data.strategies && <ScoreTable title="Strategy (final calls)" rows={card.data.strategies} names={STRATEGY_NAME} />}
        </>
      )}
    </section>
  );
}

function DayDetailPanel({ day }: { day: string }) {
  const detail = useQuery({
    queryKey: ["forex-council", "day", day],
    queryFn: async () => (await api.get(`/forex-council/day/${day}`)).data as DayDetail,
  });
  if (detail.isLoading) return <div className="note">Reading {day}…</div>;
  if (detail.isError || !detail.data) return <Status tone="problem" word={`Could not read ${day}: ${errorText(detail.error)}`} />;
  const d = detail.data;
  const m1 = d.members.member_1, m2 = d.members.member_2;
  const byPair = (calls?: Call[]) => Object.fromEntries((calls ?? []).map((c) => [c.pair, c]));
  const c1 = byPair(m1?.calls), c2 = byPair(m2?.calls);
  return (
    <>
      <section className="glass panel" aria-label={`Decisions on ${day}`}>
        <div className="panel-head">
          <h2>{day} · decisions</h2>
          <span className="label">
            {d.status === "shadow" ? "Decided" : "No trades"}{d.low_confidence ? " · one member missing (half size)" : ""}
            {d.executed ? " · carried out" : ""}
          </span>
        </div>
        <div className="table-scroll">
          <table className="ng">
            <thead><tr><th>Pair</th><th>Final call</th><th>Why</th><th>Why this strategy</th><th>Sided with</th>
              <th>Member 1{m1?.model ? ` · ${m1.model}` : ""}</th><th>Member 2{m2?.model ? ` · ${m2.model}` : ""}</th><th>Baseline</th></tr></thead>
            <tbody>
              {d.decisions.map((x) => (
                <tr key={x.pair}>
                  <td>{x.pair.replace("_", "/")}</td>
                  <td style={{ whiteSpace: "nowrap" }}>{callText(x)}{x.stop_atr_multiple ? <div className="note">stop {x.stop_atr_multiple}× daily range</div> : null}</td>
                  <td className="small">{x.reason || "—"}</td>
                  <td className="small">{x.why_not_others || (d.pack_version < 2 ? "Not recorded before 7 Nov" : "—")}</td>
                  <td>{SIDED[x.sided_with ?? ""] ?? "—"}</td>
                  <td className="small">{callText(c1[x.pair])}<div className="note">{c1[x.pair]?.reason ?? ""}</div>{c1[x.pair]?.why_not_others ? <div className="note">Why: {c1[x.pair]?.why_not_others}</div> : null}</td>
                  <td className="small">{callText(c2[x.pair])}<div className="note">{c2[x.pair]?.reason ?? ""}</div>{c2[x.pair]?.why_not_others ? <div className="note">Why: {c2[x.pair]?.why_not_others}</div> : null}</td>
                  <td>{x.baseline === "flat" ? "Stay out" : x.baseline === "long" ? "Buy" : x.baseline === "short" ? "Sell" : "—"}</td>
                </tr>
              ))}
              {!d.decisions.length && <tr><td colSpan={8} className="note">No final decision this day.{d.errors_list.length ? ` ${d.errors_list.join(" · ")}` : ""}</td></tr>}
            </tbody>
          </table>
        </div>
        {d.errors_list.length > 0 && d.decisions.length > 0 && <div className="note">Notes: {d.errors_list.join(" · ")}</div>}
        <div className="note">Record fingerprint {d.record_sha256.slice(0, 16)}… (the ledger can't be edited)</div>
      </section>

      <section className="glass panel" aria-label={`News on ${day}`}>
        <div className="panel-head"><h2>What the AIs read</h2><span className="label">{d.news.length} headlines</span></div>
        {d.pack_version < 2 && <div className="note">Before 7 Nov the council saw prices only, no news.</div>}
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
      <main className="controls">
        <div className="page-head">
          <h1 className="page-title">Forex · AI council</h1>
          <button className="btn" onClick={() => days.refetch()}>
            <RefreshCw size={15} aria-hidden="true" /> {days.isFetching ? "Refreshing" : "Refresh"}
          </button>
        </div>
        <p className="small" style={{ margin: 0, maxWidth: 820 }}>
          Every New York trading day, two AIs each read the prices and the day's central-bank and world news, pick a
          strategy for every currency pair and explain why it beat the others. A third AI makes the final call. Rules then
          size every trade and attach a stop. Paper money on the OANDA practice account.
        </p>

        <ScorecardPanel />

        <section className="glass panel" aria-label="Days">
          <div className="panel-head"><h2>Days</h2><span className="label">Newest first · pick a day</span></div>
          {days.isLoading && <div className="note">Reading the ledger…</div>}
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
      </main>
    </Shell>
  );
}
