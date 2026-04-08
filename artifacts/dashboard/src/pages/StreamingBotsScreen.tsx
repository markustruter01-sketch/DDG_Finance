import { usePortfolio, useKrakenPerformance, useKrakenStatus, useOptionsState, useOptionsPositions, useForexState, useForexPositions, type ForexPosition } from "@/hooks/use-trading";
import { TrendingUp, TrendingDown, Activity } from "lucide-react";

const STARTING_BALANCE = 100_000;

function fmtK(v: number) {
  const abs = Math.abs(v);
  if (abs >= 1_000) return v >= 0 ? `+$${(abs / 1000).toFixed(1)}k` : `-$${(abs / 1000).toFixed(1)}k`;
  return v >= 0 ? `+$${abs.toFixed(0)}` : `-$${abs.toFixed(0)}`;
}

function fmtEq(v: number) {
  return `$${Math.round(v).toLocaleString()}`;
}

interface BotCardData {
  id: string;
  name: string;
  icon: string;
  exchange: string;
  color: string;
  glow: string;
  equity: number | null;
  paused: boolean;
  winCount: number;
  lossCount: number;
  openPositions: number;
  topPair?: string;
}

interface StreamBotCardProps {
  bot: BotCardData;
}

function StreamBotCard({ bot }: StreamBotCardProps) {
  const { equity, color, glow } = bot;
  const truePnl = equity != null ? equity - STARTING_BALANCE : null;
  const totalTrades = bot.winCount + bot.lossCount;
  const winRate = totalTrades > 0 ? (bot.winCount / totalTrades) * 100 : null;

  const pnlColor =
    truePnl == null ? "#94a3b8"
    : truePnl >= 0 ? "#34d399"
    : "#f87171";

  const winRateColor =
    winRate == null ? "#94a3b8"
    : winRate >= 55 ? "#34d399"
    : winRate >= 45 ? "#fbbf24"
    : "#f87171";

  return (
    <div
      className="flex-1 min-w-0 flex flex-col relative overflow-hidden"
      style={{
        background: "linear-gradient(180deg, rgba(15,23,42,0.98) 0%, rgba(2,6,23,0.99) 100%)",
        border: `1px solid ${color}22`,
        borderTop: `2px solid ${color}`,
        borderRadius: 10,
      }}
    >
      {/* Subtle glow behind top border */}
      <div
        className="absolute top-0 left-0 right-0 h-16 pointer-events-none"
        style={{ background: `linear-gradient(180deg, ${color}0d 0%, transparent 100%)` }}
      />

      {/* Header */}
      <div className="relative px-3 pt-3 pb-2 flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-2xl leading-none">{bot.icon}</span>
          <div>
            <div className="text-xs font-black text-white uppercase tracking-wide leading-tight">{bot.name}</div>
            <div
              className="text-[9px] font-bold uppercase tracking-wider"
              style={{ color: `${color}99` }}
            >
              {bot.exchange}
            </div>
          </div>
        </div>

        {/* Status badge */}
        <div
          className="flex items-center gap-1 px-2 py-0.5 rounded-full shrink-0"
          style={{
            background: bot.paused ? "rgba(245,158,11,0.12)" : "rgba(34,197,94,0.12)",
            border: `1px solid ${bot.paused ? "rgba(245,158,11,0.3)" : "rgba(34,197,94,0.3)"}`,
          }}
        >
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{
              background: bot.paused ? "#f59e0b" : "#22c55e",
              boxShadow: bot.paused ? "0 0 6px #f59e0b" : `0 0 6px #22c55e`,
            }}
          />
          <span
            className="text-[9px] font-black uppercase tracking-wider"
            style={{ color: bot.paused ? "#f59e0b" : "#22c55e" }}
          >
            {bot.paused ? "PAUSED" : "LIVE"}
          </span>
        </div>
      </div>

      {/* Equity */}
      <div className="px-3 pb-1">
        <div className="text-[9px] font-bold uppercase tracking-widest" style={{ color: `${color}70` }}>
          EQUITY
        </div>
        <div className="text-xl font-black font-mono text-white tracking-tight leading-tight">
          {equity != null ? fmtEq(equity) : "—"}
        </div>
      </div>

      {/* P&L */}
      <div className="px-3 pb-2">
        <div className="flex items-center gap-1">
          {truePnl != null && (
            truePnl >= 0
              ? <TrendingUp className="w-3 h-3 shrink-0" style={{ color: pnlColor }} />
              : <TrendingDown className="w-3 h-3 shrink-0" style={{ color: pnlColor }} />
          )}
          <span
            className="text-sm font-black font-mono tracking-tight"
            style={{ color: pnlColor }}
          >
            {truePnl != null ? fmtK(truePnl) : "—"}
          </span>
          <span className="text-[9px] font-bold" style={{ color: "rgba(148,163,184,0.4)" }}>
            ALL-TIME
          </span>
        </div>
      </div>

      {/* Divider */}
      <div className="mx-3 mb-2" style={{ height: 1, background: `${color}15` }} />

      {/* Stats grid */}
      <div className="px-3 pb-2 grid grid-cols-2 gap-x-2 gap-y-1">
        <div>
          <div className="text-[8px] font-bold uppercase tracking-widest" style={{ color: "rgba(148,163,184,0.4)" }}>
            W / L
          </div>
          <div className="text-xs font-black font-mono">
            <span style={{ color: "#34d399" }}>{bot.winCount}</span>
            <span style={{ color: "rgba(148,163,184,0.3)" }}> / </span>
            <span style={{ color: "#f87171" }}>{bot.lossCount}</span>
          </div>
        </div>
        <div>
          <div className="text-[8px] font-bold uppercase tracking-widest" style={{ color: "rgba(148,163,184,0.4)" }}>
            WIN RATE
          </div>
          <div
            className="text-xs font-black font-mono"
            style={{ color: winRateColor }}
          >
            {winRate != null ? `${winRate.toFixed(0)}%` : "—"}
          </div>
        </div>
        <div>
          <div className="text-[8px] font-bold uppercase tracking-widest" style={{ color: "rgba(148,163,184,0.4)" }}>
            POSITIONS
          </div>
          <div className="text-xs font-black font-mono text-white">
            {bot.openPositions > 0 ? (
              <span>
                <span style={{ color }}>{bot.openPositions}</span>
                <span style={{ color: "rgba(148,163,184,0.5)" }}> open</span>
              </span>
            ) : (
              <span style={{ color: "rgba(148,163,184,0.35)" }}>none</span>
            )}
          </div>
        </div>
        <div>
          <div className="text-[8px] font-bold uppercase tracking-widest" style={{ color: "rgba(148,163,184,0.4)" }}>
            TRADES
          </div>
          <div className="text-xs font-black font-mono" style={{ color: "rgba(203,213,225,0.8)" }}>
            {totalTrades}
          </div>
        </div>
      </div>

      {/* Top position hint */}
      {bot.topPair && (
        <div className="mt-auto px-3 pb-3">
          <div
            className="text-[9px] font-bold truncate px-2 py-1 rounded"
            style={{ background: `${color}12`, color: `${color}cc`, border: `1px solid ${color}20` }}
          >
            ⬡ {bot.topPair}
          </div>
        </div>
      )}

      {!bot.topPair && <div className="mt-auto" />}
    </div>
  );
}

export default function StreamingBotsScreen() {
  const { data: portfolio } = usePortfolio();
  const { data: davyPerf } = useKrakenPerformance("davy-jones");
  const { data: davyStatus } = useKrakenStatus("davy-jones");
  const { data: bbPerf } = useKrakenPerformance("blackbeard");
  const { data: bbStatus } = useKrakenStatus("blackbeard");
  const { data: caPerf } = useKrakenPerformance("calypso");
  const { data: caStatus } = useKrakenStatus("calypso");
  const { data: optionsState } = useOptionsState();
  const { data: optionsPosRaw } = useOptionsPositions();
  const { data: forexState } = useForexState();
  const { data: forexPosRaw } = useForexPositions();

  const oracleEquity = portfolio?.account?.equity ?? null;
  const oraclePositions = (portfolio?.positions ?? []).filter((p) => (p.market_value ?? 0) > 10);
  const oracleTopPair = oraclePositions[0]?.symbol;

  const davyEquity = davyPerf?.current_equity ?? davyStatus?.total_equity_usd ?? null;
  const davyTopPair = davyStatus?.open_positions?.[0]?.symbol;

  const bbEquity = bbPerf?.current_equity ?? bbStatus?.total_equity_usd ?? null;
  const bbTopPair = bbStatus?.open_positions?.[0]?.symbol;

  const caEquity = caPerf?.current_equity ?? caStatus?.total_equity_usd ?? null;
  const caTopPair = caStatus?.open_positions?.[0]?.symbol;

  const apexEquity = optionsState?.total_equity ?? optionsState?.paper_equity ?? null;
  const apexPositionsArr = Array.isArray(optionsPosRaw) ? optionsPosRaw : [];
  const apexTopPair = apexPositionsArr[0]?.symbol;

  const navEquity = forexState?.total_equity ?? forexState?.paper_equity ?? null;
  const rawForexPos: ForexPosition[] = Array.isArray(forexPosRaw)
    ? (forexPosRaw as ForexPosition[])
    : ((forexPosRaw as { positions?: ForexPosition[] } | null)?.positions ?? []);
  const navTopPair = rawForexPos[0]?.pair;

  const allEquities = [oracleEquity, davyEquity, bbEquity, caEquity, apexEquity, navEquity].filter((e): e is number => e != null);
  const fleetTotal = allEquities.length === 6 ? allEquities.reduce((s, e) => s + e, 0) : null;
  const fleetPnl = fleetTotal != null ? fleetTotal - 600_000 : null;

  const bots: BotCardData[] = [
    {
      id: "oracle",
      name: "Oracle",
      icon: "🔮",
      exchange: "Alpaca · Stocks",
      color: "#22d3ee",
      glow: "#22d3ee",
      equity: oracleEquity,
      paused: false,
      winCount: 0,
      lossCount: 0,
      openPositions: oraclePositions.length,
      topPair: oracleTopPair,
    },
    {
      id: "davy-jones",
      name: "Davy Jones",
      icon: "⚓",
      exchange: "Kraken · Crypto",
      color: "#f59e0b",
      glow: "#f59e0b",
      equity: davyEquity,
      paused: davyStatus?.bot_paused ?? false,
      winCount: davyPerf?.win_count ?? 0,
      lossCount: davyPerf?.loss_count ?? 0,
      openPositions: davyStatus?.open_positions?.length ?? 0,
      topPair: davyTopPair,
    },
    {
      id: "blackbeard",
      name: "Blackbeard",
      icon: "🏴‍☠️",
      exchange: "Kraken · Crypto",
      color: "#ef4444",
      glow: "#ef4444",
      equity: bbEquity,
      paused: bbStatus?.bot_paused ?? false,
      winCount: bbPerf?.win_count ?? 0,
      lossCount: bbPerf?.loss_count ?? 0,
      openPositions: bbStatus?.open_positions?.length ?? 0,
      topPair: bbTopPair,
    },
    {
      id: "calypso",
      name: "Calypso",
      icon: "🌊",
      exchange: "Kraken · Crypto",
      color: "#8b5cf6",
      glow: "#8b5cf6",
      equity: caEquity,
      paused: caStatus?.bot_paused ?? false,
      winCount: caPerf?.win_count ?? 0,
      lossCount: caPerf?.loss_count ?? 0,
      openPositions: caStatus?.open_positions?.length ?? 0,
      topPair: caTopPair,
    },
    {
      id: "apex",
      name: "Apex Predator",
      icon: "🦅",
      exchange: "Alpaca · Options",
      color: "#f97316",
      glow: "#f97316",
      equity: apexEquity,
      paused: optionsState?.paused ?? false,
      winCount: optionsState?.total_wins ?? 0,
      lossCount: (optionsState?.total_trades ?? 0) - (optionsState?.total_wins ?? 0),
      openPositions: apexPositionsArr.length,
      topPair: apexTopPair,
    },
    {
      id: "navigator",
      name: "Navigator",
      icon: "🧭",
      exchange: "Oanda · Forex",
      color: "#10b981",
      glow: "#10b981",
      equity: navEquity,
      paused: forexState?.paused ?? false,
      winCount: forexState?.total_wins ?? 0,
      lossCount: (forexState?.total_trades ?? 0) - (forexState?.total_wins ?? 0),
      openPositions: rawForexPos.length,
      topPair: navTopPair,
    },
  ];

  const fleetPnlColor = fleetPnl == null ? "#94a3b8" : fleetPnl >= 0 ? "#34d399" : "#f87171";

  return (
    <div
      className="h-full w-full flex flex-col"
      style={{ background: "linear-gradient(180deg, #020617 0%, #030712 100%)" }}
    >
      {/* Header strip */}
      <div
        className="shrink-0 flex items-center justify-between px-4"
        style={{
          height: 44,
          borderBottom: "1px solid rgba(255,255,255,0.05)",
          background: "rgba(2,6,23,0.95)",
        }}
      >
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <Activity className="w-3.5 h-3.5" style={{ color: "#22d3ee" }} />
            <span className="text-xs font-black uppercase tracking-widest text-white">Bot Fleet</span>
            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded" style={{ background: "rgba(34,211,238,0.1)", color: "#22d3ee", border: "1px solid rgba(34,211,238,0.2)" }}>6 BOTS</span>
          </div>
        </div>

        <div className="flex items-center gap-6">
          <div className="text-center">
            <div className="text-[8px] font-bold uppercase tracking-widest" style={{ color: "rgba(148,163,184,0.4)" }}>FLEET EQUITY</div>
            <div className="text-xs font-black font-mono text-white">
              {fleetTotal != null ? `$${Math.round(fleetTotal).toLocaleString()}` : "—"}
            </div>
          </div>
          <div className="text-center">
            <div className="text-[8px] font-bold uppercase tracking-widest" style={{ color: "rgba(148,163,184,0.4)" }}>COMBINED P&L</div>
            <div className="text-xs font-black font-mono" style={{ color: fleetPnlColor }}>
              {fleetPnl != null ? fmtK(fleetPnl) : "—"}
            </div>
          </div>
          <div className="text-center">
            <div className="text-[8px] font-bold uppercase tracking-widest" style={{ color: "rgba(148,163,184,0.4)" }}>STARTING CAPITAL</div>
            <div className="text-xs font-black font-mono" style={{ color: "rgba(203,213,225,0.6)" }}>$600,000</div>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: "#22c55e", boxShadow: "0 0 6px #22c55e" }} />
          <span className="text-[10px] font-black uppercase tracking-widest" style={{ color: "#22c55e" }}>ALL SYSTEMS LIVE</span>
        </div>
      </div>

      {/* Bot cards row */}
      <div className="flex-1 min-h-0 flex gap-2.5 p-3">
        {bots.map((bot) => (
          <StreamBotCard key={bot.id} bot={bot} />
        ))}
      </div>

      {/* Footer */}
      <div
        className="shrink-0 flex items-center justify-center px-4 gap-8"
        style={{
          height: 28,
          borderTop: "1px solid rgba(255,255,255,0.04)",
          background: "rgba(2,6,23,0.9)",
        }}
      >
        {bots.map((bot) => {
          const pnl = bot.equity != null ? bot.equity - STARTING_BALANCE : null;
          return (
            <div key={bot.id} className="flex items-center gap-1.5">
              <span className="text-[10px]">{bot.icon}</span>
              <span className="text-[9px] font-bold" style={{ color: bot.color }}>
                {bot.name.split(" ")[0].toUpperCase()}
              </span>
              <span
                className="text-[9px] font-black font-mono"
                style={{ color: pnl == null ? "#94a3b8" : pnl >= 0 ? "#34d399" : "#f87171" }}
              >
                {pnl != null ? fmtK(pnl) : "—"}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
