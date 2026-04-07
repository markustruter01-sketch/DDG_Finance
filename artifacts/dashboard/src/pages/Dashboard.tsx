import { useMemo, useRef, useEffect, useState } from "react";
import { SafeSection } from "@/components/ErrorBoundary";
import {
  useStatusSummary, usePlatformStatus,
  useLivePositions, useKrakenStatus, useKrakenPerformance,
  useKrakenFleetSummary, useOptionsState, useForexState,
  useOptionsPositions, useForexPositions,
  useJournal, useRecentTrades, useForexTrades,
  useVault, useManualSweep, useEquityCurve,
  type LivePosition,
} from "@/hooks/use-trading";
import { CRTOverlay, RegimeGlow, EquityEcho } from "@/components/VisualOverlays";
import { FleetPerformanceHero } from "@/components/FleetPerformanceHero";
import { FleetCommanderPanel } from "@/components/FleetCommanderPanel";
import { RiskMetricsPanel } from "@/components/RiskMetricsPanel";
import { AIImpactTimeline } from "@/components/AIImpactTimeline";
import { SystemDegradationLog } from "@/components/SystemDegradationLog";
import { BlackoutBanner } from "@/components/EconomicCalendarBanner";
import { EmergencyHeaderButtons } from "@/components/EmergencyControls";
import { TradeWorkflowBar } from "@/components/TradeWorkflowBar";
import {
  EXPECTED_JOBS, tradingModeLabel, tradingModeColor,
  BOT_THEMES,
} from "@/lib/dashboard-shared";
import { cn, formatCurrency } from "@/lib/utils";
import { useToast } from "@/hooks/use-toast";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui";
import {
  Activity, ShieldAlert, TrendingUp,
  WifiOff, AlertTriangle, Brain,
  RefreshCw, History,
  Vault, ArrowUpRight, Coins, Target,
  ExternalLink,
  ArrowUp, ArrowDown, ArrowUpDown, Layers,
  ChevronDown, FileText, Mail,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
  ComposedChart, Area,
} from "recharts";

function SystemStatusBanner() {
  const { data, isError, isLoading } = useStatusSummary();

  let sysStatus: "online" | "degraded" | "ai_degraded" | "emergency" | "offline";
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

  if (isLoading && !data) {
    return null;
  }

  if (isError || !data) {
    sysStatus = "offline";
    reason = "Cannot reach trading API — check that the server is running";
  } else {
    const jobCount = data.system_health.scheduler_job_count;
    const lastStatus = data.system_health.last_run_status;
    const errorCount = data.system_health.error_count;
    tradingMode = data.trading_mode;
    const groqFallback = data.groq?.using_fallback ?? false;
    const emergencyRegime = data.emergency_regime;

    if (emergencyRegime?.active) {
      sysStatus = "emergency";
      const spyPct = emergencyRegime.spy_change_pct != null ? ` (SPY ${emergencyRegime.spy_change_pct > 0 ? "+" : ""}${emergencyRegime.spy_change_pct.toFixed(1)}%)` : "";
      reason = `EMERGENCY REGIME: BEAR${spyPct} — defensive posture forced`;
    } else if (data.alpaca_maintenance) {
      sysStatus = "degraded";
      reason = "Alpaca monthly maintenance window (2nd Saturday 09:00–11:00 ET) — Alpaca trades paused, Kraken bots unaffected";
    } else if (jobCount < EXPECTED_JOBS) {
      sysStatus = "degraded";
      reason = `Only ${jobCount}/${EXPECTED_JOBS} scheduler jobs registered`;
    } else if (["error", "analysis_failed", "execution_failed", "kill_switch_tripped"].includes(lastStatus)) {
      sysStatus = "degraded";
      reason = `Last run failed (${errorCount} total error${errorCount !== 1 ? "s" : ""})`;
    } else if (groqFallback) {
      sysStatus = "ai_degraded";
      const cachedRegime = data.groq?.regime ? ` [${data.groq.regime}]` : "";
      const ageMin = data.groq?.cache_age_min != null ? ` · ${Math.round(data.groq.cache_age_min)}min ago` : "";
      reason = `Groq rate-limited — using cached regime${cachedRegime}${ageMin} · Trading continues normally`;
    } else {
      sysStatus = "online";
      const runCount = data.system_health.run_count;
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
      <span className="hidden sm:flex items-center gap-1 text-[10px] font-mono text-violet-400/60 flex-shrink-0">
        <span className="w-1 h-1 rounded-full bg-violet-400/50 flex-shrink-0" />
        <span>Gemini</span>
        <span className="text-violet-400/35">pre-mkt</span>
      </span>
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

  const bannerMap: Record<string, { bg: string; iconEl: React.ReactNode; label: string; textColor: string }> = {
    online:      { bg: "bg-green-500/8 border-green-500/15",   iconEl: <span className="relative flex h-1.5 w-1.5 flex-shrink-0"><span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-500 opacity-75" /><span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-green-500" /></span>, label: "ONLINE",          textColor: "text-green-400" },
    ai_degraded: { bg: "bg-amber-500/8 border-amber-500/15",   iconEl: <Brain className="h-3.5 w-3.5 text-amber-400 flex-shrink-0" />,                                              label: "AI DEGRADED",     textColor: "text-amber-400" },
    emergency:   { bg: "bg-red-500/15 border-red-500/30",      iconEl: <span className="relative flex h-2 w-2 flex-shrink-0"><span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-500 opacity-75" /><span className="relative inline-flex rounded-full h-2 w-2 bg-red-500" /></span>, label: "EMERGENCY REGIME", textColor: "text-red-400" },
    degraded:    { bg: "bg-amber-500/10 border-amber-500/20",  iconEl: <AlertTriangle className="h-3.5 w-3.5 text-amber-400 flex-shrink-0" />,                                       label: "DEGRADED",        textColor: "text-amber-400" },
    offline:     { bg: "bg-red-500/10 border-red-500/20",      iconEl: <WifiOff className="h-3.5 w-3.5 text-red-400 flex-shrink-0" />,                                                label: "OFFLINE",         textColor: "text-red-400" },
  };
  const b = bannerMap[sysStatus];

  return (
    <div className={cn("sticky top-14 z-30 w-full border-b backdrop-blur-md", b.bg)}>
      <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 min-h-[2rem] py-1.5 md:py-0 md:h-8 flex flex-wrap items-center gap-x-2 gap-y-0.5">
        {b.iconEl}
        <span className={cn("text-xs font-medium", b.textColor)}>{b.label}</span>
        <span className={cn("text-xs break-words", b.textColor.replace("400", "500/70"))}>— {reason}</span>
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

function Header() {
  const { data: summary } = useStatusSummary();

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
              {summary?.market_open ? (
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
              {summary?.kill_switch_tripped ? (
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

          <div className="flex md:hidden items-center gap-1.5">
            {summary?.market_open ? (
              <span className="relative flex h-2 w-2" title="Market Open">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-green-400" />
              </span>
            ) : (
              <span className="inline-flex rounded-full h-2 w-2 bg-slate-600" title="Market Closed" />
            )}
            {summary?.kill_switch_tripped ? (
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

function PositionChangeNotifier() {
  const { data: liveData } = useLivePositions();
  const { data: krakenData } = useKrakenStatus();
  const { toast } = useToast();

  const prevAlpacaRef = useRef<Set<string>>(new Set());
  const prevKrakenRef = useRef<Set<string>>(new Set());
  const initialized = useRef(false);

  useEffect(() => {
    const curAlpaca = new Set<string>(
      (liveData?.positions ?? []).map((p: LivePosition) => p.symbol)
    );
    const curKraken = new Set<string>(
      (krakenData?.open_positions ?? []).map((p) => p.symbol)
    );

    if (!initialized.current) {
      prevAlpacaRef.current = curAlpaca;
      prevKrakenRef.current = curKraken;
      initialized.current = true;
      return;
    }

    for (const sym of curAlpaca) {
      if (!prevAlpacaRef.current.has(sym)) {
        toast({ title: `📈 Position opened: ${sym}`, description: "Alpaca equities", duration: 5000 });
      }
    }
    for (const sym of prevAlpacaRef.current) {
      if (!curAlpaca.has(sym)) {
        toast({ title: `📉 Position closed: ${sym}`, description: "Alpaca equities", duration: 5000 });
      }
    }
    for (const sym of curKraken) {
      if (!prevKrakenRef.current.has(sym)) {
        toast({ title: `📈 Position opened: ${sym}`, description: "Davy Jones crypto", duration: 5000 });
      }
    }
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

const FLEET_BOTS = [
  { id: "oracle",       label: "Oracle #1",    icon: "🔮", accent: "#818cf8", type: "alpaca" as const },
  { id: "davy-jones",   label: "Davy Jones #2", icon: "⚓", accent: "#22d3ee", type: "kraken" as const },
  { id: "blackbeard",   label: "Blackbeard #3", icon: "🏴‍☠️", accent: "#f97316", type: "kraken" as const },
  { id: "calypso",      label: "Calypso #4",   icon: "🌊", accent: "#a855f7", type: "kraken" as const },
  { id: "apex-predator", label: "Apex #5",     icon: "🎯", accent: "#ef4444", type: "options" as const },
  { id: "navigator",    label: "Navigator #6", icon: "🧭", accent: "#14b8a6", type: "forex" as const },
];

function FleetStatusBar() {
  const { data: summary } = useStatusSummary();
  const { data: platformStatus } = usePlatformStatus();
  const { data: fleetSummary } = useKrakenFleetSummary();
  const { data: optionsState } = useOptionsState();
  const { data: forexState } = useForexState();
  const { data: davyPerf } = useKrakenPerformance("davy-jones");
  const { data: bbPerf } = useKrakenPerformance("blackbeard");
  const { data: caPerf } = useKrakenPerformance("calypso");

  const regime = summary?.groq?.regime ?? null;
  const tradingMode = summary?.trading_mode;

  const getBotData = (botDef: typeof FLEET_BOTS[number]) => {
    if (botDef.type === "alpaca") {
      return {
        equity: summary?.portfolio_totals?.equity ?? null,
        pnl: null as number | null,
        positions: summary?.position_count ?? 0,
        online: summary != null,
        status: tradingMode === "full_market" ? "running" : tradingMode === "crypto_only" ? "paused" : "idle",
        cycles: summary?.system_health?.run_count ?? 0,
        lastCycle: platformStatus?.last_run?.last_run_utc ?? null,
      };
    }
    if (botDef.type === "kraken") {
      const bot = fleetSummary?.bots?.find(b => b.bot_id === botDef.id);
      const perf = botDef.id === "davy-jones" ? davyPerf : botDef.id === "blackbeard" ? bbPerf : caPerf;
      const lastTrade = perf?.recent_trades?.[0]?.closed_at ?? null;
      return {
        equity: bot?.equity_usd ?? null,
        pnl: bot?.pnl_usd ?? null,
        positions: bot?.trades ?? 0,
        online: bot != null,
        status: perf?.bot_status ?? (bot ? "running" : "offline"),
        cycles: perf?.cycle_count ?? 0,
        lastCycle: lastTrade,
      };
    }
    if (botDef.type === "options") {
      return {
        equity: optionsState?.total_equity ?? optionsState?.paper_equity ?? null,
        pnl: optionsState?.total_pnl ?? null,
        positions: optionsState?.positions_count ?? 0,
        online: optionsState?.status === "running" || optionsState?.status === "idle",
        status: optionsState?.paused ? "paused" : optionsState?.status ?? "offline",
        cycles: optionsState?.cycle_count ?? 0,
        lastCycle: optionsState?.last_scan ?? null,
      };
    }
    return {
      equity: forexState?.total_equity ?? forexState?.paper_equity ?? null,
      pnl: forexState?.total_pnl ?? null,
      positions: forexState?.position_count ?? 0,
      online: forexState?.status === "running" || forexState?.status === "idle",
      status: forexState?.paused ? "paused" : forexState?.status ?? "offline",
      cycles: forexState?.cycle_count ?? 0,
      lastCycle: forexState?.last_scan ?? null,
    };
  };

  const normalizeStatus = (s: string) => {
    if (s === "running" || s === "idle") return "running";
    if (s.startsWith("paused")) return "paused";
    return "offline";
  };

  const statusColor = (s: string) => {
    const ns = normalizeStatus(s);
    if (ns === "running") return "text-green-400";
    if (ns === "paused") return "text-amber-400";
    return "text-slate-500";
  };

  return (
    <div className="rounded-xl border border-white/5 bg-slate-900/40 overflow-hidden">
      {regime && (
        <div className="flex items-center gap-2 px-4 py-1.5 bg-white/[0.02] border-b border-white/5 text-[9px]">
          <span className="text-muted-foreground/50 uppercase tracking-wider font-semibold">Regime</span>
          <span className="font-mono text-white/70">{regime}</span>
          {tradingMode && (
            <>
              <span className="text-muted-foreground/30">|</span>
              <span className={cn("font-mono font-semibold", tradingModeColor(tradingMode))}>
                {tradingModeLabel(tradingMode)}
              </span>
            </>
          )}
        </div>
      )}
      <div className="grid grid-cols-3 sm:grid-cols-6 divide-x divide-white/5">
        {FLEET_BOTS.map((bot) => {
          const d = getBotData(bot);
          const pnlUp = (d.pnl ?? 0) >= 0;
          return (
            <div key={bot.id} className="px-3 py-2.5 hover:bg-white/[0.02] transition-colors">
              <div className="flex items-center gap-1.5 mb-1">
                <span className="text-xs">{bot.icon}</span>
                <span className="text-[9px] font-bold text-white/80 truncate uppercase tracking-wider">{bot.label.split(" ")[0]}</span>
                <span
                  className={cn("ml-auto w-1.5 h-1.5 rounded-full flex-shrink-0", d.online ? "bg-green-500" : "bg-slate-600")}
                />
              </div>
              <div className="text-[10px] font-mono text-white/60 tabular-nums">
                {d.equity != null ? formatCurrency(d.equity) : "—"}
              </div>
              <div className={cn("text-[9px] font-mono font-semibold tabular-nums", pnlUp ? "text-green-400/70" : "text-red-400/70")}>
                {d.pnl != null ? `${pnlUp ? "+" : ""}${formatCurrency(d.pnl)}` : "—"}
              </div>
              <div className="flex items-center gap-1.5 mt-1">
                <span className={cn("text-[8px] font-semibold uppercase tracking-wider", statusColor(d.status))}>
                  {normalizeStatus(d.status) === "running" ? "RUN" : normalizeStatus(d.status) === "paused" ? "PAUSE" : "OFF"}
                </span>
                <span className="text-[8px] text-muted-foreground/40 font-mono">c{d.cycles}</span>
                {d.lastCycle && (
                  <span className="text-[7px] text-muted-foreground/30 font-mono ml-auto" title={d.lastCycle}>
                    {(() => { try { const dt = new Date(d.lastCycle); const now = Date.now(); const mins = Math.floor((now - dt.getTime()) / 60000); return mins < 60 ? `${mins}m` : mins < 1440 ? `${Math.floor(mins / 60)}h` : `${Math.floor(mins / 1440)}d`; } catch { return ""; } })()}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

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

const FLEET_BASELINE = 600_000;
type EquityRange = "24h" | "7d" | "30d" | "all";

function LiveEquityCurveSection() {
  const { data, isLoading } = useEquityCurve(2000);
  const allSnapshots = data?.snapshots ?? [];
  const [range, setRange] = useState<EquityRange>("all");

  const snapshots = useMemo(() => {
    if (range === "all" || !allSnapshots.length) return allSnapshots;
    const now = Date.now();
    const cutoff = range === "24h" ? now - 86_400_000 : range === "7d" ? now - 7 * 86_400_000 : now - 30 * 86_400_000;
    const filtered = allSnapshots.filter((s) => new Date(s.ts).getTime() >= cutoff);
    return filtered.length >= 2 ? filtered : allSnapshots.slice(-2);
  }, [allSnapshots, range]);

  const { peak, drawdownPct } = useMemo(() => {
    if (!snapshots.length) return { peak: 0, drawdownPct: 0 };
    let pk = -Infinity;
    for (const s of snapshots) pk = Math.max(pk, s.total_equity);
    const last = snapshots[snapshots.length - 1]?.total_equity ?? pk;
    const dd = pk > 0 ? ((last - pk) / pk) * 100 : 0;
    return { peak: pk, drawdownPct: dd };
  }, [snapshots]);

  const chartData = useMemo(() => snapshots.map((s) => {
    const total = s.total_equity;
    return {
      ts: new Date(s.ts).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }),
      total,
      alpaca: s.alpaca_equity,
      kraken: s.kraken_equity,
      options: s.options_equity ?? 0,
      forex: s.forex_equity ?? 0,
      ddBand: total < peak ? [total, peak] as [number, number] : [total, total] as [number, number],
      regime: s.regime,
    };
  }), [snapshots, peak]);

  const last = snapshots[snapshots.length - 1];
  const first = snapshots[0];
  const gainPct = first && last && first.total_equity > 0
    ? ((last.total_equity - first.total_equity) / first.total_equity) * 100
    : null;

  const EquityTooltip = ({ active, payload, label }: ChartTooltipProps) => {
    if (!active || !payload?.length) return null;
    const d = (payload[0] as ChartPayloadEntry & { payload?: Record<string, number | string | null> })?.payload;
    return (
      <div className="bg-slate-900 border border-white/10 rounded-lg px-3 py-2 text-xs shadow-xl">
        <p className="text-muted-foreground mb-1">{label}</p>
        <p className="font-mono text-white font-semibold">Total: {formatCurrency(Number(d?.total ?? 0))}</p>
        <p className="font-mono text-emerald-400">Alpaca: {formatCurrency(Number(d?.alpaca ?? 0))}</p>
        <p className="font-mono text-amber-400">Kraken: {formatCurrency(Number(d?.kraken ?? 0))}</p>
        <p className="font-mono text-red-400">Options: {formatCurrency(Number(d?.options ?? 0))}</p>
        <p className="font-mono text-teal-400">Forex: {formatCurrency(Number(d?.forex ?? 0))}</p>
        {d?.regime && (
          <p className="text-slate-500 mt-1">Regime: {d.regime}</p>
        )}
      </div>
    );
  };

  const rangeButtons: { label: string; value: EquityRange }[] = [
    { label: "24h", value: "24h" },
    { label: "7d", value: "7d" },
    { label: "30d", value: "30d" },
    { label: "All", value: "all" },
  ];

  return (
    <Card className="border-white/5 overflow-hidden">
      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-3 flex flex-col sm:flex-row sm:items-center justify-between gap-1.5">
        <CardTitle className="flex items-center gap-2 fluid-heading">
          <TrendingUp className="h-4 w-4 text-primary" />
          <span>Fleet Equity Curve</span>
          <span className="ml-1 text-[9px] font-normal text-cyan-400/60 border border-cyan-400/20 bg-cyan-400/5 px-1.5 py-0.5 rounded-full uppercase tracking-wider">6 Bots · 4 Pools</span>
        </CardTitle>
        <div className="flex items-center gap-3">
          <div className="flex items-center bg-slate-800/60 rounded-md p-0.5 gap-0.5">
            {rangeButtons.map((b) => (
              <button
                key={b.value}
                onClick={() => setRange(b.value)}
                className={cn(
                  "px-2 py-0.5 text-[10px] rounded font-mono transition-colors",
                  range === b.value
                    ? "bg-blue-600 text-white"
                    : "text-slate-400 hover:text-white"
                )}
              >
                {b.label}
              </button>
            ))}
          </div>
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
          <div className="h-52 flex items-center justify-center text-xs text-muted-foreground">Loading equity data…</div>
        ) : snapshots.length < 2 ? (
          <div className="h-52 flex flex-col items-center justify-center gap-1">
            <TrendingUp className="h-6 w-6 text-muted-foreground/30" />
            <p className="text-xs text-muted-foreground">No equity history yet</p>
            <p className="text-[10px] text-muted-foreground/50">Data is recorded after each completed trading cycle</p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={chartData} margin={{ top: 8, right: 4, left: 4, bottom: 4 }}>
              <defs>
                <linearGradient id="drawdownFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#ef4444" stopOpacity={0.15} />
                  <stop offset="100%" stopColor="#ef4444" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis dataKey="ts" tick={{ fontSize: 9, fill: "#64748b" }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
              <YAxis
                tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
                tick={{ fontSize: 9, fill: "#64748b" }}
                tickLine={false}
                axisLine={false}
                width={48}
              />
              <Tooltip content={<EquityTooltip />} />
              <ReferenceLine y={FLEET_BASELINE} stroke="#64748b" strokeDasharray="6 4" strokeOpacity={0.4} label={{ value: "$600k baseline", position: "insideBottomRight", fill: "#64748b", fontSize: 9 }} />
              {peak > 0 && (
                <ReferenceLine y={peak} stroke="#3b82f6" strokeDasharray="4 3" strokeOpacity={0.5} label={{ value: `HWM $${(peak / 1000).toFixed(0)}k`, position: "insideTopRight", fill: "#3b82f6", fontSize: 9 }} />
              )}
              {drawdownPct < -0.01 && (
                <Area type="monotone" dataKey="ddBand" stroke="none" fill="url(#drawdownFill)" fillOpacity={1} isAnimationActive={false} />
              )}
              <Line type="monotone" dataKey="total" name="Total Fleet" stroke="#3b82f6" strokeWidth={2.5} dot={false} activeDot={{ r: 3, fill: "#3b82f6" }} />
              <Line type="monotone" dataKey="alpaca" name="Alpaca" stroke="#22c55e" strokeWidth={1.2} dot={false} strokeDasharray="5 3" />
              <Line type="monotone" dataKey="kraken" name="Kraken" stroke="#f59e0b" strokeWidth={1.2} dot={false} strokeDasharray="5 3" />
              <Line type="monotone" dataKey="options" name="Options" stroke="#ef4444" strokeWidth={1.2} dot={false} strokeDasharray="5 3" />
              <Line type="monotone" dataKey="forex" name="Forex" stroke="#14b8a6" strokeWidth={1.2} dot={false} strokeDasharray="5 3" />
            </ComposedChart>
          </ResponsiveContainer>
        )}
        <div className="flex items-center gap-4 mt-2 justify-end flex-wrap">
          <div className="flex items-center gap-1.5"><div className="w-4 h-0.5 bg-blue-500 rounded" /><span className="text-[9px] text-muted-foreground">Total Fleet</span></div>
          <div className="flex items-center gap-1.5"><div className="w-3 h-0.5 bg-green-500 rounded opacity-60" /><span className="text-[9px] text-muted-foreground">Alpaca</span></div>
          <div className="flex items-center gap-1.5"><div className="w-3 h-0.5 bg-amber-500 rounded opacity-60" /><span className="text-[9px] text-muted-foreground">Kraken</span></div>
          <div className="flex items-center gap-1.5"><div className="w-3 h-0.5 bg-red-500 rounded opacity-60" /><span className="text-[9px] text-muted-foreground">Options</span></div>
          <div className="flex items-center gap-1.5"><div className="w-3 h-0.5 bg-teal-500 rounded opacity-60" /><span className="text-[9px] text-muted-foreground">Forex</span></div>
        </div>
      </CardContent>
    </Card>
  );
}

type PositionSortKey = "bot" | "pnl" | "size" | "symbol";
type SortDir = "asc" | "desc";

interface UnifiedPosition {
  id: string;
  bot: string;
  botLabel: string;
  botColor: string;
  symbol: string;
  side: string;
  qty: number;
  entryPrice: number;
  currentPrice: number;
  sizeUsd: number;
  pnlUsd: number;
  pnlPct: number;
  entryTime: string | null;
}

const BOT_COLORS: Record<string, string> = {
  oracle: "#f59e0b",
  "davy-jones": "#3b82f6",
  blackbeard: "#a855f7",
  calypso: "#ec4899",
  "apex-predator": "#ef4444",
  navigator: "#14b8a6",
};

function formatTimeHeld(entryTime: string | null): string {
  if (!entryTime) return "—";
  const ms = Date.now() - new Date(entryTime).getTime();
  if (ms < 0) return "—";
  const mins = Math.floor(ms / 60000);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ${mins % 60}m`;
  const days = Math.floor(hrs / 24);
  return `${days}d ${hrs % 24}h`;
}

function ConsolidatedPositionsTable() {
  const { data: alpacaData } = useLivePositions();
  const { data: davyStatus } = useKrakenStatus("davy-jones");
  const { data: bbStatus } = useKrakenStatus("blackbeard");
  const { data: caStatus } = useKrakenStatus("calypso");
  const { data: optionsData } = useOptionsPositions();
  const { data: forexData } = useForexPositions();

  const [sortKey, setSortKey] = useState<PositionSortKey>("pnl");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [filterBot, setFilterBot] = useState<string>("all");

  const positions = useMemo<UnifiedPosition[]>(() => {
    const rows: UnifiedPosition[] = [];

    for (const p of alpacaData?.positions ?? []) {
      rows.push({
        id: `oracle-${p.symbol}`,
        bot: "oracle",
        botLabel: "Oracle #1",
        botColor: BOT_COLORS.oracle,
        symbol: p.symbol,
        side: p.side === "long" ? "L" : "S",
        qty: p.qty ?? 0,
        entryPrice: p.avg_entry_price ?? 0,
        currentPrice: p.current_price ?? 0,
        sizeUsd: p.market_value ?? 0,
        pnlUsd: p.unrealized_pl ?? 0,
        pnlPct: (p.unrealized_plpc ?? 0) * 100,
        entryTime: null,
      });
    }

    const krakenSources: [string, string, typeof davyStatus][] = [
      ["davy-jones", "Davy Jones #2", davyStatus],
      ["blackbeard", "Blackbeard #3", bbStatus],
      ["calypso", "Calypso #4", caStatus],
    ];
    for (const [botId, label, status] of krakenSources) {
      for (const p of status?.open_positions ?? []) {
        rows.push({
          id: `${botId}-${p.symbol}`,
          bot: botId,
          botLabel: label,
          botColor: BOT_COLORS[botId],
          symbol: p.symbol,
          side: p.side === "long" ? "L" : "S",
          qty: p.qty ?? 0,
          entryPrice: p.entry_price ?? 0,
          currentPrice: p.current_price ?? 0,
          sizeUsd: p.size_usd ?? 0,
          pnlUsd: p.unrealized_pnl_usd ?? 0,
          pnlPct: (p.unrealized_pnl_pct ?? 0) * 100,
          entryTime: p.entry_time,
        });
      }
    }

    for (const p of optionsData?.positions ?? []) {
      rows.push({
        id: `apex-${p.id}`,
        bot: "apex-predator",
        botLabel: "Apex #5",
        botColor: BOT_COLORS["apex-predator"],
        symbol: `${p.symbol} ${p.strategy}`,
        side: "L",
        qty: p.contracts ?? 0,
        entryPrice: p.premium_per_contract ?? 0,
        currentPrice: (p.current_value ?? 0) / Math.max(p.contracts ?? 1, 1),
        sizeUsd: p.total_cost ?? 0,
        pnlUsd: p.unrealized_pnl ?? 0,
        pnlPct: (p.unrealized_pnl_pct ?? 0) * 100,
        entryTime: p.opened_at ?? p.scanned_at,
      });
    }

    for (const p of forexData?.positions ?? []) {
      rows.push({
        id: `nav-${p.pair}`,
        bot: "navigator",
        botLabel: "Navigator #6",
        botColor: BOT_COLORS.navigator,
        symbol: p.pair,
        side: p.direction === "long" ? "L" : "S",
        qty: p.units ?? 0,
        entryPrice: p.entry_price ?? 0,
        currentPrice: p.current_price ?? 0,
        sizeUsd: p.size_usd ?? 0,
        pnlUsd: p.unrealized_pnl_usd ?? 0,
        pnlPct: ((p.unrealized_pnl_usd ?? 0) / Math.max(p.size_usd ?? 1, 1)) * 100,
        entryTime: p.entry_time,
      });
    }

    return rows;
  }, [alpacaData, davyStatus, bbStatus, caStatus, optionsData, forexData]);

  const filtered = filterBot === "all" ? positions : positions.filter(p => p.bot === filterBot);

  const sorted = useMemo(() => {
    const arr = [...filtered];
    const dir = sortDir === "asc" ? 1 : -1;
    arr.sort((a, b) => {
      switch (sortKey) {
        case "bot": return dir * a.botLabel.localeCompare(b.botLabel);
        case "symbol": return dir * a.symbol.localeCompare(b.symbol);
        case "pnl": return dir * (a.pnlUsd - b.pnlUsd);
        case "size": return dir * (a.sizeUsd - b.sizeUsd);
        default: return 0;
      }
    });
    return arr;
  }, [filtered, sortKey, sortDir]);

  const toggleSort = (key: PositionSortKey) => {
    if (sortKey === key) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDir("desc"); }
  };

  const sortIcon = (key: PositionSortKey) => {
    if (sortKey !== key) return <ArrowUpDown className="h-3 w-3 opacity-30" />;
    return sortDir === "asc"
      ? <ArrowUp className="h-3 w-3 text-amber-400" />
      : <ArrowDown className="h-3 w-3 text-amber-400" />;
  };

  const activeBots = [...new Set(positions.map(p => p.bot))];

  return (
    <div className="bg-[#0d1117] border border-white/8 rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-white/8 flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <Layers className="h-4 w-4 text-amber-400" />
          <h3 className="text-sm font-semibold text-white/90">Live Open Positions</h3>
          <span className="text-[10px] bg-white/10 px-1.5 py-0.5 rounded font-mono">{positions.length}</span>
        </div>
        <div className="flex items-center gap-1 flex-wrap">
          <button
            onClick={() => setFilterBot("all")}
            className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider transition-colors ${filterBot === "all" ? "bg-amber-500/20 text-amber-400" : "bg-white/5 text-white/40 hover:text-white/60"}`}
          >All</button>
          {activeBots.map(botId => {
            const def = FLEET_BOTS.find(b => b.id === botId);
            return (
              <button
                key={botId}
                onClick={() => setFilterBot(botId)}
                className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider transition-colors ${filterBot === botId ? "bg-amber-500/20 text-amber-400" : "bg-white/5 text-white/40 hover:text-white/60"}`}
              >{def?.icon} {def?.label.split(" ")[0] ?? botId}</button>
            );
          })}
        </div>
      </div>

      {sorted.length === 0 ? (
        <div className="py-10 text-center text-white/30 text-xs font-mono">No open positions</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] uppercase text-white/40 tracking-wider">
                <th className="text-left px-3 py-2 cursor-pointer select-none" onClick={() => toggleSort("bot")}>
                  <span className="flex items-center gap-1">Bot {sortIcon("bot")}</span>
                </th>
                <th className="text-left px-3 py-2 cursor-pointer select-none" onClick={() => toggleSort("symbol")}>
                  <span className="flex items-center gap-1">Symbol {sortIcon("symbol")}</span>
                </th>
                <th className="text-center px-3 py-2">Side</th>
                <th className="text-right px-3 py-2">Qty</th>
                <th className="text-right px-3 py-2">Entry</th>
                <th className="text-right px-3 py-2">Current</th>
                <th className="text-right px-3 py-2 cursor-pointer select-none" onClick={() => toggleSort("size")}>
                  <span className="flex items-center gap-1 justify-end">Size {sortIcon("size")}</span>
                </th>
                <th className="text-right px-3 py-2 cursor-pointer select-none" onClick={() => toggleSort("pnl")}>
                  <span className="flex items-center gap-1 justify-end">P&L {sortIcon("pnl")}</span>
                </th>
                <th className="text-right px-3 py-2">Held</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(pos => (
                <tr key={pos.id} className="border-t border-white/5 hover:bg-white/[0.02] transition-colors">
                  <td className="px-3 py-2">
                    <span className="inline-flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full" style={{ background: pos.botColor }} />
                      <span className="text-white/70 font-medium">{pos.botLabel}</span>
                    </span>
                  </td>
                  <td className="px-3 py-2 font-mono text-white/90 font-semibold">{pos.symbol}</td>
                  <td className="px-3 py-2 text-center">
                    <span className={`font-mono font-semibold ${pos.side === "L" ? "text-green-400" : "text-red-400"}`}>{pos.side}</span>
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-white/70">{(pos.qty ?? 0).toLocaleString()}</td>
                  <td className="px-3 py-2 text-right font-mono text-white/60">${pos.entryPrice.toFixed(2)}</td>
                  <td className="px-3 py-2 text-right font-mono text-white/80">${pos.currentPrice.toFixed(2)}</td>
                  <td className="px-3 py-2 text-right font-mono text-white/70">${pos.sizeUsd.toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                  <td className="px-3 py-2 text-right">
                    <div className="flex flex-col items-end">
                      <span className={`font-mono font-semibold ${pos.pnlUsd >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {pos.pnlUsd >= 0 ? "+" : ""}{pos.pnlUsd.toFixed(2)}
                      </span>
                      <span className={`text-[10px] ${pos.pnlPct >= 0 ? "text-green-400/60" : "text-red-400/60"}`}>
                        {pos.pnlPct >= 0 ? "+" : ""}{pos.pnlPct.toFixed(2)}%
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-white/50 text-[10px]">{formatTimeHeld(pos.entryTime)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

type TradeFilter = "all" | "oracle" | "davy-jones" | "blackbeard" | "calypso" | "apex-predator" | "navigator";

function CombinedTradeHistorySection() {
  const { data: alpacaData, isLoading: alpacaLoading } = useRecentTrades(50);
  const { data: davyPerf } = useKrakenPerformance("davy-jones");
  const { data: bbPerf } = useKrakenPerformance("blackbeard");
  const { data: caPerf } = useKrakenPerformance("calypso");
  const { data: forexData, isLoading: forexLoading } = useForexTrades();
  const { data: optionsState } = useOptionsState();
  const [filter, setFilter] = useState<TradeFilter>("all");

  const combined = useMemo(() => {
    const alpacaRows = (alpacaData?.trades ?? []).map((t) => ({
      source: "oracle" as const,
      botId: "oracle" as const,
      symbol: t.symbol,
      side: t.pnl_pct >= 0 ? "long" : "short",
      entry: null as number | null,
      exit: null as number | null,
      pnl_pct: t.pnl_pct,
      pnl_usd: t.pnl_usd,
      closed_at: t.closed_at,
      reason: t.exit_reason ?? "",
      is_win: (t.pnl_usd ?? 0) > 0,
    }));
    const makeKrakenRows = (trades: Array<{ symbol: string; side: string; entry_price: number; exit_price: number; pnl_pct: number; pnl_usd: number; reason: string; closed_at: string }> | undefined, botId: "davy-jones" | "blackbeard" | "calypso") =>
      (trades ?? []).map((t) => ({
        source: "kraken" as const,
        botId,
        symbol: t.symbol.replace("/USD", ""),
        side: t.side,
        entry: t.entry_price as number | null,
        exit: t.exit_price as number | null,
        pnl_pct: t.pnl_pct,
        pnl_usd: t.pnl_usd,
        closed_at: t.closed_at,
        reason: t.reason ?? "",
        is_win: (t.pnl_usd ?? 0) > 0,
      }));
    const davyRows = makeKrakenRows(davyPerf?.recent_trades, "davy-jones");
    const bbRows = makeKrakenRows(bbPerf?.recent_trades, "blackbeard");
    const caRows = makeKrakenRows(caPerf?.recent_trades, "calypso");
    const forexRows = (forexData?.trades ?? [])
      .filter(t => t.status === "closed" && t.exit_time)
      .map((t) => ({
        source: "forex" as const,
        botId: "navigator" as const,
        symbol: t.pair,
        side: t.direction,
        entry: t.entry_price as number | null,
        exit: t.exit_price as number | null,
        pnl_pct: t.pnl_usd != null && t.entry_price > 0 ? (t.pnl_usd / (t.units * t.entry_price)) * 100 : 0,
        pnl_usd: t.pnl_usd,
        closed_at: t.exit_time!,
        reason: "",
        is_win: (t.pnl_usd ?? 0) > 0,
      }));
    return [...alpacaRows, ...davyRows, ...bbRows, ...caRows, ...forexRows]
      .sort((a, b) => new Date(b.closed_at).getTime() - new Date(a.closed_at).getTime())
      .slice(0, 80);
  }, [alpacaData, davyPerf, bbPerf, caPerf, forexData]);

  const filtered = filter === "all" ? combined : combined.filter(t => t.botId === filter);
  const isLoading = alpacaLoading || forexLoading;
  const wins = filtered.filter((t) => t.is_win).length;
  const losses = filtered.length - wins;
  const totalPnlUsd = filtered.reduce((s, t) => s + (t.pnl_usd ?? 0), 0);
  const winRate = filtered.length > 0 ? Math.round((wins / filtered.length) * 100) : null;

  const fmtDate = (s: string) => {
    try {
      const d = new Date(s);
      return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
    } catch {
      return s.slice(0, 10);
    }
  };

  const filterTabs: { id: TradeFilter; label: string; icon: string; color: string }[] = [
    { id: "all",            label: "All",        icon: "",   color: "#3b82f6" },
    { id: "oracle",         label: "Oracle",     icon: "🔮", color: "#818cf8" },
    { id: "davy-jones",     label: "Davy Jones", icon: "⚓", color: "#22d3ee" },
    { id: "blackbeard",     label: "Blackbeard", icon: "🏴‍☠️", color: "#f97316" },
    { id: "calypso",        label: "Calypso",    icon: "🌊", color: "#a855f7" },
    { id: "apex-predator",  label: "Apex",       icon: "🎯", color: "#ef4444" },
    { id: "navigator",      label: "Navigator",  icon: "🧭", color: "#14b8a6" },
  ];

  const sourceConfig: Record<string, { badge: string; badgeStyle: string }> = {
    oracle:           { badge: "ORC", badgeStyle: "text-indigo-400 border-indigo-500/20 bg-indigo-500/5" },
    "davy-jones":     { badge: "DJ",  badgeStyle: "text-cyan-400 border-cyan-500/20 bg-cyan-500/5" },
    blackbeard:       { badge: "BB",  badgeStyle: "text-orange-400 border-orange-500/20 bg-orange-500/5" },
    calypso:          { badge: "CA",  badgeStyle: "text-purple-400 border-purple-500/20 bg-purple-500/5" },
    "apex-predator":  { badge: "APX", badgeStyle: "text-red-400 border-red-500/20 bg-red-500/5" },
    navigator:        { badge: "NAV", badgeStyle: "text-teal-400 border-teal-500/20 bg-teal-500/5" },
  };

  return (
    <Card className="border-white/5 overflow-hidden">
      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-3 sm:py-4">
        <CardTitle className="flex flex-wrap items-center gap-2 fluid-heading">
          <History className="h-4 w-4 text-primary" />
          <span>Closed Trades</span>
          {filtered.length > 0 && (
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
        <div className="flex items-center gap-1 mt-2">
          {filterTabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setFilter(tab.id)}
              className={cn(
                "px-2.5 py-1 text-[10px] font-semibold rounded-md transition-all uppercase tracking-wider",
                filter === tab.id
                  ? "text-white"
                  : "text-muted-foreground/50 hover:text-muted-foreground"
              )}
              style={filter === tab.id ? { backgroundColor: `${tab.color}25`, color: tab.color, border: `1px solid ${tab.color}40` } : undefined}
            >
              {tab.icon && <span className="mr-1">{tab.icon}</span>}
              {tab.label}
            </button>
          ))}
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {isLoading ? (
          <div className="flex items-center justify-center py-8 gap-2 text-xs text-muted-foreground/50">
            <RefreshCw className="h-3.5 w-3.5 animate-spin" />
            Loading trades…
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 gap-2 text-center">
            <History className="h-7 w-7 text-muted-foreground/15" />
            <p className="text-xs text-muted-foreground/50">
              {filter === "apex-predator" ? "No trade history available" : "No closed trades yet"}
            </p>
            <p className="text-[10px] text-muted-foreground/30">
              {filter === "apex-predator" ? "Apex Predator reports aggregate stats only" : "History will appear here as positions close"}
            </p>
          </div>
        ) : (
          <div className="max-h-80 overflow-y-auto overflow-x-auto divide-y divide-white/5">
            <div className="grid grid-cols-[auto_1fr_auto_auto_auto_auto_auto_auto_auto] gap-x-2 px-4 py-2 text-[9px] uppercase tracking-wider text-muted-foreground/50 sticky top-0 bg-slate-950/80 backdrop-blur-sm z-10 min-w-[640px]">
              <span>Bot</span>
              <span>Asset</span>
              <span>Side</span>
              <span className="text-right hidden md:block">Entry</span>
              <span className="text-right hidden md:block">Exit</span>
              <span className="text-right">P&amp;L %</span>
              <span className="text-right hidden sm:block">P&amp;L $</span>
              <span className="hidden lg:block">Reason</span>
              <span className="text-right">Date</span>
            </div>
            {filtered.map((t, i) => {
              const sc = sourceConfig[t.botId] ?? sourceConfig.oracle;
              return (
                <div
                  key={i}
                  className={cn(
                    "grid grid-cols-[auto_1fr_auto_auto_auto_auto_auto_auto_auto] gap-x-2 items-center px-4 py-2 text-[11px] transition-colors hover:bg-white/[0.02] min-w-[640px]",
                    t.is_win ? "border-l-2 border-green-500/20" : "border-l-2 border-red-500/20"
                  )}
                >
                  <span className={cn("text-[8px] font-bold uppercase tracking-widest px-1.5 py-0.5 rounded border shrink-0", sc.badgeStyle)}>
                    {sc.badge}
                  </span>
                  <span className="font-mono font-bold text-white/90 truncate">{t.symbol}</span>
                  <span className={cn(
                    "text-[8px] font-semibold uppercase tracking-wider px-1 py-0.5 rounded shrink-0",
                    t.side === "long"
                      ? "text-green-400/80 bg-green-500/10"
                      : "text-red-400/80 bg-red-500/10"
                  )}>
                    {t.side === "long" ? "L" : "S"}
                  </span>
                  <span className="font-mono text-[10px] text-muted-foreground/50 text-right tabular-nums shrink-0 hidden md:block">
                    {t.entry != null ? formatCurrency(t.entry) : "—"}
                  </span>
                  <span className="font-mono text-[10px] text-muted-foreground/50 text-right tabular-nums shrink-0 hidden md:block">
                    {t.exit != null ? formatCurrency(t.exit) : "—"}
                  </span>
                  <span className={cn("font-mono font-bold text-right tabular-nums shrink-0",
                    t.is_win ? "text-green-400" : "text-red-400"
                  )}>
                    {t.pnl_pct >= 0 ? "+" : ""}{t.pnl_pct.toFixed(2)}%
                  </span>
                  <span className={cn("font-mono text-right tabular-nums text-[10px] shrink-0 hidden sm:block",
                    t.pnl_usd != null
                      ? t.is_win ? "text-green-400/60" : "text-red-400/60"
                      : "text-muted-foreground/30"
                  )}>
                    {t.pnl_usd != null
                      ? `${t.pnl_usd >= 0 ? "+" : ""}${formatCurrency(t.pnl_usd)}`
                      : "—"}
                  </span>
                  <span className="text-[9px] text-muted-foreground/40 truncate max-w-[80px] hidden lg:block" title={t.reason || undefined}>
                    {t.reason || "—"}
                  </span>
                  <span className="text-[9px] text-muted-foreground/50 font-mono text-right shrink-0">
                    {fmtDate(t.closed_at)}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

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

function CollapsibleSection({ title, icon, defaultOpen = false, children }: { title: string; icon?: React.ReactNode; defaultOpen?: boolean; children: React.ReactNode }) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl border border-white/[0.06] bg-gradient-to-br from-slate-900/40 to-slate-950/40 overflow-hidden">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/[0.02] transition-colors"
      >
        <div className="flex items-center gap-2">
          {icon}
          <span className="text-sm font-semibold text-white/80 tracking-wide">{title}</span>
        </div>
        <ChevronDown className={cn("h-4 w-4 text-muted-foreground/50 transition-transform duration-200", isOpen && "rotate-180")} />
      </button>
      <AnimatePresence initial={false}>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            <div className="px-1 pb-1">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function ExportReportButton() {
  const [loading, setLoading] = useState(false);

  const handleExport = async () => {
    setLoading(true);
    try {
      const base = import.meta.env.VITE_API_BASE_URL || "/trading-api";
      const res = await fetch(`${base}/export/report-parts`);
      if (!res.ok) throw new Error("Export failed");
      const data = await res.json();

      for (const key of ["p1", "p2", "p3", "p4"]) {
        const part = data[key];
        if (!part) continue;
        const blob = new Blob([part.text], { type: "text/plain;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = part.filename;
        a.click();
        URL.revokeObjectURL(url);
        await new Promise((r) => setTimeout(r, 300));
      }
    } catch {
      alert("Export failed — check that the trading API is running.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <button
      onClick={handleExport}
      disabled={loading}
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-white/10 bg-white/[0.03] hover:bg-white/[0.06] text-xs font-mono text-muted-foreground hover:text-white transition-all disabled:opacity-50"
    >
      <FileText className="h-3.5 w-3.5" />
      {loading ? "Downloading 4 files..." : "Export Report"}
    </button>
  );
}

function EmailReportButton() {
  const [loading, setLoading] = useState(false);

  const handleEmail = async () => {
    setLoading(true);
    try {
      const base = import.meta.env.VITE_API_BASE_URL || "/trading-api";
      const res = await fetch(`${base}/export/report-parts`);
      if (!res.ok) throw new Error("Export failed");
      const data = await res.json();

      const labels: Record<string, string> = {
        p1: "PART 1 — System Status + Oracle/Alpaca",
        p2: "PART 2 — Kraken Fleet + Correlation Matrix",
        p3: "PART 3 — Apex Predator + Navigator + Execution Quality",
        p4: "PART 4 — Fleet Risk + Combined Summary + Journal + Strategy",
      };

      let body = "";
      for (const key of ["p1", "p2", "p3", "p4"] as const) {
        const part = data[key];
        if (!part) continue;
        body += `\n===== ${labels[key]} (${part.lines} lines) =====\n\n`;
        body += part.text;
        body += "\n\n";
      }

      const date = new Date().toISOString().slice(0, 10);
      const subject = `AlgoEdge Trading Report — ${date}`;

      const maxLen = 1_900_000;
      if (body.length > maxLen) {
        body = body.slice(0, maxLen) + "\n\n[Report truncated for email — use Export for full files]";
      }

      const mailto = `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
      window.location.href = mailto;
    } catch {
      alert("Failed to generate report for email — check that the trading API is running.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <button
      onClick={handleEmail}
      disabled={loading}
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-white/10 bg-white/[0.03] hover:bg-white/[0.06] text-xs font-mono text-muted-foreground hover:text-white transition-all disabled:opacity-50"
    >
      <Mail className="h-3.5 w-3.5" />
      {loading ? "Preparing..." : "Email Report"}
    </button>
  );
}

export default function Dashboard() {
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

      <main className="flex-1 max-w-[1600px] w-full mx-auto px-3 sm:px-6 lg:px-8 py-4 sm:py-6 space-y-4 sm:space-y-6 pb-28">
        <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
          <SafeSection label="Trade Controls">
            <div className="relative rounded-2xl border border-primary/20 bg-gradient-to-br from-slate-900/80 to-slate-950/80 px-4 sm:px-7 py-4 sm:py-5 shadow-[0_0_60px_rgba(59,130,246,0.05)] overflow-hidden">
              <div className="absolute top-0 left-0 w-64 h-64 bg-primary/5 rounded-full blur-3xl -translate-x-1/2 -translate-y-1/2 pointer-events-none" />
              <div className="flex items-center justify-between gap-3">
                <div className="flex-1"><TradeWorkflowBar /></div>
                <ExportReportButton />
                <EmailReportButton />
              </div>
            </div>
          </SafeSection>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.04 }}>
          <SafeSection label="Fleet Status">
            <FleetStatusBar />
          </SafeSection>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.06 }}>
          <SafeSection label="Fleet Performance">
            <FleetPerformanceHero />
          </SafeSection>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.07 }}>
          <SafeSection label="AI Impact Timeline">
            <AIImpactTimeline />
          </SafeSection>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08 }}>
          <SafeSection label="Live Portfolio Equity Curve">
            <LiveEquityCurveSection />
          </SafeSection>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.10 }}>
          <SafeSection label="Live Positions">
            <CollapsibleSection title="Live Open Positions" icon={<Layers className="h-4 w-4 text-blue-400/60" />} defaultOpen={false}>
              <ConsolidatedPositionsTable />
            </CollapsibleSection>
          </SafeSection>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12 }}>
          <SafeSection label="Closed Trades">
            <CollapsibleSection title="Closed Trade History" icon={<History className="h-4 w-4 text-amber-400/60" />} defaultOpen={false}>
              <CombinedTradeHistorySection />
            </CollapsibleSection>
          </SafeSection>
        </motion.div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <motion.div className="lg:col-span-2" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.14 }}>
            <SafeSection label="Fleet Commander">
              <FleetCommanderPanel />
            </SafeSection>
          </motion.div>
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.14 }}>
            <SafeSection label="Vault">
              <VaultPanel />
            </SafeSection>
          </motion.div>
        </div>

        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.16 }}>
          <SafeSection label="Risk Metrics">
            <RiskMetricsPanel />
          </SafeSection>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.18 }}>
          <SafeSection label="System Health Log">
            <SystemDegradationLog />
          </SafeSection>
        </motion.div>
      </main>
    </div>
  );
}
