import { useFleetEquity, useLivePositions } from "@/hooks/use-portfolio";
import { useJournal } from "@/hooks/use-journal";

const RETIRED = new Set(["PSX", "MPC", "BAC", "FTNT", "ARM", "PANW"]);

export function OrbVisualiser() {
  const fleet = useFleetEquity();
  const positions = useLivePositions();
  const journal = useJournal();
  const open = (positions.data?.positions ?? []).filter((p) => !RETIRED.has(p.symbol));
  const closed = (journal.data?.trades ?? []).filter((t) => !RETIRED.has(t.ticker)).slice(0, 8);
  const total = fleet.data?.fleet_total;
  return (
    <div className="h-full overflow-auto bg-[radial-gradient(circle_at_center,#123b56,#020617_62%)] p-6 text-white font-mono">
      <div className="mx-auto max-w-5xl">
        <div className="text-center text-xs tracking-[0.35em] text-cyan-300">ORB · CANONICAL ETF FLEET</div>
        <div className="mx-auto my-8 grid h-40 w-40 place-items-center rounded-full border border-cyan-300/50 bg-cyan-400/10 shadow-[0_0_80px_rgba(34,211,238,.45)]">
          <div className="text-center"><div className="text-[10px] text-cyan-200">FLEET EQUITY</div><div className="mt-2 text-xl font-black">{total ? `$${Math.round(total.equity).toLocaleString()}` : "—"}</div></div>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-xl border border-cyan-400/20 bg-slate-950/60 p-4"><h2 className="text-sm font-bold text-cyan-200">OPEN ETF POSITIONS</h2>{open.length ? open.map((p) => <div key={p.symbol} className="mt-3 flex justify-between text-xs"><span>{p.symbol}</span><span className={p.unrealized_pl >= 0 ? "text-emerald-300" : "text-rose-300"}>{p.unrealized_pl >= 0 ? "+" : ""}${Math.round(p.unrealized_pl).toLocaleString()}</span></div>) : <div className="mt-4 text-xs text-slate-500">No open positions</div>}</div>
          <div className="rounded-xl border border-violet-400/20 bg-slate-950/60 p-4"><h2 className="text-sm font-bold text-violet-200">RECENT CLOSED TRADES</h2>{closed.length ? closed.map((t) => { const pnl = t.pnl_percentage; return <div key={t.trade_id} className="mt-3 flex justify-between text-xs"><span>{t.ticker}</span><span className={pnl != null && pnl >= 0 ? "text-emerald-300" : "text-rose-300"}>{pnl == null ? "—" : `${pnl.toFixed(2)}%`}</span></div>; }) : <div className="mt-4 text-xs text-slate-500">No recent closed ETF trades</div>}</div>
        </div>
      </div>
    </div>
  );
}