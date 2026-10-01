import { useMemo, useState, type CSSProperties } from "react";
import { ArrowDownRight, ArrowUpRight, CircleHelp, Clock3, Command, Radio, Search, SlidersHorizontal, WalletCards } from "lucide-react";
import { useBotRegistry, useFleetEquity, useJournal, useLivePositions } from "../streaming-current/_shared/mockData";
import { getBotColors } from "../streaming-current/_shared/bot-colors";
import { getAttributedBotIdentity } from "../streaming-current/_shared/identity";

const STATIC_BOTS: Array<{ id: string; name: string; exchange: string; asset_class: string; color: string; status: string }> = [
  { id: "oracle", name: getAttributedBotIdentity("oracle").displayName, exchange: "alpaca", asset_class: "stocks", color: "purple", status: "active" },
  { id: "spy_qqq_trend", name: getAttributedBotIdentity("spy_qqq_trend").displayName, exchange: "alpaca", asset_class: "equity_etf", color: "cyan", status: "active" },
  { id: "jerome_macro", name: getAttributedBotIdentity("jerome_macro").displayName, exchange: "alpaca", asset_class: "macro_etf", color: "orange", status: "active" },
];

const PARAMS_UNAVAILABLE = "Not provided by the bot registry.";

function fmtEq(value: number) {
  return `$${Math.round(value).toLocaleString()}`;
}
function fmtPnl(value: number) {
  const abs = Math.abs(value);
  const sign = value >= 0 ? "+" : "−";
  return abs >= 1000 ? `${sign}$${(abs / 1000).toFixed(1)}k` : `${sign}$${abs.toFixed(0)}`;
}
function fmtPct(value: number | null | undefined) {
  if (value == null) return "";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}
function fmtTime(value: string | null | undefined) {
  if (!value) return "--:--:--";
  try {
    return new Date(value).toLocaleTimeString("en-US", { hour12: false });
  } catch {
    return "--:--:--";
  }
}
function getExchangeLabel(exchange: string, assetClass: string) {
  if (exchange === "oanda") return "OANDA · FOREX";
  if (exchange === "kraken") return "KRAKEN · CRYPTO";
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

interface BotRow {
  id: string;
  name: string;
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

function StatusPill({ bot }: { bot: BotRow }) {
  const stale = bot.stale && !bot.paused;
  const label = bot.paused ? "Paused" : stale ? "Stale" : bot.statusUnknown ? "Unknown" : "Live";
  const tone = bot.paused ? "amber" : stale ? "muted" : bot.statusUnknown ? "unknown" : "green";
  return (
    <span className={`bots-status bots-status-${tone}`}>
      <i />
      {label}
    </span>
  );
}

function signedTrade(value: number | null) {
  if (value == null) return "—";
  return `${value >= 0 ? "+" : "−"}$${Math.abs(value).toFixed(0)}`;
}

export function Bots() {
  const [filter, setFilter] = useState<"all" | "live" | "paused" | "attention">("all");
  const [query, setQuery] = useState("");
  const { data: livePositions } = useLivePositions();
  const { data: fleetEq } = useFleetEquity();
  const { data: registry } = useBotRegistry();
  const journalQuery = useJournal();
  const journal = journalQuery.data;

  const oraclePositionData = livePositions?.positions_by_bot?.oracle;
  const spyPositionData = livePositions?.positions_by_bot?.spy_qqq_trend;
  const jeromePositionData = livePositions?.positions_by_bot?.jerome_macro;
  const closedJournalTrades = (journal?.trades ?? []).filter(
    (trade) => trade.status === "Closed_Win" || trade.status === "Closed_Loss",
  );
  const journalHasUnattributedTrades = closedJournalTrades.some((trade) => !trade.bot_id?.trim());
  const recentTradesForBot = (botId: string) =>
    closedJournalTrades
      .filter((trade) => trade.bot_id === botId)
      .slice(0, 3)
      .map((trade) => ({ symbol: trade.ticker, pnl_usd: trade.pnl_usd ?? trade.realized_pnl ?? null }));

  const fleetTotal = fleetEq?.fleet_total?.equity ?? null;
  const fleetPnl = fleetEq?.fleet_total?.pnl ?? null;
  const fleetPnlPct = fleetEq?.fleet_total?.pnl_pct ?? null;

  const botRuntimeByRegistryId: Record<string, Partial<BotRow>> = {
    oracle: {
      equity: fleetEq?.oracle?.equity ?? null,
      pnl: fleetEq?.oracle?.pnl ?? null,
      pnl_pct: fleetEq?.oracle?.pnl_pct ?? null,
      ...(fleetEq?.oracle?.paused != null ? { paused: fleetEq.oracle.paused } : {}),
      statusUnknown: fleetEq?.oracle?.paused == null,
      openPositionCount: oraclePositionData?.count ?? fleetEq?.oracle?.positions ?? null,
      openPositionSymbols: oraclePositionData?.positions.map((position) => position.symbol) ?? [],
      recentTrades: recentTradesForBot("oracle"),
      recentTradesAttributionUnavailable: journalHasUnattributedTrades,
      recentTradesLoading: journalQuery.isLoading,
      recentTradesError: journalQuery.isError,
    },
    spy_qqq_trend: {
      equity: fleetEq?.spy_qqq_trend?.equity ?? null,
      pnl: fleetEq?.spy_qqq_trend?.pnl ?? null,
      pnl_pct: fleetEq?.spy_qqq_trend?.pnl_pct ?? null,
      ...(fleetEq?.spy_qqq_trend?.paused != null ? { paused: fleetEq.spy_qqq_trend.paused } : {}),
      statusUnknown: fleetEq?.spy_qqq_trend?.paused == null,
      openPositionCount: spyPositionData?.count ?? fleetEq?.spy_qqq_trend?.positions ?? null,
      openPositionSymbols: spyPositionData?.positions.map((position) => position.symbol) ?? [],
      recentTrades: recentTradesForBot("spy_qqq_trend"),
      recentTradesAttributionUnavailable: journalHasUnattributedTrades,
      recentTradesLoading: journalQuery.isLoading,
      recentTradesError: journalQuery.isError,
    },
    jerome_macro: {
      equity: fleetEq?.jerome_macro?.equity ?? null,
      pnl: fleetEq?.jerome_macro?.pnl ?? null,
      pnl_pct: fleetEq?.jerome_macro?.pnl_pct ?? null,
      ...(fleetEq?.jerome_macro?.paused != null ? { paused: fleetEq.jerome_macro.paused } : {}),
      statusUnknown: fleetEq?.jerome_macro?.paused == null,
      openPositionCount: jeromePositionData?.count ?? fleetEq?.jerome_macro?.positions ?? null,
      openPositionSymbols: jeromePositionData?.positions.map((position) => position.symbol) ?? [],
      recentTrades: recentTradesForBot("jerome_macro"),
      recentTradesAttributionUnavailable: journalHasUnattributedTrades,
      recentTradesLoading: journalQuery.isLoading,
      recentTradesError: journalQuery.isError,
    },
  };

  const rawBotSource = registry?.bots ?? STATIC_BOTS;
  const supportedBotIds = Object.keys(botRuntimeByRegistryId);
  const botSource = rawBotSource.filter((bot: { id: string }) => {
    if (!supportedBotIds.includes(bot.id)) return false;
    if (!fleetEq) return true;
    const equityRow = (fleetEq as unknown as Record<string, { stale?: boolean } | undefined>)[bot.id];
    return equityRow != null && !equityRow.stale;
  });
  const bots: BotRow[] = botSource.map((bot) => {
    const colors = getBotColors(bot.color);
    const runtime = botRuntimeByRegistryId[bot.id] ?? {};
    const identity = getAttributedBotIdentity(bot.id);
    return {
      id: bot.id,
      name: identity.displayName,
      exchangeLabel: getExchangeLabel(bot.exchange, bot.asset_class),
      color: colors.hex,
      equity: null,
      pnl: null,
      pnl_pct: null,
      paused: bot.status !== "active",
      openPositionCount: null,
      openPositionSymbols: [],
      recentTrades: [],
      paramsText: PARAMS_UNAVAILABLE,
      ...runtime,
    };
  });

  const sortedForLadder = [...bots].sort((a, b) => (b.pnl ?? -Infinity) - (a.pnl ?? -Infinity));
  const liveCount = bots.every((bot) => !bot.statusUnknown)
    ? bots.filter((bot) => !bot.paused && !bot.stale).length
    : null;
  const totalOpen = bots.every((bot) => bot.openPositionCount != null)
    ? bots.reduce((sum, bot) => sum + bot.openPositionCount!, 0)
    : null;
  const liveFeedTrades = closedJournalTrades.slice(0, 15);

  const visibleBots = useMemo(() => {
    const lowerQuery = query.trim().toLowerCase();
    return bots.filter((bot) => {
      const matchesFilter =
        filter === "all" ||
        (filter === "live" && !bot.paused && !bot.stale && !bot.statusUnknown) ||
        (filter === "paused" && bot.paused) ||
        (filter === "attention" && (bot.stale || bot.statusUnknown));
      const matchesSearch = !lowerQuery || `${bot.name} ${bot.id} ${bot.exchangeLabel}`.toLowerCase().includes(lowerQuery);
      return matchesFilter && matchesSearch;
    });
  }, [bots, filter, query]);

  return (
    <main className="fleet-page">
      <style>{`
        .fleet-page {
          --ink: #f1f4eb; --quiet: #a6b3a8; --faint: #7d8c80; --line: rgba(226,238,222,.12);
          --glass: rgba(12,28,24,.72); --glass-soft: rgba(16,35,29,.62);
          min-height: 800px; width: 100%; box-sizing: border-box; padding: 18px 34px 20px;
          color: var(--ink); font-family: 'DM Sans', 'Segoe UI', sans-serif; position: relative; isolation: isolate;
          background: #11221d url('/__mockup/images/streaming-forest-atmosphere.jpg') center 48% / cover fixed;
          overflow: hidden;
        }
        .fleet-page *, .fleet-page *::before, .fleet-page *::after { box-sizing: border-box; }
        .fleet-page::before { content:''; position:absolute; inset:0; z-index:-1; background:
          linear-gradient(90deg, rgba(7,19,17,.82) 0%, rgba(8,21,18,.74) 54%, rgba(6,18,16,.78) 100%),
          linear-gradient(0deg, rgba(5,14,13,.46), rgba(7,18,15,.25)); }
        .fleet-page::after { content:''; position:absolute; inset:0; z-index:-1; opacity:.16; pointer-events:none;
          background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.8' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.18'/%3E%3C/svg%3E"); }
        .fleet-top { height:36px; display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid rgba(235,243,228,.13); margin-bottom:17px; }
        .fleet-brand { display:flex; align-items:center; gap:11px; color:#e7ecdf; font:600 11px 'Space Mono', monospace; letter-spacing:.17em; text-transform:uppercase; }
        .brand-mark { width:25px; height:25px; display:grid; place-items:center; border:1px solid rgba(209,220,195,.35); color:#d8d7ad; border-radius:8px; background:rgba(231,237,218,.08); }
        .top-right { display:flex; align-items:center; gap:15px; color:var(--quiet); font:10px 'Space Mono',monospace; letter-spacing:.08em; text-transform:uppercase; }
        .session-tag { display:flex; align-items:center; gap:7px; padding:7px 11px; border:1px solid rgba(213,224,206,.18); border-radius:999px; background:rgba(15,32,28,.56); backdrop-filter:blur(16px); }
        .session-tag i { width:6px;height:6px;background:#a8c58b;border-radius:50%;box-shadow:0 0 10px #a8c58b77; }
        .intro { display:flex; justify-content:space-between; align-items:flex-end; margin-bottom:18px; }
        .eyebrow { color:#bdc6a0; font:10px 'Space Mono',monospace; letter-spacing:.18em; text-transform:uppercase; margin-bottom:8px; }
        .intro h1 { margin:0; font:500 35px/1.04 'DM Sans',sans-serif; letter-spacing:-.045em; color:#f2f1e6; }
        .intro-copy { margin-top:8px; color:#a9b6a8; font-size:12px; letter-spacing:.01em; }
        .intro-meta { display:flex; align-items:center; gap:8px; color:#aebbae; font:10px 'Space Mono',monospace; text-transform:uppercase; }
        .intro-meta svg { color:#c2c9a0; }
        .hero-panel, .surface { backdrop-filter:blur(22px) saturate(118%); -webkit-backdrop-filter:blur(22px) saturate(118%);
          background:linear-gradient(135deg, rgba(22,43,36,.79), rgba(12,27,24,.67)); border:1px solid rgba(228,239,221,.15);
          box-shadow:0 24px 60px rgba(0,0,0,.20), inset 0 1px rgba(245,250,239,.07); }
        .hero-panel { border-radius:18px; padding:14px 22px; display:grid; grid-template-columns:minmax(360px,1.35fr) 1fr 1fr 1fr; gap:0; margin-bottom:13px; min-height:108px; }
        .hero-main { padding-right:24px; display:flex; flex-direction:column; justify-content:center; }
        .metric-kicker { color:#a8b6a5; font:9px 'Space Mono',monospace; text-transform:uppercase; letter-spacing:.16em; }
        .fleet-equity { margin-top:6px; font:500 34px/1 'Space Mono',monospace; letter-spacing:-.075em; color:#f0f2e6; }
        .hero-delta { margin-top:8px; display:flex; align-items:center; gap:8px; font:11px 'Space Mono',monospace; }
        .hero-delta-value { color:#b7d49a; }
        .delta-caption { color:#829389; font:9px 'DM Sans',sans-serif; }
        .hero-metric { padding:11px 18px; border-left:1px solid var(--line); display:flex; flex-direction:column; justify-content:center; }
        .metric-value { margin-top:12px; color:#eff1e8; font:500 23px 'Space Mono',monospace; letter-spacing:-.06em; }
        .metric-note { margin-top:5px; color:#85968a; font:10px 'DM Sans',sans-serif; }
        .content-grid { display:grid; grid-template-columns:minmax(0,1.68fr) minmax(310px,.92fr); gap:15px; align-items:stretch; }
        .surface { border-radius:16px; overflow:hidden; }
        .panel-head { height:50px; padding:0 17px; display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid var(--line); }
        .panel-title { color:#e5e9dc; font:600 12px 'DM Sans',sans-serif; letter-spacing:.01em; display:flex; align-items:center; gap:9px; }
        .panel-title svg { color:#bbc8a2; }
        .panel-sub { margin-top:3px; color:#819187; font:9px 'Space Mono',monospace; text-transform:uppercase; letter-spacing:.11em; }
        .filter-row { display:flex; align-items:center; gap:4px; }
        .filter-button { cursor:pointer; border:1px solid transparent; color:#93a198; background:transparent; border-radius:7px; padding:6px 8px; font:9px 'Space Mono',monospace; transition:background .16s,color .16s,border-color .16s; }
        .filter-button:hover { color:#eef1e4; background:rgba(240,244,230,.08); }
        .filter-button.active { color:#e6e9d7; background:rgba(204,214,175,.12); border-color:rgba(205,216,178,.18); }
        .bot-list { padding:0 14px 13px; }
        .bot-columns { height:31px; display:grid; grid-template-columns:minmax(165px,1.04fr) minmax(122px,.78fr) minmax(150px,.9fr) minmax(150px,.9fr); align-items:center; padding:0 12px; color:#7f9186; font:8px 'Space Mono',monospace; letter-spacing:.11em; text-transform:uppercase; }
        .bot-row { min-height:105px; display:grid; grid-template-columns:minmax(165px,1.04fr) minmax(122px,.78fr) minmax(150px,.9fr) minmax(150px,.9fr); align-items:center; padding:10px 12px 9px; margin-bottom:6px; border-radius:12px; border:1px solid rgba(225,238,219,.11); border-left:2px solid var(--bot-accent); background:linear-gradient(110deg,rgba(235,245,225,.065),rgba(229,238,224,.025)); position:relative; overflow:hidden; }
        .bot-row:last-child { margin-bottom:0; }
        .bot-row::after { content:''; position:absolute; right:-55px; top:-90px; width:190px;height:190px; border-radius:50%; background:var(--bot-glow); filter:blur(38px); opacity:.11; pointer-events:none; }
        .bot-ident, .bot-equity, .bot-position, .bot-activity { min-width:0; position:relative;z-index:1; }
        .bot-ident { display:flex; align-items:flex-start; gap:11px; padding-right:10px; }
        .bot-sigil { width:30px;height:30px;border-radius:9px; display:grid; place-items:center; color:var(--bot-accent); font:600 10px 'Space Mono',monospace; background:color-mix(in srgb,var(--bot-accent) 14%, transparent); border:1px solid color-mix(in srgb,var(--bot-accent) 38%, transparent); flex:none; }
        .bot-name { color:#edf0e5; font-size:12px; font-weight:600; line-height:1.2; white-space:nowrap; }
        .bot-venue { margin-top:5px; color:#85958b; font:8px 'Space Mono',monospace; letter-spacing:.08em; }
        .bot-status-wrap { margin-top:8px; }
        .bots-status { display:inline-flex; align-items:center; gap:5px; border:1px solid; padding:3px 6px; border-radius:999px; font:8px 'Space Mono',monospace; letter-spacing:.08em; text-transform:uppercase; white-space:nowrap; }
        .bots-status i { width:5px;height:5px;border-radius:50%;background:currentColor; }
        .bots-status-green { color:#c3d7a7; background:rgba(140,174,116,.10); border-color:rgba(165,193,138,.25); }
        .bots-status-amber, .bots-status-unknown { color:#e2c28c; background:rgba(217,170,100,.10); border-color:rgba(226,190,127,.25); }
        .bots-status-muted { color:#b2b9b1; background:rgba(182,194,182,.08); border-color:rgba(182,194,182,.18); }
        .equity-value { color:#eef1e7; font:500 18px 'Space Mono',monospace; letter-spacing:-.06em; white-space:nowrap; }
        .equity-pnl { margin-top:7px; font:10px 'Space Mono',monospace; white-space:nowrap; }
        .muted-dash { color:#7f8d83; }
        .tiny-label { color:#819087; font:8px 'Space Mono',monospace; letter-spacing:.12em; text-transform:uppercase; }
        .position-count { margin-top:7px; display:flex; align-items:center; gap:8px; color:#e2e6dc; font:11px 'Space Mono',monospace; }
        .position-count b { font-size:16px; font-weight:500; }
        .position-symbols { margin-top:6px; color:#b0bba9; font:9px 'Space Mono',monospace; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .activity-list { margin-top:7px; display:flex; flex-direction:column; gap:5px; }
        .activity-item { display:flex; justify-content:space-between; gap:8px; color:#b4c0b3; font:9px 'Space Mono',monospace; }
        .activity-item span:first-child { color:#e0e6d9; font-weight:600; }
        .params-line { margin-top:10px; padding-top:7px; border-top:1px solid rgba(225,238,219,.09); color:#829087; font-size:9px; display:flex; align-items:center; gap:6px; }
        .params-line svg { flex:none; color:#9aa891; }
        .trade-panel { display:flex; flex-direction:column; min-height:0; }
        .trade-head-extra { color:#83938a; font:8px 'Space Mono',monospace; letter-spacing:.09em; }
        .trade-state { display:flex; align-items:center; gap:6px; color:#9caf92; font:8px 'Space Mono',monospace; text-transform:uppercase; letter-spacing:.1em; }
        .trade-state i { width:6px;height:6px;border-radius:50%;background:#b4cc91; box-shadow:0 0 8px #b4cc9177; }
        .trade-feed { padding:8px 16px 4px; overflow:auto; flex:1; max-height:323px; }
        .trade-entry { display:grid; grid-template-columns:55px 1fr auto; gap:10px; min-height:47px; align-items:center; border-bottom:1px solid rgba(225,238,219,.075); }
        .trade-entry:last-child { border-bottom:0; }
        .trade-time { color:#7f9185; font:8px 'Space Mono',monospace; }
        .trade-main { min-width:0; }
        .trade-symbol { color:#e3e8dc; font:600 10px 'Space Mono',monospace; }
        .trade-owner { margin-top:3px; color:#91a196; font:8px 'DM Sans',sans-serif; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .trade-pnl { font:10px 'Space Mono',monospace; }
        .feed-foot { border-top:1px solid var(--line); padding:12px 16px; margin-top:auto; display:flex; justify-content:space-between; align-items:center; color:#85948b; font:9px 'Space Mono',monospace; }
        .feed-foot span:last-child { color:#bec8b2; }
        .trade-empty { padding:20px 3px; color:#a3b0a4; font:10px 'Space Mono',monospace; }
        .search-wrap { display:flex; align-items:center; gap:7px; border:1px solid rgba(222,236,217,.14); background:rgba(4,17,14,.28); border-radius:7px; padding:6px 8px; color:#91a196; }
        .search-wrap input { width:106px; outline:0; border:0; background:transparent; color:#eaf0e5; font:9px 'DM Sans',sans-serif; }
        .search-wrap input::placeholder { color:#829187; }
        .ladder { display:flex; gap:7px; align-items:center; border-top:1px solid rgba(225,238,219,.10); margin-top:9px; padding:10px 10px 0; }
        .ladder-label { color:#798b80; font:8px 'Space Mono',monospace; letter-spacing:.11em; text-transform:uppercase; }
        .ladder-item { display:flex; align-items:center; gap:5px; color:#c2ccbd; font:8px 'Space Mono',monospace; }
        .ladder-item i { width:5px;height:5px;border-radius:50%; }
        .ladder-item b { font-weight:600; }
        @media(max-width:900px) {
          .fleet-page { min-height:100dvh; padding:20px; overflow:auto; background-attachment:scroll; }
          .hero-panel { grid-template-columns:1fr 1fr; }
          .hero-main { grid-column:span 2; padding:8px 0 18px; }
          .hero-metric:nth-child(2) { border-left:0; }
          .content-grid { grid-template-columns:1fr; }
          .bot-columns, .bot-row { grid-template-columns:minmax(155px,1fr) minmax(115px,.75fr) minmax(135px,.9fr); }
          .bot-columns > :last-child, .bot-activity { display:none; }
        }
        @media(max-width:620px) {
          .fleet-page { padding:16px 12px; }
          .fleet-top { margin-bottom:18px; }
          .top-right > span:first-child { display:none; }
          .intro { align-items:flex-start; flex-direction:column; gap:12px; }
          .intro h1 { font-size:29px; }
          .hero-panel { padding:15px; grid-template-columns:1fr 1fr; }
          .fleet-equity { font-size:29px; }
          .hero-metric { padding:10px 8px; }
          .content-grid { gap:11px; }
          .panel-head { padding:0 12px; height:auto; min-height:58px; flex-wrap:wrap; gap:8px; }
          .filter-row { flex-wrap:wrap; }
          .search-wrap { display:none; }
          .bot-list { padding:0 8px 9px; }
          .bot-columns { display:none; }
          .bot-row { grid-template-columns:1fr 1fr; gap:13px 8px; padding:12px 10px; }
          .bot-position { padding-left:41px; }
          .bot-activity { display:block; }
          .params-line { grid-column:span 2; margin-top:0; }
          .ladder { flex-wrap:wrap; }
        }
      `}</style>
      <header className="fleet-top">
        <div className="fleet-brand"><span className="brand-mark"><Command size={13} /></span><span>Northstar / Streaming</span></div>
        <div className="top-right">
          <span>Operator workspace</span>
          <span className="session-tag"><i /> Market session · open</span>
        </div>
      </header>

      <section className="intro">
        <div>
          <div className="eyebrow">Fleet operations / 01</div>
          <h1>Bots</h1>
          <div className="intro-copy">One view across strategy state, capital, and the evidence behind each close.</div>
        </div>
        <div className="intro-meta"><Radio size={13} /> Streaming overview <span style={{ opacity: 0.45 }}>·</span> <Clock3 size={12} /> Current snapshot</div>
      </section>

      <section className="hero-panel">
        <div className="hero-main">
          <div className="metric-kicker">Fleet equity</div>
          <div className="fleet-equity">{fleetTotal != null ? fmtEq(fleetTotal) : "—"}</div>
          {fleetPnl != null && (
            <div className="hero-delta">
              {fleetPnl >= 0 ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}
              <span className="hero-delta-value">{fmtPnl(fleetPnl)} ({fmtPct(fleetPnlPct)})</span>
              <span className="delta-caption">realized + unrealized source total</span>
            </div>
          )}
        </div>
        <div className="hero-metric">
          <div className="metric-kicker">Active strategies</div>
          <div className="metric-value">{liveCount == null ? `— / ${bots.length}` : `${liveCount} / ${bots.length}`}</div>
          <div className="metric-note">Status is unknown when heartbeat state is absent</div>
        </div>
        <div className="hero-metric">
          <div className="metric-kicker">Open positions</div>
          <div className="metric-value">{totalOpen == null ? "—" : totalOpen}</div>
          <div className="metric-note">Across registered strategy identities</div>
        </div>
        <div className="hero-metric">
          <div className="metric-kicker">Journal evidence</div>
          <div className="metric-value">{journalQuery.isLoading ? "…" : journalQuery.isError ? "—" : liveFeedTrades.length.toString().padStart(2, "0")}</div>
          <div className="metric-note">{journalQuery.isError ? "Unavailable" : "Closed trades returned"}</div>
        </div>
      </section>

      <section className="content-grid">
        <div className="surface">
          <div className="panel-head">
            <div>
              <div className="panel-title"><WalletCards size={15} /> Strategy fleet <span className="trade-head-extra">{bots.length.toString().padStart(2, "0")} REGISTERED</span></div>
              <div className="panel-sub">Equity and position evidence by bot identity</div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <label className="search-wrap"><Search size={12} /><input aria-label="Search bots" placeholder="Find a bot" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
              <SlidersHorizontal size={13} style={{ color: "#9aa99d" }} />
            </div>
          </div>
          <div className="filter-row" style={{ padding: "10px 16px 2px" }}>
            {(["all", "live", "paused", "attention"] as const).map((key) => (
              <button key={key} type="button" onClick={() => setFilter(key)} className={`filter-button ${filter === key ? "active" : ""}`}>
                {key === "all" ? "All bots" : key === "attention" ? "Needs attention" : key}
              </button>
            ))}
          </div>
          <div className="bot-list">
            <div className="bot-columns"><span>Strategy / state</span><span>Equity · P&amp;L</span><span>Open positions</span><span>Recent closes</span></div>
            {visibleBots.length === 0 ? (
              <div className="trade-empty">No bots match this view. Clear the search or choose another state filter.</div>
            ) : visibleBots.map((bot) => (
              <article className="bot-row" key={bot.id} style={{ "--bot-accent": bot.color, "--bot-glow": bot.color } as CSSProperties}>
                <div className="bot-ident">
                  <div className="bot-sigil">{bot.name.split(/\s+/).map((part) => part[0]).slice(0, 2).join("")}</div>
                  <div>
                    <div className="bot-name">{bot.name}</div>
                    <div className="bot-venue">{bot.exchangeLabel}</div>
                    <div className="bot-status-wrap"><StatusPill bot={bot} /></div>
                  </div>
                </div>
                <div className="bot-equity">
                  <div className="tiny-label">Equity</div>
                  <div className="equity-value">{bot.equity != null ? fmtEq(bot.equity) : "—"}</div>
                  {bot.pnl != null ? (
                    <div className="equity-pnl" style={{ color: bot.pnl > 0 ? "#b7d49a" : bot.pnl < 0 ? "#df9d8e" : "#8a998e" }}>
                      {fmtPnl(bot.pnl)} <span style={{ opacity: .75 }}>({fmtPct(bot.pnl_pct)})</span>
                    </div>
                  ) : <div className="equity-pnl muted-dash">P&amp;L unavailable</div>}
                </div>
                <div className="bot-position">
                  <div className="tiny-label">Open positions</div>
                  <div className="position-count"><b>{bot.openPositionCount == null ? "—" : bot.openPositionCount}</b><span>open</span></div>
                  <div className="position-symbols">
                    {bot.openPositionSymbols.length ? bot.openPositionSymbols.join(" · ") : bot.openPositionCount === 0 ? "None" : bot.openPositionCount == null ? "Position data unavailable" : "Position symbols unavailable"}
                  </div>
                </div>
                <div className="bot-activity">
                  <div className="tiny-label">Recent closes</div>
                  {bot.recentTrades.length ? (
                    <div className="activity-list">
                      {bot.recentTrades.slice(0, 2).map((trade, index) => (
                        <div className="activity-item" key={`${trade.symbol}-${index}`}>
                          <span>{trade.symbol}</span>
                          <span style={{ color: trade.pnl_usd == null ? "#87958a" : trade.pnl_usd >= 0 ? "#b7d49a" : "#df9d8e" }}>{signedTrade(trade.pnl_usd)}</span>
                        </div>
                      ))}
                    </div>
                  ) : <div className="position-symbols">{bot.recentTradesLoading ? "Loading journal data" : bot.recentTradesError ? "Journal data unavailable" : bot.recentTradesAttributionUnavailable ? "Journal has no bot ID; not assigned" : "No recent trades returned for this bot"}</div>}
                </div>
                <div className="params-line"><CircleHelp size={12} /> <span>Strategy parameters · {bot.paramsText}</span></div>
              </article>
            ))}
            <div className="ladder">
              <span className="ladder-label">P&amp;L rank</span>
              {sortedForLadder.map((bot) => (
                <span className="ladder-item" key={bot.id}><i style={{ background: bot.color }} />{bot.name}<b style={{ color: bot.pnl == null ? "#8a998e" : bot.pnl > 0 ? "#b7d49a" : bot.pnl < 0 ? "#df9d8e" : "#8a998e" }}>{bot.pnl != null ? fmtPnl(bot.pnl) : "—"}</b></span>
              ))}
            </div>
          </div>
        </div>

        <aside className="surface trade-panel">
          <div className="panel-head">
            <div>
              <div className="panel-title"><Radio size={14} /> Recent trade tape</div>
              <div className="panel-sub">Closed journal fills · newest first</div>
            </div>
            <div className="trade-state"><i /> {journalQuery.isError ? "Error" : journalQuery.isLoading ? "Loading" : "Journal linked"}</div>
          </div>
          <div className="trade-feed">
            {liveFeedTrades.length === 0 ? (
              <div className="trade-empty">{journalQuery.isLoading ? "Loading journal data" : journalQuery.isError ? "Journal data unavailable" : "No recent trades returned"}</div>
            ) : liveFeedTrades.map((trade, index) => {
              const pnlUsd = trade.pnl_usd ?? trade.realized_pnl ?? null;
              const identity = getAttributedBotIdentity(trade.bot_id);
              return (
                <div className="trade-entry" key={trade.trade_id ?? index}>
                  <div className="trade-time">{fmtTime(trade.date)}</div>
                  <div className="trade-main"><div className="trade-symbol">{trade.ticker}</div><div className="trade-owner">{identity.displayName}</div></div>
                  <div className="trade-pnl" style={{ color: pnlUsd == null ? "#87958a" : pnlUsd >= 0 ? "#b7d49a" : "#df9d8e" }}>{signedTrade(pnlUsd)}</div>
                </div>
              );
            })}
          </div>
          <div className="feed-foot">
            <span>Attribution is tied to source bot ID</span>
            <span>{journalHasUnattributedTrades ? "Some unassigned" : "Attribution intact"}</span>
          </div>
        </aside>
      </section>
    </main>
  );
}