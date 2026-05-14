import { useState, useRef, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { cn, formatCurrency, formatCryptoPrice } from "@/lib/utils";
import type { KrakenPerformance } from "@/hooks/use-trading";

export type KrakenTradeEntry = KrakenPerformance["recent_trades"][number];

export type GamTrade = { pnl_pct?: number; pnl_percentage?: number; status?: string };

export function computeStreak(trades: GamTrade[]): { count: number; direction: "win" | "loss" | "none" } {
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

export function computeXP(wins: number, total: number): number {
  return wins * 100 + total * 10;
}

export const KRAKEN_RANKS = [
  { xp: 10000, label: "SPY/QQQ Trend Veteran", icon: "💀", tw: "text-cyan-300" },
  { xp: 5000,  label: "Captain",            icon: "⚓", tw: "text-cyan-400" },
  { xp: 2500,  label: "Quartermaster",      icon: "🗺️", tw: "text-cyan-500" },
  { xp: 1000,  label: "First Mate",         icon: "🏴‍☠️", tw: "text-teal-400" },
  { xp: 500,   label: "Able Seaman",        icon: "⚔️", tw: "text-slate-300" },
  { xp: 0,     label: "Deckhand",           icon: "🪝", tw: "text-slate-400" },
];

export const ORACLE_RANKS = [
  { xp: 10000, label: "The Degen Oracle", icon: "🔮", tw: "text-violet-300" },
  { xp: 5000,  label: "Galaxy Brain",     icon: "🧠", tw: "text-indigo-400" },
  { xp: 2500,  label: "Diamond Hands",    icon: "💎", tw: "text-blue-400" },
  { xp: 1000,  label: "Ape Mode",         icon: "🦍", tw: "text-violet-400" },
  { xp: 500,   label: "Bag Holder",       icon: "💼", tw: "text-slate-300" },
  { xp: 0,     label: "Paper Hands",      icon: "📄", tw: "text-slate-400" },
];

export const OPTIONS_RANKS = [
  { xp: 5000,  label: "Options Guru",      icon: "📊", tw: "text-red-400" },
  { xp: 2500,  label: "Vol Hunter",        icon: "🔥", tw: "text-orange-400" },
  { xp: 1000,  label: "Straddle Master",   icon: "⚡", tw: "text-amber-400" },
  { xp: 500,   label: "Premium Collector", icon: "💰", tw: "text-slate-300" },
  { xp: 0,     label: "Options Rookie",    icon: "📈", tw: "text-slate-400" },
];

export const FOREX_RANKS = [
  { xp: 10000, label: "The Navigator",   icon: "🧭", tw: "text-teal-300" },
  { xp: 5000,  label: "Pip Commander",   icon: "🗺️", tw: "text-teal-400" },
  { xp: 2500,  label: "Swing Master",    icon: "🌊", tw: "text-cyan-400" },
  { xp: 1000,  label: "Chart Reader",    icon: "📈", tw: "text-teal-500" },
  { xp: 500,   label: "Trend Follower",  icon: "📊", tw: "text-slate-300" },
  { xp: 0,     label: "Forex Novice",    icon: "🔰", tw: "text-slate-400" },
];

export type RankEntry = typeof KRAKEN_RANKS[number];

export function getRank(xp: number, ranks: RankEntry[]): RankEntry {
  for (const rank of ranks) {
    if (xp >= rank.xp) return rank;
  }
  return ranks[ranks.length - 1];
}

export function getNextRank(xp: number, ranks: RankEntry[]): RankEntry | null {
  for (let i = ranks.length - 1; i >= 0; i--) {
    if (ranks[i].xp > xp) return ranks[i];
  }
  return null;
}

export function StreakChip({ count, direction }: { count: number; direction: "win" | "loss" | "none" }) {
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

export function XPRankBar({ xp, ranks, accent }: { xp: number; ranks: RankEntry[]; accent: string }) {
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

export type KillTradeEntry = {
  symbol?: string;
  ticker?: string;
  pnl_pct?: number;
  pnl_percentage?: number;
  pnl_usd?: number | null;
  exit_reason?: string;
  reason?: string;
};

export function KillBoardPanel({
  trades, theme, bigWinUsd, bigWinPctFallback, bigWinLabel, panelLabel,
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
    .filter(t => (t.pnl_usd ?? t.pnl_pct ?? t.pnl_percentage ?? 0) > 0)
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

export const CRYPTO_SYMBOLS = new Set(["BTC", "ETH", "SOL", "ATOM", "AVAX", "LINK", "DOT", "ADA", "XRP", "DOGE", "LTC", "UNI", "AAVE", "MATIC", "BNB", "XLM", "ALGO", "NEAR", "FTM", "ARB"]);

export function isAssetCrypto(symbol: string): boolean {
  const base = symbol.replace(/[/\-]?USD[TC]?$/, "").toUpperCase();
  return CRYPTO_SYMBOLS.has(base);
}

export function isNYSEOpen(): boolean {
  const now = new Date();
  const etStr = now.toLocaleString("en-US", { timeZone: "America/New_York" });
  const et = new Date(etStr);
  const day = et.getDay();
  if (day === 0 || day === 6) return false;
  const totalMin = et.getHours() * 60 + et.getMinutes();
  return totalMin >= 570 && totalMin < 960;
}

export function MarketStatusBadge({ symbol, isCrypto }: { symbol: string; isCrypto: boolean }) {
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

export const HEALTH_COLOR_MAP: Record<string, string> = {
  green: "#22c55e", emerald: "#10b981", amber: "#f59e0b", orange: "#f97316", red: "#ef4444",
};

export const BOT_THEMES: Record<string, { accent: string; accentTw: string; icon: string; glowRgb: string; borderTw: string; bgGradient: string }> = {
  "davy-jones": { accent: "#22d3ee", accentTw: "cyan", icon: "⚓", glowRgb: "6,182,212", borderTw: "border-cyan-500/20", bgGradient: "from-slate-950/90 to-cyan-950/10" },
  "blackbeard": { accent: "#f97316", accentTw: "orange", icon: "🏴‍☠️", glowRgb: "249,115,22", borderTw: "border-orange-500/20", bgGradient: "from-slate-950/90 to-orange-950/10" },
  "calypso":    { accent: "#a855f7", accentTw: "purple", icon: "🌊", glowRgb: "168,85,247", borderTw: "border-purple-500/20", bgGradient: "from-slate-950/90 to-purple-950/10" },
};

export function useMarketCountdown(nextOpenIso: string | null | undefined): string | null {
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

export function useCountUp(target: number, duration = 1200, enabled = true) {
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

export function AnimatedCurrency({ value, className }: { value: number; className?: string }) {
  const animVal = useCountUp(value);
  return <span className={className}>{formatCurrency(animVal)}</span>;
}

export function SlotDigit({ digit }: { digit: string }) {
  return (
    <motion.span
      key={digit}
      initial={{ y: -10, opacity: 0.3 }}
      animate={{ y: 0,  opacity: 1 }}
      transition={{ type: "spring", stiffness: 200, damping: 15 }}
      className="inline-block"
    >
      {digit}
    </motion.span>
  );
}

export function RollingCurrency({ value, className }: { value: number; className?: string }) {
  const displayed = useCountUp(value);
  const str = formatCurrency(displayed);
  return (
    <span className={className}>
      {[...str].map((ch, i) => <SlotDigit key={`${i}-${ch}`} digit={ch} />)}
    </span>
  );
}

export function RollingPnl({ value, pct }: { value: number; pct: number }) {
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

  useEffect(() => {
    if (value !== prevRef.current) {
      animateTo(prevRef.current, value);
      prevRef.current = value;
      setAnimKey(k => k + 1);
      flash();
    }
  }, [value, animateTo, flash]);

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

export function MiniSparkline({ data, color, w = 60, h = 20 }: { data: number[]; color: string; w?: number; h?: number }) {
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

export function tradingModeLabel(mode: string | undefined): string {
  switch (mode) {
    case "full_market":       return "FULL MARKET";
    case "crypto_only":       return "CRYPTO ONLY";
    case "afterhours_crypto": return "CRYPTO AFTER-HOURS";
    default: return "IDLE";
  }
}

export function tradingModeColor(mode: string | undefined): string {
  switch (mode) {
    case "full_market":       return "text-green-400";
    case "crypto_only":       return "text-purple-400";
    case "afterhours_crypto": return "text-indigo-400";
    default: return "text-zinc-500";
  }
}

export const EXPECTED_JOBS = 14;

/**
 * Canonical fleet equity formula.
 *
 * Bot layout:
 *   alpacaEquity      — Oracle (Bot #1, Alpaca paper account)
 *   krakenFleetEquity — Kraken fleet total (from /kraken/fleet-summary):
 *                       Davy Jones (#2) + Blackbeard (#3) + Calypso (#4) +
 *                       Poseidon (#7) + Kraken Current (#8)
 *                       [Bot #5 defensive_guardian and Bot #7 macro_bond retired]
 *   _optionsEquity    — DEPRECATED: pass 0 or omit.
 *   forexEquity       — Navigator (Bot #6, forex paper account)
 *
 * @deprecated Use the `useFleetEquity()` hook instead, which reads from the
 * canonical `/fleet/equity` endpoint (single source of truth for all bot equity).
 * This helper predates that endpoint and may produce stale/incorrect totals.
 */
export function computeFleetEquity(
  alpacaEquity: number,
  krakenFleetEquity: number,
  _optionsEquity: number,
  forexEquity: number,
): number {
  return alpacaEquity + krakenFleetEquity + forexEquity;
}

/** Starting capital across all 7 bots ($100k each). */
export const FLEET_STARTING_CAPITAL = 700_000;
