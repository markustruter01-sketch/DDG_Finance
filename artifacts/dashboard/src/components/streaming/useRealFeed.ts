import { useMemo, useRef, useEffect } from "react";
import {
  useJournal, useOptionsState, useForexState,
  useLivePositions, useForexPositions, useForexTrades,
} from "@/hooks/use-trading";
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
};

export function useRealFeed(maxTrades = 20) {
  const journalQuery = useJournal();
  const journal = journalQuery.data;
  const { data: livePositions } = useLivePositions();
  const { data: fxPositions }   = useForexPositions();
  const { data: optState }      = useOptionsState();
  const { data: fxState }       = useForexState();
  const { data: fxTrades }      = useForexTrades();

  const trades: RealTrade[] = useMemo(() => {
    const all: RealTrade[] = [];

    if (journal?.trades) {
      for (const t of journal.trades) {
        if (t.status !== "Closed_Win" && t.status !== "Closed_Loss") continue;
        // Skip Kraken-sourced journal entries — those bots are retired
        if (t.source === "kraken" || t.trade_id?.startsWith("kraken-") || t.trade_id?.startsWith("KRK-")) continue;

        const isForex = t.asset_class === "forex" || t.source === "forex";
        const _oracle = getBotIdentity("oracle");
        const _fx     = getBotIdentity("forex_gump");
        const _id     = isForex ? _fx : _oracle;

        const cleaned = (t.ticker || "").replace("=X", "");
        const sym = /USD$/.test(cleaned) && !cleaned.includes("/")
          ? cleaned.replace(/USD$/, "/USD")
          : cleaned;

        const rawPnlUsd = t.pnl_usd ?? (t as Record<string, unknown>).realized_pnl as number | undefined ?? null;
        const pnlUsd    = rawPnlUsd ?? 0;
        const raw       = t as Record<string, unknown>;
        const sizeUsd: number | undefined =
          (raw.market_value  as number | undefined) ??
          (raw.cost_basis    as number | undefined) ??
          (typeof raw.qty === "number" && typeof raw.avg_entry_price === "number"
            ? Math.abs((raw.qty as number) * (raw.avg_entry_price as number))
            : undefined);

        all.push({
          id: t.trade_id,
          bot: _id.displayName,
          icon: _id.icon,
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

    if (fxTrades?.trades) {
      const _fxId = getBotIdentity("forex_gump");
      const existingSymbols = new Set(all.map(t => `${t.bot}-${t.symbol}-${t.date}`));
      for (const ft of fxTrades.trades) {
        if (ft.status !== "closed" && ft.status !== "Closed_Win" && ft.status !== "Closed_Loss") continue;
        if (!ft.exit_time) continue;
        const key = `Navigator-${ft.pair}-${ft.exit_time}`;
        if (existingSymbols.has(key)) continue;
        const pnlPct = ft.entry_price > 0 && ft.exit_price
          ? ((ft.exit_price - ft.entry_price) / ft.entry_price) * 100 * (ft.direction === "short" ? -1 : 1)
          : 0;
        const fxSize = ft.units > 0 && ft.entry_price > 0
          ? Math.abs(ft.units * ft.entry_price)
          : undefined;
        all.push({
          id: `fx-${ft.id}`,
          bot: _fxId.displayName,
          icon: _fxId.icon,
          symbol: ft.pair.replace("_", "/"),
          side: ft.direction || "",
          pnlPct,
          pnlUsd: ft.pnl_usd ?? 0,
          isWin: (ft.pnl_usd ?? 0) >= 0,
          date: ft.exit_time,
          sizeUsd: fxSize,
        });
      }
    }

    all.sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
    return all.slice(0, maxTrades);
  }, [journal, maxTrades, fxTrades]);

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
        totalPnl: 0,
        totalPnlPct: (jSummary.avg_pnl ?? 0) * (jSummary.total ?? 0),
        wins: jSummary.wins ?? 0,
        losses: jSummary.losses ?? 0,
        trades: jSummary.total ?? 0,
      });
    }
    if (fxState) {
      const _fx = getBotIdentity("forex_gump");
      stats.push({
        name: _fx.displayName, icon: _fx.icon,
        totalPnl: 0,
        totalPnlPct: 0,
        wins: fxState.total_wins ?? 0,
        losses: (fxState.total_trades ?? 0) - (fxState.total_wins ?? 0),
        trades: fxState.total_trades ?? 0,
      });
    }
    return stats.sort((a, b) => b.totalPnl - a.totalPnl || b.totalPnlPct - a.totalPnlPct);
  }, [journal, fxState]);

  const totalTrades = wins + losses;

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
    const _fx     = getBotIdentity("forex_gump");

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

    if (fxPositions?.positions) {
      for (const p of fxPositions.positions) {
        const pnlPct = p.size_usd > 0 ? (p.unrealized_pnl_usd / p.size_usd) * 100 : 0;
        all.push({
          id: `nav-${p.pair}`,
          bot: _fx.displayName, icon: _fx.icon,
          symbol: p.pair.replace("_", "/"),
          side: p.direction,
          pnlPct,
          pnlUsd: p.unrealized_pnl_usd,
          sizeUsd: p.size_usd,
        });
      }
    }

    return all.sort((a, b) => Math.abs(b.pnlUsd) - Math.abs(a.pnlUsd));
  }, [livePositions, fxPositions]);

  // suppress unused — optState kept for future use
  void optState;

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
