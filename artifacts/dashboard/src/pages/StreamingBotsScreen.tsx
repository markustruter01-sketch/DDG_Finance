import {
  useLivePositions,
  useFleetEquity,
  useBotRegistry,
  useJournal,
  useStatusSummary,
} from "@/hooks/use-trading";
import { useMemo, useState } from "react";
import { getBotColors } from "@/lib/bot-colors";
import { formatBotLabel, useBotIdentity } from "@/lib/bot-identity";
import { DDGBadge } from "@/components/DDGBadge";

const STATIC_BOTS: Array<{ id: string; exchange: string; asset_class: string; color: string; status: string }> = [
  { id: "oracle", exchange: "alpaca", asset_class: "stocks", color: "purple", status: "active" },
  { id: "spy_qqq_trend", exchange: "alpaca", asset_class: "equity_etf", color: "cyan", status: "active" },
  { id: "jerome_macro", exchange: "alpaca", asset_class: "macro_etf", color: "orange", status: "active" },
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
      data-testid={`bot-card-${bot.id}`}
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
          API evidence
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
  const { getAttributedBotIdentity } = useBotIdentity();
  const [filter, setFilter] = useState<"all" | "live" | "paused" | "attention">("all");
  const [query, setQuery] = useState("");
  const { data: livePositions } = useLivePositions();
  const { data: fleetEq } = useFleetEquity();
  const registryQuery = useBotRegistry();
  const { data: registry } = registryQuery;
  const statusQuery = useStatusSummary();
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
      name:               formatBotLabel(identity),
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
  const visibleBots = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return bots.filter((bot) => {
      const matchesFilter = filter === "all"
        || (filter === "live" && !bot.paused && !bot.stale && !bot.statusUnknown)
        || (filter === "paused" && bot.paused)
        || (filter === "attention" && (bot.stale || bot.statusUnknown));
      const matchesSearch = !normalized || `${bot.name} ${bot.id} ${bot.exchangeLabel}`.toLowerCase().includes(normalized);
      return matchesFilter && matchesSearch;
    });
  }, [bots, filter, query]);

  return (
    <div
      className="stream-screen stream-screen-bots h-full w-full flex overflow-hidden"
      data-testid="bots-screen"
      style={{
        display: "grid",
        gridTemplateColumns: "172px minmax(0,1fr)",
        gridTemplateRows: "44px minmax(0,1fr)",
        background: "linear-gradient(90deg,rgba(7,19,17,.88),rgba(8,21,18,.77) 54%,rgba(6,18,16,.82)), url('/streaming-forest-atmosphere.jpg') center 48% / cover",
        color: "#f1f4eb",
        position: "relative",
        isolation: "isolate",
      }}
    >
      <style>{`
        .stream-screen-bots[data-testid="bots-screen"] { font-family:"DM Sans","Segoe UI",sans-serif; color:#f1f4eb !important; background:linear-gradient(90deg,rgba(7,19,17,.88),rgba(8,21,18,.77) 54%,rgba(6,18,16,.82)),url('/streaming-forest-atmosphere.jpg') center 48% / cover !important; }
        .stream-screen-bots[data-testid="bots-screen"] [class*="text-slate-"],.stream-screen-bots[data-testid="bots-screen"] [class*="text-white"] { color:rgba(232,239,225,.82) !important; text-shadow:none !important; }
        .stream-screen-bots[data-testid="bots-screen"] [style*="rgba(148,163,184"],.stream-screen-bots[data-testid="bots-screen"] [style*="rgba(148, 163, 184"] { color:rgba(223,233,220,.68) !important; text-shadow:none !important; }
        .stream-screen-bots[data-testid="bots-screen"] [style*="rgba(0,0,0"] { background:rgba(4,17,14,.48) !important; border-color:rgba(225,238,219,.12) !important; }
        .stream-screen-bots[data-testid="bots-screen"] [class*="text-red-"],.stream-screen-bots[data-testid="bots-screen"] [class*="text-rose-"] { color:#ee9a8c !important; }
        .stream-screen-bots[data-testid="bots-screen"] [class*="text-green-"],.stream-screen-bots[data-testid="bots-screen"] [class*="text-emerald-"] { color:#a9d8ad !important; }
        .stream-screen-bots[data-testid="bots-screen"] [class*="text-yellow-"],.stream-screen-bots[data-testid="bots-screen"] [class*="text-amber-"] { color:#e2c47d !important; }
        .stream-screen-bots > header { grid-column:1 / -1; grid-row:1; display:flex; align-items:center; justify-content:space-between; gap:12px; padding:0 13px; border-bottom:1px solid rgba(235,243,228,.13); background:rgba(10,25,21,.54); }
        .stream-screen-bots .bots-brand { color:#e7ecdf; font:600 10px "Space Mono",monospace; letter-spacing:.15em; text-transform:uppercase; white-space:nowrap; }
        .stream-screen-bots .bots-brand small { display:block; color:rgba(208,225,207,.5); font-size:7px; margin-top:2px; letter-spacing:.12em; }
        .stream-screen-bots .bots-controls { display:flex; align-items:center; justify-content:flex-end; gap:6px; min-width:0; }
        .stream-screen-bots .bots-filter { cursor:pointer; border:1px solid transparent; color:#a6b3a8; background:transparent; border-radius:7px; padding:5px 7px; font:8px "Space Mono",monospace; text-transform:uppercase; }
        .stream-screen-bots .bots-filter:hover,.stream-screen-bots .bots-filter[aria-pressed="true"] { color:#e6e9d7; background:rgba(204,214,175,.12); border-color:rgba(205,216,178,.18); }
        .stream-screen-bots .bots-search { width:130px; border:1px solid rgba(222,236,217,.14); background:rgba(4,17,14,.28); border-radius:7px; padding:5px 8px; color:#eaf0e5; font:9px "DM Sans",sans-serif; outline:0; }
        .stream-screen-bots .bots-search::placeholder { color:#829187; }
        .stream-screen-bots .stream-bot-card-grid { grid-column:2; grid-row:2; align-content:start; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)) !important; grid-auto-rows:minmax(320px,360px) !important; gap:9px !important; padding:12px !important; }
        .stream-screen-bots .stream-bot-card-grid > div { border-top:1px solid rgba(225,238,219,.15) !important; border-right:1px solid rgba(225,238,219,.15) !important; border-bottom:1px solid rgba(225,238,219,.15) !important; border-radius:12px !important; background:linear-gradient(135deg,rgba(22,43,36,.78),rgba(12,27,24,.72)) !important; box-shadow:inset 0 1px rgba(245,250,239,.06),0 12px 26px rgba(0,0,0,.14); backdrop-filter:blur(17px); }
        .stream-screen-bots [data-testid="bots-sidebar"] { background:linear-gradient(145deg,rgba(14,32,27,.88),rgba(10,24,22,.9)) !important; border-right:1px solid rgba(225,238,219,.14) !important; }
        @media(max-width:720px) { .stream-screen-bots { grid-template-columns:1fr !important; grid-template-rows:44px minmax(0,1fr) !important; } .stream-screen-bots [data-testid="bots-sidebar"] { display:none !important; } .stream-screen-bots .stream-bot-card-grid { grid-column:1 !important; } .stream-screen-bots .bots-brand small { display:none; } .stream-screen-bots .bots-search { display:none; } .stream-screen-bots .bots-filter { padding:5px; } }
      `}</style>
      <header data-testid="bots-toolbar">
        <div className="bots-brand">NORTHSTAR / STREAMING<small>FLEET OPERATIONS · SNAPSHOT VIEW</small></div>
        <div className="bots-controls">
          <input
            data-testid="bots-search"
            className="bots-search"
            aria-label="Search bots"
            placeholder="Find a strategy"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          {(["all", "live", "paused", "attention"] as const).map((key) => (
            <button
              key={key}
              data-testid={`bots-filter-${key}`}
              type="button"
              className="bots-filter"
              aria-pressed={filter === key}
              onClick={() => setFilter(key)}
            >
              {key === "all" ? "All" : key === "attention" ? "Attention" : key}
            </button>
          ))}
          <span className="hidden sm:inline text-[8px] font-mono uppercase tracking-widest" style={{ color: "rgba(223,233,220,.6)" }}>
            {registryQuery.isError ? "Registry unavailable" : registryQuery.data ? "Registry snapshot" : "Registry loading"}
            {" · "}
            {statusQuery.data?.market_open == null ? "Market unknown" : statusQuery.data.market_open ? "Market open" : "Market closed"}
          </span>
        </div>
      </header>
      {/* ── LEFT SIDEBAR ── */}
      <div
        className="flex flex-col shrink-0 overflow-hidden"
        data-testid="bots-sidebar"
        style={{ width: 172, gridColumn: 1, gridRow: 2, background: "rgba(10,24,22,.86)", borderRight: "1px solid rgba(225,238,219,0.14)" }}
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
              Closed Trade Journal
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
                    <div className="text-[7px] font-mono" style={{ color: "rgba(148,163,184,0.65)" }}>{formatBotLabel(identity)}</div>
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
        data-testid="bots-card-grid"
        style={{
          gridColumn: 2,
          gridRow: 2,
          minWidth: 0,
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))",
          gridAutoRows: "minmax(320px, 360px)",
          gap: 6,
          alignContent: "start",
        }}
      >
        {visibleBots.length > 0 ? visibleBots.map((bot) => (
          <BotCard key={bot.id} bot={bot} />
        )) : (
          <div className="col-span-full flex min-h-32 items-center justify-center rounded-lg border border-white/10 text-center font-mono text-xs text-slate-400" data-testid="bots-empty">
            {registryQuery.isLoading ? "Loading registered bots…" : registryQuery.isError ? "Bot registry unavailable" : "No bots match this search and state filter."}
          </div>
        )}
      </div>

      <DDGBadge style={{ position: "absolute", bottom: 8, left: 8, zIndex: 50 }} />
    </div>
  );
}
