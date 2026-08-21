import { useMemo, useRef, useEffect } from "react";
import { useJournal, useLivePositions, useFleetEquity } from "@/hooks/use-trading";
import { emitTradePulse } from "./tradePulseEvents";
import { getBotIdentity } from "@/lib/bot-identity";

export type RealTrade = {
  id: string;
  bot: string;
  icon: string;
  symbol: string;
  side: string;
  pnlPct: number;
  pnlUsd: number;
  isWin: boolean;
  date: string;
  sizeUsd?: number;
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
  /** Server-computed win rate from /fleet/equity, range 0–1. Use instead of wins/trades arithmetic. */
  winRate?: number;
};

export function useRealFeed(maxTrades = 20) {
  const journalQuery = useJournal();
  const journal = journalQuery.data;
  const { data: livePositions } = useLivePositions();
  // Fleet equity provides server-computed win rates and P&L — no client arithmetic.
  const { data: fleetEq }       = useFleetEquity();

  const trades: RealTrade[] = useMemo(() => {
    const all: RealTrade[] = [];

    if (journal?.trades) {
      for (const t of journal.trades) {
        if (t.status !== "Closed_Win" && t.status !== "Closed_Loss") continue;
        // Skip retired bots: Kraken and forex_gump
        if (t.source === "kraken" || t.trade_id?.startsWith("kraken-") || t.trade_id?.startsWith("KRK-")) continue;
        if (t.asset_class === "forex" || t.source === "forex") continue;

        const _oracle = getBotIdentity("oracle");

        const sym = (t.ticker || "").replace("=X", "");

        const rawPnlUsd: number | null = (t.pnl_usd ?? (t as Record<string, unknown>).realized_pnl as number | undefined) ?? null;
        // Null P&L must NOT silently become $0/win — skip trades with no known dollar amount
        if (rawPnlUsd === null) continue;
        const pnlUsd = rawPnlUsd;
        const raw       = t as Record<string, unknown>;
        const sizeUsd: number | undefined =
          (raw.market_value  as number | undefined) ??
          (raw.cost_basis    as number | undefined) ??
          (typeof raw.qty === "number" && typeof raw.avg_entry_price === "number"
            ? Math.abs((raw.qty as number) * (raw.avg_entry_price as number))
            : undefined);

        all.push({
          id: t.trade_id,
          bot: _oracle.displayName,
          icon: _oracle.icon,
          symbol: sym,
          side: t.side || t.direction || "",
          pnlPct: t.pnl_percentage,
          pnlUsd,
          isWin: rawPnlUsd != null ? pnlUsd >= 0 : t.status === "Closed_Win",
          date: t.date,
          sizeUsd,
        });
      }
    }

    all.sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
    return all.slice(0, maxTrades);
  }, [journal, maxTrades]);

  // wins/losses from journal summary — server-computed, no client aggregation
  const wins   = journal?.summary?.wins ?? 0;
  const losses = journal?.summary?.losses ?? 0;

  const botStats: BotStats[] = useMemo(() => {
    const stats: BotStats[] = [];
    const _oracle = getBotIdentity("oracle");
    const jSummary = journal?.summary;
    if (jSummary) {
      stats.push({
        name: _oracle.displayName, icon: _oracle.icon,
        // Server-computed P&L from /fleet/equity — avg×total formula was wrong
        totalPnl:    fleetEq?.oracle?.pnl     ?? 0,
        totalPnlPct: fleetEq?.oracle?.pnl_pct ?? 0,
        wins:   jSummary.wins   ?? 0,
        losses: jSummary.losses ?? 0,
        trades: jSummary.total  ?? 0,
        // Server win rate from /fleet/equity — eliminates client wins/trades arithmetic
        winRate: fleetEq?.oracle?.win_rate ?? undefined,
      });
    }
    return stats.sort((a, b) => b.totalPnl - a.totalPnl || b.totalPnlPct - a.totalPnlPct);
  }, [journal, fleetEq]);

  const totalTrades = wins + losses;

  // Surface null P&L trades in dev tools so they don't silently disappear
  useEffect(() => {
    const summary = journal?.summary as Record<string, unknown> | undefined;
    const count = summary?.null_pnl_count as number | undefined;
    const ids   = summary?.null_pnl_trade_ids as string[] | undefined;
    if (count != null && count > 0) {
      console.warn(
        `[useRealFeed] ${count} closed trade(s) have null realized_pnl — skipped from display.`,
        "IDs:", ids ?? [],
      );
    }
  }, [journal]);

  const trades24h = useMemo(() => {
    const cutoff = Date.now() - 24 * 60 * 60 * 1000;
    let count = 0;
    for (const t of journal?.trades ?? []) {
      if (t.date && new Date(t.date).getTime() >= cutoff &&
          (t.status === "Closed_Win" || t.status === "Closed_Loss")) {
        count++;
      }
    }
    return count;
  }, [journal]);

  const openPositions: OpenPosition[] = useMemo(() => {
    const all: OpenPosition[] = [];
    const _oracle = getBotIdentity("oracle");

    if (livePositions?.positions) {
      for (const p of livePositions.positions) {
        all.push({
          id: `oracle-${p.symbol}`,
          bot: _oracle.displayName, icon: _oracle.icon,
          symbol: p.symbol,
          side: p.side,
          pnlPct: (p.unrealized_plpc ?? 0) * 100,
          pnlUsd: p.unrealized_pl ?? 0,
          sizeUsd: Math.abs(p.market_value),
        });
      }
    }

    return all.sort((a, b) => Math.abs(b.pnlUsd) - Math.abs(a.pnlUsd));
  }, [livePositions]);

  const seenTradeIds = useRef<Set<string>>(new Set());
  const initialized  = useRef(false);

  useEffect(() => {
    if (trades.length === 0) return;
    if (!initialized.current) {
      for (const t of trades) seenTradeIds.current.add(t.id);
      initialized.current = true;
      return;
    }
    for (const t of trades) {
      if (!seenTradeIds.current.has(t.id)) {
        seenTradeIds.current.add(t.id);
        emitTradePulse({ type: t.isWin ? "win" : "loss", botName: t.bot });
      }
    }
  }, [trades]);

  return { trades, wins, losses, botStats, totalTrades, trades24h, openPositions };
}
