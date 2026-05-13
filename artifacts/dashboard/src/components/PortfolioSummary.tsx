import { cn, formatCurrency } from "@/lib/utils";
import {
  usePortfolio, useLivePositions, useVault, useKrakenStatus, useKrakenFleetSummary,
  useExportReport, useForexState, useFleetEquity, useBotRegistry,
} from "@/hooks/use-trading";
import { AnimatedCurrency, RollingCurrency } from "@/lib/dashboard-shared";
import { getFleetBotCount } from "@/lib/fleet-capital";
import { useToast } from "@/hooks/use-toast";
import { Card, CardContent } from "@/components/ui";
import {
  TrendingUp, TrendingDown, Zap, Vault, ArrowUpRight, Coins,
  TrendingUp as GrowthIcon, RefreshCw, FileDown, Navigation, Zap as BoltIcon,
} from "lucide-react";
import { motion } from "framer-motion";
import { Trophy } from "lucide-react";

export function CombinedPortfolioSummary() {
  const { data: portfolio } = usePortfolio();
  const { data: vault }     = useVault();
  const { data: positions } = useLivePositions();
  const { data: kraken }    = useKrakenStatus();
  const { data: fleetSummary } = useKrakenFleetSummary();
  const { data: fxState }   = useForexState();
  const { data: fleetEq }   = useFleetEquity();
  const { data: registry }       = useBotRegistry();
  const exportReport        = useExportReport();
  const { toast }           = useToast();

  const handleExportReport = async () => {
    try {
      const result = await exportReport.mutateAsync();
      await navigator.clipboard.writeText(result.report);
      toast({
        title: "Report Copied to Clipboard",
        description: `${result.line_count.toLocaleString()} lines · ${Math.round(result.char_count / 1000)}k chars · Paste into Claude or Gemini for analysis.`,
      });
    } catch (err: any) {
      toast({ variant: "destructive", title: "Export Failed", description: err?.message ?? "Could not generate report." });
    }
  };

  const alpacaEquity        = fleetEq?.oracle?.equity ?? 0;
  const alpacaCash          = portfolio?.account.cash            ?? 0;
  const alpacaBuying        = portfolio?.account.buying_power    ?? 0;
  const alpacaInitialMargin = portfolio?.account.initial_margin  ?? 0;
  const alpacaStart         = 100_000;
  const alpacaPnl           = fleetEq?.oracle?.pnl ?? 0;
  const alpacaPnlPct        = (alpacaPnl / alpacaStart) * 100;
  const alpacaProfit        = alpacaPnl >= 0;

  const SHORT_MARGIN_CAP_PCT = 35;
  const directShortPositions = positions?.positions?.filter(
    p => String(p.side ?? "long").toLowerCase() === "short" &&
         ["SPY","QQQ","XLK","XLF","XLE","IWM"].includes(p.symbol)
  ) ?? [];
  const shortCount     = directShortPositions.length;
  const shortExposure  = directShortPositions.reduce((sum, p) => sum + Math.abs(Number(p.market_value ?? 0)), 0);
  const shortMarginUsed    = alpacaInitialMargin;
  const shortMarginPct     = alpacaEquity > 0 ? (shortMarginUsed / alpacaEquity) * 100 : 0;
  const shortMarginCapUsed = Math.min(shortMarginPct / SHORT_MARGIN_CAP_PCT * 100, 100);
  const shortPnl           = directShortPositions.reduce((sum, p) => sum + Number(p.unrealized_pl ?? 0), 0);

  const vaultSymbol  = vault?.vault_symbol    ?? "JEPQ";
  const totalVaulted = vault?.total_vaulted_usd ?? 0;
  const vaultPos     = positions?.positions?.find(p => p.symbol === vaultSymbol);
  const vaultValue   = vaultPos?.market_value ?? totalVaulted;
  const vaultPnl     = vaultPos?.unrealized_pl ?? 0;

  const krakenReady       = !!kraken && kraken.status !== "not_started";
  const krakenBotPaused   = kraken?.bot_paused ?? false;
  const krakenFleetEquity = [
    fleetEq?.davy_jones?.equity ?? 0,
    fleetEq?.blackbeard?.equity ?? 0,
    fleetEq?.calypso?.equity ?? 0,
    fleetEq?.poseidon?.equity ?? 0,
    fleetEq?.kraken_current?.equity ?? 0,
  ].reduce((a, b) => a + b, 0);
  const krakenDeployed    = kraken?.deployed_pct ?? 0;
  const krakenPaper       = kraken?.paper_trading ?? true;
  const krakenPnl         = [
    fleetEq?.davy_jones?.pnl ?? 0,
    fleetEq?.blackbeard?.pnl ?? 0,
    fleetEq?.calypso?.pnl ?? 0,
    fleetEq?.poseidon?.pnl ?? 0,
    fleetEq?.kraken_current?.pnl ?? 0,
  ].reduce((a, b) => a + b, 0);
  const krakenTrades      = fleetSummary?.total_trades ?? kraken?.paper_summary?.total_trades ?? 0;
  const krakenWins        = fleetSummary?.total_wins ?? kraken?.paper_summary?.win_count ?? 0;
  const krakenStart       = fleetSummary?.total_starting_usd ?? 600_000;
  const krakenWinRate     = krakenTrades > 0 ? (krakenWins / krakenTrades) * 100 : null;
  const krakenPnlPct      = krakenStart > 0 ? (krakenPnl / krakenStart) * 100 : 0;


  const forexEquity   = fleetEq?.navigator?.equity ?? 0;
  const forexPnl      = fleetEq?.navigator?.pnl ?? 0;
  const forexTrades   = fxState?.total_trades ?? 0;
  const forexWins     = fxState?.total_wins ?? 0;
  const forexPaper    = fxState?.paper_mode ?? true;
  const forexStart    = 100_000;
  const forexPnlPct   = (forexPnl / forexStart) * 100;
  const forexPosCount = fxState?.position_count ?? 0;

  const grandTotal = fleetEq?.fleet_total?.equity ?? 0;

  const grandPnl = fleetEq?.fleet_total?.pnl ?? 0;
  const grandProfit = grandPnl >= 0;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between px-1">
        <div className="flex items-center gap-2">
          <span className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Total Portfolio</span>
          <span className="text-[9px] font-mono text-muted-foreground/50 bg-white/5 px-1.5 py-0.5 rounded">
            {getFleetBotCount(registry, fleetEq)} bots · 3 capital pools
          </span>
        </div>
        <div className="flex items-center gap-2">
          {portfolio && (
            <span className={cn("text-sm font-mono font-bold tracking-tight", grandProfit ? "text-green-400" : "text-red-400")}>
              {formatCurrency(grandTotal)}
            </span>
          )}
          {portfolio && (
            <span className={cn("text-[10px] font-mono px-1.5 py-0.5 rounded", grandProfit ? "bg-green-500/10 text-green-400" : "bg-red-500/10 text-red-400")}>
              {grandPnl >= 0 ? "+" : ""}{formatCurrency(grandPnl)}
            </span>
          )}
          <button
            onClick={handleExportReport}
            disabled={exportReport.isPending}
            title="Export full diagnostic report — copy to clipboard for LLM analysis"
            className={cn(
              "flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-semibold tracking-wide uppercase transition-all duration-150",
              "bg-blue-950/50 border border-blue-800/40 text-blue-400",
              "hover:bg-blue-600/20 hover:border-blue-500/60 hover:text-blue-300",
              "disabled:opacity-40 disabled:cursor-not-allowed", "min-h-[32px]"
            )}
          >
            {exportReport.isPending ? <RefreshCw className="h-3 w-3 animate-spin" /> : <FileDown className="h-3 w-3" />}
            <span className="hidden sm:inline">{exportReport.isPending ? "Generating…" : "Export Report"}</span>
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[5fr_3fr] gap-4">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-[9px] uppercase tracking-widest text-blue-400/60 font-semibold">Alpaca · US Equities</span>
            <div className="h-px flex-1 bg-blue-500/10" />
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            <Card className={cn("col-span-2 sm:col-span-3 lg:col-span-1 bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 relative overflow-hidden transition-all duration-500", alpacaProfit ? "hover:border-green-500/30" : "hover:border-red-500/30")}>
              {alpacaProfit
                ? <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-green-500/50 to-transparent" />
                : <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-red-500/50 to-transparent" />}
              <CardContent className="p-4">
                <div className="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-1.5">
                  Total Equity
                  {Math.abs(alpacaPnlPct) > 1 && (
                    <motion.span animate={{ scale: [1, 1.2, 1] }} transition={{ duration: 2, repeat: Infinity }}
                      className={cn("text-[9px] font-mono px-1 py-0.5 rounded", alpacaProfit ? "bg-green-500/15 text-green-400" : "bg-red-500/15 text-red-400")}>
                      {alpacaPnl >= 0 ? "+" : ""}{alpacaPnlPct.toFixed(2)}%
                    </motion.span>
                  )}
                </div>
                {portfolio
                  ? <RollingCurrency value={alpacaEquity} className={cn("fluid-equity font-mono font-bold tracking-tight", alpacaProfit ? "text-green-400 text-glow-success-strong" : "text-red-400 text-glow-danger-strong")} />
                  : <div className="h-7 w-28 bg-white/5 rounded animate-pulse" />}
                <div className={cn("text-xs mt-1.5 font-medium flex items-center gap-1", alpacaProfit ? "text-green-400/70" : "text-red-400/70")}>
                  {alpacaProfit ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                  {portfolio ? (alpacaPnl >= 0 ? `+${formatCurrency(alpacaPnl)}` : formatCurrency(alpacaPnl)) : "—"}
                </div>
              </CardContent>
            </Card>
            <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-blue-500/20 transition-all duration-500">
              <CardContent className="p-4">
                <div className="text-xs font-medium text-muted-foreground mb-1.5">Available Cash</div>
                {portfolio ? <AnimatedCurrency value={alpacaCash} className="fluid-metric font-mono font-bold text-white tracking-tight" /> : <div className="h-6 w-20 bg-white/5 rounded animate-pulse" />}
                <div className="text-xs text-muted-foreground mt-1.5"><span className="text-[9px] font-mono text-blue-400/60">{portfolio ? `${((alpacaCash / alpacaEquity) * 100).toFixed(0)}% liquid` : "—"}</span></div>
              </CardContent>
            </Card>
            <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-purple-500/20 transition-all duration-500">
              <CardContent className="p-4">
                <div className="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-1">Buying Power <Zap className="h-3 w-3 text-purple-400/60" /></div>
                {portfolio ? <AnimatedCurrency value={alpacaBuying} className="fluid-metric font-mono font-bold text-white tracking-tight" /> : <div className="h-6 w-20 bg-white/5 rounded animate-pulse" />}
                <div className="text-xs text-muted-foreground mt-1.5">With margin</div>
              </CardContent>
            </Card>
            <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-amber-500/25 transition-all duration-500 relative overflow-hidden">
              <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-amber-500/40 to-transparent" />
              <CardContent className="p-4">
                <div className="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-1.5"><Vault className="h-3 w-3 text-amber-400/70" />Growth Vault<span className="text-[9px] font-mono text-amber-400/60 bg-amber-500/10 px-1 rounded">{vaultSymbol}</span></div>
                {vault?.initialised ? (<><div className={cn("fluid-metric font-mono font-bold tracking-tight", vaultValue > 0 ? "text-amber-400" : "text-amber-400/40")}>{vaultValue > 0 ? formatCurrency(vaultValue) : "$0.00"}</div><div className="text-[10px] text-muted-foreground mt-1.5 flex items-center gap-1"><ArrowUpRight className="h-3 w-3 text-amber-400/50" />{vault.total_sweeps} sweep{vault.total_sweeps !== 1 ? "s" : ""} · HWM ${(vault.hwm ?? 0).toLocaleString("en-US", { maximumFractionDigits: 0 })}</div></>) : (<><div className="fluid-metric font-mono font-bold text-amber-400/40 tracking-tight">$0.00</div><div className="text-[10px] text-muted-foreground/50 mt-1.5">Awaiting first profit sweep</div></>)}
              </CardContent>
            </Card>
            <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-green-500/20 transition-all duration-500 relative overflow-hidden">
              <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-green-500/30 to-transparent" />
              <CardContent className="p-4">
                <div className="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-1.5"><Coins className="h-3 w-3 text-green-400/70" />Total Yield</div>
                {vault?.initialised && vaultPos ? (<><div className={cn("fluid-metric font-mono font-bold tracking-tight", vaultPnl > 0 ? "text-green-400 text-glow-success" : vaultPnl < 0 ? "text-red-400" : "text-muted-foreground/60")}>{vaultPnl >= 0 ? "+" : ""}{formatCurrency(vaultPnl)}</div><div className="text-[10px] text-muted-foreground mt-1.5 flex items-center gap-1"><GrowthIcon className="h-3 w-3 text-green-400/50" />Unrealised on {vaultSymbol}</div></>) : (<><div className="fluid-metric font-mono font-bold text-muted-foreground/40 tracking-tight">$0.00</div><div className="text-[10px] text-muted-foreground/50 mt-1.5">{vault?.initialised ? `No ${vaultSymbol} position yet` : "Awaiting first sweep"}</div></>)}
              </CardContent>
            </Card>
            <Card className={cn("bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 transition-all duration-500 relative overflow-hidden", shortCount > 0 ? "border-purple-500/30 hover:border-purple-500/50" : "hover:border-purple-500/10")}>
              {shortCount > 0 && <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-purple-500/50 to-transparent" />}
              <CardContent className="p-4">
                <div className="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-1.5"><TrendingDown className="h-3 w-3 text-purple-400/70" />Direct Shorts{shortCount > 0 && <span className="text-[9px] font-mono font-bold px-1 py-0.5 rounded bg-purple-500/15 text-purple-400 border border-purple-500/30">{shortCount}</span>}</div>
                {shortCount > 0 ? (<><div className={cn("fluid-metric font-mono font-bold tracking-tight", shortPnl > 0 ? "text-green-400" : shortPnl < 0 ? "text-red-400" : "text-purple-400")}>{shortPnl >= 0 ? "+" : ""}{formatCurrency(shortPnl)}</div><div className="text-[10px] text-muted-foreground mt-1.5 space-y-0.5"><div className="flex items-center gap-1 font-mono"><span className="text-purple-400/70">Margin: {formatCurrency(shortMarginUsed)} ({shortMarginPct.toFixed(1)}% of equity)</span></div><div className="flex items-center gap-1"><div className="flex-1 h-1 bg-white/5 rounded-full overflow-hidden max-w-[60px]"><div className={cn("h-full rounded-full transition-all duration-500", shortMarginCapUsed >= 90 ? "bg-red-400" : shortMarginCapUsed >= 70 ? "bg-amber-400" : "bg-purple-400")} style={{ width: `${shortMarginCapUsed}%` }} /></div><span className={cn("text-[9px] font-mono tabular-nums", shortMarginCapUsed >= 90 ? "text-red-400" : shortMarginCapUsed >= 70 ? "text-amber-400" : "text-purple-400/60")}>{shortMarginCapUsed.toFixed(0)}% of {SHORT_MARGIN_CAP_PCT}% cap</span></div></div></>) : (<><div className="fluid-metric font-mono font-bold text-purple-400/20 tracking-tight">—</div><div className="text-[10px] text-muted-foreground/40 mt-1.5">Scanner inactive</div></>)}
              </CardContent>
            </Card>
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-[9px] uppercase tracking-widest text-cyan-400/60 font-semibold">⚓ Kraken · Crypto Fleet ({fleetSummary?.bot_count ?? 3} bots)</span>
            {krakenPaper && <span className="text-[9px] font-mono font-bold px-1.5 py-0.5 rounded bg-yellow-500/15 text-yellow-400 border border-yellow-500/20 uppercase tracking-wide">Paper</span>}
            <div className="h-px flex-1 bg-cyan-500/10" />
            {krakenBotPaused && <span className="text-[9px] font-mono font-bold px-1.5 py-0.5 rounded bg-orange-500/15 text-orange-400 border border-orange-500/20 uppercase tracking-wide">Paused</span>}
            <span className={cn("text-[9px] font-mono", krakenReady && !krakenBotPaused ? "text-cyan-400/50" : "text-muted-foreground/30")}>{krakenReady ? `cycle #${kraken?.cycle_count ?? 0}` : "not running"}</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-cyan-500/20 transition-all duration-500 relative overflow-hidden">
              <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-cyan-500/30 to-transparent" />
              <CardContent className="p-3 sm:p-4">
                <div className="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-1.5">{krakenPaper ? "Paper Equity" : "Live Equity"}</div>
                {(krakenReady || fleetSummary) ? (<><AnimatedCurrency value={krakenFleetEquity} className={cn("fluid-metric font-mono font-bold tracking-tight", krakenPnl >= 0 ? "text-cyan-400" : "text-red-400")} /><div className={cn("text-xs mt-1.5 flex items-center gap-1 font-medium", krakenPnl >= 0 ? "text-cyan-400/70" : "text-red-400/70")}>{krakenPnl >= 0 ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}{krakenPnl >= 0 ? "+" : ""}{formatCurrency(krakenPnl)}{krakenPnlPct !== 0 && <span className={cn("text-[9px] font-mono px-1 py-0.5 rounded", krakenPnl >= 0 ? "bg-cyan-500/10 text-cyan-400" : "bg-red-500/10 text-red-400")}>{krakenPnlPct >= 0 ? "+" : ""}{krakenPnlPct.toFixed(2)}%</span>}</div></>) : (<><div className="fluid-metric font-mono font-bold text-muted-foreground/30 tracking-tight">—</div><div className="text-[10px] text-muted-foreground/40 mt-1.5">Start bot to track</div></>)}
              </CardContent>
            </Card>
            <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-cyan-500/15 transition-all duration-500">
              <CardContent className="p-3 sm:p-4">
                <div className="text-xs font-medium text-muted-foreground mb-1.5">Deployed</div>
                {krakenReady ? (<><div className="fluid-metric font-mono font-bold text-white tracking-tight">{krakenDeployed.toFixed(0)}<span className="text-xs text-muted-foreground font-normal">%</span></div><div className="mt-2 h-1 rounded-full bg-white/5 overflow-hidden"><div className="h-full rounded-full bg-cyan-500/50 transition-all duration-700" style={{ width: `${Math.min(krakenDeployed, 100)}%` }} /></div><div className="text-[9px] text-muted-foreground/50 mt-1">{kraken?.position_count ?? 0}/{kraken?.max_positions ?? 3} positions</div></>) : (<><div className="fluid-metric font-mono font-bold text-muted-foreground/30">—</div><div className="mt-2 h-1 rounded-full bg-white/5" /><div className="text-[9px] text-muted-foreground/30 mt-1">0/3 positions</div></>)}
              </CardContent>
            </Card>
            <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-cyan-500/15 transition-all duration-500">
              <CardContent className="p-3 sm:p-4">
                <div className="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-1">Win Rate<Trophy className="h-3 w-3 text-yellow-400/50" /></div>
                {(krakenReady || fleetSummary) && krakenWinRate !== null ? (<><div className="fluid-metric font-mono font-bold text-white tracking-tight">{krakenWinRate.toFixed(0)}<span className="text-xs text-muted-foreground font-normal">%</span></div><div className="text-[10px] text-muted-foreground mt-1.5">{krakenWins}W · {krakenTrades - krakenWins}L · {krakenTrades} total</div></>) : (<><div className="fluid-metric font-mono font-bold text-muted-foreground/30">—</div><div className="text-[10px] text-muted-foreground/40 mt-1.5">No trades yet</div></>)}
              </CardContent>
            </Card>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">

        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Navigation className="h-3 w-3 text-teal-400/60" />
            <span className="text-[9px] uppercase tracking-widest text-teal-400/60 font-semibold">Navigator · Forex</span>
            {forexPaper && <span className="text-[9px] font-mono font-bold px-1.5 py-0.5 rounded bg-yellow-500/15 text-yellow-400 border border-yellow-500/20 uppercase tracking-wide">Paper</span>}
            <div className="h-px flex-1 bg-teal-500/10" />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-teal-500/20 transition-all duration-500 relative overflow-hidden">
              <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-teal-500/30 to-transparent" />
              <CardContent className="p-3">
                <div className="text-xs font-medium text-muted-foreground mb-1.5">Equity</div>
                <AnimatedCurrency value={forexEquity} className={cn("fluid-metric font-mono font-bold tracking-tight", forexPnl >= 0 ? "text-teal-400" : "text-teal-400/60")} />
                <div className={cn("text-xs mt-1.5 flex items-center gap-1 font-medium", forexPnl >= 0 ? "text-green-400/70" : "text-red-400/70")}>
                  {forexPnl >= 0 ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                  {forexPnl >= 0 ? "+" : ""}{formatCurrency(forexPnl)}
                  {forexPnlPct !== 0 && <span className={cn("text-[9px] font-mono px-1 py-0.5 rounded", forexPnl >= 0 ? "bg-green-500/10 text-green-400" : "bg-red-500/10 text-red-400")}>{forexPnlPct >= 0 ? "+" : ""}{forexPnlPct.toFixed(2)}%</span>}
                </div>
              </CardContent>
            </Card>
            <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-teal-500/15 transition-all duration-500">
              <CardContent className="p-3">
                <div className="text-xs font-medium text-muted-foreground mb-1.5">Positions</div>
                <div className="fluid-metric font-mono font-bold text-white tracking-tight">{forexPosCount} / 10</div>
                <div className="text-[10px] text-muted-foreground/50 mt-1.5">{forexTrades} trades</div>
              </CardContent>
            </Card>
            <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-teal-500/15 transition-all duration-500">
              <CardContent className="p-3">
                <div className="text-xs font-medium text-muted-foreground mb-1.5">Win Rate</div>
                <div className="fluid-metric font-mono font-bold text-white tracking-tight">{forexTrades > 0 ? `${(forexWins / forexTrades * 100).toFixed(0)}%` : "—"}</div>
                <div className="text-[10px] text-muted-foreground/50 mt-1.5">{forexWins}W · {forexTrades - forexWins}L</div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}
