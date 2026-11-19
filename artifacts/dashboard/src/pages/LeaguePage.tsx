import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { api } from "@/hooks/use-trading-client";
import { Shell, Status } from "@/components/Shell";

// Shadow League leaderboard (roadmap Phase 1): the four real accounts, three
// yardsticks and every shadow strategy on fake money. Read-only; every figure is
// computed by the API (twins/leaderboard.py), this page only formats it.

type Row = {
  id: string; name: string; kind: "real" | "yardstick" | "shadow"; family: string | null;
  days: number; first_day: string | null; last_day: string | null; equity: number | null;
  return_pct: number | null; worst_fall_pct: number | null; days_in_cash: number | null;
  gap_to_spx_pp: number | null; luck: string | null; dsr: number | null;
};
type Board = { league_version: number; note: string; rows: Row[];
  luck_rule: { clear_at_dsr: number; min_days: number; n_trials: number; status: string } };

type Costs = { month: string; model_bps: number;
  market_fills: { fills: number; median_bps?: number; above_model?: boolean } };

const KIND: Record<Row["kind"], string> = { real: "Real accounts", yardstick: "Yardsticks", shadow: "Shadows" };
const pct = (v: number | null, signed = false) =>
  v === null ? "—" : `${signed && v > 0 ? "+" : ""}${v.toFixed(2)}%`;
const pp = (v: number | null) => (v === null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(2)} pts`);
const errorText = (e: unknown) => (e instanceof Error ? e.message : "Request failed");

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
  const rows = board.data?.rows ?? [];
  const mf = costs.data?.market_fills;
  return (
    <Shell>
      <main className="controls">
        <div className="page-head">
          <h1 className="page-title">Shadow League</h1>
          <button className="btn" onClick={() => board.refetch()}>
            <RefreshCw size={15} aria-hidden="true" /> {board.isFetching ? "Refreshing" : "Refresh"}
          </button>
        </div>
        <p className="small" style={{ margin: 0 }}>
          Every strategy on fake money, valued at each US close with the same costs. No orders. Real accounts show
          their real balance. {board.data?.note}
        </p>
        {board.isLoading && <div className="note">Reading the league…</div>}
        {board.isError && <Status tone="problem" word={`League unreadable: ${errorText(board.error)}`} />}
        {(["real", "yardstick", "shadow"] as const).map((kind) => {
          const part = rows.filter((r) => r.kind === kind);
          if (!part.length) return null;
          return (
            <section key={kind} className="glass panel" aria-label={KIND[kind]}>
              <div className="panel-head"><h2>{KIND[kind]}</h2><span className="label">{part.length} lines</span></div>
              <div className="table-scroll">
                <table className="ng">
                  <thead>
                    <tr><th>Line</th><th>Since</th><th>Return after costs</th><th>Worst fall</th>
                      <th>Days in cash</th><th>Gap to S&amp;P 500</th><th>Luck check</th></tr>
                  </thead>
                  <tbody>
                    {part.map((r) => (
                      <tr key={r.id}>
                        <td>{r.name}<div className="note">{r.id}</div></td>
                        <td className="small">{r.first_day ?? "—"}{r.days ? ` · ${r.days} days` : ""}</td>
                        <td>{pct(r.return_pct, true)}</td>
                        <td>{pct(r.worst_fall_pct)}</td>
                        <td>{r.days_in_cash ?? "—"}</td>
                        <td>{pp(r.gap_to_spx_pp)}</td>
                        <td className="small">{r.luck ?? "—"}{r.dsr !== null ? ` (${r.dsr.toFixed(2)})` : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          );
        })}
        {costs.data && (
          <p className="note">
            Costs, {costs.data.month}: every line is charged {costs.data.model_bps} bps a trade.{" "}
            {mf && mf.fills && mf.median_bps !== undefined
              ? `The real accounts' market orders cost a median ${mf.median_bps.toFixed(1)} bps (${mf.fills} fills)${mf.above_model ? " — above the model" : ""}.`
              : "No real market-order fills measured yet this month."}
          </p>
        )}
        {board.data && (
          <p className="note">
            Luck check: deflated Sharpe ratio adjusted for {board.data.luck_rule.n_trials} shadows tried; "clear" at
            {" "}{board.data.luck_rule.clear_at_dsr} or more, needs {board.data.luck_rule.min_days} days
            ({board.data.luck_rule.status}). Days in cash come from each shadow's decisions.
          </p>
        )}
      </main>
    </Shell>
  );
}
