/**
 * SaasPortfolioPanel.tsx — User's SaaS paper portfolio summary
 *
 * Displays the $10K demo paper portfolio seeded when Stage 5 first runs.
 * Separate from the bot's portfolio shown in the stat cards above.
 */

import { TrendingUp, TrendingDown, Loader2, AlertCircle } from "lucide-react";
import { useSaasPortfolio, type SaasTrade } from "@/hooks/use-trade";

// ── helpers ───────────────────────────────────────────────────────────────────

function fmtUsd(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

function fmtPct(n: number) {
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function relativeTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const h = Math.floor(diff / 3_600_000);
  const m = Math.floor((diff % 3_600_000) / 60_000);
  if (h > 0) return `${h}h ${m}m ago`;
  if (m > 0) return `${m}m ago`;
  return "just now";
}

// ── Sub-components ────────────────────────────────────────────────────────────

function TradeRow({ t }: { t: SaasTrade }) {
  const isOpen  = t.action === "open";
  const pnl     = t.pnl;
  const pnlPos  = pnl != null && pnl >= 0;

  return (
    <div className="flex items-center justify-between py-2 border-b border-zinc-800 last:border-0">
      <div className="flex items-center gap-2">
        <span className={[
          "w-1.5 h-1.5 rounded-full",
          isOpen ? "bg-indigo-400" : pnlPos ? "bg-emerald-400" : "bg-red-400",
        ].join(" ")} />
        <div>
          <span className="text-zinc-300 text-xs font-mono font-semibold">
            {t.symbol.split("/")[0]}
          </span>
          <span className="text-zinc-600 text-xs ml-1">
            {isOpen ? `open ${t.side?.toUpperCase()}` : "close"}
          </span>
        </div>
      </div>
      <div className="text-right">
        {isOpen ? (
          <div className="text-zinc-400 text-xs font-mono">{t.size_usd ? fmtUsd(t.size_usd) : "—"}</div>
        ) : (
          <div className={["text-xs font-semibold font-mono", pnlPos ? "text-emerald-400" : "text-red-400"].join(" ")}>
            {pnl != null ? (pnlPos ? "+" : "") + fmtUsd(pnl) : "—"}
          </div>
        )}
        <div className="text-zinc-700 text-xs">{relativeTime(t.time)}</div>
      </div>
    </div>
  );
}

// ── Main ─────────────────────────────────────────────────────────────────────

export default function SaasPortfolioPanel() {
  const { data, isLoading, isError } = useSaasPortfolio();

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-zinc-600 text-sm py-4">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading your portfolio…
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="flex items-center gap-2 text-zinc-600 text-sm py-4">
        <AlertCircle className="w-4 h-4" /> Could not load portfolio data.
      </div>
    );
  }

  const pnlPos   = data.pnl_pct >= 0;
  const positions = Object.entries(data.positions);

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900 overflow-hidden">
      {/* Header */}
      <div className="px-5 py-4 border-b border-zinc-800">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-zinc-300 text-sm font-semibold">My Demo Portfolio</div>
            <div className="text-zinc-600 text-xs mt-0.5">
              $10K paper capital · separate from bot
            </div>
          </div>
          <div className="text-right">
            <div className="text-zinc-100 text-lg font-bold font-mono">
              {fmtUsd(data.equity)}
            </div>
            <div className={["text-xs font-semibold flex items-center justify-end gap-1", pnlPos ? "text-emerald-400" : "text-red-400"].join(" ")}>
              {pnlPos ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
              {fmtPct(data.pnl_pct)} all-time
            </div>
          </div>
        </div>
      </div>

      <div className="px-5 py-4 grid grid-cols-3 gap-3 border-b border-zinc-800">
        <div className="text-center">
          <div className="text-zinc-400 text-lg font-bold font-mono">{fmtUsd(data.cash)}</div>
          <div className="text-zinc-600 text-xs mt-0.5">Cash</div>
        </div>
        <div className="text-center">
          <div className="text-zinc-400 text-lg font-bold">{data.positions_count}</div>
          <div className="text-zinc-600 text-xs mt-0.5">Positions</div>
        </div>
        <div className="text-center">
          <div className="text-zinc-400 text-lg font-bold font-mono">{fmtUsd(data.deployed)}</div>
          <div className="text-zinc-600 text-xs mt-0.5">Deployed</div>
        </div>
      </div>

      {/* Open positions */}
      {positions.length > 0 && (
        <div className="px-5 py-3 border-b border-zinc-800">
          <div className="text-zinc-600 text-xs uppercase tracking-wide mb-2">Open Positions</div>
          <div className="flex flex-col gap-2">
            {positions.map(([sym, pos]) => (
              <div key={sym} className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <span className={["rounded px-1.5 py-0.5 text-xs font-semibold", pos.side === "long" ? "bg-emerald-500/15 text-emerald-400" : "bg-red-500/15 text-red-400"].join(" ")}>
                    {pos.side.toUpperCase()}
                  </span>
                  <span className="text-zinc-300 font-mono">{sym.split("/")[0]}</span>
                </div>
                <div className="text-right">
                  <div className="text-zinc-400 font-mono">{fmtUsd(pos.size_usd)}</div>
                  <div className="text-zinc-600">@ {fmtUsd(pos.entry_price)}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent trades */}
      {data.recent_trades.length > 0 ? (
        <div className="px-5 py-3">
          <div className="text-zinc-600 text-xs uppercase tracking-wide mb-1">Recent Trades</div>
          {data.recent_trades.slice(0, 6).map((t, i) => (
            <TradeRow key={i} t={t} />
          ))}
        </div>
      ) : (
        <div className="px-5 py-5 text-center">
          <div className="text-zinc-600 text-sm">No trades yet</div>
          <div className="text-zinc-700 text-xs mt-1">
            Use the Execute button on any symbol card above to open your first position.
          </div>
        </div>
      )}
    </div>
  );
}
