import {
  useFleetEquity,
  useKrakenPerformance,
  useKrakenStatus,
  useForexState,
  useForexPositions,
  usePoseidonState,
  useKrakenCurrentState,
  usePortfolio,
  type ForexPosition,
} from "@/hooks/use-trading";
import { Activity, TrendingUp, TrendingDown, Wifi, WifiOff } from "lucide-react";

const STARTING = 100_000;
const FLEET_STARTING = 800_000;

function fmt$(v: number, decimals = 0) {
  return `$${Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`;
}
function fmtPnl(v: number) {
  const abs = Math.abs(v);
  const str = abs >= 1000 ? `${(abs / 1000).toFixed(1)}k` : abs.toFixed(0);
  return v >= 0 ? `+$${str}` : `-$${str}`;
}
function fmtPct(v: number) {
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}

interface BotSnap {
  id: string;
  name: string;
  icon: string;
  exchange: string;
  accentColor: string;
  equity: number | null;
  paused: boolean;
  stale: boolean;
  heartbeatMins: number | null;
  wins: number;
  losses: number;
  openCount: number;
  openSymbols: string[];
  pauseReason?: string;
}

// ─── Per-Bot mini card ────────────────────────────────────────────────────────

function BotRow({ bot }: { bot: BotSnap }) {
  const pnl = bot.equity != null ? bot.equity - STARTING : null;
  const pnlPct = pnl != null ? (pnl / STARTING) * 100 : null;
  const total = bot.wins + bot.losses;
  const wr = total > 0 ? (bot.wins / total) * 100 : null;

  const pnlColor = pnl == null ? "#64748b" : pnl >= 0 ? "#34d399" : "#f87171";
  const wrColor = wr == null ? "#475569" : wr >= 50 ? "#34d399" : wr >= 38 ? "#fbbf24" : "#f87171";

  const statusColor = bot.paused ? "#f59e0b" : bot.stale ? "#64748b" : "#22c55e";
  const statusLabel = bot.paused ? "PAUSED" : bot.stale ? "STALE" : "LIVE";

  return (
    <div
      className="flex flex-col rounded-xl overflow-hidden relative"
      style={{
        background: "linear-gradient(160deg, rgba(15,23,42,0.97) 0%, rgba(2,6,23,0.98) 100%)",
        border: `1px solid ${bot.accentColor}20`,
        borderTop: `2px solid ${bot.accentColor}`,
      }}
    >
      {/* Subtle top glow */}
      <div
        className="absolute inset-x-0 top-0 h-12 pointer-events-none"
        style={{ background: `linear-gradient(180deg, ${bot.accentColor}0c 0%, transparent 100%)` }}
      />

      {/* ── Header row ── */}
      <div className="relative flex items-center gap-2 px-3 pt-3 pb-2">
        <span className="text-xl leading-none flex-shrink-0">{bot.icon}</span>
        <div className="flex-1 min-w-0">
          <div className="text-[11px] font-black text-white uppercase tracking-wide leading-none truncate">
            {bot.name}
          </div>
          <div className="text-[9px] font-semibold mt-0.5" style={{ color: `${bot.accentColor}99` }}>
            {bot.exchange}
          </div>
        </div>
        {/* Status */}
        <div
          className="flex items-center gap-1 px-1.5 py-0.5 rounded-full flex-shrink-0"
          style={{ background: `${statusColor}14`, border: `1px solid ${statusColor}35` }}
        >
          <span
            className="w-1.5 h-1.5 rounded-full flex-shrink-0"
            style={{
              background: statusColor,
              boxShadow: bot.paused || bot.stale ? "none" : `0 0 5px ${statusColor}`,
            }}
          />
          <span className="text-[8px] font-black uppercase tracking-wider" style={{ color: statusColor }}>
            {statusLabel}
          </span>
        </div>
      </div>

      {/* ── Equity + P&L ── */}
      <div className="px-3 pb-2.5">
        <div className="flex items-baseline gap-2">
          <span className="text-[18px] font-black font-mono text-white leading-none">
            {bot.equity != null ? fmt$(bot.equity) : "—"}
          </span>
          {pnlPct != null && (
            <span className="text-[10px] font-bold font-mono" style={{ color: pnlPct >= 0 ? "#34d39966" : "#f8717166" }}>
              {fmtPct(pnlPct)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1 mt-0.5">
          {pnl != null && (
            pnl >= 0
              ? <TrendingUp className="w-3 h-3 flex-shrink-0" style={{ color: pnlColor }} />
              : <TrendingDown className="w-3 h-3 flex-shrink-0" style={{ color: pnlColor }} />
          )}
          <span className="text-[13px] font-black font-mono" style={{ color: pnlColor }}>
            {pnl != null ? fmtPnl(pnl) : "—"}
          </span>
          <span className="text-[8px] font-bold text-slate-600 ml-0.5">P&L</span>
        </div>
      </div>

      {/* ── Divider ── */}
      <div className="mx-3" style={{ height: 1, background: `${bot.accentColor}14` }} />

      {/* ── Stats row ── */}
      <div className="px-3 py-2 grid grid-cols-3 gap-1">
        {/* Trades */}
        <div>
          <div className="text-[8px] font-bold uppercase tracking-widest text-slate-600 mb-0.5">TRADES</div>
          <div className="text-[11px] font-black font-mono">
            {total > 0 ? (
              <>
                <span className="text-emerald-400">{bot.wins}</span>
                <span className="text-slate-700">/</span>
                <span className="text-red-400">{bot.losses}</span>
              </>
            ) : (
              <span className="text-slate-700">—</span>
            )}
          </div>
        </div>

        {/* Win rate */}
        <div>
          <div className="text-[8px] font-bold uppercase tracking-widest text-slate-600 mb-0.5">WIN RATE</div>
          {wr != null ? (
            <div>
              <div className="text-[11px] font-black font-mono" style={{ color: wrColor }}>
                {wr.toFixed(0)}%
              </div>
              <div className="mt-0.5 h-1 rounded-full bg-slate-800 overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{ width: `${Math.min(wr, 100)}%`, background: wrColor }}
                />
              </div>
            </div>
          ) : (
            <div className="text-[11px] font-black font-mono text-slate-700">—</div>
          )}
        </div>

        {/* Open positions */}
        <div>
          <div className="text-[8px] font-bold uppercase tracking-widest text-slate-600 mb-0.5">OPEN</div>
          <div
            className="text-[11px] font-black font-mono"
            style={{ color: bot.openCount > 0 ? bot.accentColor : "#334155" }}
          >
            {bot.openCount > 0 ? bot.openCount : "—"}
          </div>
        </div>
      </div>

      {/* ── Open positions list ── */}
      {bot.openCount > 0 && (
        <>
          <div className="mx-3" style={{ height: 1, background: `${bot.accentColor}10` }} />
          <div className="px-3 pt-1.5 pb-2.5">
            <div className="flex flex-wrap gap-1">
              {bot.openSymbols.slice(0, 6).map((sym) => (
                <span
                  key={sym}
                  className="text-[9px] font-black font-mono px-1.5 py-0.5 rounded"
                  style={{ background: `${bot.accentColor}18`, color: `${bot.accentColor}cc` }}
                >
                  {sym.replace("/USD", "").replace("USD", "")}
                </span>
              ))}
              {bot.openSymbols.length > 6 && (
                <span className="text-[9px] font-bold text-slate-600 self-center">
                  +{bot.openSymbols.length - 6}
                </span>
              )}
            </div>
          </div>
        </>
      )}

      {/* ── Pause reason (if paused) ── */}
      {bot.paused && bot.pauseReason && (
        <div
          className="mx-3 mb-2.5 px-2 py-1 rounded-lg text-[8px] font-bold text-amber-400/70 leading-tight"
          style={{ background: "rgba(245,158,11,0.07)", border: "1px solid rgba(245,158,11,0.15)" }}
        >
          {bot.pauseReason}
        </div>
      )}

      {/* ── Heartbeat ── */}
      {!bot.paused && bot.heartbeatMins != null && (
        <div className="absolute bottom-2 right-2.5 flex items-center gap-1">
          {bot.heartbeatMins < 10
            ? <Wifi className="w-2.5 h-2.5 text-emerald-600" />
            : <WifiOff className="w-2.5 h-2.5 text-slate-700" />
          }
          <span className="text-[8px] font-mono text-slate-700">{Math.round(bot.heartbeatMins)}m</span>
        </div>
      )}
    </div>
  );
}

// ─── Fleet header bar ─────────────────────────────────────────────────────────

interface FleetHeaderProps {
  bots: BotSnap[];
  serverTotal?: { equity: number; pnl: number; pnl_pct: number } | null;
}

function FleetHeader({ bots, serverTotal }: FleetHeaderProps) {
  // Prefer the server-computed fleet total (bot_portfolio aggregate); fall back to summing loaded bots
  const equities = bots.map(b => b.equity).filter((e): e is number => e != null);
  const fleetEquity = serverTotal?.equity ?? (equities.length > 0 ? equities.reduce((a, b) => a + b, 0) : null);
  const fleetPnl = serverTotal?.pnl ?? (fleetEquity != null ? fleetEquity - FLEET_STARTING : null);
  const fleetPnlPct = serverTotal?.pnl_pct ?? (fleetPnl != null ? (fleetPnl / FLEET_STARTING) * 100 : null);

  const allTrades = bots.reduce((a, b) => a + b.wins + b.losses, 0);
  const allWins = bots.reduce((a, b) => a + b.wins, 0);
  const fleetWr = allTrades > 0 ? (allWins / allTrades) * 100 : null;

  const active = bots.filter(b => !b.paused).length;
  const paused = bots.filter(b => b.paused).length;

  const pnlColor = fleetPnl == null ? "#64748b" : fleetPnl >= 0 ? "#34d399" : "#f87171";

  return (
    <div className="flex items-center gap-0 divide-x divide-white/[0.06]">
      {/* Fleet equity */}
      <div className="px-5 py-3">
        <div className="text-[9px] font-bold uppercase tracking-widest text-slate-600 mb-0.5">Fleet Equity</div>
        <div className="text-[17px] font-black font-mono text-white">
          {fleetEquity != null ? fmt$(fleetEquity) : "—"}
        </div>
      </div>

      {/* Fleet P&L */}
      <div className="px-5 py-3">
        <div className="text-[9px] font-bold uppercase tracking-widest text-slate-600 mb-0.5">Total P&L</div>
        <div className="flex items-baseline gap-1.5">
          <div className="text-[17px] font-black font-mono" style={{ color: pnlColor }}>
            {fleetPnl != null ? fmtPnl(fleetPnl) : "—"}
          </div>
          {fleetPnlPct != null && (
            <div className="text-[10px] font-bold" style={{ color: `${pnlColor}88` }}>
              {fmtPct(fleetPnlPct)}
            </div>
          )}
        </div>
      </div>

      {/* Win rate */}
      <div className="px-5 py-3">
        <div className="text-[9px] font-bold uppercase tracking-widest text-slate-600 mb-0.5">Fleet Win Rate</div>
        <div className="flex items-baseline gap-1.5">
          <div
            className="text-[17px] font-black font-mono"
            style={{ color: fleetWr == null ? "#475569" : fleetWr >= 50 ? "#34d399" : fleetWr >= 38 ? "#fbbf24" : "#f87171" }}
          >
            {fleetWr != null ? `${fleetWr.toFixed(1)}%` : "—"}
          </div>
          {allTrades > 0 && (
            <div className="text-[9px] font-mono text-slate-600">
              {allWins}W/{allTrades - allWins}L
            </div>
          )}
        </div>
      </div>

      {/* Bot status counts */}
      <div className="px-5 py-3">
        <div className="text-[9px] font-bold uppercase tracking-widest text-slate-600 mb-0.5">Bots</div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" style={{ boxShadow: "0 0 5px #22c55e" }} />
            <span className="text-[13px] font-black font-mono text-white">{active}</span>
            <span className="text-[9px] text-slate-600">live</span>
          </div>
          {paused > 0 && (
            <div className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
              <span className="text-[13px] font-black font-mono text-amber-400">{paused}</span>
              <span className="text-[9px] text-slate-600">paused</span>
            </div>
          )}
        </div>
      </div>

      {/* Open positions fleet-wide */}
      <div className="px-5 py-3">
        <div className="text-[9px] font-bold uppercase tracking-widest text-slate-600 mb-0.5">Open Positions</div>
        <div className="text-[17px] font-black font-mono text-white">
          {bots.reduce((a, b) => a + b.openCount, 0)}
        </div>
      </div>

      {/* Live indicator */}
      <div className="ml-auto px-5 py-3 flex items-center gap-1.5">
        <Activity className="w-3 h-3 text-emerald-500" style={{ filter: "drop-shadow(0 0 4px #22c55e)" }} />
        <span className="text-[9px] font-bold text-emerald-600 uppercase tracking-wider">Live</span>
      </div>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function BotsPage() {
  const { data: fleetEq } = useFleetEquity();
  const { data: portfolio } = usePortfolio();

  // Kraken bots — legacy IDs
  const { data: davyPerf }  = useKrakenPerformance("davy-jones");
  const { data: davySt }    = useKrakenStatus("davy-jones");
  const { data: bbPerf }    = useKrakenPerformance("blackbeard");
  const { data: bbSt }      = useKrakenStatus("blackbeard");
  // Specialist bots
  const { data: forexState }   = useForexState();
  const { data: forexPosRaw }  = useForexPositions();
  const { data: posState }     = usePoseidonState();
  const { data: kcState }      = useKrakenCurrentState();

  // Oracle positions
  const oraclePositions = (portfolio?.positions ?? []).filter(p => (p.market_value ?? 0) > 10);
  const oracleSymbols   = oraclePositions.map(p => p.symbol);

  // Forex positions
  const forexPos: ForexPosition[] = Array.isArray(forexPosRaw)
    ? (forexPosRaw as ForexPosition[])
    : ((forexPosRaw as { positions?: ForexPosition[] } | null)?.positions ?? []);
  const forexSymbols = forexPos.map(p => p.pair);

  // Poseidon positions
  const posSymbols = (posState?.open_trades ?? []).map(t =>
    `${t.asset_a.replace("/USD", "")}/${t.asset_b.replace("/USD", "")}`
  );

  // KC positions
  const kcSymbols = (kcState?.open_positions_list ?? []).map(p => p.symbol);

  // Kraken bot open positions helper
  function krakenOpenSymbols(st: typeof davySt) {
    return (st?.open_positions ?? []).map((p: { symbol: string }) => p.symbol);
  }

  const bots: BotSnap[] = [
    {
      id: "oracle",
      name: "Oracle",
      icon: "🔮",
      exchange: "Alpaca · Stocks",
      accentColor: "#22d3ee",
      equity: fleetEq?.oracle?.equity ?? (portfolio as { account?: { equity?: number } } | undefined)?.account?.equity ?? null,
      paused: false,
      stale: fleetEq?.oracle?.stale ?? false,
      heartbeatMins: fleetEq?.oracle?.heartbeat_mins_ago ?? null,
      wins: 0,
      losses: 0,
      openCount: oracleSymbols.length,
      openSymbols: oracleSymbols,
    },
    {
      id: "spy_qqq_trend",
      name: "SPY/QQQ Trend",
      icon: "📈",
      exchange: "Alpaca · ETFs",
      accentColor: "#3b82f6",
      equity: fleetEq?.davy_jones?.equity ?? null,
      paused: davySt?.bot_paused ?? false,
      stale: fleetEq?.davy_jones?.stale ?? false,
      heartbeatMins: fleetEq?.davy_jones?.heartbeat_mins_ago ?? null,
      wins: davyPerf?.win_count ?? 0,
      losses: davyPerf?.loss_count ?? 0,
      openCount: davySt?.open_positions?.length ?? 0,
      openSymbols: krakenOpenSymbols(davySt),
    },
    {
      id: "jerome_macro",
      name: "Jerome",
      icon: "🏛️",
      exchange: "Alpaca · Macro",
      accentColor: "#f97316",
      equity: fleetEq?.blackbeard?.equity ?? null,
      paused: bbSt?.bot_paused ?? false,
      stale: fleetEq?.blackbeard?.stale ?? false,
      heartbeatMins: fleetEq?.blackbeard?.heartbeat_mins_ago ?? null,
      wins: bbPerf?.win_count ?? 0,
      losses: bbPerf?.loss_count ?? 0,
      openCount: bbSt?.open_positions?.length ?? 0,
      openSymbols: krakenOpenSymbols(bbSt),
    },
    {
      id: "forex_gump",
      name: "Forex Gump",
      icon: "🧭",
      exchange: "Oanda · Forex",
      accentColor: "#06b6d4",
      equity: fleetEq?.navigator?.equity ?? null,
      paused: forexState?.paused ?? false,
      pauseReason: forexState?.paused ? (forexState?.circuit_breaker_reason ?? "Paused") : undefined,
      stale: fleetEq?.navigator?.stale ?? false,
      heartbeatMins: fleetEq?.navigator?.heartbeat_mins_ago ?? null,
      wins: forexState?.total_wins ?? 0,
      losses: (forexState?.total_trades ?? 0) - (forexState?.total_wins ?? 0),
      openCount: forexPos.length,
      openSymbols: forexSymbols,
    },
    {
      id: "poseidon_momentum",
      name: "Poseidon",
      icon: "🔱",
      exchange: "Kraken · Crypto Pairs",
      accentColor: "#8b5cf6",
      equity: fleetEq?.poseidon?.equity ?? null,
      paused: posState?.paused ?? false,
      pauseReason: posState?.paused ? "Paused" : undefined,
      stale: fleetEq?.poseidon?.stale ?? false,
      heartbeatMins: fleetEq?.poseidon?.heartbeat_mins_ago ?? null,
      wins: posState?.total_wins ?? 0,
      losses: (posState?.total_trades ?? 0) - (posState?.total_wins ?? 0),
      openCount: posSymbols.length,
      openSymbols: posSymbols,
    },
    {
      id: "kraken_trend",
      name: "Kraken Trend",
      icon: "🌊",
      exchange: "Kraken · Crypto Trend",
      accentColor: "#0ea5e9",
      equity: fleetEq?.kraken_current?.equity ?? null,
      paused: kcState?.paused ?? false,
      pauseReason: kcState?.paused ? "Paused" : undefined,
      stale: fleetEq?.kraken_current?.stale ?? false,
      heartbeatMins: fleetEq?.kraken_current?.heartbeat_mins_ago ?? null,
      wins: kcState?.total_wins ?? 0,
      losses: (kcState?.total_trades ?? 0) - (kcState?.total_wins ?? 0),
      openCount: kcSymbols.length,
      openSymbols: kcSymbols,
    },
  ];

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col">
      {/* ── Fleet header ── */}
      <div
        className="border-b border-white/[0.05] flex-shrink-0"
        style={{ background: "linear-gradient(180deg, rgba(15,23,42,0.98) 0%, rgba(2,6,23,0.99) 100%)" }}
      >
        <FleetHeader bots={bots} serverTotal={fleetEq?.fleet_total ?? null} />
      </div>

      {/* ── 3×3 Bot grid ── */}
      <div className="flex-1 p-3">
        <div className="grid grid-cols-3 gap-3 h-full" style={{ gridTemplateRows: "repeat(3, 1fr)" }}>
          {bots.map(bot => (
            <BotRow key={bot.id} bot={bot} />
          ))}
        </div>
      </div>
    </div>
  );
}
