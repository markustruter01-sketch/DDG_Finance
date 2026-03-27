import { useState, useMemo, useEffect } from "react";
import { Loader2, Play, TrendingUp, CheckCircle2, Clock, Zap, Power } from "lucide-react";
import { useRunAnalysis } from "@/hooks/use-trading";
import { useLatestAllocation, usePlatformStatus, useToggleAutoTrading } from "@/hooks/use-trading";
import { useToast } from "@/hooks/use-toast";
import { useQueryClient } from "@tanstack/react-query";
import { cn } from "@/lib/utils";

type WorkflowState = "idle" | "analyzing" | "ready" | "trading" | "done";

function ConvictionRing({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const radius = 20;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference - (pct / 100) * circumference;
  const color = pct >= 80 ? "#22c55e" : pct >= 70 ? "#3b82f6" : "#f59e0b";

  return (
    <div className="flex items-center gap-3">
      <div className="relative flex items-center justify-center">
        <svg width="52" height="52" viewBox="0 0 52 52" className="-rotate-90">
          <circle cx="26" cy="26" r={radius} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="4" />
          <circle
            cx="26" cy="26" r={radius}
            fill="none"
            stroke={color}
            strokeWidth="4"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
            style={{ transition: "stroke-dashoffset 0.8s ease, stroke 0.4s ease" }}
          />
        </svg>
        <span className="absolute text-xs font-mono font-bold" style={{ color }}>{pct}%</span>
      </div>
      <div className="flex flex-col">
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Avg Conviction</span>
        <span className="text-sm font-semibold text-white">
          {pct >= 80 ? "High Confidence" : pct >= 70 ? "Moderate" : "Cautious"}
        </span>
      </div>
    </div>
  );
}

function MarketTimingBadge({ isOpen, nextOpen }: { isOpen: boolean; nextOpen: string | null }) {
  if (isOpen) {
    return (
      <span className="flex items-center gap-1.5 text-xs px-2 py-1 rounded-full bg-green-500/10 border border-green-500/20 text-green-400">
        <Zap className="h-3 w-3" /> Executes immediately — market is open
      </span>
    );
  }

  let timeStr = "";
  if (nextOpen) {
    try {
      const diff = new Date(nextOpen).getTime() - Date.now();
      if (diff > 0) {
        const hours = Math.floor(diff / 3600000);
        const mins = Math.floor((diff % 3600000) / 60000);
        timeStr = hours > 0 ? `${hours}h ${mins}m` : `${mins}m`;
      }
    } catch {}
  }

  return (
    <span className="flex items-center gap-1.5 text-xs px-2 py-1 rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-400">
      <Clock className="h-3 w-3" />
      {timeStr ? `Queued for next open in ${timeStr}` : "Queued for next market open"}
    </span>
  );
}

export function TradeWorkflowBar() {
  const { toast } = useToast();
  const qc = useQueryClient();
  const runAnalysis = useRunAnalysis();
  const { data: allocation } = useLatestAllocation();
  const { data: status } = usePlatformStatus();
  const toggleAutoTrading = useToggleAutoTrading();

  const [workflowState, setWorkflowState] = useState<WorkflowState>("idle");
  const [pendingConfirm, setPendingConfirm] = useState(false);
  const [autoTradingConfirm, setAutoTradingConfirm] = useState<"enable" | "disable" | null>(null);

  const autoTradingEnabled = status?.auto_trading ?? false;

  const avgConviction = useMemo(() => {
    if (!allocation?.allocation) return null;
    const nonCash = allocation.allocation.filter((s) => s.ticker !== "SGOV");
    if (!nonCash.length) return null;
    return nonCash.reduce((sum, s) => sum + s.conviction_score, 0) / nonCash.length;
  }, [allocation]);

  useEffect(() => {
    if (workflowState === "done") {
      const t = setTimeout(() => setWorkflowState("idle"), 5000);
      return () => clearTimeout(t);
    }
  }, [workflowState]);

  const handleAutoTradingToggle = async () => {
    const enabling = autoTradingConfirm === "enable";
    setAutoTradingConfirm(null);
    try {
      await toggleAutoTrading.mutateAsync(enabling);
      toast({
        title: enabling ? "Auto Trading Enabled" : "Auto Trading Disabled",
        description: enabling
          ? "The autonomous trading system is now active. It will run daily at 9:31 AM ET."
          : "The autonomous trading system has been paused. No scheduled trades will execute.",
      });
    } catch (err: any) {
      toast({ variant: "destructive", title: "Toggle Failed", description: err.message });
    }
  };

  const handleStartAnalysis = async () => {
    setWorkflowState("analyzing");
    try {
      await runAnalysis.mutateAsync({ dry_run: true, force: true });
      await qc.refetchQueries({ queryKey: ["/allocation/latest"] });
      setWorkflowState("ready");
    } catch (err: any) {
      setWorkflowState("idle");
      toast({ variant: "destructive", title: "Analysis Failed", description: err.message });
    }
  };

  const handlePlaceTrades = async () => {
    setPendingConfirm(false);
    setWorkflowState("trading");
    try {
      await runAnalysis.mutateAsync({ dry_run: false, force: true });
      setWorkflowState("done");
      toast({ title: "Trades Placed", description: "Orders submitted to Alpaca paper trading." });
    } catch (err: any) {
      setWorkflowState("ready");
      toast({ variant: "destructive", title: "Execution Failed", description: err.message });
    }
  };

  const isAnalyzing = workflowState === "analyzing";
  const isReady = workflowState === "ready";
  const isTrading = workflowState === "trading";
  const isDone = workflowState === "done";
  const isIdle = workflowState === "idle";

  return (
    <div className="w-full">
      {/* Confirm overlay for Auto Trading toggle */}
      {autoTradingConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-slate-900 border border-white/10 rounded-2xl shadow-2xl p-8 max-w-md w-full mx-4">
            <h3 className="text-lg font-bold text-white mb-2">
              {autoTradingConfirm === "enable" ? "Enable Auto Trading?" : "Disable Auto Trading?"}
            </h3>
            <p className="text-muted-foreground text-sm mb-6">
              {autoTradingConfirm === "enable"
                ? "This will activate the autonomous trading system. It will automatically run daily analysis at 9:31 AM ET, monitor drawdowns every 30 minutes, and reconcile trades at 4:10 PM ET — all using your Alpaca paper trading account."
                : "This will pause all automated trading activity. No scheduled analysis, kill switch checks, or post-mortem reconciliation will run until you re-enable it. Manual operations will still work."}
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setAutoTradingConfirm(null)}
                className="px-4 py-2 rounded-lg text-sm text-muted-foreground hover:text-white border border-white/10 hover:border-white/20 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleAutoTradingToggle}
                className={cn(
                  "px-6 py-2 rounded-lg text-sm font-semibold text-white transition-colors shadow-lg",
                  autoTradingConfirm === "enable"
                    ? "bg-emerald-600 hover:bg-emerald-500 shadow-emerald-900/30"
                    : "bg-red-600 hover:bg-red-500 shadow-red-900/30"
                )}
              >
                {autoTradingConfirm === "enable" ? "Yes, Enable Auto Trading" : "Yes, Disable Auto Trading"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Confirm overlay for Place Trades */}
      {pendingConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-slate-900 border border-white/10 rounded-2xl shadow-2xl p-8 max-w-md w-full mx-4">
            <h3 className="text-lg font-bold text-white mb-2">Confirm Trade Execution</h3>
            <p className="text-muted-foreground text-sm mb-2">
              This will place real orders against your Alpaca paper trading account based on the analysis above.
            </p>
            {avgConviction !== null && (
              <p className="text-sm text-white/80 mb-6">
                System confidence: <span className="font-bold text-primary">{Math.round(avgConviction * 100)}%</span>
              </p>
            )}
            {status && (
              <div className="mb-6">
                <MarketTimingBadge isOpen={status.market.is_open} nextOpen={status.market.next_open} />
              </div>
            )}
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setPendingConfirm(false)}
                className="px-4 py-2 rounded-lg text-sm text-muted-foreground hover:text-white border border-white/10 hover:border-white/20 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handlePlaceTrades}
                className="px-6 py-2 rounded-lg text-sm font-semibold bg-green-600 hover:bg-green-500 text-white transition-colors shadow-lg shadow-green-900/30"
              >
                Place Trades Now
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-4">

        {/* PRIMARY WORKFLOW BUTTON */}
        {(isIdle) && (
          <button
            onClick={handleStartAnalysis}
            className="relative group flex items-center gap-3 px-8 py-3.5 rounded-xl font-semibold text-sm bg-primary hover:bg-primary/90 text-white shadow-lg shadow-primary/20 transition-all duration-200 active:scale-[0.98] overflow-hidden"
          >
            <span className="absolute inset-0 bg-white/10 opacity-0 group-hover:opacity-100 transition-opacity" />
            <Play className="h-4 w-4 fill-current" />
            Start Analysis
          </button>
        )}

        {isAnalyzing && (
          <button
            disabled
            className="flex items-center gap-3 px-8 py-3.5 rounded-xl font-semibold text-sm bg-slate-800 text-white/70 border border-white/10 cursor-not-allowed"
          >
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
            <span>Analyzing Markets<span className="inline-flex gap-0.5 ml-0.5">
              <span className="animate-bounce" style={{ animationDelay: "0ms" }}>.</span>
              <span className="animate-bounce" style={{ animationDelay: "150ms" }}>.</span>
              <span className="animate-bounce" style={{ animationDelay: "300ms" }}>.</span>
            </span></span>
          </button>
        )}

        {isReady && (
          <button
            onClick={() => setPendingConfirm(true)}
            className="relative group flex items-center gap-3 px-8 py-3.5 rounded-xl font-semibold text-sm bg-green-600 hover:bg-green-500 text-white shadow-lg shadow-green-900/30 transition-all duration-200 active:scale-[0.98] overflow-hidden"
          >
            <span className="absolute inset-0 bg-white/5 opacity-0 group-hover:opacity-100 transition-opacity" />
            <TrendingUp className="h-4 w-4" />
            Place Trades
          </button>
        )}

        {isTrading && (
          <button
            disabled
            className="flex items-center gap-3 px-8 py-3.5 rounded-xl font-semibold text-sm bg-green-900/40 text-green-300/70 border border-green-500/20 cursor-not-allowed"
          >
            <Loader2 className="h-4 w-4 animate-spin text-green-400" />
            Placing Trades...
          </button>
        )}

        {isDone && (
          <div className="flex items-center gap-2 px-8 py-3.5 rounded-xl font-semibold text-sm bg-green-500/10 border border-green-500/30 text-green-400">
            <CheckCircle2 className="h-4 w-4" />
            Trades Placed Successfully
          </div>
        )}

        {/* AUTO TRADING TOGGLE */}
        <button
          onClick={() => setAutoTradingConfirm(autoTradingEnabled ? "disable" : "enable")}
          disabled={toggleAutoTrading.isPending}
          className={cn(
            "relative group flex items-center gap-2.5 px-6 py-3.5 rounded-xl font-semibold text-sm transition-all duration-200 active:scale-[0.98] overflow-hidden border",
            autoTradingEnabled
              ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/20 hover:border-emerald-500/50"
              : "bg-slate-800/60 border-white/10 text-muted-foreground hover:text-white hover:border-white/20"
          )}
        >
          {toggleAutoTrading.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Power className={cn("h-4 w-4", autoTradingEnabled && "drop-shadow-[0_0_6px_rgba(16,185,129,0.6)]")} />
          )}
          <span>{autoTradingEnabled ? "Auto Trading ON" : "Auto Trading OFF"}</span>
          {autoTradingEnabled && (
            <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
          )}
        </button>

        {/* Reset button when in ready state (let them re-run analysis) */}
        {isReady && (
          <button
            onClick={() => setWorkflowState("idle")}
            className="text-xs text-muted-foreground hover:text-white transition-colors underline underline-offset-2"
          >
            Re-run analysis
          </button>
        )}

        {/* CONVICTION METER — shown when analysis has results */}
        {avgConviction !== null && (isReady || isDone || (isIdle && allocation?.allocation)) && (
          <>
            <div className="h-8 w-px bg-white/10" />
            <ConvictionRing value={avgConviction} />
          </>
        )}

        {/* Market timing badge — shown in ready state */}
        {isReady && status && (
          <MarketTimingBadge isOpen={status.market.is_open} nextOpen={status.market.next_open} />
        )}
      </div>
    </div>
  );
}
