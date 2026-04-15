import { useMemo, useState } from "react";
import {
  usePairLearning,
  type PairLearningSymbol,
  type FleetSymbol,
  type PoseidonPairParam,
} from "@/hooks/use-trading";

const C = {
  green: "#4ade80",
  red: "#f87171",
  orange: "#fb923c",
  cyan: "#22d3ee",
  violet: "#a78bfa",
  amber: "#fbbf24",
  slate: "rgba(148,163,184,0.5)",
  dim: "rgba(148,163,184,0.3)",
  bg: "#020617",
  card: "rgba(15,23,42,0.95)",
  border: "rgba(255,255,255,0.06)",
};

const BOT_COLORS: Record<string, string> = {
  "davy-jones": "#22d3ee",
  blackbeard: "#f97316",
  calypso: "#a855f7",
};

function fmtPnl(v: number) {
  const abs = Math.abs(v);
  const str = abs >= 1000 ? `$${(abs / 1000).toFixed(1)}k` : `$${abs.toFixed(0)}`;
  return v >= 0 ? `+${str}` : `-${str}`;
}

function HurstBar({ value, label }: { value: number | null; label?: string }) {
  if (value == null) return <span style={{ color: C.dim }}>—</span>;
  const pct = Math.min(1, value) * 100;
  const color =
    value < 0.45
      ? C.green
      : value < 0.55
      ? C.amber
      : value < 0.75
      ? C.orange
      : C.red;
  const meaning =
    value < 0.45
      ? "Mean-reverts"
      : value < 0.55
      ? "Random walk"
      : value < 0.75
      ? "Trending"
      : "Strong trend";
  return (
    <div title={meaning}>
      {label && (
        <div
          className="text-[8px] font-bold uppercase tracking-widest mb-0.5"
          style={{ color: C.dim }}
        >
          {label}
        </div>
      )}
      <div className="flex items-center gap-1.5">
        <div
          className="flex-1 h-1.5 rounded-full overflow-hidden"
          style={{ background: "rgba(255,255,255,0.06)" }}
        >
          <div
            className="h-full rounded-full transition-all"
            style={{ width: `${pct}%`, background: color }}
          />
        </div>
        <span
          className="text-[10px] font-mono font-bold shrink-0"
          style={{ color, minWidth: 30 }}
        >
          {value.toFixed(3)}
        </span>
      </div>
    </div>
  );
}

function AdfBadge({ value }: { value: number | null }) {
  if (value == null) return <span style={{ color: C.dim }}>—</span>;
  const good = value < 0.05;
  const ok = value < 0.1;
  const color = good ? C.green : ok ? C.amber : C.red;
  const label = good ? "cointegrated" : ok ? "marginal" : "non-stationary";
  return (
    <span
      className="text-[9px] font-mono font-bold px-1.5 py-0.5 rounded"
      style={{
        background: `${color}15`,
        color,
        border: `1px solid ${color}30`,
      }}
      title={`ADF p-value: ${value.toFixed(4)} — ${label}`}
    >
      p={value.toFixed(3)}
    </span>
  );
}

function WinRateChip({
  wins,
  losses,
  winRate,
}: {
  wins: number;
  losses: number;
  winRate: number | null;
}) {
  if (wins + losses === 0)
    return (
      <span className="text-[9px]" style={{ color: C.dim }}>
        no trades
      </span>
    );
  const color =
    winRate == null
      ? C.slate
      : winRate >= 55
      ? C.green
      : winRate >= 40
      ? C.amber
      : C.red;
  return (
    <div className="flex items-center gap-1">
      <span className="text-[9px] font-mono font-bold" style={{ color }}>
        {winRate != null ? `${winRate.toFixed(0)}%` : "—"}
      </span>
      <span className="text-[8px]" style={{ color: C.dim }}>
        {wins}W/{losses}L
      </span>
    </div>
  );
}

function PausedBanner({ symbol }: { symbol: FleetSymbol }) {
  return (
    <div
      className="rounded-lg p-3 border"
      style={{
        background: "rgba(239,68,68,0.06)",
        borderColor: "rgba(239,68,68,0.3)",
      }}
    >
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-[10px] font-black text-red-400">⛔ PAUSED</span>
        <span className="text-sm font-black font-mono text-white">
          {symbol.symbol.replace("/USD", "")}
        </span>
        <span className="text-[9px]" style={{ color: C.dim }}>
          {symbol.bot_count} bot{symbol.bot_count !== 1 ? "s" : ""}
        </span>
        <span
          className="ml-auto text-[9px] font-mono font-bold px-1.5 py-0.5 rounded"
          style={{
            color: symbol.total_pnl >= 0 ? C.green : C.red,
            background: "rgba(255,255,255,0.05)",
          }}
        >
          {fmtPnl(symbol.total_pnl)}
        </span>
      </div>
      {symbol.pause_reason && (
        <p
          className="text-[9px] leading-relaxed"
          style={{ color: "rgba(252,165,165,0.7)" }}
        >
          {symbol.pause_reason.length > 180
            ? symbol.pause_reason.slice(0, 180) + "…"
            : symbol.pause_reason}
        </p>
      )}
    </div>
  );
}

function SymbolCard({ sym }: { sym: FleetSymbol }) {
  const isPaused = sym.any_paused;
  const hasGoodHurst = sym.avg_hurst != null && sym.avg_hurst < 0.55;
  const hasGoodAdf = sym.avg_adf_pvalue != null && sym.avg_adf_pvalue < 0.1;
  const totalTrades = sym.total_wins + sym.total_losses;
  const winRate = totalTrades > 0 ? (sym.total_wins / totalTrades) * 100 : null;

  const borderColor = isPaused
    ? "rgba(239,68,68,0.4)"
    : hasGoodHurst && hasGoodAdf
    ? "rgba(74,222,128,0.2)"
    : C.border;

  return (
    <div
      className="rounded-lg p-2.5 flex flex-col gap-1.5"
      style={{ background: C.card, border: `1px solid ${borderColor}` }}
    >
      <div className="flex items-center gap-1.5">
        {isPaused && <span className="text-[9px]">⛔</span>}
        <span className="text-[11px] font-black font-mono text-white">
          {sym.symbol.replace("/USD", "")}
        </span>
        <span
          className="text-[8px] font-bold ml-auto px-1 py-0.5 rounded"
          style={{
            color: isPaused ? C.red : C.green,
            background: isPaused ? "rgba(239,68,68,0.1)" : "rgba(74,222,128,0.1)",
          }}
        >
          {isPaused ? "PAUSED" : "ACTIVE"}
        </span>
      </div>

      <HurstBar value={sym.avg_hurst} label="Hurst H" />

      <div className="flex items-center justify-between">
        <span
          className="text-[8px] font-bold uppercase tracking-widest"
          style={{ color: C.dim }}
        >
          ADF
        </span>
        <AdfBadge value={sym.avg_adf_pvalue} />
      </div>

      <div className="flex items-center justify-between">
        <span
          className="text-[8px] font-bold uppercase tracking-widest"
          style={{ color: C.dim }}
        >
          Win Rate
        </span>
        <WinRateChip
          wins={sym.total_wins}
          losses={sym.total_losses}
          winRate={winRate}
        />
      </div>

      <div className="flex items-center justify-between">
        <span
          className="text-[8px] font-bold uppercase tracking-widest"
          style={{ color: C.dim }}
        >
          Fleet P&amp;L
        </span>
        <span
          className="text-[9px] font-mono font-bold"
          style={{ color: sym.total_pnl >= 0 ? C.green : C.red }}
        >
          {fmtPnl(sym.total_pnl)}
        </span>
      </div>
    </div>
  );
}

function PoseidonPairRow({ pair }: { pair: PoseidonPairParam }) {
  const tradeable = pair.is_tradeable;
  const hurstOk = pair.hurst < 0.6;
  const adfOk = pair.adf_pvalue < 0.05;
  const health =
    tradeable && hurstOk && adfOk ? "good" : tradeable ? "ok" : "blocked";
  const color =
    health === "good" ? C.green : health === "ok" ? C.amber : C.red;

  return (
    <div
      className="flex items-center gap-3 px-3 py-2 rounded-lg"
      style={{ background: `${color}05`, border: `1px solid ${color}15` }}
    >
      <span
        className="text-[8px] font-bold font-mono"
        style={{ color: C.dim, minWidth: 14 }}
      >
        #{pair.pair_set_id}
      </span>
      <div className="flex-1 flex items-center gap-1.5">
        <span className="text-[11px] font-black font-mono text-white">
          {pair.asset_a.replace("/USD", "")}
        </span>
        <span style={{ color: C.dim }}>↔</span>
        <span className="text-[11px] font-black font-mono text-white">
          {pair.asset_b.replace("/USD", "")}
        </span>
      </div>
      <div className="flex items-center gap-3">
        <div className="text-center">
          <div
            className="text-[7px] uppercase tracking-widest"
            style={{ color: C.dim }}
          >
            H
          </div>
          <div
            className="text-[10px] font-mono font-bold"
            style={{
              color:
                pair.hurst < 0.6
                  ? C.green
                  : pair.hurst < 0.75
                  ? C.amber
                  : C.red,
            }}
          >
            {pair.hurst.toFixed(3)}
          </div>
        </div>
        <div className="text-center">
          <div
            className="text-[7px] uppercase tracking-widest"
            style={{ color: C.dim }}
          >
            ADF
          </div>
          <div
            className="text-[10px] font-mono font-bold"
            style={{
              color:
                pair.adf_pvalue < 0.05
                  ? C.green
                  : pair.adf_pvalue < 0.1
                  ? C.amber
                  : C.red,
            }}
          >
            {pair.adf_pvalue.toFixed(3)}
          </div>
        </div>
        <div className="text-center">
          <div
            className="text-[7px] uppercase tracking-widest"
            style={{ color: C.dim }}
          >
            HR
          </div>
          <div className="text-[10px] font-mono font-bold text-white">
            {pair.hedge_ratio.toFixed(3)}
          </div>
        </div>
        <span
          className="text-[8px] font-bold px-1.5 py-0.5 rounded"
          style={{
            color,
            background: `${color}15`,
            border: `1px solid ${color}30`,
            minWidth: 52,
            textAlign: "center",
          }}
        >
          {tradeable ? "TRADEABLE" : "BLOCKED"}
        </span>
      </div>
    </div>
  );
}

function BotLearningRow({
  botId,
  symbols,
}: {
  botId: string;
  symbols: PairLearningSymbol[];
}) {
  const color = BOT_COLORS[botId] ?? "#64748b";
  const botIcon =
    botId === "davy-jones" ? "⚓" : botId === "blackbeard" ? "🏴‍☠️" : "🌊";
  const paused = symbols.filter((s) => s.status === "paused");
  const active = symbols.filter((s) => s.status === "active");

  return (
    <div
      className="rounded-lg border overflow-hidden"
      style={{ borderColor: `${color}20` }}
    >
      <div
        className="px-3 py-2 flex items-center gap-2"
        style={{
          background: `${color}10`,
          borderBottom: `1px solid ${color}20`,
        }}
      >
        <span style={{ fontSize: 14 }}>{botIcon}</span>
        <span
          className="text-[11px] font-black uppercase tracking-wider"
          style={{ color }}
        >
          {botId === "davy-jones"
            ? "Davy Jones"
            : botId === "blackbeard"
            ? "Blackbeard"
            : "Calypso"}
        </span>
        <span className="text-[9px] ml-2" style={{ color: C.dim }}>
          {active.length} active · {paused.length} paused · {symbols.length}{" "}
          symbols
        </span>
      </div>
      <div className="p-2 grid grid-cols-3 gap-1.5">
        {symbols.map((s) => {
          const isPaused = s.status === "paused";
          const borderCol = isPaused ? "rgba(239,68,68,0.35)" : `${color}20`;
          return (
            <div
              key={s.symbol}
              className="rounded p-1.5"
              style={{
                background: isPaused ? "rgba(239,68,68,0.05)" : `${color}06`,
                border: `1px solid ${borderCol}`,
              }}
            >
              <div className="flex items-center gap-1 mb-1">
                <span
                  className="text-[9px] font-black font-mono"
                  style={{ color: isPaused ? C.red : "white" }}
                >
                  {s.symbol.replace("/USD", "")}
                </span>
                {isPaused && <span className="text-[8px]">⛔</span>}
                {!isPaused && s.win_rate != null && (
                  <span
                    className="ml-auto text-[8px] font-mono font-bold"
                    style={{ color: s.win_rate >= 50 ? C.green : C.red }}
                  >
                    {s.win_rate.toFixed(0)}%
                  </span>
                )}
              </div>
              {s.hurst != null && (
                <div className="flex items-center gap-1">
                  <div
                    className="flex-1 h-1 rounded-full overflow-hidden"
                    style={{ background: "rgba(255,255,255,0.06)" }}
                  >
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${Math.min(1, s.hurst) * 100}%`,
                        background:
                          s.hurst < 0.55
                            ? C.green
                            : s.hurst < 0.75
                            ? C.amber
                            : C.red,
                      }}
                    />
                  </div>
                  <span
                    className="text-[8px] font-mono shrink-0"
                    style={{
                      color:
                        s.hurst < 0.55
                          ? C.green
                          : s.hurst < 0.75
                          ? C.amber
                          : C.red,
                      minWidth: 30,
                    }}
                  >
                    H={s.hurst.toFixed(2)}
                  </span>
                </div>
              )}
              {s.total_trades > 0 && (
                <div
                  className="text-[8px] font-mono mt-0.5"
                  style={{ color: s.total_pnl >= 0 ? C.green : C.red }}
                >
                  {fmtPnl(s.total_pnl)} · {s.wins}W/{s.losses}L
                </div>
              )}
              {isPaused && s.adf_pvalue == null && (
                <div
                  className="text-[8px] mt-0.5"
                  style={{ color: "rgba(252,165,165,0.6)" }}
                >
                  stats frozen
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

type View = "fleet" | "bots" | "poseidon";

export default function StreamingScreenV3() {
  const { data, isLoading } = usePairLearning();
  const [view, setView] = useState<View>("fleet");

  const pausedSymbols = useMemo(
    () => (data?.fleet_symbols ?? []).filter((s) => s.any_paused),
    [data]
  );

  const activeSymbols = useMemo(
    () => (data?.fleet_symbols ?? []).filter((s) => !s.any_paused),
    [data]
  );

  const byBot = useMemo(() => {
    const map: Record<string, PairLearningSymbol[]> = {};
    for (const s of data?.symbols ?? []) {
      (map[s.bot_id] ??= []).push(s);
    }
    return map;
  }, [data]);

  const tabs: { id: View; label: string; icon: string }[] = [
    { id: "fleet", label: "Fleet View", icon: "⚡" },
    { id: "bots", label: "Per-Bot", icon: "🤖" },
    { id: "poseidon", label: "Poseidon Pairs", icon: "🔱" },
  ];

  return (
    <div
      className="h-full flex flex-col overflow-hidden"
      style={{
        background: C.bg,
        fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      }}
    >
      {/* Header */}
      <div
        className="flex items-center gap-4 px-4 py-3 shrink-0"
        style={{
          borderBottom: `1px solid ${C.border}`,
          background: "rgba(15,23,42,0.95)",
        }}
      >
        <div className="flex items-center gap-2">
          <span style={{ fontSize: 18 }}>🧠</span>
          <div>
            <div className="text-xs font-black uppercase tracking-widest text-white">
              Python Learning Journal
            </div>
            <div className="text-[9px]" style={{ color: C.dim }}>
              Rule-based pair evaluation · Hurst · ADF · Win rates · Auto-pause
            </div>
          </div>
        </div>

        {data && (
          <div className="flex items-center gap-4 ml-4">
            <div className="text-center">
              <div
                className="text-[8px] uppercase tracking-widest font-bold"
                style={{ color: C.dim }}
              >
                Monitoring
              </div>
              <div className="text-base font-black text-white">
                {data.total_symbols}
              </div>
            </div>
            <div className="w-px h-6" style={{ background: C.border }} />
            <div className="text-center">
              <div
                className="text-[8px] uppercase tracking-widest font-bold"
                style={{ color: C.dim }}
              >
                Active
              </div>
              <div
                className="text-base font-black"
                style={{ color: C.green }}
              >
                {data.active_count}
              </div>
            </div>
            <div className="w-px h-6" style={{ background: C.border }} />
            <div className="text-center">
              <div
                className="text-[8px] uppercase tracking-widest font-bold"
                style={{ color: C.dim }}
              >
                Paused
              </div>
              <div
                className="text-base font-black"
                style={{
                  color: data.paused_count > 0 ? C.red : C.slate,
                }}
              >
                {data.paused_count}
              </div>
            </div>
          </div>
        )}

        <div className="ml-auto flex items-center gap-1">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setView(tab.id)}
              className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] font-bold uppercase tracking-wide transition-all"
              style={{
                background:
                  view === tab.id
                    ? "rgba(139,92,246,0.2)"
                    : "rgba(255,255,255,0.04)",
                color: view === tab.id ? "#a78bfa" : C.slate,
                border: `1px solid ${
                  view === tab.id
                    ? "rgba(139,92,246,0.4)"
                    : "rgba(255,255,255,0.06)"
                }`,
              }}
            >
              <span>{tab.icon}</span>
              <span>{tab.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-4">
        {isLoading ? (
          <div className="flex items-center justify-center h-40">
            <div className="text-xs font-mono" style={{ color: C.dim }}>
              Loading pair learning data...
            </div>
          </div>
        ) : !data ? (
          <div className="flex items-center justify-center h-40">
            <div className="text-xs font-mono" style={{ color: C.dim }}>
              No data available
            </div>
          </div>
        ) : view === "fleet" ? (
          <div className="flex flex-col gap-4">
            {/* Legend */}
            <div
              className="flex flex-wrap items-center gap-4 px-3 py-2 rounded-lg text-[9px] font-bold"
              style={{
                background: "rgba(255,255,255,0.03)",
                border: `1px solid ${C.border}`,
              }}
            >
              <span
                className="uppercase tracking-widest font-bold"
                style={{ color: C.dim }}
              >
                Hurst H:
              </span>
              <span style={{ color: C.green }}>{"< 0.45 Mean-reverts ✓"}</span>
              <span style={{ color: C.amber }}>0.45–0.55 Random walk ~</span>
              <span style={{ color: C.orange }}>0.55–0.75 Trending !</span>
              <span style={{ color: C.red }}>{"> 0.75 Strong trend ✗"}</span>
              <span
                className="ml-auto uppercase tracking-widest"
                style={{ color: C.dim }}
              >
                ADF p {"< 0.05"} = cointegrated
              </span>
            </div>

            {/* Paused symbols */}
            {pausedSymbols.length > 0 && (
              <div>
                <div
                  className="text-[9px] font-black uppercase tracking-widest mb-2 flex items-center gap-2"
                  style={{ color: C.red }}
                >
                  <span>⛔</span>
                  <span>
                    Auto-Paused Symbols ({pausedSymbols.length})
                  </span>
                  <span
                    className="text-[8px] font-normal"
                    style={{ color: C.dim }}
                  >
                    — bot learned these pairs are unprofitable
                  </span>
                </div>
                <div className="flex flex-col gap-1.5">
                  {pausedSymbols.map((s) => (
                    <PausedBanner key={s.symbol} symbol={s} />
                  ))}
                </div>
              </div>
            )}

            {/* Active symbols grid */}
            <div>
              <div
                className="text-[9px] font-black uppercase tracking-widest mb-2 flex items-center gap-2"
                style={{ color: C.green }}
              >
                <span>✓</span>
                <span>Active Symbols ({activeSymbols.length})</span>
                <span
                  className="text-[8px] font-normal"
                  style={{ color: C.dim }}
                >
                  — evaluated every cycle, sorted by Hurst (lower = better)
                </span>
              </div>
              <div
                className="grid gap-2"
                style={{
                  gridTemplateColumns:
                    "repeat(auto-fill, minmax(160px, 1fr))",
                }}
              >
                {activeSymbols.map((s) => (
                  <SymbolCard key={s.symbol} sym={s} />
                ))}
              </div>
            </div>
          </div>
        ) : view === "bots" ? (
          <div className="flex flex-col gap-3">
            <div className="text-[9px] mb-1" style={{ color: C.dim }}>
              Each bot independently evaluates its symbols using Hurst exponent
              and ADF p-value tests. Symbols that fail these tests or have poor
              win rates are automatically paused per-bot.
            </div>
            {Object.entries(byBot).map(([botId, symbols]) => (
              <BotLearningRow
                key={botId}
                botId={botId}
                symbols={symbols}
              />
            ))}
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <div
              className="text-[9px] mb-1"
              style={{ color: C.dim }}
            >
              Poseidon (#7) evaluates pairs for statistical cointegration. Pairs
              must pass Hurst {"< 0.6"} and ADF p-value {"< 0.10"} to be
              tradeable. Hedge ratios are recalculated every 24 hours.
            </div>
            <div
              className="flex flex-wrap items-center gap-4 px-3 py-1.5 rounded text-[9px] font-bold mb-1"
              style={{
                background: "rgba(255,255,255,0.03)",
                border: `1px solid ${C.border}`,
              }}
            >
              <span style={{ color: C.dim }}>
                H {"< 0.6"} = mean-reverting
              </span>
              <span
                className="w-px h-3"
                style={{ background: C.border }}
              />
              <span style={{ color: C.dim }}>
                ADF p {"< 0.05"} = cointegrated
              </span>
              <span
                className="w-px h-3"
                style={{ background: C.border }}
              />
              <span style={{ color: C.dim }}>
                HR = hedge ratio (units B per unit A)
              </span>
            </div>
            <div className="flex flex-col gap-1.5">
              {(data.poseidon_pairs ?? []).map((pair) => (
                <PoseidonPairRow key={pair.pair_set_id} pair={pair} />
              ))}
              {data.poseidon_pairs.length === 0 && (
                <div
                  className="text-center py-8 text-xs font-mono"
                  style={{ color: C.dim }}
                >
                  Poseidon pair discovery running — first cycle takes ~3
                  minutes
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
