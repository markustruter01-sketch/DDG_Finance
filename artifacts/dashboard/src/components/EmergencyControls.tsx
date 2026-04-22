import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { AlertTriangle, RefreshCw, X, Zap, ShieldOff, RotateCcw } from "lucide-react";
import { useLiquidateAll, useSystemRestart, useForceRebalance } from "@/hooks/use-trading";
import { useFleetHaltStatus, useFleetHalt, useFleetResume } from "@/hooks/use-trading";
import { useToast } from "@/hooks/use-toast";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";

// ── Confirmation Modal ────────────────────────────────────────────────────────

interface ConfirmModalProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  confirmClass: string;
  requiresTyped?: string;
  onConfirm: () => void;
  onCancel: () => void;
  isLoading?: boolean;
}

function ConfirmModal({
  open, title, description, confirmLabel, confirmClass,
  requiresTyped, onConfirm, onCancel, isLoading,
}: ConfirmModalProps) {
  const [typed, setTyped] = useState("");
  const isMobile = useIsMobile();
  const canConfirm = requiresTyped ? typed.trim().toUpperCase() === requiresTyped.toUpperCase() : true;

  if (!open) return null;

  return (
    <AnimatePresence>
      <div className={cn("fixed inset-0 z-50", isMobile ? "flex items-end" : "flex items-center justify-center")}>
        {/* Backdrop */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="absolute inset-0 bg-black/80 backdrop-blur-sm"
          onClick={onCancel}
        />
        {/* Dialog */}
        <motion.div
          initial={isMobile ? { opacity: 0, y: 100 } : { opacity: 0, scale: 0.9, y: 8 }}
          animate={isMobile ? { opacity: 1, y: 0 } : { opacity: 1, scale: 1, y: 0 }}
          exit={isMobile ? { opacity: 0, y: 100 } : { opacity: 0, scale: 0.9, y: 8 }}
          transition={{ duration: 0.18 }}
          className={cn(
            "relative z-10 w-full bg-zinc-900 border border-zinc-700 shadow-2xl overflow-hidden",
            isMobile ? "rounded-t-2xl h-[100dvh] pb-[env(safe-area-inset-bottom)] overflow-y-auto" : "max-w-md mx-4 rounded-xl"
          )}
        >
          {/* Header stripe */}
          <div className={cn(
            "h-1 w-full",
            confirmClass.includes("red") ? "bg-red-600" : "bg-amber-500"
          )} />

          <div className="p-6">
            <div className="flex items-start gap-3 mb-4">
              <div className={cn(
                "p-2 rounded-lg flex-shrink-0",
                confirmClass.includes("red") ? "bg-red-500/10" : "bg-amber-500/10"
              )}>
                <AlertTriangle className={cn(
                  "h-5 w-5",
                  confirmClass.includes("red") ? "text-red-400" : "text-amber-400"
                )} />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-white mb-1">{title}</h3>
                <p className="text-xs text-zinc-400 leading-relaxed">{description}</p>
              </div>
            </div>

            {requiresTyped && (
              <div className="mb-4">
                <label className="block text-xs text-zinc-500 mb-1.5">
                  Type <span className="font-mono text-red-400 font-bold">{requiresTyped}</span> to confirm
                </label>
                <input
                  type="text"
                  value={typed}
                  onChange={e => setTyped(e.target.value)}
                  placeholder={requiresTyped}
                  autoFocus
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm font-mono text-white placeholder:text-zinc-600 focus:outline-none focus:border-red-500 focus:ring-1 focus:ring-red-500/30 transition"
                />
              </div>
            )}

            <div className="flex gap-2">
              <button
                onClick={onCancel}
                disabled={isLoading}
                className="flex-1 px-4 py-2 text-xs font-medium text-zinc-400 bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 rounded-lg transition disabled:opacity-50 tap-target"
              >
                Cancel
              </button>
              <button
                onClick={() => { if (canConfirm && !isLoading) onConfirm(); }}
                disabled={!canConfirm || isLoading}
                className={cn(
                  "flex-1 px-4 py-2 text-xs font-semibold rounded-lg transition flex items-center justify-center gap-1.5 tap-target",
                  confirmClass,
                  (!canConfirm || isLoading) && "opacity-40 cursor-not-allowed"
                )}
              >
                {isLoading ? (
                  <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                ) : null}
                {isLoading ? "Processing…" : confirmLabel}
              </button>
            </div>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}

// ── Shared action logic ───────────────────────────────────────────────────────

function useEmergencyActions() {
  const { toast } = useToast();
  const liquidate = useLiquidateAll();
  const restart   = useSystemRestart();

  const [showLiquidateModal, setShowLiquidateModal] = useState(false);
  const [showRestartModal,   setShowRestartModal]   = useState(false);

  function handleLiquidateConfirm() {
    liquidate.mutate(undefined, {
      onSuccess: (data) => {
        setShowLiquidateModal(false);
        const closedCount = data.positions_closed?.length ?? 0;
        const marketOpen = data.market_open;
        const pending = data.pending_liquidation;
        toast({
          title: marketOpen && !pending
            ? `Liquidation Complete — ${closedCount} position(s) closing`
            : `Deferred Liquidation Queued — closes at market open`,
          description: data.fill_note || (
            marketOpen
              ? "Market is open — orders will fill shortly. Kill switch is active."
              : "Market is closed. Positions will be force-closed automatically when the market opens. Kill switch is active."
          ),
          variant: "destructive",
        });
      },
      onError: (err) => {
        setShowLiquidateModal(false);
        toast({ title: "Liquidation Failed", description: err.message || "Unexpected error.", variant: "destructive" });
      },
    });
  }

  function handleRestartConfirm() {
    restart.mutate(undefined, {
      onSuccess: () => {
        setShowRestartModal(false);
        toast({ title: "System Restarted", description: "Error state cleared. Resuming on next cycle." });
      },
      onError: (err) => {
        setShowRestartModal(false);
        toast({ title: "Restart Failed", description: err.message || "Unexpected error.", variant: "destructive" });
      },
    });
  }

  return {
    liquidate, restart,
    showLiquidateModal, setShowLiquidateModal,
    showRestartModal, setShowRestartModal,
    handleLiquidateConfirm, handleRestartConfirm,
  };
}


// ── Compact Header Buttons (always visible in sticky nav) ─────────────────────

export function EmergencyHeaderButtons() {
  const {
    liquidate, restart,
    showLiquidateModal, setShowLiquidateModal,
    showRestartModal,   setShowRestartModal,
    handleLiquidateConfirm, handleRestartConfirm,
  } = useEmergencyActions();

  const { mutate: rebalance, isPending: isRebalancing } = useForceRebalance();
  const [showRebalanceModal, setShowRebalanceModal] = useState(false);
  const { toast } = useToast();

  const { data: haltStatus } = useFleetHaltStatus();
  const fleetHalt = useFleetHalt();
  const fleetResume = useFleetResume();
  const isHalted = haltStatus?.active ?? false;

  const handleFleetHalt = async () => {
    try {
      await fleetHalt.mutateAsync("dashboard_emergency");
      toast({ title: "FLEET HALTED", description: "All trading stopped across all bots.", variant: "destructive" });
    } catch {
      toast({ title: "Halt Failed", description: "Could not write halt flag to DB.", variant: "destructive" });
    }
  };

  const handleFleetResume = async () => {
    try {
      await fleetResume.mutateAsync();
      toast({ title: "Fleet Resumed", description: "Trading resumed across all bots." });
    } catch {
      toast({ title: "Resume Failed", description: "Could not clear halt flag.", variant: "destructive" });
    }
  };

  const handleRebalanceConfirm = () => {
    rebalance(undefined, {
      onSuccess: () => {
        toast({ title: "Rebalance complete", description: "All positions liquidated and pipeline re-run." });
        setShowRebalanceModal(false);
      },
      onError: () => {
        toast({ title: "Rebalance failed", description: "Check logs for details.", variant: "destructive" });
        setShowRebalanceModal(false);
      },
    });
  };

  return (
    <>
      <ConfirmModal
        open={showLiquidateModal}
        title="Confirm Emergency Liquidation"
        description={
          "Market-close ALL open positions (JEPQ protected) and trip the kill switch. " +
          "Cannot be undone without a Kill Switch Reset."
        }
        confirmLabel="Liquidate All Positions"
        confirmClass="bg-red-600 hover:bg-red-500 text-white border border-red-500"
        requiresTyped="LIQUIDATE"
        onConfirm={handleLiquidateConfirm}
        onCancel={() => setShowLiquidateModal(false)}
        isLoading={liquidate.isPending}
      />
      <ConfirmModal
        open={showRestartModal}
        title="Restart Trading System?"
        description="Clear error state and invalidate data caches. Kill switch state is preserved."
        confirmLabel="Restart System"
        confirmClass="bg-amber-600 hover:bg-amber-500 text-white border border-amber-500"
        onConfirm={handleRestartConfirm}
        onCancel={() => setShowRestartModal(false)}
        isLoading={restart.isPending}
      />
      <ConfirmModal
        open={showRebalanceModal}
        title="Force Rebalance All Bots?"
        description={
          "Close ALL open positions across every bot (Alpaca, Kraken, Forex, Options) " +
          "and re-run the trading pipeline. This cannot be undone."
        }
        confirmLabel="Rebalance Now"
        confirmClass="bg-orange-600 hover:bg-orange-500 text-white border border-orange-500"
        onConfirm={handleRebalanceConfirm}
        onCancel={() => setShowRebalanceModal(false)}
        isLoading={isRebalancing}
      />

      <div className="flex items-center gap-1.5">
        {isHalted ? (
          <button
            onClick={handleFleetResume}
            disabled={fleetResume.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-green-500/20 border border-green-500/40 text-green-400 hover:bg-green-500/30 transition animate-pulse"
          >
            <span className="w-2 h-2 rounded-full bg-green-400" />
            RESUME FLEET
          </button>
        ) : (
          <button
            onClick={handleFleetHalt}
            disabled={fleetHalt.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-red-500/10 border border-red-500/30 text-red-400 hover:bg-red-500/20 transition"
          >
            <span className="w-2 h-2 rounded-full bg-red-500" />
            HALT FLEET
          </button>
        )}

        <button
          onClick={() => setShowRebalanceModal(true)}
          disabled={isRebalancing}
          title="Force Rebalance — close all positions and re-run pipeline"
          className={cn(
            "flex items-center justify-center gap-1.5 rounded-md",
            "text-[10px] font-semibold tracking-wide",
            "bg-orange-950/40 border border-orange-800/40 text-orange-400",
            "hover:bg-orange-600 hover:border-orange-500 hover:text-white",
            "transition-all duration-150",
            "disabled:opacity-40 disabled:cursor-not-allowed",
            "min-h-[44px] min-w-[44px] px-2.5 py-1.5 sm:px-2.5"
          )}
        >
          {isRebalancing
            ? <RefreshCw className="h-3.5 w-3.5 sm:h-3 sm:w-3 animate-spin" />
            : <RotateCcw className="h-3.5 w-3.5 sm:h-3 sm:w-3" />
          }
          <span className="hidden md:inline">Rebalance</span>
        </button>

        <button
          onClick={() => setShowLiquidateModal(true)}
          disabled={liquidate.isPending}
          title="Emergency Liquidate All"
          className={cn(
            "group flex items-center justify-center gap-1.5 rounded-md",
            "text-[10px] font-bold tracking-widest uppercase",
            "bg-red-950/60 border border-red-800/60 text-red-400",
            "hover:bg-red-600 hover:border-red-500 hover:text-white",
            "transition-all duration-150",
            "disabled:opacity-40 disabled:cursor-not-allowed",
            "ring-0 hover:ring-1 hover:ring-red-400/40",
            "min-h-[44px] min-w-[44px] px-2.5 py-1.5 sm:px-2.5"
          )}
        >
          <span className="relative flex h-1.5 w-1.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-500 opacity-70" />
            <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-red-500" />
          </span>
          <ShieldOff className="h-3.5 w-3.5 sm:h-3 sm:w-3" />
          <span className="hidden md:inline">Liquidate All</span>
        </button>

        <button
          onClick={() => setShowRestartModal(true)}
          disabled={restart.isPending}
          title="Restart System"
          className={cn(
            "flex items-center justify-center gap-1.5 rounded-md",
            "text-[10px] font-semibold tracking-wide",
            "bg-zinc-800/80 border border-zinc-700/60 text-zinc-400",
            "hover:bg-amber-900/40 hover:border-amber-600/50 hover:text-amber-300",
            "transition-all duration-150",
            "disabled:opacity-40 disabled:cursor-not-allowed",
            "min-h-[44px] min-w-[44px] px-2.5 py-1.5 sm:px-2.5"
          )}
        >
          {restart.isPending
            ? <RefreshCw className="h-3.5 w-3.5 sm:h-3 sm:w-3 animate-spin" />
            : <Zap className="h-3.5 w-3.5 sm:h-3 sm:w-3" />
          }
          <span className="hidden md:inline">Restart</span>
        </button>
      </div>
    </>
  );
}


// ── Emergency Controls Panel ──────────────────────────────────────────────────

export function EmergencyControls() {
  const {
    liquidate, restart,
    showLiquidateModal, setShowLiquidateModal,
    showRestartModal,   setShowRestartModal,
    handleLiquidateConfirm, handleRestartConfirm,
  } = useEmergencyActions();

  return (
    <>
      <ConfirmModal
        open={showLiquidateModal}
        title="Confirm Emergency Liquidation"
        description={
          "Market-close ALL open positions (JEPQ vault protected) and trip the kill switch. " +
          "Cannot be undone without a Kill Switch Reset."
        }
        confirmLabel="Liquidate All Positions"
        confirmClass="bg-red-600 hover:bg-red-500 text-white border border-red-500"
        requiresTyped="LIQUIDATE"
        onConfirm={handleLiquidateConfirm}
        onCancel={() => setShowLiquidateModal(false)}
        isLoading={liquidate.isPending}
      />
      <ConfirmModal
        open={showRestartModal}
        title="Restart Trading System?"
        description={
          "Clear error state and invalidate all data caches so the next cycle fetches fresh data. " +
          "Kill switch state is preserved."
        }
        confirmLabel="Restart System"
        confirmClass="bg-amber-600 hover:bg-amber-500 text-white border border-amber-500"
        onConfirm={handleRestartConfirm}
        onCancel={() => setShowRestartModal(false)}
        isLoading={restart.isPending}
      />

      {/* Control Row */}
      <div className="flex flex-col sm:flex-row gap-2">
        {/* Liquidate All */}
        <button
          onClick={() => setShowLiquidateModal(true)}
          disabled={liquidate.isPending}
          className={cn(
            "group relative flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg",
            "text-xs font-bold tracking-wider uppercase",
            "bg-red-950/50 border border-red-700/60 text-red-400",
            "hover:bg-red-600 hover:border-red-500 hover:text-white",
            "transition-all duration-150",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            "ring-0 hover:ring-2 hover:ring-red-500/40 hover:shadow-lg hover:shadow-red-900/30"
          )}
        >
          {/* Pulsing indicator */}
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-500 opacity-60" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-red-500" />
          </span>
          <ShieldOff className="h-3.5 w-3.5" />
          Liquidate All
        </button>

        {/* Restart System */}
        <button
          onClick={() => setShowRestartModal(true)}
          disabled={restart.isPending}
          className={cn(
            "flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg",
            "text-xs font-semibold tracking-wide",
            "bg-zinc-800 border border-zinc-700 text-zinc-300",
            "hover:bg-amber-900/30 hover:border-amber-600/50 hover:text-amber-300",
            "transition-all duration-150",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            "ring-0 hover:ring-1 hover:ring-amber-500/30"
          )}
        >
          {restart.isPending
            ? <RefreshCw className="h-3.5 w-3.5 animate-spin" />
            : <Zap className="h-3.5 w-3.5" />
          }
          Restart System
        </button>
      </div>
    </>
  );
}
