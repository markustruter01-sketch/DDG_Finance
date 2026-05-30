import {
  usePortfolio,
  useKrakenPerformance,
  useKrakenStatus,
  useFleetEquity,
  useBotRegistry,
  useRecentTrades,
} from "@/hooks/use-trading";
import { getBotColors } from "@/lib/bot-colors";
import { DDGBadge } from "@/components/DDGBadge";

const STARTING_BALANCE = 100_000;

const STATIC_BOTS: Array<{ id: string; name: string; icon: string; exchange: string; asset_class: string; color: string; status: string }> = [
  { id: "oracle",            name: "Oracle",            icon: "🔮", exchange: "alpaca",  asset_class: "stocks",   color: "purple",  status: "active" },
  { id: "spy_qqq_trend",     name: "SPY/QQQ Trend",     icon: "📈", exchange: "alpaca",  asset_class: "equity_etf", color: "cyan",  status: "active" },
  { id: "jerome_macro",      name: "Jerome",            icon: "🏛",  exchange: "alpaca",  asset_class: "macro_etf", color: "orange", status: "active" },
];

const PARAMS_TEXT: Record<string, string> = {
  oracle: "Z-Score > 2.1 | Min Profit 0.5% | NYSE hours only",
  spy_qqq_trend: "Z-Entry 2.0 | Z-Exit 0.3 | Trail 1.5% | Stop 3%",
  jerome_macro: "LLM analysis at 9AM + 9PM UTC | Groq/Gemini powered",
};

function fmtEq(v: number) {
  return `$${Math.round(v).toLocaleString()}`;
}
function fmtPnl(v: number) {
  const abs = Math.abs(v);
  const sign = v >= 0 ? "+" : "−";
  if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(1)}k`;
  return `${sign}$${abs.toFixed(0)}`;
}
function fmtPct(pnl: number) {
  const pct = (pnl / STARTING_BALANCE) * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
}
function fmtTime(iso: string | null | undefined) {
  if (!iso) return "--:--:--";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString("en-US", { hour12: false });
  } catch {
    return "--:--:--";
  }
}
function getExchangeLabel(exchange: string, assetClass: string): string {
  if (exchange === "oanda") return "OANDA · FOREX";
  if (exchange === "kraken") return "KRAKEN · CRYPTO WILD";
  const map: Record<string, string> = {
    stocks: "STOCKS",
    equity_etf: "ETFS",
    macro_etf: "MACRO",
    sector_etf: "SECTOR ETFS",
    defensive_etf: "DEFENSIVE ETFS",
    bond_etf: "BOND ETFS",
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
  paused: boolean;
  stale?: boolean;
  openPositionCount: number;
  openPositionSymbols: string[];
  recentTrades: Array<{ symbol: string; pnl_usd: number }>;
  paramsText: string;
  extraBadge?: string;
}

function StatusBadge({ paused, stale }: { paused: boolean; stale?: boolean }) {
  const isStale = stale && !paused;
  const label = paused ? "PAUSED" : isStale ? "STALE" : "LIVE";
  const c = paused
    ? { bg: "rgba(245,158,11,0.15)", border: "rgba(245,158,11,0.4)", dot: "#f59e0b", text: "#f59e0b", glow: "0 0 5px #f59e0b44" }
    : isStale
    ? { bg: "rgba(100,116,139,0.12)", border: "rgba(100,116,139,0.3)", dot: "#64748b", text: "#64748b", glow: "none" }
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
  const pnl = bot.equity != null ? bot.equity - STARTING_BALANCE : null;
  const pnlColor = pnl == null ? "#64748b" : pnl > 0 ? "#34d399" : pnl < 0 ? "#f87171" : "#64748b";
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
      {/* HEADER */}
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
        <StatusBadge paused={bot.paused} stale={bot.stale} />
      </div>

      {/* EQUITY */}
      <div className="px-2.5 pb-1 shrink-0">
        <div className="text-[18px] font-black font-mono leading-tight" style={{ color: bot.paused ? "rgba(255,255,255,0.6)" : "#fff" }}>
          {bot.equity != null ? fmtEq(bot.equity) : "—"}
        </div>
        {pnl != null && (
          <div className="text-[10px] font-mono font-bold" style={{ color: pnlColor }}>
            {pnl >= 0 ? "+" : ""}${Math.abs(pnl).toFixed(0)} ({fmtPct(pnl)})
          </div>
        )}
      </div>

      <div className="flex-1 flex flex-col overflow-hidden px-2.5 pb-1.5 gap-1.5 min-h-0">
        {/* OPEN POSITIONS */}
        <div className="shrink-0">
          <div className="flex items-center justify-between mb-0.5">
            <span className="text-[8px] uppercase tracking-widest font-bold" style={{ color: "rgba(148,163,184,0.4)" }}>
              Open Positions
            </span>
            <span
              className="text-[9px] font-black font-mono px-1.5 py-px rounded"
              style={{
                background: bot.openPositionCount > 0 ? `${bot.color}22` : "rgba(0,0,0,0.3)",
                color: bot.openPositionCount > 0 ? bot.color : "#475569",
                border: `1px solid ${bot.openPositionCount > 0 ? bot.color + "44" : "rgba(255,255,255,0.06)"}`,
              }}
            >
              {bot.openPositionCount}
            </span>
          </div>
          {bot.openPositionSymbols.length > 0 ? (
            <div className="text-[8px] font-mono text-slate-400 leading-relaxed truncate">
              {bot.openPositionSymbols.join(", ")}
            </div>
          ) : (
            <div className="text-[8px] font-mono text-slate-700">None</div>
          )}
        </div>

        {/* PARAMS */}
        <div className="shrink-0">
          <div className="text-[8px] uppercase tracking-widest font-bold mb-0.5" style={{ color: "rgba(148,163,184,0.4)" }}>
            Params
          </div>
          <div className="text-[8px] leading-relaxed" style={{ color: "rgba(148,163,184,0.5)" }}>
            {bot.paramsText}
          </div>
        </div>

        {/* RECENT TRADES */}
        <div className="min-h-0 flex flex-col">
          <div className="text-[8px] uppercase tracking-widest font-bold mb-0.5 shrink-0" style={{ color: "rgba(148,163,184,0.4)" }}>
            Recent Trades
          </div>
          {bot.recentTrades.length === 0 ? (
            <div className="text-[8px] font-mono" style={{ color: "rgba(148,163,184,0.25)" }}>No recent trades</div>
          ) : (
            <div className="flex flex-col gap-px overflow-hidden">
              {bot.recentTrades.slice(0, 3).map((t, i) => (
                <div key={i} className="flex items-center justify-between">
                  <span className="text-[9px] font-mono font-bold text-slate-300">
                    {t.symbol}
                  </span>
                  <span
                    className="text-[9px] font-mono font-bold"
                    style={{ color: t.pnl_usd >= 0 ? "#34d399" : "#f87171" }}
                  >
                    {t.pnl_usd >= 0 ? "+" : ""}${Math.abs(t.pnl_usd).toFixed(0)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* FOOTER */}
      <div
        className="shrink-0 flex items-center justify-between px-2.5 py-1"
        style={{ borderTop: "1px solid rgba(255,255,255,0.05)", background: "rgba(0,0,0,0.2)" }}
      >
        <span className="text-[7px] uppercase tracking-widest font-bold" style={{ color: "rgba(148,163,184,0.2)" }}>
          Awaiting Data
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
  const { data: portfolio } = usePortfolio();
  const { data: davyPerf } = useKrakenPerformance("davy-jones");
  const { data: davyStatus } = useKrakenStatus("davy-jones");
  const { data: bbPerf } = useKrakenPerformance("blackbeard");
  const { data: bbStatus } = useKrakenStatus("blackbeard");
  const { data: listingPumpStatus } = useKrakenStatus("listing_pump");
  const { data: eventTraderStatus } = useKrakenStatus("event_trader");
  const { data: memecoinStatus } = useKrakenStatus("memecoin_velocity");
  const { data: fleetEq } = useFleetEquity();
  const { data: registry } = useBotRegistry();
  const { data: recentTrades } = useRecentTrades(15);

  const oracleEquity = fleetEq?.oracle?.equity ?? portfolio?.account?.equity ?? null;
  const oraclePositions = (portfolio?.positions ?? []).filter((p) => (p.market_value ?? 0) > 10);

  const spyEquity = fleetEq?.spy_qqq_trend?.equity ?? davyPerf?.current_equity ?? null;
  const jeromeEquity = fleetEq?.jerome_macro?.equity ?? bbPerf?.current_equity ?? null;

  const fleetTotalFromEquity = fleetEq?.fleet_total?.equity ?? null;
  const allEquities = [
    oracleEquity, spyEquity, jeromeEquity,
  ].filter((e): e is number => e != null);
  const fleetTotal = fleetTotalFromEquity ?? (allEquities.length >= 3 ? allEquities.reduce((s, e) => s + e, 0) : null);
  const fleetStarting = fleetEq?.fleet_total?.starting ?? allEquities.length * STARTING_BALANCE;
  const fleetPnl = fleetTotal != null ? fleetTotal - fleetStarting : null;
  const fleetPnlColor = fleetPnl == null ? "#94a3b8" : fleetPnl >= 0 ? "#34d399" : "#f87171";

  const botRuntimeByRegistryId: Record<string, Partial<BotCardData>> = {
    oracle: {
      equity: oracleEquity,
      paused: false,
      openPositionCount: oraclePositions.length,
      openPositionSymbols: oraclePositions.map((p) => p.symbol),
      recentTrades: (recentTrades?.trades ?? []).slice(0, 3).map((t) => ({
        symbol: t.symbol,
        pnl_usd: t.pnl_usd ?? 0,
      })),
    },
    spy_qqq_trend: {
      equity: spyEquity,
      paused: davyStatus?.bot_paused ?? false,
      stale: fleetEq?.spy_qqq_trend?.stale ?? false,
      openPositionCount: davyStatus?.open_positions?.length ?? fleetEq?.spy_qqq_trend?.positions ?? 0,
      openPositionSymbols: (davyStatus?.open_positions ?? []).map((p) => p.symbol),
      recentTrades: (davyStatus?.recent_trades ?? []).slice(0, 3).map((t) => ({
        symbol: t.symbol,
        pnl_usd: t.pnl_usd,
      })),
    },
    jerome_macro: {
      equity: jeromeEquity,
      paused: bbStatus?.bot_paused ?? false,
      stale: fleetEq?.jerome_macro?.stale ?? false,
      openPositionCount: bbStatus?.open_positions?.length ?? fleetEq?.jerome_macro?.positions ?? 0,
      openPositionSymbols: (bbStatus?.open_positions ?? []).map((p) => p.symbol),
      recentTrades: (bbStatus?.recent_trades ?? []).slice(0, 3).map((t) => ({
        symbol: t.symbol,
        pnl_usd: t.pnl_usd,
      })),
    },
    listing_pump: {
      equity: listingPumpStatus?.total_equity_usd ?? null,
      paused: listingPumpStatus?.bot_paused ?? false,
      openPositionCount: listingPumpStatus?.open_positions?.length ?? 0,
      openPositionSymbols: (listingPumpStatus?.open_positions ?? []).map((p) => p.symbol),
      recentTrades: (listingPumpStatus?.recent_trades ?? []).slice(0, 3).map((t) => ({
        symbol: t.symbol,
        pnl_usd: t.pnl_usd,
      })),
    },
    event_trader: {
      equity: eventTraderStatus?.total_equity_usd ?? null,
      paused: eventTraderStatus?.bot_paused ?? false,
      openPositionCount: eventTraderStatus?.open_positions?.length ?? 0,
      openPositionSymbols: (eventTraderStatus?.open_positions ?? []).map((p) => p.symbol),
      recentTrades: (eventTraderStatus?.recent_trades ?? []).slice(0, 3).map((t) => ({
        symbol: t.symbol,
        pnl_usd: t.pnl_usd,
      })),
    },
    memecoin_velocity: {
      equity: memecoinStatus?.total_equity_usd ?? null,
      paused: memecoinStatus?.bot_paused ?? false,
      openPositionCount: memecoinStatus?.open_positions?.length ?? 0,
      openPositionSymbols: (memecoinStatus?.open_positions ?? []).map((p) => p.symbol),
      recentTrades: (memecoinStatus?.recent_trades ?? []).slice(0, 3).map((t) => ({
        symbol: t.symbol,
        pnl_usd: t.pnl_usd,
      })),
    },
  };

  const botSource = registry?.bots ?? STATIC_BOTS;
  const bots: BotCardData[] = botSource.map((bot) => {
    const colors = getBotColors(bot.color);
    const runtime = botRuntimeByRegistryId[bot.id] ?? {};
    return {
      id: bot.id,
      name: (bot as { display_name?: string }).display_name ?? (bot as { name?: string }).name ?? bot.id,
      icon: bot.icon,
      exchangeLabel: getExchangeLabel(bot.exchange, bot.asset_class),
      color: colors.hex,
      equity: null,
      paused: bot.status !== "active",
      openPositionCount: 0,
      openPositionSymbols: [],
      recentTrades: [],
      paramsText: PARAMS_TEXT[bot.id] ?? "Strategy parameters unavailable",
      ...runtime,
    };
  });

  const getPnl = (b: BotCardData) =>
    b.equity != null ? b.equity - STARTING_BALANCE : -Infinity;

  const sortedForLadder = [...bots].sort((a, b) => getPnl(b) - getPnl(a));

  const liveCount = bots.filter((b) => !b.paused && !b.stale).length;
  const totalOpen = bots.reduce((s, b) => s + b.openPositionCount, 0);

  const liveFeedTrades = recentTrades?.trades ?? [];

  return (
    <div className="h-full w-full flex overflow-hidden" style={{ background: "#020617", color: "#e2e8f0" }}>
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
              {fleetPnl >= 0 ? "+" : ""}${Math.abs(fleetPnl).toFixed(0)} ({((fleetPnl / fleetStarting) * 100).toFixed(2)}%)
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
              <div className="text-[13px] font-black font-mono text-white">{liveCount}/{bots.length}</div>
            </div>
            <div
              className="flex-1 rounded px-1.5 py-1"
              style={{ background: "rgba(0,0,0,0.3)", border: "1px solid rgba(255,255,255,0.06)" }}
            >
              <div className="text-[7px] uppercase tracking-wider font-bold" style={{ color: "rgba(148,163,184,0.35)" }}>
                Open Pos
              </div>
              <div className="text-[13px] font-black font-mono text-white">{totalOpen}</div>
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
              const p = getPnl(bot);
              const finite = isFinite(p);
              const pColor = !finite || p === 0 ? "#475569" : p > 0 ? "#34d399" : "#f87171";
              return (
                <div key={bot.id} className="flex items-center justify-between gap-1">
                  <div className="flex items-center gap-1 min-w-0">
                    <div className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: bot.color }} />
                    <span className="text-[8px] font-medium truncate" style={{ color: "rgba(148,163,184,0.6)", maxWidth: 80 }}>
                      {bot.name}
                    </span>
                  </div>
                  <span className="text-[8px] font-mono font-bold shrink-0" style={{ color: pColor }}>
                    {finite && p !== -Infinity ? fmtPnl(p) : "$0"}
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
            <span className="w-1.5 h-1.5 rounded-full" style={{ background: "#22c55e", boxShadow: "0 0 5px #22c55e" }} />
          </div>
          <div className="flex-1 overflow-y-auto flex flex-col gap-2 min-h-0 pr-2">
            {liveFeedTrades.length === 0 ? (
              <div className="text-[8px] font-mono" style={{ color: "rgba(148,163,184,0.2)" }}>No recent trades</div>
            ) : (
              liveFeedTrades.map((t, i) => {
                const pColor = (t.pnl_usd ?? 0) >= 0 ? "#34d399" : "#f87171";
                return (
                  <div key={t.trade_id ?? i} className="shrink-0">
                    <div className="text-[7px] font-mono" style={{ color: "rgba(148,163,184,0.25)" }}>
                      {fmtTime(t.closed_at)}
                    </div>
                    <div className="flex items-center justify-between gap-1">
                      <span className="text-[9px] font-mono font-bold text-slate-300 truncate">
                        {t.symbol}
                      </span>
                      <span className="text-[9px] font-mono font-bold shrink-0" style={{ color: pColor }}>
                        {(t.pnl_usd ?? 0) >= 0 ? "+" : ""}${Math.abs(t.pnl_usd ?? 0).toFixed(0)}
                      </span>
                    </div>
                    <div className="text-[7px] font-mono" style={{ color: "rgba(148,163,184,0.3)" }}>Oracle</div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>

      {/* ── BOT GRID ── */}
      <div
        className="flex-1 overflow-y-auto p-2"
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
