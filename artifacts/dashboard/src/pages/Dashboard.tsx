import { useMemo } from "react";
import {
  usePlatformStatus, usePortfolio, useLivePositions, useLatestAllocation,
  useJournal, useRagLosses, useRagWins, usePerformanceHistory,
  usePerformanceSummary,
} from "@/hooks/use-trading";
import { cn, formatCurrency, formatPercentAbs, formatDate } from "@/lib/utils";
import { Card, CardHeader, CardTitle, CardContent, Badge, PnlText, PnlValue } from "@/components/ui";
import { ControlPanel } from "@/components/ControlPanel";
import { TradeWorkflowBar } from "@/components/TradeWorkflowBar";
import {
  Activity, ShieldAlert, History, TrendingDown, TrendingUp,
  LayoutList, WifiOff, AlertTriangle, Target, BarChart3,
} from "lucide-react";
import { motion } from "framer-motion";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";

// ── System Status Banner ───────────────────────────────────────────────────────

const EXPECTED_JOBS = 3;

function SystemStatusBanner() {
  const { data, isError } = usePlatformStatus();

  let sysStatus: "online" | "degraded" | "offline";
  let reason: string;

  if (isError || !data) {
    sysStatus = "offline";
    reason = "Cannot reach trading API — check that the server is running";
  } else {
    const jobCount = data.scheduler_jobs.length;
    const lastStatus = data.last_run.last_run_status;
    const errorCount = data.last_run.error_count;

    if (jobCount < EXPECTED_JOBS) {
      sysStatus = "degraded";
      reason = `Only ${jobCount}/${EXPECTED_JOBS} scheduler jobs registered`;
    } else if (lastStatus === "error") {
      sysStatus = "degraded";
      reason = `Last run failed (${errorCount} total error${errorCount !== 1 ? "s" : ""})`;
    } else {
      sysStatus = "online";
      reason = lastStatus === "never_run"
        ? "Scheduler running — no analysis run yet today"
        : "All systems operational";
    }
  }

  if (sysStatus === "online") {
    return (
      <div className="sticky top-14 z-30 w-full bg-green-500/8 border-b border-green-500/15 backdrop-blur-md">
        <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 h-8 flex items-center gap-2">
          <span className="relative flex h-1.5 w-1.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-500 opacity-75" />
            <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-green-500" />
          </span>
          <span className="text-xs text-green-400 font-medium">ONLINE</span>
          <span className="text-xs text-green-500/60">— {reason}</span>
        </div>
      </div>
    );
  }

  if (sysStatus === "degraded") {
    return (
      <div className="sticky top-14 z-30 w-full bg-amber-500/10 border-b border-amber-500/20 backdrop-blur-md">
        <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 h-8 flex items-center gap-2">
          <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
          <span className="text-xs text-amber-400 font-medium">DEGRADED</span>
          <span className="text-xs text-amber-500/70">— {reason}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="sticky top-14 z-30 w-full bg-red-500/10 border-b border-red-500/20 backdrop-blur-md">
      <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 h-8 flex items-center gap-2">
        <WifiOff className="h-3.5 w-3.5 text-red-400" />
        <span className="text-xs text-red-400 font-medium">OFFLINE</span>
        <span className="text-xs text-red-500/70">— {reason}</span>
      </div>
    </div>
  );
}

// ── Header ────────────────────────────────────────────────────────────────────

function Header() {
  const { data: status } = usePlatformStatus();

  return (
    <header className="sticky top-0 z-40 w-full bg-slate-950/90 backdrop-blur-md border-b border-white/5">
      <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-7 w-7 rounded-lg bg-primary/20 border border-primary/40 flex items-center justify-center">
            <Activity className="h-4 w-4 text-primary" />
          </div>
          <h1 className="text-lg font-bold tracking-tight text-white">Quant Terminal</h1>
        </div>

        <div className="flex items-center gap-5">
          <div className="flex flex-col items-end">
            <span className="text-[9px] uppercase text-muted-foreground font-semibold tracking-wider">Market</span>
            {status?.market.is_open ? (
              <span className="flex items-center gap-1 text-xs font-semibold text-green-400">
                <span className="relative flex h-1.5 w-1.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-green-400" />
                </span>
                OPEN
              </span>
            ) : (
              <span className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
                <span className="inline-flex rounded-full h-1.5 w-1.5 bg-slate-600" />
                CLOSED
              </span>
            )}
          </div>
          <div className="h-6 w-px bg-white/8" />
          <div className="flex flex-col items-end">
            <span className="text-[9px] uppercase text-muted-foreground font-semibold tracking-wider">Kill Switch</span>
            {status?.kill_switch.tripped ? (
              <span className="text-xs font-semibold text-red-400 flex items-center gap-1">
                <ShieldAlert className="h-3 w-3" /> TRIPPED
              </span>
            ) : (
              <span className="text-xs font-medium text-green-400 flex items-center gap-1">
                <ShieldAlert className="h-3 w-3 opacity-60" /> ARMED
              </span>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}

// ── Portfolio Metrics ──────────────────────────────────────────────────────────

function PortfolioMetrics() {
  const { data } = usePortfolio();
  if (!data) return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {[0, 1, 2].map(i => <div key={i} className="h-24 rounded-xl bg-card/40 animate-pulse border border-border" />)}
    </div>
  );

  const isProfit = data.account.equity >= 100000;

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5">
        <CardContent className="p-5">
          <div className="text-xs font-medium text-muted-foreground mb-1.5">Total Equity</div>
          <div className="text-3xl font-mono font-bold text-white tracking-tight">{formatCurrency(data.account.equity)}</div>
          <div className={cn("text-xs mt-1 font-medium", isProfit ? "text-green-400" : "text-red-400")}>
            {isProfit ? "↑" : "↓"} Paper Trading Account
          </div>
        </CardContent>
      </Card>
      <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5">
        <CardContent className="p-5">
          <div className="text-xs font-medium text-muted-foreground mb-1.5">Available Cash</div>
          <div className="text-3xl font-mono font-bold text-white tracking-tight">{formatCurrency(data.account.cash)}</div>
          <div className="text-xs text-muted-foreground mt-1">Uninvested capital</div>
        </CardContent>
      </Card>
      <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5">
        <CardContent className="p-5">
          <div className="text-xs font-medium text-muted-foreground mb-1.5">Buying Power</div>
          <div className="text-3xl font-mono font-bold text-white tracking-tight">{formatCurrency(data.account.buying_power)}</div>
          <div className="text-xs text-muted-foreground mt-1">With margin included</div>
        </CardContent>
      </Card>
    </div>
  );
}

// ── Live Positions ────────────────────────────────────────────────────────────

function LivePositionsSection() {
  const { data, isLoading } = useLivePositions();

  return (
    <Card className="border-white/5 overflow-hidden">
      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-4">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Target className="h-4 w-4 text-primary" />
          Live Open Positions
          {data && (
            <Badge variant={data.count > 0 ? "default" : "outline"} className="text-[10px] px-1.5 py-0 ml-1">
              {data.count}
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left min-w-[900px]">
          <thead className="text-[10px] uppercase bg-slate-950/60 text-muted-foreground">
            <tr>
              <th className="px-5 py-3 font-semibold">Asset</th>
              <th className="px-5 py-3 font-semibold text-right">Size (Qty)</th>
              <th className="px-5 py-3 font-semibold text-right">Notional</th>
              <th className="px-5 py-3 font-semibold text-right">Entry</th>
              <th className="px-5 py-3 font-semibold text-right">Current</th>
              <th className="px-5 py-3 font-semibold text-right">Unrealised P&L</th>
              <th className="px-5 py-3 font-semibold text-right">Stop Loss</th>
              <th className="px-5 py-3 font-semibold text-right">Take Profit</th>
              <th className="px-5 py-3 font-semibold text-center">Conv.</th>
              <th className="px-5 py-3 font-semibold max-w-[180px]">Thesis</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {isLoading && (
              <tr><td colSpan={10} className="px-5 py-6 text-center text-muted-foreground italic text-xs">Loading positions...</td></tr>
            )}
            {!isLoading && data?.positions.map((pos) => {
              const isUp = pos.unrealized_pl >= 0;
              return (
                <tr key={pos.symbol} className={cn("transition-colors hover:bg-white/[0.02]", isUp ? "border-l-2 border-l-green-500/20" : "border-l-2 border-l-red-500/20")}>
                  <td className="px-5 py-3.5">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-white text-sm">{pos.symbol}</span>
                      <Badge variant="outline" className="text-[9px] px-1 py-0 uppercase border-white/10">{pos.asset_class}</Badge>
                    </div>
                  </td>
                  <td className="px-5 py-3.5 text-right font-mono text-xs text-white">{pos.qty.toFixed(4)}</td>
                  <td className="px-5 py-3.5 text-right font-mono text-xs text-white">{formatCurrency(pos.market_value)}</td>
                  <td className="px-5 py-3.5 text-right font-mono text-xs text-muted-foreground">{formatCurrency(pos.avg_entry_price)}</td>
                  <td className="px-5 py-3.5 text-right font-mono text-xs text-white">{formatCurrency(pos.current_price)}</td>
                  <td className="px-5 py-3.5 text-right">
                    <div className="flex flex-col items-end">
                      <PnlValue value={pos.unrealized_pl} />
                      <span className="text-[10px] opacity-70"><PnlText value={pos.unrealized_plpc * 100} /></span>
                    </div>
                  </td>
                  <td className="px-5 py-3.5 text-right">
                    {pos.stop_loss_price != null ? (
                      <div className="flex flex-col items-end">
                        <span className="text-xs font-mono text-red-400">{formatCurrency(pos.stop_loss_price)}</span>
                        {pos.stop_loss_pct != null && <span className="text-[10px] text-red-500/60">{formatPercentAbs(pos.stop_loss_pct)}</span>}
                      </div>
                    ) : <span className="text-muted-foreground text-xs">—</span>}
                  </td>
                  <td className="px-5 py-3.5 text-right">
                    {pos.take_profit_price != null ? (
                      <div className="flex flex-col items-end">
                        <span className="text-xs font-mono text-green-400">{formatCurrency(pos.take_profit_price)}</span>
                        {pos.take_profit_pct != null && <span className="text-[10px] text-green-500/60">+{formatPercentAbs(pos.take_profit_pct)}</span>}
                      </div>
                    ) : <span className="text-muted-foreground text-xs">—</span>}
                  </td>
                  <td className="px-5 py-3.5 text-center">
                    {pos.conviction_score != null ? (
                      <span className={cn("text-xs font-mono font-semibold", pos.conviction_score >= 0.8 ? "text-green-400" : pos.conviction_score >= 0.75 ? "text-primary" : "text-amber-400")}>
                        {Math.round(pos.conviction_score * 100)}%
                      </span>
                    ) : <span className="text-muted-foreground text-xs">—</span>}
                  </td>
                  <td className="px-5 py-3.5 text-xs text-muted-foreground max-w-[180px] truncate" title={pos.original_thesis ?? ""}>
                    {pos.original_thesis ?? "—"}
                  </td>
                </tr>
              );
            })}
            {!isLoading && (!data || data.positions.length === 0) && (
              <tr>
                <td colSpan={10} className="px-5 py-8 text-center text-muted-foreground italic text-xs">
                  No open positions — system is in cash.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ── Performance Section ───────────────────────────────────────────────────────

interface ChartPayloadEntry {
  dataKey: string;
  name: string;
  value: number;
  color: string;
}

interface ChartTooltipProps {
  active?: boolean;
  payload?: ChartPayloadEntry[];
  label?: string;
}

const CustomTooltip = ({ active, payload, label }: ChartTooltipProps) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-slate-900 border border-white/10 rounded-lg px-3 py-2 text-xs shadow-xl">
      <p className="text-muted-foreground mb-1">{label}</p>
      {payload.map((p) => (
        <p key={p.dataKey} style={{ color: p.color }} className="font-mono">
          {p.name}:{" "}
          {p.dataKey === "equity"
            ? formatCurrency(p.value)
            : `${p.value >= 0 ? "+" : ""}${p.value.toFixed(2)}%`}
        </p>
      ))}
    </div>
  );
};

function PerformanceSection() {
  const { data: history } = usePerformanceHistory();
  const { data: summary } = usePerformanceSummary();

  const hasData = history && history.count > 0;

  const chartData = useMemo(() => {
    if (!history?.snapshots) return [];
    return history.snapshots.map((s) => ({
      date: s.date.slice(5),
      equity: s.equity,
      daily_pnl: parseFloat(s.daily_pnl_pct.toFixed(2)),
      win_rate: parseFloat((s.win_rate * 100).toFixed(1)),
      cumulative: parseFloat(s.cumulative_pnl_pct.toFixed(2)),
    }));
  }, [history]);

  return (
    <Card className="border-white/5 overflow-hidden">
      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-4 flex flex-row items-center justify-between">
        <CardTitle className="flex items-center gap-2 text-sm">
          <BarChart3 className="h-4 w-4 text-primary" /> System Performance
        </CardTitle>
        {summary?.latest_date && (
          <span className="text-[10px] text-muted-foreground terminal-text">
            Last snapshot: {summary.latest_date}
          </span>
        )}
      </CardHeader>
      <CardContent className="p-5">

        {/* Summary stat cards */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
          {[
            {
              label: "Total Return",
              value: summary?.total_return_pct != null
                ? `${summary.total_return_pct >= 0 ? "+" : ""}${summary.total_return_pct.toFixed(2)}%`
                : "—",
              color: summary?.total_return_pct != null
                ? summary.total_return_pct >= 0 ? "text-green-400" : "text-red-400"
                : "text-muted-foreground",
            },
            {
              label: "Win Rate",
              value: summary?.avg_win_rate != null
                ? `${(summary.avg_win_rate * 100).toFixed(1)}%`
                : "—",
              color: summary?.avg_win_rate != null
                ? summary.avg_win_rate >= 0.5 ? "text-green-400" : "text-amber-400"
                : "text-muted-foreground",
            },
            {
              label: "Best Day",
              value: summary?.best_day_pct != null ? `+${summary.best_day_pct.toFixed(2)}%` : "—",
              color: "text-green-400",
            },
            {
              label: "Worst Day",
              value: summary?.worst_day_pct != null ? `${summary.worst_day_pct.toFixed(2)}%` : "—",
              color: "text-red-400",
            },
            {
              label: "Total Trades",
              value: summary?.total_trades != null ? String(summary.total_trades) : "—",
              color: "text-white",
            },
            {
              label: "Avg Conviction",
              value: summary?.avg_conviction != null
                ? `${(summary.avg_conviction * 100).toFixed(1)}%`
                : "—",
              color: summary?.avg_conviction != null
                ? summary.avg_conviction >= 0.75 ? "text-green-400" : "text-amber-400"
                : "text-muted-foreground",
            },
          ].map((stat) => (
            <div key={stat.label} className="bg-slate-900/70 rounded-xl p-3 border border-white/5">
              <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1">{stat.label}</div>
              <div className={cn("text-xl font-mono font-bold", stat.color)}>{stat.value}</div>
            </div>
          ))}
        </div>

        {!hasData ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <BarChart3 className="h-10 w-10 text-muted-foreground/30 mb-3" />
            <p className="text-sm text-muted-foreground">Performance history appears after the first post-mortem runs</p>
            <p className="text-xs text-muted-foreground/60 mt-1">The system records a snapshot automatically each weekday at 4:10 PM ET after market close</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Equity Curve */}
            <div>
              <div className="text-xs font-medium text-muted-foreground mb-3 uppercase tracking-wide">Equity Curve</div>
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={chartData} margin={{ top: 4, right: 4, left: 4, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#64748b" }} tickLine={false} axisLine={false} />
                  <YAxis
                    tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
                    tick={{ fontSize: 10, fill: "#64748b" }}
                    tickLine={false}
                    axisLine={false}
                    width={45}
                  />
                  <Tooltip content={<CustomTooltip />} />
                  <ReferenceLine y={100000} stroke="rgba(255,255,255,0.1)" strokeDasharray="4 4" />
                  <Line
                    type="monotone"
                    dataKey="equity"
                    name="Equity"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4, fill: "#3b82f6" }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>

            {/* Daily Win Rate */}
            <div>
              <div className="text-xs font-medium text-muted-foreground mb-3 uppercase tracking-wide">Daily Win Rate (%)</div>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={chartData} margin={{ top: 4, right: 4, left: 4, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#64748b" }} tickLine={false} axisLine={false} />
                  <YAxis
                    domain={[0, 100]}
                    tickFormatter={(v) => `${v}%`}
                    tick={{ fontSize: 10, fill: "#64748b" }}
                    tickLine={false}
                    axisLine={false}
                    width={35}
                  />
                  <Tooltip content={<CustomTooltip />} />
                  <ReferenceLine y={50} stroke="rgba(255,255,255,0.15)" strokeDasharray="4 4" />
                  <Bar
                    dataKey="win_rate"
                    name="Win Rate"
                    fill="#22c55e"
                    opacity={0.75}
                    radius={[3, 3, 0, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Allocation Section ────────────────────────────────────────────────────────

function AllocationSection() {
  const { data } = useLatestAllocation();

  if (!data?.allocation) return (
    <Card className="border-dashed border-white/10 bg-transparent h-48 flex items-center justify-center">
      <p className="text-muted-foreground italic text-sm">No allocation plan yet — press Start Analysis.</p>
    </Card>
  );

  return (
    <Card className="border-white/5 overflow-hidden">
      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-4 flex flex-row items-center justify-between">
        <CardTitle className="flex items-center gap-2 text-sm">
          <LayoutList className="h-4 w-4 text-primary" /> Target Allocation (10 Slots)
        </CardTitle>
        <span className="text-[10px] text-muted-foreground terminal-text">Generated: {formatDate(data.run_utc)}</span>
      </CardHeader>
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left">
          <thead className="text-[10px] uppercase bg-slate-950/60 text-muted-foreground">
            <tr>
              <th className="px-5 py-3 font-semibold w-10 text-center">#</th>
              <th className="px-5 py-3 font-semibold">Ticker</th>
              <th className="px-5 py-3 font-semibold text-center">Conviction</th>
              <th className="px-5 py-3 font-semibold text-right">Kelly</th>
              <th className="px-5 py-3 font-semibold text-right">SL / TP</th>
              <th className="px-5 py-3 font-semibold">Thesis</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {data.allocation.map((slot) => {
              const isCash = slot.ticker === "SGOV";
              return (
                <tr key={slot.slot} className={cn("transition-colors hover:bg-white/[0.02]", isCash && "opacity-40 hover:opacity-80")}>
                  <td className="px-5 py-3 text-center text-muted-foreground terminal-text text-xs">{slot.slot}</td>
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-1.5">
                      <span className="font-bold text-white text-sm">{slot.ticker}</span>
                      <Badge variant={isCash ? "outline" : "default"} className="text-[9px] px-1 py-0 uppercase">{slot.asset_class}</Badge>
                    </div>
                  </td>
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-2 justify-center">
                      <span className="terminal-text text-[10px] w-7 text-right">{Math.round(slot.conviction_score * 100)}%</span>
                      <div className="w-14 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                        <div
                          className={cn("h-full rounded-full", slot.conviction_score >= 0.8 ? "bg-green-500" : slot.conviction_score >= 0.75 ? "bg-primary" : "bg-amber-500")}
                          style={{ width: `${slot.conviction_score * 100}%` }}
                        />
                      </div>
                    </div>
                  </td>
                  <td className="px-5 py-3 text-right terminal-text font-semibold text-white text-xs">{formatPercentAbs(slot.kelly_fraction)}</td>
                  <td className="px-5 py-3 text-right terminal-text text-[10px]">
                    <span className="text-red-400">{formatPercentAbs(slot.stop_loss_pct)}</span>
                    <span className="text-muted-foreground mx-1">/</span>
                    <span className="text-green-400">+{formatPercentAbs(slot.take_profit_pct)}</span>
                  </td>
                  <td className="px-5 py-3 text-[10px] text-muted-foreground truncate max-w-[220px] hover:whitespace-normal" title={slot.thesis}>
                    {slot.thesis}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ── Journal Section ───────────────────────────────────────────────────────────

function JournalSection() {
  const { data } = useJournal();
  if (!data) return null;

  return (
    <Card className="border-white/5 overflow-hidden">
      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-4 flex flex-row items-center justify-between">
        <CardTitle className="flex items-center gap-2 text-sm">
          <History className="h-4 w-4 text-primary" /> Trade Journal
        </CardTitle>
        <div className="flex gap-3 terminal-text text-[10px]">
          <span className="text-muted-foreground">Total: {data.summary.total}</span>
          <span className="text-green-400">Wins: {data.summary.wins ?? 0}</span>
          <span className="text-red-400">Losses: {data.summary.losses ?? 0}</span>
          <span>Avg: <PnlText value={data.summary.avg_pnl} /></span>
        </div>
      </CardHeader>
      <div className="overflow-x-auto max-h-[360px] overflow-y-auto">
        <table className="w-full text-sm text-left">
          <thead className="text-[10px] uppercase bg-slate-950/60 text-muted-foreground sticky top-0 backdrop-blur-md">
            <tr>
              <th className="px-5 py-2.5 font-semibold">Date</th>
              <th className="px-5 py-2.5 font-semibold">Asset</th>
              <th className="px-5 py-2.5 font-semibold text-center">Status</th>
              <th className="px-5 py-2.5 font-semibold text-right">P&L</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {data.trades.map((trade) => (
              <tr key={trade.trade_id} className="hover:bg-white/[0.02]">
                <td className="px-5 py-2.5 terminal-text text-muted-foreground text-[10px] whitespace-nowrap">{trade.date}</td>
                <td className="px-5 py-2.5">
                  <div className="flex items-center gap-1.5">
                    <span className="font-bold text-white text-sm">{trade.ticker}</span>
                    <span className="text-[9px] text-muted-foreground uppercase">{trade.asset_class}</span>
                  </div>
                </td>
                <td className="px-5 py-2.5 text-center">
                  <Badge variant={trade.status === 'Active' ? 'default' : trade.status === 'Closed_Win' ? 'success' : 'danger'} className="text-[9px]">
                    {trade.status.replace('Closed_', '')}
                  </Badge>
                </td>
                <td className="px-5 py-2.5 text-right">
                  {trade.status === 'Active'
                    ? <span className="text-muted-foreground text-xs">—</span>
                    : <PnlText value={trade.pnl_percentage} />}
                </td>
              </tr>
            ))}
            {data.trades.length === 0 && (
              <tr><td colSpan={4} className="px-5 py-8 text-center text-muted-foreground italic text-xs">No trades logged yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ── Learning Context (bidirectional RAG) ─────────────────────────────────────

function LearningContextSection() {
  const { data: lossData } = useRagLosses();
  const { data: winData } = useRagWins();

  const hasLosses = lossData && lossData.losses.length > 0;
  const hasWins = winData && winData.wins.length > 0;

  if (!hasLosses && !hasWins) return null;

  return (
    <div className="space-y-2">
      <div className="text-[10px] uppercase font-semibold text-muted-foreground tracking-wider px-1 flex items-center gap-2">
        <Activity className="h-3 w-3 text-primary" /> Learning Context
        <span className="font-normal normal-case text-muted-foreground/60">— injected into tomorrow's LLM prompt</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* Wins */}
        {hasWins && (
          <Card className="border-green-500/20 bg-green-500/5 overflow-hidden">
            <div className="px-4 py-2.5 bg-green-500/10 border-b border-green-500/15">
              <span className="text-[10px] uppercase font-semibold text-green-400 tracking-wider flex items-center gap-1.5">
                <TrendingUp className="h-3 w-3" /> What Worked ({winData.count})
              </span>
            </div>
            <div className="divide-y divide-green-500/8">
              {winData.wins.map((win) => (
                <div key={win.trade_id} className="p-3 hover:bg-green-500/5 transition-colors">
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono text-sm font-bold text-white">{win.ticker}</span>
                      <Badge className="text-[9px] py-0 px-1 bg-green-500/10 text-green-400 border-green-500/20 border">{win.asset_class}</Badge>
                    </div>
                    <PnlText value={win.pnl_percentage} />
                  </div>
                  <p className="text-[10px] leading-relaxed text-muted-foreground italic border-l-2 border-green-500/30 pl-2.5">
                    "{win.original_thesis}"
                  </p>
                </div>
              ))}
            </div>
          </Card>
        )}

        {/* Losses */}
        {hasLosses && (
          <Card className="border-red-500/20 bg-red-500/5 overflow-hidden">
            <div className="px-4 py-2.5 bg-red-500/10 border-b border-red-500/15">
              <span className="text-[10px] uppercase font-semibold text-red-400 tracking-wider flex items-center gap-1.5">
                <TrendingDown className="h-3 w-3" /> What Failed ({lossData.count})
              </span>
            </div>
            <div className="divide-y divide-red-500/8">
              {lossData.losses.map((loss) => (
                <div key={loss.trade_id} className="p-3 hover:bg-red-500/5 transition-colors">
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono text-sm font-bold text-white">{loss.ticker}</span>
                      <Badge className="text-[9px] py-0 px-1 bg-red-500/10 text-red-400 border-red-500/20 border">{loss.asset_class}</Badge>
                    </div>
                    <PnlText value={loss.pnl_percentage} />
                  </div>
                  <p className="text-[10px] leading-relaxed text-muted-foreground italic border-l-2 border-red-500/30 pl-2.5">
                    "{loss.original_thesis}"
                  </p>
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}

// ── Dashboard Root ────────────────────────────────────────────────────────────

export default function Dashboard() {
  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Header />
      <SystemStatusBanner />

      <main className="flex-1 max-w-[1600px] w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">

        {/* PRIMARY ACTION HERO */}
        <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
          <div className="relative rounded-2xl border border-primary/20 bg-gradient-to-br from-slate-900/80 to-slate-950/80 px-7 py-5 shadow-[0_0_60px_rgba(59,130,246,0.05)] overflow-hidden">
            <div className="absolute top-0 left-0 w-64 h-64 bg-primary/5 rounded-full blur-3xl -translate-x-1/2 -translate-y-1/2 pointer-events-none" />
            <TradeWorkflowBar />
          </div>
        </motion.div>

        {/* PORTFOLIO METRICS */}
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
          <PortfolioMetrics />
        </motion.div>

        {/* LIVE POSITIONS */}
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
          <LivePositionsSection />
        </motion.div>

        {/* PERFORMANCE */}
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
          <PerformanceSection />
        </motion.div>

        {/* ALLOCATION + JOURNAL | LEARNING + CONTROLS */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <motion.div className="col-span-1 lg:col-span-2 space-y-6" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25 }}>
            <AllocationSection />
            <JournalSection />
          </motion.div>

          <motion.div className="space-y-6" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
            <LearningContextSection />
            <ControlPanel />
          </motion.div>
        </div>

      </main>
    </div>
  );
}
