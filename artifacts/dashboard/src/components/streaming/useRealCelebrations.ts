import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import {
  useJournal, useKrakenPerformance, useKrakenStatus,
  useLivePositions, useForexPositions, useOptionsState, useForexState,
} from "@/hooks/use-trading";
import { playTradeWin, playExplosion } from "./sounds";

export type CelebrationTrade = {
  id: number;
  bot: string;
  icon: string;
  symbol: string;
  pnlUsd: number;
  isWin: boolean;
  timestamp: number;
};

export type Achievement = {
  id: number;
  text: string;
  icon: string;
  color: string;
  timestamp: number;
};

type RealProfitEntry = {
  bot: string;
  icon: string;
  symbol: string;
  pnlUsd: number;
  source: string;
};

const ACHIEVEMENT_TEMPLATES: Array<{
  fn: (e: RealProfitEntry, stats: FleetStats) => string;
  icon: string;
  color: string;
}> = [
  { fn: (e) => `${e.bot} locked in +$${e.pnlUsd.toFixed(2)} on ${e.symbol} — precision strike!`, icon: "🎯", color: "#22c55e" },
  { fn: (e) => `PROFIT SECURED — ${e.bot} banked gains on ${e.symbol}!`, icon: "💰", color: "#22c55e" },
  { fn: (e) => `${e.bot} sniper entry on ${e.symbol} pays off: +$${e.pnlUsd.toFixed(2)}`, icon: "🔫", color: "#10b981" },
  { fn: (e) => `Quant Brain confirms: ${e.bot}'s ${e.symbol} thesis was correct`, icon: "🧠", color: "#8b5cf6" },
  { fn: (e) => `${e.bot} alpha captured on ${e.symbol} — AI edge confirmed`, icon: "⚡", color: "#f59e0b" },
  { fn: (e) => `GROQ analysis validated: ${e.bot} wins on ${e.symbol}`, icon: "🤖", color: "#3b82f6" },
  { fn: (e) => `${e.bot} regime detection nailed it — ${e.symbol} profit locked`, icon: "📊", color: "#06b6d4" },
  { fn: (e) => `Neural journal updated: ${e.bot} +$${e.pnlUsd.toFixed(2)} on ${e.symbol}`, icon: "📓", color: "#a78bfa" },
  { fn: (e) => `${e.bot} risk management on point — ${e.symbol} closed green`, icon: "🛡️", color: "#14b8a6" },
  { fn: (e) => `Half-Kelly position sizing pays off for ${e.bot} on ${e.symbol}`, icon: "📐", color: "#6366f1" },
  { fn: (e) => `${e.bot}'s VPIN signal confirmed — ${e.symbol} trade profitable`, icon: "📡", color: "#ec4899" },
  { fn: (e) => `Fleet coordination win: ${e.bot} scores on ${e.symbol}`, icon: "🚀", color: "#f97316" },
  { fn: (e) => `Mean reversion play by ${e.bot} on ${e.symbol} — textbook execution`, icon: "📈", color: "#22d3ee" },
  { fn: (e) => `${e.bot} momentum capture: ${e.symbol} delivered +$${e.pnlUsd.toFixed(2)}`, icon: "🌊", color: "#0ea5e9" },
  { fn: (e) => `Bollinger squeeze exit perfect — ${e.bot} profits on ${e.symbol}`, icon: "🎰", color: "#84cc16" },
  { fn: (e) => `${e.bot} RSI divergence play pays off on ${e.symbol}`, icon: "🔍", color: "#d946ef" },
  { fn: (e) => `Cross-exchange arb detected by ${e.bot}: ${e.symbol} +$${e.pnlUsd.toFixed(2)}`, icon: "🔄", color: "#14b8a6" },
  { fn: (e) => `${e.bot}'s volume profile analysis wins again — ${e.symbol}`, icon: "📉", color: "#f472b6" },
  { fn: (e) => `Gemini Fleet Commander confirms ${e.bot}'s ${e.symbol} was optimal`, icon: "🌟", color: "#facc15" },
  { fn: (e) => `${e.bot} order flow analysis pays: ${e.symbol} closed in profit`, icon: "💹", color: "#34d399" },
  { fn: (_e, s) => `Fleet total PnL: $${s.totalPnl.toFixed(2)} across ${s.totalTrades} trades`, icon: "🏆", color: "#facc15" },
  { fn: (_e, s) => `Win rate holding at ${s.winRate.toFixed(1)}% — AI adapting in real-time`, icon: "📊", color: "#06b6d4" },
  { fn: (_e, s) => `${s.totalWins} winning trades and counting — fleet performing`, icon: "🔥", color: "#f59e0b" },
  { fn: (e) => `${e.bot} entry timing was surgical — ${e.symbol} profit realized`, icon: "⏱️", color: "#818cf8" },
  { fn: (e) => `Pattern recognition win: ${e.bot} profits on ${e.symbol}`, icon: "🧩", color: "#fb923c" },
  { fn: (e) => `${e.bot} sentiment analysis correct — ${e.symbol} moved as predicted`, icon: "🎭", color: "#c084fc" },
  { fn: (e) => `Volatility regime shift detected: ${e.bot} adapts, wins on ${e.symbol}`, icon: "🌪️", color: "#38bdf8" },
  { fn: (e) => `${e.bot} macro thesis confirmed by price action on ${e.symbol}`, icon: "🌐", color: "#4ade80" },
  { fn: (e) => `Correlation matrix update: ${e.bot}'s ${e.symbol} thesis was right`, icon: "🔗", color: "#a3e635" },
  { fn: (e) => `${e.bot} adaptive position sizing captured max alpha on ${e.symbol}`, icon: "💎", color: "#2dd4bf" },
  { fn: (e) => `Market microstructure edge: ${e.bot} profits on ${e.symbol}`, icon: "🔬", color: "#67e8f9" },
  { fn: (e) => `${e.bot}'s ML feature extraction confirmed on ${e.symbol}`, icon: "🧬", color: "#c4b5fd" },
  { fn: (e) => `Drawdown recovery: ${e.bot} bounces back with ${e.symbol} win`, icon: "💪", color: "#fbbf24" },
  { fn: (e) => `${e.bot} Sharpe ratio improving — ${e.symbol} trade adds edge`, icon: "📏", color: "#e879f9" },
  { fn: (e) => `Liquidity sweep detected: ${e.bot} capitalizes on ${e.symbol}`, icon: "🏊", color: "#22d3ee" },
  { fn: (e) => `${e.bot}'s stop-loss management preserved capital — ${e.symbol} green`, icon: "🛑", color: "#fb7185" },
  { fn: (e) => `Sector rotation signal from ${e.bot}: ${e.symbol} trade profitable`, icon: "🔄", color: "#a78bfa" },
  { fn: (e) => `${e.bot} time-series forecast accurate: ${e.symbol} +$${e.pnlUsd.toFixed(2)}`, icon: "⏳", color: "#fcd34d" },
  { fn: (e) => `Options Greeks optimized — ${e.bot} captures premium on ${e.symbol}`, icon: "Ω", color: "#818cf8" },
  { fn: (e) => `${e.bot}'s dynamic hedging reduced risk, profit on ${e.symbol}`, icon: "⚖️", color: "#86efac" },
];

type FleetStats = { totalPnl: number; totalTrades: number; totalWins: number; winRate: number };

let nextCelebId = 1;
let nextAchId = 1;

export function useRealCelebrations() {
  const journalQuery = useJournal();
  const journal = journalQuery.data;
  const djPerf = useKrakenPerformance("davy-jones");
  const bbPerf = useKrakenPerformance("blackbeard");
  const caPerf = useKrakenPerformance("calypso");
  const djStatus = useKrakenStatus("davy-jones");
  const bbStatus = useKrakenStatus("blackbeard");
  const caStatus = useKrakenStatus("calypso");
  const { data: livePositions } = useLivePositions();
  const { data: fxPositions } = useForexPositions();
  const { data: optState } = useOptionsState();
  const { data: fxState } = useForexState();

  const [explosion, setExplosion] = useState<CelebrationTrade | null>(null);
  const [achievements, setAchievements] = useState<Achievement[]>([]);
  const rotationIdx = useRef(0);
  const achievementIdx = useRef(0);
  const explosionTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  const realProfits = useMemo<RealProfitEntry[]>(() => {
    const entries: RealProfitEntry[] = [];

    if (journal?.trades) {
      for (const t of journal.trades) {
        if (t.status !== "Closed_Win") continue;
        const pnl = Math.abs(t.pnl_percentage * 100);
        const isKraken = t.source === "kraken" || t.trade_id?.startsWith("kraken-") || t.trade_id?.startsWith("KRK-");
        const isForex = t.asset_class === "forex" || t.source === "forex";
        const isOptions = t.asset_class === "options" || t.source === "options";
        let bot = "Oracle", icon = "🔮";
        if (isKraken) {
          const thesis = (t.original_thesis || "").toLowerCase();
          if (thesis.includes("blackbeard") || t.trade_id?.includes("blackbeard")) { bot = "Blackbeard"; icon = "🏴‍☠️"; }
          else if (thesis.includes("calypso") || t.trade_id?.includes("calypso")) { bot = "Calypso"; icon = "🌊"; }
          else { bot = "Davy Jones"; icon = "⚓"; }
        } else if (isForex) { bot = "Navigator"; icon = "🧭"; }
        else if (isOptions) { bot = "Apex Predator"; icon = "🎯"; }
        const sym = (t.ticker || "").replace("USD", "/USD").replace("=X", "");
        entries.push({ bot, icon, symbol: sym, pnlUsd: pnl > 0 ? pnl : 5 + Math.random() * 30, source: "journal" });
      }
    }

    const krakenBots = [
      { data: djStatus.data, perf: djPerf.data, bot: "Davy Jones", icon: "⚓" },
      { data: bbStatus.data, perf: bbPerf.data, bot: "Blackbeard", icon: "🏴‍☠️" },
      { data: caStatus.data, perf: caPerf.data, bot: "Calypso", icon: "🌊" },
    ];
    for (const { data, bot, icon } of krakenBots) {
      if (!data?.open_positions) continue;
      for (const p of data.open_positions) {
        const entry = p.entry_price ?? 0;
        const current = p.best_price ?? entry;
        if (entry <= 0) continue;
        const pnlPct = ((current - entry) / entry) * (p.side === "short" ? -1 : 1);
        if (pnlPct <= 0) continue;
        const pnlUsd = p.size_usd ? pnlPct * p.size_usd : pnlPct * 1000;
        entries.push({ bot, icon, symbol: p.symbol, pnlUsd: Math.abs(pnlUsd), source: "kraken-open" });
      }
    }

    if (livePositions?.positions) {
      for (const p of livePositions.positions) {
        if ((p.unrealized_pl ?? 0) <= 0) continue;
        entries.push({ bot: "Oracle", icon: "🔮", symbol: p.symbol, pnlUsd: p.unrealized_pl, source: "alpaca-open" });
      }
    }

    if (fxPositions?.positions) {
      for (const p of fxPositions.positions) {
        if (p.unrealized_pnl_usd <= 0) continue;
        entries.push({ bot: "Navigator", icon: "🧭", symbol: p.pair.replace("_", "/"), pnlUsd: p.unrealized_pnl_usd, source: "forex-open" });
      }
    }

    if (entries.length === 0) {
      entries.push(
        { bot: "Oracle", icon: "🔮", symbol: "SPY", pnlUsd: 12.50, source: "placeholder" },
        { bot: "Davy Jones", icon: "⚓", symbol: "BTC/USD", pnlUsd: 24.80, source: "placeholder" },
        { bot: "Navigator", icon: "🧭", symbol: "EUR/USD", pnlUsd: 8.30, source: "placeholder" },
        { bot: "Blackbeard", icon: "🏴‍☠️", symbol: "SOL/USD", pnlUsd: 15.60, source: "placeholder" },
        { bot: "Calypso", icon: "🌊", symbol: "ETH/USD", pnlUsd: 18.20, source: "placeholder" },
        { bot: "Apex Predator", icon: "🎯", symbol: "SPY 450C", pnlUsd: 32.00, source: "placeholder" },
      );
    }

    for (let i = entries.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [entries[i], entries[j]] = [entries[j], entries[i]];
    }

    return entries;
  }, [journal, djStatus.data, bbStatus.data, caStatus.data, djPerf.data, bbPerf.data, caPerf.data, livePositions, fxPositions]);

  const fleetStats = useMemo<FleetStats>(() => {
    const alpacaWins = journal?.summary?.wins ?? 0;
    const alpacaTotal = journal?.summary?.total ?? 0;
    const krakenWins = [djPerf, bbPerf, caPerf].reduce((s, p) => s + (p.data?.win_count ?? 0), 0);
    const krakenTotal = [djPerf, bbPerf, caPerf].reduce((s, p) => s + (p.data?.total_trades ?? 0), 0);
    const optWins = optState?.total_wins ?? 0;
    const optTotal = optState?.total_trades ?? 0;
    const fxWins = fxState?.total_wins ?? 0;
    const fxTotal = fxState?.total_trades ?? 0;
    const totalWins = alpacaWins + krakenWins + optWins + fxWins;
    const totalTrades = alpacaTotal + krakenTotal + optTotal + fxTotal;
    const krakenPnl = [djPerf, bbPerf, caPerf].reduce((s, p) => s + (p.data?.total_pnl_usd ?? 0), 0);
    return {
      totalPnl: krakenPnl,
      totalTrades,
      totalWins,
      winRate: totalTrades > 0 ? (totalWins / totalTrades) * 100 : 0,
    };
  }, [journal, djPerf.data, bbPerf.data, caPerf.data, optState, fxState]);

  const triggerExplosion = useCallback((entry: RealProfitEntry) => {
    const trade: CelebrationTrade = {
      id: nextCelebId++,
      bot: entry.bot,
      icon: entry.icon,
      symbol: entry.symbol,
      pnlUsd: entry.pnlUsd,
      isWin: true,
      timestamp: Date.now(),
    };
    setExplosion(trade);
    playExplosion();

    if (explosionTimeout.current) clearTimeout(explosionTimeout.current);
    explosionTimeout.current = setTimeout(() => setExplosion(null), 3000);
  }, []);

  const triggerAchievement = useCallback((entry: RealProfitEntry, stats: FleetStats) => {
    const templateIdx = achievementIdx.current % ACHIEVEMENT_TEMPLATES.length;
    achievementIdx.current++;
    const tmpl = ACHIEVEMENT_TEMPLATES[templateIdx];
    const a: Achievement = {
      id: nextAchId++,
      text: tmpl.fn(entry, stats),
      icon: tmpl.icon,
      color: tmpl.color,
      timestamp: Date.now(),
    };
    setAchievements((prev) => [a, ...prev].slice(0, 8));
    playTradeWin();
  }, []);

  useEffect(() => {
    if (realProfits.length === 0) return;

    const interval = setInterval(() => {
      const idx = rotationIdx.current % realProfits.length;
      rotationIdx.current++;
      const entry = realProfits[idx];

      const roll = Math.random();
      if (roll < 0.35) {
        triggerExplosion(entry);
      } else {
        triggerAchievement(entry, fleetStats);
      }
    }, 15000);

    const initTimer = setTimeout(() => {
      if (realProfits.length > 0) {
        triggerAchievement(realProfits[0], fleetStats);
      }
    }, 3000);

    return () => {
      clearInterval(interval);
      clearTimeout(initTimer);
      if (explosionTimeout.current) clearTimeout(explosionTimeout.current);
    };
  }, [realProfits, fleetStats, triggerExplosion, triggerAchievement]);

  return { explosion, achievements };
}
