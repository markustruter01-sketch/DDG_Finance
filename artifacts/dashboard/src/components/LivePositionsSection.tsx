import { useState } from "react";
import { cn, formatCurrency } from "@/lib/utils";
import { useLivePositions, usePlatformStatus, useForceRebalance, useCloseAndReallocate, useFleetEquity } from "@/hooks/use-trading";
import { useMarketCountdown, RollingPnl } from "@/lib/dashboard-shared";
import { AlpacaPositionsPanel, ThesisModal } from "@/components/PositionCards";
import { useToast } from "@/hooks/use-toast";
import { Card, CardHeader, CardTitle, Badge } from "@/components/ui";
import { Target, RefreshCw } from "lucide-react";
import { motion } from "framer-motion";

export function LivePositionsSection() {
  const { data, isLoading } = useLivePositions();
  const { data: platformStatus } = usePlatformStatus();
  const { mutate: rebalance, isPending: isRebalancing } = useForceRebalance();
  const { mutate: closeAndReallocate, isPending: isClosing, variables: closingVar } = useCloseAndReallocate();
  const { data: fleetEq } = useFleetEquity();
  const { toast } = useToast();
  const [thesisModal, setThesisModal] = useState<{ ticker: string; thesis: string | null } | null>(null);
  const [confirmRebalance, setConfirmRebalance] = useState(false);
  const [confirmClose, setConfirmClose] = useState<string | null>(null);
  const marketClosed = !platformStatus?.market.is_open;
  const countdown = useMarketCountdown(marketClosed ? platformStatus?.market.next_open : null);
  const positions = data?.positions ?? [];
  const totalPnl = fleetEq?.fleet_total?.pnl ?? null;
  const closingSymbol = isClosing ? String(closingVar ?? "") : null;

  const handleClose = (symbol: string) => {
    setConfirmClose(null);
    closeAndReallocate(symbol, {
      onSuccess: () => toast({ title: `${symbol} Closed`, description: "Capital freed for reallocation." }),
      onError: (err: any) => toast({ variant: "destructive", title: `Failed to close ${symbol}`, description: err?.response?.data?.detail ?? err.message }),
    });
  };

  return (
    <Card className="border-white/5 overflow-hidden">
      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-3 sm:py-4">
        <CardTitle className="flex flex-wrap items-center gap-2 text-sm">
          <Target className="h-4 w-4 text-primary" />
          <span>Live Open Positions</span>
          {positions.length > 0 && <Badge variant="default" className="text-[10px] px-1.5 py-0">{positions.length}</Badge>}
          {positions.length > 0 && <span className={cn("text-xs font-mono font-semibold", totalPnl == null ? "text-muted-foreground" : totalPnl >= 0 ? "text-green-400" : "text-red-400")}>{totalPnl != null && totalPnl >= 0 ? "+" : ""}{formatCurrency(totalPnl)}</span>}
          {countdown && <span className="ml-1 text-[10px] font-mono text-amber-400/80">Market opens in {countdown}</span>}
          <div className="ml-auto">
            {!confirmRebalance ? (
              <button onClick={() => setConfirmRebalance(true)} className="flex items-center gap-1.5 text-[10px] font-bold px-2.5 py-1.5 rounded-md border border-orange-500/20 bg-orange-500/5 text-orange-400/80">
                <RefreshCw className="h-3 w-3" /> Rebalance
              </button>
            ) : (
              <div className="flex items-center gap-2">
                <button onClick={() => { rebalance(); setConfirmRebalance(false); }} className="text-[10px] font-bold px-2.5 py-1.5 rounded-md bg-orange-500/20 text-orange-400">Confirm</button>
                <button onClick={() => setConfirmRebalance(false)} className="text-[10px] text-muted-foreground">Cancel</button>
              </div>
            )}
          </div>
        </CardTitle>
      </CardHeader>
      {isLoading ? <div className="py-6 text-center text-muted-foreground italic text-xs">Loading positions...</div> : (
        <AlpacaPositionsPanel positions={positions} onThesisClick={(ticker, thesis) => setThesisModal({ ticker, thesis })} onEject={handleClose} confirmClose={confirmClose} setConfirmClose={setConfirmClose} isClosing={isClosing} isRebalancing={isRebalancing} closingSymbol={closingSymbol} />
      )}
      {!isLoading && positions.length === 0 && (
        <div className="flex flex-col items-center gap-2 py-8">
          <motion.div animate={{ opacity: [0.3, 0.6, 0.3] }} transition={{ duration: 3, repeat: Infinity }}><Target className="h-8 w-8 text-muted-foreground/20" /></motion.div>
          <p className="text-muted-foreground/50 italic text-xs">No open positions — system is in cash</p>
        </div>
      )}
      {thesisModal && <ThesisModal ticker={thesisModal.ticker} thesis={thesisModal.thesis} onClose={() => setThesisModal(null)} />}
    </Card>
  );
}