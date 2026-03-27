import { usePlatformStatus, usePortfolio, useLatestAllocation, useJournal, useRagLosses } from "@/hooks/use-trading";
import { cn, formatCurrency, formatPercent, formatPercentAbs, formatDate } from "@/lib/utils";
import { Card, CardHeader, CardTitle, CardContent, Badge, PnlText, PnlValue } from "@/components/ui";
import { ControlPanel } from "@/components/ControlPanel";
import { TradeWorkflowBar } from "@/components/TradeWorkflowBar";
import { Activity, Clock, ShieldAlert, BarChart3, Database, History, TrendingDown, LayoutList } from "lucide-react";
import { motion } from "framer-motion";

function Header() {
  const { data: status } = usePlatformStatus();
  
  return (
    <header className="sticky top-0 z-40 w-full glass-panel border-b-0 border-white/5 bg-slate-950/80">
      <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="h-8 w-8 rounded-lg bg-primary/20 border border-primary/50 flex items-center justify-center">
            <Activity className="h-5 w-5 text-primary" />
          </div>
          <h1 className="text-xl font-bold tracking-tight text-white">Quant Terminal</h1>
        </div>
        
        <div className="flex items-center gap-6">
          <div className="flex flex-col items-end">
            <span className="text-[10px] uppercase text-muted-foreground font-semibold tracking-wider">Market Status</span>
            {status?.market.is_open ? (
              <span className="flex items-center gap-1.5 text-sm font-medium text-success text-glow-success">
                <span className="relative flex h-2 w-2"><span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-success opacity-75"></span><span className="relative inline-flex rounded-full h-2 w-2 bg-success"></span></span>
                OPEN
              </span>
            ) : (
              <span className="flex items-center gap-1.5 text-sm font-medium text-muted-foreground">
                <span className="relative inline-flex rounded-full h-2 w-2 bg-muted-foreground"></span>
                CLOSED
              </span>
            )}
          </div>

          <div className="h-8 w-px bg-white/10" />

          <div className="flex flex-col items-end">
            <span className="text-[10px] uppercase text-muted-foreground font-semibold tracking-wider">Kill Switch</span>
            {status?.kill_switch.tripped ? (
              <span className="text-sm font-medium text-destructive text-glow-danger flex items-center gap-1">
                <ShieldAlert className="h-3.5 w-3.5" /> TRIPPED
              </span>
            ) : (
              <span className="text-sm font-medium text-success flex items-center gap-1">
                <ShieldAlert className="h-3.5 w-3.5 opacity-50" /> ARMED
              </span>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}

function PortfolioSection() {
  const { data } = usePortfolio();
  
  if (!data) return <div className="h-32 rounded-xl bg-card/50 animate-pulse border border-border" />;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5">
          <CardContent className="p-6">
            <div className="text-sm font-medium text-muted-foreground mb-1">Total Equity</div>
            <div className="text-4xl font-mono font-bold text-white tracking-tight">{formatCurrency(data.account.equity)}</div>
          </CardContent>
        </Card>
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5">
          <CardContent className="p-6">
            <div className="text-sm font-medium text-muted-foreground mb-1">Available Cash</div>
            <div className="text-4xl font-mono font-bold text-white tracking-tight">{formatCurrency(data.account.cash)}</div>
          </CardContent>
        </Card>
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5">
          <CardContent className="p-6">
            <div className="text-sm font-medium text-muted-foreground mb-1">Buying Power</div>
            <div className="text-4xl font-mono font-bold text-white tracking-tight">{formatCurrency(data.account.buying_power)}</div>
          </CardContent>
        </Card>
      </div>

      <Card className="border-white/5 overflow-hidden">
        <CardHeader className="bg-slate-900/50 border-b border-white/5 pb-4">
          <CardTitle className="flex items-center gap-2 text-base">
            <Database className="h-4 w-4 text-primary" /> Active Positions ({data.positions.length})
          </CardTitle>
        </CardHeader>
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="text-xs uppercase bg-slate-950/50 text-muted-foreground">
              <tr>
                <th className="px-6 py-4 font-semibold">Asset</th>
                <th className="px-6 py-4 font-semibold text-right">Qty</th>
                <th className="px-6 py-4 font-semibold text-right">Entry Price</th>
                <th className="px-6 py-4 font-semibold text-right">Current Price</th>
                <th className="px-6 py-4 font-semibold text-right">Market Value</th>
                <th className="px-6 py-4 font-semibold text-right">Unrealized P&L</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {data.positions.map((pos) => (
                <tr key={pos.symbol} className="hover:bg-white/[0.02] transition-colors">
                  <td className="px-6 py-4 font-bold text-white">{pos.symbol}</td>
                  <td className="px-6 py-4 text-right terminal-text">{pos.qty.toFixed(4)}</td>
                  <td className="px-6 py-4 text-right terminal-text">{formatCurrency(pos.avg_entry_price)}</td>
                  <td className="px-6 py-4 text-right terminal-text text-white">{formatCurrency(pos.current_price)}</td>
                  <td className="px-6 py-4 text-right terminal-text text-white">{formatCurrency(pos.market_value)}</td>
                  <td className="px-6 py-4 text-right">
                    <div className="flex flex-col items-end">
                      <PnlValue value={pos.unrealized_pl} />
                      <span className="text-xs opacity-75"><PnlText value={pos.unrealized_plpc * 100} /></span>
                    </div>
                  </td>
                </tr>
              ))}
              {data.positions.length === 0 && (
                <tr><td colSpan={6} className="px-6 py-8 text-center text-muted-foreground italic">No open positions. All in cash.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function AllocationSection() {
  const { data } = useLatestAllocation();
  
  if (!data?.allocation) return (
    <Card className="border-dashed border-white/10 bg-transparent h-64 flex items-center justify-center">
      <p className="text-muted-foreground italic">No allocation plan available. Run a cycle.</p>
    </Card>
  );

  return (
    <Card className="border-white/5 overflow-hidden">
      <CardHeader className="bg-slate-900/50 border-b border-white/5 pb-4 flex flex-row items-center justify-between">
        <CardTitle className="flex items-center gap-2 text-base">
          <LayoutList className="h-4 w-4 text-primary" /> Target Allocation (10 Slots)
        </CardTitle>
        <span className="text-xs text-muted-foreground terminal-text">Generated: {formatDate(data.run_utc)}</span>
      </CardHeader>
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left">
          <thead className="text-xs uppercase bg-slate-950/50 text-muted-foreground">
            <tr>
              <th className="px-6 py-4 font-semibold w-12 text-center">#</th>
              <th className="px-6 py-4 font-semibold">Ticker</th>
              <th className="px-6 py-4 font-semibold text-center">Conviction</th>
              <th className="px-6 py-4 font-semibold text-right">Kelly Target</th>
              <th className="px-6 py-4 font-semibold text-right">SL / TP</th>
              <th className="px-6 py-4 font-semibold max-w-xs">Thesis</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {data.allocation.map((slot) => {
              const isCash = slot.ticker === "SGOV";
              return (
                <tr key={slot.slot} className={cn("transition-colors hover:bg-white/[0.02]", isCash && "opacity-50 grayscale hover:opacity-100 hover:grayscale-0")}>
                  <td className="px-6 py-4 text-center text-muted-foreground terminal-text">{slot.slot}</td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-white">{slot.ticker}</span>
                      <Badge variant={isCash ? "outline" : "default"} className="text-[10px] px-1.5 py-0 uppercase">{slot.asset_class}</Badge>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2 justify-center">
                      <span className="terminal-text text-xs w-8 text-right">{Math.round(slot.conviction_score * 100)}%</span>
                      <div className="w-16 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                        <div className={cn("h-full", slot.conviction_score >= 0.75 ? "bg-primary" : "bg-muted-foreground")} style={{ width: `${slot.conviction_score * 100}%` }} />
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4 text-right terminal-text font-semibold text-white">{formatPercentAbs(slot.kelly_fraction)}</td>
                  <td className="px-6 py-4 text-right terminal-text text-xs">
                    <span className="text-destructive">{formatPercentAbs(slot.stop_loss_pct)}</span>
                    <span className="text-muted-foreground mx-1">/</span>
                    <span className="text-success">+{formatPercentAbs(slot.take_profit_pct)}</span>
                  </td>
                  <td className="px-6 py-4 text-xs text-muted-foreground truncate max-w-[250px] hover:whitespace-normal" title={slot.thesis}>
                    {slot.thesis}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function JournalSection() {
  const { data } = useJournal();
  
  if (!data) return null;

  return (
    <Card className="border-white/5 overflow-hidden">
      <CardHeader className="bg-slate-900/50 border-b border-white/5 pb-4 flex flex-row items-center justify-between">
        <CardTitle className="flex items-center gap-2 text-base">
          <History className="h-4 w-4 text-primary" /> Trade Journal
        </CardTitle>
        <div className="flex gap-4 terminal-text text-xs">
          <span className="text-muted-foreground">Total: {data.summary.total}</span>
          <span className="text-success">Wins: {data.summary.wins}</span>
          <span className="text-destructive">Losses: {data.summary.losses}</span>
          <span>Avg: <PnlText value={data.summary.avg_pnl} /></span>
        </div>
      </CardHeader>
      <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
        <table className="w-full text-sm text-left">
          <thead className="text-xs uppercase bg-slate-950/50 text-muted-foreground sticky top-0 backdrop-blur-md">
            <tr>
              <th className="px-6 py-3 font-semibold">Date</th>
              <th className="px-6 py-3 font-semibold">Asset</th>
              <th className="px-6 py-3 font-semibold text-center">Status</th>
              <th className="px-6 py-3 font-semibold text-right">P&L</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {data.trades.map((trade) => (
              <tr key={trade.trade_id} className="hover:bg-white/[0.02]">
                <td className="px-6 py-3 terminal-text text-muted-foreground text-xs whitespace-nowrap">{trade.date}</td>
                <td className="px-6 py-3">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-white">{trade.ticker}</span>
                    <span className="text-[10px] text-muted-foreground uppercase">{trade.asset_class}</span>
                  </div>
                </td>
                <td className="px-6 py-3 text-center">
                  <Badge variant={trade.status === 'Active' ? 'default' : trade.status === 'Closed_Win' ? 'success' : 'danger'}>
                    {trade.status.replace('Closed_', '')}
                  </Badge>
                </td>
                <td className="px-6 py-3 text-right">
                  {trade.status === 'Active' ? <span className="text-muted-foreground">—</span> : <PnlText value={trade.pnl_percentage} />}
                </td>
              </tr>
            ))}
            {data.trades.length === 0 && (
              <tr><td colSpan={4} className="px-6 py-8 text-center text-muted-foreground italic">No trades logged yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function RagSection() {
  const { data } = useRagLosses();
  
  if (!data || data.losses.length === 0) return null;

  return (
    <Card className="border-rose-500/20 bg-rose-500/5 overflow-hidden">
      <CardHeader className="bg-rose-500/10 border-b border-rose-500/20 pb-4">
        <CardTitle className="flex items-center gap-2 text-base text-rose-400">
          <TrendingDown className="h-4 w-4" /> RAG Learning Context
        </CardTitle>
        <p className="text-xs text-rose-500/70 mt-1">These failed theses will be injected into tomorrow's LLM prompt.</p>
      </CardHeader>
      <CardContent className="p-0">
        <div className="divide-y divide-rose-500/10">
          {data.losses.map((loss, i) => (
            <div key={loss.trade_id} className="p-4 hover:bg-rose-500/5 transition-colors">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm font-bold text-white">{loss.ticker}</span>
                  <Badge variant="danger" className="text-[10px] py-0 px-1.5 bg-rose-500/10 text-rose-400 border-rose-500/20">{loss.asset_class}</Badge>
                </div>
                <PnlText value={loss.pnl_percentage} />
              </div>
              <p className="text-xs leading-relaxed text-muted-foreground italic border-l-2 border-rose-500/30 pl-3 py-1">
                "{loss.original_thesis}"
              </p>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export default function Dashboard() {
  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Header />
      
      <main className="flex-1 max-w-[1600px] w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">

        {/* PRIMARY ACTION HERO */}
        <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
          <div className="relative rounded-2xl border border-primary/20 bg-gradient-to-br from-slate-900/80 to-slate-950/80 px-8 py-6 shadow-[0_0_60px_rgba(59,130,246,0.06)] overflow-hidden">
            <div className="absolute top-0 left-0 w-72 h-72 bg-primary/5 rounded-full blur-3xl -translate-x-1/2 -translate-y-1/2 pointer-events-none" />
            <div className="absolute bottom-0 right-0 w-48 h-48 bg-primary/3 rounded-full blur-2xl translate-x-1/4 translate-y-1/4 pointer-events-none" />
            <TradeWorkflowBar />
          </div>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
          <PortfolioSection />
        </motion.div>
        
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          <motion.div className="col-span-1 lg:col-span-2 space-y-8" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25 }}>
            <AllocationSection />
            <JournalSection />
          </motion.div>
          
          <motion.div className="space-y-8" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.35 }}>
            <RagSection />
            <ControlPanel />
          </motion.div>
        </div>

      </main>
    </div>
  );
}
