import { useMemo, useRef, useEffect, useState, type ReactNode } from "react";
import { SafeSection } from "@/components/ErrorBoundary";
import {
  useStatusSummary,
  useLivePositions, useKrakenStatus, useKrakenPerformance,
  useKrakenFleetSummary, useOptionsState, useForexState,
  usePortfolio, useJournal, useEquityCurve,
  type LivePosition,
} from "@/hooks/use-trading";
import { CRTOverlay, RegimeGlow, EquityEcho } from "@/components/VisualOverlays";
import { FleetPerformanceHero } from "@/components/FleetPerformanceHero";
import { AIImpactTimeline } from "@/components/AIImpactTimeline";
import { SystemDegradationLog } from "@/components/SystemDegradationLog";
import { BlackoutBanner } from "@/components/EconomicCalendarBanner";
import { EmergencyHeaderButtons } from "@/components/EmergencyControls";
import { TradeWorkflowBar } from "@/components/TradeWorkflowBar";
import {
  EXPECTED_JOBS, tradingModeLabel, tradingModeColor,
  computeFleetEquity, FLEET_STARTING_CAPITAL,
} from "@/lib/dashboard-shared";
import { cn, formatCurrency } from "@/lib/utils";
import { useToast } from "@/hooks/use-toast";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui";
import {
  Activity, ShieldAlert, TrendingUp,
  WifiOff, AlertTriangle, Brain,
  ExternalLink,
  FileText, Mail,
  DollarSign, Percent, Bot, BarChart2,
  Code, ShieldCheck, Copy, Check, X,
  ChevronDown, TrendingDown, Hash,
} from "lucide-react";
import { motion } from "framer-motion";
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


function FleetKPISummary() {
  const { data: summary } = useStatusSummary();
  const { data: portfolio } = usePortfolio();
  const { data: fleetSummary } = useKrakenFleetSummary();
  const { data: optionsState } = useOptionsState();
  const { data: forexState } = useForexState();
  const { data: davyPerf } = useKrakenPerformance("davy-jones");
  const { data: bbPerf } = useKrakenPerformance("blackbeard");
  const { data: caPerf } = useKrakenPerformance("calypso");
  const { data: journal } = useJournal();

  // Oracle equity comes from the Alpaca portfolio endpoint, not from /status
  // (which does not include portfolio_totals).
  const alpacaEquity = portfolio?.account?.equity ?? 0;
  const krakenFleetEquity = fleetSummary?.total_equity_usd ?? 0;
  const optionsEquity = optionsState?.total_equity ?? optionsState?.paper_equity ?? 100_000;
  const forexEquity = forexState?.total_equity ?? forexState?.paper_equity ?? 100_000;
  // krakenReady = true as soon as fleetSummary data has arrived (not gated on isLoading
  // which can stay truthy across re-renders while a background refetch is in flight).
  const krakenReady = fleetSummary != null;
  // Show "—" only on the very first render before ANY real data has arrived.
  // Once any single source responds, show the live (progressively-updating) total.
  const anyLoading = alpacaEquity === 0 && !krakenReady && optionsState == null && forexState == null;
  const grandTotal = computeFleetEquity(
    alpacaEquity > 0 ? alpacaEquity : 0,
    krakenFleetEquity,
    optionsEquity,
    forexEquity,
  );

  // True P&L = grand total minus the $800k starting capital (8 bots × $100k each).
  // Guard: do not show until all key equity pools have loaded.
  const equitiesReady = alpacaEquity > 0 && krakenReady && optionsState != null && forexState != null;
  const totalPnl: number | null = equitiesReady ? grandTotal - FLEET_STARTING_CAPITAL : null;

  const alpacaWins = journal?.summary?.wins ?? 0;
  const alpacaTotal = journal?.summary?.total ?? 0;
  const allPerfs = [davyPerf, bbPerf, caPerf].filter(Boolean);
  const krakenWins = allPerfs.reduce((s, p) => s + (p?.win_count ?? 0), 0);
  const krakenTotal = allPerfs.reduce((s, p) => s + (p?.total_trades ?? 0), 0);
  const optionsWins = optionsState?.total_wins ?? 0;
  const optionsTotal = optionsState?.total_trades ?? 0;
  const forexWins = forexState?.total_wins ?? 0;
  const forexTotal = forexState?.total_trades ?? 0;
  const totalWins = alpacaWins + krakenWins + optionsWins + forexWins;
  const totalTrades = alpacaTotal + krakenTotal + optionsTotal + forexTotal;
  const combinedWinRate = totalTrades > 0 ? (totalWins / totalTrades) * 100 : null;

  const botStatuses = summary?.bot_statuses ?? {};
  const activeBotCount = Object.values(botStatuses).filter(
    (b) => b.status === "running" || b.status === "idle"
  ).length;
  const totalBotCount = (fleetSummary?.bot_count ?? 3) + 5;

  const regime = summary?.groq?.regime ?? null;
  const tradingMode = summary?.trading_mode;

  const kpis = [
    {
      label: "Fleet Equity",
      value: anyLoading ? "—" : formatCurrency(grandTotal),
      sub: `${totalBotCount} bots · 6 capital pools`,
      icon: <DollarSign className="h-4 w-4 text-blue-400" />,
      accent: "border-blue-500/20 bg-blue-500/5",
      valueColor: anyLoading ? "text-slate-500" : "text-white",
    },
    {
      label: "Total P&L",
      value: totalPnl != null
        ? `${totalPnl >= 0 ? "+" : ""}${formatCurrency(totalPnl)}`
        : "—",
      sub: "all 8 bots · vs $800k capital",
      icon: <BarChart2 className="h-4 w-4 text-emerald-400" />,
      accent: totalPnl == null
        ? "border-slate-500/20 bg-slate-500/5"
        : totalPnl >= 0
          ? "border-emerald-500/20 bg-emerald-500/5"
          : "border-red-500/20 bg-red-500/5",
      valueColor: totalPnl == null
        ? "text-slate-500"
        : totalPnl >= 0
          ? "text-emerald-400"
          : "text-red-400",
    },
    {
      label: "Fleet Win Rate",
      value: combinedWinRate != null ? `${combinedWinRate.toFixed(1)}%` : "—",
      sub: `${totalWins}W / ${totalTrades - totalWins}L across all bots`,
      icon: <Percent className="h-4 w-4 text-amber-400" />,
      accent: combinedWinRate != null && combinedWinRate >= 50 ? "border-amber-500/20 bg-amber-500/5" : "border-red-500/20 bg-red-500/5",
      valueColor: combinedWinRate != null && combinedWinRate >= 50 ? "text-amber-400" : "text-red-400",
    },
    {
      label: "Active Bots",
      value: `${activeBotCount} / ${totalBotCount}`,
      sub: tradingMode ? tradingModeLabel(tradingMode) : "—",
      icon: <Bot className="h-4 w-4 text-violet-400" />,
      accent: "border-violet-500/20 bg-violet-500/5",
      valueColor: "text-violet-400",
    },
  ];

  return (
    <div className="space-y-2">
      {regime && (
        <div className="flex items-center gap-2 text-[9px]">
          <span className="text-muted-foreground/50 uppercase tracking-wider font-semibold">Regime</span>
          <span className="font-mono text-white/60">{regime}</span>
          {tradingMode && (
            <>
              <span className="text-muted-foreground/30">·</span>
              <span className={cn("font-mono font-semibold", tradingModeColor(tradingMode))}>
                {tradingModeLabel(tradingMode)}
              </span>
            </>
          )}
        </div>
      )}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {kpis.map((kpi) => (
          <div
            key={kpi.label}
            className={cn(
              "rounded-xl border px-5 py-4 flex flex-col gap-2",
              kpi.accent
            )}
          >
            <div className="flex items-center gap-2">
              {kpi.icon}
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground/70 font-semibold">
                {kpi.label}
              </span>
            </div>
            <div className={cn("text-2xl font-mono font-bold tabular-nums leading-none", kpi.valueColor)}>
              {kpi.value}
            </div>
            <div className="text-[10px] text-muted-foreground/50">{kpi.sub}</div>
          </div>
        ))}
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

const FLEET_BASELINE = 800_000;
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
          <span className="ml-1 text-[9px] font-normal text-cyan-400/60 border border-cyan-400/20 bg-cyan-400/5 px-1.5 py-0.5 rounded-full uppercase tracking-wider">8 Bots · 6 Pools</span>
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
              <ReferenceLine y={FLEET_BASELINE} stroke="#64748b" strokeDasharray="6 4" strokeOpacity={0.4} label={{ value: "$800k baseline", position: "insideBottomRight", fill: "#64748b", fontSize: 9 }} />
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
  const [modal, setModal] = useState<{ subject: string; body: string } | null>(null);
  const [copied, setCopied] = useState<"subject" | "body" | null>(null);

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

      const maxLen = 100_000;
      if (body.length > maxLen) {
        body = body.slice(0, maxLen) + "\n\n[Report truncated — use Export Report for full files]";
      }

      setModal({ subject, body });
    } catch {
      alert("Failed to generate report for email — check that the trading API is running.");
    } finally {
      setLoading(false);
    }
  };

  const copyText = async (text: string, kind: "subject" | "body") => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(kind);
      setTimeout(() => setCopied(null), 2000);
    } catch {
      // fallback for browsers without clipboard API
      const el = document.createElement("textarea");
      el.value = text;
      el.style.position = "fixed";
      el.style.opacity = "0";
      document.body.appendChild(el);
      el.select();
      document.execCommand("copy");
      document.body.removeChild(el);
      setCopied(kind);
      setTimeout(() => setCopied(null), 2000);
    }
  };

  const closeModal = () => setModal(null);

  return (
    <>
      <button
        onClick={handleEmail}
        disabled={loading}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-white/10 bg-white/[0.03] hover:bg-white/[0.06] text-xs font-mono text-muted-foreground hover:text-white transition-all disabled:opacity-50"
      >
        <Mail className="h-3.5 w-3.5" />
        {loading ? "Preparing..." : "Email Report"}
      </button>

      {modal && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 9999,
            backgroundColor: "rgba(0,0,0,0.75)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "16px",
          }}
          onClick={closeModal}
        >
          <div
            style={{
              backgroundColor: "#0d1117",
              border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: "12px",
              width: "100%",
              maxWidth: "680px",
              maxHeight: "90vh",
              display: "flex",
              flexDirection: "column",
              fontFamily: "monospace",
              color: "#e6edf3",
              boxShadow: "0 0 40px rgba(0,0,0,0.8)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "1rem 1.25rem",
                borderBottom: "1px solid rgba(255,255,255,0.08)",
              }}
            >
              <span style={{ fontSize: "0.875rem", fontWeight: 600, color: "#58a6ff" }}>
                Email Report Ready
              </span>
              <button
                onClick={closeModal}
                style={{
                  background: "transparent",
                  border: "none",
                  color: "#8b949e",
                  cursor: "pointer",
                  fontSize: "1.1rem",
                  lineHeight: 1,
                  padding: "0.25rem",
                }}
              >
                ✕
              </button>
            </div>

            {/* Subject row */}
            <div style={{ padding: "0.875rem 1.25rem", borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.375rem" }}>
                <span style={{ fontSize: "0.7rem", color: "#8b949e", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  Subject
                </span>
              </div>
              <div style={{ display: "flex", gap: "0.5rem" }}>
                <input
                  readOnly
                  value={modal.subject}
                  style={{
                    flex: 1,
                    background: "rgba(255,255,255,0.04)",
                    border: "1px solid rgba(255,255,255,0.1)",
                    borderRadius: "0.375rem",
                    color: "#e6edf3",
                    fontFamily: "monospace",
                    fontSize: "0.8rem",
                    padding: "0.4rem 0.6rem",
                    outline: "none",
                  }}
                />
                <button
                  onClick={() => copyText(modal.subject, "subject")}
                  style={{
                    background: copied === "subject" ? "rgba(34,197,94,0.15)" : "rgba(255,255,255,0.05)",
                    border: "1px solid rgba(255,255,255,0.1)",
                    borderRadius: "0.375rem",
                    color: copied === "subject" ? "#4ade80" : "#8b949e",
                    cursor: "pointer",
                    fontSize: "0.75rem",
                    fontFamily: "monospace",
                    padding: "0.4rem 0.75rem",
                    whiteSpace: "nowrap",
                    transition: "all 0.15s",
                  }}
                >
                  {copied === "subject" ? "✓ Copied" : "Copy"}
                </button>
              </div>
            </div>

            {/* Body textarea */}
            <div style={{ padding: "0.875rem 1.25rem", flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.375rem" }}>
                <span style={{ fontSize: "0.7rem", color: "#8b949e", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  Body — {modal.body.length.toLocaleString()} chars
                </span>
                <button
                  onClick={() => copyText(modal.body, "body")}
                  style={{
                    background: copied === "body" ? "rgba(34,197,94,0.15)" : "rgba(255,255,255,0.05)",
                    border: "1px solid rgba(255,255,255,0.1)",
                    borderRadius: "0.375rem",
                    color: copied === "body" ? "#4ade80" : "#8b949e",
                    cursor: "pointer",
                    fontSize: "0.75rem",
                    fontFamily: "monospace",
                    padding: "0.3rem 0.65rem",
                    transition: "all 0.15s",
                  }}
                >
                  {copied === "body" ? "✓ Copied" : "Copy Body"}
                </button>
              </div>
              <textarea
                readOnly
                value={modal.body}
                style={{
                  flex: 1,
                  minHeight: "280px",
                  maxHeight: "380px",
                  background: "rgba(255,255,255,0.03)",
                  border: "1px solid rgba(255,255,255,0.08)",
                  borderRadius: "0.375rem",
                  color: "#8b949e",
                  fontFamily: "monospace",
                  fontSize: "0.72rem",
                  lineHeight: 1.5,
                  padding: "0.6rem 0.75rem",
                  resize: "none",
                  outline: "none",
                  overflowY: "auto",
                }}
              />
            </div>

            {/* Footer */}
            <div
              style={{
                display: "flex",
                gap: "0.5rem",
                justifyContent: "flex-end",
                padding: "0.875rem 1.25rem",
                borderTop: "1px solid rgba(255,255,255,0.08)",
              }}
            >
              <a
                href={`mailto:?subject=${encodeURIComponent(modal.subject)}&body=${encodeURIComponent(modal.body)}`}
                style={{
                  background: "rgba(88,166,255,0.12)",
                  border: "1px solid rgba(88,166,255,0.3)",
                  borderRadius: "0.375rem",
                  color: "#58a6ff",
                  cursor: "pointer",
                  fontSize: "0.78rem",
                  fontFamily: "monospace",
                  padding: "0.45rem 0.9rem",
                  textDecoration: "none",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "0.35rem",
                  transition: "background 0.15s",
                }}
              >
                <Mail style={{ width: "0.85rem", height: "0.85rem" }} />
                Open Email Client
              </a>
              <button
                onClick={closeModal}
                style={{
                  background: "rgba(255,255,255,0.04)",
                  border: "1px solid rgba(255,255,255,0.1)",
                  borderRadius: "0.375rem",
                  color: "#8b949e",
                  cursor: "pointer",
                  fontSize: "0.78rem",
                  fontFamily: "monospace",
                  padding: "0.45rem 0.9rem",
                  transition: "color 0.15s",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.color = "#e6edf3")}
                onMouseLeave={(e) => (e.currentTarget.style.color = "#8b949e")}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

interface CodePart {
  filename: string;
  text: string;
  chars: number;
  part: number;
  total_parts: number;
}

interface AuditFindingCode {
  path: string;
  status: "ok" | "missing" | "mismatch" | "not_exported";
  live_hash: string | null;
  export_hash: string | null;
}

interface AuditResult {
  summary: {
    total: number;
    ok: number;
    missing: number;
    mismatches: number;
    not_exported: number;
    all_verified: boolean;
  };
  findings: AuditFindingCode[];
}

function ExportCodeButton() {
  const [loading, setLoading] = useState(false);
  const [parts, setParts] = useState<CodePart[] | null>(null);
  const [copied, setCopied] = useState<number | null>(null);

  const handleExport = async () => {
    setLoading(true);
    try {
      const base = import.meta.env.VITE_API_BASE_URL || "/trading-api";
      const res = await fetch(`${base}/export/code-parts`);
      if (!res.ok) throw new Error("Export failed");
      const data: Record<string, CodePart> = await res.json();
      const ordered = Object.values(data).sort((a, b) => a.part - b.part);
      setParts(ordered);

      for (const part of ordered) {
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
      alert("Code export failed — check that the trading API is running.");
    } finally {
      setLoading(false);
    }
  };

  const copyPart = async (part: CodePart) => {
    try {
      await navigator.clipboard.writeText(part.text);
    } catch {
      const el = document.createElement("textarea");
      el.value = part.text;
      el.style.position = "fixed";
      el.style.opacity = "0";
      document.body.appendChild(el);
      el.select();
      document.execCommand("copy");
      document.body.removeChild(el);
    }
    setCopied(part.part);
    setTimeout(() => setCopied(null), 2000);
  };

  const closeModal = () => setParts(null);

  return (
    <>
      <button
        onClick={handleExport}
        disabled={loading}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-violet-500/30 bg-violet-500/[0.06] hover:bg-violet-500/[0.12] text-xs font-mono text-violet-400 hover:text-violet-300 transition-all disabled:opacity-50"
      >
        <Code className="h-3.5 w-3.5" />
        {loading ? "Exporting..." : "Export Code"}
      </button>

      {parts && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 9999,
            backgroundColor: "rgba(0,0,0,0.8)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "16px",
          }}
          onClick={closeModal}
        >
          <div
            style={{
              backgroundColor: "#0d1117",
              border: "1px solid rgba(139,92,246,0.3)",
              borderRadius: "12px",
              width: "100%",
              maxWidth: "640px",
              maxHeight: "85vh",
              display: "flex",
              flexDirection: "column",
              fontFamily: "monospace",
              color: "#e6edf3",
              boxShadow: "0 0 40px rgba(139,92,246,0.15)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "1rem 1.25rem",
                borderBottom: "1px solid rgba(255,255,255,0.08)",
              }}
            >
              <span style={{ fontSize: "0.875rem", fontWeight: 600, color: "#a78bfa" }}>
                Code Export — Downloaded {parts.length} file{parts.length !== 1 ? "s" : ""}
              </span>
              <button
                onClick={closeModal}
                style={{ background: "transparent", border: "none", color: "#8b949e", cursor: "pointer", fontSize: "1.1rem", lineHeight: 1, padding: "0.25rem" }}
              >
                ✕
              </button>
            </div>

            <div style={{ overflowY: "auto", padding: "0.75rem 1.25rem", display: "flex", flexDirection: "column", gap: "0.625rem" }}>
              <p style={{ fontSize: "0.75rem", color: "#8b949e", margin: "0 0 0.5rem 0" }}>
                Upload each file to Claude — one part per context window. Each part is ≤80k characters and splits only at file boundaries.
              </p>
              {parts.map((part) => (
                <div
                  key={part.part}
                  style={{
                    background: "rgba(255,255,255,0.03)",
                    border: "1px solid rgba(255,255,255,0.08)",
                    borderRadius: "0.5rem",
                    padding: "0.625rem 0.875rem",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: "0.75rem",
                  }}
                >
                  <div style={{ display: "flex", flexDirection: "column", gap: "0.2rem" }}>
                    <span style={{ fontSize: "0.8rem", color: "#a78bfa", fontWeight: 600 }}>{part.filename}</span>
                    <span style={{ fontSize: "0.7rem", color: "#8b949e" }}>
                      {part.chars.toLocaleString()} chars
                    </span>
                  </div>
                  <button
                    onClick={() => copyPart(part)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "0.3rem",
                      background: copied === part.part ? "rgba(139,92,246,0.2)" : "rgba(255,255,255,0.04)",
                      border: `1px solid ${copied === part.part ? "rgba(139,92,246,0.4)" : "rgba(255,255,255,0.1)"}`,
                      borderRadius: "0.375rem",
                      color: copied === part.part ? "#a78bfa" : "#8b949e",
                      cursor: "pointer",
                      fontSize: "0.72rem",
                      padding: "0.35rem 0.625rem",
                      transition: "all 0.15s",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {copied === part.part ? <Check style={{ width: "0.75rem", height: "0.75rem" }} /> : <Copy style={{ width: "0.75rem", height: "0.75rem" }} />}
                    {copied === part.part ? "Copied!" : "Copy"}
                  </button>
                </div>
              ))}
            </div>

            <div style={{ padding: "0.875rem 1.25rem", borderTop: "1px solid rgba(255,255,255,0.08)", display: "flex", justifyContent: "flex-end" }}>
              <button
                onClick={closeModal}
                style={{
                  background: "rgba(255,255,255,0.04)",
                  border: "1px solid rgba(255,255,255,0.1)",
                  borderRadius: "0.375rem",
                  color: "#8b949e",
                  cursor: "pointer",
                  fontSize: "0.78rem",
                  fontFamily: "monospace",
                  padding: "0.45rem 0.9rem",
                }}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function AuditExportButton() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AuditResult | null>(null);

  const handleAudit = async () => {
    setLoading(true);
    try {
      const base = import.meta.env.VITE_API_BASE_URL || "/trading-api";
      const res = await fetch(`${base}/export/code-audit`);
      if (!res.ok) throw new Error("Audit failed");
      const data: AuditResult = await res.json();
      setResult(data);
    } catch {
      alert("Audit failed — check that the trading API is running.");
    } finally {
      setLoading(false);
    }
  };

  const closeModal = () => setResult(null);

  return (
    <>
      <button
        onClick={handleAudit}
        disabled={loading}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/[0.06] hover:bg-emerald-500/[0.12] text-xs font-mono text-emerald-400 hover:text-emerald-300 transition-all disabled:opacity-50"
      >
        <ShieldCheck className="h-3.5 w-3.5" />
        {loading ? "Auditing..." : "Audit Export"}
      </button>

      {result && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 9999,
            backgroundColor: "rgba(0,0,0,0.8)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "16px",
          }}
          onClick={closeModal}
        >
          <div
            style={{
              backgroundColor: "#0d1117",
              border: `1px solid ${result.summary.all_verified ? "rgba(34,197,94,0.3)" : "rgba(239,68,68,0.3)"}`,
              borderRadius: "12px",
              width: "100%",
              maxWidth: "640px",
              maxHeight: "85vh",
              display: "flex",
              flexDirection: "column",
              fontFamily: "monospace",
              color: "#e6edf3",
              boxShadow: result.summary.all_verified ? "0 0 40px rgba(34,197,94,0.1)" : "0 0 40px rgba(239,68,68,0.1)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "1rem 1.25rem",
                borderBottom: "1px solid rgba(255,255,255,0.08)",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                {result.summary.all_verified ? (
                  <ShieldCheck style={{ width: "1rem", height: "1rem", color: "#22c55e" }} />
                ) : (
                  <X style={{ width: "1rem", height: "1rem", color: "#ef4444" }} />
                )}
                <span style={{ fontSize: "0.875rem", fontWeight: 600, color: result.summary.all_verified ? "#22c55e" : "#ef4444" }}>
                  {result.summary.all_verified
                    ? `All ${result.summary.ok} files verified — export is byte-exact`
                    : `${result.summary.mismatches} mismatch${result.summary.mismatches !== 1 ? "es" : ""}${result.summary.missing > 0 ? `, ${result.summary.missing} missing` : ""} found`}
                </span>
              </div>
              <button
                onClick={closeModal}
                style={{ background: "transparent", border: "none", color: "#8b949e", cursor: "pointer", fontSize: "1.1rem", lineHeight: 1, padding: "0.25rem" }}
              >
                ✕
              </button>
            </div>

            <div style={{ display: "flex", gap: "1.5rem", padding: "0.75rem 1.25rem", borderBottom: "1px solid rgba(255,255,255,0.06)", fontSize: "0.72rem" }}>
              <span style={{ color: "#22c55e" }}>✓ {result.summary.ok} OK</span>
              {result.summary.mismatches > 0 && <span style={{ color: "#ef4444" }}>✗ {result.summary.mismatches} mismatch{result.summary.mismatches !== 1 ? "es" : ""}</span>}
              {result.summary.missing > 0 && <span style={{ color: "#f59e0b" }}>⚠ {result.summary.missing} missing</span>}
              {result.summary.not_exported > 0 && <span style={{ color: "#6b7280" }}>○ {result.summary.not_exported} not yet exported</span>}
              <span style={{ color: "#8b949e" }}>total: {result.summary.total}</span>
            </div>

            <div style={{ overflowY: "auto", padding: "0.5rem 0.75rem", display: "flex", flexDirection: "column", gap: "0.25rem" }}>
              {result.findings.map((f) => (
                <div
                  key={f.path}
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: "0.5rem",
                    padding: "0.375rem 0.5rem",
                    borderRadius: "0.375rem",
                    background: f.status === "ok" ? "transparent"
                      : f.status === "mismatch" ? "rgba(239,68,68,0.06)"
                      : f.status === "not_exported" ? "rgba(107,114,128,0.06)"
                      : "rgba(245,158,11,0.06)",
                  }}
                >
                  <span style={{ fontSize: "0.75rem", marginTop: "0.05rem", flexShrink: 0, color: f.status === "ok" ? "#22c55e" : f.status === "mismatch" ? "#ef4444" : f.status === "not_exported" ? "#6b7280" : "#f59e0b" }}>
                    {f.status === "ok" ? "✓" : f.status === "mismatch" ? "✗" : f.status === "not_exported" ? "○" : "⚠"}
                  </span>
                  <div style={{ display: "flex", flexDirection: "column", gap: "0.1rem", minWidth: 0 }}>
                    <span style={{ fontSize: "0.72rem", color: f.status === "ok" ? "#8b949e" : f.status === "mismatch" ? "#fca5a5" : f.status === "not_exported" ? "#6b7280" : "#fcd34d", wordBreak: "break-all" }}>
                      {f.path}
                    </span>
                    {f.status === "mismatch" && (
                      <span style={{ fontSize: "0.65rem", color: "#6b7280" }}>
                        live: {f.live_hash?.slice(0, 16)}… export: {f.export_hash?.slice(0, 16)}…
                      </span>
                    )}
                    {f.status === "missing" && (
                      <span style={{ fontSize: "0.65rem", color: "#6b7280" }}>file not found on disk</span>
                    )}
                    {f.status === "not_exported" && (
                      <span style={{ fontSize: "0.65rem", color: "#6b7280" }}>run Export Code first to establish baseline</span>
                    )}
                  </div>
                </div>
              ))}
            </div>

            <div style={{ padding: "0.875rem 1.25rem", borderTop: "1px solid rgba(255,255,255,0.08)", display: "flex", justifyContent: "flex-end" }}>
              <button
                onClick={closeModal}
                style={{
                  background: "rgba(255,255,255,0.04)",
                  border: "1px solid rgba(255,255,255,0.1)",
                  borderRadius: "0.375rem",
                  color: "#8b949e",
                  cursor: "pointer",
                  fontSize: "0.78rem",
                  fontFamily: "monospace",
                  padding: "0.45rem 0.9rem",
                }}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// ── Reusable collapsable section wrapper ─────────────────────────────────────
function CollapsableSection({
  title,
  icon,
  badge,
  children,
  defaultOpen = false,
}: {
  title: string;
  icon: ReactNode;
  badge?: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-4 py-3 rounded-xl border border-white/8 bg-white/[0.02] hover:bg-white/[0.05] transition-colors group"
      >
        <div className="flex items-center gap-2.5">
          {icon}
          <span className="text-sm font-semibold text-white/80 group-hover:text-white transition-colors tracking-tight">
            {title}
          </span>
          {badge}
        </div>
        <ChevronDown
          className={cn(
            "h-4 w-4 text-muted-foreground/60 transition-transform duration-200",
            open && "rotate-180"
          )}
        />
      </button>
      {open && <div className="mt-3">{children}</div>}
    </div>
  );
}

// ── Unified closed trade row type ─────────────────────────────────────────────
interface UnifiedTrade {
  id: string;
  bot: string;
  botColor: string;
  symbol: string;
  side: string;
  pnl_pct: number;
  pnl_usd: number | null;
  reason: string | null;
  closed_at: string;
  is_win: boolean;
}

function AllClosedTradesSection() {
  const { data: journal } = useJournal();
  const { data: davyStatus } = useKrakenStatus("davy-jones");
  const { data: bbStatus }   = useKrakenStatus("blackbeard");
  const { data: caStatus }   = useKrakenStatus("calypso");
  const [page, setPage] = useState(1);
  const PER_PAGE  = 25;
  const MAX_TRADES = 100;

  const allTrades = useMemo<UnifiedTrade[]>(() => {
    const trades: UnifiedTrade[] = [];

    // Alpaca / Oracle journal trades — skip Kraken-sourced entries (those are
    // already shown under each Kraken bot via status.recent_trades below)
    if (journal?.trades) {
      for (const t of journal.trades) {
        if (t.status === "Active") continue;
        if (t.source === "kraken") continue;
        const pnlUsd = t.realized_pnl ?? null;
        const isWin = t.status === "Closed_Win" ||
          (t.status === "Closed" && (t.pnl_percentage ?? 0) > 0) ||
          (pnlUsd != null ? pnlUsd > 0 : (t.pnl_percentage ?? 0) > 0);
        trades.push({
          id: t.trade_id,
          bot: "Oracle #1",
          botColor: "text-blue-400",
          symbol: t.ticker,
          side: (t.asset_class ?? "").toLowerCase().includes("short") ? "short" : "long",
          pnl_pct: t.pnl_percentage ?? 0,
          pnl_usd: pnlUsd,
          reason: t.exit_reason ?? null,
          closed_at: t.date,
          is_win: isWin,
        });
      }
    }

    // Kraken bots — each returns up to 50 recent trades
    const krakenBots: { status: typeof davyStatus; name: string; color: string }[] = [
      { status: davyStatus, name: "Davy Jones #2", color: "text-emerald-400" },
      { status: bbStatus,   name: "Blackbeard #3", color: "text-amber-400"   },
      { status: caStatus,   name: "Calypso #4",    color: "text-violet-400"  },
    ];
    for (const { status, name, color } of krakenBots) {
      if (!status?.recent_trades) continue;
      for (const t of status.recent_trades) {
        trades.push({
          id: `${name}-${t.closed_at}-${t.symbol}`,
          bot: name,
          botColor: color,
          symbol: t.symbol,
          side: t.side ?? "—",
          pnl_pct: t.pnl_pct ?? 0,
          pnl_usd: t.pnl_usd ?? null,
          reason: t.reason ?? null,
          closed_at: t.closed_at,
          is_win: (t.pnl_usd ?? 0) > 0 || (t.pnl_usd == null && (t.pnl_pct ?? 0) > 0),
        });
      }
    }

    // Sort newest-first, cap at MAX_TRADES
    trades.sort((a, b) => new Date(b.closed_at).getTime() - new Date(a.closed_at).getTime());
    return trades.slice(0, MAX_TRADES);
  }, [journal, davyStatus, bbStatus, caStatus]);

  const totalPages = Math.max(1, Math.ceil(allTrades.length / PER_PAGE));
  const safePage   = Math.min(page, totalPages);
  const paginated  = allTrades.slice((safePage - 1) * PER_PAGE, safePage * PER_PAGE);

  useEffect(() => { setPage(1); }, [allTrades.length]);

  const wins  = allTrades.filter((t) => t.is_win).length;
  const total = allTrades.length;

  function fmtDate(iso: string) {
    try {
      const d = new Date(iso);
      return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" })
        + " " + d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
    } catch { return iso.slice(0, 16); }
  }

  if (total === 0) {
    return (
      <div className="rounded-xl border border-white/8 bg-white/[0.02] px-6 py-10 text-center text-sm text-muted-foreground">
        No closed trades yet
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-white/8 bg-slate-950/60 overflow-hidden">
      {/* Summary strip */}
      <div className="flex items-center gap-4 px-4 py-2.5 border-b border-white/6 text-[10px] font-mono text-muted-foreground/60">
        <span className="flex items-center gap-1.5">
          <Hash className="h-3 w-3" />
          {total} trades
        </span>
        <span className="text-emerald-400/70">{wins}W</span>
        <span className="text-red-400/70">{total - wins}L</span>
        <span className={cn(
          "font-semibold",
          total > 0 && wins / total >= 0.5 ? "text-emerald-400" : "text-red-400"
        )}>
          {total > 0 ? ((wins / total) * 100).toFixed(1) : "0.0"}% WR
        </span>
        <span className="ml-auto text-muted-foreground/40">latest {MAX_TRADES} · page {safePage}/{totalPages}</span>
      </div>

      {/* Trade table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-white/6 text-[10px] uppercase tracking-wider text-muted-foreground/50">
              <th className="text-left px-4 py-2 font-semibold">Time</th>
              <th className="text-left px-3 py-2 font-semibold">Bot</th>
              <th className="text-left px-3 py-2 font-semibold">Symbol</th>
              <th className="text-left px-3 py-2 font-semibold">Side</th>
              <th className="text-right px-3 py-2 font-semibold">P&L %</th>
              <th className="text-right px-3 py-2 font-semibold">P&L $</th>
              <th className="text-left px-3 py-2 font-semibold hidden sm:table-cell">Reason</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.04]">
            {paginated.map((t) => (
              <tr
                key={t.id}
                className={cn(
                  "transition-colors",
                  t.is_win ? "hover:bg-emerald-500/[0.03]" : "hover:bg-red-500/[0.03]"
                )}
              >
                <td className="px-4 py-2.5 font-mono text-[11px] text-muted-foreground/60 whitespace-nowrap">
                  {fmtDate(t.closed_at)}
                </td>
                <td className="px-3 py-2.5 whitespace-nowrap">
                  <span className={cn("font-mono text-[10px] font-semibold", t.botColor)}>
                    {t.bot}
                  </span>
                </td>
                <td className="px-3 py-2.5 font-mono font-semibold text-white/90 whitespace-nowrap">
                  {t.symbol}
                </td>
                <td className="px-3 py-2.5 whitespace-nowrap">
                  <span className={cn(
                    "text-[10px] font-mono uppercase px-1.5 py-0.5 rounded font-semibold",
                    t.side === "short"
                      ? "bg-red-500/10 text-red-400"
                      : "bg-blue-500/10 text-blue-400"
                  )}>
                    {t.side}
                  </span>
                </td>
                <td className={cn(
                  "px-3 py-2.5 text-right font-mono font-semibold tabular-nums whitespace-nowrap",
                  t.is_win ? "text-emerald-400" : "text-red-400"
                )}>
                  {t.pnl_pct >= 0 ? "+" : ""}{t.pnl_pct.toFixed(2)}%
                </td>
                <td className={cn(
                  "px-3 py-2.5 text-right font-mono tabular-nums whitespace-nowrap",
                  t.pnl_usd == null
                    ? "text-muted-foreground/40"
                    : t.is_win ? "text-emerald-400/80" : "text-red-400/80"
                )}>
                  {t.pnl_usd != null
                    ? `${t.pnl_usd >= 0 ? "+" : ""}${formatCurrency(t.pnl_usd)}`
                    : "—"}
                </td>
                <td className="px-3 py-2.5 text-muted-foreground/50 hidden sm:table-cell max-w-[180px]">
                  <span className="truncate block text-[10px]">
                    {t.reason ?? "—"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between px-4 py-2.5 border-t border-white/6">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={safePage === 1}
            className="text-[11px] font-mono px-3 py-1.5 rounded-lg border border-white/10 text-muted-foreground hover:text-white hover:border-white/20 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
          >
            ← Prev
          </button>
          <div className="flex items-center gap-1">
            {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
              <button
                key={p}
                onClick={() => setPage(p)}
                className={cn(
                  "w-7 h-7 rounded-md text-[11px] font-mono transition-all",
                  p === safePage
                    ? "bg-primary/20 border border-primary/40 text-primary"
                    : "text-muted-foreground/50 hover:text-white hover:bg-white/[0.04]"
                )}
              >
                {p}
              </button>
            ))}
          </div>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={safePage === totalPages}
            className="text-[11px] font-mono px-3 py-1.5 rounded-lg border border-white/10 text-muted-foreground hover:text-white hover:border-white/20 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
          >
            Next →
          </button>
        </div>
      )}
    </div>
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

      <main className="flex-1 max-w-[1600px] w-full mx-auto px-3 sm:px-6 lg:px-8 py-6 sm:py-8 space-y-6 sm:space-y-8 pb-28">
        <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
          <SafeSection label="Trade Controls">
            <div className="relative rounded-2xl border border-primary/20 bg-gradient-to-br from-slate-900/80 to-slate-950/80 px-4 sm:px-7 py-4 sm:py-5 shadow-[0_0_60px_rgba(59,130,246,0.05)] overflow-hidden">
              <div className="absolute top-0 left-0 w-64 h-64 bg-primary/5 rounded-full blur-3xl -translate-x-1/2 -translate-y-1/2 pointer-events-none" />
              <div className="flex items-center justify-between gap-3">
                <div className="flex-1"><TradeWorkflowBar /></div>
                <ExportReportButton />
                <EmailReportButton />
                <ExportCodeButton />
                <AuditExportButton />
              </div>
            </div>
          </SafeSection>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.04 }}>
          <SafeSection label="Fleet KPIs">
            <FleetKPISummary />
          </SafeSection>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.06 }}>
          <SafeSection label="Fleet Performance">
            <FleetPerformanceHero />
          </SafeSection>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08 }}>
          <SafeSection label="Live Portfolio Equity Curve">
            <LiveEquityCurveSection />
          </SafeSection>
        </motion.div>

        {/* All Closed Trades — collapsable */}
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.10 }}>
          <SafeSection label="All Closed Trades">
            <CollapsableSection
              title="All Closed Trades"
              defaultOpen={false}
              icon={<TrendingDown className="h-4 w-4 text-emerald-400/70" />}
            >
              <AllClosedTradesSection />
            </CollapsableSection>
          </SafeSection>
        </motion.div>

        {/* AI Interventions — collapsable */}
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12 }}>
          <SafeSection label="AI Impact Timeline">
            <CollapsableSection
              title="AI Intervention Timeline"
              defaultOpen={false}
              icon={<Brain className="h-4 w-4 text-violet-400/70" />}
            >
              <AIImpactTimeline />
            </CollapsableSection>
          </SafeSection>
        </motion.div>

        {/* System Health / Bug Report — collapsable */}
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.14 }}>
          <SafeSection label="System Health Log">
            <CollapsableSection
              title="System Health Log & Bug Report"
              defaultOpen={false}
              icon={<ShieldAlert className="h-4 w-4 text-amber-400/70" />}
            >
              <SystemDegradationLog />
            </CollapsableSection>
          </SafeSection>
        </motion.div>
      </main>
    </div>
  );
}

