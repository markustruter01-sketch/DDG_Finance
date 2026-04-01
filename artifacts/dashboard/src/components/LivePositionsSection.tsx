import { useState, useMemo } from "react";
import { cn, formatCurrency } from "@/lib/utils";
import {
  useLivePositions, useKrakenStatus, usePlatformStatus,
  useForceRebalance, useCloseAndReallocate,
  useOptionsPositions, useForexPositions,
} from "@/hooks/use-trading";
import { useMarketCountdown, RollingPnl } from "@/lib/dashboard-shared";
import { AlpacaPositionsPanel, KrakenPositionsPanel, ThesisModal } from "@/components/PositionCards";
import { useToast } from "@/hooks/use-toast";
import { useIsMobile } from "@/hooks/use-mobile";
import { Card, CardHeader, CardTitle, Badge } from "@/components/ui";
import { Target, RefreshCw, LogOut, Crosshair, Navigation } from "lucide-react";
import { motion } from "framer-motion";

function MobilePositionCard({ pos, onThesisClick, onEject, confirmClose, setConfirmClose, isClosing, isRebalancing, closingSymbol }: {
  pos: any;
  onThesisClick: (ticker: string, thesis: string | null) => void;
  onEject: (symbol: string) => void;
  confirmClose: string | null;
  setConfirmClose: (s: string | null) => void;
  isClosing: boolean;
  isRebalancing: boolean;
  closingSymbol: string | null;
}) {
  const isUp = pos.unrealized_pl >= 0;
  const colorMap: Record<string, string> = { green: "#22c55e", emerald: "#10b981", amber: "#f59e0b", orange: "#f97316", red: "#ef4444" };
  const healthColor = pos.health_score ? (colorMap[pos.health_score.color] || pos.health_score.color) : null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        "rounded-xl border p-3.5 space-y-2.5 transition-all duration-300",
        isUp
          ? "border-l-2 border-l-green-500/40 border-white/5 hover:bg-green-500/[0.03]"
          : "border-l-2 border-l-red-500/40 border-white/5 hover:bg-red-500/[0.03]"
      )}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-bold text-white text-sm">{pos.symbol}</span>
          <Badge variant="outline" className="text-[9px] px-1 py-0 uppercase border-white/10">{pos.asset_class}</Badge>
          {pos.conviction_score != null && (
            <span className={cn("text-[10px] font-mono", pos.conviction_score >= 0.8 ? "text-green-400" : pos.conviction_score >= 0.75 ? "text-primary" : "text-amber-400")}>
              {Math.round(pos.conviction_score * 100)}%
            </span>
          )}
        </div>
        {pos.health_score && healthColor && (
          <span className="text-[10px] font-mono font-bold" style={{ color: healthColor }}>
            {pos.health_score.score} {pos.health_score.label}
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[11px]">
        <div className="flex justify-between"><span className="text-muted-foreground">Qty</span><span className="font-mono text-white">{pos.qty.toFixed(4)}</span></div>
        <div className="flex justify-between"><span className="text-muted-foreground">Notional</span><span className="font-mono text-white">{formatCurrency(pos.market_value)}</span></div>
        <div className="flex justify-between"><span className="text-muted-foreground">Entry</span><span className="font-mono text-muted-foreground">{formatCurrency(pos.avg_entry_price)}</span></div>
        <div className="flex justify-between"><span className="text-muted-foreground">Current</span><span className="font-mono text-white">{formatCurrency(pos.current_price)}</span></div>
        <div className="flex justify-between items-center"><span className="text-muted-foreground">P&L</span><RollingPnl value={pos.unrealized_pl} pct={pos.unrealized_plpc} /></div>
      </div>
      <div className="flex justify-end" onClick={(e) => e.stopPropagation()}>
        {closingSymbol === pos.symbol ? (
          <div className="flex items-center gap-1.5 text-[10px] text-orange-400/70"><RefreshCw className="h-3 w-3 animate-spin" /><span>Closing…</span></div>
        ) : confirmClose === pos.symbol ? (
          <div className="flex items-center gap-1.5">
            <span className="text-[9px] text-orange-300/80">Close & re-enter?</span>
            <button onClick={() => onEject(pos.symbol)} className="text-[9px] font-bold px-3 py-1.5 rounded bg-orange-500/20 text-orange-400 border border-orange-500/30 min-h-[44px]">Yes</button>
            <button onClick={() => setConfirmClose(null)} className="text-[9px] font-bold px-2.5 py-1.5 rounded bg-slate-800 text-muted-foreground border border-white/10 min-h-[44px]">No</button>
          </div>
        ) : (
          <button
            onClick={() => setConfirmClose(pos.symbol)}
            disabled={isClosing || isRebalancing}
            className={cn(
              "flex items-center gap-1 text-[9px] font-semibold uppercase tracking-wide px-3 py-2 rounded-lg border transition-all min-h-[44px]",
              isClosing || isRebalancing
                ? "opacity-40 cursor-not-allowed border-white/10 text-muted-foreground"
                : "border-orange-500/20 bg-orange-500/5 text-orange-400/60 hover:bg-orange-500/15 hover:text-orange-400"
            )}
          >
            <LogOut className="h-2.5 w-2.5" /><span>Eject</span>
          </button>
        )}
      </div>
    </motion.div>
  );
}

export function LivePositionsSection() {
  const isMobile = useIsMobile();
  const { data, isLoading } = useLivePositions();
  const { data: krakenStatus } = useKrakenStatus();
  const { data: platformStatus } = usePlatformStatus();
  const { mutate: rebalance, isPending: isRebalancing } = useForceRebalance();
  const { mutate: closeAndReallocate, isPending: isClosing, variables: closingVar } = useCloseAndReallocate();
  const { data: optPositions } = useOptionsPositions();
  const { data: fxPositions } = useForexPositions();
  const { toast } = useToast();
  const [thesisModal, setThesisModal] = useState<{ ticker: string; thesis: string | null } | null>(null);
  const [confirmRebalance, setConfirmRebalance] = useState(false);
  const marketClosed = !platformStatus?.market.is_open;
  const countdown = useMarketCountdown(marketClosed ? platformStatus?.market.next_open : null);
  const [confirmClose, setConfirmClose] = useState<string | null>(null);

  const closingSymbol = isClosing ? (closingVar as string) : null;
  const krakenPositions = krakenStatus?.open_positions ?? [];
  const optionsPositionsList = optPositions?.positions ?? [];
  const forexPositionsList = fxPositions?.positions ?? [];

  const handleCloseAndReallocate = (symbol: string) => {
    setConfirmClose(null);
    closeAndReallocate(symbol, {
      onSuccess: () => toast({ title: `${symbol} Closed`, description: "Capital freed — fresh pipeline running to reallocate." }),
      onError: (err: any) => toast({ variant: "destructive", title: `Failed to close ${symbol}`, description: err?.response?.data?.detail ?? err.message }),
    });
  };

  const totalUnrealized = useMemo(() => {
    const alpacaPnl = data?.positions?.reduce((sum, p) => sum + p.unrealized_pl, 0) ?? 0;
    const krakenPnl = krakenPositions.reduce((sum, p) => sum + (p.unrealized_pnl_usd ?? 0), 0);
    const optionsPnl = optionsPositionsList.reduce((sum, p) => sum + (p.unrealized_pnl ?? 0), 0);
    const forexPnl = forexPositionsList.reduce((sum, p) => sum + (p.unrealized_pnl_usd ?? 0), 0);
    return alpacaPnl + krakenPnl + optionsPnl + forexPnl;
  }, [data, krakenPositions, optionsPositionsList, forexPositionsList]);

  const totalCount = (data?.count ?? 0) + krakenPositions.length + optionsPositionsList.length + forexPositionsList.length;

  return (
    <Card className="border-white/5 overflow-hidden">
      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-3 sm:py-4">
        <CardTitle className="flex flex-wrap items-center gap-2 fluid-heading">
          <Target className="h-4 w-4 text-primary" />
          <span className="hidden md:inline">Live Open Positions</span>
          <span className="md:hidden">Positions</span>
          {totalCount > 0 && (
            <Badge variant="default" className="text-[10px] px-1.5 py-0">{totalCount}</Badge>
          )}
          {totalCount > 0 && (
            <span className={cn("text-xs font-mono font-semibold", totalUnrealized >= 0 ? "text-green-400 text-glow-success" : "text-red-400 text-glow-danger")}>
              {totalUnrealized >= 0 ? "+" : ""}{formatCurrency(totalUnrealized)}
            </span>
          )}
          {countdown && (
            <span className="flex items-center gap-1 text-[10px] font-mono font-semibold text-amber-400/80 border border-amber-500/20 bg-amber-500/5 px-2 py-0.5 rounded-full ml-1">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400/60 animate-pulse" />
              <span className="hidden sm:inline">mkt open in </span>
              {countdown}
            </span>
          )}
          <div className="ml-auto flex items-center gap-2">
            {!confirmRebalance ? (
              <button
                onClick={() => setConfirmRebalance(true)}
                disabled={isRebalancing || !data || data.count === 0}
                className={cn(
                  "flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide px-2.5 sm:px-3 py-1.5 rounded-lg border transition-all duration-200 min-h-[44px]",
                  isRebalancing
                    ? "border-orange-500/30 bg-orange-500/10 text-orange-400 cursor-wait"
                    : "border-orange-500/20 bg-orange-500/5 text-orange-400/70 hover:bg-orange-500/15 hover:text-orange-400 hover:border-orange-500/40"
                )}
              >
                {isRebalancing ? (
                  <><RefreshCw className="h-3 w-3 animate-spin" /> <span className="hidden md:inline">Rebalancing...</span></>
                ) : (
                  <><RefreshCw className="h-3 w-3" /> <span className="hidden md:inline">Force</span> Rebalance</>
                )}
              </button>
            ) : (
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-orange-400/80 hidden md:inline">Close all sellable positions &amp; re-enter?</span>
                <button onClick={() => { rebalance(); setConfirmRebalance(false); }} className="text-[10px] font-bold px-2.5 py-1.5 rounded-md bg-orange-500/20 text-orange-400 border border-orange-500/30 hover:bg-orange-500/30 transition-colors min-h-[44px]">Confirm</button>
                <button onClick={() => setConfirmRebalance(false)} className="text-[10px] font-bold px-2 py-1.5 rounded-md bg-slate-800 text-muted-foreground border border-white/10 hover:bg-slate-700 transition-colors min-h-[44px]">Cancel</button>
              </div>
            )}
          </div>
        </CardTitle>
      </CardHeader>

      {isLoading && (
        <div className="py-6 text-center text-muted-foreground italic text-xs px-4">Loading positions...</div>
      )}

      {!isLoading && (
        <AlpacaPositionsPanel
          positions={data?.positions ?? []}
          onThesisClick={(t, th) => setThesisModal({ ticker: t, thesis: th })}
          onEject={handleCloseAndReallocate}
          confirmClose={confirmClose}
          setConfirmClose={setConfirmClose}
          isClosing={isClosing}
          isRebalancing={isRebalancing}
          closingSymbol={closingSymbol}
        />
      )}

      {!isLoading && (!data || data.positions.length === 0) && krakenPositions.length === 0 && optionsPositionsList.length === 0 && forexPositionsList.length === 0 && (
        <div className="flex flex-col items-center gap-2 py-8 px-4">
          <motion.div animate={{ opacity: [0.3, 0.6, 0.3] }} transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}>
            <Target className="h-8 w-8 text-muted-foreground/20" />
          </motion.div>
          <p className="text-muted-foreground/50 italic text-xs">No open positions — system is in cash</p>
          <p className="text-[9px] text-muted-foreground/30">Awaiting next analysis cycle</p>
        </div>
      )}

      <KrakenPositionsPanel
        positions={krakenPositions}
        signals={krakenStatus?.signals ?? []}
        isPaper={krakenStatus?.paper_trading}
      />

      {optionsPositionsList.length > 0 && (
        <div className="border-t border-white/[0.04] bg-red-950/[0.03]">
          <div className="px-4 py-2 flex items-center gap-2">
            <Crosshair className="h-3 w-3 text-red-400/60" />
            <span className="text-[9px] uppercase font-semibold tracking-wider text-red-400/60">🎯 Apex Predator</span>
            <Badge variant="outline" className="text-[8px] px-1 py-0 border-red-500/20 text-red-400/50">{optionsPositionsList.length}</Badge>
            <span className="text-[9px] text-muted-foreground/30 ml-1">straddle positions</span>
            <span className={cn("ml-auto text-[11px] font-mono font-semibold tabular-nums",
              optionsPositionsList.reduce((s, p) => s + (p.unrealized_pnl ?? 0), 0) >= 0 ? "text-green-400" : "text-red-400"
            )}>
              {optionsPositionsList.reduce((s, p) => s + (p.unrealized_pnl ?? 0), 0) >= 0 ? "+" : ""}
              {formatCurrency(optionsPositionsList.reduce((s, p) => s + (p.unrealized_pnl ?? 0), 0))}
            </span>
          </div>
          <div className="px-3 pb-3 space-y-1.5">
            {optionsPositionsList.map((pos) => (
              <div key={pos.id} className="rounded-lg border border-red-500/15 bg-red-950/[0.07] p-2.5 flex items-center gap-3">
                <span className="font-bold font-mono text-white text-[11px] w-12">{pos.symbol}</span>
                <span className="text-[8px] font-bold px-1.5 py-0.5 rounded-full border text-red-400 border-red-500/30 bg-red-500/10">STRADDLE</span>
                <span className="text-[9px] font-mono text-muted-foreground/50">{pos.contracts} ct</span>
                <span className={cn("font-mono font-semibold text-[10px] ml-auto tabular-nums", (pos.unrealized_pnl ?? 0) >= 0 ? "text-green-400" : "text-red-400")}>
                  {(pos.unrealized_pnl ?? 0) >= 0 ? "+" : ""}{formatCurrency(pos.unrealized_pnl ?? 0)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {forexPositionsList.length > 0 && (
        <div className="border-t border-white/[0.04] bg-teal-950/[0.03]">
          <div className="px-4 py-2 flex items-center gap-2">
            <Navigation className="h-3 w-3 text-teal-400/60" />
            <span className="text-[9px] uppercase font-semibold tracking-wider text-teal-400/60">🧭 Navigator</span>
            <Badge variant="outline" className="text-[8px] px-1 py-0 border-teal-500/20 text-teal-400/50">{forexPositionsList.length}</Badge>
            <span className="text-[9px] text-muted-foreground/30 ml-1">forex swings</span>
            <span className={cn("ml-auto text-[11px] font-mono font-semibold tabular-nums",
              forexPositionsList.reduce((s, p) => s + (p.unrealized_pnl_usd ?? 0), 0) >= 0 ? "text-green-400" : "text-red-400"
            )}>
              {forexPositionsList.reduce((s, p) => s + (p.unrealized_pnl_usd ?? 0), 0) >= 0 ? "+" : ""}
              {formatCurrency(forexPositionsList.reduce((s, p) => s + (p.unrealized_pnl_usd ?? 0), 0))}
            </span>
          </div>
          <div className="px-3 pb-3 space-y-1.5">
            {forexPositionsList.map((pos, i) => (
              <div key={i} className="rounded-lg border border-teal-500/15 bg-teal-950/[0.07] p-2.5 flex items-center gap-3">
                <span className="font-bold font-mono text-white text-[11px] w-16">{pos.pair}</span>
                <span className={cn("text-[8px] font-bold px-1.5 py-0.5 rounded-full border",
                  pos.direction === "long" ? "text-green-400 border-green-500/30 bg-green-500/10" : "text-red-400 border-red-500/30 bg-red-500/10"
                )}>{pos.direction.toUpperCase()}</span>
                <span className="text-[9px] font-mono text-muted-foreground/50">{pos.entry_price.toFixed(5)}</span>
                <span className={cn("font-mono font-semibold text-[10px] ml-auto tabular-nums", pos.unrealized_pnl_usd >= 0 ? "text-green-400" : "text-red-400")}>
                  {pos.unrealized_pnl_usd >= 0 ? "+" : ""}${pos.unrealized_pnl_usd.toFixed(2)}
                  <span className="text-[8px] opacity-60 ml-1">({pos.unrealized_pnl_pips >= 0 ? "+" : ""}{pos.unrealized_pnl_pips.toFixed(1)} pips)</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {thesisModal && (
        <ThesisModal
          ticker={thesisModal.ticker}
          thesis={thesisModal.thesis}
          onClose={() => setThesisModal(null)}
        />
      )}
    </Card>
  );
}
