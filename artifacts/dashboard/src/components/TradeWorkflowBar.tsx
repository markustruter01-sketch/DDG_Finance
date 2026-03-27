import { useState, useMemo } from "react";
import { Loader2, Power } from "lucide-react";
import { useLatestAllocation, usePlatformStatus, useToggleAutoTrading } from "@/hooks/use-trading";
import { useToast } from "@/hooks/use-toast";
import { cn } from "@/lib/utils";

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

export function TradeWorkflowBar() {
  const { toast } = useToast();
  const { data: allocation } = useLatestAllocation();
  const { data: status } = usePlatformStatus();
  const toggleAutoTrading = useToggleAutoTrading();

  const [autoTradingConfirm, setAutoTradingConfirm] = useState<"enable" | "disable" | null>(null);

  const autoTradingEnabled = status?.auto_trading ?? false;

  const avgConviction = useMemo(() => {
    if (!allocation?.allocation) return null;
    const nonCash = allocation.allocation.filter((s: any) => s.ticker !== "SGOV");
    if (!nonCash.length) return null;
    return nonCash.reduce((sum: number, s: any) => sum + s.conviction_score, 0) / nonCash.length;
  }, [allocation]);

  const handleAutoTradingToggle = async () => {
    const enabling = autoTradingConfirm === "enable";
    setAutoTradingConfirm(null);
    try {
      await toggleAutoTrading.mutateAsync(enabling);
      toast({
        title: enabling ? "Auto Trading Enabled" : "Auto Trading Disabled",
        description: enabling
          ? "The autonomous system is now active — runs every 15 min during market hours."
          : "All scheduled trading paused. Manual operations still available.",
      });
    } catch (err: any) {
      toast({ variant: "destructive", title: "Toggle Failed", description: err.message });
    }
  };

  return (
    <div className="w-full">
      {/* Confirm overlay */}
      {autoTradingConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-slate-900 border border-white/10 rounded-2xl shadow-2xl p-8 max-w-md w-full mx-4">
            <h3 className="text-lg font-bold text-white mb-2">
              {autoTradingConfirm === "enable" ? "Enable Auto Trading?" : "Disable Auto Trading?"}
            </h3>
            <p className="text-muted-foreground text-sm mb-6">
              {autoTradingConfirm === "enable"
                ? "This activates autonomous trading — the AI will run analysis and execute real paper trades every 15 minutes during market hours, plus 24/7 crypto cycles when the market is closed."
                : "This pauses all automated trading. No scheduled analysis or executions will run until you re-enable it. Kill switch and manual controls remain active."}
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
                {autoTradingConfirm === "enable" ? "Yes, Enable" : "Yes, Disable"}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-4">
        {/* AUTO TRADING TOGGLE — the primary action */}
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

        {/* CONVICTION METER — shown when there's an active allocation */}
        {avgConviction !== null && allocation?.allocation && (
          <>
            <div className="h-8 w-px bg-white/10" />
            <ConvictionRing value={avgConviction} />
          </>
        )}
      </div>
    </div>
  );
}
