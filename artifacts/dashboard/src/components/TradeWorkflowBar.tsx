import { useState, useMemo, useEffect, useCallback } from "react";
import { Loader2, Power, FileText, X, Anchor, Activity } from "lucide-react";
import {
  useLatestAllocation, usePlatformStatus, useToggleAutoTrading,
  useKrakenAutoTrading, useToggleKrakenAutoTrading,
} from "@/hooks/use-trading";
import { useToast } from "@/hooks/use-toast";
import { cn } from "@/lib/utils";
import { WhitepaperContent } from "@/components/WhitepaperContent";
import { SystemHealthModal } from "@/components/SystemHealthModal";

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

type ConfirmKind = "alpaca-enable" | "alpaca-disable" | "kraken-pause" | "kraken-resume" | null;

export function TradeWorkflowBar() {
  const { toast } = useToast();
  const { data: allocation } = useLatestAllocation();
  const { data: status } = usePlatformStatus();
  const toggleAutoTrading = useToggleAutoTrading();
  const { data: krakenControl } = useKrakenAutoTrading();
  const toggleKrakenBot = useToggleKrakenAutoTrading();

  const [confirmKind, setConfirmKind] = useState<ConfirmKind>(null);
  const [whitepaperOpen, setWhitepaperOpen] = useState(false);
  const [healthOpen, setHealthOpen] = useState(false);

  const closeWhitepaper = useCallback(() => setWhitepaperOpen(false), []);

  useEffect(() => {
    if (!whitepaperOpen) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") closeWhitepaper(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [whitepaperOpen, closeWhitepaper]);

  const autoTradingEnabled = status?.auto_trading ?? false;
  const krakenPaused = krakenControl?.bot_paused ?? false;

  const avgConviction = useMemo(() => {
    if (!allocation?.allocation) return null;
    const nonCash = allocation.allocation.filter((s: any) => s.ticker !== "SGOV");
    if (!nonCash.length) return null;
    return nonCash.reduce((sum: number, s: any) => sum + s.conviction_score, 0) / nonCash.length;
  }, [allocation]);

  const handleConfirm = async () => {
    const kind = confirmKind;
    setConfirmKind(null);
    try {
      if (kind === "alpaca-enable" || kind === "alpaca-disable") {
        const enabling = kind === "alpaca-enable";
        await toggleAutoTrading.mutateAsync(enabling);
        toast({
          title: enabling ? "Auto Trading Enabled" : "Auto Trading Disabled",
          description: enabling
            ? "The autonomous system is now active — runs every 15 min during market hours."
            : "All scheduled trading paused. Manual operations still available.",
        });
      } else if (kind === "kraken-pause" || kind === "kraken-resume") {
        const pausing = kind === "kraken-pause";
        await toggleKrakenBot.mutateAsync(pausing);
        toast({
          title: pausing ? "Kraken Bot Paused" : "Kraken Bot Resumed",
          description: pausing
            ? "SPY/QQQ Trend will skip signal processing each cycle. The workflow stays running."
            : "SPY/QQQ Trend is active and will evaluate signals each cycle.",
        });
      }
    } catch (err: any) {
      toast({ variant: "destructive", title: "Toggle Failed", description: err.message });
    }
  };

  const confirmMeta: Record<NonNullable<ConfirmKind>, { title: string; body: string; btnLabel: string; danger: boolean }> = {
    "alpaca-enable": {
      title: "Enable Auto Trading?",
      body: "This activates autonomous trading — the AI will run analysis and execute real paper trades every 15 minutes during market hours, plus 24/7 crypto cycles when the market is closed.",
      btnLabel: "Yes, Enable",
      danger: false,
    },
    "alpaca-disable": {
      title: "Disable Auto Trading?",
      body: "This pauses all automated trading. No scheduled analysis or executions will run until you re-enable it. Kill switch and manual controls remain active.",
      btnLabel: "Yes, Disable",
      danger: true,
    },
    "kraken-pause": {
      title: "Pause SPY/QQQ Trend Bot?",
      body: "The Kraken bot workflow stays running but will skip signal processing each cycle. Open positions remain open and are still tracked. Resume at any time.",
      btnLabel: "Yes, Pause",
      danger: true,
    },
    "kraken-resume": {
      title: "Resume SPY/QQQ Trend Bot?",
      body: "The Kraken bot will resume evaluating mean-reversion + RSI signals every cycle. It will trade according to its configured strategy.",
      btnLabel: "Yes, Resume",
      danger: false,
    },
  };

  const meta = confirmKind ? confirmMeta[confirmKind] : null;

  return (
    <div className="w-full">
      {/* Confirm overlay */}
      {confirmKind && meta && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-slate-900 border border-white/10 rounded-2xl shadow-2xl p-8 max-w-md w-full mx-4">
            <h3 className="text-lg font-bold text-white mb-2">{meta.title}</h3>
            <p className="text-muted-foreground text-sm mb-6">{meta.body}</p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setConfirmKind(null)}
                className="px-4 py-2 rounded-lg text-sm text-muted-foreground hover:text-white border border-white/10 hover:border-white/20 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirm}
                className={cn(
                  "px-6 py-2 rounded-lg text-sm font-semibold text-white transition-colors shadow-lg",
                  meta.danger
                    ? "bg-red-600 hover:bg-red-500 shadow-red-900/30"
                    : "bg-emerald-600 hover:bg-emerald-500 shadow-emerald-900/30"
                )}
              >
                {meta.btnLabel}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        {/* ── Alpaca Auto Trading toggle ── */}
        <button
          onClick={() => setConfirmKind(autoTradingEnabled ? "alpaca-disable" : "alpaca-enable")}
          disabled={toggleAutoTrading.isPending}
          className={cn(
            "relative group flex items-center gap-2.5 px-5 py-3 rounded-xl font-semibold text-sm transition-all duration-200 active:scale-[0.98] overflow-hidden border",
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
          <span>{autoTradingEnabled ? "Alpaca ON" : "Alpaca OFF"}</span>
          {autoTradingEnabled && (
            <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
          )}
        </button>

        {/* ── Kraken Bot toggle ── */}
        <button
          onClick={() => setConfirmKind(krakenPaused ? "kraken-resume" : "kraken-pause")}
          disabled={toggleKrakenBot.isPending}
          className={cn(
            "relative group flex items-center gap-2.5 px-5 py-3 rounded-xl font-semibold text-sm transition-all duration-200 active:scale-[0.98] overflow-hidden border",
            !krakenPaused
              ? "bg-cyan-500/10 border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/20 hover:border-cyan-500/50"
              : "bg-slate-800/60 border-white/10 text-muted-foreground hover:text-white hover:border-white/20"
          )}
        >
          {toggleKrakenBot.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Anchor className={cn("h-4 w-4", !krakenPaused && "drop-shadow-[0_0_6px_rgba(6,182,212,0.6)]")} />
          )}
          <span>{krakenPaused ? "Kraken OFF" : "Kraken ON"}</span>
          {!krakenPaused && (
            <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-cyan-400 animate-pulse" />
          )}
        </button>

        <button
          onClick={() => setWhitepaperOpen(true)}
          className="flex items-center gap-2 px-5 py-3 rounded-xl font-semibold text-sm transition-all duration-200 active:scale-[0.98] border bg-indigo-500/10 border-indigo-500/30 text-indigo-400 hover:bg-indigo-500/20 hover:border-indigo-500/50"
        >
          <FileText className="h-4 w-4" />
          <span>Whitepaper</span>
        </button>

        <button
          onClick={() => setHealthOpen(true)}
          className="flex items-center gap-2 px-5 py-3 rounded-xl font-semibold text-sm transition-all duration-200 active:scale-[0.98] border bg-emerald-500/10 border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/20 hover:border-emerald-500/50"
        >
          <Activity className="h-4 w-4" />
          <span>System Health</span>
        </button>

        {healthOpen && <SystemHealthModal onClose={() => setHealthOpen(false)} />}

        {whitepaperOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm" onClick={closeWhitepaper}>
            <div className="relative w-[90vw] h-[90vh] max-w-5xl bg-slate-900 border border-white/10 rounded-2xl shadow-2xl flex flex-col overflow-hidden" onClick={(e) => e.stopPropagation()}>
              <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
                <h3 className="text-lg font-bold text-white flex items-center gap-2">
                  <FileText className="h-5 w-5 text-indigo-400" />
                  Platform Whitepaper
                </h3>
                <button
                  onClick={closeWhitepaper}
                  className="p-2 rounded-lg text-muted-foreground hover:text-white hover:bg-white/10 transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="flex-1 overflow-y-auto">
                <WhitepaperContent />
              </div>
            </div>
          </div>
        )}

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
