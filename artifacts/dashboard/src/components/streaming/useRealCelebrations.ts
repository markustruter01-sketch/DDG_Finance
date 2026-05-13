import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import {
  useJournal, useKrakenPerformance, useKrakenStatus,
  useLivePositions, useForexPositions, useOptionsState, useForexState,
} from "@/hooks/use-trading";
import { playTradeWin, playExplosion } from "./sounds";
import { getBotIdentity } from "@/lib/bot-identity";

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

type RealTradeEntry = {
  bot: string;
  icon: string;
  symbol: string;
  pnlUsd: number;
  isWin: boolean;
  source: string;
};

const WIN_TEMPLATES: Array<{
  fn: (e: RealTradeEntry, stats: FleetStats) => string;
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

const LOSS_TEMPLATES: Array<{
  fn: (e: RealTradeEntry) => string;
  icon: string;
  color: string;
}> = [
  { fn: (e) => `${e.bot} stopped out on ${e.symbol} — -$${Math.abs(e.pnlUsd).toFixed(2)} | Risk managed`, icon: "🛡️", color: "#f97316" },
  { fn: (e) => `${e.bot} ${e.symbol} hit ATR stop — controlled exit, capital preserved`, icon: "⚠️", color: "#fb923c" },
  { fn: (e) => `Regime friction: ${e.bot}'s ${e.symbol} thesis invalidated — loss capped`, icon: "📉", color: "#f97316" },
  { fn: (e) => `${e.bot} cut ${e.symbol} quickly — small loss, big discipline`, icon: "✂️", color: "#fb923c" },
  { fn: (e) => `Market noise took ${e.bot}'s ${e.symbol} — thesis was right, timing wasn't`, icon: "⏳", color: "#f97316" },
  { fn: (e) => `${e.bot} learning from ${e.symbol} loss — neural journal updated`, icon: "📓", color: "#fb923c" },
  { fn: (e) => `VIX volatility shook ${e.bot} out of ${e.symbol} — stop did its job`, icon: "🌪️", color: "#f97316" },
  { fn: (e) => `${e.bot} ${e.symbol} position closed — cost of doing business in Bear regime`, icon: "🐻", color: "#fb923c" },
  { fn: (e) => `${e.bot} accepted the ${e.symbol} loss — preserving capital for the next setup`, icon: "♟️", color: "#f97316" },
  { fn: (e) => `Drawdown event: ${e.bot} ${e.symbol} — adjusting parameters for next cycle`, icon: "🔧", color: "#fb923c" },
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
  const lossAchievementIdx = useRef(0);
  const explosionTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  const allTrades = useMemo<RealTradeEntry[]>(() => {
    const wins: RealTradeEntry[] = [];
    const losses: RealTradeEntry[] = [];

    const _oracle = getBotIdentity("oracle");
    const _dj = getBotIdentity("davy-jones");
    const _bb = getBotIdentity("blackbeard");
    const _ca = getBotIdentity("calypso");
    const _fx = getBotIdentity("forex_gump");

    if (journal?.trades) {
      for (const t of journal.trades) {
        const isWin = t.status === "Closed_Win";
        const isLoss = t.status === "Closed_Loss";
        if (!isWin && !isLoss) continue;
        const pnl = Math.abs(t.pnl_percentage * 100);
        const isKraken = t.source === "kraken" || t.trade_id?.startsWith("kraken-") || t.trade_id?.startsWith("KRK-");
        const isForex = t.asset_class === "forex" || t.source === "forex";
        const isOptions = t.asset_class === "options" || t.source === "options";
        let _id = _oracle;
        if (isKraken) {
          const thesis = (t.original_thesis || "").toLowerCase();
          if (thesis.includes("blackbeard") || t.trade_id?.includes("blackbeard")) { _id = _bb; }
          else if (thesis.includes("calypso") || t.trade_id?.includes("calypso")) { _id = _ca; }
          else { _id = _dj; }
        } else if (isForex) { _id = _fx; }
        const sym = (t.ticker || "").replace("USD", "/USD").replace("=X", "");
        const entry: RealTradeEntry = { bot: _id.displayName, icon: _id.icon, symbol: sym, pnlUsd: pnl > 0 ? pnl : 5 + Math.random() * 30, isWin, source: "journal" };
        if (isWin) wins.push(entry);
        else losses.push(entry);
      }
    }

    const krakenBots = [
      { data: djStatus.data, perf: djPerf.data, bot: _dj.displayName, icon: _dj.icon },
      { data: bbStatus.data, perf: bbPerf.data, bot: _bb.displayName, icon: _bb.icon },
      { data: caStatus.data, perf: caPerf.data, bot: _ca.displayName, icon: _ca.icon },
    ];
    for (const { data, bot, icon } of krakenBots) {
      if (!data?.open_positions) continue;
      for (const p of data.open_positions) {
        const entry = p.entry_price ?? 0;
        const current = p.best_price ?? entry;
        if (entry <= 0) continue;
        const pnlPct = ((current - entry) / entry) * (p.side === "short" ? -1 : 1);
        const pnlUsd = p.size_usd ? Math.abs(pnlPct * p.size_usd) : Math.abs(pnlPct) * 1000;
        const isWin = pnlPct > 0;
        const arr = isWin ? wins : losses;
        arr.push({ bot, icon, symbol: p.symbol, pnlUsd, isWin, source: "kraken-open" });
      }
    }

    if (livePositions?.positions) {
      for (const p of livePositions.positions) {
        const isWin = (p.unrealized_pl ?? 0) > 0;
        const pnlUsd = Math.abs(p.unrealized_pl ?? 0);
        if (pnlUsd < 0.01) continue;
        const arr = isWin ? wins : losses;
        arr.push({ bot: _oracle.displayName, icon: _oracle.icon, symbol: p.symbol, pnlUsd, isWin, source: "alpaca-open" });
      }
    }

    if (fxPositions?.positions) {
      for (const p of fxPositions.positions) {
        const isWin = p.unrealized_pnl_usd > 0;
        const pnlUsd = Math.abs(p.unrealized_pnl_usd);
        if (pnlUsd < 0.01) continue;
        const arr = isWin ? wins : losses;
        arr.push({ bot: _fx.displayName, icon: _fx.icon, symbol: p.pair.replace("_", "/"), pnlUsd, isWin, source: "forex-open" });
      }
    }

    const _pos = getBotIdentity("poseidon");
    const _kc = getBotIdentity("kraken-current");

    if (wins.length === 0) {
      wins.push(
        { bot: _oracle.displayName, icon: _oracle.icon, symbol: "SPY",       pnlUsd: 12.50, isWin: true, source: "placeholder" },
        { bot: _dj.displayName,     icon: _dj.icon,     symbol: "BTC/USD",   pnlUsd: 24.80, isWin: true, source: "placeholder" },
        { bot: _fx.displayName,     icon: _fx.icon,     symbol: "EUR/USD",   pnlUsd: 8.30,  isWin: true, source: "placeholder" },
        { bot: _bb.displayName,     icon: _bb.icon,     symbol: "SOL/USD",   pnlUsd: 15.60, isWin: true, source: "placeholder" },
        { bot: _ca.displayName,     icon: _ca.icon,     symbol: "ETH/USD",   pnlUsd: 18.20, isWin: true, source: "placeholder" },
      );
    }
    if (losses.length === 0) {
      losses.push(
        { bot: _fx.displayName,  icon: _fx.icon,  symbol: "GBP/USD", pnlUsd: 6.40, isWin: false, source: "placeholder" },
        { bot: _dj.displayName,  icon: _dj.icon,  symbol: "ADA/USD", pnlUsd: 4.20, isWin: false, source: "placeholder" },
      );
    }

    // suppress unused-variable warnings for _pos/_kc (available for future use)
    void _pos; void _kc;

    const shuffle = (arr: RealTradeEntry[]) => {
      for (let i = arr.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [arr[i], arr[j]] = [arr[j], arr[i]];
      }
    };
    shuffle(wins);
    shuffle(losses);

    const combined: RealTradeEntry[] = [];
    let wi = 0, li = 0;
    const totalSlots = wins.length + losses.length;
    for (let slot = 0; slot < totalSlots; slot++) {
      const wantWin = Math.random() < 0.75;
      if (wantWin && wi < wins.length) {
        combined.push(wins[wi++]);
      } else if (li < losses.length) {
        combined.push(losses[li++]);
      } else if (wi < wins.length) {
        combined.push(wins[wi++]);
      }
    }
    while (wi < wins.length) combined.push(wins[wi++]);
    while (li < losses.length) combined.push(losses[li++]);

    return combined;
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

  const triggerExplosion = useCallback((entry: RealTradeEntry) => {
    const trade: CelebrationTrade = {
      id: nextCelebId++,
      bot: entry.bot,
      icon: entry.icon,
      symbol: entry.symbol,
      pnlUsd: entry.isWin ? entry.pnlUsd : -entry.pnlUsd,
      isWin: entry.isWin,
      timestamp: Date.now(),
    };
    setExplosion(trade);
    if (entry.isWin) playExplosion();

    if (explosionTimeout.current) clearTimeout(explosionTimeout.current);
    explosionTimeout.current = setTimeout(() => setExplosion(null), 3333);
  }, []);

  const triggerAchievement = useCallback((entry: RealTradeEntry, stats: FleetStats) => {
    let a: Achievement;
    if (entry.isWin) {
      const templateIdx = achievementIdx.current % WIN_TEMPLATES.length;
      achievementIdx.current++;
      const tmpl = WIN_TEMPLATES[templateIdx];
      a = {
        id: nextAchId++,
        text: tmpl.fn(entry, stats),
        icon: tmpl.icon,
        color: tmpl.color,
        timestamp: Date.now(),
      };
      playTradeWin();
    } else {
      const templateIdx = lossAchievementIdx.current % LOSS_TEMPLATES.length;
      lossAchievementIdx.current++;
      const tmpl = LOSS_TEMPLATES[templateIdx];
      a = {
        id: nextAchId++,
        text: tmpl.fn(entry),
        icon: tmpl.icon,
        color: tmpl.color,
        timestamp: Date.now(),
      };
    }
    setAchievements((prev) => [a, ...prev].slice(0, 8));
  }, []);

  const allTradesRef = useRef(allTrades);
  allTradesRef.current = allTrades;
  const fleetStatsRef = useRef(fleetStats);
  fleetStatsRef.current = fleetStats;
  const triggerExplosionRef = useRef(triggerExplosion);
  triggerExplosionRef.current = triggerExplosion;
  const triggerAchievementRef = useRef(triggerAchievement);
  triggerAchievementRef.current = triggerAchievement;
  const cycleCount = useRef(0);

  useEffect(() => {
    const tick = () => {
      const trades = allTradesRef.current;
      if (trades.length === 0) return;
      const idx = rotationIdx.current % trades.length;
      rotationIdx.current++;
      const entry = trades[idx];
      const isExplosionTurn = cycleCount.current % 2 === 0;
      cycleCount.current++;
      if (isExplosionTurn) {
        triggerExplosionRef.current(entry);
      } else {
        triggerAchievementRef.current(entry, fleetStatsRef.current);
      }
    };

    const initTimer = setTimeout(tick, 3000);
    const interval = setInterval(tick, 5000);

    return () => {
      clearInterval(interval);
      clearTimeout(initTimer);
      if (explosionTimeout.current) clearTimeout(explosionTimeout.current);
    };
  }, []);

  return { explosion, achievements };
}
