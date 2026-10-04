import { useState } from "react";
import { cn, formatCurrency, formatCryptoPrice } from "@/lib/utils";
import { formatBotLabel, useBotIdentity } from "@/lib/bot-identity";
import { MarketStatusBadge, isAssetCrypto, HEALTH_COLOR_MAP, RollingPnl } from "@/lib/dashboard-shared";
import type { LivePosition } from "@/hooks/use-trading";
import { useStatusSummary } from "@/hooks/use-trading";
import { Badge } from "@/components/ui";
import { motion, AnimatePresence } from "framer-motion";
import { LogOut, RefreshCw, Sparkles, X } from "lucide-react";

export function KrakenPositionCard({
  kpos,
  signals,
  isPaper,
  compact = false,
}: {
  kpos: { symbol: string; side: string; qty: number; entry_price: number; current_price: number; size_usd: number; unrealized_pnl_usd: number; unrealized_pnl_pct: number; entry_time: string; best_price: number; stop_loss_price: number; take_profit_price: number };
  signals?: any[];
  isPaper?: boolean;
  compact?: boolean;
}) {
  const { getBotIdentity } = useBotIdentity();
  const davyJonesIdentity = getBotIdentity("davy-jones");
  const [expanded, setExpanded] = useState(false);
  const pnlUsd  = typeof kpos.unrealized_pnl_usd === "number" ? kpos.unrealized_pnl_usd : null;
  const isUp    = pnlUsd == null ? true : pnlUsd >= 0;
  const pnlPct  = typeof kpos.unrealized_pnl_pct === "number" ? kpos.unrealized_pnl_pct : null;
  const sym     = kpos.symbol.replace("/USD", "");
  const trailActive = kpos.best_price != null && kpos.best_price > kpos.entry_price;
  const hoursIn = kpos.entry_time
    ? (Date.now() - new Date(kpos.entry_time).getTime()) / 3_600_000
    : null;
  const ageLabel = hoursIn == null ? null : hoursIn < 2 ? "Fresh" : hoursIn < 12 ? "Active" : hoursIn < 48 ? "Aging" : "Stale";
  const ageColor = hoursIn == null ? "#64748b" : hoursIn < 2 ? "#22c55e" : hoursIn < 12 ? "#22d3ee" : hoursIn < 48 ? "#f59e0b" : "#ef4444";
  const sig        = signals?.find((s: any) => s.symbol === kpos.symbol);
  const zScore     = sig?.z_score ?? null;
  const conviction = zScore != null ? Math.min(Math.abs(zScore) / 2, 1) : null;

  return (
    <div
      onClick={() => setExpanded(v => !v)}
      className={cn(
        "rounded-lg border cursor-pointer select-none transition-all duration-200",
        isUp ? "border-cyan-500/20 bg-cyan-950/[0.07] hover:bg-cyan-950/20" : "border-red-500/15 bg-red-950/[0.07] hover:bg-red-950/20"
      )}
    >
      <div className={cn("flex items-center gap-2 px-3 overflow-hidden", compact ? "py-1.5" : "py-2")}>
        <span className={cn("w-0.5 h-4 rounded-full shrink-0", isUp ? "bg-cyan-500/70" : "bg-red-400/60")} />
        <span className="font-bold font-mono text-white text-[11px] w-11 shrink-0">{sym}</span>
        <span className={cn(
          "text-[8px] font-bold px-1.5 py-0.5 rounded-full border shrink-0",
          kpos.side === "long"
            ? "text-green-400 border-green-500/30 bg-green-500/10"
            : "text-orange-400 border-orange-500/30 bg-orange-500/10"
        )}>
          {kpos.side.toUpperCase()}
        </span>
        {isPaper && (
          <span className="text-[7px] font-bold px-1 py-0.5 rounded border border-amber-500/25 text-amber-400/60 shrink-0">PAPER</span>
        )}
        <MarketStatusBadge symbol={kpos.symbol} isCrypto={true} />
        <span className={cn("font-mono font-semibold text-[10px] flex-1 tabular-nums", isUp ? "text-green-400" : "text-red-400")}>
          {pnlUsd == null ? "—" : `${isUp ? "+" : ""}$${pnlUsd.toFixed(2)}`}
          <span className="text-[8px] opacity-60 ml-1">({pnlPct == null ? "—" : `${isUp ? "+" : ""}${pnlPct.toFixed(2)}%`})</span>
        </span>
        <span className="text-[9px] font-mono text-red-400/55 shrink-0 hidden sm:inline">
          SL {formatCryptoPrice(kpos.stop_loss_price)}
        </span>
        <span className={cn(
          "text-[8px] px-1.5 py-0.5 rounded-full border shrink-0",
          trailActive ? "text-cyan-400 border-cyan-500/30 bg-cyan-500/10" : "text-slate-500/60 border-slate-700/30 bg-slate-800/20"
        )}>
          {trailActive ? "⚡ trail" : "waiting"}
        </span>
        {hoursIn != null && !compact && (
          <span className="text-[8px] font-mono shrink-0" style={{ color: ageColor }}>{hoursIn.toFixed(0)}h</span>
        )}
        <span className={cn("text-muted-foreground/30 text-[10px] transition-transform duration-200 shrink-0", expanded && "rotate-180")}>▾</span>
      </div>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-3 pt-2 border-t border-white/[0.04] mt-0">
              <div className="grid grid-cols-3 sm:grid-cols-4 gap-x-5 gap-y-2.5">
                {([
                  ["Entry", formatCryptoPrice(kpos.entry_price)],
                  ["Current", formatCryptoPrice(kpos.current_price)],
                  ["Size", formatCurrency(kpos.size_usd)],
                  ["Qty", kpos.qty == null ? "—" : kpos.qty.toFixed(4)],
                  ["Stop loss", formatCryptoPrice(kpos.stop_loss_price)],
                  ["Trail trigger", formatCryptoPrice(kpos.take_profit_price)],
                  ...(conviction != null ? [["Conviction", `${Math.round(conviction * 100)}%`]] : []),
                  ...(hoursIn != null ? [["Age", `${hoursIn.toFixed(0)}h · ${ageLabel}`]] : []),
                ] as [string, string][]).map(([label, value]) => (
                  <div key={label}>
                    <div className="text-[8px] text-muted-foreground/40 uppercase tracking-wide">{label}</div>
                    <div className="text-[10px] font-mono text-white/80 font-semibold mt-0.5">{value}</div>
                  </div>
                ))}
              </div>
              <div className="mt-2 text-[9px] text-cyan-400/40 italic">Mean-reversion · auto-managed by {formatBotLabel(davyJonesIdentity)}</div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function KrakenPositionsPanel({
  positions,
  signals,
  isPaper,
}: {
  positions: { symbol: string; side: string; qty: number; entry_price: number; current_price: number; size_usd: number; unrealized_pnl_usd: number; unrealized_pnl_pct: number; entry_time: string; best_price: number; stop_loss_price: number; take_profit_price: number }[];
  signals?: any[];
  isPaper?: boolean;
}) {
  const { getBotIdentity } = useBotIdentity();
  const davyJonesIdentity = getBotIdentity("davy-jones");
  const [open, setOpen] = useState(true);
  if (positions.length === 0) return null;

  const totalPnl = positions.every((p) => typeof p.unrealized_pnl_usd === "number")
    ? positions.reduce((sum, p) => sum + p.unrealized_pnl_usd, 0)
    : null;
  const isPnlUp  = totalPnl == null ? true : totalPnl >= 0;

  return (
    <div className="border-t border-white/[0.04] bg-cyan-950/[0.03]">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full px-4 py-2 flex items-center gap-2 text-left hover:bg-cyan-500/[0.04] transition-colors"
      >
        <span className="text-[9px] uppercase font-semibold tracking-wider text-cyan-400/60">{davyJonesIdentity.icon} {formatBotLabel(davyJonesIdentity)}</span>
        <Badge variant="outline" className="text-[8px] px-1 py-0 border-cyan-500/20 text-cyan-400/50">{positions.length}</Badge>
        {isPaper && <Badge variant="outline" className="text-[8px] px-1 py-0 border-amber-500/20 text-amber-400/50">PAPER</Badge>}
        <span className="text-[9px] text-muted-foreground/30 ml-1">crypto positions</span>
        <span className={cn("ml-auto text-[11px] font-mono font-semibold tabular-nums", totalPnl == null ? "text-muted-foreground" : isPnlUp ? "text-green-400" : "text-red-400")}>
          {totalPnl == null ? "—" : `${isPnlUp ? "+" : ""}$${totalPnl.toFixed(2)}`}
        </span>
        <span className={cn("text-muted-foreground/30 text-[10px] transition-transform duration-200 ml-2", open && "rotate-180")}>▾</span>
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 space-y-1.5">
              {positions.map((kpos) => (
                <KrakenPositionCard key={kpos.symbol} kpos={kpos} signals={signals} isPaper={isPaper} />
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function AlpacaPositionCard({
  pos, onThesisClick, onEject, confirmClose, setConfirmClose,
  isClosing, isRebalancing, closingSymbol, compact = false,
}: {
  pos: LivePosition;
  onThesisClick: (ticker: string, thesis: string | null) => void;
  onEject: (symbol: string) => void;
  confirmClose: string | null;
  setConfirmClose: (s: string | null) => void;
  isClosing: boolean;
  isRebalancing: boolean;
  closingSymbol: string | null;
  compact?: boolean;
}) {
  const { getBotIdentity } = useBotIdentity();
  const oracleIdentity = getBotIdentity("oracle");
  const [expanded, setExpanded] = useState(false);
  const isShort = (pos.side ?? "long").toLowerCase() === "short";
  const isBearHedge = (pos.asset_class ?? "").toLowerCase() === "bear_hedge";
  const isUp  = pos.unrealized_pl == null ? true : pos.unrealized_pl >= 0;
  const pnlPct = pos.unrealized_plpc == null ? null : pos.unrealized_plpc * 100;

  return (
    <div
      onClick={() => setExpanded(v => !v)}
      className={cn(
        "rounded-lg border cursor-pointer select-none transition-all duration-200",
        isShort
          ? "border-red-500/25 bg-red-950/[0.08] hover:bg-red-950/20"
          : isUp
            ? "border-green-500/20 bg-green-950/[0.07] hover:bg-green-950/20"
            : "border-red-500/15 bg-red-950/[0.07] hover:bg-red-950/20"
      )}
    >
      <div className={cn("flex items-center gap-2 px-3 overflow-hidden", compact ? "py-1.5" : "py-2")}>
        <span className={cn("w-0.5 h-4 rounded-full shrink-0", isShort ? "bg-red-500/70" : isUp ? "bg-green-500/70" : "bg-red-400/60")} />
        <span className="font-bold font-mono text-white text-[11px] w-12 shrink-0">{pos.symbol}</span>
        {isBearHedge && (
          <span className="text-[7px] font-bold px-1.5 py-0.5 rounded-full border text-orange-400 border-orange-500/30 bg-orange-500/10 shrink-0">BEAR</span>
        )}
        {!isBearHedge && !isShort && (
          <span className="text-[7px] font-bold px-1.5 py-0.5 rounded-full border text-orange-400 border-orange-500/30 bg-orange-500/10 shrink-0">DEGEN</span>
        )}
        {isShort ? (
          <span className="text-[8px] font-bold px-1.5 py-0.5 rounded-full border text-red-300 border-red-500/40 bg-red-500/15 shrink-0">SHORT</span>
        ) : (
          <span className="text-[8px] font-bold px-1.5 py-0.5 rounded-full border text-green-400 border-green-500/30 bg-green-500/10 shrink-0">LONG</span>
        )}
        <MarketStatusBadge symbol={pos.symbol} isCrypto={isAssetCrypto(pos.symbol)} />
        <span className={cn("font-mono font-semibold text-[10px] flex-1 tabular-nums", isUp ? "text-green-400" : "text-red-400")}>
          {isUp ? "+" : ""}{formatCurrency(pos.unrealized_pl)}
          <span className="text-[8px] opacity-60 ml-1">({pnlPct == null ? "—" : `${isUp ? "+" : ""}${pnlPct.toFixed(2)}%`})</span>
        </span>
        {pos.conviction_score != null && (
          <span className={cn("text-[9px] font-mono shrink-0 hidden sm:inline", pos.conviction_score >= 0.8 ? "text-green-400/60" : pos.conviction_score >= 0.75 ? "text-primary/60" : "text-amber-400/60")}>
            {Math.round(pos.conviction_score * 100)}%
          </span>
        )}
        {pos.health_score && (() => {
          const c = HEALTH_COLOR_MAP[pos.health_score.color] || pos.health_score.color;
          return (
            <span className="text-[8px] px-1.5 py-0.5 rounded-full border shrink-0 hidden sm:inline" style={{ color: c, borderColor: c + "30", backgroundColor: c + "15" }}>
              {pos.health_score.label}
            </span>
          );
        })()}
        {pos.stop_loss_price != null && (
          <span className="text-[9px] font-mono text-red-400/55 shrink-0 hidden sm:inline">SL {formatCurrency(pos.stop_loss_price)}</span>
        )}
        <span className={cn("text-muted-foreground/30 text-[10px] transition-transform duration-200 shrink-0", expanded && "rotate-180")}>▾</span>
      </div>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18 }}
            className="overflow-hidden"
            onClick={e => e.stopPropagation()}
          >
            <div className="px-4 pb-3 pt-2 border-t border-white/[0.04]">
              <div className="grid grid-cols-3 sm:grid-cols-4 gap-x-5 gap-y-2.5">
                {([
                  ["Entry",   formatCurrency(pos.avg_entry_price)],
                  ["Current", formatCurrency(pos.current_price)],
                  ["Notional", formatCurrency(pos.market_value)],
                   ["Qty",     pos.qty == null ? "—" : pos.qty.toFixed(4)],
                  pos.stop_loss_price  != null ? ["Stop loss",     formatCurrency(pos.stop_loss_price)]  : null,
                  pos.take_profit_price != null ? ["Trail trigger", formatCurrency(pos.take_profit_price)] : null,
                  pos.conviction_score != null ? ["Conviction", `${Math.round(pos.conviction_score * 100)}%`] : null,
                  pos.health_score ? ["Health", `${pos.health_score.score} · ${pos.health_score.label}`] : null,
                ] as ([string, string] | null)[])
                  .filter((x): x is [string, string] => x !== null)
                  .map(([label, value]) => (
                    <div key={label}>
                      <div className="text-[8px] text-muted-foreground/40 uppercase tracking-wide">{label}</div>
                      <div className="text-[10px] font-mono text-white/80 font-semibold mt-0.5">{value}</div>
                    </div>
                  ))}
              </div>
              {pos.original_thesis && (
                <div className="mt-3 cursor-pointer" onClick={() => onThesisClick(pos.symbol, pos.original_thesis)}>
                  <div className="text-[8px] text-muted-foreground/40 uppercase tracking-wide mb-0.5">Thesis</div>
                  <p className="text-[10px] text-indigo-300/70 line-clamp-2 border-b border-dashed border-indigo-500/20 hover:text-indigo-300 transition-colors leading-snug">
                    {pos.original_thesis}
                  </p>
                </div>
              )}
              <div className="mt-3 flex justify-end">
                {closingSymbol === pos.symbol ? (
                  <div className="flex items-center gap-1 text-[10px] text-orange-400/70">
                    <RefreshCw className="h-3 w-3 animate-spin" />
                    <span>Closing…</span>
                  </div>
                ) : confirmClose === pos.symbol ? (
                  <div className="flex items-center gap-2">
                    <span className="text-[9px] text-orange-300/80">Close &amp; re-enter?</span>
                    <button onClick={() => onEject(pos.symbol)} className="text-[9px] font-bold px-2 py-0.5 rounded bg-orange-500/20 text-orange-400 border border-orange-500/30 hover:bg-orange-500/35 transition-colors">Yes</button>
                    <button onClick={() => setConfirmClose(null)} className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-slate-800 text-muted-foreground border border-white/10 hover:bg-slate-700 transition-colors">No</button>
                  </div>
                ) : (
                  <button
                    onClick={() => setConfirmClose(pos.symbol)}
                    disabled={isClosing || isRebalancing}
                    className={cn(
                      "flex items-center gap-1 text-[9px] font-semibold uppercase tracking-wide px-2.5 py-1.5 rounded-lg border transition-all duration-200",
                      isClosing || isRebalancing
                        ? "opacity-40 cursor-not-allowed border-white/10 text-muted-foreground"
                        : "border-orange-500/20 bg-orange-500/5 text-orange-400/60 hover:bg-orange-500/15 hover:text-orange-400 hover:border-orange-500/40"
                    )}
                  >
                    <LogOut className="h-2.5 w-2.5" />
                    <span>Eject</span>
                  </button>
                )}
              </div>
              <div className="mt-1 text-[9px] text-green-400/30 italic">AI conviction · managed by {formatBotLabel(oracleIdentity)}</div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function AlpacaPositionsPanel({
  positions, onThesisClick, onEject, confirmClose, setConfirmClose,
  isClosing, isRebalancing, closingSymbol,
}: {
  positions: LivePosition[];
  onThesisClick: (ticker: string, thesis: string | null) => void;
  onEject: (symbol: string) => void;
  confirmClose: string | null;
  setConfirmClose: (s: string | null) => void;
  isClosing: boolean;
  isRebalancing: boolean;
  closingSymbol: string | null;
}) {
  const [open, setOpen] = useState(true);
  const { getBotIdentity } = useBotIdentity();
  const oracleIdentity = getBotIdentity("oracle");
  const { data: statusData } = useStatusSummary();

  const tradingMode = statusData?.trading_mode;
  const isAfterhoursMode = tradingMode === "afterhours_crypto";
  const isEquityMode = tradingMode === "full_market";
  const ahData = statusData?.afterhours_crypto;
  const ahPositionCount = ahData?.position_count ?? null;
  const ahUnrealizedPnl = ahData?.unrealized_pnl ?? null;

  // Return null only when there are no positions AND no afterhours mode badge to show
  if (positions.length === 0 && !isAfterhoursMode) return null;

  const longPositions  = positions.filter(p => (p.side ?? "long").toLowerCase() !== "short");
  const shortPositions = positions.filter(p => (p.side ?? "long").toLowerCase() === "short");
  const totalPnl  = positions.reduce((sum, p) => sum + p.unrealized_pl, 0);
  const shortPnl  = shortPositions.reduce((sum, p) => sum + p.unrealized_pl, 0);
  const shortExposure = shortPositions.reduce((sum, p) => sum + Math.abs(p.market_value), 0);
  const isPnlUp  = totalPnl >= 0;

  return (
    <div className="bg-orange-950/[0.02]">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full px-4 py-2 flex items-center gap-2 text-left hover:bg-orange-500/[0.04] transition-colors"
      >
        <span className="text-[9px] uppercase font-semibold tracking-wider text-orange-400/60">⚡ {formatBotLabel(oracleIdentity)}</span>
        <Badge variant="outline" className="text-[8px] px-1 py-0 border-orange-500/20 text-orange-400/50">{positions.length}</Badge>
        <span className="text-[9px] text-muted-foreground/30 ml-1">equity positions</span>
        {shortPositions.length > 0 && (
          <Badge variant="outline" className="text-[8px] px-1 py-0 border-red-500/30 text-red-400/70 ml-1">{shortPositions.length} short</Badge>
        )}
        {isEquityMode && (
          <span
            title={`NYSE is open — ${formatBotLabel(oracleIdentity)} is running in equity mode`}
            className="flex items-center gap-1 text-[8px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded border border-green-500/25 bg-green-500/8 text-green-400/70"
          >
            📈 Equity Mode
          </span>
        )}
        {isAfterhoursMode && (
          <span
            title={`NYSE is closed — ${formatBotLabel(oracleIdentity)} is in Crypto After-Hours mode${ahPositionCount != null && ahPositionCount > 0 ? ` · ${ahPositionCount} crypto position${ahPositionCount !== 1 ? "s" : ""}${ahUnrealizedPnl == null ? " · P&L unavailable" : ` · P&L: ${ahUnrealizedPnl >= 0 ? "+" : ""}$${Math.abs(ahUnrealizedPnl).toFixed(2)}`}` : ""}`}
            className="flex items-center gap-1 text-[8px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded border border-indigo-500/30 bg-indigo-500/10 text-indigo-400"
          >
            🌙 Crypto After-Hours
            {ahPositionCount != null && ahPositionCount > 0 && (
              <span className="text-indigo-300/70 font-mono">{ahPositionCount}</span>
            )}
            {ahPositionCount != null && ahPositionCount > 0 && ahUnrealizedPnl != null && (
              <span className={cn("font-mono", ahUnrealizedPnl >= 0 ? "text-green-400/70" : "text-red-400/70")}>
                {ahUnrealizedPnl >= 0 ? "+" : ""}{formatCurrency(ahUnrealizedPnl)}
              </span>
            )}
          </span>
        )}
        <span className={cn("ml-auto text-[11px] font-mono font-semibold tabular-nums", isPnlUp ? "text-green-400" : "text-red-400")}>
          {isPnlUp ? "+" : ""}{formatCurrency(totalPnl)}
        </span>
        <span className={cn("text-muted-foreground/30 text-[10px] transition-transform duration-200 ml-2", open && "rotate-180")}>▾</span>
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            {shortPositions.length > 0 && (
              <div className="mx-3 mb-2 px-3 py-2 rounded-lg border border-purple-500/20 bg-purple-950/[0.12]">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-[8px] font-bold uppercase tracking-wider text-purple-400/70">Bear Scanner</span>
                    <span className="text-[8px] text-muted-foreground/40">{shortPositions.length} algo short{shortPositions.length > 1 ? "s" : ""}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-[9px] font-mono text-muted-foreground/50">Exposure: {formatCurrency(shortExposure)}</span>
                    <span className={cn("text-[9px] font-mono font-semibold tabular-nums", shortPnl >= 0 ? "text-green-400" : "text-red-400")}>
                      {shortPnl >= 0 ? "+" : ""}{formatCurrency(shortPnl)}
                    </span>
                  </div>
                </div>
              </div>
            )}
            <div className="px-3 pb-3 space-y-1.5">
              {longPositions.map((pos) => (
                <AlpacaPositionCard key={`${pos.bot_id ?? "unknown"}-${pos.symbol}`} pos={pos} onThesisClick={onThesisClick} onEject={onEject} confirmClose={confirmClose} setConfirmClose={setConfirmClose} isClosing={isClosing} isRebalancing={isRebalancing} closingSymbol={closingSymbol} />
              ))}
              {shortPositions.map((pos) => (
                <AlpacaPositionCard key={`${pos.bot_id ?? "unknown"}-${pos.symbol}`} pos={pos} onThesisClick={onThesisClick} onEject={onEject} confirmClose={confirmClose} setConfirmClose={setConfirmClose} isClosing={isClosing} isRebalancing={isRebalancing} closingSymbol={closingSymbol} />
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function ThesisModal({ ticker, thesis, onClose }: {
  ticker: string;
  thesis: string | null;
  onClose: () => void;
}) {
  return (
    <AnimatePresence>
      <motion.div
        key="thesis-backdrop"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm px-4"
        onClick={onClose}
      >
        <motion.div
          key="thesis-panel"
          initial={{ opacity: 0, scale: 0.95, y: 12 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 8 }}
          transition={{ duration: 0.2, ease: "easeOut" }}
          className="relative max-w-lg w-full rounded-2xl border border-indigo-500/30 bg-slate-900 shadow-2xl overflow-hidden"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="h-px bg-gradient-to-r from-indigo-500/60 via-violet-400/40 to-transparent" />
          <div className="p-5">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Sparkles className="h-3.5 w-3.5 text-violet-400" />
                <span className="text-[10px] uppercase font-semibold tracking-wider text-violet-400">AI Thesis</span>
                <span className="font-mono text-xs font-bold text-white ml-1">{ticker}</span>
              </div>
              <button onClick={onClose} className="p-1 rounded-md hover:bg-white/8 transition-colors text-muted-foreground hover:text-white">
                <X className="h-4 w-4" />
              </button>
            </div>
            {thesis ? (
              <p className="text-sm leading-relaxed text-slate-200 font-light">{thesis}</p>
            ) : (
              <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
                <p className="text-sm text-amber-300/80 leading-relaxed">
                  <span className="font-semibold">Legacy position</span> — this position was opened before the v4.0 regime-switching architecture was deployed. No AI thesis was recorded at entry time.
                </p>
                <p className="text-xs text-muted-foreground/60 mt-2">Future positions opened by the regime engine will always include a full thesis.</p>
              </div>
            )}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
