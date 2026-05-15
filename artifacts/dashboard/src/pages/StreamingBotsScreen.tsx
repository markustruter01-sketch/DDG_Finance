import { usePortfolio, useKrakenPerformance, useKrakenStatus, useForexState, useForexPositions, usePoseidonState, useKrakenCurrentState, useVault, useFleetEquity, useBotRegistry, type ForexPosition } from "@/hooks/use-trading";
import { FLEET_STARTING_CAPITAL } from "@/lib/dashboard-shared";
import { getFleetBotCount } from "@/lib/fleet-capital";
import { getBotColors } from "@/lib/bot-colors";
import { DDGBadge } from "@/components/DDGBadge";

function getExchangeLabel(exchange: string, assetClass: string): string {
  if (exchange === "oanda") return "Oanda · Forex";
  if (exchange === "kraken") return "Kraken · Crypto";
  const acLabel: Record<string, string> = {
    stocks: "Stocks",
    equity_etf: "ETFs",
    sector_etf: "Sector ETFs",
    defensive_etf: "Defensive ETFs",
    bond_etf: "Bond ETFs",
    commodity_etf: "Commodity ETFs",
  };
  return `Alpaca · ${acLabel[assetClass] ?? "Markets"}`;
}

const STARTING_BALANCE = 100_000;

function fmtEq(v: number) {
  return `$${Math.round(v).toLocaleString()}`;
}

function fmtPnl(v: number) {
  const abs = Math.abs(v);
  const sign = v >= 0 ? "+" : "−";
  if (abs >= 1_000) return `${sign}$${(abs / 1000).toFixed(1)}k`;
  return `${sign}$${abs.toFixed(0)}`;
}

interface OpenPosSummary {
  symbol: string;
  side: string;
  entry_price: number;
  unrealized_pnl_usd: number;
  size_usd?: number;
}

interface BotCardData {
  id: string;
  name: string;
  icon: string;
  exchange: string;
  color: string;
  equity: number | null;
  paused: boolean;
  stale?: boolean;
  heartbeatMinsAgo?: number;
  winCount: number;
  lossCount: number;
  openPositions: number;
  openPositionsList?: OpenPosSummary[];
}

function StatusBadge({ paused, stale, minsAgo }: { paused: boolean; stale?: boolean; minsAgo?: number }) {
  const isStale = stale && !paused;
  const label = paused ? "PAUSED" : isStale ? (minsAgo != null ? `STALE ${Math.round(minsAgo)}m` : "STALE") : "LIVE";
  const colors = paused
    ? { bg: "rgba(245,158,11,0.12)", border: "rgba(245,158,11,0.3)", dot: "#f59e0b", text: "#f59e0b", glow: "0 0 6px #f59e0b" }
    : isStale
    ? { bg: "rgba(100,116,139,0.12)", border: "rgba(100,116,139,0.3)", dot: "#64748b", text: "#64748b", glow: "none" }
    : { bg: "rgba(34,197,94,0.12)", border: "rgba(34,197,94,0.3)", dot: "#22c55e", text: "#22c55e", glow: "0 0 6px #22c55e" };
  return (
    <div className="flex items-center gap-1 px-2 py-0.5 rounded-sm shrink-0" style={{ background: colors.bg, border: `1px solid ${colors.border}` }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: colors.dot, boxShadow: colors.glow }} />
      <span className="text-[9px] font-black uppercase tracking-wider" style={{ color: colors.text }}>{label}</span>
    </div>
  );
}

function BotRow({ bot, rank, maxAbsPnl, isFirst }: { bot: BotCardData; rank: number; maxAbsPnl: number; isFirst: boolean }) {
  const pnl = bot.equity != null ? bot.equity - STARTING_BALANCE : null;
  const totalTrades = bot.winCount + bot.lossCount;
  const winRate = totalTrades > 0 ? (bot.winCount / totalTrades) * 100 : null;
  const isNegative = pnl != null && pnl < 0;
  const barPct = pnl != null && pnl !== 0 && maxAbsPnl > 0
    ? Math.min((Math.abs(pnl) / maxAbsPnl) * 78, 78)
    : 0;

  const pnlColor = pnl == null ? "#94a3b8" : pnl > 0 ? "#34d399" : pnl < 0 ? "#f87171" : "#64748b";

  return (
    <div
      className="flex items-center gap-3 w-full rounded-lg border px-4 transition-all"
      style={{ height: "100%", minHeight: 0,
        background: isFirst
          ? "rgba(249,115,22,0.06)"
          : bot.paused
          ? "rgba(245,158,11,0.03)"
          : "rgba(255,255,255,0.03)",
        border: isFirst
          ? "1px solid rgba(249,115,22,0.25)"
          : bot.paused
          ? "1px solid rgba(245,158,11,0.12)"
          : "1px solid rgba(255,255,255,0.06)",
        opacity: bot.paused ? 0.75 : 1,
      }}
    >
      {/* Rank */}
      <div className="text-xl font-black w-8 text-center shrink-0" style={{ color: isFirst ? "#f97316" : "#475569" }}>
        {isFirst ? "👑" : `#${rank}`}
      </div>

      {/* Bot identity */}
      <div className="flex items-center gap-3 w-56 shrink-0">
        <div
          className="w-9 h-9 rounded-full flex items-center justify-center shrink-0 text-lg"
          style={{ background: "rgba(0,0,0,0.3)", border: `1px solid ${bot.color}30` }}
        >
          {bot.icon}
        </div>
        <div className="min-w-0">
          <div className="font-bold text-sm leading-tight truncate" style={{ color: isFirst ? "#f97316" : "#e2e8f0" }}>
            {bot.name}
          </div>
          <div className="text-[10px] uppercase tracking-wider font-medium" style={{ color: "#475569" }}>
            {bot.exchange}
          </div>
        </div>
      </div>

      {/* Equity */}
      <div className="w-28 shrink-0 text-right">
        <div className="text-[9px] uppercase tracking-widest font-bold" style={{ color: "rgba(148,163,184,0.4)" }}>EQUITY</div>
        <div className="text-sm font-black font-mono text-white">
          {bot.equity != null ? fmtEq(bot.equity) : "—"}
        </div>
      </div>

      {/* Proportional bar */}
      <div className="flex-1 flex items-center relative h-full py-3 min-w-0">
        <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-px bg-white/5 rounded-full" />
        {barPct > 0 && (
          <div className="relative w-full h-7 flex items-center">
            <div
              className="h-5 rounded-sm"
              style={{
                width: `${barPct}%`,
                background: isNegative
                  ? "rgba(248,113,113,0.7)"
                  : `linear-gradient(90deg, ${bot.color}ff, ${bot.color}35)`,
                boxShadow: isFirst ? `0 0 16px ${bot.color}50` : "none",
              }}
            />
          </div>
        )}
      </div>

      {/* Stats badges */}
      <div className="flex items-center gap-2 shrink-0">
        {winRate != null && (
          <div className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-black/30 border border-white/5 text-slate-300">
            WR <span className="text-white">{winRate.toFixed(0)}%</span>
          </div>
        )}
        {bot.openPositions > 0 && (
          <div className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-black/30 border border-white/5 text-slate-300">
            OPN <span className="text-white">{bot.openPositions}</span>
          </div>
        )}
      </div>

      {/* P&L */}
      <div className="w-24 text-right shrink-0">
        <div className="text-lg font-mono font-black" style={{ color: pnlColor }}>
          {pnl != null ? fmtPnl(pnl) : "—"}
        </div>
      </div>

      {/* Status pill */}
      <div className="shrink-0 w-20 flex justify-end">
        <StatusBadge paused={bot.paused} stale={bot.stale} minsAgo={bot.heartbeatMinsAgo} />
      </div>
    </div>
  );
}

export default function StreamingBotsScreen() {
  const { data: portfolio } = usePortfolio();
  const { data: davyPerf } = useKrakenPerformance("davy-jones");
  const { data: davyStatus } = useKrakenStatus("davy-jones");
  const { data: bbPerf } = useKrakenPerformance("blackbeard");
  const { data: bbStatus } = useKrakenStatus("blackbeard");
  const { data: vault } = useVault();
  const { data: forexState } = useForexState();
  const { data: forexPosRaw } = useForexPositions();
  const { data: fleetEq } = useFleetEquity();
  const { data: registry } = useBotRegistry();
  const { data: poseidonState } = usePoseidonState();
  const { data: kcState } = useKrakenCurrentState();
  // ── Equity derivations ────────────────────────────────────────────────
  // Oracle: prefer fleet equity system (reflects any manual resets) over raw Alpaca portfolio
  const oracleEquity = fleetEq?.oracle?.equity ?? portfolio?.account?.equity ?? null;
  const oraclePositions = (portfolio?.positions ?? []).filter((p) => (p.market_value ?? 0) > 10);
  const oracleOpenList: OpenPosSummary[] = oraclePositions.map((p) => ({
    symbol: p.symbol,
    side: ((p.qty ?? 0) >= 0 ? "long" : "short") as "long" | "short",
    entry_price: p.avg_entry_price ?? 0,
    unrealized_pnl_usd: p.unrealized_pl ?? 0,
    size_usd: p.market_value ?? 0,
  }));

  const davyEquity = davyPerf?.current_equity ?? davyStatus?.total_equity_usd ?? fleetEq?.davy_jones?.equity ?? null;
  const bbEquity = bbPerf?.current_equity ?? bbStatus?.total_equity_usd ?? fleetEq?.blackbeard?.equity ?? null;
  // Paused bots: Kraken API returns null — fall back to fleet equity tracking
  const navEquity = fleetEq?.navigator?.equity ?? null;
  const rawForexPos: ForexPosition[] = Array.isArray(forexPosRaw)
    ? (forexPosRaw as ForexPosition[])
    : ((forexPosRaw as { positions?: ForexPosition[] } | null)?.positions ?? []);
  const navOpenList: OpenPosSummary[] = rawForexPos.map((p) => ({
    symbol: p.pair,
    side: (p.direction === "long" ? "long" : "short") as "long" | "short",
    entry_price: p.entry_price ?? 0,
    unrealized_pnl_usd: p.unrealized_pnl_usd ?? 0,
    size_usd: p.size_usd ?? 0,
  }));

  const poseidonEquity = poseidonState?.total_equity ?? null;
  const poseidonOpenList: OpenPosSummary[] = (poseidonState?.open_trades ?? []).map((t) => ({
    symbol: `${t.asset_a.replace("/USD", "")}/${t.asset_b.replace("/USD", "")}`,
    side: (t.leg_a_side === "long" ? "long" : "short") as "long" | "short",
    entry_price: t.leg_a_entry ?? 0,
    unrealized_pnl_usd: t.total_pnl ?? 0,
    size_usd: t.position_value ?? 0,
  }));

  const kcEquity = kcState?.total_equity ?? null;
  const kcOpenList: OpenPosSummary[] = (kcState?.open_positions_list ?? []).map((p) => ({
    symbol: p.symbol,
    side: (p.direction === "long" ? "long" : "short") as "long" | "short",
    entry_price: p.entry_price ?? 0,
    unrealized_pnl_usd: p.unrealised_pnl ?? 0,
    size_usd: p.position_value ?? 0,
  }));

  const usdBias = forexState?.usd_bias ?? "NEUTRAL";

  // ── Fleet totals ──────────────────────────────────────────────────────
  // Prefer fleet equity system's pre-computed total (reflects resets, all 9 bots).
  // Fall back to dynamic sum only if fleet equity hasn't loaded yet.
  const allEquities = [oracleEquity, davyEquity, bbEquity, navEquity, poseidonEquity, kcEquity].filter((e): e is number => e != null);
  const fleetTotalFromEquity = fleetEq?.fleet_total?.equity ?? null;
  const fleetTotal = fleetTotalFromEquity ?? (allEquities.length >= 6 ? allEquities.reduce((s, e) => s + e, 0) : null);
  // Baseline: use the fleet equity system's starting capital ($900k) when available
  const fleetStartingCapital = fleetEq?.fleet_total?.starting ?? (allEquities.length * STARTING_BALANCE);
  const fleetPnl = fleetTotal != null ? fleetTotal - fleetStartingCapital : null;
  const fleetPnlColor = fleetPnl == null ? "#94a3b8" : fleetPnl >= 0 ? "#34d399" : "#f87171";

  // ── Per-bot runtime data keyed by canonical registry ID ───────────────
  const botDataByRegistryId: Record<string, Partial<BotCardData>> = {
    oracle: {
      equity: oracleEquity,
      paused: false,
      winCount: 0,
      lossCount: 0,
      openPositions: oraclePositions.length,
      openPositionsList: oracleOpenList,
    },
    spy_qqq_trend: {
      equity: davyEquity,
      paused: davyStatus?.bot_paused ?? false,
      stale: fleetEq?.davy_jones?.stale ?? false,
      heartbeatMinsAgo: fleetEq?.davy_jones?.heartbeat_mins_ago,
      winCount: davyPerf?.win_count ?? 0,
      lossCount: davyPerf?.loss_count ?? 0,
      openPositions: davyStatus?.open_positions?.length ?? 0,
      openPositionsList: davyStatus?.open_positions,
    },
    jerome_macro: {
      equity: bbEquity,
      paused: bbStatus?.bot_paused ?? false,
      stale: fleetEq?.blackbeard?.stale ?? false,
      heartbeatMinsAgo: fleetEq?.blackbeard?.heartbeat_mins_ago,
      winCount: bbPerf?.win_count ?? 0,
      lossCount: bbPerf?.loss_count ?? 0,
      openPositions: bbStatus?.open_positions?.length ?? 0,
      openPositionsList: bbStatus?.open_positions,
    },
    forex_gump: {
      equity: navEquity,
      paused: forexState?.paused ?? false,
      winCount: forexState?.total_wins ?? 0,
      lossCount: (forexState?.total_trades ?? 0) - (forexState?.total_wins ?? 0),
      openPositions: rawForexPos.length,
      openPositionsList: navOpenList,
    },
    poseidon_momentum: {
      equity: poseidonEquity,
      paused: poseidonState?.paused ?? false,
      winCount: poseidonState?.total_wins ?? 0,
      lossCount: (poseidonState?.total_trades ?? 0) - (poseidonState?.total_wins ?? 0),
      openPositions: poseidonOpenList.length,
      openPositionsList: poseidonOpenList,
    },
    kraken_trend: {
      equity: kcEquity,
      paused: kcState?.paused ?? false,
      stale: fleetEq?.kraken_current?.stale ?? false,
      heartbeatMinsAgo: fleetEq?.kraken_current?.heartbeat_mins_ago,
      winCount: kcState?.total_wins ?? 0,
      lossCount: (kcState?.total_trades ?? 0) - (kcState?.total_wins ?? 0),
      openPositions: kcOpenList.length,
      openPositionsList: kcOpenList,
    },
  };

  // ── Assemble bots from registry ───────────────────────────────────────
  const bots: BotCardData[] = (registry?.bots ?? []).map((bot) => {
    const colors = getBotColors(bot.color);
    const data = botDataByRegistryId[bot.id] ?? {};
    return {
      id: bot.id,
      name: bot.display_name,
      icon: bot.icon,
      exchange: getExchangeLabel(bot.exchange, bot.asset_class),
      color: colors.hex,
      equity: null,
      paused: bot.status !== "active",
      winCount: 0,
      lossCount: 0,
      openPositions: 0,
      ...data,
    };
  });

  // ── Sort: live bots by P&L desc, paused bots at bottom ───────────────
  const getPnl = (b: BotCardData) => b.equity != null ? b.equity - STARTING_BALANCE : -Infinity;
  const liveBots = [...bots].filter((b) => !b.paused).sort((a, b) => getPnl(b) - getPnl(a));
  const pausedBots = [...bots].filter((b) => b.paused).sort((a, b) => getPnl(b) - getPnl(a));
  const sortedBots = [...liveBots, ...pausedBots];

  // ── Fleet stats ───────────────────────────────────────────────────────
  const allWins = bots.reduce((s, b) => s + b.winCount, 0);
  const allLosses = bots.reduce((s, b) => s + b.lossCount, 0);
  const allTrades = allWins + allLosses;
  const fleetWinRate = allTrades > 0 ? (allWins / allTrades) * 100 : null;
  const totalOpen = bots.reduce((s, b) => s + b.openPositions, 0);
  const liveCount = bots.filter((b) => !b.paused && !b.stale).length;
  const pausedCount = bots.filter((b) => b.paused).length;
  const maxAbsPnl = Math.max(...sortedBots.map((b) => (b.equity != null ? Math.abs(b.equity - STARTING_BALANCE) : 0)), 1);

  // First live bot with highest pnl
  const leaderBot = liveBots[0] ?? null;
  const firstPausedIdx = sortedBots.findIndex((b) => b.paused);

  return (
    <div
      className="h-full w-full flex flex-col relative overflow-hidden"
      style={{ background: "#020617", color: "#e2e8f0" }}
    >
      {/* ── LEADERBOARD LIST ───────────────────────────────────────────── */}
      <div className="flex-1 min-h-0 px-5 py-3 overflow-y-auto flex flex-col gap-1.5">
        {sortedBots.map((bot, idx) => {
          const isFirst = idx === 0 && !bot.paused;
          const rank = idx + 1;
          const showDivider = idx === firstPausedIdx && firstPausedIdx > 0;

          return (
            <div key={bot.id} className="flex flex-col shrink-0" style={{ flex: "1 0 0", minHeight: 52 }}>
              {showDivider && (
                <div className="flex items-center gap-3 mb-1 opacity-40 shrink-0">
                  <div className="h-px flex-1 bg-white/20" />
                  <div className="text-[10px] tracking-widest uppercase font-bold text-slate-400">Paused Bots</div>
                  <div className="h-px flex-1 bg-white/20" />
                </div>
              )}
              <BotRow bot={bot} rank={rank} maxAbsPnl={maxAbsPnl} isFirst={isFirst} />
            </div>
          );
        })}
      </div>

      {/* ── FOOTER ─────────────────────────────────────────────────────── */}
      <div
        className="shrink-0 flex items-center justify-between px-6 py-2.5"
        style={{ borderTop: "1px solid rgba(255,255,255,0.07)", background: "rgba(0,0,0,0.3)" }}
      >
        <div className="flex gap-5 text-xs font-semibold uppercase tracking-widest">
          <span className="text-slate-300">
            Equity: {fleetTotal != null ? `$${Math.round(fleetTotal).toLocaleString()}` : "—"}
          </span>
          <span style={{ color: fleetPnlColor }}>
            P&amp;L: {fleetPnl != null ? fmtPnl(fleetPnl) : "—"}
          </span>
          {fleetWinRate != null && (
            <span className="text-slate-300">Win Rate: {fleetWinRate.toFixed(1)}%</span>
          )}
        </div>
        <div className="flex items-center gap-3 text-xs font-semibold uppercase tracking-widest text-slate-400">
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-500" />
            {liveCount} Live
          </span>
          {pausedCount > 0 && (
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-amber-500" />
              {pausedCount} Paused
            </span>
          )}
          <span className="text-slate-600">|</span>
          <span>{totalOpen} Open Positions</span>
        </div>
      </div>

      <DDGBadge style={{ position: "absolute", bottom: 10, left: 10, zIndex: 50 }} />
    </div>
  );
}
