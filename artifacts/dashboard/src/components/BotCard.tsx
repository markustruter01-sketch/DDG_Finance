import { useState } from "react";
import { useKrakenStatus, useKrakenPerformance, useFleetParams, useForceResume, type BotParamBounds } from "@/hooks/use-trading";
import { ParameterScale } from "./ParameterScale";
import { TrendingUp, TrendingDown, Anchor, Loader2, Zap } from "lucide-react";
import { getBotColors } from "@/lib/bot-colors";

const PARAM_ORDER = ["ZSCORE_ENTRY", "ZSCORE_EXIT", "STOP_LOSS_PCT", "TRAIL_PCT", "MIN_NET_PROFIT_PCT"];

const PARAM_LABELS: Record<string, { label: string; format: (v: number) => string }> = {
  ZSCORE_ENTRY: { label: "Z-Entry", format: (v) => v.toFixed(2) },
  ZSCORE_EXIT: { label: "Z-Exit", format: (v) => v.toFixed(2) },
  STOP_LOSS_PCT: { label: "Stop Loss", format: (v) => `${(v * 100).toFixed(1)}%` },
  TRAIL_PCT: { label: "Trail %", format: (v) => `${(v * 100).toFixed(1)}%` },
  MIN_NET_PROFIT_PCT: { label: "Min Profit", format: (v) => `${(v * 100).toFixed(2)}%` },
};

const STARTING_BALANCE = 100_000;

interface BotCardProps {
  botId: string;
  displayName: string;
  icon: string;
  colorName: string;
  strategy: string;
  previousParams?: Record<string, number>;
  equity?: number | null;
}

function fmtPnl(v: number) {
  const abs = Math.abs(v);
  if (abs >= 1000) return v >= 0 ? `+$${(abs / 1000).toFixed(1)}k` : `-$${(abs / 1000).toFixed(1)}k`;
  return v >= 0 ? `+$${abs.toFixed(2)}` : `-$${abs.toFixed(2)}`;
}

export function BotCard({ botId, displayName, icon, colorName, strategy, previousParams, equity }: BotCardProps) {
  const { data: status, isLoading: statusLoading } = useKrakenStatus(botId);
  const { data: perf, isLoading: perfLoading } = useKrakenPerformance(botId);
  const { data: fleetParams } = useFleetParams();
  const forceResume = useForceResume(botId);
  const [resumedAt, setResumedAt] = useState<number | null>(null);

  const colors = getBotColors(colorName);
  const botKey = botId.replace(/-/g, "_");
  const botParams = fleetParams?.bots?.[botKey] ?? fleetParams?.bots?.[botId];
  const current = botParams?.current ?? {};
  const bounds = botParams?.bounds ?? {};

  const isLoading = statusLoading || perfLoading;

  const currentEquity = equity ?? null;
  const truePnl = currentEquity != null && currentEquity > 0 ? currentEquity - STARTING_BALANCE : null;

  const botStatus = status?.status ?? "not_started";
  const cbActive = status?.circuit_breaker?.active ?? false;
  const cbUntil = status?.circuit_breaker?.paused_until ?? null;
  const isSuspended = status?.bot_paused || cbActive ||
    botStatus === "paused_circuit_breaker" ||
    botStatus === "paused_loss_streak" ||
    botStatus === "paused_dashboard";

  const justResumed = resumedAt != null && Date.now() - resumedAt < 10_000;

  function handleForceResume() {
    forceResume.mutate(undefined, {
      onSuccess: () => setResumedAt(Date.now()),
    });
  }

  return (
    <div
      className="rounded-2xl border bg-slate-900/60 backdrop-blur-sm overflow-hidden flex flex-col"
      style={{ borderColor: `${colors.hex}20` }}
    >
      <div
        className="px-4 py-3 flex items-center gap-3 border-b"
        style={{ borderColor: `${colors.hex}15`, background: `linear-gradient(135deg, ${colors.hex}10, transparent)` }}
      >
        <div
          className="w-9 h-9 rounded-xl flex items-center justify-center text-lg flex-shrink-0"
          style={{ background: `${colors.hex}18`, border: `1px solid ${colors.hex}30` }}
        >
          {icon}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-bold text-white leading-none">{displayName}</h3>
            {status && (
              <span
                className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded-full"
                style={{
                  color: cbActive ? "#ef4444" : isSuspended ? "#f59e0b" : "#10b981",
                  background: cbActive ? "#ef444418" : isSuspended ? "#f59e0b18" : "#10b98118",
                  border: `1px solid ${cbActive ? "#ef444430" : isSuspended ? "#f59e0b30" : "#10b98130"}`,
                }}
              >
                {cbActive ? "circuit breaker" : isSuspended ? "paused" : "live"}
              </span>
            )}
          </div>
          <p className="text-[10px] text-slate-500 mt-0.5 truncate">{strategy}</p>
        </div>
        {currentEquity != null && currentEquity > 0 && (
          <div className="text-right flex-shrink-0">
            <div className="text-xs font-mono font-bold text-white">
              ${currentEquity.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
            </div>
            <div className="text-[10px] text-slate-500">equity</div>
          </div>
        )}
      </div>

      {isSuspended && (
        <div
          className="px-4 py-2.5 flex items-center justify-between gap-3 border-b"
          style={{
            borderColor: cbActive ? "#ef444425" : "#f59e0b25",
            background: cbActive ? "#ef44440a" : "#f59e0b0a",
          }}
        >
          <div className="min-w-0 flex-1">
            <div
              className="text-[10px] font-bold uppercase tracking-wider"
              style={{ color: cbActive ? "#ef4444" : "#f59e0b" }}
            >
              {cbActive ? "⚡ Circuit Breaker Active" : "⏸ Bot Paused"}
            </div>
            {cbUntil && (
              <div className="text-[9px] text-slate-500 mt-0.5 truncate">
                Resumes {new Date(cbUntil).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} UTC
              </div>
            )}
          </div>
          {justResumed ? (
            <span className="text-[10px] font-bold text-emerald-400 flex-shrink-0">
              ✓ Override sent
            </span>
          ) : (
            <button
              onClick={handleForceResume}
              disabled={forceResume.isPending}
              className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] font-bold uppercase tracking-wider flex-shrink-0 transition-all active:scale-95"
              style={{
                background: "#f59e0b18",
                border: "1px solid #f59e0b40",
                color: "#f59e0b",
                opacity: forceResume.isPending ? 0.5 : 1,
                cursor: forceResume.isPending ? "not-allowed" : "pointer",
              }}
              title="Force-clear circuit breaker and resume this bot"
            >
              {forceResume.isPending ? (
                <Loader2 className="w-2.5 h-2.5 animate-spin" />
              ) : (
                <Zap className="w-2.5 h-2.5" />
              )}
              Force Resume
            </button>
          )}
        </div>
      )}

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
                      color={colors.hex}
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
                        <Anchor className="w-2.5 h-2.5 flex-shrink-0" style={{ color: colors.hex }} />
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
                    {currentEquity != null
                      ? `$${currentEquity.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
                      : "—"}
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
