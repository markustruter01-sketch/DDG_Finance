import { useBotRegistry, useFleetEquity, useJournal, useLivePositions } from "./_shared/mockData";
import { getBotColors } from "./_shared/bot-colors";
import { getAttributedBotIdentity } from "./_shared/identity";
import { DDGBadge } from "./_shared/DDGBadge";

const STATIC_BOTS: Array<{ id: string; name: string; icon: string; exchange: string; asset_class: string; color: string; status: string }> = [
  { id: "oracle", name: getAttributedBotIdentity("oracle").displayName, icon: getAttributedBotIdentity("oracle").icon, exchange: "alpaca", asset_class: "stocks", color: "purple", status: "active" },
  { id: "spy_qqq_trend", name: getAttributedBotIdentity("spy_qqq_trend").displayName, icon: getAttributedBotIdentity("spy_qqq_trend").icon, exchange: "alpaca", asset_class: "equity_etf", color: "cyan", status: "active" },
  { id: "jerome_macro", name: getAttributedBotIdentity("jerome_macro").displayName, icon: getAttributedBotIdentity("jerome_macro").icon, exchange: "alpaca", asset_class: "macro_etf", color: "orange", status: "active" },
  // Retired identities stay out of the runtime fallback.
];

const PARAMS_UNAVAILABLE = "Not provided by the bot registry.";

function fmtEq(v: number) {
  return `$${Math.round(v).toLocaleString()}`;
}
function fmtPnl(v: number) {
  const abs = Math.abs(v);
  const sign = v >= 0 ? "+" : "−";
  if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(1)}k`;
  return `${sign}$${abs.toFixed(0)}`;
}
function fmtPct(pct: number | null | undefined) {
  if (pct == null) return "";
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
}
function fmtTime(iso: string | null | undefined) {
  if (!iso) return "--:--:--";
  try {
    return new Date(iso).toLocaleTimeString("en-US", { hour12: false });
  } catch {
    return "--:--:--";
  }
}
function getExchangeLabel(exchange: string, assetClass: string): string {
  if (exchange === "oanda") return "OANDA · FOREX";
  if (exchange === "kraken") return "KRAKEN · CRYPTO";
  const map: Record<string, string> = {
    stocks:        "STOCKS",
    equity_etf:    "ETFS",
    macro_etf:     "MACRO",
    sector_etf:    "SECTOR ETFS",
    defensive_etf: "DEFENSIVE ETFS",
    bond_etf:      "BOND ETFS",
    commodity_etf: "COMMODITY ETFS",
  };
  return `ALPACA · ${map[assetClass] ?? "MARKETS"}`;
}

interface BotCardData {
  id: string;
  name: string;
  icon: string;
  exchangeLabel: string;
  color: string;
  equity: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  paused: boolean;
  stale?: boolean;
  statusUnknown?: boolean;
  openPositionCount: number | null;
  openPositionSymbols: string[];
  recentTrades: Array<{ symbol: string; pnl_usd: number | null }>;
  recentTradesAttributionUnavailable?: boolean;
  recentTradesLoading?: boolean;
  recentTradesError?: boolean;
  paramsText: string;
}

function StatusBadge({ paused, stale, unknown }: { paused: boolean; stale?: boolean; unknown?: boolean }) {
  const isStale = stale && !paused;
  const label = paused ? "PAUSED" : isStale ? "STALE" : unknown ? "UNKNOWN" : "LIVE";
  const c = paused
    ? { bg: "rgba(245,158,11,0.15)", border: "rgba(245,158,11,0.4)", dot: "#f59e0b", text: "#f59e0b", glow: "0 0 5px #f59e0b44" }
    : isStale
    ? { bg: "rgba(100,116,139,0.12)", border: "rgba(100,116,139,0.3)", dot: "#64748b", text: "#64748b", glow: "none" }
    : unknown
    ? { bg: "rgba(245,158,11,0.12)", border: "rgba(245,158,11,0.35)", dot: "#f59e0b", text: "#f59e0b", glow: "none" }
    : { bg: "rgba(34,197,94,0.12)", border: "rgba(34,197,94,0.35)", dot: "#22c55e", text: "#22c55e", glow: "0 0 5px #22c55e44" };
  return (
    <div
      className="flex items-center gap-1 px-1.5 py-0.5 rounded shrink-0"
      style={{ background: c.bg, border: `1px solid ${c.border}` }}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: c.dot, boxShadow: c.glow }} />
      <span className="text-[8px] font-black uppercase tracking-wider" style={{ color: c.text }}>{label}</span>
    </div>
  );
}

function BotCard({ bot }: { bot: BotCardData }) {
  const pnlColor = bot.pnl == null ? "#64748b" : bot.pnl > 0 ? "#34d399" : bot.pnl < 0 ? "#f87171" : "#64748b";
  const cardBg = bot.paused ? "rgba(245,158,11,0.03)" : "rgba(255,255,255,0.025)";

  return (
    <div
      className="flex flex-col overflow-hidden rounded-md relative"
      style={{
        background: cardBg,
        border: "1px solid rgba(255,255,255,0.07)",
        borderLeft: `3px solid ${bot.color}`,
      }}
    >
      <div className="flex items-start justify-between px-2.5 pt-2 pb-1 shrink-0">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="text-base leading-none shrink-0">{bot.icon}</span>
          <div className="min-w-0">
            <div className="text-[11px] font-black text-white leading-tight truncate">{bot.name}</div>
            <div className="text-[8px] font-bold tracking-wider uppercase" style={{ color: "rgba(148,163,184,0.45)" }}>
              {bot.exchangeLabel}
            </div>
          </div>
        </div>
        <StatusBadge paused={bot.paused} stale={bot.stale} unknown={bot.statusUnknown} />
      </div>

      <div className="px-2.5 pb-1 shrink-0">
        <div className="text-[18px] font-black font-mono leading-tight" style={{ color: bot.paused ? "rgba(255,255,255,0.6)" : "#fff" }}>
          {bot.equity != null ? fmtEq(bot.equity) : "—"}
        </div>
        {bot.pnl != null && (
          <div className="text-[10px] font-mono font-bold" style={{ color: pnlColor }}>
            {bot.pnl >= 0 ? "+" : ""}${Math.abs(bot.pnl).toFixed(0)} ({fmtPct(bot.pnl_pct)})
          </div>
        )}
      </div>

      <div className="flex-1 flex flex-col overflow-hidden px-2.5 pb-1.5 gap-1.5 min-h-0">
        <div className="shrink-0">
          <div className="flex items-center justify-between mb-0.5">
            <span className="text-[8px] uppercase tracking-widest font-bold" style={{ color: "rgba(148,163,184,0.4)" }}>
              Open Positions
            </span>
            <span
              className="text-[9px] font-black font-mono px-1.5 py-px rounded"
              style={{
                 background: bot.openPositionCount != null && bot.openPositionCount > 0 ? `${bot.color}22` : "rgba(0,0,0,0.3)",
                 color: bot.openPositionCount != null && bot.openPositionCount > 0 ? bot.color : "#475569",
                 border: `1px solid ${bot.openPositionCount != null && bot.openPositionCount > 0 ? bot.color + "44" : "rgba(255,255,255,0.06)"}`,
              }}
            >
              {bot.openPositionCount == null ? "—" : bot.openPositionCount}
            </span>
          </div>
          {bot.openPositionSymbols.length > 0 ? (
            <div className="text-[8px] font-mono text-slate-400 leading-relaxed truncate">
              {bot.openPositionSymbols.join(", ")}
            </div>
          ) : (
            <div className="text-[8px] font-mono text-slate-400">
              {bot.openPositionCount === 0
                ? "None"
                : bot.openPositionCount == null
                  ? "Position data unavailable"
                  : "Position symbols unavailable"}
            </div>
          )}
        </div>

        <div className="shrink-0">
          <div className="text-[8px] uppercase tracking-widest font-bold mb-0.5" style={{ color: "rgba(148,163,184,0.4)" }}>
            Params
          </div>
          <div className="text-[8px] leading-relaxed" style={{ color: "rgba(148,163,184,0.5)" }}>
            {bot.paramsText}
          </div>
        </div>

        <div className="min-h-0 flex flex-col">
          <div className="text-[8px] uppercase tracking-widest font-bold mb-0.5 shrink-0" style={{ color: "rgba(148,163,184,0.4)" }}>
            Recent Trades
          </div>
          {bot.recentTrades.length === 0 ? (
            <div className="text-[8px] font-mono" style={{ color: "rgba(148,163,184,0.55)" }}>
              {bot.recentTradesLoading
                ? "Loading journal data"
                : bot.recentTradesError
                  ? "Journal data unavailable"
                  : bot.recentTradesAttributionUnavailable
                    ? "Journal has no bot ID; not assigned"
                    : "No recent trades returned for this bot"}
            </div>
          ) : (
            <div className="flex flex-col gap-px overflow-hidden">
              {bot.recentTrades.slice(0, 3).map((t, i) => (
                <div key={i} className="flex items-center justify-between">
                  <span className="text-[9px] font-mono font-bold text-slate-300">{t.symbol}</span>
                   <span className="text-[9px] font-mono font-bold" style={{ color: t.pnl_usd == null ? "#64748b" : t.pnl_usd >= 0 ? "#34d399" : "#f87171" }}>
                     {t.pnl_usd == null ? "—" : `${t.pnl_usd >= 0 ? "+" : ""}$${Math.abs(t.pnl_usd).toFixed(0)}`}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div
        className="shrink-0 flex items-center justify-between px-2.5 py-1"
        style={{ borderTop: "1px solid rgba(255,255,255,0.05)", background: "rgba(0,0,0,0.2)" }}
      >
        <span className="text-[7px] uppercase tracking-widest font-bold" style={{ color: "rgba(148,163,184,0.2)" }}>
          Live
        </span>
        <div className="flex items-center gap-1">
          {["1W", "1M"].map((tf) => (
            <span
              key={tf}
              className="text-[7px] font-mono px-1 py-px rounded"
              style={{ color: "rgba(148,163,184,0.2)", border: "1px solid rgba(255,255,255,0.05)" }}
            >
              {tf}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function StreamingBotsScreen() {
  const { data: livePositions } = useLivePositions();
  const { data: fleetEq } = useFleetEquity();
  const { data: registry } = useBotRegistry();
  const journalQuery = useJournal();
  const { data: journal } = journalQuery;

  const oraclePositionData = livePositions?.positions_by_bot?.oracle;
  const spyPositionData = livePositions?.positions_by_bot?.spy_qqq_trend;
  const jeromePositionData = livePositions?.positions_by_bot?.jerome_macro;
  const closedJournalTrades = (journal?.trades ?? [])
    .filter((trade) => trade.status === "Closed_Win" || trade.status === "Closed_Loss");
  const journalHasUnattributedTrades = closedJournalTrades.some((trade) => !trade.bot_id?.trim());
  const recentTradesForBot = (botId: string) => closedJournalTrades
    .filter((trade) => trade.bot_id === botId)
    .slice(0, 3)
    .map((trade) => ({
      symbol: trade.ticker,
      pnl_usd: trade.pnl_usd ?? trade.realized_pnl ?? null,
    }));

  const fleetTotal   = fleetEq?.fleet_total?.equity ?? null;
  const fleetPnl     = fleetEq?.fleet_total?.pnl ?? null;
  const fleetPnlPct  = fleetEq?.fleet_total?.pnl_pct ?? null;
  const fleetPnlColor = fleetPnl == null ? "#94a3b8" : fleetPnl >= 0 ? "#34d399" : "#f87171";

  const botRuntimeByRegistryId: Record<string, Partial<BotCardData>> = {
    oracle: {
      equity:             fleetEq?.oracle?.equity ?? null,
      pnl:                fleetEq?.oracle?.pnl ?? null,
      pnl_pct:            fleetEq?.oracle?.pnl_pct ?? null,
      ...(fleetEq?.oracle?.paused != null ? { paused: fleetEq.oracle.paused } : {}),
      statusUnknown:      fleetEq?.oracle?.paused == null,
      openPositionCount:  oraclePositionData?.count ?? fleetEq?.oracle?.positions ?? null,
      openPositionSymbols: oraclePositionData?.positions.map((position) => position.symbol) ?? [],
      recentTrades: recentTradesForBot("oracle"),
      recentTradesAttributionUnavailable: journalHasUnattributedTrades,
      recentTradesLoading: journalQuery.isLoading,
      recentTradesError: journalQuery.isError,
    },
    spy_qqq_trend: {
      equity:             fleetEq?.spy_qqq_trend?.equity ?? null,
      pnl:                fleetEq?.spy_qqq_trend?.pnl ?? null,
      pnl_pct:            fleetEq?.spy_qqq_trend?.pnl_pct ?? null,
      ...(fleetEq?.spy_qqq_trend?.paused != null ? { paused: fleetEq.spy_qqq_trend.paused } : {}),
      statusUnknown:      fleetEq?.spy_qqq_trend?.paused == null,
      openPositionCount:  spyPositionData?.count ?? fleetEq?.spy_qqq_trend?.positions ?? null,
      openPositionSymbols: spyPositionData?.positions.map((position) => position.symbol) ?? [],
      recentTrades: recentTradesForBot("spy_qqq_trend"),
      recentTradesAttributionUnavailable: journalHasUnattributedTrades,
      recentTradesLoading: journalQuery.isLoading,
      recentTradesError: journalQuery.isError,
    },
    jerome_macro: {
      equity:             fleetEq?.jerome_macro?.equity ?? null,
      pnl:                fleetEq?.jerome_macro?.pnl ?? null,
      pnl_pct:            fleetEq?.jerome_macro?.pnl_pct ?? null,
      ...(fleetEq?.jerome_macro?.paused != null ? { paused: fleetEq.jerome_macro.paused } : {}),
      statusUnknown:      fleetEq?.jerome_macro?.paused == null,
      openPositionCount:  jeromePositionData?.count ?? fleetEq?.jerome_macro?.positions ?? null,
      openPositionSymbols: jeromePositionData?.positions.map((position) => position.symbol) ?? [],
      recentTrades: recentTradesForBot("jerome_macro"),
      recentTradesAttributionUnavailable: journalHasUnattributedTrades,
      recentTradesLoading: journalQuery.isLoading,
      recentTradesError: journalQuery.isError,
    },
    // Retired identities stay out of the runtime map.
  };

  const rawBotSource = registry?.bots ?? STATIC_BOTS;
  const supportedBotIds = Object.keys(botRuntimeByRegistryId);
  // Keep retired or unknown registry identities out of the pre-load fallback.
  const botSource = rawBotSource.filter((b: { id: string }) => {
    if (!supportedBotIds.includes(b.id)) return false;
    if (!fleetEq) return true;
    const eq = (fleetEq as unknown as Record<string, { stale?: boolean } | undefined>)[b.id];
    return eq != null && !eq.stale;
  });
  const bots: BotCardData[] = botSource.map((bot) => {
    const colors = getBotColors(bot.color);
    const runtime = botRuntimeByRegistryId[bot.id] ?? {};
    const identity = getAttributedBotIdentity(bot.id);
    return {
      id:                 bot.id,
      name:               identity.displayName,
      icon:               identity.icon,
      exchangeLabel:      getExchangeLabel(bot.exchange, bot.asset_class),
      color:              colors.hex,
      equity:             null,
      pnl:                null,
      pnl_pct:            null,
      paused:             bot.status !== "active",
      openPositionCount:  null,
      openPositionSymbols: [],
      recentTrades:       [],
      paramsText:         PARAMS_UNAVAILABLE,
      ...runtime,
    };
  });

  const sortedForLadder = [...bots].sort((a, b) => {
    const pa = a.pnl ?? -Infinity;
    const pb = b.pnl ?? -Infinity;
    return pb - pa;
  });

  const liveCount  = bots.every((b) => !b.statusUnknown)
    ? bots.filter((b) => !b.paused && !b.stale).length
    : null;
  const totalOpen  = bots.every((b) => b.openPositionCount != null)
    ? bots.reduce((s, b) => s + b.openPositionCount!, 0)
    : null;
  const liveFeedTrades = closedJournalTrades.slice(0, 15);

  return (
    <div className="stream-screen stream-screen-bots h-full w-full flex overflow-hidden" style={{ background: "#020617", color: "#e2e8f0" }}>
      {/* ── LEFT SIDEBAR ── */}
      <div
        className="flex flex-col shrink-0 overflow-hidden"
        style={{ width: 172, background: "#080e1a", borderRight: "1px solid rgba(255,255,255,0.06)" }}
      >
        {/* Fleet Overview */}
        <div className="px-3 pt-3 pb-2.5 shrink-0" style={{ borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
          <div className="text-[8px] uppercase tracking-widest font-bold mb-1.5" style={{ color: "rgba(148,163,184,0.35)" }}>
            Fleet Overview
          </div>
          <div className="text-[22px] font-black font-mono leading-tight text-white">
            {fleetTotal != null ? fmtEq(fleetTotal) : "—"}
          </div>
          {fleetPnl != null && (
            <div className="text-[10px] font-mono font-bold mt-0.5" style={{ color: fleetPnlColor }}>
              {fleetPnl >= 0 ? "+" : ""}${Math.abs(fleetPnl).toFixed(0)} ({fmtPct(fleetPnlPct)})
            </div>
          )}
          <div className="flex gap-1.5 mt-2">
            <div
              className="flex-1 rounded px-1.5 py-1"
              style={{ background: "rgba(0,0,0,0.3)", border: "1px solid rgba(255,255,255,0.06)" }}
            >
              <div className="text-[7px] uppercase tracking-wider font-bold" style={{ color: "rgba(148,163,184,0.35)" }}>
                Active Bots
              </div>
              <div className="text-[13px] font-black font-mono text-white">{liveCount == null ? `—/${bots.length}` : `${liveCount}/${bots.length}`}</div>
            </div>
            <div
              className="flex-1 rounded px-1.5 py-1"
              style={{ background: "rgba(0,0,0,0.3)", border: "1px solid rgba(255,255,255,0.06)" }}
            >
              <div className="text-[7px] uppercase tracking-wider font-bold" style={{ color: "rgba(148,163,184,0.35)" }}>
                Open Pos
              </div>
              <div className="text-[13px] font-black font-mono text-white">{totalOpen == null ? "—" : totalOpen}</div>
            </div>
          </div>
        </div>

        {/* PNL Ladder */}
        <div className="px-3 py-2 shrink-0" style={{ borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
          <div className="text-[8px] uppercase tracking-widest font-bold mb-1.5" style={{ color: "rgba(148,163,184,0.35)" }}>
            PNL Ladder
          </div>
          <div className="flex flex-col gap-0.5">
            {sortedForLadder.map((bot) => {
              const p = bot.pnl ?? null;
              const pColor = p == null || p === 0 ? "#475569" : p > 0 ? "#34d399" : "#f87171";
              return (
                <div key={bot.id} className="flex items-center justify-between gap-1">
                  <div className="flex items-center gap-1 min-w-0">
                    <div className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: bot.color }} />
                    <span className="text-[8px] font-medium truncate" style={{ color: "rgba(148,163,184,0.6)", maxWidth: 80 }}>
                      {bot.name}
                    </span>
                  </div>
                  <span className="text-[8px] font-mono font-bold shrink-0" style={{ color: pColor }}>
                    {p != null ? fmtPnl(p) : "—"}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Live Feed */}
        <div className="flex flex-col flex-1 min-h-0 px-3 py-2">
          <div className="flex items-center justify-between mb-1.5 shrink-0">
            <span className="text-[8px] uppercase tracking-widest font-bold" style={{ color: "rgba(148,163,184,0.35)" }}>
              Live Feed
            </span>
            <span
              className="w-1.5 h-1.5 rounded-full"
              role="img"
              aria-label={journalQuery.isError ? "Journal request failed" : journal ? "Journal data available" : "Journal data loading"}
              title={journalQuery.isError ? "Journal request failed" : journal ? "Journal data available" : "Journal data loading"}
              style={{
                background: journalQuery.isError ? "#ef4444" : journal ? "#22c55e" : "#f59e0b",
                boxShadow: journal ? "0 0 5px #22c55e" : "none",
              }}
            />
          </div>
          <div className="flex-1 overflow-y-auto flex flex-col gap-2 min-h-0 pr-2">
            {liveFeedTrades.length === 0 ? (
              <div className="text-[8px] font-mono" style={{ color: "rgba(148,163,184,0.6)" }}>
                {journalQuery.isLoading
                  ? "Loading journal data"
                  : journalQuery.isError
                    ? "Journal data unavailable"
                    : "No recent trades returned"}
              </div>
            ) : (
              liveFeedTrades.map((t, i) => {
                const pnlUsd = t.pnl_usd ?? t.realized_pnl ?? null;
                const pColor = pnlUsd == null ? "#64748b" : pnlUsd >= 0 ? "#34d399" : "#f87171";
                const identity = getAttributedBotIdentity(t.bot_id);
                return (
                  <div key={t.trade_id ?? i} className="shrink-0">
                    <div className="text-[7px] font-mono" style={{ color: "rgba(148,163,184,0.25)" }}>
                      {fmtTime(t.date)}
                    </div>
                    <div className="flex items-center justify-between gap-1">
                      <span className="text-[9px] font-mono font-bold text-slate-300 truncate">{t.ticker}</span>
                      <span className="text-[9px] font-mono font-bold shrink-0" style={{ color: pColor }}>
                        {pnlUsd == null ? "—" : `${pnlUsd >= 0 ? "+" : ""}$${Math.abs(pnlUsd).toFixed(0)}`}
                      </span>
                    </div>
                    <div className="text-[7px] font-mono" style={{ color: "rgba(148,163,184,0.65)" }}>{identity.displayName}</div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>

      {/* ── BOT GRID — dynamic from botSource, no hardcoded count ── */}
      <div
        className="stream-bot-card-grid flex-1 overflow-y-auto p-2"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gridAutoRows: "1fr",
          gap: 6,
          alignContent: "start",
        }}
      >
        {bots.map((bot) => (
          <BotCard key={bot.id} bot={bot} />
        ))}
      </div>

      <DDGBadge style={{ position: "absolute", bottom: 8, left: 8, zIndex: 50 }} />
    </div>
  );
}
