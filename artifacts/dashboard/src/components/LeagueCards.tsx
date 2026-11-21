/** Home's bottom row (approved design, 20 Nov 2026): League top 5, the two
 *  Allocator shadow funds with tonight's mood, and Record keeping. Every figure
 *  comes from the API (/league/leaderboard, /league/records); this file formats. */
import { useQuery } from "@tanstack/react-query";
import { Link } from "wouter";
import { api } from "@/hooks/use-trading-client";
import { useLeaderboard } from "@/hooks/use-leaderboard";
import { Status, bneTime } from "@/components/Shell";

export type LeagueRow = {
  id: string; name: string; kind: "real" | "yardstick" | "shadow" | "allocator"; family: string | null;
  days: number; first_day: string | null; return_pct: number | null; worst_fall_pct: number | null;
  days_in_cash: number | null; gap_to_spx_pp: number | null; luck: string | null; dsr: number | null; equity: number | null;
};
export type Board = { league_version: number; note: string; regime?: string | null; rows: LeagueRow[];
  luck_rule: { clear_at_dsr: number; min_days: number; n_trials: number; status: string } };
type Records = {
  logs: { lines: number; broken: string[] }; league_last_run: string | null; last_frozen_month: string | null;
  costs: { model_bps: number; fills?: number; median_bps?: number; above_model?: boolean };
  heartbeat: { runner: boolean; api: boolean };
};

export const pct = (v: number | null | undefined, signed = true) =>
  v == null ? "—" : `${signed && v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}%`;
export const pts = (v: number | null | undefined) =>
  v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)} pts`;

export function useLeague() {
  return useLeaderboard<Board>();
}

// The Allocator's table (research_harness/league/allocator.TABLE), for the "leaning to" line.
const LEAN: Record<string, string> = {
  "calm up": "trend 35% · stocks 35% · diversifiers 10% · short-term 10% · forex 10%",
  "rough up": "trend 25% · stocks 25% · diversifiers 25% · short-term 10% · forex 15%",
  "calm down": "trend 20% · stocks 15% · diversifiers 35% · short-term 10% · forex 20%",
  "rough down": "trend 15% · stocks 10% · diversifiers 40% · short-term 10% · forex 25%",
};
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export function LeagueTop({ board, error }: { board?: Board; error: boolean }) {
  const top = (board?.rows ?? []).filter((r) => r.kind === "shadow" && r.return_pct != null)
    .sort((a, b) => (b.return_pct ?? 0) - (a.return_pct ?? 0)).slice(0, 5);
  return (
    <section className="glass panel league-top" aria-label="League top 5">
      <div className="panel-head"><h2>League · top 5</h2><Link href="/league" className="small link">All lines ›</Link></div>
      {top.length ? (
        <div className="table-scroll">
          <table className="ng">
            <thead><tr><th>#</th><th>Line</th><th className="money">Return</th><th className="money">vs S&amp;P</th><th>Luck check</th></tr></thead>
            <tbody>{top.map((r, i) => (
              <tr key={r.id}><td className="mono note">{i + 1}</td><td>{r.name}</td><td className="money">{pct(r.return_pct)}</td>
                <td className="money">{r.gap_to_spx_pp == null ? "—" : pts(r.gap_to_spx_pp).replace(" pts", "")}</td>
                <td><Status tone={r.luck === "clear" ? "ok" : "none"} word={r.luck ? cap(r.luck) : "—"} /></td></tr>
            ))}</tbody>
          </table>
        </div>
      ) : <div className="empty">{error ? "League unreadable. Check the trading API." : "The league values its lines after each US close."}</div>}
    </section>
  );
}

export function AllocatorCard({ board }: { board?: Board }) {
  const fund = (id: string) => board?.rows.find((r) => r.id === id);
  const a = fund("ALLOC-EQUAL"), b = fund("ALLOC-RULES");
  const mood = board?.regime ?? null;
  return (
    <section className="glass panel" aria-label="Allocator shadow funds">
      <div className="panel-head"><h2>Allocator · shadow funds</h2><span className="label">{mood ? `Mood: ${mood}` : "Mood: —"}</span></div>
      <div className="alloc-pair">
        <div className="stat"><span className="label">(a) Equal money</span><span className="num">{pct(a?.return_pct)}</span><span className="small">every line the same</span></div>
        <div className="stat"><span className="label">(b) Rules by mood</span><span className="num">{pct(b?.return_pct)}</span><span className="small">must beat (a) by 1 pt a year</span></div>
      </div>
      <span className="small">{mood ? `Leaning to: ${LEAN[mood] ?? "—"}` : "Tonight's mood is set after the US close."}</span>
    </section>
  );
}

export function RecordsCard() {
  const q = useQuery({
    queryKey: ["league-records"],
    queryFn: async () => (await api.get("/league/records")).data as Records,
    refetchInterval: 15 * 60_000,
  });
  const r = q.data;
  const month = r?.last_frozen_month
    ? new Date(`${r.last_frozen_month}T00:00:00Z`).toLocaleDateString("en-AU", { month: "short", year: "numeric", timeZone: "UTC" })
    : null;
  const c = r?.costs;
  return (
    <section className="glass panel" aria-label="Record keeping">
      <div className="panel-head"><h2>Record keeping</h2>{r?.league_last_run && <span className="label">League night {bneTime(r.league_last_run)}</span>}</div>
      {r ? (
        <ul className="list records">
          <li><Status tone={r.logs.broken.length ? "problem" : "ok"} word={r.logs.broken.length ? `${r.logs.broken.length} decision log(s) broken` : "Decision logs intact"} /><span className="grow" /><span className="small tab">{r.logs.lines} lines</span></li>
          <li><Status tone={month ? "ok" : "none"} word="Month frozen" /><span className="grow" /><span className="small tab">{month ?? "first: 1 Dec"}</span></li>
          <li><Status tone={c?.above_model ? "late" : c?.fills ? "ok" : "none"} word="Trade costs vs model" /><span className="grow" />
            <span className="small tab">{c?.fills ? `${c.median_bps?.toFixed(1)} / ${c.model_bps.toFixed(1)} bps` : `— / ${c?.model_bps.toFixed(1) ?? "5.0"} bps`}</span></li>
          <li><Status tone={r.heartbeat.runner ? "ok" : "late"} word="Outside heartbeat" /><span className="grow" /><span className="small tab">{r.heartbeat.runner ? "on" : "not set up"}</span></li>
        </ul>
      ) : <div className="empty">{q.isError ? "Records unreadable. Check the trading API." : "Reading records…"}</div>}
    </section>
  );
}
