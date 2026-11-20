import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/hooks/use-trading-client";
import { Shell, Status } from "@/components/Shell";
import { rebase, sharedStart } from "@/lib/curves";

// Shadow League (roadmap Phase 1), approved design 20 Nov: overview first on one
// screen (headline numbers, every shadow as a small chart on the same scale, the
// road to the verdict), then the ranked table with a detail panel, then the
// Allocator. Read-only; every figure comes from the API (twins/leaderboard.py),
// this page only formats, filters and sorts it. Ranked best first everywhere.

type Row = {
  id: string; name: string; kind: "real" | "yardstick" | "shadow" | "allocator"; family: string | null;
  days: number; first_day: string | null; last_day: string | null; equity: number | null;
  return_pct: number | null; worst_fall_pct: number | null; days_in_cash: number | null;
  gap_to_spx_pp: number | null; luck: string | null; dsr: number | null; curve: [string, number][];
};
type Board = { league_version: number; note: string; rows: Row[]; regime?: string | null;
  luck_rule: { clear_at_dsr: number; min_days: number; n_trials: number; status: string } };
type Costs = { month: string; model_bps: number;
  market_fills: { fills: number; median_bps?: number; above_model?: boolean } };

const FILTERS: { key: string; label: string; test: (r: Row) => boolean }[] = [
  { key: "all", label: "All", test: () => true },
  { key: "trend", label: "Trend", test: (r) => r.family === "trend" },
  { key: "stocks", label: "Stocks", test: (r) => r.family === "stocks" },
  { key: "diversifier", label: "Diversifiers", test: (r) => r.family === "diversifier" },
  { key: "short_term", label: "Short-term", test: (r) => r.family === "short_term" },
  { key: "forex", label: "Forex", test: (r) => r.family === "forex" },
  { key: "yardstick", label: "Yardsticks", test: (r) => r.kind === "yardstick" },
  { key: "real", label: "Real accounts", test: (r) => r.kind === "real" },
  { key: "allocator", label: "Allocator", test: (r) => r.kind === "allocator" },
];
const FAMILY: Record<string, string> = { trend: "Trend", stocks: "Stocks", diversifier: "Diversifier",
  short_term: "Short-term", forex: "Forex", yardstick: "Yardstick", "real account": "Real account",
  allocator: "Allocator" };
type SortKey = "return_pct" | "worst_fall_pct" | "gap_to_spx_pp" | "days_in_cash" | "dsr";
const COLS: { key: SortKey; label: string }[] = [
  { key: "return_pct", label: "Return after costs" }, { key: "worst_fall_pct", label: "Worst fall" },
  { key: "gap_to_spx_pp", label: "vs S&P 500" }, { key: "days_in_cash", label: "Days in cash" },
  { key: "dsr", label: "Luck check" },
];
const RECORD_DAYS = 252;          // one year of sessions to the Jan 2028 verdict

const tone = (v: number | null) => (v == null || v === 0 ? "" : v > 0 ? "gain" : "loss");
const pct = (v: number | null, signed = true) =>
  v == null ? "—" : `${signed && v > 0 ? "+" : ""}${v.toFixed(2)}%`;
const pts = (v: number | null) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(2)} pts`);
const byReturn = (a: Row, b: Row) => (b.return_pct ?? -1e9) - (a.return_pct ?? -1e9);
const errorText = (e: unknown) => (e instanceof Error ? e.message : "Request failed");

function Spark({ row, spx, lo, hi }: { row: Row; spx: Map<string, number>; lo: number; hi: number }) {
  const w = 140, h = 34, pts2 = row.curve;
  if (pts2.length < 2) return <div className="empty" style={{ minHeight: h }}>too few days</div>;
  const x = (i: number) => (i / (pts2.length - 1)) * w;
  const y = (v: number) => h - ((v - lo) / (hi - lo || 1)) * h;
  const path = (vals: (number | undefined)[]) =>
    vals.map((v, i) => (v == null ? "" : `${i && vals[i - 1] != null ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`)).join("");
  const mine = path(pts2.map(([, v]) => v));
  const s = path(pts2.map(([d]) => spx.get(d)));
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} aria-hidden="true" preserveAspectRatio="none">
      <path d={s} fill="none" stroke="rgba(255,255,255,0.45)" strokeWidth={1} strokeDasharray="3 3" />
      <path d={mine} fill="none" stroke={(row.return_pct ?? 0) < 0 ? "var(--ng-loss, #f5a524)" : "var(--ng-gain, #2fb768)"} strokeWidth={1.6} />
    </svg>
  );
}

function Detail({ row, spxRow }: { row: Row; spxRow: Row | undefined }) {
  // Both lines from the first day they share, so the S&P dashes start at 0% with the line (21 Nov audit).
  const from = spxRow ? sharedStart(row.curve, spxRow.curve) : row.curve[0]?.[0] ?? null;
  const spx = new Map(from && spxRow ? rebase(spxRow.curve, from) : []);
  const data = (from ? rebase(row.curve, from) : []).map(([d, v]) => ({ d, line: v, spx: spx.get(d) ?? null }));
  return (
    <section className="glass panel" aria-label={`${row.name} detail`}>
      <div className="panel-head"><h2>{row.name}</h2><span className="label">{FAMILY[row.family ?? ""] ?? row.family} · {row.id}</span></div>
      <div className="league-detail">
        <div style={{ height: 220 }}>
          {data.length < 2 ? <div className="empty">Not enough days to draw yet.</div> : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <XAxis dataKey="d" tick={{ fill: "rgba(255,255,255,0.62)", fontSize: 11 }} minTickGap={40} />
                <YAxis tick={{ fill: "rgba(255,255,255,0.62)", fontSize: 11 }} width={44} unit="%" />
                <Tooltip contentStyle={{ background: "#141518", border: "1px solid rgba(255,255,255,0.1)" }}
                  formatter={(v: number) => `${v.toFixed(2)}%`} />
                <Line dataKey="spx" name="S&P 500" stroke="rgba(255,255,255,0.6)" strokeDasharray="4 4" dot={false} />
                <Line dataKey="line" name={row.name} stroke="var(--ng-gain, #2fb768)" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="league-detail-stats">
          <div className="stat"><span className="label">Return after costs</span><span className={`num-sm ${tone(row.return_pct)}`}>{pct(row.return_pct)}</span></div>
          <div className="stat"><span className="label">vs S&amp;P 500, same days</span><span className={`num-sm ${tone(row.gap_to_spx_pp)}`}>{pts(row.gap_to_spx_pp)}</span></div>
          <div className="stat"><span className="label">Worst fall</span><span className="num-sm">{pct(row.worst_fall_pct, false)}</span></div>
          <div className="stat"><span className="label">Days valued</span><span className="num-sm">{row.days}</span><span className="small">since {row.first_day ?? "—"}</span></div>
          <div className="stat"><span className="label">Luck check</span><span className="num-sm">{row.luck ?? "—"}</span>{row.dsr != null && <span className="small">DSR {row.dsr.toFixed(2)}</span>}</div>
        </div>
      </div>
    </section>
  );
}

export default function LeaguePage() {
  const board = useQuery({
    queryKey: ["league-leaderboard"],
    queryFn: async () => (await api.get("/league/leaderboard")).data as Board,
    refetchInterval: 15 * 60_000,
  });
  const costs = useQuery({
    queryKey: ["league-costs"],
    queryFn: async () => (await api.get("/league/costs")).data as Costs,
    refetchInterval: 60 * 60_000,
  });
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "return_pct", desc: true });
  const [picked, setPicked] = useState<string | null>(null);

  const rows = board.data?.rows ?? [];
  const shadows = useMemo(() => rows.filter((r) => r.kind === "shadow").sort(byReturn), [rows]);
  const spxRow = rows.find((r) => r.id === "Y-SPX");
  const spx = useMemo(() => new Map(spxRow?.curve ?? []), [spxRow]);
  const [lo, hi] = useMemo(() => {
    const all = [...shadows, ...(spxRow ? [spxRow] : [])].flatMap((r) => r.curve.map(([, v]) => v));
    return all.length ? [Math.min(...all, 0), Math.max(...all, 0)] : [0, 0];
  }, [shadows, spxRow]);
  const funds = Object.fromEntries(rows.filter((r) => r.kind === "allocator").map((r) => [r.id, r]));
  const allocGap = funds["ALLOC-RULES"]?.return_pct != null && funds["ALLOC-EQUAL"]?.return_pct != null
    ? funds["ALLOC-RULES"].return_pct! - funds["ALLOC-EQUAL"].return_pct! : null;
  const valued = shadows.filter((r) => r.gap_to_spx_pp != null);
  const ahead = valued.filter((r) => r.gap_to_spx_pp! > 0).length;
  const clear = shadows.filter((r) => r.luck === "clear").length;
  const recordDays = Math.max(0, ...shadows.map((r) => r.days));

  const table = useMemo(() => {
    const f = FILTERS.find((x) => x.key === filter) ?? FILTERS[0];
    const val = (r: Row) => r[sort.key] as number | null;
    return rows.filter(f.test).sort((a, b) => {
      const va = val(a), vb = val(b);
      if (va == null && vb == null) return byReturn(a, b);
      if (va == null) return 1;
      if (vb == null) return -1;
      return sort.desc ? vb - va : va - vb;
    });
  }, [rows, filter, sort]);
  const pickedRow = rows.find((r) => r.id === picked) ?? table[0];
  const mf = costs.data?.market_fills;

  return (
    <Shell>
      <main className="controls">
        <div className="page-head">
          <div>
            <h1 className="page-title">Shadow League</h1>
            <p className="small" style={{ margin: 0 }}>
              {shadows.length} strategies and 2 Allocator funds on fake money, against 3 yardsticks and the 4 real
              accounts. {board.data?.league_version === 0 ? "Trial run until the lock; the record starts 1 Jan 2027." : board.data?.note}
            </p>
          </div>
          <button className="btn" onClick={() => board.refetch()}>
            <RefreshCw size={15} aria-hidden="true" /> {board.isFetching ? "Refreshing" : "Refresh"}
          </button>
        </div>
        {board.isLoading && <div className="note">Reading the league…</div>}
        {board.isError && <Status tone="problem" word={`League unreadable: ${errorText(board.error)}`} />}

        {board.data && (<>
          <section className="glass panel league-kpis" aria-label="League at a glance">
            <div className="stat"><span className="label">Leading line</span><span className="num-sm">{shadows[0]?.name ?? "—"}</span>
              <span className={`small ${tone(shadows[0]?.return_pct ?? null)}`}>{pct(shadows[0]?.return_pct ?? null)} since start</span></div>
            <div className="stat"><span className="label">Ahead of the S&amp;P</span><span className="num-sm">{ahead} of {shadows.length}</span><span className="small">after costs, same days</span></div>
            <div className="stat"><span className="label">Clear of luck</span><span className="num-sm">{clear} of {shadows.length}</span><span className="small">DSR {board.data.luck_rule.clear_at_dsr}+, {board.data.luck_rule.min_days} days</span></div>
            <div className="stat"><span className="label">Allocator (b) − (a)</span><span className={`num-sm ${tone(allocGap)}`}>{pts(allocGap)}</span><span className="small">needs +1.0 a year</span></div>
            <div className="stat"><span className="label">Market mood</span><span className="num-sm">{board.data.regime ?? "—"}</span><span className="small">Allocator, tonight</span></div>
          </section>

          <section className="glass panel" aria-label="Every shadow at a glance">
            <div className="panel-head"><h2>All {shadows.length} at a glance</h2>
              <span className="label">line vs S&amp;P 500 (dashed) · same scale in every box · best first</span></div>
            <div className="multiples">
              {shadows.map((r) => (
                <button key={r.id} className={`multiple${pickedRow?.id === r.id ? " on" : ""}`} onClick={() => setPicked(r.id)}>
                  <span className="multiple-head"><span>{r.name}</span><span className={tone(r.return_pct)}>{pct(r.return_pct)}</span></span>
                  <Spark row={r} spx={spx} lo={lo} hi={hi} />
                  <span className="small">{FAMILY[r.family ?? ""] ?? r.family} · {r.luck ?? "—"}</span>
                </button>
              ))}
            </div>
          </section>

          <section className="glass panel league-road" aria-label="Road to the verdict">
            <div className="stat"><span className="label">Days of record</span><span className="num-sm">{board.data.league_version === 0 ? 0 : recordDays} / {RECORD_DAYS}</span><span className="small">{board.data.league_version === 0 ? "trial run: not counted" : "to the Jan 2028 verdict"}</span></div>
            <div className="stat"><span className="label">Ahead so far</span><span className="num-sm">{ahead}</span></div>
            <div className="stat"><span className="label">Behind so far</span><span className="num-sm">{valued.length - ahead}</span></div>
            <p className="small" style={{ margin: 0, flex: 1 }}>The pass bar you set: beat the S&amp;P 500, or come within 2 points a year with
              a worst fall at least a third smaller; and pass the luck check. Judged once, in January 2028.</p>
          </section>

          <div className="fold">detail</div>
          <section className="glass panel" aria-label="Every line, ranked">
            <div className="panel-head"><h2>Every line, ranked</h2><span className="label">filter by family · click a column to sort · pick a row</span></div>
            <div className="chips" role="group" aria-label="Filter by family">
              {FILTERS.map((f) => (
                <button key={f.key} className={`chip${filter === f.key ? " on" : ""}`} aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}>{f.label}</button>
              ))}
            </div>
            <div className="table-scroll">
              <table className="ng">
                <thead><tr><th>#</th><th>Line</th><th>Family</th>
                  {COLS.map((c) => (
                    <th key={c.key} aria-sort={sort.key === c.key ? (sort.desc ? "descending" : "ascending") : "none"}>
                      <button className="th-sort" onClick={() => setSort((s) => ({ key: c.key, desc: s.key === c.key ? !s.desc : true }))}>
                        {c.label}{sort.key === c.key ? (sort.desc ? " ↓" : " ↑") : ""}
                      </button>
                    </th>
                  ))}</tr></thead>
                <tbody>
                  {table.map((r, i) => (
                    <tr key={r.id} className={pickedRow?.id === r.id ? "picked" : ""} onClick={() => setPicked(r.id)} style={{ cursor: "pointer" }}>
                      <td className="small">{i + 1}</td>
                      <td>{r.name}<div className="note">{r.id}</div></td>
                      <td className="small">{FAMILY[r.family ?? ""] ?? r.family}</td>
                      <td><span className={tone(r.return_pct)}>{pct(r.return_pct)}</span></td>
                      <td>{pct(r.worst_fall_pct, false)}</td>
                      <td><span className={tone(r.gap_to_spx_pp)}>{pts(r.gap_to_spx_pp)}</span></td>
                      <td>{r.days_in_cash ?? "—"}</td>
                      <td className="small">{r.luck ?? "—"}{r.dsr != null ? ` (${r.dsr.toFixed(2)})` : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          {pickedRow && <Detail row={pickedRow} spxRow={spxRow} />}

          {costs.data && (
            <p className="note">
              Costs, {costs.data.month}: every line is charged {costs.data.model_bps} bps a trade.{" "}
              {mf && mf.fills && mf.median_bps !== undefined
                ? `The real accounts' market orders cost a median ${mf.median_bps.toFixed(1)} bps (${mf.fills} fills)${mf.above_model ? " — above the model" : ""}.`
                : "No real market-order fills measured yet this month."}
            </p>
          )}
          <p className="note">
            Luck check: deflated Sharpe ratio adjusted for {board.data.luck_rule.n_trials} shadows tried; "clear" at
            {" "}{board.data.luck_rule.clear_at_dsr} or more, needs {board.data.luck_rule.min_days} days
            ({board.data.luck_rule.status}). Days in cash come from each shadow's decisions. {board.data.note}
          </p>
        </>)}
      </main>
    </Shell>
  );
}
