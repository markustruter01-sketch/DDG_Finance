import { useAttribution } from "@/hooks/use-trading";
import { cn } from "@/lib/utils";
import { Card, CardHeader, CardTitle, CardContent, Badge } from "@/components/ui";
import { BarChart3 } from "lucide-react";

function WinRateBar({ rate, count }: { rate: number; count: number }) {
  const pct = Math.round(rate);
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 h-2 bg-slate-800 rounded-full overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all", pct >= 60 ? "bg-green-500" : pct >= 45 ? "bg-amber-500" : "bg-red-500")}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={cn("text-[10px] font-mono", pct >= 60 ? "text-green-400" : pct >= 45 ? "text-amber-400" : "text-red-400")}>
        {pct}%
      </span>
      <span className="text-[9px] text-muted-foreground">({count})</span>
    </div>
  );
}

function BucketTable({ title, buckets }: { title: string; buckets: Record<string, { count: number; total_pnl_pct: number; avg_pnl_pct: number; win_rate: number }> | null | undefined }) {
  if (!buckets) return null;
  const entries = Object.entries(buckets).sort((a, b) => b[1].total_pnl_pct - a[1].total_pnl_pct);
  if (!entries.length) return null;

  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-2 font-semibold">{title}</div>
      <div className="space-y-1.5">
        {entries.map(([key, b]) => (
          <div key={key} className="flex items-center justify-between px-3 py-2 rounded-lg bg-slate-900/60 border border-white/5">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-white min-w-[80px]">{key}</span>
              <WinRateBar rate={b.win_rate} count={b.count} />
            </div>
            <div className="flex items-center gap-3">
              <span className="text-[10px] text-muted-foreground">Avg</span>
              <span className={cn("text-xs font-mono font-semibold", b.avg_pnl_pct >= 0 ? "text-green-400" : "text-red-400")}>
                {b.avg_pnl_pct >= 0 ? "+" : ""}{b.avg_pnl_pct.toFixed(2)}%
              </span>
              <span className="text-[10px] text-muted-foreground">Total</span>
              <span className={cn("text-xs font-mono font-semibold", b.total_pnl_pct >= 0 ? "text-green-400" : "text-red-400")}>
                {b.total_pnl_pct >= 0 ? "+" : ""}{b.total_pnl_pct.toFixed(2)}%
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function AttributionPanel() {
  const { data, isLoading } = useAttribution();

  return (
    <Card className="border-white/5">
      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-4">
        <CardTitle className="flex items-center gap-2 text-sm">
          <BarChart3 className="h-4 w-4 text-indigo-400" /> P&amp;L Attribution
          {data?.overall && (
            <span className={cn("text-xs font-mono font-semibold ml-2", data.overall.total_pnl_pct >= 0 ? "text-green-400" : "text-red-400")}>
              {data.overall.total_pnl_pct >= 0 ? "+" : ""}{data.overall.total_pnl_pct.toFixed(2)}%
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-5 space-y-5">
        {isLoading ? (
          <div className="text-xs text-muted-foreground italic">Loading attribution...</div>
        ) : !data || !data.closed_trades ? (
          <div className="text-xs text-muted-foreground italic">No closed trades for attribution analysis</div>
        ) : (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                { label: "Closed Trades", value: String(data.closed_trades), color: "text-white" },
                { label: "Win Rate", value: `${Math.round(data.overall.win_rate)}%`, color: data.overall.win_rate >= 50 ? "text-green-400" : "text-amber-400" },
                { label: "W / L", value: `${data.overall.wins} / ${data.overall.losses}`, color: "text-white" },
                { label: "Avg P&L", value: `${data.overall.avg_pnl_pct >= 0 ? "+" : ""}${data.overall.avg_pnl_pct.toFixed(2)}%`, color: data.overall.avg_pnl_pct >= 0 ? "text-green-400" : "text-red-400" },
              ].map((s) => (
                <div key={s.label} className="bg-slate-900/70 rounded-xl p-3 border border-white/5">
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1">{s.label}</div>
                  <div className={cn("text-lg font-mono font-bold", s.color)}>{s.value}</div>
                </div>
              ))}
            </div>

            <BucketTable title="By Market Regime" buckets={data.regime_attribution} />
            <BucketTable title="By Asset Class" buckets={data.asset_class_attribution} />
            <BucketTable title="By Conviction Level" buckets={data.conviction_attribution} />

            {data.timing_quality.trades_with_fill_data > 0 && (
              <div>
                <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-2 font-semibold">Execution Quality</div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-slate-900/60 rounded-lg p-3 border border-white/5">
                    <div className="text-[10px] text-muted-foreground">Avg Slippage</div>
                    <div className="text-sm font-mono text-amber-400">{data.timing_quality.avg_slippage_pct?.toFixed(3) ?? "—"}%</div>
                  </div>
                  <div className="bg-slate-900/60 rounded-lg p-3 border border-white/5">
                    <div className="text-[10px] text-muted-foreground">Stops Triggered</div>
                    <div className="text-sm font-mono text-red-400">{data.stop_quality.stop_triggered_count}</div>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
