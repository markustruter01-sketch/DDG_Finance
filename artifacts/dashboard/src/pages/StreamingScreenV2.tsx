import { useEffect, useState, useRef, useMemo } from "react";
import { motion } from "framer-motion";
import {
  useStatusSummary,
  useKrakenStatus,
  useKrakenFleetSummary,
  useKrakenPerformance,
  useOptionsState,
  useForexState,
  useLivePositions,
  useForexPositions,
  useEquityCurve,
  useSentiment,
} from "@/hooks/use-trading";
import { useRealFeed } from "@/components/streaming/useRealFeed";
import { AnimatedValue } from "@/components/streaming/AnimatedValue";
import { MiniSparkline } from "@/lib/dashboard-shared";
import { formatCurrency } from "@/lib/utils";


const BOT_META: Record<string, { icon: string; color: string; label: string }> = {
  oracle:     { icon: "🔮", color: "#8b5cf6", label: "Oracle #1" },
  "davy-jones": { icon: "⚓", color: "#22d3ee", label: "Davy Jones #2" },
  blackbeard: { icon: "🏴‍☠️", color: "#f97316", label: "Blackbeard #3" },
  calypso:    { icon: "🌊", color: "#a855f7", label: "Calypso #4" },
  apex:       { icon: "🎯", color: "#f59e0b", label: "Apex Predator #5" },
  navigator:  { icon: "🧭", color: "#10b981", label: "Navigator #6" },
};

function fmtUsd(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `${v >= 0 ? "" : "-"}$${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${v >= 0 ? "" : "-"}$${(abs / 1_000).toFixed(1)}k`;
  return `${v >= 0 ? "" : "-"}$${abs.toFixed(2)}`;
}

function fmtPnl(v: number): string {
  return `${v >= 0 ? "+" : ""}${fmtUsd(v)}`;
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  return `${Math.floor(hrs / 24)}d`;
}

function PulsingDot({ color }: { color: string }) {
  return (
    <span className="relative flex h-2 w-2">
      <span
        className="absolute inline-flex h-full w-full rounded-full opacity-60"
        style={{ backgroundColor: color, animation: "ping 2s cubic-bezier(0,0,0.2,1) infinite" }}
      />
      <span className="relative inline-flex rounded-full h-2 w-2" style={{ backgroundColor: color }} />
    </span>
  );
}

function HeroStrip() {
  const { data: summary } = useStatusSummary();
  const { data: fleet } = useKrakenFleetSummary();
  const { data: optState } = useOptionsState();
  const { data: fxState } = useForexState();
  const { data: sentiment } = useSentiment();
  const { data: curve } = useEquityCurve(100);
  const { wins, losses, totalTrades } = useRealFeed(50);

  const alpacaEq = summary?.portfolio_totals?.equity ?? 0;
  const krakenEq = fleet?.total_equity_usd ?? 0;
  const optEq = optState?.paper_equity ?? 0;
  const fxEq = fxState?.paper_equity ?? 0;
  const totalEquity = alpacaEq + krakenEq + optEq + fxEq;

  const pnl24h = useMemo(() => {
    if (!curve?.snapshots?.length) return { value: 0, pct: 0 };
    const now = Date.now();
    const cutoff = now - 24 * 60 * 60 * 1000;
    const snaps = curve.snapshots;
    const baseline = snaps.find(s => new Date(s.ts).getTime() >= cutoff) ?? snaps[0];
    const latest = snaps[snaps.length - 1];
    if (!baseline || !latest) return { value: 0, pct: 0 };
    const delta = latest.total_equity - baseline.total_equity;
    const pct = baseline.total_equity > 0 ? (delta / baseline.total_equity) * 100 : 0;
    return { value: delta, pct };
  }, [curve]);

  const [prevPnl, setPrevPnl] = useState(0);
  const pnlDelta = pnl24h.value - prevPnl;
  useEffect(() => {
    if (pnl24h.value !== prevPnl) {
      const timer = setTimeout(() => setPrevPnl(pnl24h.value), 2000);
      return () => clearTimeout(timer);
    }
  }, [pnl24h.value, prevPnl]);

  const winRate = totalTrades > 0 ? ((wins / totalTrades) * 100).toFixed(1) : "0.0";

  const cfg = sentiment?.crypto_fear_greed;

  return (
    <div className="flex items-center gap-6 px-6 py-3 border-b shrink-0" style={{ borderColor: "rgba(255,255,255,0.06)", background: "linear-gradient(90deg, rgba(15,23,42,0.95), rgba(30,41,59,0.9))" }}>
      <div className="flex items-center gap-3">
        <span style={{ fontSize: 22 }}>⚡</span>
        <div>
          <div className="text-[9px] uppercase tracking-widest font-bold" style={{ color: "rgba(148,163,184,0.5)" }}>Fleet Equity</div>
          <AnimatedValue value={formatCurrency(totalEquity)} className="text-xl font-mono font-black text-white" />
        </div>
      </div>

      <div className="h-8 w-px" style={{ backgroundColor: "rgba(255,255,255,0.06)" }} />

      <div>
        <div className="text-[9px] uppercase tracking-widest font-bold" style={{ color: "rgba(148,163,184,0.5)" }}>24h P&L</div>
        <div className="flex items-baseline gap-1.5">
          <AnimatedValue
            value={fmtPnl(pnl24h.value)}
            className={`text-base font-mono font-bold ${pnl24h.value >= 0 ? "text-green-400" : "text-red-400"}`}
          />
          <span className="text-[10px] font-mono opacity-60" style={{ color: pnl24h.pct >= 0 ? "#4ade80" : "#f87171" }}>
            ({pnl24h.pct >= 0 ? "+" : ""}{pnl24h.pct.toFixed(2)}%)
          </span>
          {pnlDelta !== 0 && (
            <motion.span
              initial={{ opacity: 1, y: 0 }}
              animate={{ opacity: 0, y: -12 }}
              transition={{ duration: 1.5 }}
              key={`delta-${pnl24h.value}`}
              className="text-[9px] font-mono font-bold"
              style={{ color: pnlDelta >= 0 ? "#22c55e" : "#ef4444" }}
            >
              {pnlDelta >= 0 ? "+" : ""}{fmtUsd(pnlDelta)}
            </motion.span>
          )}
        </div>
      </div>

      <div className="h-8 w-px" style={{ backgroundColor: "rgba(255,255,255,0.06)" }} />

      <div className="flex items-center gap-4">
        <div className="text-center">
          <div className="text-[9px] uppercase tracking-widest font-bold" style={{ color: "rgba(74,222,128,0.5)" }}>Wins</div>
          <span className="text-lg font-mono font-black text-green-400">{wins}</span>
        </div>
        <div className="text-center">
          <div className="text-[9px] uppercase tracking-widest font-bold" style={{ color: "rgba(251,146,60,0.5)" }}>Losses</div>
          <span className="text-lg font-mono font-black text-orange-400">{losses}</span>
        </div>
        <div className="text-center">
          <div className="text-[9px] uppercase tracking-widest font-bold" style={{ color: "rgba(148,163,184,0.5)" }}>Win Rate</div>
          <span className="text-lg font-mono font-black text-white">{winRate}%</span>
        </div>
      </div>

      <div className="h-8 w-px" style={{ backgroundColor: "rgba(255,255,255,0.06)" }} />

      <div className="flex items-center gap-3 ml-auto">
        <div className="text-center px-2 py-1 rounded-lg border" style={{ borderColor: "rgba(139,92,246,0.15)", backgroundColor: "rgba(139,92,246,0.05)" }}>
          <div className="text-[8px] uppercase tracking-widest font-bold" style={{ color: "rgba(139,92,246,0.5)" }}>Equity Regime</div>
          <span className="text-sm font-mono font-bold" style={{ color: "#8b5cf6" }}>
            {summary?.groq?.regime ?? "---"}
          </span>
        </div>
        {cfg && cfg.value != null && (
          <div className="text-center px-2 py-1 rounded-lg border" style={{ borderColor: "rgba(34,211,238,0.15)", backgroundColor: "rgba(34,211,238,0.05)" }}>
            <div className="text-[8px] uppercase tracking-widest font-bold" style={{ color: "rgba(34,211,238,0.5)" }}>Crypto Regime</div>
            <span className="text-sm font-mono font-bold" style={{ color: "#22d3ee" }}>{cfg.value}</span>
            <span className="text-[9px] ml-1" style={{ color: "rgba(34,211,238,0.6)" }}>{cfg.label}</span>
          </div>
        )}
        <div className="flex items-center gap-1.5">
          <PulsingDot color="#22c55e" />
          <span className="text-[10px] font-mono font-bold" style={{ color: "rgba(34,197,94,0.7)" }}>LIVE</span>
        </div>
      </div>
    </div>
  );
}

function BotTile({ botKey, equity, pnl, status, thinkingText, posCount, cycleCount, winCount, lossCount, color, hasRecentTrade, currentTicker, signalStrength, lastSignal }: {
  botKey: string; equity: number; pnl: number; status: string; thinkingText: string;
  posCount: number; cycleCount: number; winCount: number; lossCount: number; color: string;
  hasRecentTrade?: boolean; currentTicker?: string; signalStrength?: string; lastSignal?: string;
}) {
  const meta = BOT_META[botKey] ?? { icon: "🤖", color: "#64748b", label: botKey };
  const isOnline = status === "running" || status === "online" || status === "ok";
  const truncatedThinking = thinkingText.length > 40 ? thinkingText.slice(0, 37) + "..." : thinkingText;

  return (
    <motion.div
      className="rounded-lg border p-2 flex flex-col gap-1 min-w-0"
      animate={hasRecentTrade ? { boxShadow: [`0 0 0px ${color}00`, `0 0 16px ${color}60`, `0 0 0px ${color}00`] } : {}}
      transition={hasRecentTrade ? { duration: 1.5, repeat: 2 } : {}}
      style={{
        borderColor: hasRecentTrade ? `${color}60` : `${color}25`,
        background: `linear-gradient(135deg, rgba(15,23,42,0.95), ${color}08)`,
      }}>
      <div className="flex items-center gap-2">
        <span style={{ fontSize: 16 }}>{meta.icon}</span>
        <span className="text-[11px] font-black uppercase tracking-wider truncate" style={{ color }}>{meta.label}</span>
        <span className="ml-auto">
          <PulsingDot color={isOnline ? "#22c55e" : "#ef4444"} />
        </span>
      </div>

      <div className="flex items-baseline gap-2">
        <span className="text-sm font-mono font-bold text-white">{fmtUsd(equity)}</span>
        <span className={`text-[10px] font-mono font-semibold ${pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
          {fmtPnl(pnl)}
        </span>
      </div>

      <div className="flex items-center gap-2 text-[9px] font-mono" style={{ color: "rgba(148,163,184,0.5)" }}>
        <span>{winCount}W/{lossCount}L</span>
        <span>·</span>
        <span>{posCount} pos</span>
        <span>·</span>
        <span>C#{cycleCount}</span>
      </div>

      {(currentTicker || lastSignal) && (
        <div className="flex items-center gap-1.5 text-[9px] font-mono truncate" style={{ color: `${color}bb` }}>
          {currentTicker && <span className="font-bold text-white">{currentTicker}</span>}
          {lastSignal && <span>{lastSignal.toUpperCase()}</span>}
          {signalStrength && <span style={{ color: "#f59e0b" }}>{signalStrength}</span>}
        </div>
      )}

      {truncatedThinking && (
        <div className="text-[9px] font-mono leading-relaxed mt-0.5 overflow-hidden" style={{
          color: `${color}99`,
          maxHeight: 28,
        }}>
          {truncatedThinking}
        </div>
      )}
    </motion.div>
  );
}

function BotTilesRow() {
  const { data: summary } = useStatusSummary();
  const { data: djStatus } = useKrakenStatus("davy-jones");
  const { data: bbStatus } = useKrakenStatus("blackbeard");
  const { data: caStatus } = useKrakenStatus("calypso");
  const { data: djPerf } = useKrakenPerformance("davy-jones");
  const { data: bbPerf } = useKrakenPerformance("blackbeard");
  const { data: caPerf } = useKrakenPerformance("calypso");
  const { data: optState } = useOptionsState();
  const { data: fxState } = useForexState();
  const { data: livePos } = useLivePositions();
  const { data: fxPos } = useForexPositions();

  const alpacaEq = summary?.portfolio_totals?.equity ?? 0;
  const oracleStatus = summary?.system_health?.system_status ?? "offline";
  const alpacaStartCap = summary?.portfolio_totals?.initial_capital ?? 100_000;
  const oraclePnl = alpacaEq - alpacaStartCap;
  const oraclePositions = livePos?.count ?? 0;
  const { botStats, trades: recentTrades } = useRealFeed(50);
  const oracleStats = botStats.find(b => b.name === "Oracle");
  const oracleWins = oracleStats?.wins ?? 0;
  const oracleLosses = oracleStats?.losses ?? 0;
  const oracleCycles = summary?.system_health?.run_count ?? 0;

  const recentBotTrades = useMemo(() => {
    const cutoff = Date.now() - 60_000;
    const recent = new Set<string>();
    for (const t of recentTrades) {
      if (new Date(t.date).getTime() >= cutoff) {
        const botKey = t.bot === "Davy Jones" ? "davy-jones" : t.bot === "Apex Predator" ? "apex" : t.bot.toLowerCase();
        recent.add(botKey);
      }
    }
    const krakenBots = [
      { data: djStatus, key: "davy-jones" },
      { data: bbStatus, key: "blackbeard" },
      { data: caStatus, key: "calypso" },
    ];
    for (const { data, key } of krakenBots) {
      if (data?.recent_trades?.length) {
        const latest = data.recent_trades[data.recent_trades.length - 1];
        if (latest.closed_at && Date.now() - new Date(latest.closed_at).getTime() < 60_000) {
          recent.add(key);
        }
      }
    }
    return recent;
  }, [recentTrades, djStatus, bbStatus, caStatus]);

  function getKrakenTopSignal(status: typeof djStatus) {
    if (!status?.signals?.length) return { ticker: undefined, signal: undefined, strength: undefined };
    const active = status.signals.find(s => s.signal_type && s.signal_type !== "watching") ?? status.signals[0];
    return {
      ticker: active?.symbol,
      signal: active?.signal_type,
      strength: active?.conviction != null ? `${(active.conviction * 100).toFixed(0)}%` :
        active?.rsi != null ? `RSI ${active.rsi.toFixed(0)}` : undefined,
    };
  }

  const djSig = getKrakenTopSignal(djStatus);
  const bbSig = getKrakenTopSignal(bbStatus);
  const caSig = getKrakenTopSignal(caStatus);

  const optTopScan = optState?.last_scan_results?.[0];
  const fxTopScan = fxState?.last_scan_results?.[0];

  const bots = [
    {
      key: "oracle", equity: alpacaEq, pnl: oraclePnl, status: oracleStatus,
      thinkingText: summary?.groq?.regime ? `Regime: ${summary.groq.regime}` : "",
      posCount: oraclePositions, cycleCount: oracleCycles,
      winCount: oracleWins, lossCount: oracleLosses, color: BOT_META.oracle.color,
      currentTicker: undefined as string | undefined,
      lastSignal: summary?.groq?.regime,
      signalStrength: undefined as string | undefined,
    },
    {
      key: "davy-jones", equity: djStatus?.total_equity_usd ?? 0,
      pnl: (djStatus?.total_equity_usd ?? 0) - (djStatus?.paper_summary?.starting_balance_usd ?? 100_000),
      status: djStatus?.status ?? "offline", thinkingText: djStatus?.thinking_text ?? "",
      posCount: djStatus?.position_count ?? 0, cycleCount: djStatus?.cycle_count ?? 0,
      winCount: djPerf?.win_count ?? 0, lossCount: djPerf?.loss_count ?? 0,
      color: BOT_META["davy-jones"].color,
      currentTicker: djSig.ticker, lastSignal: djSig.signal, signalStrength: djSig.strength,
    },
    {
      key: "blackbeard", equity: bbStatus?.total_equity_usd ?? 0,
      pnl: (bbStatus?.total_equity_usd ?? 0) - (bbStatus?.paper_summary?.starting_balance_usd ?? 100_000),
      status: bbStatus?.status ?? "offline", thinkingText: bbStatus?.thinking_text ?? "",
      posCount: bbStatus?.position_count ?? 0, cycleCount: bbStatus?.cycle_count ?? 0,
      winCount: bbPerf?.win_count ?? 0, lossCount: bbPerf?.loss_count ?? 0,
      color: BOT_META.blackbeard.color,
      currentTicker: bbSig.ticker, lastSignal: bbSig.signal, signalStrength: bbSig.strength,
    },
    {
      key: "calypso", equity: caStatus?.total_equity_usd ?? 0,
      pnl: (caStatus?.total_equity_usd ?? 0) - (caStatus?.paper_summary?.starting_balance_usd ?? 100_000),
      status: caStatus?.status ?? "offline", thinkingText: caStatus?.thinking_text ?? "",
      posCount: caStatus?.position_count ?? 0, cycleCount: caStatus?.cycle_count ?? 0,
      winCount: caPerf?.win_count ?? 0, lossCount: caPerf?.loss_count ?? 0,
      color: BOT_META.calypso.color,
      currentTicker: caSig.ticker, lastSignal: caSig.signal, signalStrength: caSig.strength,
    },
    {
      key: "apex", equity: optState?.paper_equity ?? 0,
      pnl: optState?.total_pnl ?? 0, status: optState?.status ?? "offline",
      thinkingText: optState?.error ?? (optState?.circuit_breaker_active ? "Circuit breaker active" : ""),
      posCount: optState?.positions_count ?? 0, cycleCount: optState?.cycle_count ?? 0,
      winCount: optState?.total_wins ?? 0,
      lossCount: (optState?.total_trades ?? 0) - (optState?.total_wins ?? 0),
      color: BOT_META.apex.color,
      currentTicker: optTopScan?.symbol,
      lastSignal: optTopScan?.is_squeeze ? "squeeze" : undefined,
      signalStrength: optTopScan?.ivr != null ? `IVR ${optTopScan.ivr.toFixed(0)}` : undefined,
    },
    {
      key: "navigator", equity: fxState?.paper_equity ?? 0,
      pnl: fxState?.total_pnl ?? 0, status: fxState?.status ?? "offline",
      thinkingText: fxState?.usd_bias ? `USD Bias: ${fxState.usd_bias}` : "",
      posCount: fxState?.position_count ?? 0, cycleCount: fxState?.cycle_count ?? 0,
      winCount: fxState?.total_wins ?? 0,
      lossCount: (fxState?.total_trades ?? 0) - (fxState?.total_wins ?? 0),
      color: BOT_META.navigator.color,
      currentTicker: fxTopScan?.pair,
      lastSignal: fxTopScan?.signal ?? undefined,
      signalStrength: fxTopScan?.rsi != null ? `RSI ${fxTopScan.rsi.toFixed(0)}` : undefined,
    },
  ];

  return (
    <div className="flex flex-col gap-1.5 w-52 shrink-0 overflow-auto min-h-0 px-1">
      {bots.map((b) => (
        <BotTile
          key={b.key}
          botKey={b.key}
          equity={b.equity}
          pnl={b.pnl}
          status={b.status}
          thinkingText={b.thinkingText}
          posCount={b.posCount}
          cycleCount={b.cycleCount}
          winCount={b.winCount}
          lossCount={b.lossCount}
          color={b.color}
          hasRecentTrade={recentBotTrades.has(b.key)}
          currentTicker={b.currentTicker}
          lastSignal={b.lastSignal}
          signalStrength={b.signalStrength}
        />
      ))}
    </div>
  );
}

interface NeuralLine {
  id: string;
  ts: number;
  bot: string;
  icon: string;
  color: string;
  text: string;
  type: "thinking" | "signal" | "trade" | "position" | "system";
  highConviction?: boolean;
}

function NeuralFeed() {
  const { data: djStatus } = useKrakenStatus("davy-jones");
  const { data: bbStatus } = useKrakenStatus("blackbeard");
  const { data: caStatus } = useKrakenStatus("calypso");
  const { data: optState } = useOptionsState();
  const { data: fxState } = useForexState();
  const { data: summary } = useStatusSummary();

  const [lines, setLines] = useState<NeuralLine[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const prevThinking = useRef<Record<string, string>>({});

  useEffect(() => {
    const newLines: NeuralLine[] = [];
    const now = Date.now();

    const krakenBots = [
      { data: djStatus, key: "davy-jones", bot: "Davy Jones", icon: "⚓", color: "#22d3ee" },
      { data: bbStatus, key: "blackbeard", bot: "Blackbeard", icon: "🏴‍☠️", color: "#f97316" },
      { data: caStatus, key: "calypso", bot: "Calypso", icon: "🌊", color: "#a855f7" },
    ];

    for (const { data, key, bot, icon, color } of krakenBots) {
      if (!data) continue;

      if (data.thinking_text && data.thinking_text !== prevThinking.current[key]) {
        prevThinking.current[key] = data.thinking_text;
        const thinkHash = data.thinking_text.slice(0, 60).replace(/\s+/g, "_");
        newLines.push({
          id: `think-${key}-${thinkHash}`, ts: now, bot, icon, color,
          text: data.thinking_text,
          type: "thinking",
        });
      }

      if (data.signals && data.signals.length > 0) {
        const top3 = data.signals.slice(0, 3);
        for (const s of top3) {
          if (s.signal_type && s.signal_type !== "watching") {
            const parts = [`SIGNAL ${s.symbol}: ${s.signal_type.toUpperCase()}`];
            if (s.rsi != null) parts.push(`RSI=${s.rsi.toFixed(1)}`);
            if (s.z_score != null) parts.push(`Z=${s.z_score.toFixed(2)}`);
            if (s.vpin != null) parts.push(`VPIN=${s.vpin.toFixed(3)}`);
            if (s.ofi != null) parts.push(`OFI=${s.ofi > 0 ? "+" : ""}${s.ofi.toFixed(2)}`);
            if (s.conviction != null) parts.push(`Conv=${(s.conviction * 100).toFixed(0)}%`);
            const decision = s.signal_type === "entry" ? "ENTER" : s.signal_type === "exit" ? "EXIT" : s.signal_type === "hold" ? "HOLD" : "PASS";
            parts.push(`→ ${decision}`);
            const sigText = parts.join(" | ");
            const sigHash = sigText.slice(0, 80).replace(/\s+/g, "_");
            const isHighConv = (s.conviction != null && s.conviction >= 0.7) || s.signal_type === "entry" || s.signal_type === "exit";
            newLines.push({
              id: `sig-${key}-${sigHash}`, ts: now, bot, icon, color,
              text: sigText,
              type: "signal",
              highConviction: isHighConv,
            });
          }
        }
      }

      if (data.recent_trades && data.recent_trades.length > 0) {
        const latest = data.recent_trades[data.recent_trades.length - 1];
        const pnlColor = (latest.pnl_usd ?? 0) >= 0 ? "WIN" : "LOSS";
        newLines.push({
          id: `trade-${key}-${latest.symbol}-${latest.closed_at}`, ts: now, bot, icon, color,
          text: `TRADE ${pnlColor}: ${latest.symbol} ${latest.side?.toUpperCase()} | ${fmtPnl(latest.pnl_usd)} (${latest.pnl_pct >= 0 ? "+" : ""}${latest.pnl_pct.toFixed(2)}%) | ${latest.reason}`,
          type: "trade",
          highConviction: true,
        });
      }
    }

    if (summary?.groq?.regime) {
      const oracleDecision = summary.auto_trading ? "HOLD" : "PASS";
      const regimeParts = [`REGIME: ${summary.groq.regime}`, `Groq ${summary.groq.pct_used.toFixed(0)}% used`];
      if (summary.market_open != null) regimeParts.push(`Market ${summary.market_open ? "OPEN" : "CLOSED"}`);
      regimeParts.push(`→ ${oracleDecision}`);
      newLines.push({
        id: `regime-${summary.groq.regime}-${summary.groq.pct_used.toFixed(0)}-${oracleDecision}`,
        ts: now, bot: "Oracle", icon: "🔮", color: "#8b5cf6",
        text: regimeParts.join(" | "),
        type: "thinking",
      });
    }
    if (summary?.kill_switch_tripped) {
      newLines.push({
        id: `oracle-killswitch-${summary.system_health?.run_count}`, ts: now, bot: "Oracle", icon: "🔮", color: "#8b5cf6",
        text: "KILL SWITCH TRIPPED — All trading halted → PASS",
        type: "signal",
        highConviction: true,
      });
    }

    if (optState && optState.last_scan_results?.length > 0) {
      for (const scan of optState.last_scan_results.slice(0, 3)) {
        const parts = [`SCAN ${scan.symbol}`];
        if (scan.ivr != null) parts.push(`IVR=${scan.ivr.toFixed(0)}`);
        const decision = scan.is_squeeze ? "ENTER" : "PASS";
        parts.push(`→ ${decision}`);
        newLines.push({
          id: `opt-scan-${scan.symbol}-${scan.is_squeeze}-${optState.cycle_count}`,
          ts: now, bot: "Apex Predator", icon: "🎯", color: "#f59e0b",
          text: parts.join(" | "),
          type: scan.is_squeeze ? "signal" : "thinking",
          highConviction: scan.is_squeeze,
        });
      }
      if (optState.circuit_breaker_active) {
        newLines.push({
          id: `opt-circuit-${optState.cycle_count}`, ts: now, bot: "Apex Predator", icon: "🎯", color: "#f59e0b",
          text: "CIRCUIT BREAKER ACTIVE — Position sizing reduced → HOLD",
          type: "system",
        });
      }
    }

    if (fxState) {
      const fxDecision = fxState.news_blackout ? "PASS" : fxState.position_count > 0 ? "HOLD" : "PASS";
      const fxParts = [`USD BIAS: ${(fxState.usd_bias ?? "neutral").toUpperCase()}`];
      fxParts.push(`${fxState.position_count} pos`);
      fxParts.push(`C#${fxState.cycle_count}`);
      if (fxState.news_blackout) fxParts.push("NEWS BLACKOUT");
      fxParts.push(`→ ${fxDecision}`);
      newLines.push({
        id: `fx-bias-${fxState.usd_bias}-${fxState.cycle_count}-${fxState.position_count}`,
        ts: now, bot: "Navigator", icon: "🧭", color: "#10b981",
        text: fxParts.join(" | "),
        type: "thinking",
      });
      if (fxState.last_scan_results?.length) {
        for (const scan of fxState.last_scan_results.slice(0, 2)) {
          const scanParts = [`SIGNAL ${scan.pair}`];
          if (scan.rsi != null) scanParts.push(`RSI=${scan.rsi.toFixed(1)}`);
          if (scan.atr != null) scanParts.push(`ATR=${scan.atr.toFixed(4)}`);
          const scanDecision = scan.signal ? "ENTER" : "PASS";
          scanParts.push(`→ ${scanDecision}`);
          newLines.push({
            id: `fx-scan-${scan.pair}-${scan.signal}-${fxState.cycle_count}`,
            ts: now, bot: "Navigator", icon: "🧭", color: "#10b981",
            text: scanParts.join(" | "),
            type: scan.signal ? "signal" : "thinking",
            highConviction: !!scan.signal,
          });
        }
      }
    }

    if (newLines.length > 0) {
      setLines((prev) => {
        const existing = new Set(prev.map(l => l.id));
        const filtered = newLines.filter(l => !existing.has(l.id));
        if (filtered.length === 0) return prev;
        return [...filtered, ...prev].slice(0, 50);
      });
    }
  }, [djStatus, bbStatus, caStatus, optState, fxState, summary]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [lines.length]);

  return (
    <div className="flex-1 min-h-0 flex flex-col border rounded-lg overflow-hidden" style={{ borderColor: "rgba(255,255,255,0.06)", backgroundColor: "rgba(2,6,23,0.9)" }}>
      <div className="flex items-center justify-between px-3 py-2 border-b shrink-0" style={{ borderColor: "rgba(255,255,255,0.06)" }}>
        <div className="flex items-center gap-2">
          <motion.span
            className="text-[11px] uppercase font-black tracking-widest"
            style={{ color: "rgba(34,211,238,0.8)" }}
            animate={{ opacity: [0.6, 1, 0.6] }}
            transition={{ duration: 3, repeat: Infinity }}
          >
            Fleet Mind — Live Neural Feed
          </motion.span>
        </div>
        <span className="text-[10px] font-mono" style={{ color: "rgba(148,163,184,0.3)" }}>{lines.length} events</span>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-auto min-h-0 font-mono text-[11px] leading-relaxed">
        {lines.map((line, i) => (
          <motion.div
            key={line.id}
            initial={i < 3 ? { opacity: 0, x: -10 } : false}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.3 }}
            className="flex items-start gap-2 px-3 py-1.5 border-b"
            style={{
              borderColor: line.highConviction ? "rgba(250,204,21,0.15)" : "rgba(255,255,255,0.03)",
              backgroundColor: line.highConviction
                ? line.type === "trade" ? "rgba(250,204,21,0.08)" : "rgba(248,113,113,0.06)"
                : line.type === "trade" ? "rgba(250,204,21,0.04)" : line.type === "signal" ? "rgba(248,113,113,0.02)" : "transparent",
              boxShadow: line.highConviction && i < 3 ? "inset 0 0 20px rgba(250,204,21,0.06)" : "none",
            }}
            {...(line.highConviction && i < 3 ? {
              animate: {
                backgroundColor: [
                  line.type === "trade" ? "rgba(250,204,21,0.12)" : "rgba(248,113,113,0.1)",
                  line.type === "trade" ? "rgba(250,204,21,0.04)" : "rgba(248,113,113,0.03)",
                ],
              },
              transition: { duration: 1.5, ease: "easeOut" },
            } : {})}
          >
            <span style={{ fontSize: 12 }}>{line.icon}</span>
            <span className="shrink-0 font-bold" style={{ color: line.color, fontSize: 10, minWidth: 70 }}>
              {line.bot}
            </span>
            <span
              className="shrink-0 px-1 py-0.5 rounded text-[8px] font-black uppercase"
              style={{
                color: line.type === "trade" ? "#facc15" : line.type === "signal" ? "#f87171" : line.type === "thinking" ? "#818cf8" : "#64748b",
                backgroundColor: line.type === "trade" ? "rgba(250,204,21,0.1)" : line.type === "signal" ? "rgba(248,113,113,0.1)" : line.type === "thinking" ? "rgba(129,140,248,0.1)" : "rgba(100,116,139,0.1)",
              }}
            >
              {line.type}
            </span>
            {line.highConviction && (
              <span className="shrink-0 px-1 py-0.5 rounded text-[7px] font-black" style={{ color: "#facc15", backgroundColor: "rgba(250,204,21,0.15)", letterSpacing: "0.05em" }}>
                HIGH
              </span>
            )}
            <span className="flex-1 min-w-0 break-words" style={{ color: "rgba(203,213,225,0.8)" }}>
              {line.text}
            </span>
            <span className="shrink-0 text-[9px]" style={{ color: "rgba(148,163,184,0.25)" }}>
              {new Date(line.ts).toLocaleTimeString("en-US", { hour12: false })}
            </span>
          </motion.div>
        ))}
        {lines.length === 0 && (
          <div className="text-center py-8" style={{ color: "rgba(148,163,184,0.25)" }}>
            <div className="text-lg mb-1">⚡</div>
            <div className="text-[11px]">Waiting for neural feed data...</div>
            <div className="text-[9px] mt-1">Bot telemetry will appear here as bots cycle</div>
          </div>
        )}
      </div>
    </div>
  );
}

function EquitySidebar() {
  const { data: curve } = useEquityCurve(100);
  const { data: fleet } = useKrakenFleetSummary();
  const { data: summary } = useStatusSummary();
  const { data: optState } = useOptionsState();
  const { data: fxState } = useForexState();
  const { data: livePos } = useLivePositions();
  const { data: fxPos } = useForexPositions();
  const { data: djStatus } = useKrakenStatus("davy-jones");
  const { data: bbStatus } = useKrakenStatus("blackbeard");
  const { data: caStatus } = useKrakenStatus("calypso");

  const equityData = useMemo(() => {
    if (!curve?.snapshots?.length) return [];
    return curve.snapshots.map(s => s.total_equity);
  }, [curve]);

  const krakenBotCurves = useMemo(() => {
    const buildCurve = (status: typeof djStatus, startBalance: number) => {
      if (!status?.recent_trades?.length) return [startBalance, status?.total_equity_usd ?? startBalance];
      const sorted = [...status.recent_trades].sort(
        (a, b) => new Date(a.closed_at).getTime() - new Date(b.closed_at).getTime()
      );
      const points: number[] = [startBalance];
      let running = startBalance;
      for (const t of sorted) {
        running += (t.pnl_usd ?? 0);
        points.push(running);
      }
      return points;
    };
    return {
      dj: buildCurve(djStatus, djStatus?.paper_summary?.starting_balance_usd ?? 100_000),
      bb: buildCurve(bbStatus, bbStatus?.paper_summary?.starting_balance_usd ?? 100_000),
      ca: buildCurve(caStatus, caStatus?.paper_summary?.starting_balance_usd ?? 100_000),
    };
  }, [djStatus, bbStatus, caStatus]);

  const perBotSparklines = useMemo(() => {
    const result: Array<{ name: string; icon: string; color: string; data: number[] }> = [];
    if (curve?.snapshots?.length) {
      const snaps = curve.snapshots;
      result.push({ name: "Oracle", icon: "🔮", color: "#8b5cf6", data: snaps.map(s => s.alpaca_equity) });
    }
    result.push({ name: "Davy Jones", icon: "⚓", color: "#22d3ee", data: krakenBotCurves.dj });
    result.push({ name: "Blackbeard", icon: "🏴‍☠️", color: "#f97316", data: krakenBotCurves.bb });
    result.push({ name: "Calypso", icon: "🌊", color: "#a855f7", data: krakenBotCurves.ca });
    if (curve?.snapshots?.length) {
      const snaps = curve.snapshots;
      result.push({ name: "Apex", icon: "🎯", color: "#f59e0b", data: snaps.map(s => s.options_equity) });
      result.push({ name: "Navigator", icon: "🧭", color: "#10b981", data: snaps.map(s => s.forex_equity) });
    }
    return result;
  }, [curve, krakenBotCurves]);

  const allPositions = useMemo(() => {
    const pos: Array<{ symbol: string; bot: string; icon: string; pnlUsd: number; color: string }> = [];

    const krakenBots = [
      { data: djStatus, bot: "DJ", icon: "⚓", color: "#22d3ee" },
      { data: bbStatus, bot: "BB", icon: "🏴‍☠️", color: "#f97316" },
      { data: caStatus, bot: "CAL", icon: "🌊", color: "#a855f7" },
    ];
    for (const { data, bot, icon, color } of krakenBots) {
      if (!data?.open_positions) continue;
      for (const p of data.open_positions) {
        pos.push({ symbol: p.symbol, bot, icon, pnlUsd: p.unrealized_pnl_usd ?? 0, color });
      }
    }

    if (livePos?.positions) {
      for (const p of livePos.positions) {
        pos.push({ symbol: p.symbol, bot: "ORC", icon: "🔮", pnlUsd: p.unrealized_pl, color: "#8b5cf6" });
      }
    }

    if (fxPos?.positions) {
      for (const p of fxPos.positions) {
        pos.push({ symbol: p.pair.replace("_", "/"), bot: "NAV", icon: "🧭", pnlUsd: p.unrealized_pnl_usd, color: "#10b981" });
      }
    }

    return pos.sort((a, b) => Math.abs(b.pnlUsd) - Math.abs(a.pnlUsd)).slice(0, 12);
  }, [djStatus, bbStatus, caStatus, livePos, fxPos]);

  const botEquityRows = useMemo(() => {
    const rows: Array<{ name: string; icon: string; equity: number; pnl: number; color: string; vaultUsd?: number }> = [];
    const alpacaEq = summary?.portfolio_totals?.equity ?? 0;
    const alpacaStart = summary?.portfolio_totals?.initial_capital ?? 100_000;
    rows.push({ name: "Oracle", icon: "🔮", equity: alpacaEq, pnl: alpacaEq - alpacaStart, color: "#8b5cf6" });

    const krakenBots = [
      { data: djStatus, name: "Davy Jones", icon: "⚓", color: "#22d3ee" },
      { data: bbStatus, name: "Blackbeard", icon: "🏴‍☠️", color: "#f97316" },
      { data: caStatus, name: "Calypso", icon: "🌊", color: "#a855f7" },
    ];
    for (const { data, name, icon, color } of krakenBots) {
      if (!data) continue;
      const eq = data.total_equity_usd ?? 0;
      const start = data.paper_summary?.starting_balance_usd ?? 100_000;
      rows.push({ name, icon, equity: eq, pnl: eq - start, color });
    }

    if (optState) {
      rows.push({ name: "Apex", icon: "🎯", equity: optState.paper_equity ?? 0, pnl: optState.total_pnl ?? 0, color: "#f59e0b" });
    }
    if (fxState) {
      rows.push({
        name: "Navigator", icon: "🧭", equity: fxState.paper_equity ?? 0,
        pnl: fxState.total_pnl ?? 0, color: "#10b981",
        vaultUsd: fxState.vault_total_usd,
      });
    }
    return rows;
  }, [summary, djStatus, bbStatus, caStatus, optState, fxState]);

  const segments = useMemo(() => {
    const alpacaEq = summary?.portfolio_totals?.equity ?? 0;
    const krakenEq = fleet?.total_equity_usd ?? 0;
    const optEq = optState?.paper_equity ?? 0;
    const fxEq = fxState?.paper_equity ?? 0;
    const total = alpacaEq + krakenEq + optEq + fxEq;
    if (total <= 0) return [];
    return [
      { label: "Stocks", pct: (alpacaEq / total) * 100, color: "#8b5cf6" },
      { label: "Crypto", pct: (krakenEq / total) * 100, color: "#22d3ee" },
      { label: "Options", pct: (optEq / total) * 100, color: "#f59e0b" },
      { label: "Forex", pct: (fxEq / total) * 100, color: "#10b981" },
    ].filter(s => s.pct > 0.5);
  }, [summary, fleet, optState, fxState]);

  return (
    <div className="w-72 shrink-0 flex flex-col gap-2 min-h-0 overflow-auto px-2">
      <div className="rounded-lg border p-3" style={{ borderColor: "rgba(255,255,255,0.06)", backgroundColor: "rgba(15,23,42,0.8)" }}>
        <div className="text-[9px] uppercase tracking-widest font-bold mb-2" style={{ color: "rgba(148,163,184,0.5)" }}>Fleet Equity Curve</div>
        <MiniSparkline data={equityData} color="#22d3ee" w={240} h={50} />
      </div>

      {perBotSparklines.length > 0 && (
        <div className="rounded-lg border p-3" style={{ borderColor: "rgba(255,255,255,0.06)", backgroundColor: "rgba(15,23,42,0.8)" }}>
          <div className="text-[9px] uppercase tracking-widest font-bold mb-2" style={{ color: "rgba(148,163,184,0.5)" }}>Per-Bot Equity</div>
          <div className="grid grid-cols-3 gap-1.5">
            {perBotSparklines.map(bot => (
              <div key={bot.name}>
                <div className="flex items-center gap-1 mb-0.5">
                  <span style={{ fontSize: 8 }}>{bot.icon}</span>
                  <span className="text-[7px] font-mono font-bold truncate" style={{ color: bot.color }}>{bot.name}</span>
                </div>
                <MiniSparkline data={bot.data} color={bot.color} w={72} h={20} />
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="rounded-lg border p-3" style={{ borderColor: "rgba(255,255,255,0.06)", backgroundColor: "rgba(15,23,42,0.8)" }}>
        <div className="text-[9px] uppercase tracking-widest font-bold mb-2" style={{ color: "rgba(148,163,184,0.5)" }}>Bot Equity</div>
        <div className="space-y-1.5">
          {botEquityRows.map(r => (
            <div key={r.name} className="flex items-center gap-1.5 font-mono text-[10px]">
              <span style={{ fontSize: 10 }}>{r.icon}</span>
              <span className="truncate flex-1 font-semibold" style={{ color: r.color }}>{r.name}</span>
              <span className="text-white font-bold">{fmtUsd(r.equity)}</span>
              <span className={r.pnl >= 0 ? "text-green-400" : "text-red-400"} style={{ fontSize: 9 }}>
                {fmtPnl(r.pnl)}
              </span>
            </div>
          ))}
          {botEquityRows.some(r => r.vaultUsd != null && r.vaultUsd > 0) && (
            <div className="border-t pt-1 mt-1" style={{ borderColor: "rgba(255,255,255,0.04)" }}>
              {botEquityRows.filter(r => r.vaultUsd != null && r.vaultUsd > 0).map(r => (
                <div key={`vault-${r.name}`} className="flex items-center gap-1.5 font-mono text-[9px]" style={{ color: "rgba(148,163,184,0.5)" }}>
                  <span>{r.icon}</span>
                  <span>Vault:</span>
                  <span className="font-bold text-green-400">{fmtUsd(r.vaultUsd!)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {segments.length > 0 && (
        <div className="rounded-lg border p-3" style={{ borderColor: "rgba(255,255,255,0.06)", backgroundColor: "rgba(15,23,42,0.8)" }}>
          <div className="text-[9px] uppercase tracking-widest font-bold mb-2" style={{ color: "rgba(148,163,184,0.5)" }}>Capital Allocation</div>
          <div className="flex h-2 rounded-full overflow-hidden gap-px">
            {segments.map(s => (
              <div key={s.label} style={{ width: `${s.pct}%`, backgroundColor: s.color }} />
            ))}
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-2">
            {segments.map(s => (
              <div key={s.label} className="flex items-center gap-1">
                <div className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: s.color }} />
                <span className="text-[9px] font-mono" style={{ color: "rgba(148,163,184,0.6)" }}>{s.label} {s.pct.toFixed(0)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="rounded-lg border p-3 flex-1 min-h-0 flex flex-col" style={{ borderColor: "rgba(255,255,255,0.06)", backgroundColor: "rgba(15,23,42,0.8)" }}>
        <div className="text-[9px] uppercase tracking-widest font-bold mb-2" style={{ color: "rgba(148,163,184,0.5)" }}>
          Open Positions ({allPositions.length})
        </div>
        <div className="flex-1 overflow-auto min-h-0 space-y-1">
          {allPositions.map((p, i) => (
            <div key={`${p.bot}-${p.symbol}-${i}`} className="flex items-center gap-1.5 font-mono text-[10px]">
              <span style={{ fontSize: 10 }}>{p.icon}</span>
              <span className="font-semibold text-white truncate flex-1">{p.symbol}</span>
              <span className={p.pnlUsd >= 0 ? "text-green-400" : "text-red-400"} style={{ fontWeight: 600 }}>
                {fmtPnl(p.pnlUsd)}
              </span>
            </div>
          ))}
          {allPositions.length === 0 && (
            <div className="text-[10px] text-center py-3" style={{ color: "rgba(148,163,184,0.3)" }}>No open positions</div>
          )}
        </div>
      </div>
    </div>
  );
}

function TradeTickerFooter() {
  const { trades } = useRealFeed(30);

  if (trades.length === 0) return null;

  const doubled = [...trades, ...trades];

  return (
    <div className="relative overflow-hidden border-t py-1.5 shrink-0 trade-ticker-container" style={{ borderColor: "rgba(255,255,255,0.06)", backgroundColor: "rgba(15,23,42,0.95)" }}>
      <div className="absolute left-0 top-0 bottom-0 w-12 z-10" style={{ background: "linear-gradient(to right, rgba(15,23,42,0.95), transparent)" }} />
      <div className="absolute right-0 top-0 bottom-0 w-12 z-10" style={{ background: "linear-gradient(to left, rgba(15,23,42,0.95), transparent)" }} />
      <div className="flex whitespace-nowrap font-mono text-[11px] trade-ticker-scroll">
        {doubled.map((t, i) => {
          const isWin = (t.pnlUsd ?? 0) >= 0;
          return (
            <span key={`${t.id}-${i}`} className="inline-flex items-center gap-1.5 px-3">
              <span style={{ fontSize: 11 }}>{t.icon}</span>
              <span className="font-semibold text-white">{t.symbol}</span>
              <span className="font-bold" style={{ color: t.side === "LONG" || t.side === "long" || t.side === "buy" ? "#22d3ee" : "#f472b6", fontSize: 10 }}>
                {(t.side || "").toUpperCase() === "BUY" ? "LONG" : (t.side || "").toUpperCase() === "SELL" ? "SHORT" : (t.side || "LONG").toUpperCase()}
              </span>
              <span className={isWin ? "text-green-400" : "text-orange-400"} style={{ fontWeight: 700 }}>
                {fmtPnl(t.pnlUsd)}
              </span>
              <span style={{ color: "rgba(148,163,184,0.3)" }}>{timeAgo(t.date)}</span>
              <span style={{ color: "rgba(255,255,255,0.08)" }}>|</span>
            </span>
          );
        })}
      </div>
      <style>{`
        .trade-ticker-scroll {
          animation: tradeTickerScroll 30s linear infinite;
        }
        .trade-ticker-container:hover .trade-ticker-scroll {
          animation-play-state: paused;
        }
        @keyframes tradeTickerScroll {
          0% { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
      `}</style>
    </div>
  );
}

const PIPELINE_STAGES = [
  { key: "data", label: "Market Data", icon: "📡" },
  { key: "scan", label: "Signal Scan", icon: "🔍" },
  { key: "conviction", label: "Conviction", icon: "⚡" },
  { key: "risk", label: "Risk Check", icon: "🛡️" },
  { key: "execute", label: "Execute", icon: "🎯" },
];

function DecisionPipelineBar() {
  const { data: summary } = useStatusSummary();
  const { data: djStatus } = useKrakenStatus("davy-jones");
  const { data: bbStatus } = useKrakenStatus("blackbeard");
  const { data: caStatus } = useKrakenStatus("calypso");
  const { data: optState } = useOptionsState();
  const { data: fxState } = useForexState();

  const regime = summary?.groq?.regime ?? "---";
  const autoTrading = summary?.auto_trading ? "ON" : "OFF";
  const marketOpen = summary?.market_open ? "OPEN" : "CLOSED";
  const killSwitch = summary?.kill_switch_tripped ? "TRIPPED" : "SAFE";
  const groqPct = summary?.groq?.pct_used?.toFixed(0) ?? "0";

  const totalCycles = (djStatus?.cycle_count ?? 0) + (bbStatus?.cycle_count ?? 0) + (caStatus?.cycle_count ?? 0)
    + (optState?.cycle_count ?? 0) + (fxState?.cycle_count ?? 0) + (summary?.system_health?.run_count ?? 0);

  const allBotEntries = useMemo(() => [
    { data: djStatus, name: "DJ", icon: "⚓" },
    { data: bbStatus, name: "BB", icon: "🏴‍☠️" },
    { data: caStatus, name: "CAL", icon: "🌊" },
  ], [djStatus, bbStatus, caStatus]);

  const { activeStage, activeBot } = useMemo(() => {
    let maxStage = 0;
    let leadBot = "";

    for (const { data: bot, name } of allBotEntries) {
      if (!bot) continue;
      let botStage = 0;
      if (bot.recent_trades?.length) {
        const latest = bot.recent_trades[bot.recent_trades.length - 1];
        if (latest.closed_at && Date.now() - new Date(latest.closed_at).getTime() < 30000) {
          botStage = 4;
        }
      }
      if (botStage < 4) {
        if (bot.thinking_text?.includes("SIGNAL") || bot.thinking_text?.includes("Scalp")) {
          botStage = Math.max(botStage, 3);
        } else if (bot.thinking_text?.includes("Microstructure") || bot.thinking_text?.includes("RiskProfile")) {
          botStage = Math.max(botStage, 2);
        } else if (bot.signals?.some(s => s.signal_type && s.signal_type !== "watching")) {
          botStage = Math.max(botStage, 2);
        } else if (bot.cycle_count > 0) {
          botStage = Math.max(botStage, 1);
        }
      }
      if (botStage > maxStage) {
        maxStage = botStage;
        leadBot = name;
      }
    }

    if (optState?.last_scan_results?.some(r => r.is_squeeze)) {
      if (maxStage < 2) { maxStage = 2; leadBot = "APEX"; }
    }
    if (fxState?.last_scan_results?.some(r => r.signal)) {
      if (maxStage < 2) { maxStage = 2; leadBot = "NAV"; }
    }
    if (summary?.system_health?.run_count && summary.system_health.run_count > 0 && maxStage < 1) {
      maxStage = 1;
      leadBot = "ORC";
    }

    return { activeStage: maxStage, activeBot: leadBot };
  }, [allBotEntries, optState, fxState, summary]);

  return (
    <div className="flex items-center flex-wrap gap-x-3 gap-y-0.5 px-3 py-1 rounded-lg border shrink-0 font-mono text-[9px]" style={{
      borderColor: "rgba(255,255,255,0.06)",
      backgroundColor: "rgba(15,23,42,0.9)",
      color: "rgba(148,163,184,0.5)",
    }}>
      <div className="flex items-center gap-0.5">
        {PIPELINE_STAGES.map((stage, i) => {
          const isActive = i <= activeStage;
          const isCurrent = i === activeStage;
          return (
            <div key={stage.key} className="flex items-center">
              <div
                className="flex items-center gap-1 px-2 py-0.5 rounded-sm transition-all duration-500"
                style={{
                  backgroundColor: isActive ? "rgba(34,211,238,0.12)" : "rgba(255,255,255,0.02)",
                  borderWidth: 1,
                  borderStyle: "solid",
                  borderColor: isCurrent ? "rgba(34,211,238,0.4)" : isActive ? "rgba(34,211,238,0.1)" : "rgba(255,255,255,0.04)",
                  boxShadow: isCurrent ? "0 0 8px rgba(34,211,238,0.2)" : "none",
                }}
              >
                <span style={{ fontSize: 9 }}>{stage.icon}</span>
                <span style={{
                  color: isActive ? "#22d3ee" : "rgba(148,163,184,0.3)",
                  fontWeight: isCurrent ? 800 : 600,
                  fontSize: 9,
                }}>{stage.label}</span>
              </div>
              {i < PIPELINE_STAGES.length - 1 && (
                <span style={{ color: isActive ? "rgba(34,211,238,0.4)" : "rgba(255,255,255,0.06)", fontSize: 8, margin: "0 1px" }}>→</span>
              )}
            </div>
          );
        })}
      </div>

      {activeBot && (
        <>
          <span style={{ color: "rgba(255,255,255,0.06)" }}>│</span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ backgroundColor: "#22d3ee", boxShadow: "0 0 4px #22d3ee", animation: "pulse 1.5s ease-in-out infinite" }} />
            <span style={{ color: "#22d3ee", fontWeight: 800 }}>{activeBot}</span>
            <span style={{ color: "rgba(148,163,184,0.4)" }}>CYCLING</span>
          </span>
        </>
      )}
      <span style={{ color: "rgba(255,255,255,0.06)" }}>│</span>
      <span>REGIME: <span style={{ color: "#22d3ee", fontWeight: 700 }}>{regime}</span></span>
      <span style={{ color: "rgba(255,255,255,0.06)" }}>│</span>
      <span>AUTO: <span style={{ color: autoTrading === "ON" ? "#22c55e" : "#ef4444", fontWeight: 700 }}>{autoTrading}</span></span>
      <span style={{ color: "rgba(255,255,255,0.06)" }}>│</span>
      <span>MARKET: <span style={{ color: marketOpen === "OPEN" ? "#22c55e" : "#f59e0b", fontWeight: 700 }}>{marketOpen}</span></span>
      <span style={{ color: "rgba(255,255,255,0.06)" }}>│</span>
      <span>KILL SWITCH: <span style={{ color: killSwitch === "SAFE" ? "#22c55e" : "#ef4444", fontWeight: 700 }}>{killSwitch}</span></span>
      <span style={{ color: "rgba(255,255,255,0.06)" }}>│</span>
      <span>GROQ: <span style={{ color: "#a78bfa", fontWeight: 700 }}>{groqPct}%</span></span>
      <span style={{ color: "rgba(255,255,255,0.06)" }}>│</span>
      <span>FLEET CYCLES: <span style={{ color: "#22d3ee", fontWeight: 700 }}>{totalCycles}</span></span>
      <span className="ml-auto text-[9px]" style={{ color: "rgba(148,163,184,0.3)" }}>
        FLEET MIND v2 — {new Date().toISOString().slice(0, 10)}
      </span>
    </div>
  );
}

export default function StreamingScreenV2() {
  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden" style={{ backgroundColor: "#020617" }}>
      <style>{`
        @keyframes ping {
          75%, 100% { transform: scale(2); opacity: 0; }
        }
      `}</style>

      <HeroStrip />

      <div className="flex-1 min-h-0 flex gap-2 px-3 py-2">
        <BotTilesRow />

        <div className="flex-1 min-w-0 flex flex-col gap-1">
          <NeuralFeed />
          <DecisionPipelineBar />
        </div>

        <EquitySidebar />
      </div>

      <TradeTickerFooter />
    </div>
  );
}
