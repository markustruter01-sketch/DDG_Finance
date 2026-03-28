/**
 * TradeModal.tsx — 1-Click Trade Execution Modal
 *
 * Action: open (Execute) or close a position.
 * Mode badge shows PAPER (default) or LIVE (when keys + live-mode are active).
 * Reads API keys from localStorage; passes them in the request body.
 */

import { useState } from "react";
import {
  X, Zap, AlertTriangle, CheckCircle, Loader2,
  TrendingUp, TrendingDown, ShieldCheck, Radio,
} from "lucide-react";
import { useExecuteTrade, useCloseTrade, getTradeMode } from "@/hooks/use-trade";
import type { TradeResult } from "@/hooks/use-trade";

// ── helpers ───────────────────────────────────────────────────────────────────

function fmtUsd(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface TradeModalProps {
  symbol:      string;          // e.g. "BTC/USD"
  base:        string;          // e.g. "BTC"
  label:       string;          // e.g. "Bitcoin"
  action:      "execute" | "close";
  currentSide?: "long" | "short"; // when action=close: shows what's being closed
  onClose:     () => void;
  onSuccess:   () => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function TradeModal({
  symbol, base, label, action, currentSide = "long", onClose, onSuccess,
}: TradeModalProps) {
  const [side, setSide]       = useState<"long" | "short">(
    action === "close" ? currentSide : "long"
  );
  const [sizePct, setSizePct] = useState(10);
  const [result, setResult]   = useState<TradeResult | null>(null);

  const mode          = getTradeMode();
  const isLive        = mode === "live";
  const executeMut    = useExecuteTrade();
  const closeMut      = useCloseTrade();
  const isPending     = executeMut.isPending || closeMut.isPending;

  async function handleConfirm() {
    let res: TradeResult;
    if (action === "execute") {
      res = await executeMut.mutateAsync({ symbol, side, size_pct: sizePct });
    } else {
      res = await closeMut.mutateAsync({ symbol });
    }
    setResult(res);
    if (res.status !== "error") {
      setTimeout(() => { onSuccess(); onClose(); }, 1800);
    }
  }

  return (
    // Backdrop
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.7)", backdropFilter: "blur(4px)" }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="w-full max-w-sm rounded-2xl border border-zinc-700 bg-zinc-900 shadow-2xl overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-800">
          <div className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-indigo-400" />
            <span className="text-zinc-100 font-semibold text-sm">
              {action === "execute" ? "Execute Trade" : "Close Position"}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {/* Mode badge */}
            {isLive ? (
              <span className="flex items-center gap-1 rounded-full bg-red-500/15 border border-red-500/30 px-2 py-0.5 text-red-400 text-xs font-bold">
                <Radio className="w-2.5 h-2.5 animate-pulse" /> LIVE
              </span>
            ) : (
              <span className="flex items-center gap-1 rounded-full bg-zinc-800 border border-zinc-700 px-2 py-0.5 text-zinc-400 text-xs font-semibold">
                <ShieldCheck className="w-2.5 h-2.5" /> PAPER
              </span>
            )}
            <button onClick={onClose} className="text-zinc-600 hover:text-zinc-400 transition-colors">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="px-5 py-5 flex flex-col gap-4">

          {/* Symbol */}
          <div className="flex items-center justify-between">
            <div>
              <div className="text-zinc-100 font-bold text-lg font-mono">{base}/USD</div>
              <div className="text-zinc-500 text-xs">{label}</div>
            </div>
            <div className="text-zinc-600 font-mono text-sm">{symbol}</div>
          </div>

          {/* Side selector (only for execute) */}
          {action === "execute" && (
            <div className="flex rounded-lg border border-zinc-700 overflow-hidden">
              <button
                className={[
                  "flex-1 flex items-center justify-center gap-1.5 py-2 text-sm font-semibold transition-colors",
                  side === "long"
                    ? "bg-emerald-600/20 text-emerald-400 border-r border-zinc-700"
                    : "bg-transparent text-zinc-500 hover:text-zinc-300 border-r border-zinc-700",
                ].join(" ")}
                onClick={() => setSide("long")}
              >
                <TrendingUp className="w-3.5 h-3.5" /> Long
              </button>
              <button
                className={[
                  "flex-1 flex items-center justify-center gap-1.5 py-2 text-sm font-semibold transition-colors",
                  side === "short"
                    ? "bg-red-600/20 text-red-400"
                    : "bg-transparent text-zinc-500 hover:text-zinc-300",
                ].join(" ")}
                onClick={() => setSide("short")}
              >
                <TrendingDown className="w-3.5 h-3.5" /> Short
              </button>
            </div>
          )}

          {/* Closing — show what's being closed */}
          {action === "close" && (
            <div className="flex items-center gap-2 rounded-lg bg-zinc-800 px-3 py-2">
              <span className={[
                "text-xs font-semibold",
                currentSide === "long" ? "text-emerald-400" : "text-red-400",
              ].join(" ")}>
                {currentSide.toUpperCase()} position
              </span>
              <span className="text-zinc-500 text-xs">→ will be closed at market price</span>
            </div>
          )}

          {/* Size slider (only for execute) */}
          {action === "execute" && (
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <label className="text-zinc-400 text-xs font-medium">Position size</label>
                <span className="text-indigo-400 text-sm font-mono font-bold">{sizePct}%</span>
              </div>
              <input
                type="range"
                min={1}
                max={25}
                step={1}
                value={sizePct}
                onChange={(e) => setSizePct(Number(e.target.value))}
                className="w-full accent-indigo-500"
              />
              <div className="flex justify-between text-zinc-600 text-xs">
                <span>1%</span>
                <span className="text-zinc-500">of {isLive ? "your Kraken balance" : "$10K paper balance"}</span>
                <span>25%</span>
              </div>
            </div>
          )}

          {/* Live mode warning */}
          {isLive && (
            <div className="flex items-start gap-2 rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2">
              <AlertTriangle className="w-3.5 h-3.5 text-red-400 mt-0.5 shrink-0" />
              <p className="text-red-300 text-xs leading-relaxed">
                <span className="font-semibold">LIVE MODE:</span> This will execute a real
                market order on your Kraken account using real funds.
              </p>
            </div>
          )}

          {/* Result */}
          {result && (
            <div className={[
              "rounded-lg border px-3 py-3 flex flex-col gap-1",
              result.status === "error"
                ? "border-red-500/30 bg-red-500/5"
                : "border-emerald-500/30 bg-emerald-500/5",
            ].join(" ")}>
              {result.status === "error" ? (
                <>
                  <div className="flex items-center gap-1.5 text-red-400 text-xs font-semibold">
                    <AlertTriangle className="w-3.5 h-3.5" /> Error
                  </div>
                  <p className="text-red-300 text-xs">{result.message}</p>
                </>
              ) : (
                <>
                  <div className="flex items-center gap-1.5 text-emerald-400 text-xs font-semibold">
                    <CheckCircle className="w-3.5 h-3.5" />
                    {result.status === "executed" ? "Order executed" : "Position closed"}
                    <span className="text-zinc-600 font-normal ml-1">
                      ({result.mode})
                    </span>
                  </div>
                  {result.fill_price && (
                    <div className="text-zinc-400 text-xs">
                      Fill price: <span className="font-mono text-zinc-300">{fmtUsd(result.fill_price)}</span>
                    </div>
                  )}
                  {result.size_usd && (
                    <div className="text-zinc-400 text-xs">
                      Size: <span className="font-mono text-zinc-300">{fmtUsd(result.size_usd)}</span>
                    </div>
                  )}
                  {result.pnl !== undefined && (
                    <div className={["text-xs font-semibold", result.pnl >= 0 ? "text-emerald-400" : "text-red-400"].join(" ")}>
                      P&L: {result.pnl >= 0 ? "+" : ""}{fmtUsd(result.pnl)}
                    </div>
                  )}
                  {result.order_id && (
                    <div className="text-zinc-600 text-xs font-mono">
                      ID: {result.order_id}
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        {!result && (
          <div className="px-5 pb-5 flex gap-2">
            <button
              onClick={onClose}
              className="flex-1 rounded-lg border border-zinc-700 bg-zinc-800 hover:bg-zinc-700 py-2.5 text-zinc-400 text-sm font-medium transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleConfirm}
              disabled={isPending}
              className={[
                "flex-1 flex items-center justify-center gap-2 rounded-lg py-2.5 text-sm font-semibold transition-colors disabled:opacity-60",
                isLive
                  ? "bg-red-600 hover:bg-red-500 text-white"
                  : "bg-indigo-600 hover:bg-indigo-500 text-white",
              ].join(" ")}
            >
              {isPending ? (
                <><Loader2 className="w-4 h-4 animate-spin" /> Processing…</>
              ) : action === "execute" ? (
                <><Zap className="w-4 h-4" /> Confirm {side === "long" ? "Long" : "Short"}</>
              ) : (
                <><X className="w-4 h-4" /> Close Position</>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
