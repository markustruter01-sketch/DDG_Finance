import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import type {
  FleetEquityData,
  VaultState,
  TradeJournal,
  MathAuditSummary,
} from "@/hooks/use-trading";
import { api as hdrApi } from "@/hooks/use-trading-client";

const INTERVAL = 3_000;

// Exactly the 3 live bots — buck_futures retired May 30, excluded permanently.
const BOT_COLORS: Record<string, string> = {
  oracle:        "#8b5cf6",
  spy_qqq_trend: "#fbbf24",
  jerome_macro:  "#f87171",
};
// Drive bot-dot list from fleet equity keys at render time (dynamic, not hardcoded count)

function fmt$(v: number | null): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : "-"}$${Math.round(Math.abs(v)).toLocaleString()}`;
}
function fmtPct(v: number | null): string {
  if (v == null) return "";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

export function StreamHeaderBar() {
  const [clock, setClock] = useState(() =>
    new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })
  );
  useEffect(() => {
    const t = setInterval(() =>
      setClock(new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })),
      1_000
    );
    return () => clearInterval(t);
  }, []);

  const { data: fleet } = useQuery<FleetEquityData>({
    queryKey: ["fleet-equity"],
    queryFn: async () => (await hdrApi.get("/fleet/equity")).data,
    refetchInterval: INTERVAL,
    staleTime: 2_000,
    retry: 1,
  });

  const { data: vault } = useQuery<VaultState>({
    queryKey: ["/vault"],
    queryFn: async () => (await hdrApi.get("/vault")).data,
    refetchInterval: INTERVAL,
    staleTime: 2_000,
  });

  const { data: journal } = useQuery<TradeJournal>({
    queryKey: ["/journal"],
    queryFn: async () => (await hdrApi.get("/journal")).data,
    refetchInterval: INTERVAL,
    staleTime: 2_000,
  });

  const { data: audit } = useQuery<MathAuditSummary>({
    queryKey: ["/admin/math-audit/summary", 24],
    queryFn: async () => (await hdrApi.get("/admin/math-audit/summary?hours=24")).data,
    refetchInterval: INTERVAL,
    staleTime: 2_000,
    retry: false,
  });

  const fleetPnl      = fleet?.fleet_total?.pnl     ?? null;
  const fleetPnlPct   = fleet?.fleet_total?.pnl_pct ?? null;
  const fleetEquity   = fleet?.fleet_total?.equity   ?? null;
  const vaultAmt    = vault?.total_vaulted_usd     ?? null;
  const wins        = journal?.summary?.wins       ?? null;
  const losses      = journal?.summary?.losses     ?? null;
  // Win rate sourced from canonical /fleet/equity (30-day, active bots only)
  const _fleetWr    = fleet?.fleet_total?.win_rate;
  const winRate     = _fleetWr != null ? _fleetWr * 100 : null;

  // Best/worst sourced from server all-time journal summary — no 50-trade window reduce()
  type SummaryExt = { best_trade_usd?: number|null; best_trade_symbol?: string|null; worst_trade_usd?: number|null; worst_trade_symbol?: string|null; };
  const summary = journal?.summary as (NonNullable<typeof journal>["summary"] & SummaryExt) | undefined;
  const bestTradeUsd    = summary?.best_trade_usd    ?? null;
  const bestTradeSymbol = summary?.best_trade_symbol ?? null;
  const worstTradeUsd   = summary?.worst_trade_usd   ?? null;
  const worstTradeSymbol= summary?.worst_trade_symbol ?? null;

  const auditCounts = audit == null ? null : [audit.pass, audit.warn, audit.fail];
  const auditChecked = auditCounts?.every((count) => count != null)
    ? auditCounts.reduce((sum, count) => sum + count, 0)
    : null;
  const auditPassRate = auditChecked != null && auditChecked > 0 && audit?.pass != null
    ? ((audit.pass / auditChecked) * 100).toFixed(1) : null;
  const auditTotal = auditChecked;

  // Drive bot dots from the 3-bot color map — dynamic, no hardcoded count
  const botStatuses = Object.entries(BOT_COLORS).map(([k, color]) => {
    const b = fleet ? (fleet as unknown as Record<string, unknown>)[k] as { equity?: number; stale?: boolean } | undefined : undefined;
    const known = b != null && typeof b.equity === "number" && !b.stale;
    const active = known && (b?.equity ?? 0) > 0;
    return { key: k, color, known, active };
  });
  const activeCount = botStatuses.every(b => b.known)
    ? botStatuses.filter(b => b.active).length
    : null;

  const CELL = "flex flex-col items-start justify-center px-4 shrink-0 whitespace-nowrap";
  const LABEL_STYLE: React.CSSProperties = { color: "rgba(30,41,59,0.82)", fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.12em", marginBottom: 2 };
  const DIV_STYLE: React.CSSProperties = { borderRight: "1px solid rgba(255,255,255,0.05)" };

  return (
    <div
      className="stream-production-header w-full shrink-0 flex items-stretch font-mono"
      style={{
        height: 52,
        background: "rgba(255,255,255,0.12)",
        borderBottom: "1px solid rgba(34,211,238,0.12)",
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
        zIndex: 30,
      }}
    >
      {/* ── STREAM VIEW ── */}
      <div className="flex items-center gap-2.5 px-4 shrink-0" style={{ borderRight: "1px solid rgba(255,255,255,0.06)" }}>
        <div className="relative w-2 h-2 flex items-center justify-center">
          <span className="absolute inline-flex rounded-full" style={{ width: 8, height: 8, background: "#0e7490", boxShadow: "0 0 6px rgba(14,116,144,0.35)" }} />
        </div>
        <span className="text-[10px] font-black tracking-[0.16em] uppercase" style={{ color: "#0e7490" }}>STREAM</span>
      </div>

      {/* ── TOTAL P&L ── */}
      <div className={CELL} style={{ ...DIV_STYLE, width: 148 }}>
        <span style={LABEL_STYLE}>TOTAL P&amp;L</span>
        <div className="flex items-baseline gap-1.5 whitespace-nowrap">
          <span className="text-[14px] font-bold leading-none" style={{ color: fleetPnl != null && fleetPnl >= 0 ? "#4ade80" : "#f87171" }}>
            {fmt$(fleetPnl)}
          </span>
          <span className="text-[10px] font-medium" style={{ color: fleetPnlPct != null && fleetPnlPct >= 0 ? "rgba(74,222,128,0.7)" : "rgba(248,113,113,0.7)" }}>
            {fmtPct(fleetPnlPct)}
          </span>
        </div>
      </div>

      {/* ── VAULT ── */}
      <div className={CELL} style={{ ...DIV_STYLE, width: 128 }}>
        <span style={LABEL_STYLE}>VAULT</span>
        <div className="flex items-baseline gap-1.5 whitespace-nowrap">
          <span className="text-[14px] font-bold leading-none" style={{ color: "#a78bfa" }}>
            {vaultAmt != null ? `$${Math.round(vaultAmt).toLocaleString()}` : "—"}
          </span>
          <span className="text-[10px] font-medium" style={{ color: "rgba(100,116,139,0.6)" }}>secured</span>
        </div>
      </div>

      {/* ── BEST TRADE (all-time) ── */}
      <div className={CELL} style={{ ...DIV_STYLE, width: 138 }}>
        <span style={LABEL_STYLE}>BEST TRADE</span>
        <div className="flex items-baseline gap-1.5 whitespace-nowrap">
          <span className="text-[14px] font-bold leading-none" style={{ color: "#4ade80" }}>
            {bestTradeUsd != null ? `+$${Math.round(Math.abs(bestTradeUsd)).toLocaleString()}` : "—"}
          </span>
          <span className="text-[10px] font-medium" style={{ color: "rgba(74,222,128,0.7)" }}>
            {bestTradeSymbol ?? ""}
          </span>
          <span className="text-[9px] font-medium" style={{ color: "rgba(100,116,139,0.5)" }}>
            all-time
          </span>
        </div>
      </div>

      {/* ── WORST TRADE (all-time) ── */}
      <div className={CELL} style={{ ...DIV_STYLE, width: 138 }}>
        <span style={LABEL_STYLE}>WORST TRADE</span>
        <div className="flex items-baseline gap-1.5 whitespace-nowrap">
          <span className="text-[14px] font-bold leading-none" style={{ color: "#f87171" }}>
            {worstTradeUsd != null ? `-$${Math.round(Math.abs(worstTradeUsd)).toLocaleString()}` : "—"}
          </span>
          <span className="text-[10px] font-medium" style={{ color: "rgba(248,113,113,0.7)" }}>
            {worstTradeSymbol ?? ""}
          </span>
          <span className="text-[9px] font-medium" style={{ color: "rgba(100,116,139,0.5)" }}>
            all-time
          </span>
        </div>
      </div>

      {/* ── WIN RATE ── */}
      <div className={CELL} style={{ ...DIV_STYLE, width: 118 }}>
        <span style={LABEL_STYLE}>WIN RATE</span>
        <div className="flex items-baseline gap-1.5 whitespace-nowrap">
          <span className="text-[14px] font-bold leading-none" style={{ color: "#22d3ee" }}>
            {winRate != null ? `${winRate.toFixed(1)}%` : "—"}
          </span>
          <span className="text-[10px] font-medium" style={{ color: "rgba(100,116,139,0.6)" }}>30d</span>
        </div>
      </div>

      {/* ── TRADES ── */}
      <div className={CELL} style={{ ...DIV_STYLE, width: 108 }}>
        <span style={LABEL_STYLE}>TRADES</span>
        <div className="flex items-baseline gap-1 whitespace-nowrap">
          <span className="text-[14px] font-bold leading-none" style={{ color: "#4ade80" }}>
            {wins != null ? `${wins}W` : "—"}
          </span>
          <span className="text-[11px] font-bold leading-none" style={{ color: "rgba(100,116,139,0.4)" }}>/</span>
          <span className="text-[14px] font-bold leading-none" style={{ color: "#f87171" }}>
            {losses != null ? `${losses}L` : "—"}
          </span>
        </div>
      </div>

      {/* ── MATH AUDIT ── */}
      <div className={CELL} style={{ ...DIV_STYLE, width: 168 }}>
        <span style={LABEL_STYLE}>MATH AUDIT</span>
        <div className="flex items-baseline gap-1.5 whitespace-nowrap">
          <span className="text-[14px] font-bold leading-none" style={{ color: "#22d3ee" }}>
            {auditPassRate != null ? `${auditPassRate}%` : "—"}
          </span>
          <span className="text-[10px] font-medium" style={{ color: "rgba(100,116,139,0.6)" }}>
            {auditTotal != null ? `${auditTotal.toLocaleString()} checks` : ""}
          </span>
        </div>
      </div>

      {/* ── PLATFORM EQUITY ── */}
      <div className={CELL} style={{ ...DIV_STYLE, width: 168, marginLeft: "auto" }}>
        <span style={LABEL_STYLE}>PLATFORM EQUITY</span>
        <div className="flex items-baseline gap-1.5 whitespace-nowrap">
          <span className="text-[14px] font-bold leading-none" style={{ color: "#fbbf24" }}>
            {fleetEquity != null ? `$${Math.round(fleetEquity).toLocaleString()}` : "—"}
          </span>
          <span className="text-[10px] font-medium" style={{ color: fleetPnlPct != null && fleetPnlPct < 0 ? "rgba(248,113,113,0.8)" : "rgba(74,222,128,0.8)" }}>
            {fleetPnlPct != null ? fmtPct(fleetPnlPct) : ""}
          </span>
        </div>
      </div>

      {/* ── ACTIVE BOTS ── */}
      <div className="flex items-center gap-3 px-4 shrink-0" style={{ borderLeft: "1px solid rgba(255,255,255,0.05)" }}>
        <div className="flex flex-col items-start">
          <span style={{ ...LABEL_STYLE, marginBottom: 4 }}>ACTIVE BOTS</span>
          <div className="flex items-center gap-1.5 whitespace-nowrap">
            {botStatuses.map(b => (
              <div
                key={b.key}
                title={b.key.replace("_", " ")}
                className="rounded-full"
                style={{
                  width: 8, height: 8,
                  background: !b.known
                    ? "rgba(245,158,11,0.7)"
                    : b.active ? b.color : "rgba(100,116,139,0.55)",
                  boxShadow: b.known && b.active ? `0 0 5px ${b.color}` : "none",
                  transition: "all 0.6s",
                  flexShrink: 0,
                }}
              />
            ))}
            <span className="text-[11px] font-bold ml-1" style={{ color: "#22d3ee" }}>
              {activeCount == null ? `—/${botStatuses.length}` : `${activeCount}/${botStatuses.length}`}
            </span>
          </div>
        </div>

        {/* UTC Clock */}
        <div className="flex flex-col items-end" style={{ borderLeft: "1px solid rgba(255,255,255,0.05)", paddingLeft: 12 }}>
          <span style={{ ...LABEL_STYLE, marginBottom: 2 }}>UTC</span>
          <span className="text-[12px] font-bold tabular-nums" style={{ color: "rgba(148,163,184,0.6)" }}>
            {clock}
          </span>
        </div>
      </div>
    </div>
  );
}
