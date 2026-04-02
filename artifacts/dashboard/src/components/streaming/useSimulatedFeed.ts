import { useState, useEffect, useRef, useCallback } from "react";

export type SimulatedTrade = {
  id: number;
  bot: string;
  icon: string;
  symbol: string;
  pnlUsd: number;
  isWin: boolean;
  timestamp: number;
};

export type BotStats = {
  name: string;
  icon: string;
  totalPnl: number;
  wins: number;
  losses: number;
  trades: number;
  streak: number;
};

export type Achievement = {
  id: number;
  text: string;
  icon: string;
  color: string;
  timestamp: number;
};

const BOT_ROSTER = [
  { name: "Oracle", icon: "🔮", symbols: ["SPY", "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMZN", "GOOGL", "AMD", "QQQ"] },
  { name: "Davy Jones", icon: "⚓", symbols: ["BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD", "LINK/USD", "DOT/USD"] },
  { name: "Blackbeard", icon: "🏴‍☠️", symbols: ["BTC/USD", "SOL/USD", "NEAR/USD", "JUP/USD", "INJ/USD", "FET/USD"] },
  { name: "Calypso", icon: "🌊", symbols: ["ETH/USD", "MATIC/USD", "ARB/USD", "OP/USD", "ATOM/USD", "DOGE/USD"] },
  { name: "Apex Predator", icon: "🎯", symbols: ["SPY 450C", "QQQ 380P", "AAPL 200C", "TSLA 250P", "NVDA 900C"] },
  { name: "Navigator", icon: "🧭", symbols: ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "NZD/USD"] },
];

let nextId = 1;
let nextAchievementId = 1;

function generateTrade(): SimulatedTrade {
  const bot = BOT_ROSTER[Math.floor(Math.random() * BOT_ROSTER.length)];
  const symbol = bot.symbols[Math.floor(Math.random() * bot.symbols.length)];
  const isBigWin = Math.random() < 0.08;
  const isWin = isBigWin || Math.random() < 0.52;
  const pnlUsd = isWin
    ? isBigWin
      ? 50 + Math.random() * 300
      : 5 + Math.random() * 45
    : -(5 + Math.random() * 40);

  return {
    id: nextId++,
    bot: bot.name,
    icon: bot.icon,
    symbol,
    pnlUsd: Math.round(pnlUsd * 100) / 100,
    isWin,
    timestamp: Date.now(),
  };
}

const initialBotStats: Record<string, BotStats> = {};
BOT_ROSTER.forEach((b) => {
  initialBotStats[b.name] = { name: b.name, icon: b.icon, totalPnl: 0, wins: 0, losses: 0, trades: 0, streak: 0 };
});

export function useSimulatedFeed(maxTrades = 15) {
  const [trades, setTrades] = useState<SimulatedTrade[]>([]);
  const [explosion, setExplosion] = useState<SimulatedTrade | null>(null);
  const [wins, setWins] = useState(0);
  const [losses, setLosses] = useState(0);
  const [botStats, setBotStats] = useState<Record<string, BotStats>>(() => JSON.parse(JSON.stringify(initialBotStats)));
  const [achievements, setAchievements] = useState<Achievement[]>([]);
  const [tradesPerHour, setTradesPerHour] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const explosionTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cooldownRef = useRef(false);
  const tradeTimestamps = useRef<number[]>([]);
  const firstTradeRef = useRef(false);

  const clearExplosion = useCallback(() => {
    setExplosion(null);
    cooldownRef.current = false;
    if (explosionTimeoutRef.current) {
      clearTimeout(explosionTimeoutRef.current);
      explosionTimeoutRef.current = null;
    }
  }, []);

  const addAchievement = useCallback((text: string, icon: string, color: string) => {
    const a: Achievement = { id: nextAchievementId++, text, icon, color, timestamp: Date.now() };
    setAchievements((prev) => [a, ...prev].slice(0, 8));
  }, []);

  useEffect(() => {
    intervalRef.current = setInterval(() => {
      const trade = generateTrade();
      const now = Date.now();
      setTrades((prev) => [trade, ...prev].slice(0, maxTrades));

      tradeTimestamps.current = [...tradeTimestamps.current.filter((t) => now - t < 3600000), now];
      setTradesPerHour(tradeTimestamps.current.length);

      if (trade.isWin) {
        setWins((w) => w + 1);
      } else {
        setLosses((l) => l + 1);
      }

      setBotStats((prev) => {
        const s = { ...prev };
        const bot = { ...s[trade.bot] };
        bot.totalPnl += trade.pnlUsd;
        bot.trades += 1;
        if (trade.isWin) {
          bot.wins += 1;
          bot.streak = bot.streak >= 0 ? bot.streak + 1 : 1;
        } else {
          bot.losses += 1;
          bot.streak = bot.streak <= 0 ? bot.streak - 1 : -1;
        }
        s[trade.bot] = bot;

        if (bot.streak === 3) {
          addAchievement(`${trade.bot} is on a 3-win streak! 🔥`, "🔥", "#f59e0b");
        } else if (bot.streak === 5) {
          addAchievement(`${trade.bot} is UNSTOPPABLE — 5 wins in a row!`, "⚡", "#ef4444");
        } else if (bot.streak === 7) {
          addAchievement(`${trade.bot} GODLIKE — 7-win streak!`, "👑", "#facc15");
        }

        if (bot.trades === 1 && !firstTradeRef.current) {
          firstTradeRef.current = true;
          addAchievement(`FIRST BLOOD — ${trade.bot} opened today's first trade!`, "🩸", "#ef4444");
        }

        if (trade.pnlUsd > 100) {
          addAchievement(`BIG WIN — ${trade.bot} just banked $${trade.pnlUsd.toFixed(0)} on ${trade.symbol}!`, "💰", "#22c55e");
        }

        if (bot.trades === 10) {
          addAchievement(`${trade.bot} hit 10 trades — machine mode activated!`, "🤖", "#3b82f6");
        }

        if (bot.totalPnl > 500 && bot.totalPnl - trade.pnlUsd <= 500) {
          addAchievement(`${trade.bot} crossed $500 in total profit!`, "🏆", "#facc15");
        }

        return s;
      });

      if (trade.pnlUsd > 50 && !cooldownRef.current) {
        cooldownRef.current = true;
        setExplosion(trade);
        explosionTimeoutRef.current = setTimeout(() => {
          setExplosion(null);
          cooldownRef.current = false;
        }, 5000);
      }
    }, 3000 + Math.random() * 2000);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      if (explosionTimeoutRef.current) clearTimeout(explosionTimeoutRef.current);
    };
  }, [maxTrades, addAchievement]);

  return { trades, explosion, wins, losses, clearExplosion, botStats, achievements, tradesPerHour };
}
