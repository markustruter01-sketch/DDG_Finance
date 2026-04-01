import { cn } from "@/lib/utils";
import {
  useForexState, useForexPositions, useForexTrades, useForexVault,
  useToggleForexBot, useForexManualScan,
  type ForexVaultSweep,
} from "@/hooks/use-trading";
import { Card, CardContent } from "@/components/ui";
import {
  Navigation, Play, Pause, Search, AlertTriangle,
  Target, History, Vault,
} from "lucide-react";

export function ForexSection() {
  const { data: fxState } = useForexState();
  const { data: fxPositions } = useForexPositions();
  const { data: fxTrades } = useForexTrades();
  const { data: fxVault } = useForexVault();
  const toggleBot = useToggleForexBot();
  const manualScan = useForexManualScan();

  const paused = fxState?.paused ?? false;
  const paperMode = fxState?.paper_mode ?? true;
  const totalEquity = fxState?.total_equity ?? 100000;
  const totalPnl = fxState?.total_pnl ?? 0;
  const totalTrades = fxState?.total_trades ?? 0;
  const totalWins = fxState?.total_wins ?? 0;
  const winRate = totalTrades > 0 ? (totalWins / totalTrades * 100) : 0;
  const cycleCount = fxState?.cycle_count ?? 0;
  const usdBias = fxState?.usd_bias ?? "NEUTRAL";
  const newsBlackout = fxState?.news_blackout ?? false;
  const hwm = fxState?.hwm_usd ?? 100000;
  const vaultTotal = fxState?.vault_total_usd ?? 0;
  const scanResults = fxState?.last_scan_results ?? [];
  const lastScan = fxState?.last_scan;
  const positions = fxPositions?.positions ?? [];
  const trades = fxTrades?.trades ?? [];
  const closedTrades = trades.filter(t => t.status === "closed");
  const vaultSweeps = fxVault?.sweeps ?? [];
  const posCount = fxState?.position_count ?? positions.length;
  const status = fxState?.status ?? "loading";

  const formatCcy = (v: number) => v.toLocaleString("en-US", { style: "currency", currency: "USD" });
  const biasColor = usdBias === "USD_BULLISH" ? "text-green-400" : usdBias === "USD_BEARISH" ? "text-red-400" : "text-yellow-400";
  const biasLabel = usdBias === "USD_BULLISH" ? "USD BULL" : usdBias === "USD_BEARISH" ? "USD BEAR" : "NEUTRAL";

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="h-px flex-1 bg-gradient-to-r from-transparent via-teal-500/20 to-transparent" />
        <div className="flex items-center gap-2 px-3 py-1 rounded-full border border-teal-500/20 bg-teal-950/30 text-[10px] text-teal-400/70 font-semibold uppercase tracking-widest">
          <Navigation className="h-3 w-3" />
          <span>The Navigator — Forex Swing Engine</span>
          <span className="text-[8px] font-mono px-1 py-0.5 rounded bg-teal-500/15 text-teal-400 border border-teal-500/30">BOT #6</span>
          {paperMode && <span className="text-[8px] font-mono px-1 py-0.5 rounded bg-yellow-500/15 text-yellow-400 border border-yellow-500/30">PAPER</span>}
        </div>
        <div className="h-px flex-1 bg-gradient-to-r from-transparent via-teal-500/20 to-transparent" />
      </div>

      {newsBlackout && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg border border-yellow-500/30 bg-yellow-500/10 text-yellow-400 text-xs font-mono">
          <AlertTriangle className="h-3.5 w-3.5" />
          NEWS BLACKOUT ACTIVE — High-impact event within 4h window. No new trades.
        </div>
      )}

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
          className="text-xs font-mono px-3 py-1.5 rounded-lg border border-teal-500/30 bg-teal-500/10 text-teal-400 hover:bg-teal-500/20 transition-all disabled:opacity-50"
        >
          <Search className="h-3 w-3 inline mr-1" />
          {manualScan.isPending ? "Scanning..." : "Manual Scan"}
        </button>
        <div className="flex items-center gap-2 ml-auto text-[10px] font-mono text-muted-foreground/50">
          <span className={cn("px-1.5 py-0.5 rounded", paused ? "bg-orange-500/15 text-orange-400" : "bg-green-500/15 text-green-400")}>
            {paused ? "PAUSED" : status === "scanning" ? "SCANNING" : "ARMED"}
          </span>
          <span className={cn("px-1.5 py-0.5 rounded font-bold", biasColor, "bg-white/5")}>{biasLabel}</span>
          <span>cycle #{cycleCount}</span>
          {lastScan && <span>last: {new Date(lastScan).toLocaleTimeString()}</span>}
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-teal-500/20 transition-all">
          <CardContent className="p-3">
            <div className="text-[10px] font-medium text-muted-foreground mb-1">{paperMode ? "Paper Equity" : "Account Equity"}</div>
            <div className="text-sm font-mono font-bold text-white">{formatCcy(totalEquity)}</div>
            <div className="text-[9px] text-muted-foreground/50 mt-1">{paperMode ? "simulated $100k" : "live account"}</div>
          </CardContent>
        </Card>
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-teal-500/20 transition-all">
          <CardContent className="p-3">
            <div className="text-[10px] font-medium text-muted-foreground mb-1">USD Bias</div>
            <div className={cn("text-sm font-mono font-bold", biasColor)}>{biasLabel}</div>
            <div className="text-[9px] text-muted-foreground/50 mt-1">Groq Macro Compass</div>
          </CardContent>
        </Card>
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-teal-500/20 transition-all">
          <CardContent className="p-3">
            <div className="text-[10px] font-medium text-muted-foreground mb-1">Positions</div>
            <div className="text-sm font-mono font-bold text-white">{posCount} / 5</div>
            <div className="mt-1 h-1 rounded-full bg-white/5 overflow-hidden">
              <div className="h-full rounded-full bg-teal-500/50 transition-all duration-700" style={{ width: `${(posCount / 5) * 100}%` }} />
            </div>
          </CardContent>
        </Card>
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-teal-500/15 transition-all">
          <CardContent className="p-3">
            <div className="text-[10px] font-medium text-muted-foreground mb-1">Realized P&L</div>
            <div className={cn("text-sm font-mono font-bold", totalPnl >= 0 ? "text-green-400" : "text-red-400")}>
              {totalPnl >= 0 ? "+" : ""}{formatCcy(totalPnl)}
            </div>
            <div className="text-[9px] text-muted-foreground/50 mt-1">{totalTrades} trades</div>
          </CardContent>
        </Card>
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-teal-500/15 transition-all">
          <CardContent className="p-3">
            <div className="text-[10px] font-medium text-muted-foreground mb-1">Win Rate</div>
            <div className="text-sm font-mono font-bold text-white">{totalTrades > 0 ? `${winRate.toFixed(0)}%` : "—"}</div>
            <div className="text-[9px] text-muted-foreground/50 mt-1">{totalWins}W · {totalTrades - totalWins}L</div>
          </CardContent>
        </Card>
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-teal-500/15 transition-all">
          <CardContent className="p-3">
            <div className="text-[10px] font-medium text-muted-foreground mb-1">HWM</div>
            <div className="text-sm font-mono font-bold text-teal-400">{formatCcy(hwm)}</div>
            <div className="text-[9px] text-muted-foreground/50 mt-1">high water mark</div>
          </CardContent>
        </Card>
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-teal-500/15 transition-all">
          <CardContent className="p-3">
            <div className="text-[10px] font-medium text-muted-foreground mb-1">Vault</div>
            <div className="text-sm font-mono font-bold text-yellow-400">{formatCcy(vaultTotal)}</div>
            <div className="text-[9px] text-muted-foreground/50 mt-1">20% profit sweep</div>
          </CardContent>
        </Card>
      </div>

      {positions.length > 0 && (
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5">
          <CardContent className="p-4">
            <div className="text-xs font-semibold text-teal-400/80 uppercase tracking-wider mb-3 flex items-center gap-2">
              <Target className="h-3.5 w-3.5" />
              Open Positions
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-[11px] font-mono">
                <thead>
                  <tr className="text-muted-foreground/50 border-b border-white/5">
                    <th className="text-left py-1.5 px-2">Pair</th>
                    <th className="text-left py-1.5 px-2">Dir</th>
                    <th className="text-right py-1.5 px-2">Entry</th>
                    <th className="text-right py-1.5 px-2">Current</th>
                    <th className="text-right py-1.5 px-2">SL</th>
                    <th className="text-right py-1.5 px-2">TP</th>
                    <th className="text-right py-1.5 px-2">P&L (pips)</th>
                    <th className="text-right py-1.5 px-2">P&L ($)</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((pos, i) => (
                    <tr key={i} className="border-b border-white/3 hover:bg-white/2">
                      <td className="py-1.5 px-2 text-white font-bold">{pos.pair}</td>
                      <td className={cn("py-1.5 px-2 font-bold", pos.direction === "long" ? "text-green-400" : "text-red-400")}>{pos.direction.toUpperCase()}</td>
                      <td className="py-1.5 px-2 text-right text-muted-foreground">{pos.entry_price.toFixed(5)}</td>
                      <td className="py-1.5 px-2 text-right text-white">{pos.current_price.toFixed(5)}</td>
                      <td className="py-1.5 px-2 text-right text-red-400/70">{pos.sl_price.toFixed(5)}</td>
                      <td className="py-1.5 px-2 text-right text-green-400/70">{pos.tp_price.toFixed(5)}</td>
                      <td className={cn("py-1.5 px-2 text-right font-bold", pos.unrealized_pnl_pips >= 0 ? "text-green-400" : "text-red-400")}>
                        {pos.unrealized_pnl_pips >= 0 ? "+" : ""}{pos.unrealized_pnl_pips.toFixed(1)}
                      </td>
                      <td className={cn("py-1.5 px-2 text-right font-bold", pos.unrealized_pnl_usd >= 0 ? "text-green-400" : "text-red-400")}>
                        {pos.unrealized_pnl_usd >= 0 ? "+" : ""}${pos.unrealized_pnl_usd.toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {scanResults.length > 0 && (
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5">
          <CardContent className="p-4">
            <div className="text-xs font-semibold text-teal-400/80 uppercase tracking-wider mb-3 flex items-center gap-2">
              <Search className="h-3.5 w-3.5" />
              H4 Scanner Results
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-[11px] font-mono">
                <thead>
                  <tr className="text-muted-foreground/50 border-b border-white/5">
                    <th className="text-left py-1.5 px-2">Pair</th>
                    <th className="text-right py-1.5 px-2">Price</th>
                    <th className="text-right py-1.5 px-2">RSI</th>
                    <th className="text-right py-1.5 px-2">ATR</th>
                    <th className="text-left py-1.5 px-2">Bias Filter</th>
                    <th className="text-left py-1.5 px-2">Signal</th>
                  </tr>
                </thead>
                <tbody>
                  {scanResults.map((sr, i) => (
                    <tr key={i} className="border-b border-white/3 hover:bg-white/2">
                      <td className="py-1.5 px-2 text-white font-bold">{sr.pair}</td>
                      <td className="py-1.5 px-2 text-right text-muted-foreground">{sr.price?.toFixed(5) ?? "—"}</td>
                      <td className={cn("py-1.5 px-2 text-right",
                        sr.rsi != null && sr.rsi < 30 ? "text-green-400" :
                        sr.rsi != null && sr.rsi > 70 ? "text-red-400" : "text-muted-foreground"
                      )}>{sr.rsi?.toFixed(1) ?? "—"}</td>
                      <td className="py-1.5 px-2 text-right text-muted-foreground">{sr.atr?.toFixed(5) ?? "—"}</td>
                      <td className="py-1.5 px-2 text-teal-400/70">{sr.bias_filter ?? "—"}</td>
                      <td className={cn("py-1.5 px-2",
                        sr.signal?.includes("FILLED") ? "text-green-400 font-bold" :
                        sr.signal?.includes("LONG") || sr.signal?.includes("SHORT") ? "text-yellow-400" :
                        "text-muted-foreground/50"
                      )}>{sr.signal ?? sr.status ?? "no signal"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {closedTrades.length > 0 && (
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5">
          <CardContent className="p-4">
            <div className="text-xs font-semibold text-teal-400/80 uppercase tracking-wider mb-3 flex items-center gap-2">
              <History className="h-3.5 w-3.5" />
              Trade History ({closedTrades.length} closed)
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-[11px] font-mono">
                <thead>
                  <tr className="text-muted-foreground/50 border-b border-white/5">
                    <th className="text-left py-1.5 px-2">Pair</th>
                    <th className="text-left py-1.5 px-2">Dir</th>
                    <th className="text-right py-1.5 px-2">Entry</th>
                    <th className="text-right py-1.5 px-2">Exit</th>
                    <th className="text-right py-1.5 px-2">Pips</th>
                    <th className="text-right py-1.5 px-2">P&L</th>
                    <th className="text-left py-1.5 px-2">Closed</th>
                  </tr>
                </thead>
                <tbody>
                  {closedTrades.slice(0, 20).map((t, i) => (
                    <tr key={i} className="border-b border-white/3 hover:bg-white/2">
                      <td className="py-1.5 px-2 text-white font-bold">{t.pair}</td>
                      <td className={cn("py-1.5 px-2", t.direction === "long" ? "text-green-400" : "text-red-400")}>{t.direction.toUpperCase()}</td>
                      <td className="py-1.5 px-2 text-right text-muted-foreground">{t.entry_price.toFixed(5)}</td>
                      <td className="py-1.5 px-2 text-right text-muted-foreground">{t.exit_price?.toFixed(5) ?? "—"}</td>
                      <td className={cn("py-1.5 px-2 text-right font-bold", (t.pnl_pips ?? 0) >= 0 ? "text-green-400" : "text-red-400")}>
                        {(t.pnl_pips ?? 0) >= 0 ? "+" : ""}{(t.pnl_pips ?? 0).toFixed(1)}
                      </td>
                      <td className={cn("py-1.5 px-2 text-right font-bold", (t.pnl_usd ?? 0) >= 0 ? "text-green-400" : "text-red-400")}>
                        {(t.pnl_usd ?? 0) >= 0 ? "+" : ""}${(t.pnl_usd ?? 0).toFixed(2)}
                      </td>
                      <td className="py-1.5 px-2 text-muted-foreground/50">{t.exit_time ? new Date(t.exit_time).toLocaleDateString() : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {vaultSweeps.length > 0 && (
        <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5">
          <CardContent className="p-4">
            <div className="text-xs font-semibold text-yellow-400/80 uppercase tracking-wider mb-3 flex items-center gap-2">
              <Vault className="h-3.5 w-3.5" />
              Capital Vault — {formatCcy(vaultTotal)}
            </div>
            <div className="space-y-1.5">
              {vaultSweeps.slice(0, 10).map((s: ForexVaultSweep, i: number) => (
                <div key={i} className="flex items-center justify-between text-[11px] font-mono px-2 py-1 rounded bg-white/2">
                  <span className="text-muted-foreground">{s.sweep_date}</span>
                  <span className="text-green-400">+{formatCcy(s.amount)}</span>
                  <span className="text-yellow-400/70">{formatCcy(s.running_total)}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5">
        <CardContent className="p-4">
          <div className="text-xs font-semibold text-teal-400/80 uppercase tracking-wider mb-3">Strategy Reference</div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-[11px] font-mono text-muted-foreground">
            <div className="space-y-1"><div className="text-[9px] text-teal-400/50 uppercase font-semibold">Timeframe</div><div>H4 Swing Trading</div><div>5 Major FX Pairs</div></div>
            <div className="space-y-1"><div className="text-[9px] text-teal-400/50 uppercase font-semibold">Entry Signal</div><div>RSI &lt; 30 (oversold)</div><div>RSI &gt; 70 (overbought)</div></div>
            <div className="space-y-1"><div className="text-[9px] text-teal-400/50 uppercase font-semibold">Risk</div><div>SL = 1.5x ATR(14)</div><div>TP = 3.0x ATR (1:2 R:R)</div></div>
            <div className="space-y-1"><div className="text-[9px] text-teal-400/50 uppercase font-semibold">Capital</div><div>1.5% risk per trade</div><div>Groq USD bias filter</div></div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
