import { useMemo, useRef, useEffect, useState } from "react";
import {
  usePlatformStatus, usePortfolio, useLivePositions, useLatestAllocation,
  useJournal, useRagLosses, useRagWins, usePerformanceHistory,
  usePerformanceSummary, useAICommentary, useRefreshCommentary,
  useVault, useManualSweep, useAuditorReport, useTriggerAudit,
  type AllocationPlan, type AuditFinding,
} from "@/hooks/use-trading";
import { cn, formatCurrency, formatPercentAbs, formatDate } from "@/lib/utils";
import { Card, CardHeader, CardTitle, CardContent, Badge, PnlText, PnlValue } from "@/components/ui";
import { ControlPanel } from "@/components/ControlPanel";
import { TradeWorkflowBar } from "@/components/TradeWorkflowBar";
import {
  Activity, ShieldAlert, History, TrendingDown, TrendingUp,
  LayoutList, WifiOff, AlertTriangle, Target, BarChart3,
  RefreshCw, Sparkles, Brain, Trophy, Flame, Zap, X,
  Vault, ArrowUpRight, Coins, TrendingUp as GrowthIcon,
  Shield, Eye, CheckCircle2, XCircle, AlertOctagon, Lock,
  Lightbulb, Play,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";

function useCountUp(target: number, duration = 1200, enabled = true) {
  const [value, setValue] = useState(0);
  const prevTarget = useRef(0);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (!enabled) { setValue(target); return; }
    const from = prevTarget.current;
    prevTarget.current = target;
    const start = performance.now();
    const animate = (now: number) => {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setValue(from + (target - from) * eased);
      if (progress < 1) rafRef.current = requestAnimationFrame(animate);
    };
    rafRef.current = requestAnimationFrame(animate);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [target, duration, enabled]);

  return value;
}

// ── System Status Banner ───────────────────────────────────────────────────────

const EXPECTED_JOBS = 4;

function tradingModeLabel(mode: string | undefined): string {
  switch (mode) {
    case "full_market": return "FULL MARKET";
    case "crypto_only": return "CRYPTO ONLY";
    default: return "IDLE";
  }
}

function tradingModeColor(mode: string | undefined): string {
  switch (mode) {
    case "full_market": return "text-green-400";
    case "crypto_only": return "text-purple-400";
    default: return "text-zinc-500";
  }
}

function SystemStatusBanner() {
  const { data, isError } = usePlatformStatus();

  let sysStatus: "online" | "degraded" | "offline";
  let reason: string;
  let tradingMode: string | undefined;

  if (isError || !data) {
    sysStatus = "offline";
    reason = "Cannot reach trading API — check that the server is running";
  } else {
    const jobCount = data.scheduler_jobs.length;
    const lastStatus = data.last_run.last_run_status;
    const errorCount = data.last_run.error_count;
    tradingMode = data.trading_mode;

    if (jobCount < EXPECTED_JOBS) {
      sysStatus = "degraded";
      reason = `Only ${jobCount}/${EXPECTED_JOBS} scheduler jobs registered`;
    } else if (["error", "analysis_failed", "execution_failed", "kill_switch_tripped"].includes(lastStatus)) {
      sysStatus = "degraded";
      reason = `Last run failed (${errorCount} total error${errorCount !== 1 ? "s" : ""})`;
    } else {
      sysStatus = "online";
      const runCount = data.last_run.run_count;
      const modeTag = tradingModeLabel(tradingMode);
      if (lastStatus === "never_run") {
        reason = `24/7 scheduler ready (15-min cycles) — ${modeTag} mode`;
      } else {
        reason = `All systems operational — cycle #${runCount} — ${modeTag} mode`;
      }
    }
  }

  if (sysStatus === "online") {
    return (
      <div className="sticky top-14 z-30 w-full bg-green-500/8 border-b border-green-500/15 backdrop-blur-md">
        <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 h-8 flex items-center gap-2">
          <span className="relative flex h-1.5 w-1.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-500 opacity-75" />
            <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-green-500" />
          </span>
          <span className="text-xs text-green-400 font-medium">ONLINE</span>
          <span className="text-xs text-green-500/60">— {reason}</span>
          {tradingMode && (
            <span className={cn("text-xs font-mono ml-auto", tradingModeColor(tradingMode))}>
              {tradingModeLabel(tradingMode)}
            </span>
          )}
        </div>
      </div>
    );
  }

  if (sysStatus === "degraded") {
    return (
      <div className="sticky top-14 z-30 w-full bg-amber-500/10 border-b border-amber-500/20 backdrop-blur-md">
        <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 h-8 flex items-center gap-2">
          <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
          <span className="text-xs text-amber-400 font-medium">DEGRADED</span>
          <span className="text-xs text-amber-500/70">— {reason}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="sticky top-14 z-30 w-full bg-red-500/10 border-b border-red-500/20 backdrop-blur-md">
      <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 h-8 flex items-center gap-2">
        <WifiOff className="h-3.5 w-3.5 text-red-400" />
        <span className="text-xs text-red-400 font-medium">OFFLINE</span>
        <span className="text-xs text-red-500/70">— {reason}</span>
      </div>
    </div>
  );
}

// ── Header ────────────────────────────────────────────────────────────────────

function Header() {
  const { data: status } = usePlatformStatus();

  return (
    <header className="sticky top-0 z-40 w-full bg-slate-950/90 backdrop-blur-md border-b border-white/5">
      <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-7 w-7 rounded-lg bg-primary/20 border border-primary/40 flex items-center justify-center">
            <Activity className="h-4 w-4 text-primary" />
          </div>
          <h1 className="text-lg font-bold tracking-tight text-white">Quant Terminal</h1>
        </div>

        <div className="flex items-center gap-5">
          <div className="flex flex-col items-end">
            <span className="text-[9px] uppercase text-muted-foreground font-semibold tracking-wider">Market</span>
            {status?.market.is_open ? (
              <span className="flex items-center gap-1 text-xs font-semibold text-green-400">
                <span className="relative flex h-1.5 w-1.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-green-400" />
                </span>
                OPEN
              </span>
            ) : (
              <span className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
                <span className="inline-flex rounded-full h-1.5 w-1.5 bg-slate-600" />
                CLOSED
              </span>
            )}
          </div>
          <div className="h-6 w-px bg-white/8" />
          <div className="flex flex-col items-end">
            <span className="text-[9px] uppercase text-muted-foreground font-semibold tracking-wider">Kill Switch</span>
            {status?.kill_switch.tripped ? (
              <span className="text-xs font-semibold text-red-400 flex items-center gap-1">
                <ShieldAlert className="h-3 w-3" /> TRIPPED
              </span>
            ) : (
              <span className="text-xs font-medium text-green-400 flex items-center gap-1">
                <ShieldAlert className="h-3 w-3 opacity-60" /> ARMED
              </span>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}

// ── Portfolio Metrics ──────────────────────────────────────────────────────────

function AnimatedCurrency({ value, className }: { value: number; className?: string }) {
  const animated = useCountUp(value, 1400);
  return <span className={className}>{formatCurrency(animated)}</span>;
}

// Slot-machine rolling digit — each numeric character independently rolls in
function SlotDigit({ digit }: { digit: string }) {
  if (!/\d/.test(digit)) return <span>{digit}</span>;
  return (
    <span
      className="inline-block overflow-hidden"
      style={{ height: "1.1em", verticalAlign: "bottom", minWidth: "0.55em", textAlign: "center" }}
    >
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={digit}
          className="block"
          initial={{ y: "100%", opacity: 0 }}
          animate={{ y: "0%", opacity: 1 }}
          exit={{ y: "-100%", opacity: 0 }}
          transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
          style={{ lineHeight: "1.1em", height: "1.1em" }}
        >
          {digit}
        </motion.span>
      </AnimatePresence>
    </span>
  );
}

function RollingCurrency({ value, className }: { value: number; className?: string }) {
  const formatted = formatCurrency(value);
  return (
    <span className={cn("inline-flex items-end", className)}>
      {formatted.split("").map((char, i) => (
        <SlotDigit key={i} digit={char} />
      ))}
    </span>
  );
}

function PortfolioMetrics() {
  const { data } = usePortfolio();
  const { data: vault } = useVault();
  const { data: positions } = useLivePositions();

  if (!data) return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
      {[0, 1, 2, 3, 4].map(i => <div key={i} className="h-24 rounded-xl bg-card/40 animate-pulse border border-border" />)}
    </div>
  );

  const isProfit = data.account.equity >= 100000;
  const pnl = data.account.equity - 100000;
  const pnlPct = (pnl / 100000) * 100;

  const vaultSymbol    = vault?.vault_symbol ?? "JEPQ";
  const totalVaulted   = vault?.total_vaulted_usd ?? 0;
  const hwm            = vault?.hwm ?? 0;
  const totalSweeps    = vault?.total_sweeps ?? 0;
  const isVaultInit    = vault?.initialised ?? false;

  // Find live JEPQ position for true market value and P&L
  const vaultPos = positions?.positions?.find(p => p.symbol === vaultSymbol);
  const vaultMarketValue = vaultPos?.market_value ?? totalVaulted;
  const vaultPnl         = vaultPos?.unrealized_pl ?? 0;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
      {/* Total Equity */}
      <Card className={cn(
        "bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 relative overflow-hidden transition-all duration-500",
        isProfit && "hover:border-green-500/30",
        !isProfit && "hover:border-red-500/30"
      )}>
        {isProfit && <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-green-500/50 to-transparent" />}
        {!isProfit && <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-red-500/50 to-transparent" />}
        <CardContent className="p-4">
          <div className="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-1.5">
            Total Equity
            {Math.abs(pnlPct) > 1 && (
              <motion.span
                animate={{ scale: [1, 1.2, 1] }}
                transition={{ duration: 2, repeat: Infinity }}
                className={cn("text-[9px] font-mono px-1 py-0.5 rounded", isProfit ? "bg-green-500/15 text-green-400" : "bg-red-500/15 text-red-400")}
              >
                {pnl >= 0 ? "+" : ""}{pnlPct.toFixed(2)}%
              </motion.span>
            )}
          </div>
          <RollingCurrency value={data.account.equity} className={cn("text-2xl font-mono font-bold tracking-tight", isProfit ? "text-green-400 text-glow-success-strong" : "text-red-400 text-glow-danger-strong")} />
          <div className={cn("text-xs mt-1.5 font-medium flex items-center gap-1", isProfit ? "text-green-400/70" : "text-red-400/70")}>
            {isProfit ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
            {isProfit ? `+${formatCurrency(pnl)}` : `${formatCurrency(pnl)}`}
          </div>
        </CardContent>
      </Card>

      {/* Available Cash */}
      <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-blue-500/20 transition-all duration-500">
        <CardContent className="p-4">
          <div className="text-xs font-medium text-muted-foreground mb-1.5">Available Cash</div>
          <AnimatedCurrency value={data.account.cash} className="text-2xl font-mono font-bold text-white tracking-tight" />
          <div className="text-xs text-muted-foreground mt-1.5 flex items-center gap-1.5">
            <span className="text-[9px] font-mono text-blue-400/60">{((data.account.cash / data.account.equity) * 100).toFixed(0)}% liquid</span>
          </div>
        </CardContent>
      </Card>

      {/* Buying Power */}
      <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-purple-500/20 transition-all duration-500">
        <CardContent className="p-4">
          <div className="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-1">
            Buying Power
            <Zap className="h-3 w-3 text-purple-400/60" />
          </div>
          <AnimatedCurrency value={data.account.buying_power} className="text-2xl font-mono font-bold text-white tracking-tight" />
          <div className="text-xs text-muted-foreground mt-1.5">With margin</div>
        </CardContent>
      </Card>

      {/* High-Yield Growth Vault */}
      <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-amber-500/25 transition-all duration-500 relative overflow-hidden">
        <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-amber-500/40 to-transparent" />
        <CardContent className="p-4">
          <div className="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-1.5">
            <Vault className="h-3 w-3 text-amber-400/70" />
            Growth Vault
            <span className="text-[9px] font-mono text-amber-400/60 bg-amber-500/10 px-1 rounded">{vaultSymbol}</span>
          </div>
          {isVaultInit ? (
            <>
              <div className={cn(
                "text-2xl font-mono font-bold tracking-tight",
                vaultMarketValue > 0 ? "text-amber-400" : "text-amber-400/40"
              )}>
                {vaultMarketValue > 0 ? formatCurrency(vaultMarketValue) : "$0.00"}
              </div>
              <div className="text-[10px] text-muted-foreground mt-1.5 flex items-center gap-1">
                <ArrowUpRight className="h-3 w-3 text-amber-400/50" />
                {totalSweeps} sweep{totalSweeps !== 1 ? "s" : ""} · HWM ${hwm.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
              </div>
            </>
          ) : (
            <>
              <div className="text-2xl font-mono font-bold text-amber-400/40 tracking-tight">$0.00</div>
              <div className="text-[10px] text-muted-foreground/50 mt-1.5">Awaiting first profit sweep</div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Total Yield Generated */}
      <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-green-500/20 transition-all duration-500 relative overflow-hidden">
        <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-green-500/30 to-transparent" />
        <CardContent className="p-4">
          <div className="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-1.5">
            <Coins className="h-3 w-3 text-green-400/70" />
            Total Yield
          </div>
          {isVaultInit && vaultPos ? (
            <>
              <div className={cn(
                "text-2xl font-mono font-bold tracking-tight",
                vaultPnl > 0 ? "text-green-400 text-glow-success" : vaultPnl < 0 ? "text-red-400" : "text-muted-foreground/60"
              )}>
                {vaultPnl >= 0 ? "+" : ""}{formatCurrency(vaultPnl)}
              </div>
              <div className="text-[10px] text-muted-foreground mt-1.5 flex items-center gap-1">
                <GrowthIcon className="h-3 w-3 text-green-400/50" />
                Unrealised on {vaultSymbol} position
              </div>
            </>
          ) : (
            <>
              <div className="text-2xl font-mono font-bold text-muted-foreground/40 tracking-tight">$0.00</div>
              <div className="text-[10px] text-muted-foreground/50 mt-1.5">
                {isVaultInit ? `No ${vaultSymbol} position yet` : "Awaiting first sweep"}
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ── AI Brain Section ──────────────────────────────────────────────────────────

const NODES = [
  { id: 0, cx: 52,  cy: 46 },
  { id: 1, cx: 78,  cy: 35 },
  { id: 2, cx: 104, cy: 46 },
  { id: 3, cx: 38,  cy: 66 },
  { id: 4, cx: 62,  cy: 61 },
  { id: 5, cx: 98,  cy: 61 },
  { id: 6, cx: 122, cy: 66 },
  { id: 7, cx: 52,  cy: 83 },
  { id: 8, cx: 108, cy: 83 },
  { id: 9, cx: 80,  cy: 102 },
];

const EDGES: [number, number][] = [
  [0,1],[1,2],[0,3],[0,4],[1,4],[1,5],[2,5],[2,6],
  [3,4],[4,5],[5,6],[4,7],[5,8],[7,9],[8,9],[3,7],
];

const PULSE_DELAYS = [0, 0.3, 0.6, 0.9, 0.4, 0.7, 0.2, 0.8, 0.5, 1.0];

function BrainSVG({ thinking }: { thinking: boolean }) {
  const ringRadii = [78, 68, 58];
  return (
    <svg viewBox="0 0 160 130" className="w-full h-full drop-shadow-[0_0_24px_rgba(99,102,241,0.6)]">
      <defs>
        <radialGradient id="brainGrad" cx="50%" cy="50%" r="50%">
          <stop offset="0%"   stopColor="rgba(129,140,248,0.18)" />
          <stop offset="100%" stopColor="rgba(79,70,229,0.04)" />
        </radialGradient>
        <filter id="nodeGlow">
          <feGaussianBlur stdDeviation="2.5" result="blur" />
          <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
        <filter id="lineGlow">
          <feGaussianBlur stdDeviation="1.2" result="blur" />
          <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
      </defs>

      {/* Outer energy rings — opacity only, no r animation */}
      {ringRadii.map((r, i) => (
        <motion.circle key={r} cx={80} cy={65} r={r}
          fill="none" stroke="rgba(99,102,241,0.22)" strokeWidth={i === 0 ? 1.5 : 1}
          animate={{ opacity: [0.15, 0.5, 0.15] }}
          transition={{ duration: 2.4 + i * 0.4, repeat: Infinity, delay: i * 0.5, ease: "easeInOut" }}
        />
      ))}

      {/* Brain outline — right hemisphere */}
      <motion.path
        d="M80 28 C88 22, 108 24, 120 40 C132 56, 130 74, 120 86 C112 96, 96 100, 84 98 L80 96"
        fill="url(#brainGrad)" stroke="rgba(129,140,248,0.55)" strokeWidth="1.5"
        animate={{ opacity: thinking ? [0.6, 1, 0.6] : [0.55, 0.85, 0.55] }}
        transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
      />

      {/* Brain outline — left hemisphere */}
      <motion.path
        d="M80 28 C72 22, 52 24, 40 40 C28 56, 30 74, 40 86 C48 96, 64 100, 76 98 L80 96"
        fill="url(#brainGrad)" stroke="rgba(129,140,248,0.55)" strokeWidth="1.5"
        animate={{ opacity: thinking ? [0.6, 1, 0.6] : [0.55, 0.85, 0.55] }}
        transition={{ duration: 2, repeat: Infinity, delay: 0.5, ease: "easeInOut" }}
      />

      {/* Cerebellum */}
      <motion.path
        d="M68 97 Q80 110, 92 97 Q88 118, 80 121 Q72 118, 68 97 Z"
        fill="url(#brainGrad)" stroke="rgba(129,140,248,0.45)" strokeWidth="1.2"
        animate={{ opacity: [0.4, 0.75, 0.4] }}
        transition={{ duration: 2.5, repeat: Infinity, ease: "easeInOut" }}
      />

      {/* Central fissure */}
      <motion.line x1={80} y1={28} x2={80} y2={96}
        stroke="rgba(99,102,241,0.3)" strokeWidth="1"
        animate={{ opacity: [0.2, 0.5, 0.2] }}
        transition={{ duration: 1.8, repeat: Infinity, ease: "easeInOut" }}
      />

      {/* Synaptic connections */}
      {EDGES.map(([a, b], i) => {
        const na = NODES[a]; const nb = NODES[b];
        return (
          <motion.line key={`e${i}`}
            x1={na.cx} y1={na.cy} x2={nb.cx} y2={nb.cy}
            stroke="rgba(129,140,248,0.4)" strokeWidth="0.8"
            filter="url(#lineGlow)"
            animate={{ opacity: thinking ? [0.15, 0.8, 0.15] : [0.1, 0.5, 0.1] }}
            transition={{ duration: 1.6 + (i % 4) * 0.3, repeat: Infinity,
              delay: (i * 0.12) % 1.5, ease: "easeInOut" }}
          />
        );
      })}

      {/* Neural nodes — halo: animate only opacity, core fixed r */}
      {NODES.map((n, i) => (
        <g key={n.id}>
          <circle cx={n.cx} cy={n.cy} r={5}
            fill="rgba(129,140,248,0.12)" stroke="rgba(129,140,248,0.25)" strokeWidth="1"
          />
          <motion.circle cx={n.cx} cy={n.cy} r={5}
            fill="rgba(129,140,248,0.08)" stroke="rgba(129,140,248,0.3)" strokeWidth="1"
            animate={{ opacity: [0.3, thinking ? 1 : 0.7, 0.3] }}
            transition={{ duration: 1.4 + (i % 3) * 0.3, repeat: Infinity,
              delay: PULSE_DELAYS[i], ease: "easeInOut" }}
          />
          <motion.circle cx={n.cx} cy={n.cy} r={2.5}
            fill="rgba(167,139,250,0.95)" filter="url(#nodeGlow)"
            animate={{ opacity: [0.6, 1, 0.6] }}
            transition={{ duration: 1.2 + (i % 3) * 0.25, repeat: Infinity,
              delay: PULSE_DELAYS[i], ease: "easeInOut" }}
          />
        </g>
      ))}

      {/* Central core — brightest node */}
      <circle cx={80} cy={65} r={4} fill="rgba(167,139,250,0.85)" filter="url(#nodeGlow)" />
      <motion.circle cx={80} cy={65} r={4}
        fill="rgba(167,139,250,0.9)" filter="url(#nodeGlow)"
        animate={{ opacity: [0.7, 1, 0.7] }}
        transition={{ duration: 1.1, repeat: Infinity, ease: "easeInOut" }}
      />

      {/* Thinking mode: extra glow ring around center */}
      {thinking && (
        <motion.circle cx={80} cy={65} r={12}
          fill="none" stroke="rgba(167,139,250,0.4)" strokeWidth="1.5"
          animate={{ opacity: [0.2, 0.8, 0.2] }}
          transition={{ duration: 0.9, repeat: Infinity, ease: "easeInOut" }}
        />
      )}
    </svg>
  );
}

function SpeechBubble({
  commentary, generatedAt, cached, cacheAge, thinking, onRefresh, isRefreshing,
}: {
  commentary: string | undefined;
  generatedAt: string | null | undefined;
  cached: boolean | undefined;
  cacheAge: number | undefined;
  thinking: boolean;
  onRefresh: () => void;
  isRefreshing: boolean;
}) {
  const ageMin = cacheAge != null ? Math.round(cacheAge / 60) : null;

  const textRef = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    if (!thinking && textRef.current) {
      textRef.current.style.animation = "none";
      void textRef.current.offsetHeight;
      textRef.current.style.animation = "";
    }
  }, [commentary, thinking]);

  return (
    <div className="relative flex-1 min-w-0">
      {/* Arrow pointing left toward the brain */}
      <div className="absolute left-0 top-1/2 -translate-x-3 -translate-y-1/2 w-3 h-4 overflow-hidden">
        <div className="absolute inset-0 border-r border-b border-indigo-500/40 bg-slate-900 rotate-[135deg] origin-top-right scale-75" />
      </div>

      <div className="relative rounded-2xl border border-indigo-500/30 bg-slate-900/80 backdrop-blur-sm shadow-[0_0_30px_rgba(99,102,241,0.08)] overflow-hidden">
        {/* Top accent line */}
        <div className="h-px bg-gradient-to-r from-indigo-500/60 via-violet-400/40 to-transparent" />

        <div className="px-5 py-4">
          <div className="flex items-center gap-2 mb-3">
            <motion.div
              animate={{ scale: [1, 1.15, 1], opacity: [0.7, 1, 0.7] }}
              transition={{ duration: 1.8, repeat: Infinity, ease: "easeInOut" }}
            >
              <Sparkles className="h-3.5 w-3.5 text-violet-400" />
            </motion.div>
            <span className="text-[10px] uppercase font-semibold tracking-wider text-violet-400">
              AI Brain Thoughts
            </span>
            {cached && ageMin != null && (
              <span className="ml-auto text-[9px] text-muted-foreground/50">
                cached · {ageMin === 0 ? "just now" : `${ageMin}m ago`}
              </span>
            )}
          </div>

          {/* Commentary text */}
          <div className="min-h-[52px] flex items-start">
            {thinking ? (
              <div className="flex items-center gap-2 mt-1">
                {[0, 1, 2].map(i => (
                  <motion.div key={i}
                    className="w-1.5 h-1.5 rounded-full bg-indigo-400"
                    animate={{ y: [0, -5, 0], opacity: [0.4, 1, 0.4] }}
                    transition={{ duration: 0.8, repeat: Infinity, delay: i * 0.18, ease: "easeInOut" }}
                  />
                ))}
                <span className="text-[11px] text-muted-foreground ml-1">Thinking…</span>
              </div>
            ) : commentary ? (
              <p ref={textRef} className="text-[11px] leading-relaxed text-slate-300 font-light line-clamp-5">
                {commentary}
              </p>
            ) : (
              <p className="text-[11px] text-muted-foreground/50 italic">
                Auto-refreshing every 90s — click Refresh to generate now.
              </p>
            )}
          </div>

          {/* Footer */}
          <div className="mt-3 flex items-center justify-between">
            {generatedAt && !thinking ? (
              <span className="text-[9px] text-muted-foreground/40">
                Generated {new Date(generatedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </span>
            ) : <span />}
            <button
              onClick={onRefresh}
              disabled={isRefreshing || thinking}
              className={cn(
                "flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-medium transition-all",
                "border border-indigo-500/30 text-indigo-400 hover:bg-indigo-500/10 hover:border-indigo-400/50",
                "disabled:opacity-40 disabled:cursor-not-allowed"
              )}
            >
              <RefreshCw className={cn("h-3 w-3", (isRefreshing || thinking) && "animate-spin")} />
              {isRefreshing ? "Regenerating…" : "Refresh"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

const REGIME_META: Record<string, { color: string; bg: string; border: string; label: string }> = {
  Bull:    { color: "text-green-400",  bg: "bg-green-500/15",  border: "border-green-500/40",  label: "BULL" },
  Bear:    { color: "text-red-400",    bg: "bg-red-500/15",    border: "border-red-500/40",    label: "BEAR" },
  Sideways:{ color: "text-amber-400",  bg: "bg-amber-500/15",  border: "border-amber-500/40",  label: "SIDEWAYS" },
  Crypto:  { color: "text-purple-400", bg: "bg-purple-500/15", border: "border-purple-500/40", label: "CRYPTO" },
};

const ASSET_CLASS_COLORS: Record<string, string> = {
  equity:      "#3b82f6",
  safe_haven:  "#f59e0b",
  crypto_spot: "#a855f7",
  cash:        "#22c55e",
};

function RegimeAllocationPanel({ regime, allocation }: {
  regime: string | null | undefined;
  allocation: AllocationPlan["allocation"];
}) {
  if (!allocation || allocation.length === 0) return null;
  const meta = regime ? (REGIME_META[regime] ?? REGIME_META["Bull"]) : null;

  return (
    <div className="relative mt-4 pt-4 border-t border-white/5">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-[9px] uppercase font-semibold tracking-wider text-muted-foreground/70">
          Macro Regime
        </span>
        {meta && regime && (
          <motion.span
            key={regime}
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            className={cn("text-[10px] font-mono font-bold px-2 py-0.5 rounded border", meta.color, meta.bg, meta.border)}
          >
            {meta.label}
          </motion.span>
        )}
        <span className="ml-auto text-[9px] uppercase font-semibold tracking-wider text-muted-foreground/70">
          Target Allocation
        </span>
      </div>
      <div className="grid gap-1.5">
        {allocation.map((slot, idx) => {
          const pct = Math.round(slot.kelly_fraction * 100);
          const isCrypto = slot.ticker.includes("/");
          const isCash = slot.ticker === "SGOV";
          const barColor = ASSET_CLASS_COLORS[slot.asset_class] ?? "#6366f1";
          return (
            <motion.div
              key={slot.slot}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: idx * 0.05 }}
              className="flex items-center gap-2"
            >
              <span className={cn("font-mono text-xs font-bold w-16 flex-shrink-0", isCrypto ? "text-purple-300" : isCash ? "text-green-400/70" : "text-white")}>
                {slot.ticker}
              </span>
              <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${pct}%` }}
                  transition={{ duration: 0.6, delay: idx * 0.07, ease: "easeOut" }}
                  className="h-full rounded-full"
                  style={{ backgroundColor: barColor }}
                />
              </div>
              <span className="text-[10px] font-mono text-muted-foreground w-7 text-right flex-shrink-0">
                {pct}%
              </span>
              <span className={cn(
                "text-[9px] font-mono w-6 text-right flex-shrink-0",
                slot.conviction_score >= 0.8 ? "text-green-400" : "text-amber-400"
              )}>
                {Math.round(slot.conviction_score * 100)}
              </span>
            </motion.div>
          );
        })}
      </div>
      <div className="flex items-center gap-3 mt-2">
        {Object.entries(ASSET_CLASS_COLORS).map(([cls, color]) => (
          <span key={cls} className="flex items-center gap-1 text-[8px] text-muted-foreground/50">
            <span className="inline-block w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
            {cls.replace("_", " ")}
          </span>
        ))}
        <span className="ml-auto text-[8px] text-muted-foreground/40">conv%</span>
      </div>
    </div>
  );
}

// ── Brain Insights Modal ──────────────────────────────────────────────────────

function BrainInsightsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { data: commentary } = useAICommentary();
  const { data: alloc } = useLatestAllocation();
  const { data: winData } = useRagWins();
  const { data: lossData } = useRagLosses();

  if (!open) return null;

  const regime = alloc?.regime;
  const allocation = alloc?.allocation ?? [];
  const topAlloc = allocation.filter((s: any) => s.ticker !== "SGOV").slice(0, 5);
  const topWins = winData?.wins?.slice(0, 3) ?? [];
  const topLosses = lossData?.losses?.slice(0, 3) ?? [];
  const regimeMeta = regime ? (REGIME_META[regime] ?? REGIME_META["Bull"]) : null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 12 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95, y: 12 }}
        transition={{ duration: 0.2 }}
        className="relative w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-2xl border border-indigo-500/30 bg-slate-950 shadow-[0_0_80px_rgba(99,102,241,0.12)] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top accent */}
        <div className="h-px bg-gradient-to-r from-indigo-500/60 via-violet-400/40 to-transparent" />

        {/* Header */}
        <div className="flex items-center gap-3 px-6 py-4 border-b border-white/5">
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <Brain className="h-4 w-4 text-indigo-400 flex-shrink-0" />
            <span className="text-sm font-semibold text-white">AI Brain — Strategy Intelligence</span>
            {regimeMeta && regime && (
              <span className={cn("text-[10px] font-mono font-bold px-2 py-0.5 rounded border ml-1", regimeMeta.color, regimeMeta.bg, regimeMeta.border)}>
                {regimeMeta.label}
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="flex-shrink-0 p-1 rounded-lg hover:bg-white/8 text-muted-foreground hover:text-white transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="px-6 py-5 space-y-5">
          {/* Strategy Summary */}
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <Sparkles className="h-3 w-3 text-indigo-400" />
              <span className="text-[10px] uppercase font-semibold tracking-wider text-indigo-400/80">Current Strategy</span>
            </div>
            {commentary?.commentary ? (
              <p className="text-sm text-white/80 leading-relaxed border-l-2 border-indigo-500/40 pl-3">
                {commentary.commentary}
              </p>
            ) : (
              <p className="text-xs text-muted-foreground italic">No commentary available yet — the AI will generate one on the next cycle.</p>
            )}
          </div>

          {/* Target Allocations */}
          {topAlloc.length > 0 && (
            <div>
              <div className="flex items-center gap-1.5 mb-2">
                <BarChart3 className="h-3 w-3 text-violet-400" />
                <span className="text-[10px] uppercase font-semibold tracking-wider text-violet-400/80">Target Positions</span>
              </div>
              <div className="space-y-1.5">
                {topAlloc.map((slot: any) => {
                  const pct = Math.round(slot.kelly_fraction * 100);
                  const conv = Math.round(slot.conviction_score * 100);
                  const barColor = ASSET_CLASS_COLORS[slot.asset_class] ?? "#6366f1";
                  const isCrypto = slot.ticker.includes("/");
                  return (
                    <div key={slot.slot} className="flex items-center gap-3">
                      <span className={cn("font-mono text-xs font-bold w-16 flex-shrink-0", isCrypto ? "text-purple-300" : "text-white")}>
                        {slot.ticker}
                      </span>
                      <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                        <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: barColor }} />
                      </div>
                      <span className="text-[10px] font-mono text-muted-foreground w-8 text-right">{pct}%</span>
                      <span className={cn("text-[9px] font-mono w-8 text-right", conv >= 80 ? "text-green-400" : "text-amber-400")}>
                        {conv}cv
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Learnings */}
          {(topWins.length > 0 || topLosses.length > 0) && (
            <div>
              <div className="flex items-center gap-1.5 mb-2">
                <Activity className="h-3 w-3 text-primary" />
                <span className="text-[10px] uppercase font-semibold tracking-wider text-muted-foreground/70">What the AI Has Learned</span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {topWins.length > 0 && (
                  <div className="rounded-xl border border-green-500/20 bg-green-500/5 p-3 space-y-2">
                    <span className="text-[9px] uppercase font-semibold text-green-400 tracking-wider flex items-center gap-1">
                      <TrendingUp className="h-3 w-3" /> What Worked
                    </span>
                    {topWins.map((win: any) => (
                      <div key={win.trade_id} className="border-l-2 border-green-500/30 pl-2">
                        <div className="flex items-center gap-1.5 mb-0.5">
                          <span className="font-mono text-xs font-bold text-white">{win.ticker}</span>
                          <span className="text-[9px] text-green-400">+{win.pnl_percentage?.toFixed(1)}%</span>
                        </div>
                        <p className="text-[10px] text-muted-foreground leading-snug line-clamp-2">
                          {win.original_thesis}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
                {topLosses.length > 0 && (
                  <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-3 space-y-2">
                    <span className="text-[9px] uppercase font-semibold text-red-400 tracking-wider flex items-center gap-1">
                      <TrendingDown className="h-3 w-3" /> What Failed
                    </span>
                    {topLosses.map((loss: any) => (
                      <div key={loss.trade_id} className="border-l-2 border-red-500/30 pl-2">
                        <div className="flex items-center gap-1.5 mb-0.5">
                          <span className="font-mono text-xs font-bold text-white">{loss.ticker}</span>
                          <span className="text-[9px] text-red-400">{loss.pnl_percentage?.toFixed(1)}%</span>
                        </div>
                        <p className="text-[10px] text-muted-foreground leading-snug line-clamp-2">
                          {loss.original_thesis}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {topWins.length === 0 && topLosses.length === 0 && topAlloc.length === 0 && !commentary?.commentary && (
            <div className="text-center py-6 text-muted-foreground text-xs italic">
              The brain is still learning — check back after the first trading cycle completes.
            </div>
          )}
        </div>

        {/* Footer hint */}
        <div className="px-6 pb-4 text-[9px] text-muted-foreground/40 text-center">
          Model: Llama 3.3 70B · Groq · Updated every 90s
        </div>
      </motion.div>
    </div>
  );
}

function AIBrainSection() {
  const { data, isLoading } = useAICommentary();
  const { mutate: refresh, isPending: isRefreshing } = useRefreshCommentary();
  const { data: alloc } = useLatestAllocation();
  const [showInsights, setShowInsights] = useState(false);

  const thinking = isLoading || isRefreshing;

  // Auto-refresh commentary every 90 seconds when not already thinking
  useEffect(() => {
    const id = setInterval(() => {
      if (!isRefreshing && !isLoading) {
        refresh();
      }
    }, 90_000);
    return () => clearInterval(id);
  }, [isRefreshing, isLoading, refresh]);

  return (
    <>
      <AnimatePresence>
        {showInsights && <BrainInsightsModal open={showInsights} onClose={() => setShowInsights(false)} />}
      </AnimatePresence>

      <div className="relative rounded-2xl border border-indigo-500/20 bg-gradient-to-br from-slate-950/90 to-indigo-950/20 p-5 shadow-[0_0_60px_rgba(99,102,241,0.06)] overflow-hidden">
        {/* Background glow */}
        <div className="absolute top-0 left-0 w-48 h-48 bg-indigo-500/5 rounded-full blur-3xl -translate-x-1/4 -translate-y-1/4 pointer-events-none" />
        <div className="absolute bottom-0 right-0 w-64 h-64 bg-violet-500/4 rounded-full blur-3xl translate-x-1/4 translate-y-1/4 pointer-events-none" />

        <div className="relative flex items-center gap-2 mb-4">
          <Brain className="h-3.5 w-3.5 text-indigo-400" />
          <span className="text-[10px] uppercase font-semibold tracking-wider text-indigo-400/80">
            Learning Intelligence
          </span>
          {/* Live auto-refresh indicator */}
          <span className="ml-auto flex items-center gap-1 text-[9px] text-indigo-400/40">
            <motion.span
              className="inline-block w-1.5 h-1.5 rounded-full bg-indigo-400"
              animate={{ opacity: [0.3, 1, 0.3] }}
              transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
            />
            auto-refresh 90s
          </span>
        </div>

        <div className="relative flex items-start gap-5">
          {/* Brain SVG — clickable to open insights */}
          <motion.div
            className="flex-shrink-0 w-52 h-44 cursor-pointer relative group"
            animate={{ y: [0, -6, 0, 4, 0], x: [0, 3, 0, -3, 0] }}
            transition={{ duration: 7, repeat: Infinity, ease: "easeInOut" }}
            onClick={() => setShowInsights(true)}
            title="Click to view AI strategy & learnings"
          >
            <BrainSVG thinking={thinking} />
            {/* Hover hint */}
            <div className="absolute inset-0 flex items-end justify-center pb-1 opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none">
              <span className="text-[9px] font-semibold text-indigo-300/80 bg-slate-950/80 rounded-full px-2 py-0.5 border border-indigo-500/20 backdrop-blur-sm">
                tap to inspect
              </span>
            </div>
          </motion.div>

          {/* Speech bubble */}
          <SpeechBubble
            commentary={data?.commentary}
            generatedAt={data?.generated_at}
            cached={data?.cached}
            cacheAge={data?.cache_age_seconds}
            thinking={thinking}
            onRefresh={() => refresh()}
            isRefreshing={isRefreshing}
          />
        </div>

        {/* Regime + allocation breakdown */}
        <RegimeAllocationPanel regime={alloc?.regime} allocation={alloc?.allocation ?? null} />
      </div>
    </>
  );
}

// ── Auditor Agent Section ────────────────────────────────────────────────────

const AUDIT_SCAN_LINES = [
  { y: 20, delay: 0 },
  { y: 45, delay: 0.6 },
  { y: 70, delay: 1.2 },
  { y: 95, delay: 1.8 },
];

function AuditorShieldSVG({ scanning }: { scanning: boolean }) {
  return (
    <svg viewBox="0 0 140 150" className="w-full h-full drop-shadow-[0_0_24px_rgba(234,179,8,0.5)]">
      <defs>
        <radialGradient id="shieldGrad" cx="50%" cy="40%" r="55%">
          <stop offset="0%" stopColor="rgba(234,179,8,0.15)" />
          <stop offset="100%" stopColor="rgba(161,98,7,0.03)" />
        </radialGradient>
        <linearGradient id="shieldStroke" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="rgba(250,204,21,0.7)" />
          <stop offset="100%" stopColor="rgba(161,98,7,0.3)" />
        </linearGradient>
        <filter id="shieldGlow">
          <feGaussianBlur stdDeviation="2.5" result="blur" />
          <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
        <filter id="scanGlow">
          <feGaussianBlur stdDeviation="1.5" result="blur" />
          <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
        <clipPath id="shieldClip">
          <path d="M70 12 L120 35 L120 80 Q120 120 70 140 Q20 120 20 80 L20 35 Z" />
        </clipPath>
      </defs>

      {/* Outer energy rings */}
      {[72, 62, 52].map((r, i) => (
        <motion.circle key={r} cx={70} cy={75} r={r}
          fill="none" stroke="rgba(234,179,8,0.18)" strokeWidth={i === 0 ? 1.2 : 0.8}
          animate={{ opacity: [0.1, 0.4, 0.1] }}
          transition={{ duration: 2.8 + i * 0.5, repeat: Infinity, delay: i * 0.6, ease: "easeInOut" }}
        />
      ))}

      {/* Shield body */}
      <motion.path
        d="M70 12 L120 35 L120 80 Q120 120 70 140 Q20 120 20 80 L20 35 Z"
        fill="url(#shieldGrad)" stroke="url(#shieldStroke)" strokeWidth="2"
        animate={{ opacity: scanning ? [0.7, 1, 0.7] : [0.6, 0.85, 0.6] }}
        transition={{ duration: 2.2, repeat: Infinity, ease: "easeInOut" }}
      />

      {/* Inner shield border */}
      <motion.path
        d="M70 22 L112 42 L112 78 Q112 112 70 130 Q28 112 28 78 L28 42 Z"
        fill="none" stroke="rgba(234,179,8,0.25)" strokeWidth="1"
        animate={{ opacity: [0.2, 0.5, 0.2] }}
        transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
      />

      {/* Scanning lines (animate inside shield) */}
      <g clipPath="url(#shieldClip)">
        {AUDIT_SCAN_LINES.map((line, i) => (
          <motion.line key={i}
            x1={20} y1={line.y} x2={120} y2={line.y}
            stroke="rgba(250,204,21,0.35)" strokeWidth="1" filter="url(#scanGlow)"
            animate={scanning ? {
              y1: [line.y, line.y + 100, line.y],
              y2: [line.y, line.y + 100, line.y],
              opacity: [0, 0.7, 0],
            } : { opacity: [0.05, 0.2, 0.05] }}
            transition={{ duration: 3, repeat: Infinity, delay: line.delay, ease: "easeInOut" }}
          />
        ))}
      </g>

      {/* Central eye */}
      <motion.ellipse cx={70} cy={70} rx={16} ry={10}
        fill="none" stroke="rgba(250,204,21,0.6)" strokeWidth="1.5"
        filter="url(#shieldGlow)"
        animate={{ opacity: [0.5, 1, 0.5] }}
        transition={{ duration: 1.8, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.circle cx={70} cy={70} r={4}
        fill="rgba(250,204,21,0.9)" filter="url(#shieldGlow)"
        animate={{ opacity: [0.7, 1, 0.7] }}
        transition={{ duration: 1.2, repeat: Infinity, ease: "easeInOut" }}
      />
      {scanning && (
        <motion.circle cx={70} cy={70} r={8}
          fill="none" stroke="rgba(250,204,21,0.4)" strokeWidth="1.2"
          animate={{ opacity: [0.2, 0.7, 0.2], r: [8, 12, 8] }}
          transition={{ duration: 1.1, repeat: Infinity, ease: "easeInOut" }}
        />
      )}

      {/* Check marks on shield */}
      <motion.path d="M55 90 L65 100 L85 80" fill="none" stroke="rgba(74,222,128,0.5)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
        animate={{ opacity: scanning ? [0.3, 0.8, 0.3] : [0.4, 0.6, 0.4] }}
        transition={{ duration: 2.5, repeat: Infinity, ease: "easeInOut" }}
      />
    </svg>
  );
}

const SEVERITY_CONFIG: Record<string, { icon: typeof CheckCircle2; color: string; bg: string; border: string }> = {
  INFO:    { icon: CheckCircle2, color: "text-green-400",  bg: "bg-green-500/10",  border: "border-green-500/30" },
  WARNING: { icon: AlertTriangle, color: "text-amber-400", bg: "bg-amber-500/10",  border: "border-amber-500/30" },
  ALERT:   { icon: AlertOctagon, color: "text-red-400",    bg: "bg-red-500/10",    border: "border-red-500/30" },
  HOLD:    { icon: Lock,         color: "text-orange-400", bg: "bg-orange-500/10", border: "border-orange-500/30" },
};

const OVERALL_CONFIG: Record<string, { label: string; color: string; bg: string; border: string }> = {
  ALL_CLEAR:          { label: "ALL CLEAR",    color: "text-green-400",  bg: "bg-green-500/15",  border: "border-green-500/40" },
  REVIEW_RECOMMENDED: { label: "REVIEW",       color: "text-amber-400",  bg: "bg-amber-500/15",  border: "border-amber-500/40" },
  ACTION_REQUIRED:    { label: "ACTION REQ",   color: "text-red-400",    bg: "bg-red-500/15",    border: "border-red-500/40" },
  never_run:          { label: "STANDBY",      color: "text-slate-400",  bg: "bg-slate-500/15",  border: "border-slate-500/40" },
};

function AuditorDialogueBubble({
  report, scanning, onRunAudit, isTriggering,
}: {
  report: AuditFinding[] | null;
  scanning: boolean;
  onRunAudit: () => void;
  isTriggering: boolean;
}) {
  return (
    <div className="relative flex-1 min-w-0">
      <div className="absolute left-0 top-1/2 -translate-x-3 -translate-y-1/2 w-3 h-4 overflow-hidden">
        <div className="absolute inset-0 border-r border-b border-amber-500/40 bg-slate-900 rotate-[135deg] origin-top-right scale-75" />
      </div>

      <div className="relative rounded-2xl border border-amber-500/30 bg-slate-900/80 backdrop-blur-sm shadow-[0_0_30px_rgba(234,179,8,0.08)] overflow-hidden">
        <div className="h-px bg-gradient-to-r from-amber-500/60 via-yellow-400/40 to-transparent" />

        <div className="px-5 py-4">
          <div className="flex items-center gap-2 mb-3">
            <motion.div
              animate={{ scale: [1, 1.15, 1], opacity: [0.7, 1, 0.7] }}
              transition={{ duration: 1.8, repeat: Infinity, ease: "easeInOut" }}
            >
              <Eye className="h-3.5 w-3.5 text-amber-400" />
            </motion.div>
            <span className="text-[10px] uppercase font-semibold tracking-wider text-amber-400">
              Audit Findings
            </span>
            <span className="ml-auto text-[9px] text-muted-foreground/50">
              daily 4:30PM ET
            </span>
          </div>

          <div className="min-h-[52px]">
            {scanning ? (
              <div className="flex items-center gap-2 mt-1">
                {[0, 1, 2].map(i => (
                  <motion.div key={i}
                    className="w-1.5 h-1.5 rounded-full bg-amber-400"
                    animate={{ y: [0, -5, 0], opacity: [0.4, 1, 0.4] }}
                    transition={{ duration: 0.8, repeat: Infinity, delay: i * 0.18, ease: "easeInOut" }}
                  />
                ))}
                <span className="text-[11px] text-muted-foreground ml-1">Running audit…</span>
              </div>
            ) : report && report.length > 0 ? (
              <div className="space-y-1.5">
                {report.map((f, i) => {
                  const cfg = SEVERITY_CONFIG[f.severity] || SEVERITY_CONFIG.INFO;
                  const Icon = cfg.icon;
                  return (
                    <motion.div key={f.check}
                      initial={{ opacity: 0, x: -4 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: i * 0.06 }}
                      className="flex items-start gap-2"
                    >
                      <Icon className={cn("h-3 w-3 mt-0.5 flex-shrink-0", cfg.color)} />
                      <span className="text-[10px] leading-snug text-slate-300">
                        <span className="font-semibold">{f.check.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}:</span>{" "}
                        {f.passed ? "Pass" : f.message.length > 60 ? f.message.slice(0, 60) + "…" : f.message}
                      </span>
                    </motion.div>
                  );
                })}
              </div>
            ) : (
              <p className="text-[11px] text-muted-foreground/50 italic">
                No audit run yet — click Run Audit to generate the first report.
              </p>
            )}
          </div>

          <div className="mt-3 flex items-center justify-between">
            {report ? (
              <span className="text-[9px] text-muted-foreground/40">
                {report.filter(f => f.passed).length}/{report.length} checks passed
              </span>
            ) : <span />}
            <button
              onClick={onRunAudit}
              disabled={isTriggering || scanning}
              className={cn(
                "flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-medium transition-all",
                "border border-amber-500/30 text-amber-400 hover:bg-amber-500/10 hover:border-amber-400/50",
                "disabled:opacity-40 disabled:cursor-not-allowed"
              )}
            >
              <Play className={cn("h-3 w-3", (isTriggering || scanning) && "animate-spin")} />
              {isTriggering ? "Triggering…" : "Run Audit"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function AuditorInsightsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { data: auditorData } = useAuditorReport();
  const report = auditorData?.report;
  if (!open) return null;

  const findings = report?.findings ?? [];
  const recommendations = report?.recommendations ?? [];
  const overallMeta = report?.overall ? OVERALL_CONFIG[report.overall] ?? OVERALL_CONFIG.never_run : OVERALL_CONFIG.never_run;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4" onClick={onClose}>
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 12 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95, y: 12 }}
        transition={{ duration: 0.2 }}
        className="relative w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-2xl border border-amber-500/30 bg-slate-950 shadow-[0_0_80px_rgba(234,179,8,0.12)] overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        <div className="h-px bg-gradient-to-r from-amber-500/60 via-yellow-400/40 to-transparent" />

        <div className="flex items-center gap-3 px-6 py-4 border-b border-white/5">
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <Shield className="h-4 w-4 text-amber-400 flex-shrink-0" />
            <span className="text-sm font-semibold text-white">Auditor Agent — HITL Supervisor</span>
            <span className={cn("text-[10px] font-mono font-bold px-2 py-0.5 rounded border ml-1", overallMeta.color, overallMeta.bg, overallMeta.border)}>
              {overallMeta.label}
            </span>
          </div>
          <button onClick={onClose} className="flex-shrink-0 p-1 rounded-lg hover:bg-white/8 text-muted-foreground hover:text-white transition-colors">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="px-6 py-5 space-y-5">
          {report?.run_at && (
            <div className="text-[10px] text-muted-foreground/50">
              Last run: {new Date(report.run_at).toLocaleString()} · {report.total_checks} checks · {report.failed_checks} failed · {report.alert_count} alerts
            </div>
          )}

          {findings.length > 0 ? findings.map((f, i) => {
            const cfg = SEVERITY_CONFIG[f.severity] || SEVERITY_CONFIG.INFO;
            const Icon = cfg.icon;
            return (
              <motion.div key={f.check}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05 }}
                className={cn("rounded-xl border p-4", cfg.border, cfg.bg)}
              >
                <div className="flex items-center gap-2 mb-2">
                  <Icon className={cn("h-4 w-4", cfg.color)} />
                  <span className={cn("text-xs font-bold uppercase tracking-wider", cfg.color)}>
                    {f.check.replace(/_/g, " ")}
                  </span>
                  <span className={cn("ml-auto text-[10px] font-mono font-bold px-1.5 py-0.5 rounded", f.passed ? "text-green-400 bg-green-500/10" : "text-red-400 bg-red-500/10")}>
                    {f.passed ? "PASS" : "FAIL"}
                  </span>
                </div>
                <p className="text-sm text-white/80 leading-relaxed">{f.message}</p>
                {f.details?.flags && Array.isArray(f.details.flags) && f.details.flags.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {f.details.flags.map((flag: string, fi: number) => (
                      <div key={fi} className="flex items-start gap-1.5 text-[10px] text-white/60">
                        <AlertTriangle className="h-3 w-3 mt-0.5 flex-shrink-0 text-amber-400/70" />
                        <span>{flag}</span>
                      </div>
                    ))}
                  </div>
                )}
                {f.details?.holds && Array.isArray(f.details.holds) && f.details.holds.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {f.details.holds.map((hold: any, hi: number) => (
                      <div key={hi} className="flex items-start gap-1.5 text-[10px] text-white/60">
                        <Lock className="h-3 w-3 mt-0.5 flex-shrink-0 text-orange-400/70" />
                        <span>{hold.ticker}: blocked by {hold.blocking_ticker} — {hold.reason}</span>
                      </div>
                    ))}
                  </div>
                )}
              </motion.div>
            );
          }) : (
            <p className="text-sm text-muted-foreground italic">No audit has been run yet.</p>
          )}

          {recommendations.length > 0 && (
            <div>
              <div className="flex items-center gap-1.5 mb-3">
                <Lightbulb className="h-3.5 w-3.5 text-yellow-400" />
                <span className="text-[10px] uppercase font-semibold tracking-wider text-yellow-400/80">Prompt Engineering Recommendations</span>
              </div>
              <div className="space-y-2">
                {recommendations.map((rec, i) => (
                  <div key={i} className="flex items-start gap-2 rounded-lg border border-yellow-500/15 bg-yellow-500/5 p-3">
                    <span className="text-[10px] font-mono text-yellow-400/60 flex-shrink-0 mt-0.5">{i + 1}.</span>
                    <p className="text-[11px] text-white/70 leading-relaxed">{rec}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </motion.div>
    </div>
  );
}

function AuditorAgentSection() {
  const { data: auditorData } = useAuditorReport();
  const { mutate: triggerAudit, isPending: isTriggering } = useTriggerAudit();
  const [showInsights, setShowInsights] = useState(false);

  const report  = auditorData?.report;
  const overall = report?.overall ?? "never_run";
  const findings = report?.findings ?? null;
  const scanning = isTriggering;
  const overallMeta = OVERALL_CONFIG[overall] ?? OVERALL_CONFIG.never_run;

  return (
    <>
      <AnimatePresence>
        {showInsights && <AuditorInsightsModal open={showInsights} onClose={() => setShowInsights(false)} />}
      </AnimatePresence>

      <div className="relative rounded-2xl border border-amber-500/20 bg-gradient-to-br from-slate-950/90 to-amber-950/15 p-5 shadow-[0_0_60px_rgba(234,179,8,0.06)] overflow-hidden">
        <div className="absolute top-0 left-0 w-48 h-48 bg-amber-500/5 rounded-full blur-3xl -translate-x-1/4 -translate-y-1/4 pointer-events-none" />
        <div className="absolute bottom-0 right-0 w-64 h-64 bg-yellow-500/3 rounded-full blur-3xl translate-x-1/4 translate-y-1/4 pointer-events-none" />

        <div className="relative flex items-center gap-2 mb-4">
          <Shield className="h-3.5 w-3.5 text-amber-400" />
          <span className="text-[10px] uppercase font-semibold tracking-wider text-amber-400/80">
            HITL Auditor
          </span>
          <motion.span
            key={overall}
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            className={cn("text-[9px] font-mono font-bold px-1.5 py-0.5 rounded border", overallMeta.color, overallMeta.bg, overallMeta.border)}
          >
            {overallMeta.label}
          </motion.span>
          <span className="ml-auto flex items-center gap-1 text-[9px] text-amber-400/40">
            <motion.span
              className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400"
              animate={{ opacity: [0.3, 1, 0.3] }}
              transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
            />
            {report?.run_at ? `last: ${new Date(report.run_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : "awaiting first run"}
          </span>
        </div>

        <div className="relative flex items-start gap-5">
          <motion.div
            className="flex-shrink-0 w-44 h-44 cursor-pointer relative group"
            animate={{ y: [0, -4, 0, 3, 0], x: [0, 2, 0, -2, 0] }}
            transition={{ duration: 8, repeat: Infinity, ease: "easeInOut" }}
            onClick={() => setShowInsights(true)}
            title="Click to view full audit details"
          >
            <AuditorShieldSVG scanning={scanning} />
            <div className="absolute inset-0 flex items-end justify-center pb-1 opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none">
              <span className="text-[9px] font-semibold text-amber-300/80 bg-slate-950/80 rounded-full px-2 py-0.5 border border-amber-500/20 backdrop-blur-sm">
                tap to inspect
              </span>
            </div>
          </motion.div>

          <AuditorDialogueBubble
            report={findings}
            scanning={scanning}
            onRunAudit={() => triggerAudit()}
            isTriggering={isTriggering}
          />
        </div>

        {report && report.recommendations && report.recommendations.length > 0 && (
          <div className="relative mt-4 pt-4 border-t border-white/5">
            <div className="flex items-center gap-2 mb-2">
              <Lightbulb className="h-3 w-3 text-yellow-400/70" />
              <span className="text-[9px] uppercase font-semibold tracking-wider text-muted-foreground/70">
                Prompt Tweaks
              </span>
            </div>
            <div className="space-y-1">
              {report.recommendations.slice(0, 2).map((rec, i) => (
                <p key={i} className="text-[10px] text-slate-400 leading-snug line-clamp-2">
                  {rec}
                </p>
              ))}
            </div>
          </div>
        )}
      </div>
    </>
  );
}

// ── Live Activity Ticker ──────────────────────────────────────────────────────

function ActivityTicker() {
  const { data: journal } = useJournal();
  const { data: positions } = useLivePositions();

  const items = useMemo(() => {
    const entries: Array<{ key: string; text: string; color: string }> = [];
    if (positions?.positions) {
      for (const p of positions.positions) {
        const pct = (p.unrealized_plpc * 100).toFixed(2);
        entries.push({
          key: `pos-${p.symbol}`,
          text: `${p.symbol} ${p.unrealized_pl >= 0 ? "+" : ""}${pct}%`,
          color: p.unrealized_pl >= 0 ? "text-green-400" : "text-red-400",
        });
      }
    }
    if (journal?.trades) {
      const recent = journal.trades.slice(0, 8);
      for (const t of recent) {
        if (t.status === "Active") continue;
        const prefix = t.status === "Closed_Win" ? "WIN" : "LOSS";
        entries.push({
          key: `j-${t.trade_id}`,
          text: `${prefix} ${t.ticker} ${t.pnl_percentage >= 0 ? "+" : ""}${t.pnl_percentage.toFixed(2)}%`,
          color: t.status === "Closed_Win" ? "text-green-400" : "text-red-400",
        });
      }
    }
    return entries;
  }, [journal, positions]);

  if (items.length === 0) return null;

  const doubled = [...items, ...items];

  return (
    <div className="w-full overflow-hidden bg-slate-950/60 border-b border-white/5 h-7 flex items-center relative">
      <div className="absolute left-0 top-0 bottom-0 w-12 bg-gradient-to-r from-slate-950 to-transparent z-10 pointer-events-none" />
      <div className="absolute right-0 top-0 bottom-0 w-12 bg-gradient-to-l from-slate-950 to-transparent z-10 pointer-events-none" />
      <div className="ticker-animate flex items-center gap-6 whitespace-nowrap">
        {doubled.map((item, i) => (
          <span key={`${item.key}-${i}`} className={cn("text-[10px] font-mono tracking-wide flex items-center gap-1.5", item.color)}>
            <span className="text-white/20">|</span>
            {item.text}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── Best Trade Hero ──────────────────────────────────────────────────────────

function BestTradeHero() {
  const { data: winData } = useRagWins();
  const { data: lossData } = useRagLosses();

  const bestWin = useMemo(() => {
    if (!winData?.wins.length) return null;
    return winData.wins.reduce((best, w) => w.pnl_percentage > best.pnl_percentage ? w : best);
  }, [winData]);

  const worstLoss = useMemo(() => {
    if (!lossData?.losses.length) return null;
    return lossData.losses.reduce((worst, l) => l.pnl_percentage < worst.pnl_percentage ? l : worst);
  }, [lossData]);

  if (!bestWin && !worstLoss) return null;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {bestWin && (
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.5 }}
          className="hero-win-glow rounded-xl border border-green-500/20 bg-gradient-to-br from-green-500/5 to-slate-950 p-4 relative overflow-hidden"
        >
          <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-green-400/60 to-transparent" />
          <div className="absolute -top-6 -right-6 w-24 h-24 bg-green-500/10 rounded-full blur-2xl pointer-events-none" />
          <div className="flex items-center gap-2 mb-2">
            <motion.div animate={{ rotate: [0, 10, -10, 0] }} transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}>
              <Trophy className="h-4 w-4 text-yellow-400" />
            </motion.div>
            <span className="text-[10px] uppercase font-semibold tracking-wider text-green-400">Best Win</span>
            <span className="text-[10px] text-muted-foreground/50 ml-auto">{bestWin.date}</span>
          </div>
          <div className="flex items-baseline gap-3">
            <span className="font-mono text-lg font-bold text-white">{bestWin.ticker}</span>
            <span className="font-mono text-2xl font-bold text-green-400 text-glow-success-strong">+{bestWin.pnl_percentage.toFixed(2)}%</span>
          </div>
          <p className="text-[10px] text-muted-foreground/70 mt-1.5 italic truncate">"{bestWin.original_thesis}"</p>
        </motion.div>
      )}
      {worstLoss && (
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="hero-loss-glow rounded-xl border border-red-500/20 bg-gradient-to-br from-red-500/5 to-slate-950 p-4 relative overflow-hidden"
        >
          <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-red-400/60 to-transparent" />
          <div className="absolute -top-6 -right-6 w-24 h-24 bg-red-500/10 rounded-full blur-2xl pointer-events-none" />
          <div className="flex items-center gap-2 mb-2">
            <motion.div animate={{ scale: [1, 1.2, 1] }} transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}>
              <Flame className="h-4 w-4 text-red-400" />
            </motion.div>
            <span className="text-[10px] uppercase font-semibold tracking-wider text-red-400">Biggest Loss</span>
            <span className="text-[10px] text-muted-foreground/50 ml-auto">{worstLoss.date}</span>
          </div>
          <div className="flex items-baseline gap-3">
            <span className="font-mono text-lg font-bold text-white">{worstLoss.ticker}</span>
            <span className="font-mono text-2xl font-bold text-red-400 text-glow-danger-strong">{worstLoss.pnl_percentage.toFixed(2)}%</span>
          </div>
          <p className="text-[10px] text-muted-foreground/70 mt-1.5 italic truncate">"{worstLoss.original_thesis}"</p>
        </motion.div>
      )}
    </div>
  );
}

// ── Live Positions ────────────────────────────────────────────────────────────

const positionRowVariants = {
  hidden: { opacity: 0, x: -10 },
  visible: (i: number) => ({
    opacity: 1, x: 0,
    transition: { delay: i * 0.05, duration: 0.3, ease: "easeOut" as const },
  }),
};

function ThesisModal({ ticker, thesis, onClose }: {
  ticker: string;
  thesis: string | null;
  onClose: () => void;
}) {
  return (
    <AnimatePresence>
      <motion.div
        key="thesis-backdrop"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm px-4"
        onClick={onClose}
      >
        <motion.div
          key="thesis-panel"
          initial={{ opacity: 0, scale: 0.95, y: 12 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 8 }}
          transition={{ duration: 0.2, ease: "easeOut" }}
          className="relative max-w-lg w-full rounded-2xl border border-indigo-500/30 bg-slate-900 shadow-2xl overflow-hidden"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="h-px bg-gradient-to-r from-indigo-500/60 via-violet-400/40 to-transparent" />
          <div className="p-5">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Sparkles className="h-3.5 w-3.5 text-violet-400" />
                <span className="text-[10px] uppercase font-semibold tracking-wider text-violet-400">AI Thesis</span>
                <span className="font-mono text-xs font-bold text-white ml-1">{ticker}</span>
              </div>
              <button onClick={onClose} className="p-1 rounded-md hover:bg-white/8 transition-colors text-muted-foreground hover:text-white">
                <X className="h-4 w-4" />
              </button>
            </div>
            {thesis ? (
              <p className="text-sm leading-relaxed text-slate-200 font-light">{thesis}</p>
            ) : (
              <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
                <p className="text-sm text-amber-300/80 leading-relaxed">
                  <span className="font-semibold">Legacy position</span> — this position was opened before the v4.0 regime-switching architecture was deployed. No AI thesis was recorded at entry time.
                </p>
                <p className="text-xs text-muted-foreground/60 mt-2">Future positions opened by the regime engine will always include a full thesis.</p>
              </div>
            )}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}

function LivePositionsSection() {
  const { data, isLoading } = useLivePositions();
  const [thesisModal, setThesisModal] = useState<{ ticker: string; thesis: string | null } | null>(null);

  const totalUnrealized = useMemo(() => {
    if (!data?.positions) return 0;
    return data.positions.reduce((sum, p) => sum + p.unrealized_pl, 0);
  }, [data]);

  return (
    <Card className="border-white/5 overflow-hidden">
      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-4">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Target className="h-4 w-4 text-primary" />
          Live Open Positions
          {data && (
            <Badge variant={data.count > 0 ? "default" : "outline"} className="text-[10px] px-1.5 py-0 ml-1">
              {data.count}
            </Badge>
          )}
          {data && data.count > 0 && (
            <span className={cn("ml-auto text-xs font-mono font-semibold", totalUnrealized >= 0 ? "text-green-400 text-glow-success" : "text-red-400 text-glow-danger")}>
              {totalUnrealized >= 0 ? "+" : ""}{formatCurrency(totalUnrealized)}
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left min-w-[900px]">
          <thead className="text-[10px] uppercase bg-slate-950/60 text-muted-foreground">
            <tr>
              <th className="px-5 py-3 font-semibold">Asset</th>
              <th className="px-5 py-3 font-semibold text-right">Size (Qty)</th>
              <th className="px-5 py-3 font-semibold text-right">Notional</th>
              <th className="px-5 py-3 font-semibold text-right">Entry</th>
              <th className="px-5 py-3 font-semibold text-right">Current</th>
              <th className="px-5 py-3 font-semibold text-right">Unrealised P&L</th>
              <th className="px-5 py-3 font-semibold text-right">Stop Loss</th>
              <th className="px-5 py-3 font-semibold text-right">Take Profit</th>
              <th className="px-5 py-3 font-semibold text-center">Conv.</th>
              <th className="px-5 py-3 font-semibold max-w-[180px]">Thesis</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {isLoading && (
              <tr><td colSpan={10} className="px-5 py-6 text-center text-muted-foreground italic text-xs">Loading positions...</td></tr>
            )}
            {!isLoading && data?.positions.map((pos, i) => {
              const isUp = pos.unrealized_pl >= 0;
              return (
                <motion.tr
                  key={pos.symbol}
                  custom={i}
                  initial="hidden"
                  animate="visible"
                  variants={positionRowVariants}
                  className={cn(
                    "transition-all duration-300 cursor-default",
                    isUp
                      ? "border-l-2 border-l-green-500/30 hover:bg-green-500/[0.04] hover:shadow-[inset_0_0_30px_rgba(34,197,94,0.04)]"
                      : "border-l-2 border-l-red-500/30 hover:bg-red-500/[0.04] hover:shadow-[inset_0_0_30px_rgba(239,68,68,0.04)]"
                  )}
                >
                  <td className="px-5 py-3.5">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-white text-sm">{pos.symbol}</span>
                      <Badge variant="outline" className="text-[9px] px-1 py-0 uppercase border-white/10">{pos.asset_class}</Badge>
                    </div>
                  </td>
                  <td className="px-5 py-3.5 text-right font-mono text-xs text-white">{pos.qty.toFixed(4)}</td>
                  <td className="px-5 py-3.5 text-right font-mono text-xs text-white">{formatCurrency(pos.market_value)}</td>
                  <td className="px-5 py-3.5 text-right font-mono text-xs text-muted-foreground">{formatCurrency(pos.avg_entry_price)}</td>
                  <td className="px-5 py-3.5 text-right font-mono text-xs text-white">{formatCurrency(pos.current_price)}</td>
                  <td className="px-5 py-3.5 text-right">
                    <div className="flex flex-col items-end">
                      <PnlValue value={pos.unrealized_pl} />
                      <span className="text-[10px] opacity-70"><PnlText value={pos.unrealized_plpc * 100} /></span>
                    </div>
                  </td>
                  <td className="px-5 py-3.5 text-right">
                    {pos.stop_loss_price != null ? (
                      <div className="flex flex-col items-end">
                        <span className="text-xs font-mono text-red-400">{formatCurrency(pos.stop_loss_price)}</span>
                        {pos.stop_loss_pct != null && <span className="text-[10px] text-red-500/60">{formatPercentAbs(pos.stop_loss_pct)}</span>}
                      </div>
                    ) : <span className="text-muted-foreground text-xs">—</span>}
                  </td>
                  <td className="px-5 py-3.5 text-right">
                    {pos.take_profit_price != null ? (
                      <div className="flex flex-col items-end">
                        <span className="text-xs font-mono text-green-400">{formatCurrency(pos.take_profit_price)}</span>
                        {pos.take_profit_pct != null && <span className="text-[10px] text-green-500/60">+{formatPercentAbs(pos.take_profit_pct)}</span>}
                      </div>
                    ) : <span className="text-muted-foreground text-xs">—</span>}
                  </td>
                  <td className="px-5 py-3.5 text-center">
                    {pos.conviction_score != null ? (
                      <span className={cn("text-xs font-mono font-semibold", pos.conviction_score >= 0.8 ? "text-green-400" : pos.conviction_score >= 0.75 ? "text-primary" : "text-amber-400")}>
                        {Math.round(pos.conviction_score * 100)}%
                      </span>
                    ) : <span className="text-muted-foreground text-xs">—</span>}
                  </td>
                  <td
                    className="px-5 py-3.5 text-xs text-muted-foreground max-w-[180px] truncate cursor-pointer hover:text-indigo-400 transition-colors"
                    title="Click to view full thesis"
                    onClick={() => setThesisModal({ ticker: pos.symbol, thesis: pos.original_thesis })}
                  >
                    {pos.original_thesis
                      ? <span className="border-b border-dashed border-indigo-500/30">{pos.original_thesis}</span>
                      : <span className="text-muted-foreground/40 italic text-[10px]">legacy — click to view</span>
                    }
                  </td>
                </motion.tr>
              );
            })}
            {!isLoading && (!data || data.positions.length === 0) && (
              <tr>
                <td colSpan={10} className="px-5 py-8 text-center">
                  <div className="flex flex-col items-center gap-2">
                    <motion.div
                      animate={{ opacity: [0.3, 0.6, 0.3] }}
                      transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
                    >
                      <Target className="h-8 w-8 text-muted-foreground/20" />
                    </motion.div>
                    <p className="text-muted-foreground/50 italic text-xs">No open positions — system is in cash</p>
                    <p className="text-[9px] text-muted-foreground/30">Awaiting next analysis cycle</p>
                  </div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
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

// ── Performance Section ───────────────────────────────────────────────────────

interface ChartPayloadEntry {
  dataKey: string;
  name: string;
  value: number;
  color: string;
}

interface ChartTooltipProps {
  active?: boolean;
  payload?: ChartPayloadEntry[];
  label?: string;
}

const CustomTooltip = ({ active, payload, label }: ChartTooltipProps) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-slate-900 border border-white/10 rounded-lg px-3 py-2 text-xs shadow-xl">
      <p className="text-muted-foreground mb-1">{label}</p>
      {payload.map((p) => (
        <p key={p.dataKey} style={{ color: p.color }} className="font-mono">
          {p.name}:{" "}
          {p.dataKey === "equity"
            ? formatCurrency(p.value)
            : `${p.value >= 0 ? "+" : ""}${p.value.toFixed(2)}%`}
        </p>
      ))}
    </div>
  );
};

function PerformanceSection() {
  const { data: history } = usePerformanceHistory();
  const { data: summary } = usePerformanceSummary();

  const hasData = history && history.count > 0;

  const chartData = useMemo(() => {
    if (!history?.snapshots) return [];
    return history.snapshots.map((s) => ({
      date: s.date.slice(5),
      equity: s.equity,
      daily_pnl: parseFloat(s.daily_pnl_pct.toFixed(2)),
      win_rate: parseFloat((s.win_rate * 100).toFixed(1)),
      cumulative: parseFloat(s.cumulative_pnl_pct.toFixed(2)),
    }));
  }, [history]);

  return (
    <Card className="border-white/5 overflow-hidden">
      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-4 flex flex-row items-center justify-between">
        <CardTitle className="flex items-center gap-2 text-sm">
          <BarChart3 className="h-4 w-4 text-primary" /> System Performance
        </CardTitle>
        {summary?.latest_date && (
          <span className="text-[10px] text-muted-foreground terminal-text">
            Last snapshot: {summary.latest_date}
          </span>
        )}
      </CardHeader>
      <CardContent className="p-5">

        {/* Summary stat cards */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
          {[
            {
              label: "Total Return",
              value: summary?.total_return_pct != null
                ? `${summary.total_return_pct >= 0 ? "+" : ""}${summary.total_return_pct.toFixed(2)}%`
                : "—",
              color: summary?.total_return_pct != null
                ? summary.total_return_pct >= 0 ? "text-green-400" : "text-red-400"
                : "text-muted-foreground",
            },
            {
              label: "Win Rate",
              value: summary?.avg_win_rate != null
                ? `${(summary.avg_win_rate * 100).toFixed(1)}%`
                : "—",
              color: summary?.avg_win_rate != null
                ? summary.avg_win_rate >= 0.5 ? "text-green-400" : "text-amber-400"
                : "text-muted-foreground",
            },
            {
              label: "Best Day",
              value: summary?.best_day_pct != null ? `+${summary.best_day_pct.toFixed(2)}%` : "—",
              color: "text-green-400",
            },
            {
              label: "Worst Day",
              value: summary?.worst_day_pct != null ? `${summary.worst_day_pct.toFixed(2)}%` : "—",
              color: "text-red-400",
            },
            {
              label: "Total Trades",
              value: summary?.total_trades != null ? String(summary.total_trades) : "—",
              color: "text-white",
            },
            {
              label: "Avg Conviction",
              value: summary?.avg_conviction != null
                ? `${(summary.avg_conviction * 100).toFixed(1)}%`
                : "—",
              color: summary?.avg_conviction != null
                ? summary.avg_conviction >= 0.75 ? "text-green-400" : "text-amber-400"
                : "text-muted-foreground",
            },
          ].map((stat) => (
            <div key={stat.label} className="bg-slate-900/70 rounded-xl p-3 border border-white/5">
              <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1">{stat.label}</div>
              <div className={cn("text-xl font-mono font-bold", stat.color)}>{stat.value}</div>
            </div>
          ))}
        </div>

        {!hasData ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <BarChart3 className="h-10 w-10 text-muted-foreground/30 mb-3" />
            <p className="text-sm text-muted-foreground">Performance history appears after the first post-mortem runs</p>
            <p className="text-xs text-muted-foreground/60 mt-1">The system records a snapshot automatically each weekday at 4:10 PM ET after market close</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Equity Curve */}
            <div>
              <div className="text-xs font-medium text-muted-foreground mb-3 uppercase tracking-wide">Equity Curve</div>
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={chartData} margin={{ top: 4, right: 4, left: 4, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#64748b" }} tickLine={false} axisLine={false} />
                  <YAxis
                    tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
                    tick={{ fontSize: 10, fill: "#64748b" }}
                    tickLine={false}
                    axisLine={false}
                    width={45}
                  />
                  <Tooltip content={<CustomTooltip />} />
                  <ReferenceLine y={100000} stroke="rgba(255,255,255,0.1)" strokeDasharray="4 4" />
                  <Line
                    type="monotone"
                    dataKey="equity"
                    name="Equity"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4, fill: "#3b82f6" }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>

            {/* Daily Win Rate */}
            <div>
              <div className="text-xs font-medium text-muted-foreground mb-3 uppercase tracking-wide">Daily Win Rate (%)</div>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={chartData} margin={{ top: 4, right: 4, left: 4, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#64748b" }} tickLine={false} axisLine={false} />
                  <YAxis
                    domain={[0, 100]}
                    tickFormatter={(v) => `${v}%`}
                    tick={{ fontSize: 10, fill: "#64748b" }}
                    tickLine={false}
                    axisLine={false}
                    width={35}
                  />
                  <Tooltip content={<CustomTooltip />} />
                  <ReferenceLine y={50} stroke="rgba(255,255,255,0.15)" strokeDasharray="4 4" />
                  <Bar
                    dataKey="win_rate"
                    name="Win Rate"
                    fill="#22c55e"
                    opacity={0.75}
                    radius={[3, 3, 0, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Allocation Section ────────────────────────────────────────────────────────

function AllocationSection() {
  const { data } = useLatestAllocation();

  if (!data?.allocation) return (
    <Card className="border-dashed border-white/10 bg-transparent h-48 flex items-center justify-center">
      <div className="flex flex-col items-center gap-2">
        <motion.div animate={{ opacity: [0.2, 0.5, 0.2] }} transition={{ duration: 3, repeat: Infinity }}>
          <LayoutList className="h-8 w-8 text-muted-foreground/20" />
        </motion.div>
        <p className="text-muted-foreground italic text-sm">No allocation plan yet — the AI will generate one on the next cycle.</p>
      </div>
    </Card>
  );

  const slotCount = data.allocation.length;
  const avgConviction = data.allocation.reduce((s, sl) => s + sl.conviction_score, 0) / slotCount;

  return (
    <Card className="border-white/5 overflow-hidden">
      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-4 flex flex-row items-center justify-between">
        <CardTitle className="flex items-center gap-2 text-sm">
          <LayoutList className="h-4 w-4 text-primary" /> Target Allocation ({slotCount} Slots)
          <span className={cn("text-[9px] font-mono ml-1 px-1.5 py-0.5 rounded-full border", avgConviction >= 0.8 ? "text-green-400 border-green-500/30 bg-green-500/10" : avgConviction >= 0.75 ? "text-blue-400 border-blue-500/30 bg-blue-500/10" : "text-amber-400 border-amber-500/30 bg-amber-500/10")}>
            avg {Math.round(avgConviction * 100)}%
          </span>
        </CardTitle>
        <span className="text-[10px] text-muted-foreground terminal-text">Generated: {formatDate(data.run_utc)}</span>
      </CardHeader>
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left">
          <thead className="text-[10px] uppercase bg-slate-950/60 text-muted-foreground">
            <tr>
              <th className="px-5 py-3 font-semibold w-10 text-center">#</th>
              <th className="px-5 py-3 font-semibold">Ticker</th>
              <th className="px-5 py-3 font-semibold text-center">Conviction</th>
              <th className="px-5 py-3 font-semibold text-right">Kelly</th>
              <th className="px-5 py-3 font-semibold text-right">SL / TP</th>
              <th className="px-5 py-3 font-semibold">Thesis</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {data.allocation.map((slot, idx) => {
              const isCash = slot.ticker === "SGOV";
              const isCrypto = slot.ticker.includes("/");
              return (
                <motion.tr
                  key={slot.slot}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: idx * 0.04, duration: 0.3 }}
                  className={cn("transition-all duration-300 hover:bg-white/[0.03]", isCash && "opacity-40 hover:opacity-80")}
                >
                  <td className="px-5 py-3 text-center text-muted-foreground terminal-text text-xs">{slot.slot}</td>
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-1.5">
                      <span className="font-bold text-white text-sm">{slot.ticker}</span>
                      <Badge variant={isCash ? "outline" : "default"} className={cn("text-[9px] px-1 py-0 uppercase", isCrypto && "bg-purple-500/20 text-purple-400 border-purple-500/30")}>{slot.asset_class}</Badge>
                    </div>
                  </td>
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-2 justify-center">
                      <span className="terminal-text text-[10px] w-7 text-right">{Math.round(slot.conviction_score * 100)}%</span>
                      <div className="w-14 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                        <div
                          className={cn("h-full rounded-full conviction-bar-animate", slot.conviction_score >= 0.8 ? "bg-green-500" : slot.conviction_score >= 0.75 ? "bg-primary" : "bg-amber-500")}
                          style={{ width: `${slot.conviction_score * 100}%`, animationDelay: `${idx * 60}ms` }}
                        />
                      </div>
                    </div>
                  </td>
                  <td className="px-5 py-3 text-right terminal-text font-semibold text-white text-xs">{formatPercentAbs(slot.kelly_fraction)}</td>
                  <td className="px-5 py-3 text-right terminal-text text-[10px]">
                    <span className="text-red-400">{formatPercentAbs(slot.stop_loss_pct)}</span>
                    <span className="text-muted-foreground mx-1">/</span>
                    <span className="text-green-400">+{formatPercentAbs(slot.take_profit_pct)}</span>
                  </td>
                  <td className="px-5 py-3 text-[10px] text-muted-foreground truncate max-w-[220px] hover:whitespace-normal hover:text-slate-300 transition-colors" title={slot.thesis}>
                    {slot.thesis}
                  </td>
                </motion.tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ── Journal Section ───────────────────────────────────────────────────────────

type ParticleItem = { id: number; dx: number; dy: number; isWin: boolean };

function JournalSection() {
  const { data } = useJournal();
  const [particles, setParticles] = useState<ParticleItem[]>([]);
  const prevClosedCount = useRef(0);

  // Detect new closed trades and fire a radial particle burst
  useEffect(() => {
    if (!data?.trades) return;
    const closed = data.trades.filter((t) => t.status !== "Active");
    const prev = prevClosedCount.current;
    if (closed.length > prev && prev > 0) {
      const latest = closed[0];
      const isWin = latest.status === "Closed_Win";
      const burst: ParticleItem[] = Array.from({ length: 12 }, (_, i) => {
        const angle = (i / 12) * Math.PI * 2;
        const dist = 36 + Math.abs(Math.sin(i * 1.7)) * 28;
        return { id: Date.now() + i, dx: Math.cos(angle) * dist, dy: Math.sin(angle) * dist, isWin };
      });
      setParticles((p) => [...p, ...burst]);
    }
    prevClosedCount.current = closed.length;
  }, [data?.trades?.length]);

  if (!data) return null;

  const winRate = data.summary.total > 0 && data.summary.wins != null
    ? ((data.summary.wins / data.summary.total) * 100).toFixed(0)
    : null;

  return (
    <Card className="border-white/5 overflow-hidden relative">
      {/* Particle burst anchor — fires at the top-right of the card header */}
      <div className="absolute top-6 right-20 pointer-events-none z-20">
        <AnimatePresence>
          {particles.map((p) => (
            <motion.div
              key={p.id}
              className="absolute rounded-full"
              style={{
                width: 5, height: 5,
                backgroundColor: p.isWin ? "#22c55e" : "#ef4444",
                boxShadow: p.isWin ? "0 0 6px #22c55e" : "0 0 6px #ef4444",
              }}
              initial={{ x: 0, y: 0, scale: 1, opacity: 0.95 }}
              animate={{ x: p.dx, y: p.dy, scale: 0, opacity: 0 }}
              transition={{ duration: 0.75, ease: [0.22, 1, 0.36, 1] }}
              onAnimationComplete={() => setParticles((prev) => prev.filter((x) => x.id !== p.id))}
            />
          ))}
        </AnimatePresence>
      </div>

      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-4 flex flex-row items-center justify-between">
        <CardTitle className="flex items-center gap-2 text-sm">
          <History className="h-4 w-4 text-primary" /> Trade Journal
          {winRate && (
            <span className={cn("text-[9px] font-mono px-1.5 py-0.5 rounded-full border", Number(winRate) >= 50 ? "text-green-400 border-green-500/30 bg-green-500/10" : "text-red-400 border-red-500/30 bg-red-500/10")}>
              {winRate}% win
            </span>
          )}
        </CardTitle>
        <div className="flex gap-3 terminal-text text-[10px]">
          <span className="text-muted-foreground">Total: {data.summary.total}</span>
          <span className="text-green-400">Wins: {data.summary.wins ?? 0}</span>
          <span className="text-red-400">Losses: {data.summary.losses ?? 0}</span>
          <span>Avg: <PnlText value={data.summary.avg_pnl} /></span>
        </div>
      </CardHeader>
      <div className="overflow-x-auto max-h-[360px] overflow-y-auto">
        <table className="w-full text-sm text-left">
          <thead className="text-[10px] uppercase bg-slate-950/60 text-muted-foreground sticky top-0 backdrop-blur-md z-10">
            <tr>
              <th className="px-5 py-2.5 font-semibold">Date</th>
              <th className="px-5 py-2.5 font-semibold">Asset</th>
              <th className="px-5 py-2.5 font-semibold text-center">Status</th>
              <th className="px-5 py-2.5 font-semibold text-right">P&L</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {data.trades.map((trade, idx) => {
              const isWin = trade.status === "Closed_Win";
              const isLoss = trade.status === "Closed_Loss";
              return (
                <motion.tr
                  key={trade.trade_id}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: Math.min(idx * 0.03, 0.5), duration: 0.25 }}
                  className={cn(
                    "transition-all duration-300",
                    isWin && "hover:bg-green-500/[0.04]",
                    isLoss && "hover:bg-red-500/[0.04]",
                    !isWin && !isLoss && "hover:bg-white/[0.02]"
                  )}
                >
                  <td className="px-5 py-2.5 terminal-text text-muted-foreground text-[10px] whitespace-nowrap">{trade.date}</td>
                  <td className="px-5 py-2.5">
                    <div className="flex items-center gap-1.5">
                      <span className="font-bold text-white text-sm">{trade.ticker}</span>
                      <span className={cn("text-[9px] uppercase", trade.ticker.includes("/") ? "text-purple-400/70" : "text-muted-foreground")}>{trade.asset_class}</span>
                    </div>
                  </td>
                  <td className="px-5 py-2.5 text-center">
                    <Badge variant={trade.status === 'Active' ? 'default' : isWin ? 'success' : 'danger'} className="text-[9px]">
                      {trade.status.replace('Closed_', '')}
                    </Badge>
                  </td>
                  <td className="px-5 py-2.5 text-right">
                    {trade.status === 'Active'
                      ? <span className="text-muted-foreground text-xs">—</span>
                      : <PnlText value={trade.pnl_percentage} />}
                  </td>
                </motion.tr>
              );
            })}
            {data.trades.length === 0 && (
              <tr><td colSpan={4} className="px-5 py-8 text-center text-muted-foreground italic text-xs">No trades logged yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ── Learning Context (bidirectional RAG) ─────────────────────────────────────

function LearningContextSection() {
  const { data: lossData } = useRagLosses();
  const { data: winData } = useRagWins();

  const hasLosses = lossData && lossData.losses.length > 0;
  const hasWins = winData && winData.wins.length > 0;

  if (!hasLosses && !hasWins) return null;

  return (
    <div className="space-y-2">
      <div className="text-[10px] uppercase font-semibold text-muted-foreground tracking-wider px-1 flex items-center gap-2">
        <Activity className="h-3 w-3 text-primary" /> Learning Context
        <span className="font-normal normal-case text-muted-foreground/60">— injected into LLM prompt</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {hasWins && (
          <Card className="border-green-500/20 bg-green-500/5 overflow-hidden">
            <div className="px-4 py-2.5 bg-green-500/10 border-b border-green-500/15">
              <span className="text-[10px] uppercase font-semibold text-green-400 tracking-wider flex items-center gap-1.5">
                <TrendingUp className="h-3 w-3" /> What Worked ({winData.count})
              </span>
            </div>
            <div className="divide-y divide-green-500/8">
              {winData.wins.map((win, i) => (
                <motion.div
                  key={win.trade_id}
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.08 }}
                  className="p-3 hover:bg-green-500/5 transition-all duration-300 group"
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono text-sm font-bold text-white group-hover:text-green-300 transition-colors">{win.ticker}</span>
                      <Badge className="text-[9px] py-0 px-1 bg-green-500/10 text-green-400 border-green-500/20 border">{win.asset_class}</Badge>
                    </div>
                    <PnlText value={win.pnl_percentage} />
                  </div>
                  <p className="text-[10px] leading-relaxed text-muted-foreground italic border-l-2 border-green-500/30 pl-2.5">
                    "{win.original_thesis}"
                  </p>
                </motion.div>
              ))}
            </div>
          </Card>
        )}

        {hasLosses && (
          <Card className="border-red-500/20 bg-red-500/5 overflow-hidden">
            <div className="px-4 py-2.5 bg-red-500/10 border-b border-red-500/15">
              <span className="text-[10px] uppercase font-semibold text-red-400 tracking-wider flex items-center gap-1.5">
                <TrendingDown className="h-3 w-3" /> What Failed ({lossData.count})
              </span>
            </div>
            <div className="divide-y divide-red-500/8">
              {lossData.losses.map((loss, i) => (
                <motion.div
                  key={loss.trade_id}
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.08 }}
                  className="p-3 hover:bg-red-500/5 transition-all duration-300 group"
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono text-sm font-bold text-white group-hover:text-red-300 transition-colors">{loss.ticker}</span>
                      <Badge className="text-[9px] py-0 px-1 bg-red-500/10 text-red-400 border-red-500/20 border">{loss.asset_class}</Badge>
                    </div>
                    <PnlText value={loss.pnl_percentage} />
                  </div>
                  <p className="text-[10px] leading-relaxed text-muted-foreground italic border-l-2 border-red-500/30 pl-2.5">
                    "{loss.original_thesis}"
                  </p>
                </motion.div>
              ))}
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}

// ── High-Yield Growth Vault Panel ─────────────────────────────────────────────

function VaultPanel() {
  const { data, isLoading } = useVault();
  const sweep = useManualSweep();
  const [lastResult, setLastResult] = useState<string | null>(null);

  const handleSweep = async (dryRun: boolean) => {
    const res = await sweep.mutateAsync(dryRun);
    const r = res?.result;
    if (r?.swept) {
      setLastResult(`✓ Swept $${r.sweep_amount?.toFixed(2)} → ${r.vault_symbol} | New HWM: $${r.new_hwm?.toFixed(2)}`);
    } else if (r?.reason === "first_run_hwm_initialised") {
      setLastResult(`HWM initialised at $${r.hwm?.toFixed(2)}`);
    } else if (r?.reason === "no_new_profit") {
      setLastResult(`No new profit above HWM — vault unchanged`);
    } else if (r?.reason === "sweep_below_minimum") {
      setLastResult(`Eligible profit too small ($${r.sweep_amount?.toFixed(4)}) — minimum not met`);
    } else {
      setLastResult(r?.reason ?? "No action taken");
    }
  };

  if (isLoading) {
    return (
      <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5">
        <CardContent className="p-5">
          <div className="h-16 animate-pulse bg-white/5 rounded-lg" />
        </CardContent>
      </Card>
    );
  }

  const vaultSymbol = data?.vault_symbol ?? "JEPQ";
  const isInit      = data?.initialised ?? false;
  const hwm         = data?.hwm ?? 0;
  const totalVaulted = data?.total_vaulted_usd ?? 0;
  const totalSweeps  = data?.total_sweeps ?? 0;
  const lastSweepAmt = data?.last_sweep_amount;
  const lastSweepDate = data?.last_sweep_date;

  return (
    <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-amber-500/20 transition-all duration-500 relative overflow-hidden">
      <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-amber-500/40 to-transparent" />
      <div className="absolute top-2 right-2 opacity-5">
        <Vault className="h-16 w-16 text-amber-400" />
      </div>

      <CardContent className="p-5">
        <div className="flex items-center gap-2 mb-4">
          <div className="p-1.5 rounded-lg bg-amber-500/10 border border-amber-500/20">
            <Vault className="h-3.5 w-3.5 text-amber-400" />
          </div>
          <span className="text-xs font-semibold text-amber-400/90 tracking-wider uppercase">
            High-Yield Growth Vault
          </span>
          <span className="ml-auto text-[10px] font-mono text-amber-400/60 bg-amber-500/10 px-1.5 py-0.5 rounded">
            {vaultSymbol}
          </span>
        </div>

        {!isInit ? (
          <p className="text-xs text-muted-foreground">
            Vault not initialised — run an analysis cycle to set the High Water Mark.
          </p>
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-white/3 rounded-lg p-3 border border-white/5">
                <div className="text-[10px] font-medium text-muted-foreground mb-1 flex items-center gap-1">
                  <Target className="h-3 w-3" /> High Water Mark
                </div>
                <div className="text-lg font-mono font-bold text-white">
                  {formatCurrency(hwm)}
                </div>
              </div>
              <div className="bg-amber-500/5 rounded-lg p-3 border border-amber-500/10">
                <div className="text-[10px] font-medium text-amber-400/70 mb-1 flex items-center gap-1">
                  <Coins className="h-3 w-3" /> Total Vaulted
                </div>
                <div className="text-lg font-mono font-bold text-amber-400">
                  {formatCurrency(totalVaulted)}
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between text-xs text-muted-foreground bg-white/3 rounded-lg px-3 py-2 border border-white/5">
              <span className="flex items-center gap-1.5">
                <ArrowUpRight className="h-3 w-3 text-green-400" />
                {totalSweeps} sweep{totalSweeps !== 1 ? "s" : ""} completed
              </span>
              {lastSweepDate && lastSweepAmt && (
                <span className="font-mono text-[10px] text-amber-400/70">
                  Last: +{formatCurrency(lastSweepAmt)} on {lastSweepDate}
                </span>
              )}
            </div>

            <div className="text-[10px] text-muted-foreground/60 bg-white/2 rounded px-2 py-1.5 border border-white/5 leading-relaxed">
              20% of new profits above HWM auto-swept into {vaultSymbol}. Vault shares are
              protected — the AI cannot sell them.
            </div>

            {lastResult && (
              <div className="text-[10px] font-mono text-green-400/80 bg-green-500/5 border border-green-500/10 rounded px-2 py-1.5">
                {lastResult}
              </div>
            )}

            <div className="flex gap-2">
              <button
                onClick={() => handleSweep(false)}
                disabled={sweep.isPending}
                className="flex-1 text-[11px] font-medium py-1.5 px-3 rounded-lg bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/20 text-amber-400 transition-all disabled:opacity-50"
              >
                {sweep.isPending ? "Running…" : "Run Sweep"}
              </button>
              <button
                onClick={() => handleSweep(true)}
                disabled={sweep.isPending}
                className="text-[11px] font-medium py-1.5 px-3 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-muted-foreground transition-all disabled:opacity-50"
              >
                Dry Run
              </button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Ambient Visual Overlays ──────────────────────────────────────────────────

/** CRT scanline — a single translucent beam that slowly sweeps top→bottom */
function CRTOverlay() {
  return (
    <div className="fixed inset-0 pointer-events-none z-[9998] overflow-hidden">
      <div
        className="crt-scanline absolute left-0 right-0 h-[3px]"
        style={{
          background: "linear-gradient(to bottom, transparent, rgba(99,102,241,0.055), transparent)",
          boxShadow: "0 0 10px rgba(99,102,241,0.07)",
        }}
      />
      {/* Subtle edge vignette */}
      <div
        className="absolute inset-0"
        style={{
          background: "radial-gradient(ellipse at center, transparent 55%, rgba(0,0,0,0.28) 100%)",
        }}
      />
    </div>
  );
}

/** Left-edge regime pulse — color changes with macro regime */
function RegimeGlow() {
  const { data: alloc } = useLatestAllocation();
  const regime = alloc?.regime;

  const cfg = regime === "Bear"
    ? { color: "rgba(239,68,68,0.18)", glow: "rgba(239,68,68,0.14)", key: "bear" }
    : regime === "Neutral"
    ? { color: "rgba(245,158,11,0.15)", glow: "rgba(245,158,11,0.11)", key: "neutral" }
    : { color: "rgba(34,197,94,0.14)", glow: "rgba(34,197,94,0.10)", key: "bull" };

  if (!regime) return null;

  return (
    <motion.div
      key={cfg.key}
      className="fixed left-0 top-0 bottom-0 w-[3px] pointer-events-none z-[9997]"
      initial={{ opacity: 0 }}
      animate={{ opacity: [0.45, 1, 0.45] }}
      transition={{ duration: 3.5, repeat: Infinity, ease: "easeInOut" }}
      style={{ background: cfg.color, boxShadow: `3px 0 24px ${cfg.glow}` }}
    />
  );
}

/** Ambient bottom glow — warm amber on drawdown, cool blue when profitable */
function EquityEcho() {
  const { data } = usePortfolio();
  if (!data) return null;

  const isProfit = data.account.equity >= 100000;
  const magnitude = Math.min(Math.abs(data.account.equity - 100000) / 20000, 1);
  const baseAlpha = 0.035 + magnitude * 0.055;

  return (
    <motion.div
      key={isProfit ? "profit" : "loss"}
      className="fixed inset-0 pointer-events-none z-0"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 2.5, ease: "easeInOut" }}
      style={{
        background: isProfit
          ? `radial-gradient(ellipse at 50% 100%, rgba(59,130,246,${baseAlpha}) 0%, transparent 60%)`
          : `radial-gradient(ellipse at 50% 100%, rgba(245,158,11,${baseAlpha}) 0%, transparent 60%)`,
      }}
    />
  );
}

// ── Dashboard Root ────────────────────────────────────────────────────────────

export default function Dashboard() {
  return (
    <div className="min-h-screen bg-background flex flex-col relative">
      <CRTOverlay />
      <RegimeGlow />
      <EquityEcho />
      <Header />
      <SystemStatusBanner />
      <ActivityTicker />

      <main className="flex-1 max-w-[1600px] w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">

        {/* PRIMARY ACTION HERO */}
        <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
          <div className="relative rounded-2xl border border-primary/20 bg-gradient-to-br from-slate-900/80 to-slate-950/80 px-7 py-5 shadow-[0_0_60px_rgba(59,130,246,0.05)] overflow-hidden">
            <div className="absolute top-0 left-0 w-64 h-64 bg-primary/5 rounded-full blur-3xl -translate-x-1/2 -translate-y-1/2 pointer-events-none" />
            <TradeWorkflowBar />
          </div>
        </motion.div>

        {/* PORTFOLIO METRICS */}
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
          <PortfolioMetrics />
        </motion.div>

        {/* BEST/WORST TRADE HERO */}
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12 }}>
          <BestTradeHero />
        </motion.div>

        {/* AI AGENTS: Trading Brain + Auditor side-by-side */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.14 }}>
            <AIBrainSection />
          </motion.div>
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.16 }}>
            <AuditorAgentSection />
          </motion.div>
        </div>

        {/* LIVE POSITIONS */}
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.16 }}>
          <LivePositionsSection />
        </motion.div>

        {/* PERFORMANCE */}
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
          <PerformanceSection />
        </motion.div>

        {/* ALLOCATION + JOURNAL | LEARNING + CONTROLS */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <motion.div className="col-span-1 lg:col-span-2 space-y-6" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25 }}>
            <AllocationSection />
            <JournalSection />
          </motion.div>

          <motion.div className="space-y-6" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
            <LearningContextSection />
            <VaultPanel />
            <ControlPanel />
          </motion.div>
        </div>

      </main>
    </div>
  );
}
