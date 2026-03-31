import { useMemo, useRef, useEffect, useState, useCallback } from "react";
import { useIsMobile } from "@/hooks/use-mobile";
import { SafeSection } from "@/components/ErrorBoundary";
import {
  usePlatformStatus, usePortfolio, useLivePositions, useLatestAllocation,
  useJournal, useRagLosses, useRagWins, usePerformanceHistory,
  usePerformanceSummary, useAICommentary, useRefreshCommentary,
  useVault, useManualSweep, useAuditorReport, useTriggerAudit,
  useAuditorPerformance, useTriggerPerformanceAnalysis,
  useLearningSnapshotInfo, useSyncLearningSnapshot,
  useForceRebalance, useCloseAndReallocate, useKrakenStatus, useKrakenPerformance,
  useKrakenCommentary, useRefreshKrakenCommentary, useKrakenBots, useEquityCurve,
  useLearningJournal, useAttribution,
  useDegradationLog, useDegradationReport, useDegradationHealth,
  useRecentTrades, useRagWinsExtended, useExportReport,
  type AllocationPlan, type AuditFinding, type LivePosition,
  type KrakenStatus, type KrakenPerformance, type KrakenSymbolStats,
  type KrakenBotProfile, type RecentTradeItem,
  type LearningEntry, type DegradationEvent, type DegradationStats,
} from "@/hooks/use-trading";
import { CorrelationMatrix } from "@/components/CorrelationMatrix";
import { SentimentGauges } from "@/components/SentimentGauges";
import { BlackoutBanner, EconomicCalendarPanel } from "@/components/EconomicCalendarBanner";
import { RiskMetricsPanel } from "@/components/RiskMetricsPanel";
import { AttributionPanel } from "@/components/AttributionPanel";
import { BacktesterPanel } from "@/components/BacktesterPanel";
import { cn, formatCurrency, formatCryptoPrice, formatPercentAbs, formatDate } from "@/lib/utils";
import { useToast } from "@/hooks/use-toast";
import { Card, CardHeader, CardTitle, CardContent, Badge, PnlText, PnlValue } from "@/components/ui";
import { ControlPanel } from "@/components/ControlPanel";
import { EmergencyControls, EmergencyHeaderButtons } from "@/components/EmergencyControls";
import { TradeWorkflowBar } from "@/components/TradeWorkflowBar";
import {
  Activity, ShieldAlert, History, TrendingDown, TrendingUp,
  LayoutList, WifiOff, AlertTriangle, Target, BarChart3,
  RefreshCw, Sparkles, Brain, Trophy, Flame, Zap, X,
  Vault, ArrowUpRight, Coins, TrendingUp as GrowthIcon,
  Shield, Eye, CheckCircle2, XCircle, AlertOctagon, Lock,
  Lightbulb, Play, LogOut, ExternalLink, Copy, Bug,
  LayoutDashboard, MoreHorizontal, Anchor, Database, FileDown,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";

function useMarketCountdown(nextOpenIso: string | null | undefined): string | null {
  const [display, setDisplay] = useState<string | null>(null);
  useEffect(() => {
    if (!nextOpenIso) { setDisplay(null); return; }
    const tick = () => {
      const diff = new Date(nextOpenIso).getTime() - Date.now();
      if (diff <= 0) { setDisplay(null); return; }
      const h = Math.floor(diff / 3_600_000);
      const m = Math.floor((diff % 3_600_000) / 60_000);
      const s = Math.floor((diff % 60_000) / 1_000);
      setDisplay(`${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [nextOpenIso]);
  return display;
}

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

// ── Gamification — Streak, XP Rank, Kill Board ────────────────────────────────

type GamTrade = { pnl_pct?: number; pnl_percentage?: number; status?: string };

function computeStreak(trades: GamTrade[]): { count: number; direction: "win" | "loss" | "none" } {
  if (!trades || trades.length === 0) return { count: 0, direction: "none" };
  const isWin = (t: GamTrade) => {
    if (t.status) return t.status === "Closed_Win";
    const pct = t.pnl_pct ?? t.pnl_percentage ?? 0;
    return pct > 0;
  };
  const direction = isWin(trades[0]) ? "win" : "loss";
  let count = 0;
  for (const t of trades) {
    if (isWin(t) === (direction === "win")) count++;
    else break;
  }
  return { count, direction };
}

function computeXP(wins: number, total: number): number {
  return wins * 100 + total * 10;
}

const KRAKEN_RANKS = [
  { xp: 10000, label: "Davy Jones Himself", icon: "💀", tw: "text-cyan-300" },
  { xp: 5000,  label: "Captain",            icon: "⚓", tw: "text-cyan-400" },
  { xp: 2500,  label: "Quartermaster",      icon: "🗺️", tw: "text-cyan-500" },
  { xp: 1000,  label: "First Mate",         icon: "🏴‍☠️", tw: "text-teal-400" },
  { xp: 500,   label: "Able Seaman",        icon: "⚔️", tw: "text-slate-300" },
  { xp: 0,     label: "Deckhand",           icon: "🪝", tw: "text-slate-400" },
];

const ORACLE_RANKS = [
  { xp: 10000, label: "The Degen Oracle", icon: "🔮", tw: "text-violet-300" },
  { xp: 5000,  label: "Galaxy Brain",     icon: "🧠", tw: "text-indigo-400" },
  { xp: 2500,  label: "Diamond Hands",    icon: "💎", tw: "text-blue-400" },
  { xp: 1000,  label: "Ape Mode",         icon: "🦍", tw: "text-violet-400" },
  { xp: 500,   label: "Bag Holder",       icon: "💼", tw: "text-slate-300" },
  { xp: 0,     label: "Paper Hands",      icon: "📄", tw: "text-slate-400" },
];

type RankEntry = typeof KRAKEN_RANKS[number];

function getRank(xp: number, ranks: RankEntry[]): RankEntry {
  for (const rank of ranks) {
    if (xp >= rank.xp) return rank;
  }
  return ranks[ranks.length - 1];
}

function getNextRank(xp: number, ranks: RankEntry[]): RankEntry | null {
  for (let i = ranks.length - 1; i >= 0; i--) {
    if (ranks[i].xp > xp) return ranks[i];
  }
  return null;
}

function StreakChip({ count, direction }: { count: number; direction: "win" | "loss" | "none" }) {
  if (count === 0 || direction === "none") return null;
  const isWin = direction === "win";
  const isHot  = isWin && count >= 5;
  const isWarm = isWin && count >= 3 && !isHot;
  const emoji = isWin ? "🔥" : "💀";
  const label = `${count}${isWin ? "W" : "L"}`;
  return (
    <motion.span
      className={cn(
        "text-[9px] font-bold px-1.5 py-0.5 rounded-full border",
        isHot  ? "text-red-300 bg-red-500/15 border-red-500/40" :
        isWarm ? "text-amber-300 bg-amber-500/15 border-amber-500/30" :
        isWin  ? "text-green-400 bg-green-500/10 border-green-500/20" :
                 "text-slate-400 bg-slate-800/50 border-slate-600/30"
      )}
      animate={
        isHot  ? { boxShadow: ["0 0 0px rgba(239,68,68,0)", "0 0 8px rgba(239,68,68,0.5)", "0 0 0px rgba(239,68,68,0)"] } :
        isWarm ? { boxShadow: ["0 0 0px rgba(251,146,60,0)", "0 0 6px rgba(251,146,60,0.4)", "0 0 0px rgba(251,146,60,0)"] } :
        {}
      }
      transition={{ duration: 1.5, repeat: Infinity }}
    >
      {emoji} {label}
    </motion.span>
  );
}

function XPRankBar({ xp, ranks, accent }: { xp: number; ranks: RankEntry[]; accent: string }) {
  const current  = getRank(xp, ranks);
  const next     = getNextRank(xp, ranks);
  const progress = next
    ? Math.min(((xp - current.xp) / (next.xp - current.xp)) * 100, 100)
    : 100;
  return (
    <div className="mt-2 mb-3">
      <div className="flex items-center justify-between mb-1">
        <span className={cn("text-[9px] font-bold", current.tw)}>
          {current.icon} {current.label}
        </span>
        <span className="text-[8px] text-muted-foreground/50 font-mono">{xp.toLocaleString()} XP</span>
      </div>
      <div className="h-1 bg-slate-800 rounded-full overflow-hidden">
        <motion.div
          className="h-full rounded-full"
          style={{ backgroundColor: accent }}
          initial={{ width: 0 }}
          animate={{ width: `${progress}%` }}
          transition={{ duration: 1, ease: "easeOut" }}
        />
      </div>
      {next && (
        <div className="text-[8px] text-muted-foreground/30 mt-0.5 text-right">
          {next.icon} {next.label} at {next.xp.toLocaleString()} XP
        </div>
      )}
    </div>
  );
}

type KillTradeEntry = {
  symbol?: string;
  ticker?: string;
  pnl_pct?: number;
  pnl_percentage?: number;
  pnl_usd?: number | null;
  exit_reason?: string;
  reason?: string;
};

function KillBoardPanel({
  trades,
  theme,
  bigWinUsd,
  bigWinPctFallback,
  bigWinLabel,
  panelLabel,
}: {
  trades: KillTradeEntry[];
  theme: "pirate" | "degen";
  bigWinUsd: number;
  bigWinPctFallback?: number;
  bigWinLabel: string;
  panelLabel: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const isPirate = theme === "pirate";

  const pnlNum = (t: KillTradeEntry) => t.pnl_usd ?? t.pnl_pct ?? t.pnl_percentage ?? 0;

  const wins = [...trades]
    .filter(t => (t.pnl_pct ?? t.pnl_percentage ?? 0) > 0)
    .sort((a, b) => pnlNum(b) - pnlNum(a))
    .slice(0, 10);

  if (wins.length === 0) return null;

  return (
    <div className="mt-2">
      <button
        onClick={() => setExpanded(v => !v)}
        className={cn(
          "flex items-center gap-1.5 text-[9px] font-semibold px-2 py-0.5 rounded-full border transition-all",
          isPirate
            ? "text-cyan-400/70 border-cyan-500/20 bg-cyan-500/5 hover:bg-cyan-500/10 hover:text-cyan-300"
            : "text-indigo-400/70 border-indigo-500/20 bg-indigo-500/5 hover:bg-indigo-500/10 hover:text-indigo-300"
        )}
      >
        <span>{isPirate ? "☠️" : "🎯"}</span>
        <span>{panelLabel} · {wins.length} Kill{wins.length !== 1 ? "s" : ""}</span>
        <span className={cn("transition-transform duration-200", expanded && "rotate-180")}>▾</span>
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="mt-2 space-y-1.5">
              {wins.map((trade, i) => {
                const sym = (trade.symbol ?? trade.ticker ?? "?").replace("/USD", "");
                const pct = trade.pnl_pct ?? trade.pnl_percentage ?? 0;
                const usd = trade.pnl_usd ?? null;
                const isBig = usd != null
                  ? usd >= bigWinUsd
                  : (bigWinPctFallback != null ? pct >= bigWinPctFallback : false);
                const reason = trade.exit_reason ?? trade.reason ?? "";
                return (
                  <motion.div
                    key={`${sym}-${i}`}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.04 }}
                    className={cn(
                      "flex items-center gap-2 px-2.5 py-1.5 rounded-lg border",
                      isPirate
                        ? "border-cyan-500/10 bg-cyan-950/20"
                        : "border-indigo-500/10 bg-indigo-950/20"
                    )}
                  >
                    <span className="font-bold text-white font-mono text-[10px] w-10 shrink-0">{sym}</span>
                    <span className="text-green-400 font-mono font-semibold text-[10px]">+{pct.toFixed(2)}%</span>
                    {usd != null && (
                      <span className="text-green-300/70 font-mono text-[9px]">${usd.toFixed(2)}</span>
                    )}
                    {reason && <span className="text-muted-foreground/40 text-[8px] flex-1 truncate">{reason}</span>}
                    {isBig && (
                      <span className="ml-auto text-[8px] font-bold text-yellow-400 bg-yellow-500/10 border border-yellow-500/20 px-1.5 py-0.5 rounded-full shrink-0 whitespace-nowrap">
                        {bigWinLabel}
                      </span>
                    )}
                  </motion.div>
                );
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── KrakenPositionCard — collapsible single-position row ──────────────────────
// Thin collapsed pill showing PnL, stop & trail; expands to full detail on click.
// Used in both the main Live Positions section and the DavyJones bot card.
function KrakenPositionCard({
  kpos,
  signals,
  isPaper,
  compact = false,
}: {
  kpos: { symbol: string; side: string; qty: number; entry_price: number; current_price: number; size_usd: number; unrealized_pnl_usd: number; unrealized_pnl_pct: number; entry_time: string; best_price: number; stop_loss_price: number; take_profit_price: number };
  signals?: any[];
  isPaper?: boolean;
  compact?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const isUp    = (kpos.unrealized_pnl_usd ?? 0) >= 0;
  const pnlPct  = kpos.unrealized_pnl_pct ?? 0;
  const sym     = kpos.symbol.replace("/USD", "");
  const trailActive = kpos.best_price != null && kpos.best_price > kpos.entry_price;
  const hoursIn = kpos.entry_time
    ? (Date.now() - new Date(kpos.entry_time).getTime()) / 3_600_000
    : null;
  const ageLabel = hoursIn == null ? null : hoursIn < 2 ? "Fresh" : hoursIn < 12 ? "Active" : hoursIn < 48 ? "Aging" : "Stale";
  const ageColor = hoursIn == null ? "#64748b" : hoursIn < 2 ? "#22c55e" : hoursIn < 12 ? "#22d3ee" : hoursIn < 48 ? "#f59e0b" : "#ef4444";
  const sig        = signals?.find((s: any) => s.symbol === kpos.symbol);
  const zScore     = sig?.z_score ?? null;
  const conviction = zScore != null ? Math.min(Math.abs(zScore) / 2, 1) : null;

  return (
    <div
      onClick={() => setExpanded(v => !v)}
      className={cn(
        "rounded-lg border cursor-pointer select-none transition-all duration-200",
        isUp ? "border-cyan-500/20 bg-cyan-950/[0.07] hover:bg-cyan-950/20" : "border-red-500/15 bg-red-950/[0.07] hover:bg-red-950/20"
      )}
    >
      {/* ── Collapsed header — always visible ── */}
      <div className={cn("flex items-center gap-2 px-3 overflow-hidden", compact ? "py-1.5" : "py-2")}>
        <span className={cn("w-0.5 h-4 rounded-full shrink-0", isUp ? "bg-cyan-500/70" : "bg-red-400/60")} />
        <span className="font-bold font-mono text-white text-[11px] w-11 shrink-0">{sym}</span>
        <span className={cn(
          "text-[8px] font-bold px-1.5 py-0.5 rounded-full border shrink-0",
          kpos.side === "long"
            ? "text-green-400 border-green-500/30 bg-green-500/10"
            : "text-orange-400 border-orange-500/30 bg-orange-500/10"
        )}>
          {kpos.side.toUpperCase()}
        </span>
        {isPaper && (
          <span className="text-[7px] font-bold px-1 py-0.5 rounded border border-amber-500/25 text-amber-400/60 shrink-0">PAPER</span>
        )}
        <MarketStatusBadge symbol={kpos.symbol} isCrypto={true} />
        {/* PnL */}
        <span className={cn("font-mono font-semibold text-[10px] flex-1 tabular-nums", isUp ? "text-green-400" : "text-red-400")}>
          {isUp ? "+" : ""}${(kpos.unrealized_pnl_usd ?? 0).toFixed(2)}
          <span className="text-[8px] opacity-60 ml-1">({isUp ? "+" : ""}{pnlPct.toFixed(2)}%)</span>
        </span>
        {/* Stop loss */}
        <span className="text-[9px] font-mono text-red-400/55 shrink-0 hidden sm:inline">
          SL {formatCryptoPrice(kpos.stop_loss_price)}
        </span>
        {/* Trail status */}
        <span className={cn(
          "text-[8px] px-1.5 py-0.5 rounded-full border shrink-0",
          trailActive ? "text-cyan-400 border-cyan-500/30 bg-cyan-500/10" : "text-slate-500/60 border-slate-700/30 bg-slate-800/20"
        )}>
          {trailActive ? "⚡ trail" : "waiting"}
        </span>
        {/* Age — hide on compact */}
        {hoursIn != null && !compact && (
          <span className="text-[8px] font-mono shrink-0" style={{ color: ageColor }}>{hoursIn.toFixed(0)}h</span>
        )}
        <span className={cn("text-muted-foreground/30 text-[10px] transition-transform duration-200 shrink-0", expanded && "rotate-180")}>▾</span>
      </div>

      {/* ── Expanded detail grid ── */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-3 pt-2 border-t border-white/[0.04] mt-0">
              <div className="grid grid-cols-3 sm:grid-cols-4 gap-x-5 gap-y-2.5">
                {([
                  ["Entry", formatCryptoPrice(kpos.entry_price)],
                  ["Current", formatCryptoPrice(kpos.current_price)],
                  ["Size", formatCurrency(kpos.size_usd)],
                  ["Qty", kpos.qty.toFixed(4)],
                  ["Stop loss", formatCryptoPrice(kpos.stop_loss_price)],
                  ["Trail trigger", formatCryptoPrice(kpos.take_profit_price)],
                  ...(conviction != null ? [["Conviction", `${Math.round(conviction * 100)}%`]] : []),
                  ...(hoursIn != null ? [["Age", `${hoursIn.toFixed(0)}h · ${ageLabel}`]] : []),
                ] as [string, string][]).map(([label, value]) => (
                  <div key={label}>
                    <div className="text-[8px] text-muted-foreground/40 uppercase tracking-wide">{label}</div>
                    <div className="text-[10px] font-mono text-white/80 font-semibold mt-0.5">{value}</div>
                  </div>
                ))}
              </div>
              <div className="mt-2 text-[9px] text-cyan-400/40 italic">Mean-reversion · auto-managed by Davy Jones</div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── KrakenPositionsPanel — collapsible section for all Kraken open positions ──
// Used below the Alpaca positions table in LivePositionsSection.
function KrakenPositionsPanel({
  positions,
  signals,
  isPaper,
}: {
  positions: { symbol: string; side: string; qty: number; entry_price: number; current_price: number; size_usd: number; unrealized_pnl_usd: number; unrealized_pnl_pct: number; entry_time: string; best_price: number; stop_loss_price: number; take_profit_price: number }[];
  signals?: any[];
  isPaper?: boolean;
}) {
  const [open, setOpen] = useState(true);
  if (positions.length === 0) return null;

  const totalPnl = positions.reduce((sum, p) => sum + (p.unrealized_pnl_usd ?? 0), 0);
  const isPnlUp  = totalPnl >= 0;

  return (
    <div className="border-t border-white/[0.04] bg-cyan-950/[0.03]">
      {/* Section header / toggle */}
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full px-4 py-2 flex items-center gap-2 text-left hover:bg-cyan-500/[0.04] transition-colors"
      >
        <span className="text-[9px] uppercase font-semibold tracking-wider text-cyan-400/60">⚓ Davy Jones</span>
        <Badge variant="outline" className="text-[8px] px-1 py-0 border-cyan-500/20 text-cyan-400/50">{positions.length}</Badge>
        {isPaper && <Badge variant="outline" className="text-[8px] px-1 py-0 border-amber-500/20 text-amber-400/50">PAPER</Badge>}
        <span className="text-[9px] text-muted-foreground/30 ml-1">crypto positions</span>
        <span className={cn("ml-auto text-[11px] font-mono font-semibold tabular-nums", isPnlUp ? "text-green-400" : "text-red-400")}>
          {isPnlUp ? "+" : ""}${totalPnl.toFixed(2)}
        </span>
        <span className={cn("text-muted-foreground/30 text-[10px] transition-transform duration-200 ml-2", open && "rotate-180")}>▾</span>
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 space-y-1.5">
              {positions.map((kpos) => (
                <KrakenPositionCard key={kpos.symbol} kpos={kpos} signals={signals} isPaper={isPaper} />
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Health score colour map (shared by table + card) ─────────────────────────
const HEALTH_COLOR_MAP: Record<string, string> = {
  green: "#22c55e", emerald: "#10b981", amber: "#f59e0b", orange: "#f97316", red: "#ef4444",
};

// ── AlpacaPositionCard — collapsible row for one Alpaca equity position ────────
// Mirrors KrakenPositionCard layout so both sections look consistent.
function AlpacaPositionCard({
  pos,
  onThesisClick,
  onEject,
  confirmClose,
  setConfirmClose,
  isClosing,
  isRebalancing,
  closingSymbol,
  compact = false,
}: {
  pos: LivePosition;
  onThesisClick: (ticker: string, thesis: string | null) => void;
  onEject: (symbol: string) => void;
  confirmClose: string | null;
  setConfirmClose: (s: string | null) => void;
  isClosing: boolean;
  isRebalancing: boolean;
  closingSymbol: string | null;
  compact?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const isShort = (pos.side ?? "long").toLowerCase() === "short";
  const isBearHedge = (pos.asset_class ?? "").toLowerCase() === "bear_hedge";
  // For short positions, P&L logic is the same (negative pl = loss, positive = gain from short)
  const isUp  = pos.unrealized_pl >= 0;
  const pnlPct = (pos.unrealized_plpc ?? 0) * 100;

  return (
    <div
      onClick={() => setExpanded(v => !v)}
      className={cn(
        "rounded-lg border cursor-pointer select-none transition-all duration-200",
        isShort
          ? "border-red-500/25 bg-red-950/[0.08] hover:bg-red-950/20"
          : isUp
            ? "border-green-500/20 bg-green-950/[0.07] hover:bg-green-950/20"
            : "border-red-500/15 bg-red-950/[0.07] hover:bg-red-950/20"
      )}
    >
      {/* ── Collapsed header ── */}
      <div className={cn("flex items-center gap-2 px-3 overflow-hidden", compact ? "py-1.5" : "py-2")}>
        <span className={cn(
          "w-0.5 h-4 rounded-full shrink-0",
          isShort ? "bg-red-500/70" : isUp ? "bg-green-500/70" : "bg-red-400/60"
        )} />
        <span className="font-bold font-mono text-white text-[11px] w-12 shrink-0">{pos.symbol}</span>
        {isBearHedge && (
          <span className="text-[7px] font-bold px-1.5 py-0.5 rounded-full border text-orange-400 border-orange-500/30 bg-orange-500/10 shrink-0">
            BEAR
          </span>
        )}
        {!isBearHedge && !isShort && (
          <span className="text-[7px] font-bold px-1.5 py-0.5 rounded-full border text-orange-400 border-orange-500/30 bg-orange-500/10 shrink-0">
            DEGEN
          </span>
        )}
        {isShort ? (
          <span className="text-[8px] font-bold px-1.5 py-0.5 rounded-full border text-red-300 border-red-500/40 bg-red-500/15 shrink-0">
            SHORT
          </span>
        ) : (
          <span className="text-[8px] font-bold px-1.5 py-0.5 rounded-full border text-green-400 border-green-500/30 bg-green-500/10 shrink-0">
            LONG
          </span>
        )}
        <MarketStatusBadge symbol={pos.symbol} isCrypto={isAssetCrypto(pos.symbol)} />
        {/* P&L */}
        <span className={cn("font-mono font-semibold text-[10px] flex-1 tabular-nums", isUp ? "text-green-400" : "text-red-400")}>
          {isUp ? "+" : ""}{formatCurrency(pos.unrealized_pl)}
          <span className="text-[8px] opacity-60 ml-1">({isUp ? "+" : ""}{pnlPct.toFixed(2)}%)</span>
        </span>
        {/* Conviction */}
        {pos.conviction_score != null && (
          <span className={cn(
            "text-[9px] font-mono shrink-0 hidden sm:inline",
            pos.conviction_score >= 0.8 ? "text-green-400/60" : pos.conviction_score >= 0.75 ? "text-primary/60" : "text-amber-400/60"
          )}>
            {Math.round(pos.conviction_score * 100)}%
          </span>
        )}
        {/* Health label */}
        {pos.health_score && (() => {
          const c = HEALTH_COLOR_MAP[pos.health_score.color] || pos.health_score.color;
          return (
            <span
              className="text-[8px] px-1.5 py-0.5 rounded-full border shrink-0 hidden sm:inline"
              style={{ color: c, borderColor: c + "30", backgroundColor: c + "15" }}
            >
              {pos.health_score.label}
            </span>
          );
        })()}
        {/* Stop loss */}
        {pos.stop_loss_price != null && (
          <span className="text-[9px] font-mono text-red-400/55 shrink-0 hidden sm:inline">
            SL {formatCurrency(pos.stop_loss_price)}
          </span>
        )}
        <span className={cn("text-muted-foreground/30 text-[10px] transition-transform duration-200 shrink-0", expanded && "rotate-180")}>▾</span>
      </div>

      {/* ── Expanded detail grid ── */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18 }}
            className="overflow-hidden"
            onClick={e => e.stopPropagation()}
          >
            <div className="px-4 pb-3 pt-2 border-t border-white/[0.04]">
              <div className="grid grid-cols-3 sm:grid-cols-4 gap-x-5 gap-y-2.5">
                {([
                  ["Entry",   formatCurrency(pos.avg_entry_price)],
                  ["Current", formatCurrency(pos.current_price)],
                  ["Notional", formatCurrency(pos.market_value)],
                  ["Qty",     pos.qty.toFixed(4)],
                  pos.stop_loss_price  != null ? ["Stop loss",     formatCurrency(pos.stop_loss_price)]  : null,
                  pos.take_profit_price != null ? ["Trail trigger", formatCurrency(pos.take_profit_price)] : null,
                  pos.conviction_score != null
                    ? ["Conviction", `${Math.round(pos.conviction_score * 100)}%`]
                    : null,
                  pos.health_score
                    ? ["Health", `${pos.health_score.score} · ${pos.health_score.label}`]
                    : null,
                ] as ([string, string] | null)[])
                  .filter((x): x is [string, string] => x !== null)
                  .map(([label, value]) => (
                    <div key={label}>
                      <div className="text-[8px] text-muted-foreground/40 uppercase tracking-wide">{label}</div>
                      <div className="text-[10px] font-mono text-white/80 font-semibold mt-0.5">{value}</div>
                    </div>
                  ))}
              </div>

              {/* Thesis */}
              {pos.original_thesis && (
                <div
                  className="mt-3 cursor-pointer"
                  onClick={() => onThesisClick(pos.symbol, pos.original_thesis)}
                >
                  <div className="text-[8px] text-muted-foreground/40 uppercase tracking-wide mb-0.5">Thesis</div>
                  <p className="text-[10px] text-indigo-300/70 line-clamp-2 border-b border-dashed border-indigo-500/20 hover:text-indigo-300 transition-colors leading-snug">
                    {pos.original_thesis}
                  </p>
                </div>
              )}

              {/* Eject */}
              <div className="mt-3 flex justify-end">
                {closingSymbol === pos.symbol ? (
                  <div className="flex items-center gap-1 text-[10px] text-orange-400/70">
                    <RefreshCw className="h-3 w-3 animate-spin" />
                    <span>Closing…</span>
                  </div>
                ) : confirmClose === pos.symbol ? (
                  <div className="flex items-center gap-2">
                    <span className="text-[9px] text-orange-300/80">Close &amp; re-enter?</span>
                    <button
                      onClick={() => onEject(pos.symbol)}
                      className="text-[9px] font-bold px-2 py-0.5 rounded bg-orange-500/20 text-orange-400 border border-orange-500/30 hover:bg-orange-500/35 transition-colors"
                    >
                      Yes
                    </button>
                    <button
                      onClick={() => setConfirmClose(null)}
                      className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-slate-800 text-muted-foreground border border-white/10 hover:bg-slate-700 transition-colors"
                    >
                      No
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setConfirmClose(pos.symbol)}
                    disabled={isClosing || isRebalancing}
                    className={cn(
                      "flex items-center gap-1 text-[9px] font-semibold uppercase tracking-wide px-2.5 py-1.5 rounded-lg border transition-all duration-200",
                      isClosing || isRebalancing
                        ? "opacity-40 cursor-not-allowed border-white/10 text-muted-foreground"
                        : "border-orange-500/20 bg-orange-500/5 text-orange-400/60 hover:bg-orange-500/15 hover:text-orange-400 hover:border-orange-500/40"
                    )}
                  >
                    <LogOut className="h-2.5 w-2.5" />
                    <span>Eject</span>
                  </button>
                )}
              </div>

              <div className="mt-1 text-[9px] text-green-400/30 italic">AI conviction · managed by Degen Oracle</div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── AlpacaPositionsPanel — collapsible section for all Alpaca open positions ───
function AlpacaPositionsPanel({
  positions,
  onThesisClick,
  onEject,
  confirmClose,
  setConfirmClose,
  isClosing,
  isRebalancing,
  closingSymbol,
}: {
  positions: LivePosition[];
  onThesisClick: (ticker: string, thesis: string | null) => void;
  onEject: (symbol: string) => void;
  confirmClose: string | null;
  setConfirmClose: (s: string | null) => void;
  isClosing: boolean;
  isRebalancing: boolean;
  closingSymbol: string | null;
}) {
  const [open, setOpen] = useState(true);
  if (positions.length === 0) return null;

  const longPositions  = positions.filter(p => (p.side ?? "long").toLowerCase() !== "short");
  const shortPositions = positions.filter(p => (p.side ?? "long").toLowerCase() === "short");
  const totalPnl  = positions.reduce((sum, p) => sum + p.unrealized_pl, 0);
  const shortPnl  = shortPositions.reduce((sum, p) => sum + p.unrealized_pl, 0);
  const shortExposure = shortPositions.reduce((sum, p) => sum + Math.abs(p.market_value), 0);
  const isPnlUp  = totalPnl >= 0;

  return (
    <div className="bg-orange-950/[0.02]">
      {/* Section header */}
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full px-4 py-2 flex items-center gap-2 text-left hover:bg-orange-500/[0.04] transition-colors"
      >
        <span className="text-[9px] uppercase font-semibold tracking-wider text-orange-400/60">⚡ Degen Oracle</span>
        <Badge variant="outline" className="text-[8px] px-1 py-0 border-orange-500/20 text-orange-400/50">
          {positions.length}
        </Badge>
        <span className="text-[9px] text-muted-foreground/30 ml-1">equity positions</span>
        {shortPositions.length > 0 && (
          <Badge variant="outline" className="text-[8px] px-1 py-0 border-red-500/30 text-red-400/70 ml-1">
            {shortPositions.length} short
          </Badge>
        )}
        <span className={cn("ml-auto text-[11px] font-mono font-semibold tabular-nums", isPnlUp ? "text-green-400" : "text-red-400")}>
          {isPnlUp ? "+" : ""}{formatCurrency(totalPnl)}
        </span>
        <span className={cn("text-muted-foreground/30 text-[10px] transition-transform duration-200 ml-2", open && "rotate-180")}>▾</span>
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            {/* Algo Short Scanner Stats Bar */}
            {shortPositions.length > 0 && (
              <div className="mx-3 mb-2 px-3 py-2 rounded-lg border border-purple-500/20 bg-purple-950/[0.12]">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-[8px] font-bold uppercase tracking-wider text-purple-400/70">Bear Scanner</span>
                    <span className="text-[8px] text-muted-foreground/40">{shortPositions.length} algo short{shortPositions.length > 1 ? "s" : ""}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-[9px] font-mono text-muted-foreground/50">
                      Exposure: {formatCurrency(shortExposure)}
                    </span>
                    <span className={cn("text-[9px] font-mono font-semibold tabular-nums", shortPnl >= 0 ? "text-green-400" : "text-red-400")}>
                      {shortPnl >= 0 ? "+" : ""}{formatCurrency(shortPnl)}
                    </span>
                  </div>
                </div>
              </div>
            )}

            <div className="px-3 pb-3 space-y-1.5">
              {/* Render longs first, then shorts */}
              {longPositions.map((pos) => (
                <AlpacaPositionCard
                  key={pos.symbol}
                  pos={pos}
                  onThesisClick={onThesisClick}
                  onEject={onEject}
                  confirmClose={confirmClose}
                  setConfirmClose={setConfirmClose}
                  isClosing={isClosing}
                  isRebalancing={isRebalancing}
                  closingSymbol={closingSymbol}
                />
              ))}
              {shortPositions.map((pos) => (
                <AlpacaPositionCard
                  key={pos.symbol}
                  pos={pos}
                  onThesisClick={onThesisClick}
                  onEject={onEject}
                  confirmClose={confirmClose}
                  setConfirmClose={setConfirmClose}
                  isClosing={isClosing}
                  isRebalancing={isRebalancing}
                  closingSymbol={closingSymbol}
                />
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── RollingPnl — animated unrealised P&L cell ─────────────────────────────────
// Smoothly animates between value changes. Pulses with a glow every 10 seconds
// and slides digits down from above on each tick, giving a live-feed odometer feel.
function RollingPnl({ value, pct }: { value: number; pct: number }) {
  const prevRef  = useRef(value);
  const rafRef   = useRef<number | null>(null);
  const [displayed, setDisplayed] = useState(value);
  const [animKey, setAnimKey]     = useState(0);
  const [glowing, setGlowing]     = useState(false);

  const animateTo = useCallback((from: number, to: number) => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    const duration = 800;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplayed(from + (to - from) * eased);
      if (t < 1) rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
  }, []);

  const flash = useCallback(() => {
    setGlowing(true);
    setTimeout(() => setGlowing(false), 700);
  }, []);

  // Animate when the external value changes (API refresh)
  useEffect(() => {
    if (value !== prevRef.current) {
      animateTo(prevRef.current, value);
      prevRef.current = value;
      setAnimKey(k => k + 1);
      flash();
    }
  }, [value, animateTo, flash]);

  // 10-second heartbeat: nudge digits so the roll is always visible
  useEffect(() => {
    const id = setInterval(() => {
      const nudge = Math.abs(value) > 0.01 ? value * 0.0004 : 0.01;
      animateTo(value - nudge, value);
      setAnimKey(k => k + 1);
      flash();
    }, 10_000);
    return () => {
      clearInterval(id);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [value, animateTo, flash]);

  const isUp   = value >= 0;
  const sign   = isUp ? "+" : "";
  const glow   = isUp ? "rgba(34,197,94,0.85)" : "rgba(239,68,68,0.85)";
  const pctAbs = Math.abs(pct * 100).toFixed(2);

  return (
    <div
      className="flex flex-col items-end transition-[filter] duration-300"
      style={glowing ? { filter: `drop-shadow(0 0 5px ${glow})` } : undefined}
    >
      <motion.span
        key={animKey}
        initial={{ y: -8, opacity: 0.3 }}
        animate={{ y: 0,  opacity: 1   }}
        transition={{ duration: 0.3, ease: "easeOut" }}
        className={cn(
          "text-xs font-mono font-semibold tabular-nums tracking-tight",
          isUp ? "text-green-400" : "text-red-400"
        )}
      >
        {sign}{formatCurrency(displayed)}
      </motion.span>
      <span className={cn(
        "text-[10px] font-mono opacity-70 tabular-nums",
        isUp ? "text-green-400" : "text-red-400"
      )}>
        {isUp ? "+" : "-"}{pctAbs}%
      </span>
    </div>
  );
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

const CRYPTO_SYMBOLS = new Set(["BTC", "ETH", "SOL", "ATOM", "AVAX", "LINK", "DOT", "ADA", "XRP", "DOGE", "LTC", "UNI", "AAVE", "MATIC", "BNB", "XLM", "ALGO", "NEAR", "FTM", "ARB"]);
function isAssetCrypto(symbol: string): boolean {
  const base = symbol.replace(/[/\-]?USD[TC]?$/, "").toUpperCase();
  return CRYPTO_SYMBOLS.has(base);
}
function isNYSEOpen(): boolean {
  const now = new Date();
  const etStr = now.toLocaleString("en-US", { timeZone: "America/New_York" });
  const et = new Date(etStr);
  const day = et.getDay();
  if (day === 0 || day === 6) return false;
  const totalMin = et.getHours() * 60 + et.getMinutes();
  return totalMin >= 570 && totalMin < 960;
}
function MarketStatusBadge({ symbol, isCrypto }: { symbol: string; isCrypto: boolean }) {
  const open = isCrypto || isNYSEOpen();
  if (isCrypto) {
    return (
      <span className="flex items-center gap-0.5 text-[7px] font-bold px-1 py-0.5 rounded border border-cyan-500/25 text-cyan-400/70 shrink-0">
        <span className="relative flex h-1 w-1 mr-0.5">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-60" />
          <span className="relative inline-flex rounded-full h-1 w-1 bg-cyan-400" />
        </span>
        24/7
      </span>
    );
  }
  if (open) {
    return (
      <span className="flex items-center gap-0.5 text-[7px] font-bold px-1 py-0.5 rounded border border-green-500/25 text-green-400/70 shrink-0">
        <span className="relative flex h-1 w-1 mr-0.5">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-60" />
          <span className="relative inline-flex rounded-full h-1 w-1 bg-green-400" />
        </span>
        NYSE
      </span>
    );
  }
  return (
    <span className="flex items-center gap-0.5 text-[7px] font-medium px-1 py-0.5 rounded border border-slate-600/40 text-slate-500 shrink-0">
      <span className="inline-flex rounded-full h-1 w-1 bg-slate-600 mr-0.5" />
      CLOSED
    </span>
  );
}

function SystemStatusBanner() {
  const { data, isError } = usePlatformStatus();

  // Three distinct states:
  //   "offline"  — API is unreachable (genuine network/server failure) → RED
  //   "ai_degraded" — API responded but Groq regime cache is being used → AMBER (not red)
  //   "degraded" — API up, but pipeline/scheduler has errors → AMBER
  //   "online"   — Everything healthy → GREEN
  let sysStatus: "online" | "degraded" | "ai_degraded" | "offline";
  let reason: string;
  let tradingMode: string | undefined;

  const groqPct = data?.groq?.pct_used ?? 0;
  const groqUsed = data?.groq?.tokens_used_today ?? 0;
  const groqTotal = data?.groq?.token_budget_total ?? 100000;
  const groqRemaining = Math.max(0, groqTotal - groqUsed);
  const groqExhausted = data?.groq?.budget_exhausted ?? false;
  const groqBudgetColor =
    groqExhausted     ? "text-red-400" :
    groqPct >= 90     ? "text-red-400" :
    groqPct >= 70     ? "text-amber-400" :
    groqUsed > 0      ? "text-emerald-400" :
    "text-zinc-500";
  const groqBarColor =
    groqExhausted || groqPct >= 90 ? "bg-red-500" :
    groqPct >= 70 ? "bg-amber-400" :
    "bg-emerald-500";
  const groqRemainingLabel = groqExhausted
    ? "EXHAUSTED"
    : groqRemaining >= 1000
      ? `${Math.round(groqRemaining / 1000)}k left`
      : `${groqRemaining} left`;
  const showBudgetMeter = data?.groq != null;

  if (isError || !data) {
    sysStatus = "offline";
    reason = "Cannot reach trading API — check that the server is running";
  } else {
    const jobCount = data.scheduler_jobs.length;
    const lastStatus = data.last_run.last_run_status;
    const errorCount = data.last_run.error_count;
    tradingMode = data.trading_mode;
    const groqFallback = data.groq?.using_fallback ?? false;

    if (jobCount < EXPECTED_JOBS) {
      sysStatus = "degraded";
      reason = `Only ${jobCount}/${EXPECTED_JOBS} scheduler jobs registered`;
    } else if (["error", "analysis_failed", "execution_failed", "kill_switch_tripped"].includes(lastStatus)) {
      sysStatus = "degraded";
      reason = `Last run failed (${errorCount} total error${errorCount !== 1 ? "s" : ""})`;
    } else if (groqFallback) {
      // Groq hit its daily token limit — we're using a cached regime to keep trading.
      // This is NOT an outage. Show amber to distinguish from genuine red failures.
      sysStatus = "ai_degraded";
      const cachedRegime = data.groq?.regime ? ` [${data.groq.regime}]` : "";
      const ageMin = data.groq?.cache_age_min != null ? ` · ${Math.round(data.groq.cache_age_min)}min ago` : "";
      reason = `Groq rate-limited — using cached regime${cachedRegime}${ageMin} · Trading continues normally`;
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

  const BudgetMeter = showBudgetMeter ? (
    <span
      className="ml-auto flex items-center gap-3 flex-shrink-0"
      title={`Groq session tokens: ${groqUsed.toLocaleString()} used / ${groqTotal.toLocaleString()} total · Resets at midnight UTC`}
    >
      {/* Gemini indicator */}
      <span className="hidden sm:flex items-center gap-1 text-[10px] font-mono text-violet-400/60 flex-shrink-0">
        <span className="w-1 h-1 rounded-full bg-violet-400/50 flex-shrink-0" />
        <span>Gemini</span>
        <span className="text-violet-400/35">pre-mkt</span>
      </span>
      {/* Groq countdown meter */}
      <span className="flex flex-col gap-0.5 flex-shrink-0">
        <span className="flex items-center gap-1.5">
          <span className="text-[9px] uppercase font-semibold tracking-wider text-zinc-600">Groq</span>
          <span className={cn("text-[10px] font-mono font-semibold tabular-nums", groqBudgetColor)}>
            {groqRemainingLabel}
          </span>
        </span>
        <span className="w-20 h-1 bg-zinc-800 rounded-full overflow-hidden flex-shrink-0">
          <span
            className={cn("h-full rounded-full transition-all duration-700", groqBarColor)}
            style={{ width: `${Math.min(groqPct, 100)}%` }}
          />
        </span>
      </span>
    </span>
  ) : null;

  if (sysStatus === "online") {
    return (
      <div className="sticky top-14 z-30 w-full bg-green-500/8 border-b border-green-500/15 backdrop-blur-md">
        <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 min-h-[2rem] py-1.5 md:py-0 md:h-8 flex flex-wrap items-center gap-x-2 gap-y-0.5">
          <span className="relative flex h-1.5 w-1.5 flex-shrink-0">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-500 opacity-75" />
            <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-green-500" />
          </span>
          <span className="text-xs text-green-400 font-medium">ONLINE</span>
          <span className="text-xs text-green-500/60 break-words">— {reason}</span>
          {tradingMode && !showBudgetMeter && (
            <span className={cn("text-xs font-mono ml-auto", tradingModeColor(tradingMode))}>
              {tradingModeLabel(tradingMode)}
            </span>
          )}
          {tradingMode && showBudgetMeter && (
            <span className={cn("text-xs font-mono", tradingModeColor(tradingMode))}>
              {tradingModeLabel(tradingMode)}
            </span>
          )}
          {BudgetMeter}
        </div>
      </div>
    );
  }

  if (sysStatus === "ai_degraded") {
    return (
      <div className="sticky top-14 z-30 w-full bg-amber-500/8 border-b border-amber-500/15 backdrop-blur-md">
        <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 min-h-[2rem] py-1.5 md:py-0 md:h-8 flex flex-wrap items-center gap-x-2 gap-y-0.5">
          <Brain className="h-3.5 w-3.5 text-amber-400 flex-shrink-0" />
          <span className="text-xs text-amber-400 font-medium">AI DEGRADED</span>
          <span className="text-xs text-amber-500/70 break-words">— {reason}</span>
          {tradingMode && (
            <span className={cn("text-xs font-mono", tradingModeColor(tradingMode))}>
              {tradingModeLabel(tradingMode)}
            </span>
          )}
          {BudgetMeter}
        </div>
      </div>
    );
  }

  if (sysStatus === "degraded") {
    return (
      <div className="sticky top-14 z-30 w-full bg-amber-500/10 border-b border-amber-500/20 backdrop-blur-md">
        <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 min-h-[2rem] py-1.5 md:py-0 md:h-8 flex flex-wrap items-center gap-x-2 gap-y-0.5">
          <AlertTriangle className="h-3.5 w-3.5 text-amber-400 flex-shrink-0" />
          <span className="text-xs text-amber-400 font-medium">DEGRADED</span>
          <span className="text-xs text-amber-500/70 break-words">— {reason}</span>
          {BudgetMeter}
        </div>
      </div>
    );
  }

  return (
    <div className="sticky top-14 z-30 w-full bg-red-500/10 border-b border-red-500/20 backdrop-blur-md">
      <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 min-h-[2rem] py-1.5 md:py-0 md:h-8 flex flex-wrap items-center gap-x-2 gap-y-0.5">
        <WifiOff className="h-3.5 w-3.5 text-red-400 flex-shrink-0" />
        <span className="text-xs text-red-400 font-medium">OFFLINE</span>
        <span className="text-xs text-red-500/70 break-words">— {reason}</span>
      </div>
    </div>
  );
}

// ── Header ────────────────────────────────────────────────────────────────────

function Header() {
  const { data: status } = usePlatformStatus();

  return (
    <header className="sticky top-0 z-40 w-full bg-slate-950/90 backdrop-blur-md border-b border-white/5">
      <div className="max-w-[1600px] mx-auto px-3 sm:px-6 lg:px-8 h-14 flex items-center justify-between">
        <div className="flex items-center gap-2 sm:gap-3">
          <div className="h-7 w-7 rounded-lg bg-primary/20 border border-primary/40 flex items-center justify-center flex-shrink-0">
            <Activity className="h-4 w-4 text-primary" />
          </div>
          <h1 className="text-sm sm:text-lg font-bold tracking-tight text-white">
            <span className="md:hidden">QT</span>
            <span className="hidden md:inline">Quant Terminal</span>
          </h1>
        </div>

        <div className="flex items-center gap-2 sm:gap-3">
          {/* AlgoEdge SaaS switcher */}
          <a
            href="/saas/"
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-indigo-500/40 bg-indigo-500/10 text-indigo-400 text-xs font-semibold hover:bg-indigo-500/20 hover:border-indigo-500/60 transition-all select-none"
            title="Switch to AlgoEdge SaaS Platform"
          >
            <span className="inline-flex items-center justify-center w-4 h-4 rounded bg-indigo-600 text-white text-[9px] font-black">AE</span>
            <span className="hidden sm:inline">AlgoEdge</span>
            <ExternalLink className="h-3 w-3 opacity-70" />
          </a>

          <EmergencyHeaderButtons />

          <div className="h-6 w-px bg-white/8 hidden md:block" />

          <div className="hidden md:flex items-center gap-5">
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

          {/* Mobile: compact market + kill switch indicators */}
          <div className="flex md:hidden items-center gap-1.5">
            {status?.market.is_open ? (
              <span className="relative flex h-2 w-2" title="Market Open">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-green-400" />
              </span>
            ) : (
              <span className="inline-flex rounded-full h-2 w-2 bg-slate-600" title="Market Closed" />
            )}
            {status?.kill_switch.tripped ? (
              <span title="Kill Switch Tripped"><ShieldAlert className="h-3.5 w-3.5 text-red-400" /></span>
            ) : (
              <span title="Kill Switch Armed"><ShieldAlert className="h-3.5 w-3.5 text-green-400/60" /></span>
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
    <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-5 gap-3 sm:gap-4">
      {[0, 1, 2, 3, 4].map(i => <div key={i} className={cn("h-24 rounded-xl bg-card/40 animate-pulse border border-border", i === 0 && "col-span-2 sm:col-span-2 lg:col-span-1")} />)}
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
    <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-5 gap-3 sm:gap-4">
      {/* Total Equity */}
      <Card className={cn(
        "col-span-2 sm:col-span-2 lg:col-span-1",
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
          <RollingCurrency value={data.account.equity} className={cn("fluid-equity font-mono font-bold tracking-tight", isProfit ? "text-green-400 text-glow-success-strong" : "text-red-400 text-glow-danger-strong")} />
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
          <AnimatedCurrency value={data.account.cash} className="fluid-metric font-mono font-bold text-white tracking-tight" />
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
          <AnimatedCurrency value={data.account.buying_power} className="fluid-metric font-mono font-bold text-white tracking-tight" />
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
                "fluid-metric font-mono font-bold tracking-tight",
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
              <div className="fluid-metric font-mono font-bold text-amber-400/40 tracking-tight">$0.00</div>
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
                "fluid-metric font-mono font-bold tracking-tight",
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
              <div className="fluid-metric font-mono font-bold text-muted-foreground/40 tracking-tight">$0.00</div>
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

// ── Combined Portfolio Summary ─────────────────────────────────────────────────
// Shows Alpaca (US Equities) and Kraken (Crypto Bot) side-by-side in one row.
// Alpaca data source: Alpaca brokerage API.  Kraken source: kraken-bot/status.json.
// These are SEPARATE capital pools — the combined total is informational only.

function CombinedPortfolioSummary() {
  const { data: portfolio } = usePortfolio();
  const { data: vault }     = useVault();
  const { data: positions } = useLivePositions();
  const { data: kraken }    = useKrakenStatus();
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
      toast({
        variant: "destructive",
        title: "Export Failed",
        description: err?.message ?? "Could not generate report.",
      });
    }
  };

  // ── Alpaca values ────────────────────────────────────────────────────────────
  const alpacaEquity        = portfolio?.account.equity          ?? 0;
  const alpacaCash          = portfolio?.account.cash            ?? 0;
  const alpacaBuying        = portfolio?.account.buying_power    ?? 0;
  const alpacaInitialMargin = portfolio?.account.initial_margin  ?? 0;
  const alpacaStart         = 100_000;
  const alpacaPnl           = alpacaEquity - alpacaStart;
  const alpacaPnlPct        = (alpacaPnl / alpacaStart) * 100;
  const alpacaProfit        = alpacaPnl >= 0;

  // ── Direct Shorts (algo short scanner) ───────────────────────────────────────
  const SHORT_MARGIN_CAP_PCT = 35;    // mirrors MAX_SHORT_EXPOSURE_PCT in short_scanner.py
  const directShortPositions = positions?.positions?.filter(
    p => String(p.side ?? "long").toLowerCase() === "short" &&
         ["SPY","QQQ","XLK","XLF","XLE","IWM"].includes(p.symbol)
  ) ?? [];
  const shortCount     = directShortPositions.length;
  const shortExposure  = directShortPositions.reduce(
    (sum, p) => sum + Math.abs(Number(p.market_value ?? 0)), 0
  );
  // initial_margin from Alpaca = actual margin required for all short positions.
  // This is the authoritative deployment metric for the 35% cap check.
  const shortMarginUsed    = alpacaInitialMargin;
  const shortMarginPct     = alpacaEquity > 0 ? (shortMarginUsed / alpacaEquity) * 100 : 0;
  const shortMarginCapUsed = Math.min(shortMarginPct / SHORT_MARGIN_CAP_PCT * 100, 100);
  const shortPnl           = directShortPositions.reduce(
    (sum, p) => sum + Number(p.unrealized_pl ?? 0), 0
  );

  const vaultSymbol  = vault?.vault_symbol    ?? "JEPQ";
  const totalVaulted = vault?.total_vaulted_usd ?? 0;
  const vaultPos     = positions?.positions?.find(p => p.symbol === vaultSymbol);
  const vaultValue   = vaultPos?.market_value ?? totalVaulted;
  const vaultPnl     = vaultPos?.unrealized_pl ?? 0;

  // ── Kraken values ─────────────────────────────────────────────────────────────
  const krakenReady       = !!kraken && kraken.status !== "not_started";
  const krakenBotPaused   = kraken?.bot_paused ?? false;
  const krakenEquity      = kraken?.total_equity_usd ?? 0;
  const krakenDeployed    = kraken?.deployed_pct ?? 0;
  const krakenPaper       = kraken?.paper_trading ?? true;
  const krakenPaperSumm   = kraken?.paper_summary;
  const krakenPnl         = krakenPaperSumm?.all_time_pnl_usd ?? 0;
  const krakenTrades      = krakenPaperSumm?.total_trades ?? 0;
  const krakenWins        = krakenPaperSumm?.win_count ?? 0;
  const krakenStart       = krakenPaperSumm?.starting_balance_usd ?? 100_000;
  const krakenWinRate     = krakenTrades > 0 ? (krakenWins / krakenTrades) * 100 : null;
  const krakenPnlPct      = krakenStart > 0 ? (krakenPnl / krakenStart) * 100 : 0;

  // ── Grand total (informational only — two separate capital pools) ─────────────
  const grandTotal = alpacaEquity + (krakenReady ? krakenEquity : 0);

  return (
    <div className="space-y-3">
      {/* Grand total ribbon */}
      <div className="flex items-center justify-between px-1">
        <div className="flex items-center gap-2">
          <span className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">
            Total Portfolio
          </span>
          <span className="text-[9px] font-mono text-muted-foreground/50 bg-white/5 px-1.5 py-0.5 rounded">
            2 exchanges
          </span>
        </div>
        <div className="flex items-center gap-2">
          {portfolio && (
            <span className={cn(
              "text-sm font-mono font-bold tracking-tight",
              alpacaProfit ? "text-green-400" : "text-red-400"
            )}>
              {formatCurrency(grandTotal)}
            </span>
          )}
          <button
            onClick={handleExportReport}
            disabled={exportReport.isPending}
            title="Export full diagnostic report (both bots) — copy to clipboard for LLM analysis"
            className={cn(
              "flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-semibold tracking-wide uppercase transition-all duration-150",
              "bg-blue-950/50 border border-blue-800/40 text-blue-400",
              "hover:bg-blue-600/20 hover:border-blue-500/60 hover:text-blue-300",
              "disabled:opacity-40 disabled:cursor-not-allowed",
              "min-h-[32px]"
            )}
          >
            {exportReport.isPending
              ? <RefreshCw className="h-3 w-3 animate-spin" />
              : <FileDown className="h-3 w-3" />
            }
            <span className="hidden sm:inline">
              {exportReport.isPending ? "Generating…" : "Export Report"}
            </span>
          </button>
        </div>
      </div>

      {/* Two-panel split — Alpaca (5 cards) on left, Kraken (3 cards) on right */}
      <div className="grid grid-cols-1 xl:grid-cols-[5fr_3fr] gap-4">

        {/* ── LEFT: Alpaca US Equities ───────────────────────────────────────── */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-[9px] uppercase tracking-widest text-blue-400/60 font-semibold">Alpaca · US Equities</span>
            <div className="h-px flex-1 bg-blue-500/10" />
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">

            {/* Total Equity */}
            <Card className={cn(
              "col-span-2 sm:col-span-3 lg:col-span-1 bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 relative overflow-hidden transition-all duration-500",
              alpacaProfit ? "hover:border-green-500/30" : "hover:border-red-500/30"
            )}>
              {alpacaProfit
                ? <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-green-500/50 to-transparent" />
                : <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-red-500/50 to-transparent" />
              }
              <CardContent className="p-4">
                <div className="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-1.5">
                  Total Equity
                  {Math.abs(alpacaPnlPct) > 1 && (
                    <motion.span
                      animate={{ scale: [1, 1.2, 1] }}
                      transition={{ duration: 2, repeat: Infinity }}
                      className={cn("text-[9px] font-mono px-1 py-0.5 rounded", alpacaProfit ? "bg-green-500/15 text-green-400" : "bg-red-500/15 text-red-400")}
                    >
                      {alpacaPnl >= 0 ? "+" : ""}{alpacaPnlPct.toFixed(2)}%
                    </motion.span>
                  )}
                </div>
                {portfolio
                  ? <RollingCurrency value={alpacaEquity} className={cn("fluid-equity font-mono font-bold tracking-tight", alpacaProfit ? "text-green-400 text-glow-success-strong" : "text-red-400 text-glow-danger-strong")} />
                  : <div className="h-7 w-28 bg-white/5 rounded animate-pulse" />
                }
                <div className={cn("text-xs mt-1.5 font-medium flex items-center gap-1", alpacaProfit ? "text-green-400/70" : "text-red-400/70")}>
                  {alpacaProfit ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                  {portfolio ? (alpacaPnl >= 0 ? `+${formatCurrency(alpacaPnl)}` : formatCurrency(alpacaPnl)) : "—"}
                </div>
              </CardContent>
            </Card>

            {/* Available Cash */}
            <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-blue-500/20 transition-all duration-500">
              <CardContent className="p-4">
                <div className="text-xs font-medium text-muted-foreground mb-1.5">Available Cash</div>
                {portfolio
                  ? <AnimatedCurrency value={alpacaCash} className="fluid-metric font-mono font-bold text-white tracking-tight" />
                  : <div className="h-6 w-20 bg-white/5 rounded animate-pulse" />
                }
                <div className="text-xs text-muted-foreground mt-1.5">
                  <span className="text-[9px] font-mono text-blue-400/60">
                    {portfolio ? `${((alpacaCash / alpacaEquity) * 100).toFixed(0)}% liquid` : "—"}
                  </span>
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
                {portfolio
                  ? <AnimatedCurrency value={alpacaBuying} className="fluid-metric font-mono font-bold text-white tracking-tight" />
                  : <div className="h-6 w-20 bg-white/5 rounded animate-pulse" />
                }
                <div className="text-xs text-muted-foreground mt-1.5">With margin</div>
              </CardContent>
            </Card>

            {/* Growth Vault */}
            <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-amber-500/25 transition-all duration-500 relative overflow-hidden">
              <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-amber-500/40 to-transparent" />
              <CardContent className="p-4">
                <div className="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-1.5">
                  <Vault className="h-3 w-3 text-amber-400/70" />
                  Growth Vault
                  <span className="text-[9px] font-mono text-amber-400/60 bg-amber-500/10 px-1 rounded">{vaultSymbol}</span>
                </div>
                {vault?.initialised ? (
                  <>
                    <div className={cn("fluid-metric font-mono font-bold tracking-tight", vaultValue > 0 ? "text-amber-400" : "text-amber-400/40")}>
                      {vaultValue > 0 ? formatCurrency(vaultValue) : "$0.00"}
                    </div>
                    <div className="text-[10px] text-muted-foreground mt-1.5 flex items-center gap-1">
                      <ArrowUpRight className="h-3 w-3 text-amber-400/50" />
                      {vault.total_sweeps} sweep{vault.total_sweeps !== 1 ? "s" : ""} · HWM ${(vault.hwm ?? 0).toLocaleString("en-US", { maximumFractionDigits: 0 })}
                    </div>
                  </>
                ) : (
                  <>
                    <div className="fluid-metric font-mono font-bold text-amber-400/40 tracking-tight">$0.00</div>
                    <div className="text-[10px] text-muted-foreground/50 mt-1.5">Awaiting first profit sweep</div>
                  </>
                )}
              </CardContent>
            </Card>

            {/* Total Yield */}
            <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-green-500/20 transition-all duration-500 relative overflow-hidden">
              <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-green-500/30 to-transparent" />
              <CardContent className="p-4">
                <div className="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-1.5">
                  <Coins className="h-3 w-3 text-green-400/70" />
                  Total Yield
                </div>
                {vault?.initialised && vaultPos ? (
                  <>
                    <div className={cn("fluid-metric font-mono font-bold tracking-tight", vaultPnl > 0 ? "text-green-400 text-glow-success" : vaultPnl < 0 ? "text-red-400" : "text-muted-foreground/60")}>
                      {vaultPnl >= 0 ? "+" : ""}{formatCurrency(vaultPnl)}
                    </div>
                    <div className="text-[10px] text-muted-foreground mt-1.5 flex items-center gap-1">
                      <GrowthIcon className="h-3 w-3 text-green-400/50" />
                      Unrealised on {vaultSymbol}
                    </div>
                  </>
                ) : (
                  <>
                    <div className="fluid-metric font-mono font-bold text-muted-foreground/40 tracking-tight">$0.00</div>
                    <div className="text-[10px] text-muted-foreground/50 mt-1.5">{vault?.initialised ? `No ${vaultSymbol} position yet` : "Awaiting first sweep"}</div>
                  </>
                )}
              </CardContent>
            </Card>

            {/* Direct Shorts */}
            <Card className={cn(
              "bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 transition-all duration-500 relative overflow-hidden",
              shortCount > 0
                ? "border-purple-500/30 hover:border-purple-500/50"
                : "hover:border-purple-500/10"
            )}>
              {shortCount > 0 && (
                <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-purple-500/50 to-transparent" />
              )}
              <CardContent className="p-4">
                <div className="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-1.5">
                  <TrendingDown className="h-3 w-3 text-purple-400/70" />
                  Direct Shorts
                  {shortCount > 0 && (
                    <span className="text-[9px] font-mono font-bold px-1 py-0.5 rounded bg-purple-500/15 text-purple-400 border border-purple-500/30">
                      {shortCount}
                    </span>
                  )}
                </div>
                {shortCount > 0 ? (
                  <>
                    <div className={cn(
                      "fluid-metric font-mono font-bold tracking-tight",
                      shortPnl > 0 ? "text-green-400" : shortPnl < 0 ? "text-red-400" : "text-purple-400"
                    )}>
                      {shortPnl >= 0 ? "+" : ""}{formatCurrency(shortPnl)}
                    </div>
                    <div className="text-[10px] text-muted-foreground mt-1.5 space-y-0.5">
                      <div className="flex items-center gap-1 font-mono">
                        <span className="text-purple-400/70">
                          Margin: {formatCurrency(shortMarginUsed)} ({shortMarginPct.toFixed(1)}% of equity)
                        </span>
                      </div>
                      <div className="flex items-center gap-1">
                        <div className="flex-1 h-1 bg-white/5 rounded-full overflow-hidden max-w-[60px]">
                          <div
                            className={cn(
                              "h-full rounded-full transition-all duration-500",
                              shortMarginCapUsed >= 90 ? "bg-red-400" :
                              shortMarginCapUsed >= 70 ? "bg-amber-400" : "bg-purple-400"
                            )}
                            style={{ width: `${shortMarginCapUsed}%` }}
                          />
                        </div>
                        <span className={cn(
                          "text-[9px] font-mono tabular-nums",
                          shortMarginCapUsed >= 90 ? "text-red-400" :
                          shortMarginCapUsed >= 70 ? "text-amber-400" : "text-purple-400/60"
                        )}>
                          {shortMarginCapUsed.toFixed(0)}% of {SHORT_MARGIN_CAP_PCT}% cap
                        </span>
                      </div>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="fluid-metric font-mono font-bold text-purple-400/20 tracking-tight">—</div>
                    <div className="text-[10px] text-muted-foreground/40 mt-1.5">Scanner inactive</div>
                  </>
                )}
              </CardContent>
            </Card>

          </div>
        </div>

        {/* ── RIGHT: Kraken Crypto Bot ─────────────────────────────────────── */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-[9px] uppercase tracking-widest text-cyan-400/60 font-semibold">⚓ Kraken · Crypto Bot</span>
            {krakenPaper && (
              <span className="text-[9px] font-mono font-bold px-1.5 py-0.5 rounded bg-yellow-500/15 text-yellow-400 border border-yellow-500/20 uppercase tracking-wide">
                Paper
              </span>
            )}
            <div className="h-px flex-1 bg-cyan-500/10" />
            {krakenBotPaused && (
              <span className="text-[9px] font-mono font-bold px-1.5 py-0.5 rounded bg-orange-500/15 text-orange-400 border border-orange-500/20 uppercase tracking-wide">
                Paused
              </span>
            )}
            <span className={cn(
              "text-[9px] font-mono",
              krakenReady && !krakenBotPaused ? "text-cyan-400/50" : "text-muted-foreground/30"
            )}>
              {krakenReady ? `cycle #${kraken?.cycle_count ?? 0}` : "not running"}
            </span>
          </div>

          {/* 3 cards in a single row — matches Alpaca section height */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">

            {/* Paper / Live Equity */}
            <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-cyan-500/20 transition-all duration-500 relative overflow-hidden">
              <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-cyan-500/30 to-transparent" />
              <CardContent className="p-3 sm:p-4">
                <div className="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-1.5">
                  {krakenPaper ? "Paper Equity" : "Live Equity"}
                </div>
                {krakenReady ? (
                  <>
                    <AnimatedCurrency
                      value={krakenEquity}
                      className={cn("fluid-metric font-mono font-bold tracking-tight", krakenPnl >= 0 ? "text-cyan-400" : "text-red-400")}
                    />
                    <div className={cn("text-xs mt-1.5 flex items-center gap-1 font-medium", krakenPnl >= 0 ? "text-cyan-400/70" : "text-red-400/70")}>
                      {krakenPnl >= 0 ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                      {krakenPnl >= 0 ? "+" : ""}{formatCurrency(krakenPnl)}
                      {krakenPnlPct !== 0 && (
                        <span className={cn("text-[9px] font-mono px-1 py-0.5 rounded", krakenPnl >= 0 ? "bg-cyan-500/10 text-cyan-400" : "bg-red-500/10 text-red-400")}>
                          {krakenPnlPct >= 0 ? "+" : ""}{krakenPnlPct.toFixed(2)}%
                        </span>
                      )}
                    </div>
                  </>
                ) : (
                  <>
                    <div className="fluid-metric font-mono font-bold text-muted-foreground/30 tracking-tight">—</div>
                    <div className="text-[10px] text-muted-foreground/40 mt-1.5">Start bot to track</div>
                  </>
                )}
              </CardContent>
            </Card>

            {/* Deployed Capital */}
            <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-cyan-500/15 transition-all duration-500">
              <CardContent className="p-3 sm:p-4">
                <div className="text-xs font-medium text-muted-foreground mb-1.5">Deployed</div>
                {krakenReady ? (
                  <>
                    <div className="fluid-metric font-mono font-bold text-white tracking-tight">
                      {krakenDeployed.toFixed(0)}<span className="text-xs text-muted-foreground font-normal">%</span>
                    </div>
                    <div className="mt-2 h-1 rounded-full bg-white/5 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-cyan-500/50 transition-all duration-700"
                        style={{ width: `${Math.min(krakenDeployed, 100)}%` }}
                      />
                    </div>
                    <div className="text-[9px] text-muted-foreground/50 mt-1">
                      {kraken?.position_count ?? 0}/{kraken?.max_positions ?? 3} positions
                    </div>
                  </>
                ) : (
                  <>
                    <div className="fluid-metric font-mono font-bold text-muted-foreground/30">—</div>
                    <div className="mt-2 h-1 rounded-full bg-white/5" />
                    <div className="text-[9px] text-muted-foreground/30 mt-1">0/3 positions</div>
                  </>
                )}
              </CardContent>
            </Card>

            {/* Win Rate */}
            <Card className="bg-gradient-to-br from-slate-900 to-slate-950 border-white/5 hover:border-cyan-500/15 transition-all duration-500">
              <CardContent className="p-3 sm:p-4">
                <div className="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-1">
                  Win Rate
                  <Trophy className="h-3 w-3 text-yellow-400/50" />
                </div>
                {krakenReady && krakenWinRate !== null ? (
                  <>
                    <div className="fluid-metric font-mono font-bold text-white tracking-tight">
                      {krakenWinRate.toFixed(0)}<span className="text-xs text-muted-foreground font-normal">%</span>
                    </div>
                    <div className="text-[10px] text-muted-foreground mt-1.5">
                      {krakenWins}W · {krakenTrades - krakenWins}L · {krakenTrades} total
                    </div>
                  </>
                ) : (
                  <>
                    <div className="fluid-metric font-mono font-bold text-muted-foreground/30">—</div>
                    <div className="text-[10px] text-muted-foreground/40 mt-1.5">No trades yet</div>
                  </>
                )}
              </CardContent>
            </Card>

          </div>
        </div>

      </div>
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
  theme = "indigo", title = "Oracle Dispatch", infoNote,
}: {
  commentary: string | undefined;
  generatedAt: string | null | undefined;
  cached: boolean | undefined;
  cacheAge: number | undefined;
  thinking: boolean;
  onRefresh: () => void;
  isRefreshing: boolean;
  theme?: "indigo" | "cyan";
  title?: string;
  infoNote?: string;
}) {
  const ageMin = cacheAge != null ? Math.round(cacheAge / 60) : null;
  const textRef = useRef<HTMLParagraphElement>(null);
  const isCyan = theme === "cyan";

  useEffect(() => {
    if (!thinking && textRef.current) {
      textRef.current.style.animation = "none";
      void textRef.current.offsetHeight;
      textRef.current.style.animation = "";
    }
  }, [commentary, thinking]);

  return (
    <div className="relative flex-1 min-w-0">
      {/* Arrow pointing left toward the bot avatar */}
      <div className="absolute left-0 top-1/2 -translate-x-3 -translate-y-1/2 w-3 h-4 overflow-hidden">
        <div className={cn(
          "absolute inset-0 border-r border-b bg-slate-900 rotate-[135deg] origin-top-right scale-75",
          isCyan ? "border-cyan-500/40" : "border-indigo-500/40"
        )} />
      </div>

      <div className={cn(
        "relative rounded-2xl border bg-slate-900/80 backdrop-blur-sm overflow-hidden",
        isCyan
          ? "border-cyan-500/30 shadow-[0_0_30px_rgba(6,182,212,0.08)]"
          : "border-indigo-500/30 shadow-[0_0_30px_rgba(99,102,241,0.08)]"
      )}>
        {/* Top accent line */}
        <div className={cn(
          "h-px bg-gradient-to-r to-transparent",
          isCyan ? "from-cyan-500/60 via-teal-400/40" : "from-indigo-500/60 via-violet-400/40"
        )} />

        <div className="px-5 py-4">
          <div className="flex items-center gap-2 mb-3">
            <motion.div
              animate={{ scale: [1, 1.15, 1], opacity: [0.7, 1, 0.7] }}
              transition={{ duration: 1.8, repeat: Infinity, ease: "easeInOut" }}
            >
              {isCyan
                ? <span className="text-sm">⚓</span>
                : <Sparkles className="h-3.5 w-3.5 text-violet-400" />
              }
            </motion.div>
            <span className={cn(
              "text-[10px] uppercase font-semibold tracking-wider",
              isCyan ? "text-cyan-400" : "text-violet-400"
            )}>
              {title}
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
                    className={cn("w-1.5 h-1.5 rounded-full", isCyan ? "bg-cyan-400" : "bg-indigo-400")}
                    animate={{ y: [0, -5, 0], opacity: [0.4, 1, 0.4] }}
                    transition={{ duration: 0.8, repeat: Infinity, delay: i * 0.18, ease: "easeInOut" }}
                  />
                ))}
                <span className="text-[11px] text-muted-foreground ml-1">Thinking…</span>
              </div>
            ) : commentary ? (
              <p ref={textRef} className="text-[11px] leading-relaxed text-slate-300 font-light">
                {commentary}
              </p>
            ) : (
              <p className="text-[11px] text-muted-foreground/50 italic">
                Updates when positions change — click Refresh to generate now.
              </p>
            )}
          </div>

          {/* Info note (e.g. narrative paused) */}
          {infoNote && !thinking && (
            <div className={cn(
              "mt-2 flex items-center gap-1.5 text-[9px] font-mono px-2 py-1 rounded-md",
              isCyan
                ? "bg-cyan-500/6 border border-cyan-500/15 text-cyan-400/60"
                : "bg-indigo-500/6 border border-indigo-500/15 text-indigo-400/60"
            )}>
              <span className="shrink-0">ℹ</span>
              <span>{infoNote}</span>
            </div>
          )}

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
                "disabled:opacity-40 disabled:cursor-not-allowed",
                isCyan
                  ? "border border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/10 hover:border-cyan-400/50"
                  : "border border-indigo-500/30 text-indigo-400 hover:bg-indigo-500/10 hover:border-indigo-400/50"
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
            <span className="text-sm font-semibold text-white">The Degen Oracle — Strategy Intelligence</span>
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
  const { data: posData } = useLivePositions();
  const { data: journal } = useJournal();
  const { data: recentTrades } = useRecentTrades(20);
  const { data: winsData } = useRagWinsExtended(10);
  const [showInsights, setShowInsights] = useState(false);

  const thinking = isLoading || isRefreshing;

  // Gamification — streak + XP
  const oracleStreak = useMemo(
    () => computeStreak(recentTrades?.trades ?? []),
    [recentTrades?.trades]
  );
  const oracleWins  = journal?.summary?.wins  ?? 0;
  const oracleTotal = journal?.summary?.total ?? 0;
  const oracleXP = computeXP(oracleWins, oracleTotal);

  // Refresh only when position count changes or 10 minutes have passed — not blindly every 90s
  const prevPosCount = useRef<number>(-1);
  const lastRefreshTs = useRef<number>(0);

  useEffect(() => {
    const id = setInterval(() => {
      if (isRefreshing || isLoading) return;
      const now = Date.now();
      const posCount = posData?.count ?? 0;
      const posChanged = prevPosCount.current !== -1 && posCount !== prevPosCount.current;
      const tenMinPassed = now - lastRefreshTs.current > 600_000;
      if (posChanged || tenMinPassed || lastRefreshTs.current === 0) {
        lastRefreshTs.current = now;
        prevPosCount.current = posCount;
        refresh();
      }
    }, 60_000);
    return () => clearInterval(id);
  }, [isRefreshing, isLoading, refresh, posData?.count]);

  return (
    <>
      <AnimatePresence>
        {showInsights && <BrainInsightsModal open={showInsights} onClose={() => setShowInsights(false)} />}
      </AnimatePresence>

      <div className="relative rounded-2xl border border-indigo-500/20 bg-gradient-to-br from-slate-950/90 to-indigo-950/20 p-5 shadow-[0_0_60px_rgba(99,102,241,0.06)] overflow-hidden flex-1 flex flex-col">
        <div className="absolute top-0 left-0 w-48 h-48 bg-indigo-500/5 rounded-full blur-3xl -translate-x-1/4 -translate-y-1/4 pointer-events-none" />
        <div className="absolute bottom-0 right-0 w-64 h-64 bg-violet-500/4 rounded-full blur-3xl translate-x-1/4 translate-y-1/4 pointer-events-none" />

        <div className="relative flex items-center gap-2 mb-1">
          <Brain className="h-3.5 w-3.5 text-indigo-400" />
          <span className="text-[10px] uppercase font-semibold tracking-wider text-indigo-400/80">
            The Degen Oracle
          </span>
          <span className="ml-auto flex items-center gap-1.5 text-[9px] text-indigo-400/40">
            <StreakChip count={oracleStreak.count} direction={oracleStreak.direction} />
            <motion.span
              className="inline-block w-1.5 h-1.5 rounded-full bg-indigo-400"
              animate={{ opacity: [0.3, 1, 0.3] }}
              transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
            />
            updates on new activity
          </span>
        </div>

        {/* XP Rank bar */}
        <XPRankBar xp={oracleXP} ranks={ORACLE_RANKS} accent="#818cf8" />

        <div className="relative flex flex-col sm:flex-row items-center sm:items-start gap-3 sm:gap-5 flex-1">
          <motion.div
            className="flex-shrink-0 w-24 h-24 sm:w-44 sm:h-44 cursor-pointer relative group"
            animate={{ y: [0, -6, 0, 4, 0], x: [0, 3, 0, -3, 0] }}
            transition={{ duration: 7, repeat: Infinity, ease: "easeInOut" }}
            onClick={() => setShowInsights(true)}
            title="Click to view AI strategy & learnings"
          >
            <BrainSVG thinking={thinking} />
            <div className="absolute inset-0 flex items-end justify-center pb-1 opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none">
              <span className="text-[9px] font-semibold text-indigo-300/80 bg-slate-950/80 rounded-full px-2 py-0.5 border border-indigo-500/20 backdrop-blur-sm">
                tap to inspect
              </span>
            </div>
          </motion.div>

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

        {/* Equity Signal Scanner — always visible, mirrors Kraken's signal scanner format */}
        <div className="mt-3 rounded-xl border border-white/5 bg-slate-900/40 overflow-hidden">
          <div className="px-3 py-1.5 text-[9px] uppercase font-semibold text-muted-foreground tracking-wider border-b border-white/5 flex items-center justify-between">
            <span>Signal Scanner</span>
            <span className="text-[9px] text-indigo-400/50 font-normal normal-case">
              {(posData?.positions?.length ?? 0) > 0 ? "live positions" : "awaiting positions"}
            </span>
          </div>
          {(posData?.positions?.length ?? 0) === 0 ? (
            <div className="px-3 py-3 text-[10px] text-muted-foreground/50 italic text-center">
              No open positions — scanner activates when trades are entered
            </div>
          ) : (
            <div className="divide-y divide-white/[0.03]">
              {(posData?.positions ?? []).map((pos) => {
                const pnlPct = (pos.unrealized_plpc ?? 0) * 100;
                const conv = pos.conviction_score;
                const convPct = conv !== null ? conv * 100 : null;
                const convColor = conv !== null ? (conv > 0.7 ? "#22c55e" : conv > 0.4 ? "#22d3ee" : "#f97316") : "#64748b";
                return (
                  <div key={pos.symbol} className="px-3 py-2 flex items-center gap-3">
                    <span className="text-xs font-bold text-white w-14 shrink-0">{pos.symbol}</span>
                    {/* Conviction bar */}
                    <div className="flex items-center gap-1.5 flex-1">
                      <span className="text-[9px] text-muted-foreground/60 w-8">Conv</span>
                      <div className="flex-1 h-1 bg-slate-800 rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full transition-all duration-700"
                          style={{ width: `${convPct ?? 50}%`, backgroundColor: convColor }}
                        />
                      </div>
                      <span className="text-[9px] font-mono w-8 text-right" style={{ color: convColor }}>
                        {convPct !== null ? `${convPct.toFixed(0)}%` : "—"}
                      </span>
                    </div>
                    {/* P&L status pill */}
                    <span className={cn(
                      "text-[8px] font-bold px-1.5 py-0.5 rounded-full border shrink-0",
                      pnlPct >= 0
                        ? "text-green-400 bg-green-500/10 border-green-500/30"
                        : "text-red-400 bg-red-500/10 border-red-500/20"
                    )}>
                      HOLD {pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(1)}%
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <RegimeAllocationPanel regime={alloc?.regime} allocation={alloc?.allocation ?? null} />

        {/* Kill Board — Hit List */}
        <KillBoardPanel
          trades={(winsData?.wins ?? []).map(w => ({ symbol: w.ticker, pnl_pct: w.pnl_percentage, pnl_usd: null }))}
          theme="degen"
          bigWinUsd={200}
          bigWinPctFallback={5}
          bigWinLabel="🦍 APE MODE"
          panelLabel="Hit List"
        />
      </div>
    </>
  );
}

// ── Davy Jones' Portfolio — Kraken Brain Modal ───────────────────────────────

function KrakenBrainModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { data } = useKrakenStatus();
  if (!open) return null;

  const signals: any[] = data?.signals ?? [];
  const trades: any[]  = data?.recent_trades ?? [];
  const wins  = trades.filter(t => t.pnl_pct > 0);
  const losses = trades.filter(t => t.pnl_pct <= 0);
  const bestTrade  = trades.reduce((b, t) => (b == null || t.pnl_pct > b.pnl_pct ? t : b), null as any);
  const worstTrade = trades.reduce((w, t) => (w == null || t.pnl_pct < w.pnl_pct ? t : w), null as any);
  const winRate    = trades.length > 0 ? (wins.length / trades.length * 100) : null;

  const signalTypeLabel: Record<string, string> = {
    hold: "HOLDING", watching: "WATCHING", slots_full: "SLOTS FULL",
    long_entered: "LONG ENTERED", short_entered: "SHORT ENTERED",
    long_signal: "LONG SIGNAL", short_signal: "SHORT SIGNAL",
    exit_mean_reversion: "EXITED (REVERT)", exit_stop_loss: "EXITED (STOP)",
    exit_trailing_stop: "EXITED (TRAIL)",
  };
  const signalTypeColor: Record<string, string> = {
    hold: "text-cyan-400 bg-cyan-500/10 border-cyan-500/30",
    watching: "text-slate-400 bg-slate-500/10 border-slate-500/20",
    slots_full: "text-amber-400 bg-amber-500/10 border-amber-500/20",
    long_entered: "text-green-400 bg-green-500/10 border-green-500/30",
    short_entered: "text-red-400 bg-red-500/10 border-red-500/20",
    long_signal: "text-green-400 bg-green-500/10 border-green-500/30",
    short_signal: "text-red-400 bg-red-500/10 border-red-500/20",
  };

  return (
    <motion.div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      onClick={onClose}
    >
      <motion.div
        className="relative w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-2xl border border-cyan-500/20 bg-gradient-to-br from-slate-950 to-cyan-950/30 shadow-[0_0_80px_rgba(6,182,212,0.15)] p-6"
        initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.95, opacity: 0 }} onClick={e => e.stopPropagation()}
      >
        <button onClick={onClose} className="absolute top-4 right-4 text-muted-foreground hover:text-white transition-colors text-xl">✕</button>

        {/* Header */}
        <div className="flex items-center gap-3 mb-5">
          <span className="text-2xl">⚓</span>
          <div>
            <h2 className="text-sm font-bold text-cyan-400 uppercase tracking-wider">Davy Jones' Strategy Debrief</h2>
            <p className="text-[10px] text-muted-foreground">Mean-Reversion · RSI + Z-Score · 1h candles · Kraken Exchange</p>
          </div>
        </div>

        {/* Thinking text */}
        {data?.thinking_text && (
          <div className="mb-5 rounded-xl border border-cyan-500/15 bg-slate-900/60 p-3.5 text-xs text-white/80 leading-relaxed">
            {data.thinking_text}
          </div>
        )}

        {/* Signal Scanner */}
        <div className="mb-5">
          <h3 className="text-[10px] uppercase font-semibold tracking-wider text-muted-foreground mb-3">Live Signal Scanner</h3>
          {signals.length === 0 ? (
            <p className="text-xs text-muted-foreground/50 italic">No signals yet — waiting for first cycle</p>
          ) : (
            <div className="space-y-3">
              {signals.map((sig: any) => {
                const rsiPct = Math.min(sig.rsi, 100);
                const rsiColor = sig.rsi < 35 ? "#ef4444" : sig.rsi < 45 ? "#f97316" : sig.rsi > 65 ? "#22c55e" : sig.rsi > 55 ? "#22d3ee" : "#64748b";
                const zAbs = Math.min(Math.abs(sig.z_score), 3);
                const zColor = sig.z_score < -0.6 ? "#f97316" : sig.z_score > 0.6 ? "#22d3ee" : "#64748b";
                const stLabel = signalTypeLabel[sig.signal_type] ?? sig.signal_type.toUpperCase();
                const stColor = signalTypeColor[sig.signal_type] ?? "text-slate-400 bg-slate-500/10 border-slate-500/20";
                return (
                  <div key={sig.symbol} className="rounded-xl border border-white/5 bg-slate-900/50 p-3">
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-bold text-white text-sm">{sig.symbol}</span>
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs text-muted-foreground">${sig.price?.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
                        <span className={cn("text-[9px] font-bold px-1.5 py-0.5 rounded-full border", stColor)}>{stLabel}</span>
                      </div>
                    </div>
                    {/* RSI gauge */}
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className="text-[10px] text-muted-foreground w-8">RSI</span>
                      <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden relative">
                        <div className="absolute left-[35%] w-px h-full bg-orange-500/40" />
                        <div className="absolute left-[45%] w-px h-full bg-slate-600" />
                        <div className="absolute left-[55%] w-px h-full bg-slate-600" />
                        <div className="absolute left-[65%] w-px h-full bg-cyan-500/40" />
                        <div className="h-full rounded-full transition-all duration-500" style={{ width: `${rsiPct}%`, backgroundColor: rsiColor }} />
                      </div>
                      <span className="text-[10px] font-mono w-8 text-right" style={{ color: rsiColor }}>{sig.rsi}</span>
                    </div>
                    {/* Z-score bar */}
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] text-muted-foreground w-8">Z</span>
                      <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden relative">
                        <div className="absolute left-1/2 w-px h-full bg-slate-600" />
                        {sig.z_score < 0 ? (
                          <div className="absolute right-1/2 h-full rounded-l-full transition-all" style={{ width: `${(zAbs / 3) * 50}%`, backgroundColor: "#f97316" }} />
                        ) : (
                          <div className="absolute left-1/2 h-full rounded-r-full transition-all" style={{ width: `${(zAbs / 3) * 50}%`, backgroundColor: "#22d3ee" }} />
                        )}
                      </div>
                      <span className="text-[10px] font-mono w-12 text-right" style={{ color: zColor }}>{sig.z_score >= 0 ? "+" : ""}{sig.z_score}</span>
                    </div>
                    {sig.pnl_pct != null && (
                      <div className="mt-1.5 text-[9px] font-mono" style={{ color: sig.pnl_pct >= 0 ? "#22c55e" : "#ef4444" }}>
                        P&L: {sig.pnl_pct >= 0 ? "+" : ""}{sig.pnl_pct}%
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* What I'm Learning */}
        <div className="mb-5">
          <h3 className="text-[10px] uppercase font-semibold tracking-wider text-muted-foreground mb-3">What I'm Learning</h3>
          {trades.length === 0 ? (
            <p className="text-xs text-muted-foreground/50 italic">No completed trades yet — learning begins after first exit</p>
          ) : (
            <div className="space-y-2">
              {/* Stats row */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                <div className="rounded-xl border border-white/5 bg-slate-900/50 p-2.5 text-center">
                  <div className="text-[9px] text-muted-foreground mb-1">Win Rate</div>
                  <div className={cn("text-base font-bold font-mono", (winRate ?? 0) >= 50 ? "text-green-400" : "text-amber-400")}>
                    {winRate?.toFixed(0) ?? "—"}%
                  </div>
                  <div className="text-[9px] text-muted-foreground">{wins.length}W · {losses.length}L</div>
                </div>
                <div className="rounded-xl border border-white/5 bg-slate-900/50 p-2.5 text-center">
                  <div className="text-[9px] text-muted-foreground mb-1">Best Trade</div>
                  <div className="text-base font-bold font-mono text-green-400">
                    {bestTrade ? `+${bestTrade.pnl_pct.toFixed(2)}%` : "—"}
                  </div>
                  <div className="text-[9px] text-muted-foreground">{bestTrade?.symbol ?? ""}</div>
                </div>
                <div className="rounded-xl border border-white/5 bg-slate-900/50 p-2.5 text-center">
                  <div className="text-[9px] text-muted-foreground mb-1">Worst Trade</div>
                  <div className="text-base font-bold font-mono text-red-400">
                    {worstTrade ? `${worstTrade.pnl_pct.toFixed(2)}%` : "—"}
                  </div>
                  <div className="text-[9px] text-muted-foreground">{worstTrade?.symbol ?? ""}</div>
                </div>
              </div>
              {/* Recent trades */}
              <div className="rounded-xl border border-white/5 bg-slate-900/40 overflow-hidden">
                <div className="px-3 py-1.5 text-[9px] uppercase font-semibold text-muted-foreground border-b border-white/5">Recent Trades</div>
                {trades.slice(-8).reverse().map((t: any, i: number) => (
                  <div key={i} className="flex items-center justify-between px-3 py-2 border-b border-white/[0.03] last:border-0">
                    <span className="text-xs font-mono text-white">{t.symbol}</span>
                    <span className="text-[10px] text-muted-foreground uppercase">{t.side}</span>
                    <span className="text-[10px] text-muted-foreground">{t.exit_reason?.replace(/_/g, " ")}</span>
                    <span className={cn("text-xs font-mono font-bold", t.pnl_pct >= 0 ? "text-green-400" : "text-red-400")}>
                      {t.pnl_pct >= 0 ? "+" : ""}{t.pnl_pct.toFixed(2)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Strategy config */}
        <div className="rounded-xl border border-white/5 bg-slate-900/30 p-3">
          <div className="text-[9px] uppercase font-semibold text-muted-foreground mb-2">Strategy Parameters</div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[10px] font-mono">
            <span className="text-muted-foreground">RSI Period</span><span className="text-white">14 candles</span>
            <span className="text-muted-foreground">RSI Oversold / Overbought</span><span className="text-white">&lt;40 / &gt;60</span>
            <span className="text-muted-foreground">Z-Score Entry Threshold</span><span className="text-white">±1.0σ</span>
            <span className="text-muted-foreground">Z-Score Exit Threshold</span><span className="text-white">±0.30σ (mean-revert)</span>
            <span className="text-muted-foreground">Stop Loss</span><span className="text-white">2% from entry</span>
            <span className="text-muted-foreground">Trailing Stop</span><span className="text-white">5% below best price (arms once in profit)</span>
            <span className="text-muted-foreground">Max Positions</span><span className="text-white">10 simultaneous</span>
            <span className="text-muted-foreground">Max Per Position</span><span className="text-white">10% of equity</span>
            <span className="text-muted-foreground">Cash Reserve</span><span className="text-white">20% always held</span>
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
}

// ── Davy Jones' Portfolio — Kraken Bot Section ───────────────────────────────

function AnchorSVG({ active }: { active: boolean }) {
  return (
    <svg viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg" className="w-full h-full">
      {/* Glow halo */}
      <circle cx="60" cy="60" r="52" fill={active ? "rgba(6,182,212,0.06)" : "rgba(100,116,139,0.04)"} />
      <circle cx="60" cy="60" r="42" fill={active ? "rgba(6,182,212,0.08)" : "rgba(100,116,139,0.06)"} stroke={active ? "rgba(6,182,212,0.25)" : "rgba(100,116,139,0.15)"} strokeWidth="1" />
      {/* Anchor ring at top */}
      <circle cx="60" cy="28" r="9" stroke={active ? "#22d3ee" : "#64748b"} strokeWidth="3" fill="none" />
      {/* Vertical shaft */}
      <line x1="60" y1="37" x2="60" y2="88" stroke={active ? "#22d3ee" : "#64748b"} strokeWidth="3" strokeLinecap="round" />
      {/* Horizontal crossbar */}
      <line x1="38" y1="52" x2="82" y2="52" stroke={active ? "#22d3ee" : "#64748b"} strokeWidth="3" strokeLinecap="round" />
      {/* Left fluke */}
      <path d="M60 88 Q42 96 36 90 Q34 80 44 78" stroke={active ? "#22d3ee" : "#64748b"} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      {/* Right fluke */}
      <path d="M60 88 Q78 96 84 90 Q86 80 76 78" stroke={active ? "#22d3ee" : "#64748b"} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      {/* Chain wrapping around shaft (circuit-breaker = red) */}
      {active ? (
        <>
          <circle cx="52" cy="65" r="3" fill="rgba(34,211,238,0.5)" />
          <circle cx="68" cy="70" r="3" fill="rgba(34,211,238,0.5)" />
          <circle cx="52" cy="75" r="3" fill="rgba(34,211,238,0.5)" />
        </>
      ) : (
        <>
          <circle cx="52" cy="65" r="3" fill="rgba(100,116,139,0.4)" />
          <circle cx="68" cy="70" r="3" fill="rgba(100,116,139,0.4)" />
          <circle cx="52" cy="75" r="3" fill="rgba(100,116,139,0.4)" />
        </>
      )}
    </svg>
  );
}

const BOT_THEMES: Record<string, { accent: string; accentTw: string; icon: string; glowRgb: string; borderTw: string; bgGradient: string }> = {
  "davy-jones": { accent: "#22d3ee", accentTw: "cyan", icon: "⚓", glowRgb: "6,182,212", borderTw: "border-cyan-500/20", bgGradient: "from-slate-950/90 to-cyan-950/10" },
  "blackbeard": { accent: "#f97316", accentTw: "orange", icon: "🏴‍☠️", glowRgb: "249,115,22", borderTw: "border-orange-500/20", bgGradient: "from-slate-950/90 to-orange-950/10" },
  "calypso":    { accent: "#a855f7", accentTw: "purple", icon: "🌊", glowRgb: "168,85,247", borderTw: "border-purple-500/20", bgGradient: "from-slate-950/90 to-purple-950/10" },
};

function KrakenBotCard({ botId }: { botId: string }) {
  const theme = BOT_THEMES[botId] ?? BOT_THEMES["davy-jones"];
  const { data } = useKrakenStatus(botId);
  const { data: krakenPerf } = useKrakenPerformance(botId);
  const { data: krakenCommentary, isLoading: commentaryLoading } = useKrakenCommentary(botId);
  const { mutate: refreshKrakenCommentary, isPending: isRefreshingKraken } = useRefreshKrakenCommentary(botId);
  const [showModal, setShowModal] = useState(false);
  const isMobile = useIsMobile();

  const botName = data?.bot_name ?? botId;
  const strategyLabel = data?.strategy_label ?? "";

  const isRunning  = data?.status === "running";
  const isCB       = data?.status === "paused_circuit_breaker";
  const isError    = data?.status === "error";
  const notStarted = !data || data.status === "not_started";
  const krakenThinking = commentaryLoading || isRefreshingKraken;
  const krakenThrottled = krakenCommentary?.throttled === true;

  const statusLabel = isCB ? "CIRCUIT BREAKER" : isRunning ? "RUNNING" : isError ? "ERROR" : "NOT STARTED";
  const statusDot   = isCB ? "bg-red-400" : isRunning ? `bg-[${theme.accent}]` : isError ? "bg-amber-400" : "bg-slate-600";

  const recentKrakenTrades = useMemo(() => [...(data?.recent_trades ?? [])].reverse(), [data?.recent_trades]);
  const krakenStreak = useMemo(() => computeStreak(recentKrakenTrades), [recentKrakenTrades]);
  const krakenXP = computeXP(krakenPerf?.win_count ?? 0, krakenPerf?.total_trades ?? 0);

  const lastTrade    = data?.recent_trades?.at(-1);
  const posCount     = data?.position_count ?? 0;
  const deployedPct  = data?.deployed_pct ?? 0;
  const maxDeployPct = data?.deployable_ceiling_pct ?? 80;
  const signals: any[] = data?.signals ?? [];

  const fallbackText = notStarted
    ? `${botName} is waiting to start — bot hasn't run yet.`
    : isCB
    ? "Circuit breaker tripped — all trading paused until volatility clears."
    : isError
    ? `Error: ${data?.error ?? "unknown"}. Regrouping...`
    : "Scanning for mean-reversion setups.";

  const [displayedText, setDisplayedText] = useState<string | null>(null);
  const prevPosCount   = useRef<number>(-1);
  const prevSignalKey  = useRef<string>("");
  const signalKey = signals
    .filter((s: any) => s.signal_type === "hold" || s.signal_type.includes("entered"))
    .map((s: any) => `${s.symbol}:${s.signal_type}`)
    .join("|");

  useEffect(() => {
    const posChanged = posCount !== prevPosCount.current;
    const sigChanged = signalKey !== prevSignalKey.current;
    if (!displayedText || posChanged || sigChanged) {
      setDisplayedText(data?.thinking_text ?? fallbackText);
      prevPosCount.current  = posCount;
      prevSignalKey.current = signalKey;
    }
  }, [posCount, signalKey, data?.thinking_text]);

  const dialogueText = displayedText ?? fallbackText;

  return (
    <>
      <AnimatePresence>
        {showModal && <KrakenBrainModal open={showModal} onClose={() => setShowModal(false)} />}
      </AnimatePresence>

      <div className={cn("relative rounded-2xl border bg-gradient-to-br p-5 shadow-[0_0_60px_rgba(var(--glow),0.04)] overflow-hidden flex-1 flex flex-col", theme.borderTw, theme.bgGradient)} style={{ "--glow": theme.glowRgb } as any}>
        <div className={cn("absolute top-0 left-0 w-48 h-48 rounded-full blur-3xl -translate-x-1/4 -translate-y-1/4 pointer-events-none")} style={{ backgroundColor: `rgba(${theme.glowRgb}, 0.04)` }} />
        <div className={cn("absolute bottom-0 right-0 w-64 h-64 rounded-full blur-3xl translate-x-1/4 translate-y-1/4 pointer-events-none")} style={{ backgroundColor: `rgba(${theme.glowRgb}, 0.03)` }} />

        <div className="relative flex items-center gap-2 mb-1">
          <span className="text-sm" style={{ color: `rgba(${theme.glowRgb}, 0.7)` }}>{theme.icon}</span>
          <span className="text-[10px] uppercase font-semibold tracking-wider" style={{ color: `rgba(${theme.glowRgb}, 0.8)` }}>
            {botName}
          </span>
          {strategyLabel && (
            <span className="text-[8px] px-1.5 py-0.5 rounded-full border border-white/10 text-muted-foreground/60">{strategyLabel}</span>
          )}
          <span className="ml-auto flex items-center gap-1.5">
            <StreakChip count={krakenStreak.count} direction={krakenStreak.direction} />
            {isCB && (
              <motion.span
                className="text-[9px] font-bold text-red-400 border border-red-500/30 bg-red-500/10 px-1.5 py-0.5 rounded-full"
                animate={{ opacity: [1, 0.4, 1] }}
                transition={{ duration: 1, repeat: Infinity }}
              >
                CIRCUIT BREAKER
              </motion.span>
            )}
            <span className="flex items-center gap-1 text-[9px]" style={{ color: `rgba(${theme.glowRgb}, 0.4)` }}>
              <motion.span
                className={cn("inline-block w-1.5 h-1.5 rounded-full")}
                style={{ backgroundColor: isCB ? "#f87171" : isRunning ? theme.accent : isError ? "#fbbf24" : "#475569" }}
                animate={{ opacity: isRunning ? [0.3, 1, 0.3] : 1 }}
                transition={{ duration: 2, repeat: isRunning ? Infinity : 0, ease: "easeInOut" }}
              />
              {statusLabel.toLowerCase()}
            </span>
          </span>
        </div>

        <XPRankBar xp={krakenXP} ranks={KRAKEN_RANKS} accent={theme.accent} />

        <div className="relative flex flex-col sm:flex-row items-center sm:items-start gap-3 sm:gap-5">
          <motion.div
            className="flex-shrink-0 w-24 h-24 sm:w-44 sm:h-44 cursor-pointer relative group"
            animate={isRunning ? { y: [0, -6, 0, 4, 0], rotate: [0, 1, 0, -1, 0] } : { rotate: [0, 2, 0, -2, 0] }}
            transition={{ duration: isRunning ? 7 : 10, repeat: Infinity, ease: "easeInOut" }}
            onClick={() => setShowModal(true)}
            title="Click to view full strategy analysis"
          >
            <AnchorSVG active={isRunning} />
            <div className="absolute inset-0 flex items-end justify-center pb-1 opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none">
              <span className="text-[9px] font-semibold bg-slate-950/80 rounded-full px-2 py-0.5 border backdrop-blur-sm" style={{ color: `rgba(${theme.glowRgb}, 0.8)`, borderColor: `rgba(${theme.glowRgb}, 0.2)` }}>
                tap to inspect
              </span>
            </div>
          </motion.div>

          <SpeechBubble
            commentary={
              krakenThrottled
                ? (krakenThinking ? undefined : dialogueText)
                : (krakenCommentary?.commentary ?? (krakenThinking ? undefined : dialogueText))
            }
            generatedAt={krakenThrottled ? null : (krakenCommentary?.generated_at ?? null)}
            cached={krakenThrottled ? false : krakenCommentary?.cached}
            cacheAge={krakenThrottled ? undefined : krakenCommentary?.cache_age_seconds}
            thinking={krakenThinking}
            onRefresh={() => refreshKrakenCommentary()}
            isRefreshing={isRefreshingKraken}
            theme={theme.accentTw as any}
            title={botName.split("'")[0] ?? botName}
            infoNote={krakenThrottled ? "AI narrative paused — daily token budget reached. Trades are unaffected; all decisions are algorithmic." : undefined}
          />
        </div>

        {(() => {
          const WATCHED = ["BTC/USD","ETH/USD","SOL/USD","XRP/USD","ADA/USD","AVAX/USD","LINK/USD","DOT/USD","ATOM/USD","LTC/USD"];
          const displayRows = WATCHED.map((sym) => {
            const live = signals.find((s: any) => s.symbol === sym);
            return live ?? { symbol: sym, rsi: null, z_score: null, signal_type: "monitoring", has_position: false, pnl_pct: null };
          });
          const hasLive = signals.length > 0;
          return (
            <div className="mt-3 rounded-xl border border-white/5 bg-slate-900/40 overflow-hidden">
              <div className="px-3 py-1.5 text-[9px] uppercase font-semibold text-muted-foreground tracking-wider border-b border-white/5 flex items-center justify-between">
                <span>Signal Scanner</span>
                <div className="flex items-center gap-2">
                  {!hasLive && <span className="text-[8px] text-slate-600">waiting for data…</span>}
                  <button onClick={() => setShowModal(true)} className="transition-colors text-[9px]" style={{ color: `rgba(${theme.glowRgb}, 0.6)` }}>
                    full analysis →
                  </button>
                </div>
              </div>
              {isMobile ? (
                <div className="grid grid-cols-2 gap-2 p-2">
                  {displayRows.map((sig: any) => {
                    const hasData = sig.rsi != null;
                    const rsiColor = !hasData ? "#374151" : sig.rsi < 35 ? "#ef4444" : sig.rsi < 45 ? "#f97316" : sig.rsi > 65 ? "#22c55e" : sig.rsi > 55 ? "#22d3ee" : "#64748b";
                    const zColor = !hasData ? "#374151" : sig.z_score < -0.6 ? "#f97316" : sig.z_score > 0.6 ? "#22d3ee" : "#64748b";
                    const isPosHeld = sig.has_position && sig.signal_type === "hold";
                    const pillClass = !hasData ? "text-slate-700 bg-slate-800/30 border-slate-700/20" :
                      isPosHeld ? "text-cyan-400 bg-cyan-500/10 border-cyan-500/30" :
                      sig.signal_type.includes("long") ? "text-green-400 bg-green-500/10 border-green-500/30" :
                      sig.signal_type.includes("short") ? "text-red-400 bg-red-500/10 border-red-500/20" :
                      "text-slate-500 bg-slate-800/50 border-slate-700/40";
                    const pillText = !hasData ? "…" :
                      isPosHeld ? `HOLD ${sig.pnl_pct >= 0 ? "+" : ""}${sig.pnl_pct?.toFixed(1)}%` :
                      sig.signal_type === "watching" ? "WATCH" :
                      sig.signal_type.includes("entered") ? "IN" :
                      sig.signal_type === "slots_full" ? "FULL" : "—";
                    return (
                      <div key={sig.symbol} className={cn("rounded-lg border border-white/[0.06] bg-slate-900/60 p-2.5", !hasData && "opacity-40")}>
                        <div className="flex items-center justify-between mb-2">
                          <span className={cn("text-sm font-bold font-mono", hasData ? "text-white" : "text-slate-600")}>
                            {sig.symbol.replace("/USD", "")}
                          </span>
                          <span className={cn("text-[8px] font-bold px-1.5 py-0.5 rounded-full border", pillClass)}>{pillText}</span>
                        </div>
                        <div className="flex items-center gap-1.5 mb-1.5">
                          <span className="text-[9px] text-muted-foreground/60 w-6">RSI</span>
                          <div className="flex-1 h-1 bg-slate-800 rounded-full overflow-hidden">
                            {hasData && <div className="h-full rounded-full transition-all duration-700" style={{ width: `${Math.min(sig.rsi,100)}%`, backgroundColor: rsiColor }} />}
                          </div>
                          <span className="text-[9px] font-mono w-6 text-right" style={{ color: rsiColor }}>{hasData ? sig.rsi : "—"}</span>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <span className="text-[9px] text-muted-foreground/60 w-6">Z</span>
                          <div className="flex-1 h-1 bg-slate-800 rounded-full overflow-hidden relative">
                            <div className="absolute left-1/2 w-px h-full bg-slate-600" />
                            {hasData && sig.z_score < 0 && (
                              <div className="absolute right-1/2 h-full rounded-l-full" style={{ width: `${(Math.min(Math.abs(sig.z_score),2)/2)*50}%`, backgroundColor: "#f97316" }} />
                            )}
                            {hasData && sig.z_score >= 0 && (
                              <div className="absolute left-1/2 h-full rounded-r-full" style={{ width: `${(Math.min(sig.z_score,2)/2)*50}%`, backgroundColor: "#22d3ee" }} />
                            )}
                          </div>
                          <span className="text-[9px] font-mono w-9 text-right" style={{ color: zColor }}>
                            {hasData ? `${sig.z_score >= 0 ? "+" : ""}${sig.z_score}` : "—"}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                /* ── Desktop: compact divide-y rows ── */
                <div className="divide-y divide-white/[0.03]">
                  {displayRows.map((sig: any) => {
                    const hasData = sig.rsi != null;
                    const rsiColor = !hasData ? "#374151" : sig.rsi < 35 ? "#ef4444" : sig.rsi < 45 ? "#f97316" : sig.rsi > 65 ? "#22c55e" : sig.rsi > 55 ? "#22d3ee" : "#64748b";
                    const zColor = !hasData ? "#374151" : sig.z_score < -0.6 ? "#f97316" : sig.z_score > 0.6 ? "#22d3ee" : "#64748b";
                    const isPosHeld = sig.has_position && sig.signal_type === "hold";
                    return (
                      <div key={sig.symbol} className={cn("px-3 py-2 flex items-center gap-3", !hasData && "opacity-40")}>
                        <span className={cn("text-xs font-bold w-12 shrink-0", hasData ? "text-white" : "text-slate-600")}>{sig.symbol.replace("/USD","")}</span>
                        <div className="flex items-center gap-1.5 flex-1">
                          <span className="text-[9px] text-muted-foreground/60 w-6">RSI</span>
                          <div className="flex-1 h-1 bg-slate-800 rounded-full overflow-hidden">
                            {hasData && <div className="h-full rounded-full transition-all duration-700" style={{ width: `${Math.min(sig.rsi,100)}%`, backgroundColor: rsiColor }} />}
                          </div>
                          <span className="text-[9px] font-mono w-7 text-right" style={{ color: rsiColor }}>{hasData ? sig.rsi : "—"}</span>
                        </div>
                        <div className="flex items-center gap-1.5 flex-1">
                          <span className="text-[9px] text-muted-foreground/60 w-4">Z</span>
                          <div className="flex-1 h-1 bg-slate-800 rounded-full overflow-hidden relative">
                            <div className="absolute left-1/2 w-px h-full bg-slate-600" />
                            {hasData && sig.z_score < 0 && (
                              <div className="absolute right-1/2 h-full rounded-l-full" style={{ width: `${(Math.min(Math.abs(sig.z_score),2)/2)*50}%`, backgroundColor: "#f97316" }} />
                            )}
                            {hasData && sig.z_score >= 0 && (
                              <div className="absolute left-1/2 h-full rounded-r-full" style={{ width: `${(Math.min(sig.z_score,2)/2)*50}%`, backgroundColor: "#22d3ee" }} />
                            )}
                          </div>
                          <span className="text-[9px] font-mono w-10 text-right" style={{ color: zColor }}>
                            {hasData ? `${sig.z_score >= 0 ? "+" : ""}${sig.z_score}` : "—"}
                          </span>
                        </div>
                        <span className={cn(
                          "text-[8px] font-bold px-1.5 py-0.5 rounded-full border shrink-0",
                          !hasData ? "text-slate-700 bg-slate-800/30 border-slate-700/20" :
                          isPosHeld ? "text-cyan-400 bg-cyan-500/10 border-cyan-500/30" :
                          sig.signal_type.includes("long") ? "text-green-400 bg-green-500/10 border-green-500/30" :
                          sig.signal_type.includes("short") ? "text-red-400 bg-red-500/10 border-red-500/20" :
                          "text-slate-500 bg-slate-800/50 border-slate-700/40"
                        )}>
                          {!hasData ? "…" :
                           isPosHeld ? `HOLD ${sig.pnl_pct >= 0 ? "+" : ""}${sig.pnl_pct?.toFixed(1)}%` :
                           sig.signal_type === "watching" ? "WATCH" :
                           sig.signal_type.includes("entered") ? "IN" :
                           sig.signal_type === "slots_full" ? "FULL" : "—"}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })()}

        <div className="mt-3 grid grid-cols-2 gap-2">
          <div className="rounded-xl border border-white/5 bg-slate-900/40 p-2.5">
            <div className="text-[9px] uppercase font-semibold text-muted-foreground tracking-wider mb-1.5">Capital Deployed</div>
            <div className="flex items-end gap-1 mb-1">
              <span className="text-lg font-bold font-mono leading-none" style={{ color: deployedPct > 70 ? "#fbbf24" : theme.accent }}>
                {deployedPct.toFixed(0)}%
              </span>
              <span className="text-[9px] text-muted-foreground mb-0.5">/ {maxDeployPct}% ceiling</span>
            </div>
            <div className="h-1 bg-slate-800 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{ width: `${Math.min((deployedPct / maxDeployPct) * 100, 100)}%`, backgroundColor: deployedPct > 70 ? "#fbbf24" : theme.accent }}
              />
            </div>
          </div>
          <div className="rounded-xl border border-white/5 bg-slate-900/40 p-2.5">
            <div className="text-[9px] uppercase font-semibold text-muted-foreground tracking-wider mb-1.5">Open Positions</div>
            <div className="flex items-end gap-1 mb-1">
              <span className="text-lg font-bold font-mono leading-none text-white">{posCount}</span>
              <span className="text-[9px] text-muted-foreground mb-0.5">/ {data?.max_positions ?? 10} max</span>
            </div>
            <div className="flex gap-1">
              {Array.from({ length: data?.max_positions ?? 10 }).map((_, i) => (
                <div key={i} className="h-1.5 flex-1 rounded-full" style={{ backgroundColor: i < posCount ? theme.accent : "#334155" }} />
              ))}
            </div>
          </div>
        </div>

        {(data?.open_positions?.length ?? 0) > 0 && (
          <div className="mt-3 rounded-xl border border-white/5 bg-slate-900/30 overflow-hidden">
            <div className="px-3 py-1.5 text-[9px] uppercase font-semibold text-muted-foreground tracking-wider border-b border-white/5 flex items-center gap-2">
              <span>Open Positions</span>
              <span style={{ color: `rgba(${theme.glowRgb}, 0.5)` }}>{data!.open_positions.length}/{data!.max_positions}</span>
              {data?.paper_trading && (
                <span className="text-[7px] font-bold px-1 py-0.5 rounded border border-amber-500/25 text-amber-400/60 ml-1">PAPER</span>
              )}
              <span className={cn(
                "ml-auto text-[10px] font-mono font-semibold tabular-nums",
                (data!.open_positions.reduce((s, p) => s + p.unrealized_pnl_usd, 0)) >= 0 ? "text-green-400" : "text-red-400"
              )}>
                {(() => {
                  const t = data!.open_positions.reduce((s, p) => s + p.unrealized_pnl_usd, 0);
                  return `${t >= 0 ? "+" : ""}$${t.toFixed(2)}`;
                })()}
              </span>
            </div>
            <div className="p-2 space-y-1">
              {data!.open_positions.map((kpos) => (
                <KrakenPositionCard
                  key={kpos.symbol}
                  kpos={kpos}
                  signals={signals}
                  isPaper={data?.paper_trading}
                  compact
                />
              ))}
            </div>
          </div>
        )}

        <KillBoardPanel
          trades={data?.recent_trades ?? []}
          theme="pirate"
          bigWinUsd={50}
          bigWinLabel={`${theme.icon} LEVIATHAN KILL`}
          panelLabel="Trophy Wall"
        />

        {(lastTrade || (data && data.status !== "not_started")) && (
          <div className="mt-2 flex items-center gap-3 text-[9px] text-muted-foreground/50 font-mono">
            {lastTrade ? (
              <>
                <span>Last:</span>
                <span className="font-bold text-white/70">{lastTrade.symbol}</span>
                <span>{lastTrade.side?.toUpperCase()}</span>
                <span className={cn("font-bold", lastTrade.pnl_pct >= 0 ? "text-green-400" : "text-red-400")}>
                  {lastTrade.pnl_pct >= 0 ? "+" : ""}{lastTrade.pnl_pct?.toFixed(2)}%
                </span>
              </>
            ) : <span />}
            {data && data.status !== "not_started" && (
              <>
                <span className="ml-auto">Cycle #{data.cycle_count}</span>
                <span>·</span>
                <span>{data.cash_reserve_pct}% reserve</span>
                {data.total_equity_usd > 0 && (
                  <>
                    <span>·</span>
                    <span>${data.total_equity_usd.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
                  </>
                )}
                <button onClick={() => setShowModal(true)} className="transition-colors" style={{ color: `rgba(${theme.glowRgb}, 0.5)` }}>
                  full debrief →
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </>
  );
}

type KrakenTradeEntry = KrakenPerformance["recent_trades"][number];

function CommandersLog() {
  const { data: recentTrades } = useRecentTrades(20);
  const { data: journal } = useJournal();
  const djStatus = useKrakenStatus("davy-jones");
  const bbStatus = useKrakenStatus("blackbeard");
  const caStatus = useKrakenStatus("calypso");
  const djPerf = useKrakenPerformance("davy-jones");
  const bbPerf = useKrakenPerformance("blackbeard");
  const caPerf = useKrakenPerformance("calypso");

  const oracleStreak = useMemo(() => computeStreak(recentTrades?.trades ?? []), [recentTrades?.trades]);
  const oracleWins = journal?.summary?.wins ?? 0;
  const oracleTotal = journal?.summary?.total ?? 0;
  const oracleXP = computeXP(oracleWins, oracleTotal);
  const oracleRank = getRank(oracleXP, ORACLE_RANKS);

  const krakenBots = [
    { id: "davy-jones", status: djStatus.data, perf: djPerf.data },
    { id: "blackbeard", status: bbStatus.data, perf: bbPerf.data },
    { id: "calypso", status: caStatus.data, perf: caPerf.data },
  ];

  const entries = [
    {
      name: "Oracle",
      icon: "🔮",
      accent: "#818cf8",
      streak: oracleStreak,
      xp: oracleXP,
      rank: oracleRank,
      wins: oracleWins,
      total: oracleTotal,
      ranks: ORACLE_RANKS,
    },
    ...krakenBots.map((b) => {
      const t = BOT_THEMES[b.id] ?? BOT_THEMES["davy-jones"];
      const recentKrTrades = [...(b.status?.recent_trades ?? [])].reverse();
      const streak = computeStreak(recentKrTrades);
      const wins = b.perf?.win_count ?? 0;
      const total = b.perf?.total_trades ?? 0;
      const xp = computeXP(wins, total);
      const rank = getRank(xp, KRAKEN_RANKS);
      return {
        name: b.status?.bot_name ?? b.id.replace("-", " "),
        icon: t.icon,
        accent: t.accent,
        streak,
        xp,
        rank,
        wins,
        total,
        ranks: KRAKEN_RANKS,
      };
    }),
  ];

  const recentKills = useMemo(() => {
    const kills: { agent: string; icon: string; accent: string; symbol: string; pnlPct: number; side: string; ts: string }[] = [];
    (recentTrades?.trades ?? []).forEach((t: RecentTradeItem) => {
      if (t.pnl_pct != null && t.pnl_pct > 0) {
        kills.push({ agent: "Oracle", icon: "🔮", accent: "#818cf8", symbol: t.symbol ?? "?", pnlPct: t.pnl_pct, side: "long", ts: t.closed_at ?? "" });
      }
    });
    krakenBots.forEach((b) => {
      const t = BOT_THEMES[b.id] ?? BOT_THEMES["davy-jones"];
      (b.status?.recent_trades ?? []).forEach((tr: KrakenTradeEntry) => {
        if (tr.pnl_pct != null && tr.pnl_pct > 0) {
          kills.push({ agent: b.status?.bot_name ?? b.id, icon: t.icon, accent: t.accent, symbol: tr.symbol ?? "?", pnlPct: tr.pnl_pct, side: tr.side ?? "long", ts: tr.closed_at ?? "" });
        }
      });
    });
    kills.sort((a, b) => b.pnlPct - a.pnlPct);
    return kills.slice(0, 8);
  }, [recentTrades?.trades, djStatus.data, bbStatus.data, caStatus.data]);

  return (
    <div className="rounded-2xl border border-amber-500/15 bg-gradient-to-r from-slate-950/90 via-amber-950/5 to-slate-950/90 p-4 shadow-[0_0_40px_rgba(245,158,11,0.04)]">
      <div className="flex items-center gap-2 mb-3">
        <Trophy className="h-3.5 w-3.5 text-amber-400" />
        <span className="text-[10px] uppercase font-bold tracking-widest text-amber-400/80">Commander&apos;s Log</span>
        <span className="text-[8px] text-muted-foreground/40 ml-auto font-mono">{entries.length} agents</span>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {entries.map((e) => {
          const winRate = e.total > 0 ? ((e.wins / e.total) * 100).toFixed(0) : "—";
          const next = getNextRank(e.xp, e.ranks);
          const progress = next
            ? Math.min(((e.xp - e.rank.xp) / (next.xp - e.rank.xp)) * 100, 100)
            : 100;
          return (
            <div
              key={e.name}
              className="rounded-xl border border-white/5 bg-slate-900/60 p-3 space-y-2"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span className="text-sm">{e.icon}</span>
                  <span className="text-[10px] font-bold text-white capitalize truncate">{e.name}</span>
                </div>
                <StreakChip count={e.streak.count} direction={e.streak.direction} />
              </div>
              <div className="flex items-center gap-1.5">
                <span className={cn("text-[9px] font-bold", e.rank.tw)}>
                  {e.rank.icon} {e.rank.label}
                </span>
              </div>
              <div className="h-1 bg-slate-800 rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-1000 ease-out"
                  style={{ backgroundColor: e.accent, width: `${progress}%` }}
                />
              </div>
              <div className="flex items-center justify-between text-[8px] text-muted-foreground/50 font-mono">
                <span>{e.xp.toLocaleString()} XP</span>
                <span>{winRate !== "—" ? `${winRate}% WR` : "— WR"} · {e.total} trades</span>
              </div>
            </div>
          );
        })}
      </div>
      {recentKills.length > 0 && (
        <div className="mt-3 pt-3 border-t border-amber-500/10">
          <div className="flex items-center gap-2 mb-2">
            <Zap className="h-3 w-3 text-amber-400/60" />
            <span className="text-[9px] uppercase font-bold tracking-wider text-amber-400/50">Recent Kills</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {recentKills.map((k, i) => (
              <div key={`${k.agent}-${k.symbol}-${i}`} className="flex items-center gap-1 rounded-lg bg-slate-800/60 border border-white/5 px-2 py-1">
                <span className="text-[10px]">{k.icon}</span>
                <span className="text-[9px] font-mono text-white/70">{k.symbol.replace("/USD", "")}</span>
                <span className="text-[9px] font-mono font-bold text-green-400">+{k.pnlPct.toFixed(2)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function MiniSparkline({ data, color, w = 60, h = 20 }: { data: number[]; color: string; w?: number; h?: number }) {
  if (data.length < 2) return <div style={{ width: w, height: h }} className="rounded bg-slate-800/40" />;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - ((v - min) / range) * (h - 2) - 1;
    return `${x},${y}`;
  }).join(" ");
  return (
    <svg width={w} height={h} className="shrink-0">
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.7" />
    </svg>
  );
}

function FleetPerformanceHero() {
  const { data: portfolio } = usePortfolio();
  const { data: kraken } = useKrakenStatus();
  const { data: journal } = useJournal();
  const { data: perfHistory } = usePerformanceHistory();
  const djPerf = useKrakenPerformance("davy-jones");
  const bbPerf = useKrakenPerformance("blackbeard");
  const caPerf = useKrakenPerformance("calypso");
  const djStatus = useKrakenStatus("davy-jones");
  const bbStatus = useKrakenStatus("blackbeard");
  const caStatus = useKrakenStatus("calypso");

  const alpacaEquity = portfolio?.account.equity ?? 0;
  const krakenEquity = kraken?.total_equity_usd ?? 0;
  const grandTotal = alpacaEquity + krakenEquity;

  const alpacaWins = journal?.summary?.wins ?? 0;
  const alpacaTotal = journal?.summary?.total ?? 0;

  const botPerfList = [
    { id: "davy-jones", perf: djPerf.data, status: djStatus.data },
    { id: "blackbeard", perf: bbPerf.data, status: bbStatus.data },
    { id: "calypso", perf: caPerf.data, status: caStatus.data },
  ];
  const allPerfs = botPerfList.map(b => b.perf).filter(Boolean);
  const krakenWins = allPerfs.reduce((s, p) => s + (p?.win_count ?? 0), 0);
  const krakenTotal = allPerfs.reduce((s, p) => s + (p?.total_trades ?? 0), 0);

  const totalWins = alpacaWins + krakenWins;
  const totalTrades = alpacaTotal + krakenTotal;
  const combinedWinRate = totalTrades > 0 ? (totalWins / totalTrades) * 100 : null;

  const bestKrakenPct = Math.max(0, ...allPerfs.map(p => p?.best_trade_pct ?? 0));
  const worstKrakenPct = Math.min(0, ...allPerfs.map(p => p?.worst_trade_pct ?? 0));

  const todayStr = new Date().toISOString().slice(0, 10);

  const todayPerformers = useMemo(() => {
    type Performer = { name: string; icon: string; dailyPnl: number };
    const results: Performer[] = [];

    botPerfList.forEach((b) => {
      const trades = b.perf?.recent_trades ?? [];
      const theme = BOT_THEMES[b.id] ?? BOT_THEMES["davy-jones"];
      const todayTrades = trades.filter((t: KrakenTradeEntry) => t.closed_at?.startsWith(todayStr));
      const dailyPnl = todayTrades.reduce((sum: number, t: KrakenTradeEntry) => sum + (t.pnl_pct ?? 0), 0);
      results.push({ name: b.status?.bot_name ?? b.id, icon: theme.icon, dailyPnl });
    });

    const oracleTodayTrades = journal?.trades?.filter(t => t.date?.startsWith(todayStr)) ?? [];
    const oracleDailyPnl = oracleTodayTrades.reduce((sum, t) => sum + (t.pnl_percentage ?? 0), 0);
    results.push({ name: "Oracle", icon: "🔮", dailyPnl: oracleDailyPnl });

    const sorted = [...results].sort((a, b) => b.dailyPnl - a.dailyPnl);
    const best = sorted[0] ?? null;
    const worst = sorted[sorted.length - 1] ?? null;
    return { best, worst };
  }, [djPerf.data, bbPerf.data, caPerf.data, journal, todayStr]);

  const botSparklines = useMemo(() => {
    const krakenLines = botPerfList.map((b) => {
      const trades = b.perf?.recent_trades ?? [];
      const theme = BOT_THEMES[b.id] ?? BOT_THEMES["davy-jones"];
      let cum = 0;
      const curve = [0, ...trades.map((t: KrakenTradeEntry) => { cum += (t.pnl_pct ?? 0); return cum; })];
      return { id: b.id, name: b.status?.bot_name ?? b.id, icon: theme.icon, accent: theme.accent, curve };
    });

    const oracleSnapshots = perfHistory?.snapshots ?? [];
    const oracleCurve = oracleSnapshots.length > 1
      ? oracleSnapshots.slice(-20).map(s => s.cumulative_pnl_pct)
      : [0];
    krakenLines.unshift({ id: "oracle", name: "Oracle", icon: "🔮", accent: "#facc15", curve: oracleCurve });

    return krakenLines;
  }, [djPerf.data, bbPerf.data, caPerf.data, perfHistory]);

  const stats = [
    { label: "Fleet Equity", value: formatCurrency(grandTotal), color: "text-white", sub: "2 exchanges" },
    { label: "Total Trades", value: String(totalTrades), color: "text-white", sub: `${totalWins}W / ${totalTrades - totalWins}L` },
    { label: "Fleet Win Rate", value: combinedWinRate != null ? `${combinedWinRate.toFixed(1)}%` : "—", color: combinedWinRate != null && combinedWinRate >= 50 ? "text-green-400" : "text-amber-400", sub: "all bots combined" },
    { label: "Best Today", value: todayPerformers.best ? `${todayPerformers.best.icon} ${todayPerformers.best.name}` : "—", color: "text-green-400", sub: todayPerformers.best ? `${todayPerformers.best.dailyPnl >= 0 ? "+" : ""}${todayPerformers.best.dailyPnl.toFixed(2)}% daily P&L` : "no trades today" },
    { label: "Worst Today", value: todayPerformers.worst ? `${todayPerformers.worst.icon} ${todayPerformers.worst.name}` : "—", color: todayPerformers.worst && todayPerformers.worst.dailyPnl < 0 ? "text-red-400" : "text-muted-foreground", sub: todayPerformers.worst ? `${todayPerformers.worst.dailyPnl >= 0 ? "+" : ""}${todayPerformers.worst.dailyPnl.toFixed(2)}% daily P&L` : "no trades today" },
    { label: "Best/Worst Trade", value: bestKrakenPct > 0 || worstKrakenPct < 0 ? `+${bestKrakenPct.toFixed(1)}% / ${worstKrakenPct.toFixed(1)}%` : "—", color: "text-amber-400", sub: "fleet all-time extremes" },
  ];

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3">
        {stats.map((s) => (
          <div
            key={s.label}
            className="rounded-xl border border-white/5 bg-gradient-to-br from-slate-900/80 to-slate-950/60 p-3"
          >
            <div className="text-[9px] uppercase tracking-wider text-muted-foreground/60 mb-1">{s.label}</div>
            <div className={cn("text-base font-mono font-bold truncate", s.color)}>{s.value}</div>
            <div className="text-[8px] text-muted-foreground/40 mt-0.5">{s.sub}</div>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-4 px-1">
        <span className="text-[8px] uppercase font-bold tracking-wider text-muted-foreground/30">Equity Trend</span>
        {botSparklines.map((b) => (
          <div key={b.id} className="flex items-center gap-1.5">
            <span className="text-[10px]">{b.icon}</span>
            <MiniSparkline data={b.curve} color={b.accent} />
          </div>
        ))}
      </div>
    </div>
  );
}

function FleetComparisonMini() {
  const djPerf = useKrakenPerformance("davy-jones");
  const bbPerf = useKrakenPerformance("blackbeard");
  const caPerf = useKrakenPerformance("calypso");
  const djStatus = useKrakenStatus("davy-jones");
  const bbStatus = useKrakenStatus("blackbeard");
  const caStatus = useKrakenStatus("calypso");

  const bots = [
    { id: "davy-jones", data: djPerf.data, status: djStatus.data },
    { id: "blackbeard", data: bbPerf.data, status: bbStatus.data },
    { id: "calypso", data: caPerf.data, status: caStatus.data },
  ];

  const maxTrades = Math.max(1, ...bots.map(b => b.data?.total_trades ?? 0));

  return (
    <div className="rounded-2xl border border-cyan-500/10 bg-slate-900/40 overflow-hidden">
      <div className="px-4 py-2 text-[9px] uppercase font-bold text-cyan-400/60 tracking-widest border-b border-white/5 flex items-center gap-2">
        <Anchor className="h-3 w-3" />
        <span>Kraken Fleet</span>
      </div>
      <div className="p-3 space-y-3">
        {bots.map((b) => {
          const t = BOT_THEMES[b.id] ?? BOT_THEMES["davy-jones"];
          const trades = b.data?.total_trades ?? 0;
          const winRate = b.data?.win_rate_pct;
          const pnl = b.data?.total_pnl_usd;
          const equity = b.status?.total_equity_usd;
          const barW = maxTrades > 0 ? (trades / maxTrades) * 100 : 0;
          return (
            <div key={b.id} className="space-y-1">
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1.5 w-24 shrink-0">
                  <span className="text-xs">{t.icon}</span>
                  <span className="text-[10px] font-semibold text-white capitalize truncate">{b.id.replace("-", " ")}</span>
                </div>
                <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-800 ease-out"
                    style={{ backgroundColor: t.accent, width: `${barW}%` }}
                  />
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="text-[9px] font-mono text-muted-foreground">{trades}t</span>
                  <span className={cn("text-[9px] font-mono font-semibold", winRate != null && winRate >= 50 ? "text-green-400" : winRate != null ? "text-red-400" : "text-muted-foreground")}>
                    {winRate != null ? `${winRate.toFixed(0)}%` : "—"}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-3 pl-8 text-[8px] font-mono text-muted-foreground/50">
                <span>Eq: {equity != null ? formatCurrency(equity) : "—"}</span>
                <span className={cn((pnl ?? 0) >= 0 ? "text-green-400/60" : "text-red-400/60")}>
                  P&L: {pnl != null ? `${pnl >= 0 ? "+" : ""}$${Math.abs(pnl).toFixed(0)}` : "—"}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function KrakenFleetSection() {
  const { data: bots } = useKrakenBots();
  const botIds = bots?.map(b => b.bot_id) ?? ["davy-jones"];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {botIds.map((bid) => (
          <KrakenBotCard key={bid} botId={bid} />
        ))}
      </div>
      <StrategyComparisonPanel botIds={botIds} />
    </div>
  );
}

function StrategyComparisonPanel({ botIds }: { botIds: string[] }) {
  const dj = useKrakenPerformance("davy-jones");
  const bb = useKrakenPerformance("blackbeard");
  const ca = useKrakenPerformance("calypso");
  const perfMap: Record<string, typeof dj> = { "davy-jones": dj, blackbeard: bb, calypso: ca };

  const rows = botIds.map((id) => {
    const { data } = perfMap[id] ?? dj;
    const t = BOT_THEMES[id] ?? BOT_THEMES["davy-jones"];
    return {
      id,
      name: data?.bot_id ?? id,
      accent: t.accent,
      icon: t.icon,
      trades: data?.total_trades ?? 0,
      winRate: data?.win_rate_pct,
      totalPnl: data?.total_pnl_usd,
      avgPnl: data?.avg_trade_pct,
      equity: data?.current_equity ?? 0,
      status: data?.bot_status ?? "not_started",
    };
  });

  return (
    <div className="rounded-2xl border border-white/5 bg-slate-900/40 overflow-hidden">
      <div className="px-4 py-2 text-[9px] uppercase font-semibold text-muted-foreground tracking-wider border-b border-white/5 flex items-center gap-2">
        <span>Strategy Comparison</span>
        <span className="text-muted-foreground/40">·</span>
        <span className="text-muted-foreground/40">{botIds.length} bots</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[9px] uppercase text-muted-foreground/60 border-b border-white/5">
              <th className="text-left px-4 py-2 font-semibold">Bot</th>
              <th className="text-right px-3 py-2 font-semibold">Trades</th>
              <th className="text-right px-3 py-2 font-semibold">Win Rate</th>
              <th className="text-right px-3 py-2 font-semibold">Total P&L</th>
              <th className="text-right px-3 py-2 font-semibold">Avg Trade</th>
              <th className="text-right px-3 py-2 font-semibold">Equity</th>
              <th className="text-center px-3 py-2 font-semibold">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors">
                <td className="px-4 py-2.5">
                  <div className="flex items-center gap-2">
                    <span>{r.icon}</span>
                    <span className="font-semibold text-white capitalize">{r.id.replace("-", " ")}</span>
                  </div>
                </td>
                <td className="text-right px-3 py-2.5 font-mono text-white">{r.trades}</td>
                <td className="text-right px-3 py-2.5 font-mono" style={{ color: r.winRate != null && r.winRate >= 50 ? "#22c55e" : r.winRate != null ? "#ef4444" : "#64748b" }}>
                  {r.winRate != null ? `${r.winRate.toFixed(1)}%` : "—"}
                </td>
                <td className={cn("text-right px-3 py-2.5 font-mono font-semibold", (r.totalPnl ?? 0) >= 0 ? "text-green-400" : "text-red-400")}>
                  {r.totalPnl != null ? `${r.totalPnl >= 0 ? "+" : ""}$${r.totalPnl.toFixed(2)}` : "—"}
                </td>
                <td className={cn("text-right px-3 py-2.5 font-mono", (r.avgPnl ?? 0) >= 0 ? "text-green-400" : "text-red-400")}>
                  {r.avgPnl != null ? `${r.avgPnl >= 0 ? "+" : ""}${r.avgPnl.toFixed(2)}%` : "—"}
                </td>
                <td className="text-right px-3 py-2.5 font-mono text-white">
                  ${r.equity.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                </td>
                <td className="text-center px-3 py-2.5">
                  <span className={cn(
                    "text-[8px] font-bold px-2 py-0.5 rounded-full",
                    r.status === "running" ? "text-green-400 bg-green-500/10" :
                    r.status === "not_started" ? "text-slate-500 bg-slate-800/50" :
                    "text-amber-400 bg-amber-500/10"
                  )}>
                    {r.status.replace("_", " ").toUpperCase()}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
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
              Inspection Report
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
            ) : report && report.length > 0 ? (() => {
              const failed = report.filter(f => !f.passed);
              const passCount = report.length - failed.length;
              return (
                <div className="space-y-1.5">
                  {failed.length === 0 ? (
                    <p className="text-[11px] text-green-400/70 italic">All {passCount} checks passed.</p>
                  ) : (
                    <>
                      {failed.slice(0, 4).map((f, i) => {
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
                              {f.message.length > 50 ? f.message.slice(0, 50) + "…" : f.message}
                            </span>
                          </motion.div>
                        );
                      })}
                      {passCount > 0 && (
                        <p className="text-[9px] text-muted-foreground/40">{passCount}/{report.length} checks passed · tap for full report</p>
                      )}
                    </>
                  )}
                </div>
              );
            })() : (
              <p className="text-[11px] text-muted-foreground/50 italic">No audit run yet.</p>
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
            <span className="text-sm font-semibold text-white">Inspector Rekt — HITL Supervisor</span>
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
  const { data: perfData, isLoading: isPerfLoading } = useAuditorPerformance();
  const { mutate: runPerf, isPending: isRunningPerf } = useTriggerPerformanceAnalysis();
  const { data: snapshotInfo } = useLearningSnapshotInfo();
  const { mutate: syncSnapshot, isPending: isSyncing } = useSyncLearningSnapshot();
  const [showInsights, setShowInsights] = useState(false);
  const [showPerf, setShowPerf] = useState(false);
  const [showSync, setShowSync] = useState(false);

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

      <div className="relative rounded-2xl border border-amber-500/20 bg-gradient-to-br from-slate-950/90 to-amber-950/15 p-5 shadow-[0_0_60px_rgba(234,179,8,0.06)] overflow-hidden flex-1 flex flex-col">
        <div className="absolute top-0 left-0 w-48 h-48 bg-amber-500/5 rounded-full blur-3xl -translate-x-1/4 -translate-y-1/4 pointer-events-none" />
        <div className="absolute bottom-0 right-0 w-64 h-64 bg-yellow-500/3 rounded-full blur-3xl translate-x-1/4 translate-y-1/4 pointer-events-none" />

        <div className="relative flex items-center gap-2 mb-4">
          <Shield className="h-3.5 w-3.5 text-amber-400" />
          <span className="text-[10px] uppercase font-semibold tracking-wider text-amber-400/80">
            Inspector Rekt
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

        <div className="relative flex flex-col sm:flex-row items-center sm:items-start gap-3 sm:gap-5">
          <motion.div
            className="flex-shrink-0 w-24 h-24 sm:w-44 sm:h-44 cursor-pointer relative group"
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

        {/* ── Sync Learning Snapshot ───────────────────────────────────────── */}
        <div className="relative mt-4 pt-4 border-t border-white/5">
          <button
            onClick={() => setShowSync(v => !v)}
            className="w-full flex items-center gap-2 text-left group"
          >
            <Database className="h-3 w-3 text-violet-400/70" />
            <span className="text-[9px] uppercase font-semibold tracking-wider text-muted-foreground/70 group-hover:text-violet-400/80 transition-colors">
              Sync Learning
            </span>
            {snapshotInfo?.llm_learnings_count != null && (
              <span className="text-[8px] text-muted-foreground/30 font-mono ml-1">
                {snapshotInfo.llm_learnings_count} learnings
              </span>
            )}
            <span className={cn("ml-auto text-muted-foreground/30 text-[10px] transition-transform duration-200", showSync && "rotate-180")}>▾</span>
          </button>

          <AnimatePresence>
            {showSync && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="overflow-hidden"
              >
                <div className="pt-3 space-y-3">
                  <p className="text-[10px] text-slate-400/70 leading-relaxed">
                    Snapshots bundle all LLM learnings and Kraken adaptive parameters into a file committed with the repo.
                    Production starts seeded with this data so knowledge survives redeploys.
                  </p>

                  {snapshotInfo && snapshotInfo.status !== "not_found" && (
                    <div className="grid grid-cols-2 gap-2 text-[9px] font-mono">
                      {[
                        ["LLM Learnings", snapshotInfo.llm_learnings_count ?? "—"],
                        ["Kraken Params n", snapshotInfo.kraken_params_n ?? "—"],
                        ["File Size", snapshotInfo.file_size_bytes != null ? `${(snapshotInfo.file_size_bytes / 1024).toFixed(1)} KB` : "—"],
                        ["Exported", snapshotInfo.exported_at ? new Date(snapshotInfo.exported_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"],
                      ].map(([label, val]) => (
                        <div key={String(label)}>
                          <div className="text-[7px] text-muted-foreground/40 uppercase">{label}</div>
                          <div className="text-white/70 mt-0.5">{String(val)}</div>
                        </div>
                      ))}
                    </div>
                  )}

                  {snapshotInfo?.status === "not_found" && (
                    <p className="text-[10px] text-muted-foreground/40 italic">No snapshot file found — click below to generate one.</p>
                  )}

                  <button
                    onClick={() => syncSnapshot()}
                    disabled={isSyncing}
                    className={cn(
                      "flex items-center gap-1.5 text-[9px] font-semibold uppercase tracking-wide px-3 py-1.5 rounded-lg border transition-all duration-200",
                      isSyncing
                        ? "opacity-50 cursor-not-allowed border-white/10 text-muted-foreground"
                        : "border-violet-500/20 bg-violet-500/5 text-violet-400/60 hover:bg-violet-500/15 hover:text-violet-400 hover:border-violet-500/40"
                    )}
                  >
                    {isSyncing ? (
                      <>
                        <RefreshCw className="h-3 w-3 animate-spin" />
                        <span>Exporting…</span>
                      </>
                    ) : (
                      <>
                        <Database className="h-3 w-3" />
                        <span>Export Snapshot Now</span>
                      </>
                    )}
                  </button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* ── Performance Analysis ─────────────────────────────────────────── */}
        <div className="relative mt-4 pt-4 border-t border-white/5">
          <button
            onClick={() => setShowPerf(v => !v)}
            className="w-full flex items-center gap-2 text-left group"
          >
            <TrendingUp className="h-3 w-3 text-cyan-400/70" />
            <span className="text-[9px] uppercase font-semibold tracking-wider text-muted-foreground/70 group-hover:text-cyan-400/80 transition-colors">
              Performance Analysis
            </span>
            {perfData?.run_at && (
              <span className="text-[8px] text-muted-foreground/30 font-mono ml-1">
                {new Date(perfData.run_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </span>
            )}
            <span className={cn("ml-auto text-muted-foreground/30 text-[10px] transition-transform duration-200", showPerf && "rotate-180")}>▾</span>
          </button>

          <AnimatePresence>
            {showPerf && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="overflow-hidden"
              >
                <div className="pt-3 space-y-3">
                  {/* Stats grid */}
                  {(perfData?.alpaca || perfData?.kraken) && (
                    <div className="grid grid-cols-2 gap-2">
                      {perfData.alpaca && (
                        <div className="rounded-lg border border-orange-500/15 bg-orange-950/[0.07] p-2.5">
                          <div className="text-[8px] text-orange-400/50 uppercase font-semibold tracking-wide mb-1.5">⚡ Degen Oracle</div>
                          <div className="grid grid-cols-3 gap-x-3 gap-y-1">
                            {[
                              ["Trades", perfData.alpaca.total],
                              ["Wins",   perfData.alpaca.wins],
                              ["Losses", perfData.alpaca.losses],
                              ["Win %",  perfData.alpaca.win_rate != null ? `${(perfData.alpaca.win_rate * 100).toFixed(0)}%` : "—"],
                              ["Avg P&L", perfData.alpaca.avg_pnl != null ? `${perfData.alpaca.avg_pnl >= 0 ? "+" : ""}${perfData.alpaca.avg_pnl.toFixed(1)}%` : "—", 2],
                            ].map(([label, value, span]) => (
                              <div key={String(label)} className={cn(span === 2 ? "col-span-2" : "")}>
                                <div className="text-[7px] text-muted-foreground/40 uppercase">{label}</div>
                                <div className={cn("text-[10px] font-mono font-semibold mt-0.5", String(value).startsWith("+") ? "text-green-400" : String(value).startsWith("-") ? "text-red-400" : "text-white/70")}>
                                  {String(value)}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                      {perfData.kraken && (
                        <div className="rounded-lg border border-cyan-500/15 bg-cyan-950/[0.07] p-2.5">
                          <div className="text-[8px] text-cyan-400/50 uppercase font-semibold tracking-wide mb-1.5">🐙 Davy Jones</div>
                          <div className="grid grid-cols-3 gap-x-3 gap-y-1">
                            {[
                              ["Trades", perfData.kraken.total],
                              ["Wins",   perfData.kraken.wins],
                              ["Losses", perfData.kraken.losses],
                              ["Win %",  perfData.kraken.win_rate != null ? `${(perfData.kraken.win_rate * 100).toFixed(0)}%` : "—"],
                              ["Avg P&L", perfData.kraken.avg_pnl != null ? `${perfData.kraken.avg_pnl >= 0 ? "+" : ""}${perfData.kraken.avg_pnl.toFixed(1)}%` : "—", 2],
                            ].map(([label, value, span]) => (
                              <div key={String(label)} className={cn(span === 2 ? "col-span-2" : "")}>
                                <div className="text-[7px] text-muted-foreground/40 uppercase">{label}</div>
                                <div className={cn("text-[10px] font-mono font-semibold mt-0.5", String(value).startsWith("+") ? "text-green-400" : String(value).startsWith("-") ? "text-red-400" : "text-white/70")}>
                                  {String(value)}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* LLM narrative */}
                  {perfData?.narrative ? (
                    <div className="rounded-lg border border-amber-500/10 bg-amber-950/[0.05] p-3">
                      <div className="flex items-center gap-1.5 mb-2">
                        <Brain className="h-3 w-3 text-amber-400/50" />
                        <span className="text-[8px] text-amber-400/40 uppercase font-semibold tracking-wide">AI Narrative</span>
                      </div>
                      <p className="text-[10px] text-slate-300/80 leading-relaxed">
                        {perfData.narrative}
                      </p>
                    </div>
                  ) : (
                    !isPerfLoading && (
                      <p className="text-[10px] text-muted-foreground/40 italic">
                        {perfData?.status === "no_data" ? "No trade data found for analysis window." : "No analysis run yet — click below to generate."}
                      </p>
                    )
                  )}

                  {isPerfLoading && (
                    <div className="flex items-center gap-2 text-[10px] text-muted-foreground/50 italic">
                      <RefreshCw className="h-3 w-3 animate-spin" />
                      <span>Loading performance data…</span>
                    </div>
                  )}

                  {/* Run analysis button */}
                  <button
                    onClick={() => runPerf(10)}
                    disabled={isRunningPerf}
                    className={cn(
                      "flex items-center gap-1.5 text-[9px] font-semibold uppercase tracking-wide px-3 py-1.5 rounded-lg border transition-all duration-200",
                      isRunningPerf
                        ? "opacity-50 cursor-not-allowed border-white/10 text-muted-foreground"
                        : "border-cyan-500/20 bg-cyan-500/5 text-cyan-400/60 hover:bg-cyan-500/15 hover:text-cyan-400 hover:border-cyan-500/40"
                    )}
                  >
                    {isRunningPerf ? (
                      <>
                        <RefreshCw className="h-3 w-3 animate-spin" />
                        <span>Analysing…</span>
                      </>
                    ) : (
                      <>
                        <TrendingUp className="h-3 w-3" />
                        <span>Run 10-day Analysis</span>
                      </>
                    )}
                  </button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
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
    <div className="w-full overflow-hidden bg-slate-950/60 border-b border-white/5 hidden md:flex h-7 items-center relative">
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

function MobilePositionCard({ pos, onThesisClick, onEject, confirmClose, setConfirmClose, isClosing, isRebalancing, closingSymbol }: {
  pos: LivePosition;
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
        <div className="flex justify-between">
          <span className="text-muted-foreground">Qty</span>
          <span className="font-mono text-white">{pos.qty.toFixed(4)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Notional</span>
          <span className="font-mono text-white">{formatCurrency(pos.market_value)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Entry</span>
          <span className="font-mono text-muted-foreground">{formatCurrency(pos.avg_entry_price)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Current</span>
          <span className="font-mono text-white">{formatCurrency(pos.current_price)}</span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-muted-foreground">P&L</span>
          <RollingPnl value={pos.unrealized_pl} pct={pos.unrealized_plpc} />
        </div>
        {(pos.stop_loss_price != null || pos.take_profit_price != null) && (
          <div className="flex justify-between">
            <span className="text-muted-foreground">SL/Trail</span>
            <span className="font-mono text-[10px]">
              {pos.stop_loss_price != null && <span className="text-red-400">{formatCurrency(pos.stop_loss_price)}</span>}
              {pos.stop_loss_price != null && pos.take_profit_price != null && <span className="text-muted-foreground mx-0.5">/</span>}
              {pos.take_profit_price != null && <span className="text-green-400">{formatCurrency(pos.take_profit_price)}</span>}
            </span>
          </div>
        )}
      </div>

      {pos.original_thesis && (
        <p
          className="text-[10px] text-muted-foreground/70 italic truncate cursor-pointer hover:text-indigo-400 border-b border-dashed border-indigo-500/20 pb-0.5"
          onClick={() => onThesisClick(pos.symbol, pos.original_thesis)}
        >
          "{pos.original_thesis}"
        </p>
      )}

      <div className="flex justify-end" onClick={(e) => e.stopPropagation()}>
        {closingSymbol === pos.symbol ? (
          <div className="flex items-center gap-1.5 text-[10px] text-orange-400/70">
            <RefreshCw className="h-3 w-3 animate-spin" />
            <span>Closing…</span>
          </div>
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
            <LogOut className="h-2.5 w-2.5" />
            <span>Eject</span>
          </button>
        )}
      </div>
    </motion.div>
  );
}

function LivePositionsSection() {
  const isMobile = useIsMobile();
  const { data, isLoading } = useLivePositions();
  const { data: krakenStatus } = useKrakenStatus();
  const { data: platformStatus } = usePlatformStatus();
  const { mutate: rebalance, isPending: isRebalancing } = useForceRebalance();
  const { mutate: closeAndReallocate, isPending: isClosing, variables: closingVar } = useCloseAndReallocate();
  const { toast } = useToast();
  const [thesisModal, setThesisModal] = useState<{ ticker: string; thesis: string | null } | null>(null);
  const [confirmRebalance, setConfirmRebalance] = useState(false);
  const marketClosed = !platformStatus?.market.is_open;
  const countdown = useMarketCountdown(marketClosed ? platformStatus?.market.next_open : null);
  const [confirmClose, setConfirmClose] = useState<string | null>(null);

  const closingSymbol = isClosing ? (closingVar as string) : null;
  const krakenPositions = krakenStatus?.open_positions ?? [];

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
    return alpacaPnl + krakenPnl;
  }, [data, krakenPositions]);

  const totalCount = (data?.count ?? 0) + krakenPositions.length;

  return (
    <Card className="border-white/5 overflow-hidden">
      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-3 sm:py-4">
        <CardTitle className="flex flex-wrap items-center gap-2 fluid-heading">
          <Target className="h-4 w-4 text-primary" />
          <span className="hidden md:inline">Live Open Positions</span>
          <span className="md:hidden">Positions</span>
          {(data || krakenPositions.length > 0) && (
            <Badge variant={totalCount > 0 ? "default" : "outline"} className="text-[10px] px-1.5 py-0">
              {totalCount}
            </Badge>
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
                <button
                  onClick={() => { rebalance(); setConfirmRebalance(false); }}
                  className="text-[10px] font-bold px-2.5 py-1.5 rounded-md bg-orange-500/20 text-orange-400 border border-orange-500/30 hover:bg-orange-500/30 transition-colors min-h-[44px]"
                >
                  Confirm
                </button>
                <button
                  onClick={() => setConfirmRebalance(false)}
                  className="text-[10px] font-bold px-2 py-1.5 rounded-md bg-slate-800 text-muted-foreground border border-white/10 hover:bg-slate-700 transition-colors min-h-[44px]"
                >
                  Cancel
                </button>
              </div>
            )}
          </div>
        </CardTitle>
      </CardHeader>
      {/* ── Loading state ── */}
      {isLoading && (
        <div className="py-6 text-center text-muted-foreground italic text-xs px-4">Loading positions...</div>
      )}

      {/* ── Alpaca / Degen Oracle positions — collapsible card list ── */}
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

      {/* ── Empty state (both bots have no positions) ── */}
      {!isLoading && (!data || data.positions.length === 0) && krakenPositions.length === 0 && (
        <div className="flex flex-col items-center gap-2 py-8 px-4">
          <motion.div animate={{ opacity: [0.3, 0.6, 0.3] }} transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}>
            <Target className="h-8 w-8 text-muted-foreground/20" />
          </motion.div>
          <p className="text-muted-foreground/50 italic text-xs">No open positions — system is in cash</p>
          <p className="text-[9px] text-muted-foreground/30">Awaiting next analysis cycle</p>
        </div>
      )}

      {/* dummy block to keep the structure intact — replaced the old table/mobile split */}
      {false && (
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
              <th className="px-5 py-3 font-semibold text-right">Trail Stop</th>
              <th className="px-5 py-3 font-semibold text-center">Conv.</th>
              <th className="px-5 py-3 font-semibold text-center">Health</th>
              <th className="px-5 py-3 font-semibold max-w-[180px]">Thesis</th>
              <th className="px-4 py-3 font-semibold text-center">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {isLoading && (
              <tr><td colSpan={12} className="px-5 py-6 text-center text-muted-foreground italic text-xs">Loading positions...</td></tr>
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
                    <RollingPnl value={pos.unrealized_pl} pct={pos.unrealized_plpc} />
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
                  <td className="px-5 py-3.5 text-center">
                    {pos.health_score ? (() => {
                      const colorMap: Record<string, string> = { green: "#22c55e", emerald: "#10b981", amber: "#f59e0b", orange: "#f97316", red: "#ef4444" };
                      const cssColor = colorMap[pos.health_score.color] || pos.health_score.color;
                      return (
                        <div className="flex flex-col items-center gap-0.5">
                          <span className="text-xs font-mono font-bold" style={{ color: cssColor }}>
                            {pos.health_score.score}
                          </span>
                          <span className="text-[9px]" style={{ color: cssColor }}>
                            {pos.health_score.label}
                          </span>
                        </div>
                      );
                    })() : <span className="text-muted-foreground text-xs">—</span>}
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
                  <td className="px-4 py-3.5 text-center" onClick={(e) => e.stopPropagation()}>
                    {closingSymbol === pos.symbol ? (
                      <div className="flex items-center justify-center gap-1.5 text-[10px] text-orange-400/70">
                        <RefreshCw className="h-3 w-3 animate-spin" />
                        <span>Closing…</span>
                      </div>
                    ) : confirmClose === pos.symbol ? (
                      <div className="flex items-center justify-center gap-1.5">
                        <span className="text-[9px] text-orange-300/80 whitespace-nowrap">Close &amp; re-enter?</span>
                        <button
                          onClick={() => handleCloseAndReallocate(pos.symbol)}
                          className="text-[9px] font-bold px-2 py-0.5 rounded bg-orange-500/20 text-orange-400 border border-orange-500/30 hover:bg-orange-500/35 transition-colors"
                        >
                          Yes
                        </button>
                        <button
                          onClick={() => setConfirmClose(null)}
                          className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-slate-800 text-muted-foreground border border-white/10 hover:bg-slate-700 transition-colors"
                        >
                          No
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setConfirmClose(pos.symbol)}
                        disabled={isClosing || isRebalancing}
                        title="Force-close this position and reallocate capital"
                        className={cn(
                          "flex items-center gap-1 text-[9px] font-semibold uppercase tracking-wide px-2.5 py-1.5 rounded-lg border transition-all duration-200 mx-auto",
                          isClosing || isRebalancing
                            ? "opacity-40 cursor-not-allowed border-white/10 text-muted-foreground"
                            : "border-orange-500/20 bg-orange-500/5 text-orange-400/60 hover:bg-orange-500/15 hover:text-orange-400 hover:border-orange-500/40"
                        )}
                      >
                        <LogOut className="h-2.5 w-2.5" />
                        <span>Eject</span>
                      </button>
                    )}
                  </td>
                </motion.tr>
              );
            })}
            {!isLoading && (!data?.positions?.length) && krakenPositions.length === 0 && (
              <tr>
                <td colSpan={12} className="px-5 py-8 text-center">
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
      )}

      {/* ── Kraken / Davy Jones crypto positions — collapsible card list ── */}
      <KrakenPositionsPanel
        positions={krakenPositions}
        signals={krakenStatus?.signals ?? []}
        isPaper={krakenStatus?.paper_trading}
      />

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

// ── Combined Trade History (both bots, Overview tab) ─────────────────────────

function CombinedTradeHistorySection() {
  const { data: alpacaData, isLoading: alpacaLoading } = useRecentTrades(50);
  const { data: krakenPerf, isLoading: krakenLoading } = useKrakenPerformance();

  const combined = useMemo(() => {
    const alpacaRows = (alpacaData?.trades ?? []).map((t) => ({
      source: "alpaca" as const,
      symbol: t.symbol,
      side: t.pnl_pct >= 0 ? "long" : "short",
      pnl_pct: t.pnl_pct,
      pnl_usd: t.pnl_usd,
      closed_at: t.closed_at,
      reason: t.exit_reason ?? "",
      is_win: t.pnl_pct > 0,
    }));
    const krakenRows = (krakenPerf?.recent_trades ?? []).map((t) => ({
      source: "kraken" as const,
      symbol: t.symbol.replace("/USD", ""),
      side: t.side,
      pnl_pct: t.pnl_pct,
      pnl_usd: t.pnl_usd,
      closed_at: t.closed_at,
      reason: t.reason ?? "",
      is_win: t.pnl_pct > 0,
    }));
    return [...alpacaRows, ...krakenRows]
      .sort((a, b) => new Date(b.closed_at).getTime() - new Date(a.closed_at).getTime())
      .slice(0, 40);
  }, [alpacaData, krakenPerf]);

  const isLoading = alpacaLoading || krakenLoading;
  const wins = combined.filter((t) => t.is_win).length;
  const losses = combined.length - wins;
  const totalPnlUsd = combined.reduce((s, t) => s + (t.pnl_usd ?? 0), 0);
  const winRate = combined.length > 0 ? Math.round((wins / combined.length) * 100) : null;

  const fmtDate = (s: string) => {
    try {
      const d = new Date(s);
      return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
    } catch {
      return s.slice(0, 10);
    }
  };

  return (
    <Card className="border-white/5 overflow-hidden">
      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-3 sm:py-4">
        <CardTitle className="flex flex-wrap items-center gap-2 fluid-heading">
          <History className="h-4 w-4 text-primary" />
          <span>Combined Trade History</span>
          <span className="ml-1 text-[9px] font-normal text-muted-foreground/60 border border-white/10 bg-white/5 px-1.5 py-0.5 rounded-full uppercase tracking-wider">
            Both Bots
          </span>
          {combined.length > 0 && (
            <div className="flex items-center gap-2 ml-auto">
              <span className="text-[10px] font-mono text-green-400">{wins}W</span>
              <span className="text-[10px] text-muted-foreground/40">/</span>
              <span className="text-[10px] font-mono text-red-400">{losses}L</span>
              {winRate != null && (
                <span className={cn("text-[10px] font-mono font-bold border px-1.5 py-0.5 rounded-full",
                  winRate >= 50 ? "text-green-400 border-green-500/20 bg-green-500/5" : "text-amber-400 border-amber-500/20 bg-amber-500/5"
                )}>{winRate}% win</span>
              )}
              <span className={cn("text-xs font-mono font-semibold", totalPnlUsd >= 0 ? "text-green-400" : "text-red-400")}>
                {totalPnlUsd >= 0 ? "+" : ""}{formatCurrency(totalPnlUsd)}
              </span>
            </div>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {isLoading ? (
          <div className="flex items-center justify-center py-8 gap-2 text-xs text-muted-foreground/50">
            <RefreshCw className="h-3.5 w-3.5 animate-spin" />
            Loading trades…
          </div>
        ) : combined.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 gap-2 text-center">
            <History className="h-7 w-7 text-muted-foreground/15" />
            <p className="text-xs text-muted-foreground/50">No closed trades yet</p>
            <p className="text-[10px] text-muted-foreground/30">History will appear here as positions close</p>
          </div>
        ) : (
          <div className="max-h-72 overflow-y-auto divide-y divide-white/5">
            {/* Column headers */}
            <div className="grid grid-cols-[auto_1fr_auto_auto_auto] gap-x-3 px-4 py-2 text-[9px] uppercase tracking-wider text-muted-foreground/50 sticky top-0 bg-slate-950/80 backdrop-blur-sm z-10">
              <span>Bot</span>
              <span>Asset</span>
              <span className="text-right">P&amp;L %</span>
              <span className="text-right hidden sm:block">P&amp;L $</span>
              <span className="text-right">Date</span>
            </div>
            {combined.map((t, i) => (
              <div
                key={i}
                className={cn(
                  "grid grid-cols-[auto_1fr_auto_auto_auto] gap-x-3 items-center px-4 py-2.5 text-[11px] transition-colors hover:bg-white/2",
                  t.is_win ? "border-l-2 border-green-500/20" : "border-l-2 border-red-500/20"
                )}
              >
                {/* Source badge */}
                <span className={cn(
                  "text-[8px] font-bold uppercase tracking-widest px-1.5 py-0.5 rounded border shrink-0",
                  t.source === "kraken"
                    ? "text-cyan-400 border-cyan-500/20 bg-cyan-500/5"
                    : "text-blue-400 border-blue-500/20 bg-blue-500/5"
                )}>
                  {t.source === "kraken" ? "KRK" : "ALP"}
                </span>

                {/* Symbol + side */}
                <div className="flex items-center gap-1.5 min-w-0">
                  <span className="font-mono font-bold text-white/90 truncate">{t.symbol}</span>
                  {t.source === "kraken" && (
                    <span className={cn(
                      "text-[8px] font-semibold uppercase tracking-wider px-1 py-0.5 rounded shrink-0",
                      t.side === "long"
                        ? "text-blue-400/80 bg-blue-500/10"
                        : "text-purple-400/80 bg-purple-500/10"
                    )}>
                      {t.side}
                    </span>
                  )}
                </div>

                {/* P&L % */}
                <span className={cn("font-mono font-bold text-right tabular-nums shrink-0",
                  t.is_win ? "text-green-400" : "text-red-400"
                )}>
                  {t.pnl_pct >= 0 ? "+" : ""}{t.pnl_pct.toFixed(2)}%
                </span>

                {/* P&L $ */}
                <span className={cn("font-mono text-right tabular-nums text-[10px] shrink-0 hidden sm:block",
                  t.pnl_usd != null
                    ? t.is_win ? "text-green-400/60" : "text-red-400/60"
                    : "text-muted-foreground/30"
                )}>
                  {t.pnl_usd != null
                    ? `${t.pnl_usd >= 0 ? "+" : ""}${formatCurrency(t.pnl_usd)}`
                    : "—"}
                </span>

                {/* Date */}
                <span className="text-[9px] text-muted-foreground/50 font-mono text-right shrink-0">
                  {fmtDate(t.closed_at)}
                </span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
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

// ── Live Equity Curve (from equity_snapshots table) ───────────────────────────
function LiveEquityCurveSection() {
  const { data, isLoading } = useEquityCurve(500);
  const snapshots = data?.snapshots ?? [];

  // Compute drawdown from peak
  const { peak, drawdownPct } = useMemo(() => {
    if (!snapshots.length) return { peak: 0, drawdownPct: 0 };
    let pk = -Infinity;
    for (const s of snapshots) pk = Math.max(pk, s.total_equity);
    const last = snapshots[snapshots.length - 1]?.total_equity ?? pk;
    const dd = pk > 0 ? ((last - pk) / pk) * 100 : 0;
    return { peak: pk, drawdownPct: dd };
  }, [snapshots]);

  const chartData = useMemo(() => snapshots.map((s) => ({
    ts: new Date(s.ts).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }),
    total: s.total_equity,
    alpaca: s.alpaca_equity,
    kraken: s.kraken_equity,
    regime: s.regime,
  })), [snapshots]);

  const last = snapshots[snapshots.length - 1];
  const first = snapshots[0];
  const gainPct = first && last && first.total_equity > 0
    ? ((last.total_equity - first.total_equity) / first.total_equity) * 100
    : null;

  const EquityTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null;
    return (
      <div className="bg-slate-900 border border-white/10 rounded-lg px-3 py-2 text-xs shadow-xl">
        <p className="text-muted-foreground mb-1">{label}</p>
        {payload.map((p: any) => (
          <p key={p.dataKey} style={{ color: p.color }} className="font-mono">
            {p.name}: {formatCurrency(p.value)}
          </p>
        ))}
        {payload[0]?.payload?.regime && (
          <p className="text-slate-500 mt-1">Regime: {payload[0].payload.regime}</p>
        )}
      </div>
    );
  };

  return (
    <Card className="border-white/5 overflow-hidden mb-4">
      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-3 flex flex-col sm:flex-row sm:items-center justify-between gap-1.5">
        <CardTitle className="flex items-center gap-2 fluid-heading">
          <TrendingUp className="h-4 w-4 text-primary" />
          <span>Live Portfolio Equity Curve</span>
          <span className="ml-1 text-[9px] font-normal text-cyan-400/60 border border-cyan-400/20 bg-cyan-400/5 px-1.5 py-0.5 rounded-full uppercase tracking-wider">Alpaca + Kraken</span>
        </CardTitle>
        <div className="flex items-center gap-4">
          {last && (
            <span className="text-xs font-mono text-white">{formatCurrency(last.total_equity)}</span>
          )}
          {gainPct != null && (
            <span className={cn("text-xs font-mono", gainPct >= 0 ? "text-green-400" : "text-red-400")}>
              {gainPct >= 0 ? "+" : ""}{gainPct.toFixed(2)}%
            </span>
          )}
          {drawdownPct < -0.01 && (
            <span className="text-xs font-mono text-amber-400">
              DD: {drawdownPct.toFixed(2)}%
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent className="p-4">
        {isLoading ? (
          <div className="h-40 flex items-center justify-center text-xs text-muted-foreground">Loading equity data…</div>
        ) : snapshots.length < 2 ? (
          <div className="h-40 flex flex-col items-center justify-center gap-1">
            <TrendingUp className="h-6 w-6 text-muted-foreground/30" />
            <p className="text-xs text-muted-foreground">No equity history yet</p>
            <p className="text-[10px] text-muted-foreground/50">Data is recorded after each completed trading cycle</p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={chartData} margin={{ top: 4, right: 4, left: 4, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis dataKey="ts" tick={{ fontSize: 9, fill: "#64748b" }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
              <YAxis
                tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
                tick={{ fontSize: 9, fill: "#64748b" }}
                tickLine={false}
                axisLine={false}
                width={42}
              />
              <Tooltip content={<EquityTooltip />} />
              <Line type="monotone" dataKey="total" name="Total" stroke="#3b82f6" strokeWidth={2} dot={false} activeDot={{ r: 3, fill: "#3b82f6" }} />
              <Line type="monotone" dataKey="alpaca" name="Alpaca" stroke="#22c55e" strokeWidth={1} dot={false} strokeDasharray="4 2" />
              <Line type="monotone" dataKey="kraken" name="Kraken" stroke="#f59e0b" strokeWidth={1} dot={false} strokeDasharray="4 2" />
            </LineChart>
          </ResponsiveContainer>
        )}
        <div className="flex items-center gap-4 mt-2 justify-end">
          <div className="flex items-center gap-1.5"><div className="w-3 h-0.5 bg-blue-500 rounded" /><span className="text-[9px] text-muted-foreground">Total</span></div>
          <div className="flex items-center gap-1.5"><div className="w-3 h-0.5 bg-green-500 rounded opacity-60" /><span className="text-[9px] text-muted-foreground">Alpaca</span></div>
          <div className="flex items-center gap-1.5"><div className="w-3 h-0.5 bg-amber-500 rounded opacity-60" /><span className="text-[9px] text-muted-foreground">Kraken</span></div>
        </div>
      </CardContent>
    </Card>
  );
}

function PerformanceSection() {
  const isMobile = useIsMobile();
  const { data: history } = usePerformanceHistory();
  const { data: summary } = usePerformanceSummary();
  const { data: attrData } = useAttribution();

  const chartHeight = isMobile ? 140 : 180;
  const hasData = history && history.count > 0;

  // Fallback stats from attribution when no performance snapshots exist
  const totalTrades = summary?.total_trades ?? attrData?.closed_trades ?? null;
  const winRate = summary?.avg_win_rate != null
    ? summary.avg_win_rate * 100
    : attrData?.overall?.win_rate ?? null;
  const winCount = attrData?.overall?.wins ?? null;
  const lossCount = attrData?.overall?.losses ?? null;
  const avgPnl = attrData?.overall?.avg_pnl_pct ?? null;
  const hasAttrFallback = !hasData && attrData?.closed_trades != null;

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
      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-3 sm:py-4 flex flex-col sm:flex-row sm:items-center justify-between gap-1.5 sm:gap-0">
        <CardTitle className="flex items-center gap-2 fluid-heading">
          <BarChart3 className="h-4 w-4 text-primary" />
          <span>Alpaca — Stock Trading Performance</span>
          <span className="ml-1 text-[9px] font-normal text-blue-400/60 border border-blue-400/20 bg-blue-400/5 px-1.5 py-0.5 rounded-full uppercase tracking-wider">US Equities · Alpaca</span>
        </CardTitle>
        {summary?.latest_date && (
          <span className="text-[10px] text-muted-foreground terminal-text">
            Last snapshot: {summary.latest_date}
          </span>
        )}
      </CardHeader>
      <CardContent className="p-5">

        {/* Summary stat cards — with attribution fallback when no snapshot history */}
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
              value: winRate != null ? `${winRate.toFixed(1)}%` : "—",
              color: winRate != null
                ? winRate >= 50 ? "text-green-400" : "text-amber-400"
                : "text-muted-foreground",
            },
            {
              label: "Best Trade",
              value: summary?.best_day_pct != null ? `+${summary.best_day_pct.toFixed(2)}%` : "—",
              color: "text-green-400",
            },
            {
              label: "Worst Trade",
              value: summary?.worst_day_pct != null ? `${summary.worst_day_pct.toFixed(2)}%` : "—",
              color: "text-red-400",
            },
            {
              label: "Total Trades",
              value: totalTrades != null ? String(totalTrades) : "—",
              sub: winCount != null && lossCount != null ? `${winCount}W / ${lossCount}L` : undefined,
              color: "text-white",
            },
            {
              label: "Avg P&L",
              value: avgPnl != null
                ? `${avgPnl >= 0 ? "+" : ""}${avgPnl.toFixed(2)}%`
                : summary?.avg_conviction != null
                  ? `${(summary.avg_conviction * 100).toFixed(1)}% conv`
                  : "—",
              color: avgPnl != null
                ? avgPnl >= 0 ? "text-green-400" : "text-red-400"
                : summary?.avg_conviction != null
                  ? summary.avg_conviction >= 0.75 ? "text-green-400" : "text-amber-400"
                  : "text-muted-foreground",
            },
          ].map((stat) => (
            <div key={stat.label} className="bg-slate-900/70 rounded-xl p-3 border border-white/5">
              <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1">{stat.label}</div>
              <div className={cn("text-xl font-mono font-bold", stat.color)}>{stat.value}</div>
              {(stat as any).sub && <div className="text-[9px] text-muted-foreground/60 mt-0.5 font-mono">{(stat as any).sub}</div>}
            </div>
          ))}
        </div>

        {!hasData ? (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <BarChart3 className="h-10 w-10 text-muted-foreground/30 mb-3" />
            {hasAttrFallback ? (
              <>
                <p className="text-sm text-muted-foreground">Equity curve builds after first post-mortem</p>
                <p className="text-xs text-muted-foreground/60 mt-1">Stats above sourced from trade journal · {attrData!.closed_trades} closed trade{attrData!.closed_trades !== 1 ? "s" : ""} recorded</p>
              </>
            ) : (
              <>
                <p className="text-sm text-muted-foreground">Performance history appears after the first post-mortem runs</p>
                <p className="text-xs text-muted-foreground/60 mt-1">The system records a snapshot automatically each weekday at 4:10 PM ET after market close</p>
              </>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Equity Curve */}
            <div>
              <div className="text-xs font-medium text-muted-foreground mb-3 uppercase tracking-wide">Equity Curve</div>
              <ResponsiveContainer width="100%" height={chartHeight}>
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
              <ResponsiveContainer width="100%" height={chartHeight}>
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

// ── Kraken Crypto Performance Section ────────────────────────────────────────
// DATA SOURCE: kraken-bot/status.json  (Kraken exchange)
// INDEPENDENT FROM: Alpaca stock trading system — separate exchange, separate capital

function KrakenPerformanceSection() {
  const { data, isLoading } = useKrakenPerformance();

  const pnlColor = (v: number | null) =>
    v == null ? "text-muted-foreground" : v >= 0 ? "text-green-400" : "text-red-400";

  const fmt = (v: number | null, prefix = "", suffix = "") =>
    v == null ? "—" : `${prefix}${v >= 0 ? "+" : ""}${v.toFixed(2)}${suffix}`;

  const stats = [
    {
      label: "Total P&L",
      value: data?.total_pnl_pct != null
        ? `${data.total_pnl_pct >= 0 ? "+" : ""}${data.total_pnl_pct.toFixed(2)}%`
        : "—",
      sub: data?.total_pnl_usd != null
        ? `${data.total_pnl_usd >= 0 ? "+" : ""}$${Math.abs(data.total_pnl_usd).toFixed(2)}`
        : undefined,
      color: pnlColor(data?.total_pnl_pct ?? null),
    },
    {
      label: "Win Rate",
      value: data?.win_rate_pct != null ? `${data.win_rate_pct.toFixed(1)}%` : "—",
      sub: data?.has_data ? `${data.win_count}W / ${data.loss_count}L` : undefined,
      color: data?.win_rate_pct != null
        ? data.win_rate_pct >= 50 ? "text-green-400" : "text-amber-400"
        : "text-muted-foreground",
    },
    {
      label: "Best Trade",
      value: fmt(data?.best_trade_pct ?? null, "", "%"),
      color: "text-green-400",
    },
    {
      label: "Worst Trade",
      value: fmt(data?.worst_trade_pct ?? null, "", "%"),
      color: "text-red-400",
    },
    {
      label: "Avg Trade",
      value: fmt(data?.avg_trade_pct ?? null, "", "%"),
      color: pnlColor(data?.avg_trade_pct ?? null),
    },
    {
      label: "Total Trades",
      value: data?.total_trades != null ? String(data.total_trades) : "—",
      sub: data?.cycle_count ? `${data.cycle_count} cycles` : undefined,
      color: "text-white",
    },
  ];

  return (
    <Card className="border-cyan-500/10 overflow-hidden">
      <CardHeader className="bg-cyan-950/20 border-b border-cyan-500/10 py-3 sm:py-4 flex flex-col sm:flex-row sm:items-center justify-between gap-1.5 sm:gap-0">
        <CardTitle className="flex items-center gap-2 fluid-heading">
          <span className="text-cyan-500/80">⚓</span>
          <span>Davy Jones — Kraken Crypto Performance</span>
          <span className="ml-1 text-[9px] font-normal text-cyan-400/60 border border-cyan-400/20 bg-cyan-400/5 px-1.5 py-0.5 rounded-full uppercase tracking-wider">Crypto · Kraken</span>
        </CardTitle>
        <div className="flex items-center gap-3">
          {data?.current_equity != null && data.current_equity > 0 && (
            <span className="text-[10px] text-muted-foreground terminal-text">
              Equity: ${data.current_equity.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </span>
          )}
          <span className="text-[9px] text-cyan-500/50 border border-cyan-500/10 bg-cyan-500/5 px-2 py-0.5 rounded-full">
            kraken_trades · PostgreSQL
          </span>
        </div>
      </CardHeader>
      <CardContent className="p-5">

        {/* Firewall notice */}
        <div className="mb-4 flex items-start gap-2 rounded-xl border border-cyan-500/10 bg-cyan-950/20 px-3 py-2.5 text-[10px] text-cyan-400/60">
          <span className="mt-0.5 shrink-0">🔒</span>
          <span>
            <span className="font-semibold text-cyan-400/80">Data firewall:</span> all metrics below
            are sourced exclusively from <code className="bg-cyan-950/40 px-1 rounded">kraken_trades · PostgreSQL</code>.
            Alpaca trading data is stored separately and never mingles with crypto performance.
          </span>
        </div>

        {/* Stat cards */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
          {stats.map((stat) => (
            <div key={stat.label} className="bg-slate-900/70 rounded-xl p-3 border border-cyan-500/8">
              <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1">{stat.label}</div>
              <div className={cn("text-xl font-mono font-bold", stat.color)}>{stat.value}</div>
              {stat.sub && <div className="text-[9px] text-muted-foreground/60 mt-0.5 font-mono">{stat.sub}</div>}
            </div>
          ))}
        </div>

        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-10 text-center gap-2">
            <RefreshCw className="h-6 w-6 text-cyan-500/30 animate-spin" />
            <p className="text-xs text-muted-foreground/60">Loading trade history…</p>
          </div>
        ) : !data ? (
          <div className="flex flex-col items-center justify-center py-10 text-center">
            <span className="text-4xl mb-3 opacity-20">⚓</span>
            <p className="text-sm text-muted-foreground">Trade data temporarily unavailable</p>
            <p className="text-xs text-muted-foreground/60 mt-1">Will retry automatically — no action needed</p>
          </div>
        ) : !data.has_data ? (
          <div className="flex flex-col items-center justify-center py-10 text-center">
            <span className="text-4xl mb-3 opacity-20">⚓</span>
            <p className="text-sm text-muted-foreground">No closed trades yet — bot is scanning 50 pairs</p>
            <p className="text-xs text-muted-foreground/60 mt-1">First trade will appear here once a position closes</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

            {/* Per-symbol breakdown */}
            <div>
              <div className="text-xs font-medium text-muted-foreground mb-3 uppercase tracking-wide">By Symbol</div>
              <div className="space-y-2">
                {Object.entries(data.by_symbol).map(([sym, s]: [string, KrakenSymbolStats]) => (
                  <div key={sym} className="flex items-center gap-3 rounded-xl border border-white/5 bg-slate-900/50 px-3 py-2.5">
                    <div className="w-20 shrink-0">
                      <div className="text-xs font-mono font-bold text-white">{sym.replace("/USD", "")}</div>
                      <div className="text-[9px] text-muted-foreground">{s.trades} trades</div>
                    </div>
                    {/* Win rate bar */}
                    <div className="flex-1 min-w-0">
                      <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
                        <div
                          className={cn("h-full rounded-full", s.win_rate_pct >= 50 ? "bg-green-400" : "bg-amber-400")}
                          style={{ width: `${s.win_rate_pct}%` }}
                        />
                      </div>
                      <div className="text-[9px] text-muted-foreground mt-0.5">{s.win_rate_pct}% win rate</div>
                    </div>
                    <div className={cn("text-xs font-mono font-bold shrink-0", s.total_pnl_pct >= 0 ? "text-green-400" : "text-red-400")}>
                      {s.total_pnl_pct >= 0 ? "+" : ""}{s.total_pnl_pct.toFixed(2)}%
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Recent trades */}
            <div>
              <div className="text-xs font-medium text-muted-foreground mb-3 uppercase tracking-wide">Recent Trades</div>
              <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1">
                {[...data.recent_trades].reverse().map((t, i) => (
                  <div key={i} className={cn(
                    "flex items-center gap-2 rounded-lg border px-2.5 py-2 text-[10px]",
                    t.pnl_pct >= 0 ? "border-green-500/15 bg-green-500/5" : "border-red-500/15 bg-red-500/5"
                  )}>
                    <span className={cn(
                      "w-10 shrink-0 text-center rounded font-bold py-0.5",
                      t.side === "long" ? "bg-blue-500/15 text-blue-400" : "bg-purple-500/15 text-purple-400"
                    )}>
                      {t.side === "long" ? "LONG" : "SHORT"}
                    </span>
                    <span className="font-mono font-bold text-white/80 flex-1">
                      {t.symbol.replace("/USD", "")}
                    </span>
                    <span className="text-muted-foreground/60 flex-1 truncate">{t.reason}</span>
                    <span className={cn("font-mono font-bold shrink-0", t.pnl_pct >= 0 ? "text-green-400" : "text-red-400")}>
                      {t.pnl_pct >= 0 ? "+" : ""}{t.pnl_pct.toFixed(2)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Kraken P&L Attribution Panel ─────────────────────────────────────────────
// DATA SOURCE: kraken-bot/status.json via useKrakenPerformance()

function KrakenBucketTable({ title, buckets, accent = "cyan" }: {
  title: string;
  buckets: Record<string, { count: number; total_pnl_pct: number; avg_pnl_pct: number; win_rate: number }>;
  accent?: string;
}) {
  const entries = Object.entries(buckets).sort((a, b) => b[1].total_pnl_pct - a[1].total_pnl_pct);
  if (!entries.length) return null;
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-2 font-semibold">{title}</div>
      <div className="space-y-1.5">
        {entries.map(([key, b]) => (
          <div key={key} className="flex items-center justify-between px-3 py-2 rounded-lg bg-slate-900/60 border border-cyan-500/8">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-white min-w-[70px]">{key}</span>
              <div className="flex items-center gap-1.5">
                <div className="w-16 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className={cn("h-full rounded-full", b.win_rate >= 60 ? "bg-green-500" : b.win_rate >= 45 ? "bg-amber-500" : "bg-red-500")}
                    style={{ width: `${b.win_rate}%` }}
                  />
                </div>
                <span className={cn("text-[10px] font-mono", b.win_rate >= 60 ? "text-green-400" : b.win_rate >= 45 ? "text-amber-400" : "text-red-400")}>
                  {Math.round(b.win_rate)}%
                </span>
                <span className="text-[9px] text-muted-foreground">({b.count})</span>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-[10px] text-muted-foreground">Avg</span>
              <span className={cn("text-xs font-mono font-semibold", b.avg_pnl_pct >= 0 ? "text-green-400" : "text-red-400")}>
                {b.avg_pnl_pct >= 0 ? "+" : ""}{b.avg_pnl_pct.toFixed(2)}%
              </span>
              <span className="text-[10px] text-muted-foreground">Total</span>
              <span className={cn("text-xs font-mono font-semibold", b.total_pnl_pct >= 0 ? "text-green-400" : "text-red-400")}>
                {b.total_pnl_pct >= 0 ? "+" : ""}{b.total_pnl_pct.toFixed(2)}%
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function KrakenAttributionPanel() {
  const { data, isLoading } = useKrakenPerformance();

  const attribution = useMemo(() => {
    if (!data?.has_data || !data.recent_trades?.length) return null;
    const trades = data.recent_trades;
    type Bucket = { count: number; wins: number; total_pnl_pct: number };
    const bySymbol: Record<string, Bucket> = {};
    const bySide: Record<string, Bucket> = {};
    const byReason: Record<string, Bucket> = {};

    for (const t of trades) {
      const sym = (t.symbol ?? "UNKNOWN").replace("/USD", "");
      const side = t.side === "long" ? "Long" : "Short";
      const reason = t.reason === "mean_reversion_complete" ? "Take Profit"
        : t.reason === "stop" ? "Stop Loss"
        : t.reason === "trailing_stop" ? "Trailing Stop"
        : t.reason ?? "Other";
      const isWin = (t.pnl_pct ?? 0) > 0;

      for (const [key, grp] of [[sym, bySymbol], [side, bySide], [reason, byReason]] as [string, Record<string, Bucket>][]) {
        if (!grp[key]) grp[key] = { count: 0, wins: 0, total_pnl_pct: 0 };
        grp[key].count++;
        if (isWin) grp[key].wins++;
        grp[key].total_pnl_pct += t.pnl_pct ?? 0;
      }
    }

    const toResult = (grp: Record<string, Bucket>) =>
      Object.fromEntries(Object.entries(grp).map(([k, v]) => [k, {
        count: v.count,
        total_pnl_pct: parseFloat(v.total_pnl_pct.toFixed(2)),
        avg_pnl_pct: parseFloat((v.total_pnl_pct / v.count).toFixed(2)),
        win_rate: parseFloat((v.wins / v.count * 100).toFixed(1)),
      }]));

    return { by_symbol: toResult(bySymbol), by_side: toResult(bySide), by_reason: toResult(byReason) };
  }, [data]);

  return (
    <Card className="border-cyan-500/10">
      <CardHeader className="bg-cyan-950/20 border-b border-cyan-500/10 py-4">
        <CardTitle className="flex items-center gap-2 text-sm">
          <BarChart3 className="h-4 w-4 text-cyan-400" /> P&amp;L Attribution
          {data?.total_pnl_pct != null && (
            <span className={cn("text-xs font-mono font-semibold ml-2", data.total_pnl_pct >= 0 ? "text-green-400" : "text-red-400")}>
              {data.total_pnl_pct >= 0 ? "+" : ""}{data.total_pnl_pct.toFixed(2)}%
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-5 space-y-5">
        {isLoading ? (
          <div className="text-xs text-muted-foreground italic">Loading...</div>
        ) : !data?.has_data ? (
          <div className="text-xs text-muted-foreground italic">No closed trades for attribution analysis</div>
        ) : (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                { label: "Closed Trades", value: String(data.total_trades ?? 0), color: "text-white" },
                { label: "Win Rate", value: data.win_rate_pct != null ? `${data.win_rate_pct.toFixed(1)}%` : "—", color: data.win_rate_pct != null && data.win_rate_pct >= 50 ? "text-green-400" : "text-amber-400" },
                { label: "W / L", value: `${data.win_count ?? 0} / ${data.loss_count ?? 0}`, color: "text-white" },
                { label: "Avg P&L", value: data.avg_trade_pct != null ? `${data.avg_trade_pct >= 0 ? "+" : ""}${data.avg_trade_pct.toFixed(2)}%` : "—", color: data.avg_trade_pct != null && data.avg_trade_pct >= 0 ? "text-green-400" : "text-red-400" },
              ].map((s) => (
                <div key={s.label} className="bg-slate-900/70 rounded-xl p-3 border border-cyan-500/8">
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1">{s.label}</div>
                  <div className={cn("text-lg font-mono font-bold", s.color)}>{s.value}</div>
                </div>
              ))}
            </div>
            {attribution && <KrakenBucketTable title="By Symbol" buckets={attribution.by_symbol} />}
            {attribution && <KrakenBucketTable title="By Side" buckets={attribution.by_side} />}
            {attribution && <KrakenBucketTable title="By Exit Reason" buckets={attribution.by_reason} />}
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ── Allocation Section ────────────────────────────────────────────────────────

function AllocationSection() {
  const { data } = useLatestAllocation();

  if (!data?.allocation?.length) return (
    <div className="rounded-xl border border-dashed border-white/5 bg-transparent px-4 py-3 flex items-center gap-3">
      <LayoutList className="h-4 w-4 text-muted-foreground/20 shrink-0" />
      <p className="text-muted-foreground/40 italic text-xs">No allocation plan yet — awaiting next AI cycle.</p>
    </div>
  );

  const slotCount = data.allocation.length;
  const avgConviction = data.allocation.reduce((s, sl) => s + sl.conviction_score, 0) / slotCount;

  return (
    <Card className="border-white/5 overflow-hidden">
      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-3 sm:py-4 flex flex-col sm:flex-row sm:items-center justify-between gap-1.5 sm:gap-0">
        <CardTitle className="flex items-center gap-2 fluid-heading">
          <LayoutList className="h-4 w-4 text-primary" /> <span className="hidden md:inline">Target Allocation</span><span className="md:hidden">Allocation</span> ({slotCount} Slots)
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

      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-3 sm:py-4 flex flex-col sm:flex-row sm:items-center justify-between gap-1.5 sm:gap-0">
        <CardTitle className="flex items-center gap-2 fluid-heading">
          <History className="h-4 w-4 text-primary" /> Trade Journal
          {winRate && (
            <span className={cn("text-[9px] font-mono px-1.5 py-0.5 rounded-full border", Number(winRate) >= 50 ? "text-green-400 border-green-500/30 bg-green-500/10" : "text-red-400 border-red-500/30 bg-red-500/10")}>
              {winRate}% win
            </span>
          )}
        </CardTitle>
        <div className="flex gap-2 sm:gap-3 terminal-text text-[10px]">
          <span className="text-muted-foreground">Total: {data.summary.total}</span>
          <span className="text-green-400">W: {data.summary.wins ?? 0}</span>
          <span className="text-red-400">L: {data.summary.losses ?? 0}</span>
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

// ── LLM Learning Journal ──────────────────────────────────────────────────────

function LLMJournalSection() {
  const [regimeFilter, setRegimeFilter] = useState<string | undefined>(undefined);
  const [catFilter, setCatFilter] = useState<string | undefined>(undefined);
  const { data, isLoading } = useLearningJournal(regimeFilter, catFilter, 50);

  const REGIMES = ["Bull", "Bear", "Sideways", "Crypto"];
  const CATEGORIES = ["macro", "momentum", "risk", "position", "crypto"];

  const regimeColor = (r: string) => {
    if (r === "Bull")     return "text-green-400 border-green-500/30 bg-green-500/10";
    if (r === "Bear")     return "text-red-400 border-red-500/30 bg-red-500/10";
    if (r === "Sideways") return "text-yellow-400 border-yellow-500/30 bg-yellow-500/10";
    if (r === "Crypto")   return "text-purple-400 border-purple-500/30 bg-purple-500/10";
    return "text-muted-foreground border-white/10 bg-white/5";
  };

  const catColor = (c: string) => {
    if (c === "macro")     return "text-blue-400 border-blue-500/30";
    if (c === "momentum")  return "text-cyan-400 border-cyan-500/30";
    if (c === "risk")      return "text-orange-400 border-orange-500/30";
    if (c === "position")  return "text-indigo-400 border-indigo-500/30";
    if (c === "crypto")    return "text-purple-400 border-purple-500/30";
    return "text-muted-foreground border-white/10";
  };

  const confidenceBar = (score: number) => {
    const pct = Math.round(score * 100);
    const barColor = score >= 0.7 ? "bg-green-500" : score >= 0.5 ? "bg-yellow-500" : "bg-blue-500";
    return (
      <div className="flex items-center gap-1.5">
        <div className="w-16 h-1 bg-white/10 rounded-full overflow-hidden">
          <div className={cn("h-full rounded-full", barColor)} style={{ width: `${pct}%` }} />
        </div>
        <span className="text-[9px] font-mono text-muted-foreground">{pct}%</span>
      </div>
    );
  };

  return (
    <Card className="border-white/5">
      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-3 sm:py-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 fluid-heading">
            <Brain className="h-4 w-4 text-purple-400" />
            LLM Learning Journal
            {data && (
              <span className="text-[9px] font-mono px-1.5 py-0.5 rounded-full border text-purple-400 border-purple-500/30 bg-purple-500/10">
                {data.count} insight{data.count !== 1 ? "s" : ""}
              </span>
            )}
          </CardTitle>
          <p className="text-[10px] text-muted-foreground/60 font-mono hidden sm:block">
            Patterns confirmed across multiple independent analysis cycles
          </p>
        </div>

        <div className="flex flex-wrap gap-1.5 mt-2">
          <button
            onClick={() => setRegimeFilter(undefined)}
            className={cn(
              "text-[9px] font-mono px-2 py-0.5 rounded-full border transition-all",
              !regimeFilter ? "text-white border-white/30 bg-white/10" : "text-muted-foreground border-white/10 hover:border-white/20"
            )}
          >
            All Regimes
          </button>
          {REGIMES.map(r => (
            <button
              key={r}
              onClick={() => setRegimeFilter(regimeFilter === r ? undefined : r)}
              className={cn(
                "text-[9px] font-mono px-2 py-0.5 rounded-full border transition-all",
                regimeFilter === r ? regimeColor(r) : "text-muted-foreground border-white/10 hover:border-white/20"
              )}
            >
              {r}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap gap-1.5 mt-1.5">
          <button
            onClick={() => setCatFilter(undefined)}
            className={cn(
              "text-[9px] font-mono px-2 py-0.5 rounded-full border transition-all",
              !catFilter ? "text-white border-white/30 bg-white/10" : "text-muted-foreground border-white/10 hover:border-white/20"
            )}
          >
            All Topics
          </button>
          {CATEGORIES.map(c => (
            <button
              key={c}
              onClick={() => setCatFilter(catFilter === c ? undefined : c)}
              className={cn(
                "text-[9px] font-mono px-2 py-0.5 rounded-full border transition-all capitalize",
                catFilter === c ? catColor(c) : "text-muted-foreground border-white/10 hover:border-white/20"
              )}
            >
              {c}
            </button>
          ))}
        </div>
      </CardHeader>

      <div className="p-4 space-y-2 max-h-[520px] overflow-y-auto">
        {isLoading && (
          <div className="text-center py-8 text-muted-foreground text-xs animate-pulse">
            Loading journal entries...
          </div>
        )}

        {!isLoading && (!data || data.count === 0) && (
          <div className="flex flex-col items-center gap-3 py-10 text-center">
            <Brain className="h-8 w-8 text-purple-400/25" />
            <div>
              <p className="text-sm text-muted-foreground">No learnings recorded yet.</p>
              <p className="text-[11px] text-muted-foreground/50 mt-1 max-w-xs mx-auto">
                The journal populates automatically after the first LLM analysis cycle completes. Check back after the next trading cycle.
              </p>
            </div>
          </div>
        )}

        <AnimatePresence>
          {data?.entries.map((entry: LearningEntry, idx: number) => (
            <motion.div
              key={entry.id}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ delay: Math.min(idx * 0.025, 0.5) }}
              className="rounded-lg border border-white/5 bg-slate-900/50 p-3 hover:border-white/10 hover:bg-slate-800/50 transition-all duration-200"
            >
              <div className="flex items-start justify-between gap-2">
                <p className="text-xs text-white/85 leading-relaxed flex-1">{entry.insight_text}</p>
                <div className="flex flex-col items-end gap-1 shrink-0 ml-2">
                  <span className={cn("text-[8px] font-mono px-1.5 py-0.5 rounded-full border whitespace-nowrap", regimeColor(entry.regime))}>
                    {entry.regime}
                  </span>
                  <span className={cn("text-[8px] font-mono px-1.5 py-0.5 rounded-full border capitalize whitespace-nowrap", catColor(entry.category))}>
                    {entry.category}
                  </span>
                </div>
              </div>
              <div className="flex items-center justify-between mt-2 gap-2 flex-wrap">
                {confidenceBar(entry.confidence_score)}
                <div className="flex items-center gap-3 text-[9px] font-mono text-muted-foreground/60 flex-wrap">
                  <span className="flex items-center gap-0.5">
                    <CheckCircle2 className="h-2.5 w-2.5 text-green-500/70" />
                    {entry.confirmed_count}× confirmed
                  </span>
                  {entry.first_seen && (
                    <span>First: {entry.first_seen.slice(0, 10)}</span>
                  )}
                  {entry.last_seen && entry.last_seen !== entry.first_seen && (
                    <span>Last: {entry.last_seen.slice(0, 10)}</span>
                  )}
                </div>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
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

function CRTOverlay() {
  const isMobile = useIsMobile();
  if (isMobile) return null;

  return (
    <div className="fixed inset-0 pointer-events-none z-[9998] overflow-hidden">
      <div
        className="crt-scanline absolute left-0 right-0 h-[3px]"
        style={{
          background: "linear-gradient(to bottom, transparent, rgba(99,102,241,0.055), transparent)",
          boxShadow: "0 0 10px rgba(99,102,241,0.07)",
        }}
      />
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

function EquityEcho() {
  const isMobile = useIsMobile();
  const { data } = usePortfolio();
  if (isMobile || !data) return null;

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

// ── System Overrides Panel ────────────────────────────────────────────────────

function SystemOverridesPanel() {
  return (
    <div className="space-y-4">
      {/* Warning header */}
      <div className="flex items-start gap-2.5 p-3 rounded-lg bg-red-950/30 border border-red-900/40">
        <ShieldAlert className="h-4 w-4 text-red-500 mt-0.5 flex-shrink-0" />
        <div>
          <p className="text-xs font-semibold text-red-400 leading-tight">Danger Zone</p>
          <p className="text-xs text-red-500/70 mt-0.5 leading-relaxed">
            These controls trigger immediate irreversible broker actions. Use only in emergencies.
          </p>
        </div>
      </div>
      {/* Buttons */}
      <EmergencyControls />
      {/* Legend */}
      <div className="space-y-1">
        <p className="text-xs text-zinc-600">
          <span className="text-red-500 font-medium">Liquidate All</span>
          {" "}— Market-close all positions (JEPQ protected) + halt trading.
        </p>
        <p className="text-xs text-zinc-600">
          <span className="text-amber-500 font-medium">Restart System</span>
          {" "}— Clear DEGRADED error state + refresh data cache.
        </p>
      </div>
    </div>
  );
}


// ── Dashboard Root ────────────────────────────────────────────────────────────

// ── Position change toast notifier ────────────────────────────────────────────
// Fires toasts when Alpaca or Kraken positions open/close between polls.
// Runs as a side-effect-only component (renders null) to keep Dashboard pure.
function PositionChangeNotifier() {
  const { data: liveData } = useLivePositions();
  const { data: krakenData } = useKrakenStatus();
  const { toast } = useToast();

  const prevAlpacaRef = useRef<Set<string>>(new Set());
  const prevKrakenRef = useRef<Set<string>>(new Set());
  const initialized = useRef(false);

  useEffect(() => {
    // Build current Alpaca position set
    const curAlpaca = new Set<string>(
      (liveData?.positions ?? []).map((p: LivePosition) => p.symbol)
    );
    // Build current Kraken position set
    const curKraken = new Set<string>(
      (krakenData?.open_positions ?? []).map((p) => p.symbol)
    );

    if (!initialized.current) {
      // First load — seed refs without toasting
      prevAlpacaRef.current = curAlpaca;
      prevKrakenRef.current = curKraken;
      initialized.current = true;
      return;
    }

    // Alpaca opened
    for (const sym of curAlpaca) {
      if (!prevAlpacaRef.current.has(sym)) {
        toast({ title: `📈 Position opened: ${sym}`, description: "Alpaca equities", duration: 5000 });
      }
    }
    // Alpaca closed
    for (const sym of prevAlpacaRef.current) {
      if (!curAlpaca.has(sym)) {
        toast({ title: `📉 Position closed: ${sym}`, description: "Alpaca equities", duration: 5000 });
      }
    }
    // Kraken opened
    for (const sym of curKraken) {
      if (!prevKrakenRef.current.has(sym)) {
        toast({ title: `📈 Position opened: ${sym}`, description: "Davy Jones crypto", duration: 5000 });
      }
    }
    // Kraken closed
    for (const sym of prevKrakenRef.current) {
      if (!curKraken.has(sym)) {
        toast({ title: `📉 Position closed: ${sym}`, description: "Davy Jones crypto", duration: 5000 });
      }
    }

    prevAlpacaRef.current = curAlpaca;
    prevKrakenRef.current = curKraken;
  }, [liveData, krakenData, toast]);

  return null;
}

// ── System Degradation Log ────────────────────────────────────────────────────

// ── Plain-English alert metadata ──────────────────────────────────────────────
interface AlertMeta {
  what: string;
  resolution: "self" | "code";
  resolutionNote: string;
  tradingImpact: "none" | "kraken_none" | "alpaca_may" | "paused" | "check";
  tradingNote: string;
}

const ALERT_META: Record<string, AlertMeta> = {
  "kraken_api/stale": {
    what: "The Kraken bot stopped writing its status log — it's still running and trading independently, but the dashboard can't read what it's doing right now.",
    resolution: "self",
    resolutionNote: "Usually clears on its own when the bot finishes its current cycle.",
    tradingImpact: "kraken_none",
    tradingNote: "Kraken trading is not affected — the bot makes its own decisions without the dashboard.",
  },
  "groq/budget_exhausted": {
    what: "The AI commentary brain has used up all its daily words. All commentary panels will show a fallback message until tomorrow.",
    resolution: "self",
    resolutionNote: "Resets automatically at midnight UTC — nothing to do.",
    tradingImpact: "none",
    tradingNote: "Trading is not affected — AI commentary is display-only and never drives trade decisions.",
  },
  "groq/rate_limited": {
    what: "The AI brain hit its daily word limit. Commentary panels will be quiet until the limit resets.",
    resolution: "self",
    resolutionNote: "Resets automatically at midnight UTC.",
    tradingImpact: "none",
    tradingNote: "Trading is not affected — AI commentary is display-only.",
  },
  "groq/api_error": {
    what: "The AI commentary service returned an unexpected error.",
    resolution: "self",
    resolutionNote: "Usually clears on the next auto-refresh cycle.",
    tradingImpact: "none",
    tradingNote: "Trading is not affected.",
  },
  "data_pipeline/stale": {
    what: "Market data feeds are running behind — the platform may be working with slightly old prices and indicators.",
    resolution: "self",
    resolutionNote: "Usually fixes itself within a few minutes as external data sources respond.",
    tradingImpact: "alpaca_may",
    tradingNote: "May affect the next Alpaca trade decision if it fires before the data refreshes.",
  },
  "platform_core/analysis_failed": {
    what: "The last scheduled market analysis cycle failed — the AI could not complete its market review.",
    resolution: "self",
    resolutionNote: "Clears when the next scheduled cycle completes successfully (runs every 15 min during market hours).",
    tradingImpact: "alpaca_may",
    tradingNote: "The next Alpaca trade decision may use older analysis. Kraken bot is unaffected.",
  },
  "platform_core/missing_jobs": {
    what: "One or more scheduled trading jobs went missing — the system may not fire its next trading cycle.",
    resolution: "code",
    resolutionNote: "Needs a server restart or code fix — scheduler jobs did not register correctly.",
    tradingImpact: "paused",
    tradingNote: "Alpaca auto-trading may be paused — no new cycles will fire until the scheduler recovers.",
  },
  "platform_core/execution_failed": {
    what: "A trade execution attempt failed — the system tried to place or close a position and hit an error.",
    resolution: "code",
    resolutionNote: "Check Alpaca connection and account status. May need manual review.",
    tradingImpact: "alpaca_may",
    tradingNote: "The last Alpaca execution attempt failed. Kraken bot is unaffected.",
  },
  "http/500": {
    what: "An internal server error occurred on an API request.",
    resolution: "code",
    resolutionNote: "If this keeps appearing for the same endpoint, a code fix is likely needed.",
    tradingImpact: "check",
    tradingNote: "Trading is not affected unless this occurred on a trade-execution endpoint — check the error detail if trades are involved.",
  },
  "http/503": {
    what: "A service was temporarily unavailable — usually the AI commentary service was rate-limited.",
    resolution: "self",
    resolutionNote: "Self-clearing — usually caused by the AI word limit being hit.",
    tradingImpact: "none",
    tradingNote: "Trading is not affected — this is a display-only issue.",
  },
};

const TRADING_IMPACT_CONFIG = {
  none:        { label: "Trading not affected",              color: "text-emerald-400 border-emerald-400/30 bg-emerald-400/10" },
  kraken_none: { label: "Kraken trading not affected",       color: "text-sky-400 border-sky-400/30 bg-sky-400/10" },
  alpaca_may:  { label: "May affect next trade",             color: "text-amber-400 border-amber-400/30 bg-amber-400/10" },
  paused:      { label: "Trading may be paused",             color: "text-red-400 border-red-400/30 bg-red-400/10" },
  check:       { label: "Check required",                    color: "text-slate-400 border-slate-400/30 bg-slate-400/10" },
};

const IMPACT_UNKNOWN = { label: "Impact unknown",           color: "text-slate-500 border-slate-500/30 bg-slate-500/10" };

function AlertMetaCard({ ev }: { ev: DegradationEvent }) {
  const metaKey = `${ev.component}/${ev.error_type}`;
  const meta = ALERT_META[metaKey];
  const sev = SEV_CONFIG[ev.severity] ?? SEV_CONFIG.warning;
  const impact = meta ? TRADING_IMPACT_CONFIG[meta.tradingImpact] : IMPACT_UNKNOWN;
  const ts = new Date(ev.ts).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  const compLabel = COMP_LABELS[ev.component] ?? ev.component;

  return (
    <div className={`rounded border px-3 py-2.5 ${sev.color} space-y-1.5`}>
      <div className="flex items-start gap-2">
        <span className="mt-0.5 flex-shrink-0">{sev.icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] font-bold tracking-widest opacity-80">{sev.label}</span>
            <span className="text-[10px] font-semibold opacity-80">{compLabel}</span>
            <span className="text-[10px] opacity-50">/{ev.error_type}</span>
            <span className="ml-auto text-[10px] opacity-50 flex-shrink-0">{ts}</span>
            {ev.resolved_at && (
              <span className="text-[10px] text-emerald-400 opacity-80 flex items-center gap-0.5">
                <CheckCircle2 className="h-2.5 w-2.5" /> resolved
              </span>
            )}
          </div>
          {meta ? (
            <p className="text-[11px] mt-1 leading-snug opacity-90">{meta.what}</p>
          ) : (
            <p className="text-[11px] mt-1 leading-snug opacity-90 font-mono">{ev.message}</p>
          )}
          <div className="flex flex-wrap gap-1.5 mt-1.5">
            {meta ? (
              <span className={`text-[9px] px-1.5 py-0.5 rounded border font-semibold ${meta.resolution === "self" ? "text-emerald-400 border-emerald-400/30 bg-emerald-400/10" : "text-amber-400 border-amber-400/30 bg-amber-400/10"}`}>
                {meta.resolution === "self" ? "Clears on its own" : meta.resolution === "code" ? "Needs a code fix" : "Needs attention"}
              </span>
            ) : (
              <span className="text-[9px] px-1.5 py-0.5 rounded border font-semibold text-slate-400 border-slate-400/30 bg-slate-400/10">
                Check required
              </span>
            )}
            <span className={`text-[9px] px-1.5 py-0.5 rounded border font-semibold ${impact.color}`}>
              {impact.label}
            </span>
          </div>
          {meta && (
            <p className="text-[10px] mt-1 opacity-55 italic">{meta.resolutionNote} · {meta.tradingNote}</p>
          )}
        </div>
      </div>
    </div>
  );
}

function SystemHealthCard() {
  const { data: health, isLoading: healthLoading } = useDegradationHealth();
  const { data: log24h }                           = useDegradationLog(24);

  const sevenDayEvents = health?.events ?? [];
  const count24h       = log24h?.total ?? 0;
  const TARGET_PER_DAY = 10;

  const health24hGood = count24h < TARGET_PER_DAY;
  const statusColor   = count24h === 0
    ? "text-emerald-400"
    : count24h < TARGET_PER_DAY
      ? "text-yellow-300"
      : "text-red-400";

  // Group events by day (last 7) for the sparkline
  const dailyCounts = useMemo(() => {
    const buckets: Record<string, number> = {};
    for (let i = 6; i >= 0; i--) {
      const d = new Date();
      d.setDate(d.getDate() - i);
      buckets[d.toISOString().slice(0, 10)] = 0;
    }
    for (const ev of sevenDayEvents) {
      const day = ev.ts.slice(0, 10);
      if (day in buckets) buckets[day]++;
    }
    return Object.entries(buckets).map(([day, count]) => ({ day, count }));
  }, [sevenDayEvents]);

  const maxDay = Math.max(...dailyCounts.map(d => d.count), 1);

  // Deduplicated 24h alerts for the "current issues" panel
  const recentAlerts = useMemo(() => {
    const seen = new Set<string>();
    const out: DegradationEvent[] = [];
    for (const ev of (log24h?.events ?? [])) {
      const key = `${ev.component}/${ev.error_type}`;
      if (!seen.has(key)) { seen.add(key); out.push(ev); }
      if (out.length >= 5) break;
    }
    return out;
  }, [log24h]);

  return (
    <Card className="bg-card/60 border-border/40 backdrop-blur-sm">
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2 flex-wrap">
          <Activity className={`h-4 w-4 ${statusColor}`} />
          <CardTitle className="text-sm font-semibold tracking-wide uppercase">System Health</CardTitle>
          <span className={`text-[10px] font-bold ${statusColor}`}>
            {count24h === 0
              ? "Clean — no issues in 24h"
              : `${count24h} event${count24h !== 1 ? "s" : ""} in 24h`}
          </span>
          <span className={`ml-auto text-[10px] font-mono ${health24hGood ? "text-muted-foreground" : "text-amber-400"}`}>
            Target: &lt;{TARGET_PER_DAY}/day
          </span>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* ── 7-day sparkline ─────────────────────────────────────────────── */}
        <div>
          <p className="text-[10px] text-muted-foreground mb-1.5 uppercase tracking-wider">Events per day — last 7 days</p>
          <div className="flex items-end gap-1 h-10">
            {dailyCounts.map(({ day, count }) => {
              const today = new Date().toISOString().slice(0, 10);
              const isToday = day === today;
              const barH = Math.max((count / maxDay) * 40, count > 0 ? 4 : 1);
              const barColor = count === 0
                ? "bg-emerald-400/30"
                : count < TARGET_PER_DAY
                  ? "bg-amber-400/60"
                  : "bg-red-400/70";
              return (
                <div key={day} className="flex-1 flex flex-col items-center gap-0.5">
                  <div
                    className={`w-full rounded-sm ${barColor} transition-all`}
                    style={{ height: `${barH}px` }}
                    title={`${day}: ${count} event${count !== 1 ? "s" : ""}`}
                  />
                  <span className={`text-[8px] ${isToday ? "text-primary font-bold" : "text-muted-foreground opacity-50"}`}>
                    {isToday ? "today" : new Date(day + "T12:00:00").toLocaleDateString(undefined, { weekday: "short" })}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* ── Component breakdown row ─────────────────────────────────────── */}
        {(() => {
          const stats = log24h?.stats ?? {};
          const KEY_COMPONENTS = ["kraken_api", "platform_core", "data_pipeline", "http"] as const;
          const allKeys = [...KEY_COMPONENTS, ...Object.keys(stats).filter(k => !KEY_COMPONENTS.includes(k as never))];
          return (
            <div>
              <p className="text-[10px] text-muted-foreground mb-1.5 uppercase tracking-wider">Component status — 24h</p>
              <div className="flex flex-wrap gap-1.5">
                {allKeys.map(comp => {
                  const s = stats[comp];
                  const label = COMP_LABELS[comp] ?? comp;
                  const dominant = s?.critical ? "critical" : s?.error ? "error" : s?.warning ? "warning" : null;
                  const cfg = dominant ? SEV_CONFIG[dominant] : null;
                  const total = (s?.critical ?? 0) + (s?.error ?? 0) + (s?.warning ?? 0);
                  return (
                    <span
                      key={comp}
                      className={`text-[10px] px-2 py-0.5 rounded border font-mono ${
                        cfg ? cfg.color : "text-emerald-400 border-emerald-400/20 bg-emerald-400/5"
                      }`}
                      title={`${label}: ${total} event${total !== 1 ? "s" : ""} in 24h`}
                    >
                      {label}
                      {total > 0 ? `: ${total}` : ": clean"}
                    </span>
                  );
                })}
              </div>
            </div>
          );
        })()}

        {/* ── Current issues ───────────────────────────────────────────────── */}
        {healthLoading ? (
          <div className="text-center text-muted-foreground text-xs py-4">Loading health status…</div>
        ) : recentAlerts.length === 0 ? (
          <div className="flex items-center gap-2 text-emerald-400 text-xs py-2">
            <CheckCircle2 className="h-4 w-4" />
            <span>All systems normal — no issues recorded in the last 24 hours.</span>
          </div>
        ) : (
          <div className="space-y-2">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Active issues (24h, de-duplicated)</p>
            {recentAlerts.map(ev => (
              <AlertMetaCard key={ev.id} ev={ev} />
            ))}
            {(log24h?.events?.length ?? 0) > 5 && (
              <p className="text-[10px] text-muted-foreground text-center opacity-60">
                Showing 5 of {log24h!.total} events — see the Degradation Log below for full history
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

const SEV_CONFIG: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  critical: { label: "CRITICAL", color: "text-red-400 border-red-400/30 bg-red-400/10", icon: <XCircle className="h-3 w-3" /> },
  error:    { label: "ERROR",    color: "text-amber-400 border-amber-400/30 bg-amber-400/10", icon: <AlertTriangle className="h-3 w-3" /> },
  warning:  { label: "WARN",     color: "text-yellow-300 border-yellow-300/30 bg-yellow-300/10", icon: <AlertOctagon className="h-3 w-3" /> },
};

const COMP_LABELS: Record<string, string> = {
  platform_core: "Platform Core",
  data_pipeline: "Data Pipeline",
  kraken_api:    "Kraken Bot",
  groq:          "Groq / LLM",
  alpaca:        "Alpaca",
  http:          "HTTP Endpoint",
  database:      "Database",
  scheduler:     "Scheduler",
};

function DegradationEventCard({ ev }: { ev: DegradationEvent }) {
  const [expanded, setExpanded] = useState(false);
  const sev = SEV_CONFIG[ev.severity] ?? SEV_CONFIG.warning;
  const ts = new Date(ev.ts).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  const compLabel = COMP_LABELS[ev.component] ?? ev.component;

  return (
    <div
      className={`rounded border px-3 py-2 cursor-pointer transition-colors ${sev.color} ${expanded ? "opacity-100" : "opacity-90 hover:opacity-100"}`}
      onClick={() => setExpanded(x => !x)}
    >
      <div className="flex items-start gap-2">
        <span className="mt-0.5 flex-shrink-0">{sev.icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] font-bold tracking-widest opacity-80">{sev.label}</span>
            <span className="text-[10px] font-semibold opacity-70">{compLabel}</span>
            <span className="text-[10px] opacity-50">/{ev.error_type}</span>
            <span className="ml-auto text-[10px] opacity-50 flex-shrink-0">{ts}</span>
            {ev.resolved_at && (
              <span className="text-[10px] text-emerald-400 opacity-80 flex items-center gap-0.5">
                <CheckCircle2 className="h-2.5 w-2.5" /> resolved
              </span>
            )}
          </div>
          <p className="text-[11px] mt-0.5 leading-snug opacity-90 font-mono">{ev.message}</p>
          {expanded && ev.detail && (
            <pre className="text-[10px] mt-1.5 opacity-60 whitespace-pre-wrap break-all leading-relaxed font-mono max-h-32 overflow-y-auto">
              {ev.detail}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}

function SystemDegradationSection() {
  const [hours, setHours] = useState(48);
  const [copied, setCopied] = useState(false);
  const { data, isLoading, refetch } = useDegradationLog(hours);
  const reportMutation = useDegradationReport(hours);

  const handleCopyReport = async () => {
    const report = await reportMutation.mutateAsync();
    await navigator.clipboard.writeText(report);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  const events = data?.events ?? [];
  const stats = data?.stats ?? {};
  const total = data?.total ?? 0;

  // Count by severity across all components
  let critCount = 0, errCount = 0, warnCount = 0;
  Object.values(stats).forEach(s => {
    critCount += s.critical ?? 0;
    errCount  += s.error    ?? 0;
    warnCount += s.warning  ?? 0;
  });

  const overallColor =
    critCount > 0 ? "text-red-400" :
    errCount  > 0 ? "text-amber-400" :
    warnCount > 0 ? "text-yellow-300" :
    "text-emerald-400";

  return (
    <Card className="bg-card/60 border-border/40 backdrop-blur-sm">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <Bug className={`h-4 w-4 ${overallColor}`} />
            <CardTitle className="text-sm font-semibold tracking-wide uppercase">
              System Degradation Log
            </CardTitle>
            <span className={`text-[10px] font-bold ${overallColor}`}>
              {total === 0 ? "Clean" : `${total} events`}
            </span>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            {/* Time window selector */}
            <div className="flex gap-1">
              {[12, 24, 48].map(h => (
                <button
                  key={h}
                  onClick={() => setHours(h)}
                  className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${
                    hours === h
                      ? "bg-primary/20 border-primary/50 text-primary"
                      : "border-border/30 text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {h}h
                </button>
              ))}
            </div>

            <button
              onClick={() => refetch()}
              className="text-[10px] px-2 py-0.5 rounded border border-border/30 text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1"
            >
              <RefreshCw className="h-3 w-3" /> Refresh
            </button>

            <button
              onClick={handleCopyReport}
              disabled={reportMutation.isPending}
              className="text-[10px] px-3 py-1 rounded border border-primary/50 text-primary bg-primary/10 hover:bg-primary/20 transition-colors flex items-center gap-1.5 font-semibold disabled:opacity-50"
            >
              {copied ? (
                <><CheckCircle2 className="h-3 w-3 text-emerald-400" /> Copied!</>
              ) : reportMutation.isPending ? (
                <><RefreshCw className="h-3 w-3 animate-spin" /> Building…</>
              ) : (
                <><Copy className="h-3 w-3" /> Copy Bug Report</>
              )}
            </button>
          </div>
        </div>

        {/* Component summary chips */}
        {Object.keys(stats).length > 0 && (
          <div className="flex flex-wrap gap-2 mt-2">
            {Object.entries(stats).map(([comp, sevMap]) => {
              const parts: string[] = [];
              if (sevMap.critical) parts.push(`${sevMap.critical} crit`);
              if (sevMap.error)    parts.push(`${sevMap.error} err`);
              if (sevMap.warning)  parts.push(`${sevMap.warning} warn`);
              const dominant = sevMap.critical ? "critical" : sevMap.error ? "error" : "warning";
              const cfg = SEV_CONFIG[dominant];
              return (
                <span key={comp} className={`text-[10px] px-2 py-0.5 rounded border font-mono ${cfg.color}`}>
                  {COMP_LABELS[comp] ?? comp}: {parts.join(" · ")}
                </span>
              );
            })}
          </div>
        )}
      </CardHeader>

      <CardContent>
        {isLoading ? (
          <div className="text-center text-muted-foreground text-xs py-6">Loading degradation log…</div>
        ) : events.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 gap-2 text-muted-foreground">
            <CheckCircle2 className="h-6 w-6 text-emerald-400" />
            <p className="text-xs">No degradation events recorded in the last {hours}h</p>
            <p className="text-[10px] opacity-60">Events are captured automatically every 2 minutes by the auto-heal monitor</p>
          </div>
        ) : (
          <div className="space-y-1.5 max-h-[480px] overflow-y-auto pr-1">
            {events.map(ev => (
              <DegradationEventCard key={ev.id} ev={ev} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Mobile bottom tab bar ──────────────────────────────────────────────────────

type Tab = 'overview' | 'kraken' | 'alpaca' | 'more';

function TabBar({ activeTab, onTabChange }: { activeTab: Tab; onTabChange: (tab: Tab) => void }) {
  const tabs: { id: Tab; label: string; icon: React.ReactNode }[] = [
    { id: 'overview', label: 'Overview', icon: <LayoutDashboard className="h-4 w-4 md:h-3.5 md:w-3.5" /> },
    { id: 'kraken',   label: 'Kraken',   icon: <Anchor className="h-4 w-4 md:h-3.5 md:w-3.5" /> },
    { id: 'alpaca',   label: 'Alpaca',   icon: <TrendingUp className="h-4 w-4 md:h-3.5 md:w-3.5" /> },
    { id: 'more',     label: 'More',     icon: <MoreHorizontal className="h-4 w-4 md:h-3.5 md:w-3.5" /> },
  ];
  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 bg-slate-950/95 backdrop-blur-md border-t border-white/8">
      <div className="flex items-stretch justify-around h-16 md:h-11 md:max-w-none md:px-4 max-w-lg mx-auto">
        {tabs.map(({ id, label, icon }) => (
          <button
            key={id}
            onClick={() => onTabChange(id)}
            className={cn(
              "relative flex flex-col md:flex-row items-center justify-center gap-0.5 md:gap-1.5 flex-1 md:flex-none md:px-5 py-2 transition-all duration-200",
              activeTab === id
                ? "text-primary"
                : "text-muted-foreground/60 hover:text-muted-foreground"
            )}
          >
            {icon}
            <span className="text-[9px] md:text-[10px] font-semibold tracking-wide uppercase">{label}</span>
            {activeTab === id && (
              <span className="absolute bottom-0 left-1/2 -translate-x-1/2 h-0.5 w-8 md:w-full rounded-t-full bg-primary" />
            )}
          </button>
        ))}
      </div>
    </nav>
  );
}
const MobileTabBar = TabBar;

export default function Dashboard() {
  const isMobile = useIsMobile();
  const [activeTab, setActiveTab] = useState<Tab>('overview');

  // Returns 'hidden' when the current tab is NOT in the provided list.
  // Now universal — applies on all screen sizes since the tab bar is always visible.
  const mobileHide = (tabs: Tab[]) =>
    !tabs.includes(activeTab) ? 'hidden' : '';

  return (
    <div className="min-h-screen bg-background flex flex-col relative">
      <CRTOverlay />
      <RegimeGlow />
      <EquityEcho />
      <PositionChangeNotifier />
      <Header />
      <SystemStatusBanner />
      <div className="max-w-[1600px] w-full mx-auto px-4 sm:px-6 lg:px-8 pt-2">
        <BlackoutBanner />
      </div>
      <ActivityTicker />

      <main className="flex-1 max-w-[1600px] w-full mx-auto px-3 sm:px-6 lg:px-8 py-4 sm:py-6 space-y-4 sm:space-y-6 pb-20">

        {/* ═══ ALWAYS VISIBLE: trading controls bar ═══ */}
        <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
          <SafeSection label="Trade Controls">
            <div className="relative rounded-2xl border border-primary/20 bg-gradient-to-br from-slate-900/80 to-slate-950/80 px-4 sm:px-7 py-4 sm:py-5 shadow-[0_0_60px_rgba(59,130,246,0.05)] overflow-hidden">
              <div className="absolute top-0 left-0 w-64 h-64 bg-primary/5 rounded-full blur-3xl -translate-x-1/2 -translate-y-1/2 pointer-events-none" />
              <TradeWorkflowBar />
            </div>
          </SafeSection>
        </motion.div>

        {/* ═══ OVERVIEW TAB — Commander's Log + Fleet Hero + portfolio + positions ═══ */}

        <motion.div
          initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}
          className={mobileHide(['overview'])}
        >
          <SafeSection label="Commander's Log">
            <CommandersLog />
          </SafeSection>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.06 }}
          className={mobileHide(['overview'])}
        >
          <SafeSection label="Fleet Performance">
            <FleetPerformanceHero />
          </SafeSection>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.07 }}
          className={mobileHide(['overview'])}
        >
          <SafeSection label="Portfolio Metrics">
            <CombinedPortfolioSummary />
          </SafeSection>
        </motion.div>

        <div className={cn("grid grid-cols-1 lg:grid-cols-3 gap-4", mobileHide(['overview']))}>
          <motion.div className="lg:col-span-2"
            initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08 }}
          >
            <SafeSection label="Live Positions">
              <LivePositionsSection />
            </SafeSection>
          </motion.div>
          <motion.div
            initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08 }}
          >
            <SafeSection label="Kraken Fleet Overview">
              <FleetComparisonMini />
            </SafeSection>
          </motion.div>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.09 }}
          className={mobileHide(['overview'])}
        >
          <SafeSection label="Combined Trade History">
            <CombinedTradeHistorySection />
          </SafeSection>
        </motion.div>

        {/* ═══ AI AGENTS ROW — Oracle + Auditor (Alpaca) · Davy Jones (Kraken) ═══
            Mobile: Oracle + Auditor appear under Alpaca tab; Davy Jones under Kraken tab.
            Desktop: all three in a 3-col grid.                                      */}
        <div className={cn(
          "grid grid-cols-1 lg:grid-cols-3 gap-6 items-stretch",
          mobileHide(['kraken', 'alpaca'])
        )}>
          <motion.div
            initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}
            className={cn("flex flex-col", mobileHide(['alpaca']))}
          >
            <SafeSection label="The Degen Oracle">
              <AIBrainSection />
            </SafeSection>
          </motion.div>
          <motion.div
            initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.11 }}
            className={cn("flex flex-col", mobileHide(['alpaca']))}
          >
            <SafeSection label="Inspector Rekt">
              <AuditorAgentSection />
            </SafeSection>
          </motion.div>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12 }}
          className={mobileHide(['kraken'])}
        >
          <SafeSection label="Kraken Fleet">
            <KrakenFleetSection />
          </SafeSection>
        </motion.div>

        {/* ═══ MORE TAB — COMPACT GRID LAYOUT ═══════════════════════════════════════ */}

        {/* ROW 1: Risk | Sentiment | Correlation (3-col, analytics overview) */}
        <div className={cn("grid grid-cols-1 lg:grid-cols-3 gap-4", mobileHide(['more']))}>
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.10 }}>
            <SafeSection label="Risk Metrics (Both Bots)">
              <RiskMetricsPanel />
            </SafeSection>
          </motion.div>
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12 }}>
            <SafeSection label="Market Sentiment">
              <SentimentGauges />
            </SafeSection>
          </motion.div>
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.14 }}>
            <SafeSection label="Correlation Matrix">
              <CorrelationMatrix />
            </SafeSection>
          </motion.div>
        </div>

        {/* ROW 2: Equity Curve (2/3) | Best Win + Biggest Loss (1/3) */}
        <div className={cn("grid grid-cols-1 lg:grid-cols-3 gap-4", mobileHide(['more']))}>
          <motion.div className="lg:col-span-2" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.16 }}>
            <SafeSection label="Live Portfolio Equity Curve">
              <LiveEquityCurveSection />
            </SafeSection>
          </motion.div>
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.18 }}>
            <SafeSection label="Best & Worst Trades (Both Bots)">
              <BestTradeHero />
            </SafeSection>
          </motion.div>
        </div>

        {/* ROW 3: Backtester (2/3) | Economic Calendar (1/3) */}
        <div className={cn("grid grid-cols-1 lg:grid-cols-3 gap-4", mobileHide(['more']))}>
          <motion.div className="lg:col-span-2" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.20 }}>
            <SafeSection label="Backtester">
              <BacktesterPanel />
            </SafeSection>
          </motion.div>
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.22 }}>
            <SafeSection label="Economic Calendar">
              <EconomicCalendarPanel />
            </SafeSection>
          </motion.div>
        </div>

        {/* ROW 4: Allocation + Journal (2/3) | Vault + Controls (1/3) */}
        <div className={cn("grid grid-cols-1 lg:grid-cols-3 gap-4", mobileHide(['more']))}>
          <motion.div className="lg:col-span-2 space-y-4" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.24 }}>
            <SafeSection label="Allocation Plan">
              <AllocationSection />
            </SafeSection>
            <SafeSection label="Trade Journal">
              <JournalSection />
            </SafeSection>
          </motion.div>
          <motion.div className="space-y-4" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.26 }}>
            <SafeSection label="Vault">
              <VaultPanel />
            </SafeSection>
            <SafeSection label="Controls">
              <ControlPanel />
            </SafeSection>
            <SafeSection label="System Overrides">
              <SystemOverridesPanel />
            </SafeSection>
            <SafeSection label="Learning Context">
              <LearningContextSection />
            </SafeSection>
          </motion.div>
        </div>

        {/* ROW 5: LLM Journal (2/3) | System Health + Degradation (1/3) */}
        <div className={cn("grid grid-cols-1 lg:grid-cols-3 gap-4", mobileHide(['more']))}>
          <motion.div className="lg:col-span-2 space-y-4" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.28 }}>
            <SafeSection label="LLM Learning Journal">
              <LLMJournalSection />
            </SafeSection>
          </motion.div>
          <motion.div className="space-y-4" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.30 }}>
            <SafeSection label="System Health">
              <SystemHealthCard />
            </SafeSection>
            <SafeSection label="Degradation Log">
              <SystemDegradationSection />
            </SafeSection>
          </motion.div>
        </div>

        {/* ═══ ALPACA TAB — stock performance + attribution ═══ */}
        <div className={cn("grid grid-cols-1 lg:grid-cols-3 gap-4", mobileHide(['alpaca']))}>
          <motion.div className="lg:col-span-2" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.18 }}>
            <SafeSection label="Alpaca Stock Performance">
              <PerformanceSection />
            </SafeSection>
          </motion.div>
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
            <SafeSection label="P&L Attribution">
              <AttributionPanel />
            </SafeSection>
          </motion.div>
        </div>

        {/* ═══ KRAKEN TAB — performance + attribution ═══ */}
        <div className={cn("relative", mobileHide(['kraken']))}>
          <div className="flex items-center gap-3 mb-4">
            <div className="h-px flex-1 bg-gradient-to-r from-transparent via-cyan-500/20 to-transparent" />
            <div className="flex items-center gap-2 px-3 py-1 rounded-full border border-cyan-500/20 bg-cyan-950/30 text-[10px] text-cyan-400/70 font-semibold uppercase tracking-widest">
              <span>⚓</span>
              <span className="hidden sm:inline">Kraken Crypto Bot — Separate Exchange · Separate Capital</span>
              <span className="sm:hidden">Kraken Crypto Bot</span>
            </div>
            <div className="h-px flex-1 bg-gradient-to-r from-transparent via-cyan-500/20 to-transparent" />
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <motion.div className="lg:col-span-2" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.19 }}>
              <SafeSection label="Kraken Crypto Performance">
                <KrakenPerformanceSection />
              </SafeSection>
            </motion.div>
            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.21 }}>
              <SafeSection label="P&L Attribution">
                <KrakenAttributionPanel />
              </SafeSection>
            </motion.div>
          </div>
        </div>

      </main>

      {/* Sticky bottom tab bar — mobile only */}
      <MobileTabBar activeTab={activeTab} onTabChange={setActiveTab} />
    </div>
  );
}
