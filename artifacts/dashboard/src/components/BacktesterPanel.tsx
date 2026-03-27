import { useState } from "react";
import { useRunBacktest, type BacktestResult } from "@/hooks/use-trading";
import { cn, formatCurrency } from "@/lib/utils";
import { Card, CardHeader, CardTitle, CardContent, Badge } from "@/components/ui";
import { Play, TrendingUp, TrendingDown } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

export function BacktesterPanel() {
  const { mutate: runBacktest, data, isPending, error: mutationError } = useRunBacktest();
  const [lookback, setLookback] = useState(90);

  return (
    <Card className="border-white/5">
      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-4">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Play className="h-4 w-4 text-violet-400" /> Strategy Backtester
          <div className="ml-auto flex items-center gap-2">
            <select
              value={lookback}
              onChange={(e) => setLookback(Number(e.target.value))}
              className="text-[10px] bg-slate-800 border border-white/10 rounded-md px-2 py-1 text-white"
            >
              <option value={30}>30 days</option>
              <option value={60}>60 days</option>
              <option value={90}>90 days</option>
              <option value={180}>180 days</option>
            </select>
            <button
              onClick={() => runBacktest(lookback)}
              disabled={isPending}
              className={cn(
                "flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide px-3 py-1.5 rounded-lg border transition-all",
                isPending
                  ? "border-violet-500/30 bg-violet-500/10 text-violet-400 cursor-wait"
                  : "border-violet-500/20 bg-violet-500/5 text-violet-400/80 hover:bg-violet-500/15 hover:text-violet-400"
              )}
            >
              {isPending ? "Running..." : "Run Backtest"}
            </button>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent className="p-5">
        {!data && !isPending && (
          <div className="text-xs text-muted-foreground italic text-center py-4">
            Click "Run Backtest" to simulate the momentum strategy against historical data
          </div>
        )}

        {isPending && (
          <div className="text-xs text-muted-foreground italic text-center py-4 animate-pulse">
            Simulating strategy against {lookback} days of data...
          </div>
        )}

        {data && !data.error && (
          <div className="space-y-5">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                { label: "Total Return", value: `${data.total_return_pct >= 0 ? "+" : ""}${data.total_return_pct.toFixed(2)}%`, color: data.total_return_pct >= 0 ? "text-green-400" : "text-red-400" },
                { label: "Max Drawdown", value: `-${data.max_drawdown_pct.toFixed(2)}%`, color: data.max_drawdown_pct < 5 ? "text-amber-400" : "text-red-400" },
                { label: "Win Rate", value: `${Math.round(data.win_rate)}%`, color: data.win_rate >= 50 ? "text-green-400" : "text-amber-400" },
                { label: "Total Trades", value: String(data.total_trades), color: "text-white" },
              ].map((s) => (
                <div key={s.label} className="bg-slate-900/70 rounded-xl p-3 border border-white/5">
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1">{s.label}</div>
                  <div className={cn("text-lg font-mono font-bold", s.color)}>{s.value}</div>
                </div>
              ))}
            </div>

            {data.equity_curve?.length > 1 && (
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data.equity_curve}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                    <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#6b7280" }} tickFormatter={(d: string) => d.slice(5)} />
                    <YAxis tick={{ fontSize: 10, fill: "#6b7280" }} tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`} domain={["dataMin", "dataMax"]} />
                    <Tooltip
                      contentStyle={{ background: "#0f172a", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "8px", fontSize: "11px" }}
                      formatter={(v: number) => [formatCurrency(v), "Equity"]}
                      labelFormatter={(l: string) => l}
                    />
                    <Line type="monotone" dataKey="equity" stroke="#8b5cf6" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}

            {data.trades?.length > 0 && (
              <div>
                <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-2 font-semibold">Recent Trades</div>
                <div className="max-h-40 overflow-y-auto space-y-1">
                  {data.trades.slice(-10).reverse().map((t, i) => (
                    <div key={i} className="flex items-center justify-between px-3 py-1.5 rounded-lg bg-slate-900/60 border border-white/5 text-[11px]">
                      <div className="flex items-center gap-2">
                        {t.pnl_pct >= 0 ? <TrendingUp className="h-3 w-3 text-green-400" /> : <TrendingDown className="h-3 w-3 text-red-400" />}
                        <span className="font-semibold text-white">{t.ticker}</span>
                        <span className="text-muted-foreground">{t.entry_date.slice(5)} → {t.exit_date.slice(5)}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className={cn("font-mono font-semibold", t.pnl_pct >= 0 ? "text-green-400" : "text-red-400")}>
                          {t.pnl_pct >= 0 ? "+" : ""}{t.pnl_pct.toFixed(2)}%
                        </span>
                        <Badge variant="outline" className="text-[8px] px-1 py-0">{t.reason}</Badge>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {(data?.error || mutationError) && (
          <div className="text-xs text-red-400 italic">{data?.error || mutationError?.message || "Backtest failed — check server logs"}</div>
        )}
      </CardContent>
    </Card>
  );
}
