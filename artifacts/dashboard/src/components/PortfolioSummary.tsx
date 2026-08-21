import { cn, formatCurrency } from "@/lib/utils";
import { usePortfolio, useLivePositions, useVault, useFleetEquity, useBotRegistry } from "@/hooks/use-trading";
import { useExportReport } from "@/hooks/use-report";
import { AnimatedCurrency, RollingCurrency } from "@/lib/dashboard-shared";
import { getFleetBotCount } from "@/lib/fleet-capital";
import { useToast } from "@/hooks/use-toast";
import { Card, CardContent } from "@/components/ui";
import { TrendingUp, TrendingDown, Zap, Vault, ArrowUpRight, Coins, FileDown } from "lucide-react";

export function CombinedPortfolioSummary() {
  const { data: portfolio } = usePortfolio();
  const { data: vault } = useVault();
  const { data: positions } = useLivePositions();
  const { data: fleetEq } = useFleetEquity();
  const { data: registry } = useBotRegistry();
  const exportReport = useExportReport();
  const { toast } = useToast();
  const total = fleetEq?.fleet_total?.equity ?? 0;
  const pnl = fleetEq?.fleet_total?.pnl ?? 0;
  const equity = portfolio?.account.equity ?? total;
  const cash = portfolio?.account.cash ?? 0;
  const buying = portfolio?.account.buying_power ?? 0;
  const vaultSymbol = vault?.vault_symbol ?? "JEPQ";
  const vaultPos = positions?.positions?.find(p => p.symbol === vaultSymbol);
  const vaultValue = vaultPos?.market_value ?? vault?.total_vaulted_usd ?? 0;
  const vaultPnl = vaultPos?.unrealized_pl ?? 0;
  const winRate = fleetEq?.fleet_total?.win_rate;

  const handleExport = async () => {
    try {
      const result = await exportReport.mutateAsync();
      const blob = new Blob([result.report], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `quant-terminal-report-${Date.now()}.txt`; a.click();
      URL.revokeObjectURL(url);
      toast({ title: "Report downloaded" });
    } catch (err: any) {
      toast({ variant: "destructive", title: "Export failed", description: err?.message ?? "Could not generate report." });
    }
  };

  const cards = [
    { label: "Total Equity", value: formatCurrency(equity), sub: `${pnl >= 0 ? "+" : ""}${formatCurrency(pnl)}`, icon: pnl >= 0 ? TrendingUp : TrendingDown, color: pnl >= 0 ? "text-green-400" : "text-red-400" },
    { label: "Available Cash", value: formatCurrency(cash), sub: equity > 0 ? `${((cash / equity) * 100).toFixed(0)}% liquid` : "—", icon: ArrowUpRight, color: "text-blue-400" },
    { label: "Buying Power", value: formatCurrency(buying), sub: "With margin", icon: Zap, color: "text-purple-400" },
    { label: "Fleet Win Rate", value: winRate == null ? "—" : `${(winRate * 100).toFixed(1)}%`, sub: "Canonical /fleet/equity", icon: TrendingUp, color: "text-cyan-400" },
    { label: "Growth Vault", value: formatCurrency(vaultValue), sub: vault?.initialised ? vaultSymbol : "Awaiting first sweep", icon: Vault, color: "text-amber-400" },
    { label: "Vault P&L", value: `${vaultPnl >= 0 ? "+" : ""}${formatCurrency(vaultPnl)}`, sub: `Unrealised on ${vaultSymbol}`, icon: Coins, color: vaultPnl >= 0 ? "text-green-400" : "text-red-400" },
  ];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between px-1">
        <span className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Total Portfolio · {getFleetBotCount(registry, fleetEq)} active Alpaca ETF bots</span>
        <button onClick={handleExport} disabled={exportReport.isPending} className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] uppercase font-semibold bg-blue-950/50 border border-blue-800/40 text-blue-400 disabled:opacity-40">
          <FileDown className="h-3 w-3" /> Export Report
        </button>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
        {cards.map(({ label, value, sub, icon: Icon, color }) => (
          <Card key={label} className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5">
            <CardContent className="p-4">
              <div className="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-1.5"><Icon className={cn("h-3 w-3", color)} />{label}</div>
              <div className={cn("text-lg font-mono font-bold tracking-tight", color)}>{value}</div>
              <div className="text-[10px] text-muted-foreground mt-1.5">{sub}</div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}