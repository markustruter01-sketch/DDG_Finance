import { cn } from "@/lib/utils";
import {
  useOptionsState, useOptionsPositions, useOptionsPending,
  useApproveOptionsTrade, useRejectOptionsTrade, useToggleOptionsBot,
  useOptionsManualScan, useCloseOptionsPosition,
  type OptionsPosition, type OptionsPendingTrade, type OptionsScanResult,
} from "@/hooks/use-trading";
import { Card, CardContent } from "@/components/ui";
import {
  Crosshair, Play, Pause, Search, AlertTriangle,
  ThumbsUp, ThumbsDown,
} from "lucide-react";

export function OptionsSection() {
  const { data: optState } = useOptionsState();
  const { data: optPositions } = useOptionsPositions();
  const { data: optPending } = useOptionsPending();
  const toggleBot = useToggleOptionsBot();
  const manualScan = useOptionsManualScan();
  const approveTrade = useApproveOptionsTrade();
  const rejectTrade = useRejectOptionsTrade();
  const closePosition = useCloseOptionsPosition();

  const paused = optState?.paused ?? false;
  const paperMode = optState?.paper_mode ?? true;
  const totalEquity = optState?.total_equity ?? 0;
  const fencedCapital = optState?.fenced_capital ?? 0;
  const deployed = optState?.deployed_capital ?? 0;
  const unrealizedPnl = optState?.unrealized_pnl ?? 0;
  const totalPnl = optState?.total_pnl ?? 0;
  const totalTrades = optState?.total_trades ?? 0;
  const totalWins = optState?.total_wins ?? 0;
  const winRate = totalTrades > 0 ? (totalWins / totalTrades * 100) : 0;
  const cycleCount = optState?.cycle_count ?? 0;
  const scanResults = optState?.last_scan_results ?? [];
  const lastScan = optState?.last_scan;
  const positions = optPositions?.positions ?? [];
  const pending = optPending?.pending ?? [];
  const deployedPct = fencedCapital > 0 ? (deployed / fencedCapital * 100) : 0;

  const formatCcy = (v: number) => v.toLocaleString("en-US", { style: "currency", currency: "USD" });
  const formatGreek = (v: number | null | undefined) => v != null ? v.toFixed(4) : "—";

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="h-px flex-1 bg-gradient-to-r from-transparent via-red-500/20 to-transparent" />
        <div className="flex items-center gap-2 px-3 py-1 rounded-full border border-red-500/20 bg-red-950/30 text-[10px] text-red-400/70 font-semibold uppercase tracking-widest">
          <Crosshair className="h-3 w-3" />
          <span>Apex Predator — Options Engine</span>
          <span className="text-[8px] font-mono px-1 py-0.5 rounded bg-red-500/15 text-red-400 border border-red-500/30">BOT #5</span>
          {paperMode && <span className="text-[8px] font-mono px-1 py-0.5 rounded bg-yellow-500/15 text-yellow-400 border border-yellow-500/30">PAPER</span>}
        </div>
        <div className="h-px flex-1 bg-gradient-to-r from-transparent via-red-500/20 to-transparent" />
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={() => toggleBot.mutate()}
          className={cn(
            "text-xs font-mono px-3 py-1.5 rounded-lg border transition-all",
            paused
              ? "border-green-500/30 bg-green-500/10 text-green-400 hover:bg-green-500/20"
              : "border-orange-500/30 bg-orange-500/10 text-orange-400 hover:bg-orange-500/20"
          )}
        >
          {paused ? <><Play className="h-3 w-3 inline mr-1" />Resume</> : <><Pause className="h-3 w-3 inline mr-1" />Pause</>}
        </button>
        <button
          onClick={() => manualScan.mutate()}
          disabled={manualScan.isPending}
          className="text-xs font-mono px-3 py-1.5 rounded-lg border border-red-500/30 bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-all disabled:opacity-50"
        >
          <Search className="h-3 w-3 inline mr-1" />
          {manualScan.isPending ? "Scanning..." : "Manual Scan"}
        </button>
        <div className="flex items-center gap-2 ml-auto text-[10px] font-mono text-muted-foreground/50">
          <span className={cn("px-1.5 py-0.5 rounded", paused ? "bg-orange-500/15 text-orange-400" : "bg-green-500/15 text-green-400")}>
            {paused ? "PAUSED" : "ARMED"}
          </span>
          <span>cycle #{cycleCount}</span>
          {lastScan && <span>last scan: {new Date(lastScan).toLocaleTimeString()}</span>}
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-red-500/20 transition-all">
          <CardContent className="p-3">
            <div className="text-[10px] font-medium text-muted-foreground mb-1">{paperMode ? "Paper Equity" : "Account Equity"}</div>
            <div className="text-sm font-mono font-bold text-white">{formatCcy(totalEquity)}</div>
            <div className="text-[9px] text-muted-foreground/50 mt-1">{paperMode ? "simulated $100k" : "live account"}</div>
          </CardContent>
        </Card>
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-red-500/20 transition-all">
          <CardContent className="p-3">
            <div className="text-[10px] font-medium text-muted-foreground mb-1">Fenced Capital</div>
            <div className="text-sm font-mono font-bold text-red-400">{formatCcy(fencedCapital)}</div>
            <div className="text-[9px] text-muted-foreground/50 mt-1">5% of {formatCcy(totalEquity)}</div>
          </CardContent>
        </Card>
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-red-500/15 transition-all">
          <CardContent className="p-3">
            <div className="text-[10px] font-medium text-muted-foreground mb-1">Deployed</div>
            <div className="text-sm font-mono font-bold text-white">{deployedPct.toFixed(0)}%</div>
            <div className="mt-1 h-1 rounded-full bg-white/5 overflow-hidden">
              <div className="h-full rounded-full bg-red-500/50 transition-all duration-700" style={{ width: `${Math.min(deployedPct, 100)}%` }} />
            </div>
            <div className="text-[9px] text-muted-foreground/50 mt-1">{formatCcy(deployed)}</div>
          </CardContent>
        </Card>
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-red-500/15 transition-all">
          <CardContent className="p-3">
            <div className="text-[10px] font-medium text-muted-foreground mb-1">Unrealized P&L</div>
            <div className={cn("text-sm font-mono font-bold", unrealizedPnl >= 0 ? "text-green-400" : "text-red-400")}>
              {unrealizedPnl >= 0 ? "+" : ""}{formatCcy(unrealizedPnl)}
            </div>
          </CardContent>
        </Card>
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-red-500/15 transition-all">
          <CardContent className="p-3">
            <div className="text-[10px] font-medium text-muted-foreground mb-1">Realized P&L</div>
            <div className={cn("text-sm font-mono font-bold", totalPnl >= 0 ? "text-green-400" : "text-red-400")}>
              {totalPnl >= 0 ? "+" : ""}{formatCcy(totalPnl)}
            </div>
            <div className="text-[9px] text-muted-foreground/50 mt-1">{totalTrades} trades</div>
          </CardContent>
        </Card>
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-red-500/15 transition-all">
          <CardContent className="p-3">
            <div className="text-[10px] font-medium text-muted-foreground mb-1">Win Rate</div>
            <div className="text-sm font-mono font-bold text-white">{totalTrades > 0 ? `${winRate.toFixed(0)}%` : "—"}</div>
            <div className="text-[9px] text-muted-foreground/50 mt-1">{totalWins}W · {totalTrades - totalWins}L</div>
          </CardContent>
        </Card>
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-red-500/15 transition-all">
          <CardContent className="p-3">
            <div className="text-[10px] font-medium text-muted-foreground mb-1">Strategy</div>
            <div className="text-sm font-mono font-bold text-red-400">Vol Squeeze</div>
            <div className="text-[9px] text-muted-foreground/50 mt-1">IVR &lt; 20 + BB</div>
          </CardContent>
        </Card>
      </div>

      {scanResults.length > 0 && (
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5">
          <CardContent className="p-4">
            <div className="text-xs font-semibold text-red-400/80 uppercase tracking-wider mb-3 flex items-center gap-2">
              <Search className="h-3.5 w-3.5" />
              Volatility Scanner
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
              {scanResults.map((r: OptionsScanResult, i: number) => (
                <div key={i} className={cn(
                  "rounded-lg border p-3 transition-all",
                  r.signal ? "border-red-500/40 bg-red-500/5" : "border-white/5 bg-white/[0.02]"
                )}>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-mono font-bold text-white">{r.symbol}</span>
                    {r.signal ? (
                      <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-red-500/20 text-red-400 border border-red-500/30 animate-pulse">SIGNAL</span>
                    ) : (
                      <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-white/5 text-muted-foreground/50">NO SIGNAL</span>
                    )}
                  </div>
                  <div className="space-y-1 text-[10px] font-mono">
                    <div className="flex justify-between"><span className="text-muted-foreground/60">IVR</span><span className={cn(r.ivr_pass ? "text-green-400" : "text-muted-foreground")}>{r.ivr?.toFixed(1) ?? "—"}</span></div>
                    <div className="flex justify-between"><span className="text-muted-foreground/60">BB Width</span><span className={cn(r.is_squeeze ? "text-green-400" : "text-muted-foreground")}>{r.bollinger_bandwidth?.toFixed(4) ?? "—"}</span></div>
                    <div className="flex justify-between"><span className="text-muted-foreground/60">Squeeze</span><span className={cn(r.is_squeeze ? "text-green-400" : "text-red-400/60")}>{r.is_squeeze ? "YES" : "NO"}</span></div>
                    <div className="flex justify-between"><span className="text-muted-foreground/60">IVR Pass</span><span className={cn(r.ivr_pass ? "text-green-400" : "text-red-400/60")}>{r.ivr_pass ? "YES" : "NO"}</span></div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {pending.length > 0 && (
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-red-500/20 relative overflow-hidden">
          <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-red-500/50 to-transparent" />
          <CardContent className="p-4">
            <div className="text-xs font-semibold text-red-400 uppercase tracking-wider mb-3 flex items-center gap-2">
              <AlertTriangle className="h-3.5 w-3.5 animate-pulse" />
              Pending Approval — {pending.length} trade{pending.length !== 1 ? "s" : ""}
            </div>
            <div className="space-y-3">
              {pending.map((trade: OptionsPendingTrade) => (
                <div key={trade.id} className="rounded-lg border border-red-500/20 bg-red-500/5 p-4">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-mono font-bold text-white">{trade.symbol}</span>
                      <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-red-500/15 text-red-400 border border-red-500/30 uppercase">Long Straddle</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <button onClick={() => approveTrade.mutate(trade.id)} disabled={approveTrade.isPending} className="flex items-center gap-1 text-xs font-mono px-3 py-1.5 rounded-lg bg-green-500/15 text-green-400 border border-green-500/30 hover:bg-green-500/25 transition-all">
                        <ThumbsUp className="h-3 w-3" /> Approve
                      </button>
                      <button onClick={() => rejectTrade.mutate(trade.id)} disabled={rejectTrade.isPending} className="flex items-center gap-1 text-xs font-mono px-3 py-1.5 rounded-lg bg-red-500/10 text-red-400/70 border border-red-500/20 hover:bg-red-500/20 transition-all">
                        <ThumbsDown className="h-3 w-3" /> Reject
                      </button>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 text-[10px] font-mono">
                    <div><div className="text-muted-foreground/50 mb-0.5">Call Strike</div><div className="text-green-400">${trade.call.strike.toFixed(2)}</div></div>
                    <div><div className="text-muted-foreground/50 mb-0.5">Put Strike</div><div className="text-red-400">${trade.put.strike.toFixed(2)}</div></div>
                    <div><div className="text-muted-foreground/50 mb-0.5">Expiry</div><div className="text-white">{trade.call.expiry} ({trade.call.dte}d)</div></div>
                    <div><div className="text-muted-foreground/50 mb-0.5">Total Premium</div><div className="text-amber-400 font-bold">{formatCcy(trade.total_cost)}</div></div>
                  </div>
                  <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 text-[10px] font-mono mt-2">
                    <div><div className="text-muted-foreground/50 mb-0.5">Contracts</div><div className="text-white">{trade.contracts}</div></div>
                    <div><div className="text-muted-foreground/50 mb-0.5">Kelly Frac</div><div className="text-white">{(trade.kelly_fraction * 100).toFixed(2)}%</div></div>
                    <div><div className="text-muted-foreground/50 mb-0.5">IVR</div><div className="text-cyan-400">{trade.ivr.toFixed(1)}</div></div>
                    <div><div className="text-muted-foreground/50 mb-0.5">BB Width</div><div className="text-cyan-400">{trade.bollinger_bandwidth.toFixed(4)}</div></div>
                  </div>
                  <div className="mt-3 pt-2 border-t border-white/5">
                    <div className="text-[10px] text-muted-foreground/40 font-mono">Options Greeks (Call / Put)</div>
                    <div className="grid grid-cols-4 gap-3 mt-1 text-[10px] font-mono">
                      <div><span className="text-muted-foreground/50">IV:</span> <span className="text-white">{formatGreek(trade.call.iv)} / {formatGreek(trade.put.iv)}</span></div>
                      <div><span className="text-muted-foreground/50">&Delta;:</span> <span className="text-white">{formatGreek(trade.call.delta)} / {formatGreek(trade.put.delta)}</span></div>
                      <div><span className="text-muted-foreground/50">&Gamma;:</span> <span className="text-white">{formatGreek(trade.call.gamma)} / {formatGreek(trade.put.gamma)}</span></div>
                      <div><span className="text-muted-foreground/50">&Theta;:</span> <span className="text-white">{formatGreek(trade.call.theta)} / {formatGreek(trade.put.theta)}</span></div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {positions.length > 0 ? (
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5">
          <CardContent className="p-4">
            <div className="text-xs font-semibold text-red-400/80 uppercase tracking-wider mb-3 flex items-center gap-2">
              <Crosshair className="h-3.5 w-3.5" />
              Open Straddle Positions — {positions.length}
            </div>
            <div className="space-y-3">
              {positions.map((pos: OptionsPosition) => (
                <div key={pos.id} className="rounded-lg border border-white/5 bg-white/[0.02] p-4">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-mono font-bold text-white">{pos.symbol}</span>
                      <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-red-500/10 text-red-400/70 uppercase">Straddle</span>
                      <span className={cn("text-[9px] font-mono px-1.5 py-0.5 rounded", pos.unrealized_pnl >= 0 ? "bg-green-500/15 text-green-400" : "bg-red-500/15 text-red-400")}>
                        {pos.unrealized_pnl >= 0 ? "+" : ""}{formatCcy(pos.unrealized_pnl)} ({pos.unrealized_pnl_pct?.toFixed(1) ?? "0.0"}%)
                      </span>
                    </div>
                    <button onClick={() => closePosition.mutate(pos.id)} disabled={closePosition.isPending} className="text-[10px] font-mono px-2 py-1 rounded border border-red-500/20 text-red-400/60 hover:bg-red-500/10 transition-all">Close</button>
                  </div>
                  <div className="grid grid-cols-2 lg:grid-cols-6 gap-3 text-[10px] font-mono">
                    <div><div className="text-muted-foreground/50 mb-0.5">Call Strike</div><div className="text-green-400">${pos.call.strike.toFixed(2)}</div></div>
                    <div><div className="text-muted-foreground/50 mb-0.5">Put Strike</div><div className="text-red-400">${pos.put.strike.toFixed(2)}</div></div>
                    <div><div className="text-muted-foreground/50 mb-0.5">Expiry</div><div className="text-white">{pos.call.expiry} ({pos.call.dte}d)</div></div>
                    <div><div className="text-muted-foreground/50 mb-0.5">Contracts</div><div className="text-white">{pos.contracts}</div></div>
                    <div><div className="text-muted-foreground/50 mb-0.5">Entry Cost</div><div className="text-amber-400">{formatCcy(pos.total_cost)}</div></div>
                    <div><div className="text-muted-foreground/50 mb-0.5">Current Value</div><div className="text-white">{formatCcy(pos.current_value)}</div></div>
                  </div>
                  <div className="mt-2 pt-2 border-t border-white/5">
                    <div className="grid grid-cols-4 gap-3 text-[10px] font-mono">
                      <div><span className="text-muted-foreground/50">&Delta;:</span> <span className="text-green-400/70">{formatGreek(pos.call.delta)}</span><span className="text-muted-foreground/30"> / </span><span className="text-red-400/70">{formatGreek(pos.put.delta)}</span></div>
                      <div><span className="text-muted-foreground/50">&Gamma;:</span> <span className="text-green-400/70">{formatGreek(pos.call.gamma)}</span><span className="text-muted-foreground/30"> / </span><span className="text-red-400/70">{formatGreek(pos.put.gamma)}</span></div>
                      <div><span className="text-muted-foreground/50">&Theta;:</span> <span className="text-green-400/70">{formatGreek(pos.call.theta)}</span><span className="text-muted-foreground/30"> / </span><span className="text-red-400/70">{formatGreek(pos.put.theta)}</span></div>
                      <div><span className="text-muted-foreground/50">IV:</span> <span className="text-green-400/70">{formatGreek(pos.call.iv)}</span><span className="text-muted-foreground/30"> / </span><span className="text-red-400/70">{formatGreek(pos.put.iv)}</span></div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5">
          <CardContent className="p-8 text-center">
            <Crosshair className="h-10 w-10 mx-auto text-red-400/20 mb-3" />
            <div className="text-sm font-medium text-muted-foreground/50">No Open Positions</div>
            <div className="text-[10px] text-muted-foreground/30 mt-1">The Apex Predator scans SPY, QQQ, NVDA, TSLA at 3:30 PM ET daily</div>
            <div className="text-[10px] text-muted-foreground/30 mt-0.5">Waiting for IVR &lt; 20 + Bollinger Squeeze signal</div>
          </CardContent>
        </Card>
      )}

      <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5">
        <CardContent className="p-4">
          <div className="text-xs font-semibold text-muted-foreground/60 uppercase tracking-wider mb-3">Engine Specs</div>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 text-[10px] font-mono text-muted-foreground/50">
            <div className="space-y-1"><div className="text-[9px] text-red-400/50 uppercase font-semibold">Strategy</div><div>Long Straddle (ATM Call + Put)</div><div>30-45 DTE contracts</div></div>
            <div className="space-y-1"><div className="text-[9px] text-red-400/50 uppercase font-semibold">Entry Signal</div><div>IVR &lt; 20 (cheap options)</div><div>BB Squeeze (6-month low)</div></div>
            <div className="space-y-1"><div className="text-[9px] text-red-400/50 uppercase font-semibold">Sizing</div><div>Half-Kelly Criterion</div><div>f* = [p(b+1)-1] / 2b</div></div>
            <div className="space-y-1"><div className="text-[9px] text-red-400/50 uppercase font-semibold">Capital</div><div>5% fence of total equity</div><div>100% LLM-free engine</div></div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
