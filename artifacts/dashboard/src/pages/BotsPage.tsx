import { useMemo } from "react";
import {
  useKrakenBots,
  useAIImpactTimeline,
  usePortfolio,
  useOptionsState,
  useOptionsPositions,
  useForexState,
  useForexPositions,
  type AIIntervention,
  type ForexPosition,
} from "@/hooks/use-trading";
import { BotCard } from "@/components/BotCard";
import { Loader2, Bot, TrendingUp, TrendingDown } from "lucide-react";

const STARTING_BALANCE = 100_000;

function fmtUsd(v: number) {
  return `$${Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
}

function fmtPnl(v: number) {
  const abs = Math.abs(v);
  if (abs >= 1000) return v >= 0 ? `+$${(abs / 1000).toFixed(1)}k` : `-$${(abs / 1000).toFixed(1)}k`;
  return v >= 0 ? `+$${abs.toFixed(2)}` : `-$${abs.toFixed(2)}`;
}

interface GenericPosition {
  symbol: string;
  size_usd: number;
  unrealized_pnl: number;
  entry_price?: number;
}

interface GenericBotCardProps {
  name: string;
  icon: string;
  color: string;
  strategy: string;
  equity: number | null | undefined;
  winCount?: number;
  lossCount?: number;
  winRate?: number | null;
  positions?: GenericPosition[];
  isLoading?: boolean;
  paused?: boolean;
  totalTrades?: number;
}

function GenericBotCard({
  name, icon, color, strategy, equity,
  winCount, lossCount, winRate, positions, isLoading, paused, totalTrades,
}: GenericBotCardProps) {
  const truePnl = equity != null && equity > 0 ? equity - STARTING_BALANCE : null;

  return (
    <div
      className="rounded-2xl border bg-slate-900/60 backdrop-blur-sm overflow-hidden flex flex-col"
      style={{ borderColor: `${color}20` }}
    >
      <div
        className="px-4 py-3 flex items-center gap-3 border-b"
        style={{ borderColor: `${color}15`, background: `linear-gradient(135deg, ${color}10, transparent)` }}
      >
        <div
          className="w-9 h-9 rounded-xl flex items-center justify-center text-lg flex-shrink-0"
          style={{ background: `${color}18`, border: `1px solid ${color}30` }}
        >
          {icon}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-bold text-white leading-none">{name}</h3>
            <span
              className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded-full"
              style={{
                color: paused ? "#f59e0b" : "#10b981",
                background: paused ? "#f59e0b18" : "#10b98118",
                border: `1px solid ${paused ? "#f59e0b30" : "#10b98130"}`,
              }}
            >
              {paused ? "paused" : "live"}
            </span>
          </div>
          <p className="text-[10px] text-slate-500 mt-0.5 truncate">{strategy}</p>
        </div>
        {equity != null && equity > 0 && (
          <div className="text-right flex-shrink-0">
            <div className="text-xs font-mono font-bold text-white">{fmtUsd(equity)}</div>
            <div className="text-[10px] text-slate-500">equity</div>
          </div>
        )}
      </div>

      {isLoading ? (
        <div className="flex-1 flex items-center justify-center py-8">
          <Loader2 className="w-4 h-4 text-slate-600 animate-spin" />
        </div>
      ) : (
        <div className="flex-1 flex flex-col divide-y divide-white/[0.04]">
          <div className="px-4 py-3">
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-2">Open Positions</div>
            {!positions || positions.length === 0 ? (
              <div className="text-[11px] text-slate-600 italic">No open positions</div>
            ) : (
              <div className="space-y-1.5">
                {positions.slice(0, 3).map((pos) => (
                  <div key={pos.symbol} className="flex items-center justify-between gap-2 text-[11px]">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: `${color}80` }} />
                      <span className="font-mono font-bold text-white">{pos.symbol}</span>
                      {pos.entry_price != null && (
                        <span className="text-slate-500 text-[10px]">@{pos.entry_price.toFixed(4)}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <span className="text-slate-400 text-[10px]">{fmtUsd(pos.size_usd)}</span>
                      <span
                        className="font-mono font-bold text-[11px]"
                        style={{ color: pos.unrealized_pnl >= 0 ? "#10b981" : "#ef4444" }}
                      >
                        {fmtPnl(pos.unrealized_pnl)}
                      </span>
                    </div>
                  </div>
                ))}
                {positions.length > 3 && (
                  <div className="text-[10px] text-slate-600">+{positions.length - 3} more</div>
                )}
              </div>
            )}
          </div>

          <div className="px-4 py-3">
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-2">Performance</div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-2">
              <div>
                <div className="text-[9px] text-slate-600 uppercase tracking-wider">Total Equity</div>
                <div className="text-[12px] font-mono font-bold text-white">
                  {equity != null ? fmtUsd(equity) : "—"}
                </div>
              </div>
              <div>
                <div className="text-[9px] text-slate-600 uppercase tracking-wider">Total P&L</div>
                <div
                  className="text-[12px] font-mono font-bold flex items-center gap-1"
                  style={{ color: truePnl != null && truePnl >= 0 ? "#10b981" : "#ef4444" }}
                >
                  {truePnl != null && truePnl >= 0
                    ? <TrendingUp className="w-3 h-3" />
                    : <TrendingDown className="w-3 h-3" />
                  }
                  {truePnl != null ? fmtPnl(truePnl) : "—"}
                </div>
              </div>
              <div>
                <div className="text-[9px] text-slate-600 uppercase tracking-wider">W / L</div>
                <div className="text-[12px] font-mono font-bold">
                  <span className="text-emerald-400">{winCount ?? 0}</span>
                  <span className="text-slate-600"> / </span>
                  <span className="text-red-400">{lossCount ?? 0}</span>
                </div>
              </div>
              <div>
                {winRate != null ? (
                  <>
                    <div className="text-[9px] text-slate-600 uppercase tracking-wider">Win Rate</div>
                    <div
                      className="text-[12px] font-mono font-bold"
                      style={{ color: winRate >= 50 ? "#10b981" : winRate >= 40 ? "#f59e0b" : "#ef4444" }}
                    >
                      {winRate.toFixed(1)}%
                    </div>
                  </>
                ) : (
                  <>
                    <div className="text-[9px] text-slate-600 uppercase tracking-wider">Trades</div>
                    <div className="text-[12px] font-mono font-bold text-slate-400">{totalTrades ?? 0}</div>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function derivePreviousParams(
  interventions: AIIntervention[] | undefined
): Record<string, Record<string, number>> {
  if (!interventions || interventions.length < 2) return {};
  const sorted = [...interventions].sort(
    (a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime()
  );

  const result: Record<string, Record<string, number>> = {};
  const lastChanges: Record<string, Set<string>> = {};
  for (const pc of sorted[0]?.param_changes ?? []) {
    if (!pc.bot_id) continue;
    if (!lastChanges[pc.bot_id]) lastChanges[pc.bot_id] = new Set();
    const keys = ["ZSCORE_ENTRY", "ZSCORE_EXIT", "STOP_LOSS_PCT", "TRAIL_PCT", "MIN_NET_PROFIT_PCT"] as const;
    for (const k of keys) {
      if (pc[k] !== undefined) lastChanges[pc.bot_id].add(k);
    }
  }

  for (let i = 1; i < sorted.length; i++) {
    const intervention = sorted[i];
    for (const pc of intervention.param_changes ?? []) {
      if (!pc.bot_id) continue;
      const changedInLast = lastChanges[pc.bot_id];
      if (!changedInLast) continue;
      if (!result[pc.bot_id]) result[pc.bot_id] = {};
      const keys = ["ZSCORE_ENTRY", "ZSCORE_EXIT", "STOP_LOSS_PCT", "TRAIL_PCT", "MIN_NET_PROFIT_PCT"] as const;
      for (const k of keys) {
        if (pc[k] !== undefined && changedInLast.has(k) && result[pc.bot_id][k] == null) {
          result[pc.bot_id][k] = pc[k] as number;
        }
      }
    }
    const allFilled = Object.entries(lastChanges).every(([botId, params]) =>
      [...params].every((p) => result[botId]?.[p] != null)
    );
    if (allFilled) break;
  }

  return result;
}

export default function BotsPage() {
  const { data: krakenBots, isLoading: krakenLoading } = useKrakenBots();
  const { data: aiTimeline } = useAIImpactTimeline();
  const { data: portfolio, isLoading: portfolioLoading } = usePortfolio();
  const { data: optionsState, isLoading: optionsLoading } = useOptionsState();
  const { data: optionsPositions, isLoading: optionsPosLoading } = useOptionsPositions();
  const { data: forexState, isLoading: forexLoading } = useForexState();
  const { data: forexPositionsRaw, isLoading: forexPosLoading } = useForexPositions();

  const previousParams = useMemo(
    () => derivePreviousParams(aiTimeline?.interventions),
    [aiTimeline]
  );

  const oracleEquity = portfolio?.account?.equity ?? null;
  const oraclePositions: GenericPosition[] = (portfolio?.positions ?? [])
    .filter((p) => (p.market_value ?? 0) > 10)
    .map((p) => ({
      symbol: p.symbol,
      size_usd: p.market_value ?? 0,
      unrealized_pnl: p.unrealized_pl ?? 0,
      entry_price: p.avg_entry_price,
    }));

  const apexEquity = optionsState?.total_equity ?? optionsState?.paper_equity ?? null;
  const apexPosArr = Array.isArray(optionsPositions) ? optionsPositions : [];
  const apexPositions: GenericPosition[] = apexPosArr.map((p) => ({
    symbol: p.symbol,
    size_usd: p.total_cost ?? 0,
    unrealized_pnl: p.unrealized_pnl ?? 0,
  }));
  const apexTotalTrades = optionsState?.total_trades ?? 0;
  const apexWins = optionsState?.total_wins ?? 0;
  const apexLosses = apexTotalTrades - apexWins;
  const apexWinRate = apexTotalTrades > 0 ? (apexWins / apexTotalTrades) * 100 : null;

  const navEquity = forexState?.total_equity ?? forexState?.paper_equity ?? null;
  const rawPositions: ForexPosition[] = Array.isArray(forexPositionsRaw)
    ? (forexPositionsRaw as ForexPosition[])
    : ((forexPositionsRaw as { positions?: ForexPosition[] } | null)?.positions ?? []);
  const navPositions: GenericPosition[] = rawPositions.map((p) => ({
    symbol: p.pair,
    size_usd: p.size_usd ?? 0,
    unrealized_pnl: p.unrealized_pnl_usd ?? 0,
    entry_price: p.entry_price,
  }));
  const navTotalTrades = forexState?.total_trades ?? 0;
  const navWins = forexState?.total_wins ?? 0;
  const navLosses = navTotalTrades - navWins;
  const navWinRate = navTotalTrades > 0 ? (navWins / navTotalTrades) * 100 : null;

  return (
    <div className="min-h-screen bg-slate-950 pb-24">
      <header className="sticky top-0 z-40 border-b border-white/[0.06] bg-slate-950/95 backdrop-blur-xl px-4 py-3">
        <div className="max-w-7xl mx-auto flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl bg-amber-500/20 border border-amber-500/30 flex items-center justify-center">
            <Bot className="w-4 h-4 text-amber-400" />
          </div>
          <div>
            <h1 className="text-sm font-bold text-white leading-none">Bots</h1>
            <p className="text-[10px] text-slate-500">6-bot automated fleet</p>
          </div>
          <span className="ml-auto text-[11px] text-slate-500">6 bots</span>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 pt-5">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">

          <GenericBotCard
            name="Oracle"
            icon="🔮"
            color="#22d3ee"
            strategy="Alpaca stocks — conviction-based allocation"
            equity={oracleEquity}
            positions={oraclePositions}
            isLoading={portfolioLoading}
            paused={false}
            winCount={undefined}
            lossCount={undefined}
            winRate={null}
            totalTrades={undefined}
          />

          {krakenLoading ? (
            <div className="col-span-3 flex items-center justify-center py-16">
              <Loader2 className="w-6 h-6 text-slate-500 animate-spin" />
            </div>
          ) : (
            krakenBots?.map((bot) => (
              <BotCard
                key={bot.bot_id}
                botId={bot.bot_id}
                displayName={bot.display_name}
                strategyLabel={bot.strategy_label}
                previousParams={previousParams[bot.bot_id.replace(/-/g, "_")]}
              />
            ))
          )}

          <GenericBotCard
            name="Apex Predator"
            icon="🦅"
            color="#f97316"
            strategy="Options — iron condors, volatility squeeze"
            equity={apexEquity}
            positions={apexPositions}
            isLoading={optionsLoading || optionsPosLoading}
            paused={optionsState?.paused ?? false}
            winCount={apexWins}
            lossCount={apexLosses}
            winRate={apexWinRate}
            totalTrades={apexTotalTrades}
          />

          <GenericBotCard
            name="Navigator"
            icon="🧭"
            color="#10b981"
            strategy="Forex — USD-bias macro trend following"
            equity={navEquity}
            positions={navPositions}
            isLoading={forexLoading || forexPosLoading}
            paused={forexState?.paused ?? false}
            winCount={navWins}
            lossCount={navLosses}
            winRate={navWinRate}
            totalTrades={navTotalTrades}
          />

        </div>
      </div>
    </div>
  );
}
