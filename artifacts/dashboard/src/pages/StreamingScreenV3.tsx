import { useMemo, useState } from "react";
import { DDGBadge } from "@/components/DDGBadge";
import {
  usePairLearning,
  type PairLearningSymbol,
  type FleetSymbol,
  type PoseidonPairParam,
  type AdaptiveParam,
  type RecentTrade,
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
};

const BOT_ICONS: Record<string, string> = {
  "davy-jones": "⚓",
  blackbeard: "🏛️",
};

const BOT_NAMES: Record<string, string> = {
  "davy-jones": "SPY/QQQ Trend",
  blackbeard: "Jerome",
};

function fmtPnl(v: number, short = false) {
  const abs = Math.abs(v);
  const str =
    abs >= 1000
      ? `$${(abs / 1000).toFixed(1)}k`
      : short
      ? `$${abs.toFixed(0)}`
      : `$${abs.toFixed(2)}`;
  return v >= 0 ? `+${str}` : `-${str}`;
}

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return "—";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function hurstLabel(h: number | null): string {
  if (h == null) return "—";
  if (h < 0.45) return "Mean-reverts ✓";
  if (h < 0.55) return "Random walk ~";
  if (h < 0.75) return "Trending !";
  return "Strong trend ✗";
}

function hurstColor(h: number | null): string {
  if (h == null) return C.dim;
  if (h < 0.45) return C.green;
  if (h < 0.55) return C.amber;
  if (h < 0.75) return C.orange;
  return C.red;
}

function HurstBar({ value }: { value: number | null }) {
  const color = hurstColor(value);
  const pct = value != null ? Math.min(1, value) * 100 : 0;
  return (
    <div className="flex items-center gap-2">
      <div
        className="flex-1 h-2 rounded-full overflow-hidden"
        style={{ background: "rgba(255,255,255,0.06)" }}
      >
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <span
        className="text-[11px] font-mono font-bold shrink-0"
        style={{ color, minWidth: 36 }}
      >
        {value != null ? value.toFixed(3) : "—"}
      </span>
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
      className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded"
      style={{ background: `${color}15`, color, border: `1px solid ${color}30` }}
      title={label}
    >
      p={value.toFixed(3)}
    </span>
  );
}

function InsightCard({
  icon,
  title,
  body,
  accent,
}: {
  icon: string;
  title: string;
  body: string;
  accent: string;
}) {
  return (
    <div
      className="rounded-xl p-3 flex gap-3"
      style={{
        background: `${accent}08`,
        border: `1px solid ${accent}25`,
        flex: "1 1 280px",
      }}
    >
      <span style={{ fontSize: 18, lineHeight: 1.2, flexShrink: 0 }}>{icon}</span>
      <div>
        <div
          className="text-[10px] font-black uppercase tracking-widest mb-1"
          style={{ color: accent }}
        >
          {title}
        </div>
        <div className="text-[11px] leading-relaxed" style={{ color: "rgba(203,213,225,0.8)" }}>
          {body}
        </div>
      </div>
    </div>
  );
}

function SymbolCard({ sym }: { sym: FleetSymbol }) {
  const isPaused = sym.any_paused;
  const totalTrades = sym.total_wins + sym.total_losses;
  const winRate = totalTrades > 0 ? (sym.total_wins / totalTrades) * 100 : null;
  const color = hurstColor(sym.avg_hurst);
  const borderColor = isPaused ? "rgba(239,68,68,0.45)" : `${color}22`;

  return (
    <div
      className="rounded-xl p-4 flex flex-col gap-3"
      style={{ background: C.card, border: `1px solid ${borderColor}` }}
    >
      <div className="flex items-center gap-2">
        {isPaused && <span className="text-base">⛔</span>}
        <span className="text-base font-black font-mono text-white">
          {sym.symbol.replace("/USD", "")}
        </span>
        <span
          className="text-[9px] font-bold px-1.5 py-0.5 rounded ml-auto"
          style={{
            color: isPaused ? C.red : C.green,
            background: isPaused ? "rgba(239,68,68,0.12)" : "rgba(74,222,128,0.1)",
          }}
        >
          {isPaused ? "PAUSED" : "ACTIVE"}
        </span>
      </div>

      <div>
        <div
          className="text-[8px] font-bold uppercase tracking-widest mb-1.5"
          style={{ color: C.dim }}
        >
          Hurst Exponent
        </div>
        <HurstBar value={sym.avg_hurst} />
        <div className="text-[9px] mt-1" style={{ color }}>
          {hurstLabel(sym.avg_hurst)}
        </div>
      </div>

      <div className="flex items-center justify-between">
        <div>
          <div
            className="text-[8px] font-bold uppercase tracking-widest mb-1"
            style={{ color: C.dim }}
          >
            ADF Test
          </div>
          <AdfBadge value={sym.avg_adf_pvalue} />
        </div>
        <div className="text-right">
          <div
            className="text-[8px] font-bold uppercase tracking-widest mb-1"
            style={{ color: C.dim }}
          >
            Fleet P&amp;L
          </div>
          <span
            className="text-sm font-black font-mono"
            style={{ color: sym.total_pnl >= 0 ? C.green : C.red }}
          >
            {fmtPnl(sym.total_pnl, true)}
          </span>
        </div>
      </div>

      <div
        className="pt-2"
        style={{ borderTop: `1px solid ${C.border}` }}
      >
        <div
          className="text-[8px] font-bold uppercase tracking-widest mb-1"
          style={{ color: C.dim }}
        >
          Trade Record
        </div>
        {totalTrades === 0 ? (
          <span className="text-[10px]" style={{ color: C.dim }}>
            No trades yet
          </span>
        ) : (
          <div className="flex items-center gap-2">
            <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: "rgba(239,68,68,0.2)" }}>
              <div
                className="h-full rounded-full"
                style={{
                  width: `${winRate ?? 0}%`,
                  background: (winRate ?? 0) >= 50 ? C.green : C.amber,
                }}
              />
            </div>
            <span
              className="text-[10px] font-mono font-bold"
              style={{ color: (winRate ?? 0) >= 50 ? C.green : C.red }}
            >
              {winRate != null ? `${winRate.toFixed(0)}%` : "—"}
            </span>
            <span className="text-[9px]" style={{ color: C.dim }}>
              {sym.total_wins}W / {sym.total_losses}L
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function AdaptiveParamsPanel({ ap }: { ap: AdaptiveParam }) {
  const color = BOT_COLORS[ap.bot_id] ?? "#64748b";
  const icon = BOT_ICONS[ap.bot_id] ?? "🤖";
  const name = BOT_NAMES[ap.bot_id] ?? ap.bot_id;
  const m = ap.metrics;
  const hasReasons = Object.keys(ap.reasons).length > 0;

  const paramLabels: Record<string, string> = {
    ZSCORE_ENTRY: "Z-Entry",
    ZSCORE_EXIT: "Z-Exit",
    STOP_LOSS_PCT: "Stop %",
    TRAIL_PCT: "Trail %",
    MIN_NET_PROFIT_PCT: "Min Profit %",
  };

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ border: `1px solid ${color}20` }}
    >
      <div
        className="px-4 py-2.5 flex items-center gap-2"
        style={{ background: `${color}10`, borderBottom: `1px solid ${color}20` }}
      >
        <span style={{ fontSize: 16 }}>{icon}</span>
        <span className="text-xs font-black uppercase tracking-widest" style={{ color }}>
          {name}
        </span>
        <span className="text-[9px] ml-1" style={{ color: C.dim }}>
          {ap.lookback_n > 0 ? `over ${ap.lookback_n} trades` : "initializing"}
        </span>
        <span className="ml-auto text-[9px]" style={{ color: C.dim }}>
          adapted {timeAgo(ap.adapted_at)}
        </span>
      </div>

      <div className="p-3 flex gap-4 flex-wrap">
        {/* Live params */}
        <div className="flex-1 min-w-[180px]">
          <div className="text-[8px] font-bold uppercase tracking-widest mb-2" style={{ color: C.dim }}>
            Live Parameters
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1.5">
            {Object.entries(ap.params)
              .filter(([k]) => !k.startsWith("_"))
              .map(([k, v]) => (
                <div key={k} className="flex items-center gap-1.5">
                  <span className="text-[9px]" style={{ color: C.dim }}>
                    {paramLabels[k] ?? k}
                  </span>
                  <span className="text-[10px] font-mono font-bold text-white">
                    {typeof v === "number"
                      ? k.includes("PCT")
                        ? `${(v * 100).toFixed(1)}%`
                        : v.toFixed(2)
                      : String(v)}
                  </span>
                </div>
              ))}
          </div>
        </div>

        {/* Performance metrics */}
        {Object.keys(m).length > 1 && (
          <div className="flex-1 min-w-[180px]">
            <div className="text-[8px] font-bold uppercase tracking-widest mb-2" style={{ color: C.dim }}>
              Performance Metrics
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1.5">
              {m.win_rate != null && (
                <div className="flex items-center gap-1.5">
                  <span className="text-[9px]" style={{ color: C.dim }}>Win rate</span>
                  <span
                    className="text-[10px] font-mono font-bold"
                    style={{ color: m.win_rate >= 0.5 ? C.green : C.red }}
                  >
                    {(m.win_rate * 100).toFixed(0)}%
                  </span>
                </div>
              )}
              {m.profit_factor != null && (
                <div className="flex items-center gap-1.5">
                  <span className="text-[9px]" style={{ color: C.dim }}>Prof. factor</span>
                  <span
                    className="text-[10px] font-mono font-bold"
                    style={{ color: m.profit_factor >= 1 ? C.green : C.red }}
                  >
                    {m.profit_factor.toFixed(2)}
                  </span>
                </div>
              )}
              {m.consec_losses != null && m.consec_losses > 0 && (
                <div className="flex items-center gap-1.5">
                  <span className="text-[9px]" style={{ color: C.dim }}>Consec. losses</span>
                  <span
                    className="text-[10px] font-mono font-bold"
                    style={{ color: m.consec_losses >= 5 ? C.red : C.amber }}
                  >
                    {m.consec_losses}
                  </span>
                </div>
              )}
              {m.stop_loss_rate != null && (
                <div className="flex items-center gap-1.5">
                  <span className="text-[9px]" style={{ color: C.dim }}>Stop-hit rate</span>
                  <span
                    className="text-[10px] font-mono font-bold"
                    style={{ color: m.stop_loss_rate > 0.3 ? C.red : C.slate }}
                  >
                    {(m.stop_loss_rate * 100).toFixed(0)}%
                  </span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Adaptation reasons */}
      {hasReasons && (
        <div className="px-3 pb-3">
          <div className="text-[8px] font-bold uppercase tracking-widest mb-1.5" style={{ color: C.amber }}>
            Why the bot adapted
          </div>
          <div className="flex flex-col gap-1">
            {Object.entries(ap.reasons).map(([param, reason]) => (
              <div
                key={param}
                className="flex items-start gap-2 text-[9px] px-2 py-1.5 rounded"
                style={{ background: "rgba(251,191,36,0.06)", border: "1px solid rgba(251,191,36,0.15)" }}
              >
                <span className="font-mono font-bold shrink-0" style={{ color: C.amber }}>
                  {paramLabels[param] ?? param}
                </span>
                <span style={{ color: "rgba(203,213,225,0.7)" }}>{reason}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function TradeRow({ trade }: { trade: RecentTrade }) {
  const color = BOT_COLORS[trade.bot_id] ?? "#64748b";
  const won = trade.pnl_usd > 0;
  return (
    <div
      className="flex items-center gap-3 px-3 py-2 rounded-lg"
      style={{
        background: won ? "rgba(74,222,128,0.04)" : "rgba(248,113,113,0.04)",
        border: `1px solid ${won ? "rgba(74,222,128,0.1)" : "rgba(248,113,113,0.1)"}`,
      }}
    >
      <span className="text-[9px] font-bold shrink-0" style={{ color }}>
        {BOT_ICONS[trade.bot_id]} {BOT_NAMES[trade.bot_id] ?? trade.bot_id}
      </span>
      <span className="text-[10px] font-mono font-black text-white shrink-0">
        {trade.symbol.replace("/USD", "")}
      </span>
      <span
        className="text-[9px] px-1.5 py-0.5 rounded font-bold uppercase tracking-wide shrink-0"
        style={{
          color: trade.side === "long" ? C.green : C.red,
          background: trade.side === "long" ? "rgba(74,222,128,0.1)" : "rgba(248,113,113,0.1)",
        }}
      >
        {trade.side}
      </span>
      <span
        className="ml-auto text-[11px] font-mono font-black"
        style={{ color: won ? C.green : C.red }}
      >
        {fmtPnl(trade.pnl_usd)}
      </span>
      <span className="text-[9px] shrink-0" style={{ color: C.dim }}>
        {timeAgo(trade.closed_at)}
      </span>
    </div>
  );
}

function PoseidonPairRow({ pair }: { pair: PoseidonPairParam }) {
  const tradeable = pair.is_tradeable;
  const hurstOk = pair.hurst < 0.6;
  const adfOk = pair.adf_pvalue < 0.05;
  const health = tradeable && hurstOk && adfOk ? "good" : tradeable ? "ok" : "blocked";
  const color = health === "good" ? C.green : health === "ok" ? C.amber : C.red;
  return (
    <div
      className="flex items-center gap-3 px-3 py-2.5 rounded-lg"
      style={{ background: `${color}05`, border: `1px solid ${color}15` }}
    >
      <span className="text-[8px] font-bold font-mono" style={{ color: C.dim, minWidth: 20 }}>
        #{pair.pair_set_id}
      </span>
      <div className="flex-1 flex items-center gap-1.5">
        <span className="text-xs font-black font-mono text-white">
          {pair.asset_a.replace("/USD", "")}
        </span>
        <span style={{ color: C.dim }}>↔</span>
        <span className="text-xs font-black font-mono text-white">
          {pair.asset_b.replace("/USD", "")}
        </span>
      </div>
      <div className="flex items-center gap-4 text-center">
        <div>
          <div className="text-[7px] uppercase" style={{ color: C.dim }}>H</div>
          <div
            className="text-[10px] font-mono font-bold"
            style={{ color: pair.hurst < 0.6 ? C.green : pair.hurst < 0.75 ? C.amber : C.red }}
          >
            {pair.hurst.toFixed(3)}
          </div>
        </div>
        <div>
          <div className="text-[7px] uppercase" style={{ color: C.dim }}>ADF</div>
          <div
            className="text-[10px] font-mono font-bold"
            style={{ color: pair.adf_pvalue < 0.05 ? C.green : pair.adf_pvalue < 0.1 ? C.amber : C.red }}
          >
            {pair.adf_pvalue.toFixed(3)}
          </div>
        </div>
        <div>
          <div className="text-[7px] uppercase" style={{ color: C.dim }}>Hedge</div>
          <div className="text-[10px] font-mono font-bold text-white">
            {pair.hedge_ratio.toFixed(3)}
          </div>
        </div>
      </div>
      <span
        className="text-[9px] font-bold px-2 py-0.5 rounded shrink-0"
        style={{ color, background: `${color}15`, border: `1px solid ${color}30`, minWidth: 64, textAlign: "center" }}
      >
        {tradeable ? "TRADEABLE" : "BLOCKED"}
      </span>
    </div>
  );
}

function buildInsights(data: {
  fleet_symbols: FleetSymbol[];
  adaptive_params: AdaptiveParam[];
  recent_trades: RecentTrade[];
  paused_count: number;
  bot_slot_active: number;
}): Array<{ icon: string; title: string; body: string; accent: string }> {
  const insights: Array<{ icon: string; title: string; body: string; accent: string }> = [];

  const activeSyms = data.fleet_symbols.filter((s) => !s.any_paused);
  const trendingCount = activeSyms.filter((s) => s.avg_hurst != null && s.avg_hurst > 0.75).length;
  const meanRevCount = activeSyms.filter((s) => s.avg_hurst != null && s.avg_hurst < 0.55).length;

  if (trendingCount > 0) {
    insights.push({
      icon: "📈",
      title: "Market Is Trending",
      body: `${trendingCount} of ${activeSyms.length} active symbols have Hurst > 0.75, indicating strong directional momentum. The Hurst filter is blocking mean-reversion entries on these — this is working as intended.`,
      accent: C.amber,
    });
  }

  if (meanRevCount > 0) {
    insights.push({
      icon: "↩️",
      title: "Mean-Reverting Opportunities",
      body: `${meanRevCount} symbol${meanRevCount > 1 ? "s are" : " is"} showing Hurst < 0.55 — the regime the strategy is built for. These are being actively evaluated for entries.`,
      accent: C.green,
    });
  }

  const adapted = data.adaptive_params.filter((ap) => Object.keys(ap.reasons).length > 0);
  if (adapted.length > 0) {
    const names = adapted.map((a) => BOT_NAMES[a.bot_id] ?? a.bot_id).join(", ");
    insights.push({
      icon: "⚙️",
      title: "Parameters Auto-Adapted",
      body: `${names} ha${adapted.length === 1 ? "s" : "ve"} already self-tuned based on live trade results. The system is raising entry thresholds and profit floors in response to high stop-loss rates.`,
      accent: C.violet,
    });
  }

  if (data.paused_count > 0) {
    insights.push({
      icon: "🛑",
      title: "Auto-Pause System Active",
      body: `${data.paused_count} symbol${data.paused_count > 1 ? "s have" : " has"} been automatically paused after failing win rate, Hurst, or profit factor thresholds. This prevents the fleet from trading toxic pairs.`,
      accent: C.red,
    });
  }

  const totalPnl = data.fleet_symbols.reduce((sum, s) => sum + s.total_pnl, 0);
  if (data.recent_trades.length > 0) {
    const allShort = data.recent_trades.every((t) => t.side === "short");
    if (allShort) {
      insights.push({
        icon: "🔻",
        title: "All Trades Were Short",
        body: `The last ${data.recent_trades.length} closed trades were all short (mean-reversion from above). In the current risk-off trending market, these positions moved against the strategy — confirming the Hurst filter's caution.`,
        accent: C.cyan,
      });
    }
  }

  if (insights.length === 0) {
    insights.push({
      icon: "🔍",
      title: "Learning In Progress",
      body: "The fleet is accumulating trade data. Insights will appear automatically as the bots evaluate symbols, close trades, and adapt their parameters.",
      accent: C.slate,
    });
  }

  return insights;
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

  const insights = useMemo(
    () =>
      data
        ? buildInsights({
            fleet_symbols: data.fleet_symbols,
            adaptive_params: data.adaptive_params,
            recent_trades: data.recent_trades,
            paused_count: data.paused_count,
            bot_slot_active: data.bot_slot_active,
          })
        : [],
    [data]
  );

  const tabs: { id: View; label: string; icon: string }[] = [
    { id: "fleet", label: "Fleet View", icon: "⚡" },
    { id: "bots", label: "Per-Bot", icon: "🤖" },
    { id: "poseidon", label: "Poseidon Pairs", icon: "🔱" },
  ];

  return (
    <div
      className="h-full flex flex-col overflow-hidden relative"
      style={{ background: C.bg, fontFamily: "'JetBrains Mono','Fira Code',monospace" }}
    >
      {/* ── Title bar ── */}
      <div
        className="px-5 pt-5 pb-4 shrink-0"
        style={{ borderBottom: `1px solid ${C.border}`, background: "rgba(15,23,42,0.98)" }}
      >
        {/* Stats */}
          {data && (
            <div className="flex items-center gap-5 shrink-0">
              <div className="text-center">
                <div className="text-[9px] uppercase tracking-widest font-bold" style={{ color: C.dim }}>Symbols</div>
                <div className="text-2xl font-black text-white leading-none mt-0.5">{data.total_symbols}</div>
              </div>
              <div className="w-px h-8" style={{ background: C.border }} />
              <div className="text-center">
                <div className="text-[9px] uppercase tracking-widest font-bold" style={{ color: C.dim }}>Active</div>
                <div className="text-2xl font-black leading-none mt-0.5" style={{ color: C.green }}>{data.active_count}</div>
              </div>
              <div className="w-px h-8" style={{ background: C.border }} />
              <div className="text-center">
                <div className="text-[9px] uppercase tracking-widest font-bold" style={{ color: C.dim }}>Paused</div>
                <div
                  className="text-2xl font-black leading-none mt-0.5"
                  style={{ color: data.paused_count > 0 ? C.red : C.slate }}
                >
                  {data.paused_count}
                </div>
              </div>
              <div className="w-px h-8" style={{ background: C.border }} />
              <div className="text-center">
                <div className="text-[9px] uppercase tracking-widest font-bold" style={{ color: C.dim }}>All Trades</div>
                <div className="text-2xl font-black text-white leading-none mt-0.5">{data.total_trade_count ?? data.recent_trades.length}</div>
              </div>
            </div>
          )}

          {/* Tabs */}
          <div className="flex items-center gap-1 ml-4 shrink-0">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setView(tab.id)}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-[10px] font-bold uppercase tracking-wide transition-all"
                style={{
                  background: view === tab.id ? "rgba(139,92,246,0.2)" : "rgba(255,255,255,0.04)",
                  color: view === tab.id ? "#a78bfa" : C.slate,
                  border: `1px solid ${view === tab.id ? "rgba(139,92,246,0.4)" : C.border}`,
                }}
              >
                <span>{tab.icon}</span>
                <span>{tab.label}</span>
              </button>
            ))}
          </div>

        {/* Hurst legend */}
        <div
          className="flex flex-wrap items-center gap-4 px-3 py-1.5 rounded-lg text-[9px] font-bold"
          style={{ background: "rgba(255,255,255,0.03)", border: `1px solid ${C.border}` }}
        >
          <span className="uppercase tracking-widest" style={{ color: C.dim }}>Hurst H:</span>
          <span style={{ color: C.green }}>{"< 0.45"} Mean-reverts ✓</span>
          <span style={{ color: C.amber }}>0.45–0.55 Random walk ~</span>
          <span style={{ color: C.orange }}>0.55–0.75 Trending !</span>
          <span style={{ color: C.red }}>{"> 0.75"} Strong trend ✗</span>
          <span className="ml-auto" style={{ color: C.dim }}>
            ADF p {"< 0.05"} = cointegrated · refreshes every 60s
          </span>
        </div>
      </div>

      {/* ── Content ── */}
      <div className="flex-1 overflow-auto p-4">
        {isLoading && (
          <div className="flex items-center justify-center h-40">
            <div className="text-xs font-mono" style={{ color: C.dim }}>
              Loading learning data…
            </div>
          </div>
        )}

        {!isLoading && !data && (
          <div className="flex items-center justify-center h-40">
            <div className="text-xs font-mono" style={{ color: C.dim }}>No data available</div>
          </div>
        )}

        {!isLoading && data && view === "fleet" && (
          <div className="flex flex-col gap-5">
            {/* Insights */}
            <div>
              <div
                className="text-[9px] font-black uppercase tracking-widest mb-2"
                style={{ color: C.violet }}
              >
                ✦ What the fleet has learned
              </div>
              <div className="flex flex-wrap gap-2">
                {insights.map((ins, i) => (
                  <InsightCard key={i} {...ins} />
                ))}
              </div>
            </div>

            {/* Paused symbols */}
            {pausedSymbols.length > 0 && (
              <div>
                <div
                  className="text-[9px] font-black uppercase tracking-widest mb-2"
                  style={{ color: C.red }}
                >
                  ⛔ Auto-paused symbols ({pausedSymbols.length}) — bot learned these pairs are unprofitable
                </div>
                <div className="flex flex-col gap-2">
                  {pausedSymbols.map((s) => (
                    <div
                      key={s.symbol}
                      className="rounded-xl p-3 border"
                      style={{ background: "rgba(239,68,68,0.06)", borderColor: "rgba(239,68,68,0.3)" }}
                    >
                      <div className="flex items-center gap-2 mb-1.5">
                        <span className="text-[10px] font-black text-red-400">⛔ PAUSED</span>
                        <span className="text-sm font-black font-mono text-white">
                          {s.symbol.replace("/USD", "")}
                        </span>
                        <span className="text-[9px]" style={{ color: C.dim }}>
                          {s.bot_count} bot{s.bot_count !== 1 ? "s" : ""}
                        </span>
                        {s.total_pnl !== 0 && (
                          <span
                            className="ml-auto text-[9px] font-mono font-bold"
                            style={{ color: s.total_pnl >= 0 ? C.green : C.red }}
                          >
                            {fmtPnl(s.total_pnl, true)}
                          </span>
                        )}
                      </div>
                      {s.pause_reason && (
                        <p className="text-[9px] leading-relaxed" style={{ color: "rgba(252,165,165,0.7)" }}>
                          {s.pause_reason.length > 240
                            ? s.pause_reason.slice(0, 240) + "…"
                            : s.pause_reason}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Active symbol grid */}
            <div>
              <div
                className="text-[9px] font-black uppercase tracking-widest mb-2"
                style={{ color: C.green }}
              >
                ✓ Active symbols ({activeSymbols.length}) — evaluated every cycle
              </div>
              <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))" }}>
                {activeSymbols.map((s) => (
                  <SymbolCard key={s.symbol} sym={s} />
                ))}
              </div>
            </div>

            {/* Adaptive parameters */}
            {data.adaptive_params.length > 0 && (
              <div>
                <div
                  className="text-[9px] font-black uppercase tracking-widest mb-2"
                  style={{ color: C.amber }}
                >
                  ⚙️ Adaptive parameters — self-tuning in response to live results
                </div>
                <div className="flex flex-col gap-2">
                  {data.adaptive_params.map((ap) => (
                    <AdaptiveParamsPanel key={ap.bot_id} ap={ap} />
                  ))}
                </div>
              </div>
            )}

            {/* Recent trade feed */}
            {data.recent_trades.length > 0 && (
              <div>
                <div
                  className="text-[9px] font-black uppercase tracking-widest mb-2"
                  style={{ color: C.cyan }}
                >
                  🕐 Recent trade history — last {data.recent_trades.length} closed trades
                </div>
                <div className="flex flex-col gap-1">
                  {data.recent_trades.map((t, i) => (
                    <TradeRow key={i} trade={t} />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {!isLoading && data && view === "bots" && (
          <div className="flex flex-col gap-4">
            <div className="text-[10px]" style={{ color: C.dim }}>
              Each bot independently evaluates its own symbol universe. Symbols that fail Hurst/ADF
              thresholds or show poor win rates are automatically paused per-bot.
            </div>
            {Object.entries(byBot).map(([botId, symbols]) => {
              const color = BOT_COLORS[botId] ?? "#64748b";
              const icon = BOT_ICONS[botId] ?? "🤖";
              const name = BOT_NAMES[botId] ?? botId;
              const paused = symbols.filter((s) => s.status === "paused");
              const active = symbols.filter((s) => s.status === "active");
              return (
                <div
                  key={botId}
                  className="rounded-xl overflow-hidden"
                  style={{ border: `1px solid ${color}20` }}
                >
                  <div
                    className="px-4 py-2.5 flex items-center gap-2"
                    style={{ background: `${color}10`, borderBottom: `1px solid ${color}20` }}
                  >
                    <span style={{ fontSize: 16 }}>{icon}</span>
                    <span className="text-xs font-black uppercase tracking-wider" style={{ color }}>
                      {name}
                    </span>
                    <span className="text-[9px] ml-2" style={{ color: C.dim }}>
                      {active.length} active · {paused.length} paused · {symbols.length} symbols tracked
                    </span>
                  </div>
                  <div className="p-3 grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(170px, 1fr))" }}>
                    {symbols.map((s) => {
                      const isPaused = s.status === "paused";
                      return (
                        <div
                          key={s.symbol}
                          className="rounded-lg p-2.5"
                          style={{
                            background: isPaused ? "rgba(239,68,68,0.06)" : `${color}07`,
                            border: `1px solid ${isPaused ? "rgba(239,68,68,0.3)" : `${color}22`}`,
                          }}
                        >
                          <div className="flex items-center gap-1.5 mb-2">
                            <span
                              className="text-[11px] font-black font-mono"
                              style={{ color: isPaused ? C.red : "white" }}
                            >
                              {s.symbol.replace("/USD", "")}
                            </span>
                            {isPaused && <span>⛔</span>}
                            {!isPaused && s.win_rate != null && (
                              <span
                                className="ml-auto text-[9px] font-mono font-bold"
                                style={{ color: s.win_rate >= 50 ? C.green : C.red }}
                              >
                                {s.win_rate.toFixed(0)}%
                              </span>
                            )}
                          </div>
                          {s.hurst != null && (
                            <div>
                              <div className="text-[8px] mb-1" style={{ color: C.dim }}>Hurst</div>
                              <HurstBar value={s.hurst} />
                            </div>
                          )}
                          {s.adf_pvalue != null && (
                            <div className="flex items-center gap-2 mt-1.5">
                              <span className="text-[8px]" style={{ color: C.dim }}>ADF</span>
                              <AdfBadge value={s.adf_pvalue} />
                            </div>
                          )}
                          {s.total_trades > 0 && (
                            <div
                              className="text-[9px] font-mono mt-1.5"
                              style={{ color: s.total_pnl >= 0 ? C.green : C.red }}
                            >
                              {fmtPnl(s.total_pnl, true)} · {s.wins}W/{s.losses}L
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {!isLoading && data && view === "poseidon" && (
          <div className="flex flex-col gap-3">
            <div className="text-[10px]" style={{ color: C.dim }}>
              Poseidon (#7) evaluates each pair for statistical cointegration every 24 hours. Pairs must pass
              Hurst {"< 0.6"} and ADF p-value {"< 0.10"} to be traded. Hedge ratios are recalculated via OLS regression.
            </div>
            <div
              className="flex flex-wrap gap-4 px-3 py-1.5 rounded text-[9px] font-bold"
              style={{ background: "rgba(255,255,255,0.03)", border: `1px solid ${C.border}` }}
            >
              <span style={{ color: C.dim }}>H {"< 0.6"} = mean-reverting</span>
              <span style={{ color: C.dim }}>ADF p {"< 0.05"} = cointegrated</span>
              <span style={{ color: C.dim }}>Hedge = β (units B per unit A)</span>
              <span className="ml-auto" style={{ color: C.dim }}>
                {data.poseidon_pairs.filter((p) => p.is_tradeable).length} / {data.poseidon_pairs.length} tradeable
              </span>
            </div>
            <div className="flex flex-col gap-1.5">
              {data.poseidon_pairs.map((pair) => (
                <PoseidonPairRow key={pair.pair_set_id} pair={pair} />
              ))}
              {data.poseidon_pairs.length === 0 && (
                <div className="text-center py-8 text-xs font-mono" style={{ color: C.dim }}>
                  Poseidon pair discovery running — first cycle takes ~3 minutes
                </div>
              )}
            </div>
          </div>
        )}
      </div>
      <DDGBadge style={{ position: "absolute", bottom: 10, left: 10, zIndex: 50 }} />
    </div>
  );
}
