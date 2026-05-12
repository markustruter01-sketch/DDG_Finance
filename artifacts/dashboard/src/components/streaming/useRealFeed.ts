import { useMemo, useRef, useEffect } from "react";
import {
  useJournal, useKrakenPerformance, useOptionsState, useForexState,
  useKrakenStatus, useLivePositions, useForexPositions, useForexTrades,
  usePoseidonState, useKrakenCurrentState,
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
  const apexStatus = useKrakenStatus("apex-predator");
  const { data: livePositions } = useLivePositions();
  const { data: fxPositions } = useForexPositions();
  const { data: optState } = useOptionsState();
  const { data: fxState } = useForexState();
  const { data: fxTrades } = useForexTrades();
  const { data: poseidonState } = usePoseidonState();
  const { data: kcState } = useKrakenCurrentState();

  const trades: RealTrade[] = useMemo(() => {
    const all: RealTrade[] = [];

    if (journal?.trades) {
      for (const t of journal.trades) {
        if (t.status !== "Closed_Win" && t.status !== "Closed_Loss") continue;
        const isKraken = t.source === "kraken" || t.trade_id?.startsWith("kraken-") || t.trade_id?.startsWith("KRK-");
        const isForex = t.asset_class === "forex" || t.source === "forex";
        const isOptions = t.asset_class === "options" || t.source === "options";

        let _id = getBotIdentity("oracle");
        if (isKraken) {
          const thesis = (t.original_thesis || "").toLowerCase();
          if (thesis.includes("blackbeard") || t.trade_id?.includes("blackbeard")) {
            _id = getBotIdentity("blackbeard");
          } else if (thesis.includes("calypso") || t.trade_id?.includes("calypso")) {
            _id = getBotIdentity("calypso");
          } else {
            _id = getBotIdentity("davy-jones");
          }
        } else if (isForex) {
          _id = getBotIdentity("forex_gump");
        } else if (isOptions) {
          _id = getBotIdentity("apex-predator");
        }
        const bot = _id.displayName;
        const icon = _id.icon;

        const cleaned = (t.ticker || "").replace("=X", "");
        const sym = /USD$/.test(cleaned) && !cleaned.includes("/")
          ? cleaned.replace(/USD$/, "/USD")
          : cleaned;

        const hasExplicitPnl = t.pnl_usd != null;
        // Skip Kraken journal entries with no pnl_usd — they're covered by the
        // Kraken status recent_trades path which always carries a proper dollar amount.
        if (isKraken && !hasExplicitPnl) continue;

        const pnlUsd = t.pnl_usd ?? 0;
        all.push({
          id: t.trade_id,
          bot,
          icon,
          symbol: sym,
          side: t.side || t.direction || "",
          pnlPct: t.pnl_percentage,
          pnlUsd,
          isWin: hasExplicitPnl ? pnlUsd >= 0 : t.status === "Closed_Win",
          date: t.date,
        });
      }
    }

    const _dj = getBotIdentity("davy-jones");
    const _bb = getBotIdentity("blackbeard");
    const _ca = getBotIdentity("calypso");
    const _ap = getBotIdentity("apex-predator");
    const krakenRecent: Array<{ data: typeof djStatus.data; bot: string; icon: string }> = [
      { data: djStatus.data,   bot: _dj.displayName, icon: _dj.icon },
      { data: bbStatus.data,   bot: _bb.displayName, icon: _bb.icon },
      { data: caStatus.data,   bot: _ca.displayName, icon: _ca.icon },
      { data: apexStatus.data, bot: _ap.displayName, icon: _ap.icon },
    ];
    const journalIds = new Set(all.map(t => t.id));
    for (const { data, bot, icon } of krakenRecent) {
      if (!data?.recent_trades) continue;
      for (const rt of data.recent_trades) {
        const id = `${bot}-${rt.symbol}-${rt.closed_at}`;
        if (journalIds.has(id)) continue;
        all.push({
          id,
          bot,
          icon,
          symbol: rt.symbol,
          side: rt.side || "",
          pnlPct: rt.pnl_pct,
          pnlUsd: rt.pnl_usd,
          isWin: rt.pnl_usd >= 0,
          date: rt.closed_at,
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
        });
      }
    }

    all.sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
    return all.slice(0, maxTrades);
  }, [journal, maxTrades, djStatus.data, bbStatus.data, caStatus.data, apexStatus.data, fxTrades]);

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

    const _oracle = getBotIdentity("oracle");
    const _dj = getBotIdentity("davy-jones");
    const _bb = getBotIdentity("blackbeard");
    const _ca = getBotIdentity("calypso");
    const _ap = getBotIdentity("apex-predator");
    const _fx = getBotIdentity("forex_gump");

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

    if (djPerf.data?.has_data) {
      stats.push({
        name: _dj.displayName, icon: _dj.icon,
        totalPnl: djPerf.data.total_pnl_usd ?? 0,
        totalPnlPct: djPerf.data.total_pnl_pct ?? 0,
        wins: djPerf.data.win_count, losses: djPerf.data.loss_count,
        trades: djPerf.data.total_trades,
      });
    }

    if (bbPerf.data?.has_data) {
      stats.push({
        name: _bb.displayName, icon: _bb.icon,
        totalPnl: bbPerf.data.total_pnl_usd ?? 0,
        totalPnlPct: bbPerf.data.total_pnl_pct ?? 0,
        wins: bbPerf.data.win_count, losses: bbPerf.data.loss_count,
        trades: bbPerf.data.total_trades,
      });
    }

    if (caPerf.data?.has_data) {
      stats.push({
        name: _ca.displayName, icon: _ca.icon,
        totalPnl: caPerf.data.total_pnl_usd ?? 0,
        totalPnlPct: caPerf.data.total_pnl_pct ?? 0,
        wins: caPerf.data.win_count, losses: caPerf.data.loss_count,
        trades: caPerf.data.total_trades,
      });
    }

    if (optState) {
      stats.push({
        name: _ap.displayName, icon: _ap.icon,
        totalPnl: 0,
        totalPnlPct: 0,
        wins: optState.total_wins ?? 0,
        losses: (optState.total_trades ?? 0) - (optState.total_wins ?? 0),
        trades: optState.total_trades ?? 0,
      });
    }

    if (fxState) {
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
  }, [journal, djPerf.data, bbPerf.data, caPerf.data, optState, fxState]);

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
    const krakenBotData = [djPerf.data, bbPerf.data, caPerf.data];
    for (const p of krakenBotData) {
      if (p?.has_data && p.trades_today) count += p.trades_today;
    }
    return count;
  }, [journal, djPerf.data, bbPerf.data, caPerf.data]);

  const openPositions: OpenPosition[] = useMemo(() => {
    const all: OpenPosition[] = [];

    const _dj = getBotIdentity("davy-jones");
    const _bb = getBotIdentity("blackbeard");
    const _ca = getBotIdentity("calypso");
    const _ap = getBotIdentity("apex-predator");
    const _oracle = getBotIdentity("oracle");
    const _fx = getBotIdentity("forex_gump");
    const _pos = getBotIdentity("poseidon");
    const _kc = getBotIdentity("kraken-current");

    const krakenBots: Array<{ data: typeof djStatus.data; bot: string; icon: string }> = [
      { data: djStatus.data,   bot: _dj.displayName, icon: _dj.icon },
      { data: bbStatus.data,   bot: _bb.displayName, icon: _bb.icon },
      { data: caStatus.data,   bot: _ca.displayName, icon: _ca.icon },
      { data: apexStatus.data, bot: _ap.displayName, icon: _ap.icon },
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

    if (poseidonState?.open_trades) {
      for (const t of poseidonState.open_trades) {
        const symbol = `${t.asset_a.replace("/USD", "")}/${t.asset_b.replace("/USD", "")}`;
        all.push({
          id: `poseidon-${t.pair_set_id}`,
          bot: _pos.displayName, icon: _pos.icon,
          symbol,
          side: t.direction,
          pnlPct: t.position_value > 0 ? (t.total_pnl / t.position_value) * 100 : 0,
          pnlUsd: t.total_pnl,
          sizeUsd: t.position_value,
        });
      }
    }

    if (kcState?.open_positions_list) {
      for (const p of kcState.open_positions_list) {
        all.push({
          id: `kc-${p.symbol}`,
          bot: _kc.displayName, icon: _kc.icon,
          symbol: p.symbol,
          side: p.direction,
          pnlPct: p.position_value > 0 ? (p.unrealised_pnl / p.position_value) * 100 : 0,
          pnlUsd: p.unrealised_pnl,
          sizeUsd: p.position_value,
        });
      }
    }

    return all.sort((a, b) => Math.abs(b.pnlUsd) - Math.abs(a.pnlUsd));
  }, [djStatus.data, bbStatus.data, caStatus.data, apexStatus.data, livePositions, fxPositions, poseidonState, kcState]);

  const seenTradeIds = useRef<Set<string>>(new Set());
  const initialized = useRef(false);

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
