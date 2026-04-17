import { usePortfolio, useKrakenPerformance, useKrakenStatus, useFleetParams, useOptionsState, useOptionsPositions, useForexState, useForexPositions, usePoseidonState, useKrakenCurrentState, type ForexPosition, type BotParamBounds } from "@/hooks/use-trading";
import { TrendingUp, TrendingDown, Activity } from "lucide-react";
import { ParameterScale } from "@/components/ParameterScale";
import { DDGBadge } from "@/components/DDGBadge";
import { FLEET_STARTING_CAPITAL } from "@/lib/dashboard-shared";

const STARTING_BALANCE = 100_000;

function fmtK(v: number) {
  const abs = Math.abs(v);
  if (abs >= 1_000) return v >= 0 ? `+$${(abs / 1000).toFixed(1)}k` : `-$${(abs / 1000).toFixed(1)}k`;
  return v >= 0 ? `+$${abs.toFixed(0)}` : `-$${abs.toFixed(0)}`;
}

function fmtEq(v: number) {
  return `$${Math.round(v).toLocaleString()}`;
}

interface ConfigRow {
  label: string;
  value: string;
  color?: string;
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
  glow: string;
  equity: number | null;
  paused: boolean;
  winCount: number;
  lossCount: number;
  openPositions: number;
  topPair?: string;
  strategyConfig?: ConfigRow[];
  openPositionsList?: OpenPosSummary[];
  krakenBotKey?: string;
  isBest?: boolean;
}

interface StreamBotCardProps {
  bot: BotCardData;
}

function StreamBotCard({ bot }: StreamBotCardProps) {
  const { data: fleetParams } = useFleetParams();
  const { equity, color, glow, isBest } = bot;
  const truePnl = equity != null ? equity - STARTING_BALANCE : null;

  // Kraken bots: use live bounds + current from fleet params (same as normal bots page)
  const krakenBotData = bot.krakenBotKey ? fleetParams?.bots?.[bot.krakenBotKey] : undefined;
  const krakenCurrent: Record<string, number> = krakenBotData?.current ?? {};
  const krakenBounds: Record<string, BotParamBounds> = krakenBotData?.bounds ?? {};

  // Non-Kraken bots: use static strategyConfig text rows
  const effectiveStrategyConfig: ConfigRow[] = bot.krakenBotKey ? [] : (bot.strategyConfig ?? []);
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
    <>
      {isBest && (
        <style>{`
          @keyframes fireGlow {
            0%   { box-shadow: 0 0 4px 1px #ff4500, 0 0 8px 2px #ff6a00, 0 0 15px 5px #ffd700; border-color: #ff4500; }
            25%  { box-shadow: 0 0 5px 2px #ff6a00, 0 0 11px 3px #ff4500, 0 0 20px 5px #ff8c00; border-color: #ff6a00; }
            50%  { box-shadow: 0 0 7px 2px #ffd700, 0 0 13px 4px #ff6a00, 0 0 23px 7px #ff4500; border-color: #ffd700; }
            75%  { box-shadow: 0 0 5px 2px #ff8c00, 0 0 11px 3px #ffd700, 0 0 18px 5px #ff6a00; border-color: #ff8c00; }
            100% { box-shadow: 0 0 4px 1px #ff4500, 0 0 8px 2px #ff6a00, 0 0 15px 5px #ffd700; border-color: #ff4500; }
          }
        `}</style>
      )}
    <div
      className="flex-1 min-w-0 flex flex-col relative overflow-hidden"
      style={
        isBest
          ? {
              background: "linear-gradient(180deg, rgba(30,10,5,0.98) 0%, rgba(2,6,23,0.99) 100%)",
              border: "2px solid #ff4500",
              borderRadius: 10,
              animation: "fireGlow 1.8s ease-in-out infinite",
            }
          : {
              background: "linear-gradient(180deg, rgba(15,23,42,0.98) 0%, rgba(2,6,23,0.99) 100%)",
              border: `1px solid ${color}22`,
              borderTop: `2px solid ${color}`,
              borderRadius: 10,
            }
      }
    >
      {/* Subtle glow behind top border */}
      <div
        className="absolute top-0 left-0 right-0 h-16 pointer-events-none"
        style={{ background: isBest ? "linear-gradient(180deg, rgba(255,80,0,0.12) 0%, transparent 100%)" : `linear-gradient(180deg, ${color}0d 0%, transparent 100%)` }}
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

      {/* P&L — 4× bigger */}
      <div className="px-3 pb-2">
        <div className="flex items-center gap-1.5 mb-0.5">
          {truePnl != null && (
            truePnl >= 0
              ? <TrendingUp className="w-4 h-4 shrink-0" style={{ color: pnlColor }} />
              : <TrendingDown className="w-4 h-4 shrink-0" style={{ color: pnlColor }} />
          )}
          <span
            className="font-black font-mono tracking-tight leading-none"
            style={{ color: pnlColor, fontSize: 52 }}
          >
            {truePnl != null ? fmtK(truePnl) : "—"}
          </span>
        </div>
        <span className="text-[9px] font-bold" style={{ color: "rgba(148,163,184,0.4)" }}>
          ALL-TIME P&L
        </span>
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

      {/* Parameters — Kraken bots: ParameterScale sliders (same as normal bots page) */}
      {bot.krakenBotKey && (
        <>
          <div className="mx-3 mb-1" style={{ height: 1, background: `${color}10` }} />
          <div className="px-3 pb-2">
            <div
              className="text-[7px] font-black uppercase tracking-widest mb-2"
              style={{ color: `${color}60` }}
            >
              PARAMETERS
            </div>
            <div className="space-y-2">
              {PARAM_ORDER.map((param) => {
                const cfg = PARAM_LABELS[param];
                const b = krakenBounds[param];
                const val = krakenCurrent[param];
                if (!cfg) return null;
                if (!b || val == null) {
                  return (
                    <div key={param}>
                      <div className="flex justify-between items-center mb-1">
                        <span className="text-[10px] text-slate-400 font-mono">{cfg.label}</span>
                        <span className="text-[10px] font-mono text-slate-600">···</span>
                      </div>
                      <div className="relative h-2 rounded-full bg-slate-800/80" />
                    </div>
                  );
                }
                return (
                  <ParameterScale
                    key={param}
                    label={cfg.label}
                    min={b.min}
                    max={b.max}
                    current={val}
                    format={cfg.format}
                    color={color}
                  />
                );
              })}
            </div>
          </div>
        </>
      )}

      {/* Strategy Config strip — non-Kraken bots: text label:value rows */}
      {!bot.krakenBotKey && effectiveStrategyConfig.length > 0 && (
        <>
          <div className="mx-3 mb-1" style={{ height: 1, background: `${color}10` }} />
          <div className="px-3 pb-2">
            <div
              className="text-[7px] font-black uppercase tracking-widest mb-1"
              style={{ color: `${color}60` }}
            >
              STRATEGY CONFIG
            </div>
            <div className="grid grid-cols-2 gap-x-2 gap-y-0.5">
              {effectiveStrategyConfig.map((row) => (
                <div key={row.label} className="flex items-center gap-1 min-w-0">
                  <span
                    className="text-[7px] font-bold uppercase tracking-wide shrink-0"
                    style={{ color: "rgba(148,163,184,0.4)" }}
                  >
                    {row.label}:
                  </span>
                  <span
                    className="text-[8px] font-black font-mono truncate"
                    style={{ color: row.color ?? "rgba(203,213,225,0.7)" }}
                  >
                    {row.value}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      {/* Open Trades Panel — large, readable, all positions */}
      <div className="mx-3 mb-1" style={{ height: 1, background: `${color}15` }} />
      <div className="px-3 pb-3 flex-1 min-h-0 flex flex-col">
        <div
          className="text-[9px] font-black uppercase tracking-widest mb-2 flex items-center gap-1.5"
          style={{ color: `${color}` }}
        >
          <span>⬡</span>
          <span>Open Trades</span>
          {bot.openPositionsList != null && bot.openPositionsList.length > 0 && (
            <span
              className="ml-auto text-[8px] font-bold px-1.5 py-0.5 rounded"
              style={{ background: `${color}18`, color: `${color}cc` }}
            >
              {bot.openPositionsList.length}
            </span>
          )}
        </div>

        {bot.openPositionsList == null || bot.openPositionsList.length === 0 ? (
          <div
            className="flex-1 flex items-center justify-center rounded-lg"
            style={{ border: `1px dashed ${color}18`, minHeight: 52 }}
          >
            <span className="text-xs font-bold italic" style={{ color: "rgba(148,163,184,0.3)" }}>
              No open trades
            </span>
          </div>
        ) : (
          <div className="flex flex-col gap-1.5 overflow-auto" style={{ maxHeight: 220 }}>
            {bot.openPositionsList.map((pos, i) => {
              const positivePnl = pos.unrealized_pnl_usd >= 0;
              const posPnlColor = positivePnl ? "#34d399" : "#f87171";
              const pnlStr = positivePnl
                ? `+$${Math.abs(pos.unrealized_pnl_usd).toFixed(0)}`
                : `-$${Math.abs(pos.unrealized_pnl_usd).toFixed(0)}`;
              const ticker = pos.symbol.replace("/USD", "").replace("USD", "");
              const entryFmt = pos.entry_price === 0
                ? "—"
                : pos.entry_price < 1
                  ? pos.entry_price.toFixed(4)
                  : pos.entry_price.toFixed(2);
              const sizeFmt = pos.size_usd != null && pos.size_usd > 0
                ? `$${Math.round(pos.size_usd).toLocaleString()}`
                : null;
              return (
                <div
                  key={`${pos.symbol}-${i}`}
                  className="rounded-lg px-2.5 py-2 flex items-center gap-2"
                  style={{
                    background: positivePnl ? "rgba(52,211,153,0.06)" : "rgba(248,113,113,0.06)",
                    border: `1px solid ${positivePnl ? "rgba(52,211,153,0.14)" : "rgba(248,113,113,0.14)"}`,
                  }}
                >
                  {/* Direction badge */}
                  <div
                    className="shrink-0 w-5 h-5 rounded flex items-center justify-center"
                    style={{
                      background: pos.side === "long" ? "rgba(52,211,153,0.15)" : "rgba(248,113,113,0.15)",
                    }}
                  >
                    <span
                      className="text-[10px] font-black"
                      style={{ color: pos.side === "long" ? "#34d399" : "#f87171" }}
                    >
                      {pos.side === "long" ? "▲" : "▼"}
                    </span>
                  </div>

                  {/* Symbol + entry */}
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-black font-mono text-white leading-tight truncate">
                      {ticker}
                    </div>
                    <div className="text-[10px] font-mono leading-tight" style={{ color: "rgba(148,163,184,0.55)" }}>
                      @{entryFmt}{sizeFmt ? ` · ${sizeFmt}` : ""}
                    </div>
                  </div>

                  {/* Unrealized P&L */}
                  <div
                    className="shrink-0 text-sm font-black font-mono"
                    style={{ color: posPnlColor }}
                  >
                    {pnlStr}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
    </>
  );
}

const PARAM_ORDER = ["ZSCORE_ENTRY", "ZSCORE_EXIT", "STOP_LOSS_PCT", "TRAIL_PCT", "MIN_NET_PROFIT_PCT"] as const;
const PARAM_LABELS: Record<string, { label: string; format: (v: number) => string }> = {
  ZSCORE_ENTRY: { label: "Z-Entry", format: (v) => v.toFixed(2) },
  ZSCORE_EXIT: { label: "Z-Exit", format: (v) => v.toFixed(2) },
  STOP_LOSS_PCT: { label: "Stop Loss", format: (v) => `${(v * 100).toFixed(1)}%` },
  TRAIL_PCT: { label: "Trail %", format: (v) => `${(v * 100).toFixed(1)}%` },
  MIN_NET_PROFIT_PCT: { label: "Min Profit", format: (v) => `${(v * 100).toFixed(2)}%` },
};

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
  const { data: poseidonState } = usePoseidonState();
  const { data: kcState } = useKrakenCurrentState();

  const oracleEquity = portfolio?.account?.equity ?? null;
  const oraclePositions = (portfolio?.positions ?? []).filter((p) => (p.market_value ?? 0) > 10);
  const oracleTopPair = oraclePositions[0]?.symbol;
  const oracleOpenList: OpenPosSummary[] = oraclePositions.map((p) => ({
    symbol: p.symbol,
    side: ((p.qty ?? 0) >= 0 ? "long" : "short") as "long" | "short",
    entry_price: p.avg_entry_price ?? 0,
    unrealized_pnl_usd: p.unrealized_pl ?? 0,
    size_usd: p.market_value ?? 0,
  }));

  const davyEquity = davyPerf?.current_equity ?? davyStatus?.total_equity_usd ?? null;
  const davyTopPair = davyStatus?.open_positions?.[0]?.symbol;

  const bbEquity = bbPerf?.current_equity ?? bbStatus?.total_equity_usd ?? null;
  const bbTopPair = bbStatus?.open_positions?.[0]?.symbol;

  const caEquity = caPerf?.current_equity ?? caStatus?.total_equity_usd ?? null;
  const caTopPair = caStatus?.open_positions?.[0]?.symbol;

  const apexEquity = optionsState?.total_equity ?? optionsState?.paper_equity ?? null;
  const apexPositionsArr = Array.isArray(optionsPosRaw) ? optionsPosRaw : [];
  const apexTopPair = apexPositionsArr[0]?.symbol;
  const apexOpenList: OpenPosSummary[] = apexPositionsArr.map((p) => ({
    symbol: p.symbol,
    side: "long" as const,
    entry_price: p.premium_per_contract ?? 0,
    unrealized_pnl_usd: p.unrealized_pnl ?? 0,
    size_usd: p.total_cost ?? 0,
  }));

  const navEquity = forexState?.total_equity ?? forexState?.paper_equity ?? null;
  const rawForexPos: ForexPosition[] = Array.isArray(forexPosRaw)
    ? (forexPosRaw as ForexPosition[])
    : ((forexPosRaw as { positions?: ForexPosition[] } | null)?.positions ?? []);
  const navTopPair = rawForexPos[0]?.pair;
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
  const poseidonTopPair = poseidonOpenList[0]?.symbol;

  const kcEquity = kcState?.total_equity ?? null;
  const kcOpenList: OpenPosSummary[] = (kcState?.open_positions_list ?? []).map((p) => ({
    symbol: p.symbol,
    side: (p.direction === "long" ? "long" : "short") as "long" | "short",
    entry_price: p.entry_price ?? 0,
    unrealized_pnl_usd: p.unrealised_pnl ?? 0,
    size_usd: p.position_value ?? 0,
  }));
  const kcTopPair = kcOpenList[0]?.symbol;

  const allEquities = [oracleEquity, davyEquity, bbEquity, caEquity, apexEquity, navEquity, poseidonEquity, kcEquity].filter((e): e is number => e != null);
  const fleetTotal = allEquities.length === 8 ? allEquities.reduce((s, e) => s + e, 0) : null;
  const fleetPnl = fleetTotal != null ? fleetTotal - FLEET_STARTING_CAPITAL : null;

  const usdBias = forexState?.usd_bias ?? "NEUTRAL";

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
      openPositionsList: oracleOpenList,
      strategyConfig: [
        { label: "Conviction", value: "≥0.65", color: "#22d3ee" },
        { label: "Slots", value: "8 max", color: "#94a3b8" },
        { label: "Kill Switch", value: "−12%", color: "#f87171" },
        { label: "Stop", value: "ATR 2.0×", color: "#94a3b8" },
      ],
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
      krakenBotKey: "davy_jones",
      openPositionsList: davyStatus?.open_positions,
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
      krakenBotKey: "blackbeard",
      openPositionsList: bbStatus?.open_positions,
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
      krakenBotKey: "calypso",
      openPositionsList: caStatus?.open_positions,
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
      openPositionsList: apexOpenList,
      strategyConfig: [
        {
          label: "Cap Fence",
          value: `${((optionsState?.capital_fence_pct ?? 0.05) * 100).toFixed(0)}%`,
          color: "#f97316",
        },
        {
          label: "Fenced",
          value: `$${(optionsState?.fenced_capital ?? 5000).toLocaleString()}`,
          color: "#94a3b8",
        },
        {
          label: "Circuit Brk",
          value: optionsState?.circuit_breaker_active ? "ACTIVE" : "OFF",
          color: optionsState?.circuit_breaker_active ? "#f87171" : "#10b981",
        },
        {
          label: "Mode",
          value: optionsState?.paper_mode ? "PAPER" : "LIVE",
          color: optionsState?.paper_mode ? "#fbbf24" : "#10b981",
        },
      ],
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
      openPositionsList: navOpenList,
      strategyConfig: [
        {
          label: "USD Bias",
          value: usdBias,
          color: usdBias === "LONG" ? "#10b981" : usdBias === "SHORT" ? "#f87171" : "#94a3b8",
        },
        {
          label: "News Blkout",
          value: forexState?.news_blackout ? "ACTIVE" : "OFF",
          color: forexState?.news_blackout ? "#fbbf24" : "#10b981",
        },
        {
          label: "Circuit Brk",
          value: forexState?.circuit_breaker_active ? "ACTIVE" : "OFF",
          color: forexState?.circuit_breaker_active ? "#f87171" : "#10b981",
        },
        {
          label: "HWM",
          value: `$${(forexState?.hwm_usd ?? 100000).toLocaleString()}`,
          color: "#94a3b8",
        },
      ],
    },
    {
      id: "poseidon",
      name: "Poseidon",
      icon: "🔱",
      exchange: "Kraken · Pairs",
      color: "#8b5cf6",
      glow: "#8b5cf6",
      equity: poseidonEquity,
      paused: poseidonState?.paused ?? false,
      winCount: poseidonState?.total_wins ?? 0,
      lossCount: (poseidonState?.total_trades ?? 0) - (poseidonState?.total_wins ?? 0),
      openPositions: poseidonOpenList.length,
      topPair: poseidonTopPair,
      openPositionsList: poseidonOpenList,
      strategyConfig: [
        { label: "Entry Z", value: `|Z| > ${poseidonState?.zscore_entry ?? 2.0}`, color: "#8b5cf6" },
        { label: "Exit Z", value: `|Z| < ${poseidonState?.zscore_exit ?? 0.3}`, color: "#a78bfa" },
        { label: "Max Pairs", value: `${poseidonState?.max_pairs ?? 3} open`, color: "#cbd5e1" },
        { label: "Cycle", value: `${poseidonState?.cycle_minutes ?? 15} min`, color: "#94a3b8" },
      ],
    },
    {
      id: "kraken-current",
      name: "Kraken Current",
      icon: "🌊",
      exchange: "Kraken · Trend",
      color: "#06b6d4",
      glow: "#06b6d4",
      equity: kcEquity,
      paused: kcState?.paused ?? false,
      winCount: kcState?.total_wins ?? 0,
      lossCount: (kcState?.total_trades ?? 0) - (kcState?.total_wins ?? 0),
      openPositions: kcOpenList.length,
      topPair: kcTopPair,
      openPositionsList: kcOpenList,
      strategyConfig: [
        { label: "EMA", value: `${kcState?.ema_fast ?? 20}/${kcState?.ema_slow ?? 100}`, color: "#06b6d4" },
        { label: "ADX Filter", value: `> ${kcState?.adx_threshold ?? 25}`, color: "#22d3ee" },
        { label: "Max Pos", value: `${kcState?.max_positions ?? 5}`, color: "#cbd5e1" },
        { label: "Universe", value: `${kcState?.universe_size ?? 156} coins`, color: "#94a3b8" },
      ],
    },
  ];

  const bestBotId = bots.reduce<string | null>((best, bot) => {
    if (bot.equity == null) return best;
    const pnl = bot.equity - STARTING_BALANCE;
    if (best === null) return bot.id;
    const bestBot = bots.find((b) => b.id === best);
    const bestPnl = bestBot?.equity != null ? bestBot.equity - STARTING_BALANCE : -Infinity;
    return pnl > bestPnl ? bot.id : best;
  }, null);

  const fleetPnlColor = fleetPnl == null ? "#94a3b8" : fleetPnl >= 0 ? "#34d399" : "#f87171";

  return (
    <div
      className="h-full w-full flex flex-col relative"
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
            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded" style={{ background: "rgba(34,211,238,0.1)", color: "#22d3ee", border: "1px solid rgba(34,211,238,0.2)" }}>8 BOTS</span>
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
            <div className="text-xs font-black font-mono" style={{ color: "rgba(203,213,225,0.6)" }}>${FLEET_STARTING_CAPITAL.toLocaleString()}</div>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: "#22c55e", boxShadow: "0 0 6px #22c55e" }} />
          <span className="text-[10px] font-black uppercase tracking-widest" style={{ color: "#22c55e" }}>ALL SYSTEMS LIVE</span>
        </div>
      </div>

      {/* Bot cards grid — 4 cols × 2 rows */}
      <div className="flex-1 min-h-0 grid grid-cols-4 gap-2 p-3" style={{ gridTemplateRows: "1fr 1fr" }}>
        {bots.map((bot) => (
          <StreamBotCard key={bot.id} bot={{ ...bot, isBest: bot.id === bestBotId }} />
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
      <DDGBadge style={{ position: "absolute", bottom: 10, left: 10, zIndex: 50 }} />
    </div>
  );
}
