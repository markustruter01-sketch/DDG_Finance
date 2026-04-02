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

const BOT_ROSTER = [
  { name: "Oracle", icon: "🔮", symbols: ["SPY", "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMZN", "GOOGL", "AMD", "QQQ"] },
  { name: "Davy Jones", icon: "⚓", symbols: ["BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD", "LINK/USD", "DOT/USD"] },
  { name: "Blackbeard", icon: "🏴‍☠️", symbols: ["BTC/USD", "SOL/USD", "NEAR/USD", "JUP/USD", "INJ/USD", "FET/USD"] },
  { name: "Calypso", icon: "🌊", symbols: ["ETH/USD", "MATIC/USD", "ARB/USD", "OP/USD", "ATOM/USD", "DOGE/USD"] },
  { name: "Apex Predator", icon: "🎯", symbols: ["SPY 450C", "QQQ 380P", "AAPL 200C", "TSLA 250P", "NVDA 900C"] },
  { name: "Navigator", icon: "🧭", symbols: ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "NZD/USD"] },
];

let nextId = 1;

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

export function useSimulatedFeed(maxTrades = 20) {
  const [trades, setTrades] = useState<SimulatedTrade[]>([]);
  const [explosion, setExplosion] = useState<SimulatedTrade | null>(null);
  const [wins, setWins] = useState(0);
  const [losses, setLosses] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const explosionTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cooldownRef = useRef(false);

  const clearExplosion = useCallback(() => {
    setExplosion(null);
    cooldownRef.current = false;
    if (explosionTimeoutRef.current) {
      clearTimeout(explosionTimeoutRef.current);
      explosionTimeoutRef.current = null;
    }
  }, []);

  useEffect(() => {
    intervalRef.current = setInterval(() => {
      const trade = generateTrade();
      setTrades((prev) => [trade, ...prev].slice(0, maxTrades));
      if (trade.isWin) {
        setWins((w) => w + 1);
      } else {
        setLosses((l) => l + 1);
      }
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
  }, [maxTrades]);

  return { trades, explosion, wins, losses, clearExplosion };
}
