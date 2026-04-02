import { useMemo } from "react";
import {
  useJournal, useKrakenPerformance, useOptionsState, useForexState,
  useKrakenStatus, useLivePositions, useForexPositions,
} from "@/hooks/use-trading";

export type RealTrade = {
  id: string;
  bot: string;
  icon: string;
  symbol: string;
  pnlPct: number;
  isWin: boolean;
  date: string;
};

export type OpenPosition = {
  id: string;
  bot: string;
  icon: string;
  symbol: string;
  side: string;
  pnlPct: number;
  pnlUsd: number;
  sizeUsd: number;
};

export type BotStats = {
  name: string;
  icon: string;
  totalPnl: number;
  totalPnlPct: number;
  wins: number;
  losses: number;
  trades: number;
};

export function useRealFeed(maxTrades = 20) {
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

  const trades: RealTrade[] = useMemo(() => {
    if (!journal?.trades) return [];
    return journal.trades
      .filter((t) => t.status === "Closed_Win" || t.status === "Closed_Loss")
      .slice(0, maxTrades)
      .map((t) => {
        const isKraken = t.source === "kraken" || t.trade_id?.startsWith("kraken-") || t.trade_id?.startsWith("KRK-");
        const isForex = t.asset_class === "forex" || t.source === "forex";
        const isOptions = t.asset_class === "options" || t.source === "options";

        let bot = "Oracle";
        let icon = "🔮";
        if (isKraken) {
          const thesis = (t.original_thesis || "").toLowerCase();
          if (thesis.includes("blackbeard") || t.trade_id?.includes("blackbeard")) {
            bot = "Blackbeard"; icon = "🏴‍☠️";
          } else if (thesis.includes("calypso") || t.trade_id?.includes("calypso")) {
            bot = "Calypso"; icon = "🌊";
          } else {
            bot = "Davy Jones"; icon = "⚓";
          }
        } else if (isForex) {
          bot = "Navigator"; icon = "🧭";
        } else if (isOptions) {
          bot = "Apex Predator"; icon = "🎯";
        }

        const sym = (t.ticker || "").replace("USD", "/USD").replace("=X", "");

        return {
          id: t.trade_id,
          bot,
          icon,
          symbol: sym,
          pnlPct: t.pnl_percentage,
          isWin: t.status === "Closed_Win",
          date: t.date,
        };
      });
  }, [journal, maxTrades]);

  const krakenWins = useMemo(() =>
    [djPerf, bbPerf, caPerf].reduce((s, p) => s + (p.data?.win_count ?? 0), 0),
    [djPerf.data, bbPerf.data, caPerf.data]
  );

  const krakenLosses = useMemo(() =>
    [djPerf, bbPerf, caPerf].reduce((s, p) => s + (p.data?.loss_count ?? 0), 0),
    [djPerf.data, bbPerf.data, caPerf.data]
  );

  const wins = useMemo(() => {
    const alpacaWins = journal?.summary?.wins ?? 0;
    const optWins = optState?.total_wins ?? 0;
    const fxWins = fxState?.total_wins ?? 0;
    return alpacaWins + krakenWins + optWins + fxWins;
  }, [journal, krakenWins, optState, fxState]);

  const losses = useMemo(() => {
    const alpacaLosses = journal?.summary?.losses ?? 0;
    const optLosses = (optState?.total_trades ?? 0) - (optState?.total_wins ?? 0);
    const fxLosses = (fxState?.total_trades ?? 0) - (fxState?.total_wins ?? 0);
    return alpacaLosses + krakenLosses + optLosses + fxLosses;
  }, [journal, krakenLosses, optState, fxState]);

  const botStats: BotStats[] = useMemo(() => {
    const stats: BotStats[] = [];

    const jSummary = journal?.summary;
    if (jSummary) {
      stats.push({
        name: "Oracle", icon: "🔮",
        totalPnl: 0,
        totalPnlPct: (jSummary.avg_pnl ?? 0) * (jSummary.total ?? 0),
        wins: jSummary.wins ?? 0,
        losses: jSummary.losses ?? 0,
        trades: jSummary.total ?? 0,
      });
    }

    if (djPerf.data?.has_data) {
      stats.push({
        name: "Davy Jones", icon: "⚓",
        totalPnl: djPerf.data.total_pnl_usd ?? 0,
        totalPnlPct: djPerf.data.total_pnl_pct ?? 0,
        wins: djPerf.data.win_count, losses: djPerf.data.loss_count,
        trades: djPerf.data.total_trades,
      });
    }

    if (bbPerf.data?.has_data) {
      stats.push({
        name: "Blackbeard", icon: "🏴‍☠️",
        totalPnl: bbPerf.data.total_pnl_usd ?? 0,
        totalPnlPct: bbPerf.data.total_pnl_pct ?? 0,
        wins: bbPerf.data.win_count, losses: bbPerf.data.loss_count,
        trades: bbPerf.data.total_trades,
      });
    }

    if (caPerf.data?.has_data) {
      stats.push({
        name: "Calypso", icon: "🌊",
        totalPnl: caPerf.data.total_pnl_usd ?? 0,
        totalPnlPct: caPerf.data.total_pnl_pct ?? 0,
        wins: caPerf.data.win_count, losses: caPerf.data.loss_count,
        trades: caPerf.data.total_trades,
      });
    }

    if (optState) {
      stats.push({
        name: "Apex Predator", icon: "🎯",
        totalPnl: 0,
        totalPnlPct: 0,
        wins: optState.total_wins ?? 0,
        losses: (optState.total_trades ?? 0) - (optState.total_wins ?? 0),
        trades: optState.total_trades ?? 0,
      });
    }

    if (fxState) {
      stats.push({
        name: "Navigator", icon: "🧭",
        totalPnl: 0,
        totalPnlPct: 0,
        wins: fxState.total_wins ?? 0,
        losses: (fxState.total_trades ?? 0) - (fxState.total_wins ?? 0),
        trades: fxState.total_trades ?? 0,
      });
    }

    return stats.sort((a, b) => b.totalPnl - a.totalPnl || b.totalPnlPct - a.totalPnlPct);
  }, [journal, djPerf.data, bbPerf.data, caPerf.data, optState, fxState]);

  const totalTrades = wins + losses;

  const openPositions: OpenPosition[] = useMemo(() => {
    const all: OpenPosition[] = [];

    const krakenBots: Array<{ data: typeof djStatus.data; bot: string; icon: string }> = [
      { data: djStatus.data, bot: "Davy Jones", icon: "⚓" },
      { data: bbStatus.data, bot: "Blackbeard", icon: "🏴‍☠️" },
      { data: caStatus.data, bot: "Calypso", icon: "🌊" },
    ];
    for (const { data, bot, icon } of krakenBots) {
      if (!data?.open_positions) continue;
      for (const p of data.open_positions) {
        const entry = p.entry_price ?? 0;
        const current = p.best_price ?? entry;
        const pnlPct = entry > 0
          ? ((current - entry) / entry) * 100 * (p.side === "short" ? -1 : 1)
          : 0;
        const pnlUsd = entry > 0 && p.size_usd
          ? (current - entry) / entry * p.size_usd * (p.side === "short" ? -1 : 1)
          : 0;
        all.push({
          id: `${bot}-${p.symbol}`,
          bot, icon,
          symbol: p.symbol,
          side: p.side,
          pnlPct,
          pnlUsd,
          sizeUsd: p.size_usd,
        });
      }
    }

    if (livePositions?.positions) {
      for (const p of livePositions.positions) {
        all.push({
          id: `oracle-${p.symbol}`,
          bot: "Oracle", icon: "🔮",
          symbol: p.symbol,
          side: p.side,
          pnlPct: (p.unrealized_plpc ?? 0) * 100,
          pnlUsd: p.unrealized_pl ?? 0,
          sizeUsd: Math.abs(p.market_value),
        });
      }
    }

    if (fxPositions?.positions) {
      for (const p of fxPositions.positions) {
        const pnlPct = p.size_usd > 0 ? (p.unrealized_pnl_usd / p.size_usd) * 100 : 0;
        all.push({
          id: `nav-${p.pair}`,
          bot: "Navigator", icon: "🧭",
          symbol: p.pair.replace("_", "/"),
          side: p.direction,
          pnlPct,
          pnlUsd: p.unrealized_pnl_usd,
          sizeUsd: p.size_usd,
        });
      }
    }

    return all.sort((a, b) => Math.abs(b.pnlUsd) - Math.abs(a.pnlUsd));
  }, [djStatus.data, bbStatus.data, caStatus.data, livePositions, fxPositions]);

  return { trades, wins, losses, botStats, totalTrades, openPositions };
}
