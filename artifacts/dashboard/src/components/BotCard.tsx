import { useKrakenStatus, useKrakenPerformance, useFleetParams, type BotParamBounds } from "@/hooks/use-trading";
import { ParameterScale } from "./ParameterScale";
import { TrendingUp, TrendingDown, Anchor, Loader2 } from "lucide-react";

const PARAM_ORDER = ["ZSCORE_ENTRY", "ZSCORE_EXIT", "STOP_LOSS_PCT", "TRAIL_PCT", "MIN_NET_PROFIT_PCT"];

const PARAM_LABELS: Record<string, { label: string; format: (v: number) => string }> = {
  ZSCORE_ENTRY: { label: "Z-Entry", format: (v) => v.toFixed(2) },
  ZSCORE_EXIT: { label: "Z-Exit", format: (v) => v.toFixed(2) },
  STOP_LOSS_PCT: { label: "Stop Loss", format: (v) => `${(v * 100).toFixed(1)}%` },
  TRAIL_PCT: { label: "Trail %", format: (v) => `${(v * 100).toFixed(1)}%` },
  MIN_NET_PROFIT_PCT: { label: "Min Profit", format: (v) => `${(v * 100).toFixed(2)}%` },
};

const BOT_META: Record<string, { color: string; icon: string; strategy: string }> = {
  davy_jones: {
    color: "#f59e0b",
    icon: "⚓",
    strategy: "Mean-reversion z-score scalper",
  },
  blackbeard: {
    color: "#ef4444",
    icon: "🏴‍☠️",
    strategy: "Aggressive momentum breakout",
  },
  calypso: {
    color: "#8b5cf6",
    icon: "🌊",
    strategy: "Conservative trend follower",
  },
};

const STARTING_BALANCE = 100_000;

interface BotCardProps {
  botId: string;
  displayName: string;
  strategyLabel?: string;
  previousParams?: Record<string, number>;
}

function fmtPnl(v: number) {
  const abs = Math.abs(v);
  if (abs >= 1000) return v >= 0 ? `+$${(abs / 1000).toFixed(1)}k` : `-$${(abs / 1000).toFixed(1)}k`;
  return v >= 0 ? `+$${abs.toFixed(2)}` : `-$${abs.toFixed(2)}`;
}

export function BotCard({ botId, displayName, strategyLabel, previousParams }: BotCardProps) {
  const { data: status, isLoading: statusLoading } = useKrakenStatus(botId);
  const { data: perf, isLoading: perfLoading } = useKrakenPerformance(botId);
  const { data: fleetParams } = useFleetParams();

  const botKey = botId.replace(/-/g, "_");
  const meta = BOT_META[botKey] ?? { color: "#6b7280", icon: "🤖", strategy: strategyLabel ?? "Automated trading bot" };
  const botParams = fleetParams?.bots?.[botKey] ?? fleetParams?.bots?.[botId];
  const current = botParams?.current ?? {};
  const bounds = botParams?.bounds ?? {};

  const isLoading = statusLoading || perfLoading;

  const currentEquity = perf?.current_equity ?? status?.total_equity_usd ?? 0;
  const truePnl = currentEquity > 0 ? currentEquity - STARTING_BALANCE : null;

  return (
    <div
      className="rounded-2xl border bg-slate-900/60 backdrop-blur-sm overflow-hidden flex flex-col"
      style={{ borderColor: `${meta.color}20` }}
    >
      <div
        className="px-4 py-3 flex items-center gap-3 border-b"
        style={{ borderColor: `${meta.color}15`, background: `linear-gradient(135deg, ${meta.color}10, transparent)` }}
      >
        <div
          className="w-9 h-9 rounded-xl flex items-center justify-center text-lg flex-shrink-0"
          style={{ background: `${meta.color}18`, border: `1px solid ${meta.color}30` }}
        >
          {meta.icon}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-bold text-white leading-none">{displayName}</h3>
            {status && (
              <span
                className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded-full"
                style={{
                  color: status.bot_paused ? "#f59e0b" : "#10b981",
                  background: status.bot_paused ? "#f59e0b18" : "#10b98118",
                  border: `1px solid ${status.bot_paused ? "#f59e0b30" : "#10b98130"}`,
                }}
              >
                {status.bot_paused ? "paused" : "live"}
              </span>
            )}
          </div>
          <p className="text-[10px] text-slate-500 mt-0.5 truncate">{meta.strategy}</p>
        </div>
        {currentEquity > 0 && (
          <div className="text-right flex-shrink-0">
            <div className="text-xs font-mono font-bold text-white">
              ${currentEquity.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
            </div>
            <div className="text-[10px] text-slate-500">equity</div>
          </div>
        )}
      </div>

      {isLoading && (
        <div className="flex-1 flex items-center justify-center py-8">
          <Loader2 className="w-4 h-4 text-slate-600 animate-spin" />
        </div>
      )}

      {!isLoading && (
        <div className="flex-1 flex flex-col divide-y divide-white/[0.04]">
          {Object.keys(bounds).length > 0 && (
            <div className="px-4 py-3">
              <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-2.5">Parameters</div>
              <div className="space-y-3">
                {PARAM_ORDER.map((param) => {
                  const val = current[param];
                  const b = bounds[param] as BotParamBounds | undefined;
                  if (val == null || !b) return null;
                  const cfg = PARAM_LABELS[param];
                  const prev = previousParams?.[param];
                  return (
                    <ParameterScale
                      key={param}
                      label={cfg?.label ?? param}
                      min={b.min}
                      max={b.max}
                      current={val}
                      previous={prev}
                      format={cfg?.format}
                      color={meta.color}
                    />
                  );
                })}
              </div>
            </div>
          )}

          <div className="px-4 py-3">
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-2">Open Positions</div>
            {!status || status.open_positions.length === 0 ? (
              <div className="text-[11px] text-slate-600 italic">No open positions</div>
            ) : (
              <div className="space-y-1.5">
                {status.open_positions.slice(0, 3).map((pos) => {
                  const pnl = pos.unrealized_pnl_usd ?? 0;
                  return (
                    <div key={pos.symbol} className="flex items-center justify-between gap-2 text-[11px]">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <Anchor className="w-2.5 h-2.5 flex-shrink-0" style={{ color: meta.color }} />
                        <span className="font-mono font-bold text-white">{pos.symbol}</span>
                        <span className="text-slate-500 text-[10px]">@{pos.entry_price.toFixed(4)}</span>
                      </div>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        <span className="text-slate-400 text-[10px]">${(pos.size_usd ?? 0).toFixed(0)}</span>
                        <span
                          className="font-mono font-bold text-[11px]"
                          style={{ color: pnl >= 0 ? "#10b981" : "#ef4444" }}
                        >
                          {fmtPnl(pnl)}
                        </span>
                      </div>
                    </div>
                  );
                })}
                {status.open_positions.length > 3 && (
                  <div className="text-[10px] text-slate-600">+{status.open_positions.length - 3} more</div>
                )}
              </div>
            )}
          </div>

          <div className="px-4 py-3">
            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-2">Performance</div>
            {!perf ? (
              <div className="text-[11px] text-slate-600 italic">No data</div>
            ) : (
              <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                <div>
                  <div className="text-[9px] text-slate-600 uppercase tracking-wider">Total Equity</div>
                  <div className="text-[12px] font-mono font-bold text-white">
                    ${currentEquity.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
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
                    <span className="text-emerald-400">{perf.win_count}</span>
                    <span className="text-slate-600"> / </span>
                    <span className="text-red-400">{perf.loss_count}</span>
                  </div>
                </div>
                <div>
                  <div className="text-[9px] text-slate-600 uppercase tracking-wider">Win Rate</div>
                  <div
                    className="text-[12px] font-mono font-bold"
                    style={{
                      color: (perf.win_rate_pct ?? 0) >= 50 ? "#10b981" : (perf.win_rate_pct ?? 0) >= 40 ? "#f59e0b" : "#ef4444"
                    }}
                  >
                    {perf.win_rate_pct != null ? `${perf.win_rate_pct.toFixed(1)}%` : "—"}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
