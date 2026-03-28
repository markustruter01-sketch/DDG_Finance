/**
 * Dashboard.tsx — AlgoEdge Insight Dashboard
 * Live data from /saas-api/insights, auto-refreshes every 60 seconds.
 */

import { RefreshCw, TrendingUp, TrendingDown, Minus, AlertCircle, Loader2 } from "lucide-react";
import { useInsights, type SymbolRow } from "@/hooks/use-insights";
import { useQueryClient } from "@tanstack/react-query";

// ── helpers ──────────────────────────────────────────────────────────────────

function fmtUsd(n: number | null | undefined) {
  if (n == null) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 }).format(n);
}

function fmtPct(n: number) {
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

function relativeTime(iso: string | null) {
  if (!iso) return null;
  const diff = Date.now() - new Date(iso).getTime();
  const h = Math.floor(diff / 3_600_000);
  const m = Math.floor((diff % 3_600_000) / 60_000);
  if (h > 0) return `${h}h ${m}m ago`;
  return `${m}m ago`;
}

function fgColor(val: number) {
  if (val <= 25) return "text-red-400";
  if (val <= 45) return "text-orange-400";
  if (val <= 55) return "text-zinc-300";
  if (val <= 75) return "text-emerald-400";
  return "text-green-400";
}

function fgBarColor(val: number) {
  if (val <= 25) return "bg-red-500";
  if (val <= 45) return "bg-orange-500";
  if (val <= 55) return "bg-zinc-400";
  if (val <= 75) return "bg-emerald-500";
  return "bg-green-500";
}

// ── Symbol card ───────────────────────────────────────────────────────────────

function SymbolCard({ row }: { row: SymbolRow }) {
  const held = row.status === "held";
  return (
    <div
      className={[
        "rounded-xl border p-4 flex flex-col gap-3 transition-colors",
        held
          ? "border-indigo-500/30 bg-indigo-500/5"
          : "border-zinc-800 bg-zinc-900/60",
      ].join(" ")}
    >
      {/* Header row */}
      <div className="flex items-start justify-between">
        <div>
          <span className="text-zinc-100 font-semibold text-sm font-mono">
            {row.base}
          </span>
          <span className="ml-1 text-zinc-500 text-xs">/USD</span>
          <div className="text-zinc-600 text-xs mt-0.5">{row.label}</div>
        </div>
        <span
          className={[
            "rounded-full px-2 py-0.5 text-xs font-semibold border",
            held
              ? "bg-indigo-500/15 border-indigo-500/30 text-indigo-400"
              : "bg-zinc-800 border-zinc-700 text-zinc-500",
          ].join(" ")}
        >
          {held ? (row.side === "long" ? "LONG" : "SHORT") : "WATCHING"}
        </span>
      </div>

      {/* Position data — only when held */}
      {held ? (
        <div className="flex flex-col gap-1.5">
          <div className="flex justify-between text-xs">
            <span className="text-zinc-500">Entry</span>
            <span className="text-zinc-300 font-mono">
              {fmtUsd(row.entry_price)}
            </span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-zinc-500">Deployed</span>
            <span className="text-zinc-300 font-mono">{fmtUsd(row.size_usd)}</span>
          </div>
          {row.entry_time && (
            <div className="flex justify-between text-xs">
              <span className="text-zinc-500">Opened</span>
              <span className="text-zinc-400">{relativeTime(row.entry_time)}</span>
            </div>
          )}
        </div>
      ) : (
        <div className="text-zinc-700 text-xs">
          Scanning for RSI&lt;40 + Z-score&gt;1.0
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function Dashboard() {
  const { data, isLoading, isError, dataUpdatedAt } = useInsights();
  const qc = useQueryClient();

  function handleRefresh() {
    qc.invalidateQueries({ queryKey: ["saas-insights"] });
  }

  // Loading skeleton
  if (isLoading && !data) {
    return (
      <div className="w-full max-w-6xl mx-auto px-6 py-12 flex flex-col items-center gap-4">
        <Loader2 className="w-6 h-6 text-indigo-400 animate-spin" />
        <span className="text-zinc-500 text-sm">Loading live data…</span>
      </div>
    );
  }

  // Error state
  if (isError || !data) {
    return (
      <div className="w-full max-w-6xl mx-auto px-6 py-12 flex flex-col items-center gap-3">
        <AlertCircle className="w-6 h-6 text-red-400" />
        <p className="text-zinc-400 text-sm">Could not reach the backend API.</p>
        <button
          onClick={handleRefresh}
          className="text-indigo-400 text-xs hover:underline"
        >
          Retry
        </button>
      </div>
    );
  }

  const { portfolio, symbols, sentiment, cycle_count } = data;
  const pnlPositive = portfolio.total_pnl_pct >= 0;
  const lastUpdated = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString()
    : "—";

  return (
    <div className="w-full max-w-6xl mx-auto px-6 py-8 flex flex-col gap-8">

      {/* ── Page header ───────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-zinc-100 text-xl font-bold">Insight Dashboard</h1>
          <p className="text-zinc-500 text-xs mt-0.5">
            Live from paper trading bot · Cycle data · Updated {lastUpdated}
          </p>
        </div>
        <button
          onClick={handleRefresh}
          className="flex items-center gap-1.5 rounded-lg border border-zinc-700 bg-zinc-900 hover:bg-zinc-800 px-3 py-1.5 text-zinc-400 text-xs font-medium transition-colors"
        >
          <RefreshCw className="w-3 h-3" />
          Refresh
        </button>
      </div>

      {/* ── Portfolio stats ────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {/* Equity */}
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
          <div className="text-zinc-500 text-xs font-medium uppercase tracking-wide mb-1">
            Portfolio Equity
          </div>
          <div className="text-zinc-100 text-xl font-bold font-mono">
            {fmtUsd(portfolio.equity)}
          </div>
          <div
            className={[
              "text-xs font-medium mt-1 flex items-center gap-1",
              pnlPositive ? "text-emerald-400" : "text-red-400",
            ].join(" ")}
          >
            {pnlPositive ? (
              <TrendingUp className="w-3 h-3" />
            ) : (
              <TrendingDown className="w-3 h-3" />
            )}
            {fmtPct(portfolio.total_pnl_pct)} all-time
          </div>
        </div>

        {/* Positions */}
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
          <div className="text-zinc-500 text-xs font-medium uppercase tracking-wide mb-1">
            Open Positions
          </div>
          <div className="text-zinc-100 text-xl font-bold">
            {portfolio.positions_count}
            <span className="text-zinc-600 text-base font-normal"> / 10</span>
          </div>
          <div className="mt-2 h-1.5 rounded-full bg-zinc-800">
            <div
              className="h-1.5 rounded-full bg-indigo-500 transition-all"
              style={{ width: `${portfolio.positions_count * 10}%` }}
            />
          </div>
        </div>

        {/* Deployed */}
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
          <div className="text-zinc-500 text-xs font-medium uppercase tracking-wide mb-1">
            Deployed Capital
          </div>
          <div className="text-zinc-100 text-xl font-bold font-mono">
            {fmtUsd(portfolio.deployed)}
          </div>
          <div className="text-zinc-500 text-xs mt-1">
            {portfolio.deployed_pct}% of equity
          </div>
        </div>

        {/* Cash */}
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
          <div className="text-zinc-500 text-xs font-medium uppercase tracking-wide mb-1">
            Cash Reserve
          </div>
          <div className="text-zinc-100 text-xl font-bold font-mono">
            {fmtUsd(portfolio.cash)}
          </div>
          <div className="text-zinc-500 text-xs mt-1">
            {(100 - portfolio.deployed_pct).toFixed(1)}% available
          </div>
        </div>
      </div>

      {/* ── Symbol grid ───────────────────────────────────────────────── */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-zinc-300 text-sm font-semibold">
            Signal Universe —{" "}
            <span className="text-indigo-400">
              {symbols.filter((s) => s.status === "held").length} held
            </span>
            <span className="text-zinc-600">
              {" "}· {symbols.filter((s) => s.status === "watching").length} watching
            </span>
          </h2>
          <span className="text-zinc-600 text-xs font-mono">
            RSI threshold: &lt;40 / &gt;60 · Z: ±1.0
          </span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
          {symbols.map((row) => (
            <SymbolCard key={row.symbol} row={row} />
          ))}
        </div>
      </div>

      {/* ── Sentiment ─────────────────────────────────────────────────── */}
      <div>
        <h2 className="text-zinc-300 text-sm font-semibold mb-4">
          Market Sentiment
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {[
            { title: "Crypto Fear & Greed", ...sentiment.crypto },
            { title: "Equity Market Sentiment", ...sentiment.market },
          ].map(({ title, value, label }) => (
            <div
              key={title}
              className="rounded-xl border border-zinc-800 bg-zinc-900 p-5 flex flex-col gap-3"
            >
              <div className="flex items-center justify-between">
                <span className="text-zinc-500 text-xs font-medium uppercase tracking-wide">
                  {title}
                </span>
                <span className={["text-lg font-bold font-mono", fgColor(value)].join(" ")}>
                  {value}
                </span>
              </div>
              <div className="h-2 rounded-full bg-zinc-800">
                <div
                  className={["h-2 rounded-full transition-all", fgBarColor(value)].join(" ")}
                  style={{ width: `${value}%` }}
                />
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-zinc-600">Extreme Fear</span>
                <span className={["font-semibold", fgColor(value)].join(" ")}>
                  {label}
                </span>
                <span className="text-zinc-600">Extreme Greed</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Bot meta ──────────────────────────────────────────────────── */}
      <div className="flex items-center justify-center gap-2 py-2">
        <Minus className="w-3 h-3 text-zinc-700" />
        <span className="text-zinc-700 text-xs font-mono">
          Paper trading · $100K simulated capital · {cycle_count} trade cycles completed
        </span>
        <Minus className="w-3 h-3 text-zinc-700" />
      </div>
    </div>
  );
}
