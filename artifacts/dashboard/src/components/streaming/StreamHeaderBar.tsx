import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import axios from "axios";
import type {
  FleetEquityData,
  VaultState,
  TradeJournal,
  MathAuditSummary,
  RecentTrades,
} from "@/hooks/use-trading";

const BASE = import.meta.env.VITE_API_BASE_URL || "/trading-api";
const hdrApi = axios.create({ baseURL: BASE });

const INTERVAL = 3_000;

const BOT_COLORS: Record<string, string> = {
  oracle:          "#8b5cf6",
  spy_qqq_trend:   "#fbbf24",
  jerome_macro:    "#f87171",
  buck_futures:    "#22d3ee",
};
const BOT_KEYS = Object.keys(BOT_COLORS);

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

  const { data: recent } = useQuery<RecentTrades>({
    queryKey: ["/journal/recent", 50],
    queryFn: async () => (await hdrApi.get("/journal/recent?n=50")).data,
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

  const trades = (recent?.trades ?? []).filter(t => t.pnl_usd != null);
  const bestTrade  = trades.length > 0 ? trades.reduce((a, b) => (b.pnl_usd ?? -Infinity) > (a.pnl_usd ?? -Infinity) ? b : a) : null;
  const worstTrade = trades.length > 0 ? trades.reduce((a, b) => (b.pnl_usd ?? Infinity) < (a.pnl_usd ?? Infinity) ? b : a) : null;

  const auditChecked = audit != null ? (audit.pass ?? 0) + (audit.warn ?? 0) + (audit.fail ?? 0) : null;
  const auditPassRate = auditChecked != null && auditChecked > 0
    ? (((audit!.pass ?? 0) / auditChecked) * 100).toFixed(1) : null;
  const auditTotal = auditChecked;

  const botStatuses = BOT_KEYS.map(k => {
    const b = fleet ? (fleet as unknown as Record<string, unknown>)[k] as { equity?: number; stale?: boolean } | undefined : undefined;
    const active = b != null && typeof b.equity === "number" && b.equity > 0 && !b.stale;
    return { key: k, color: BOT_COLORS[k], active };
  });
  const activeCount = botStatuses.filter(b => b.active).length;

  const CELL = "flex flex-col items-start justify-center px-4 shrink-0 whitespace-nowrap";
  const LABEL_STYLE: React.CSSProperties = { color: "rgba(100,116,139,0.8)", fontSize: 8, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.18em", marginBottom: 2 };
  const DIV_STYLE: React.CSSProperties = { borderRight: "1px solid rgba(255,255,255,0.05)" };

  return (
    <div
      className="w-full shrink-0 flex items-stretch font-mono"
      style={{
        height: 52,
        background: "#000000",
        borderBottom: "1px solid rgba(34,211,238,0.12)",
        zIndex: 30,
      }}
    >
      <style dangerouslySetInnerHTML={{ __html: `
        @keyframes shb-ping {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.4; transform: scale(1.5); }
        }
        .shb-live-dot { animation: shb-ping 1.4s ease-in-out infinite; }
      ` }} />

      {/* ── LIVE ── */}
      <div className="flex items-center gap-2.5 px-4 shrink-0" style={{ borderRight: "1px solid rgba(255,255,255,0.06)" }}>
        <div className="relative w-2 h-2 flex items-center justify-center">
          <span className="shb-live-dot absolute inline-flex rounded-full" style={{ width: 8, height: 8, background: "#22c55e", boxShadow: "0 0 6px #22c55e" }} />
        </div>
        <span className="text-[10px] font-black tracking-[0.2em] uppercase" style={{ color: "#22c55e" }}>LIVE</span>
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

      {/* ── BEST TRADE ── */}
      <div className={CELL} style={{ ...DIV_STYLE, width: 138 }}>
        <span style={LABEL_STYLE}>BEST TRADE</span>
        <div className="flex items-baseline gap-1.5 whitespace-nowrap">
          <span className="text-[14px] font-bold leading-none" style={{ color: "#4ade80" }}>
            {bestTrade?.pnl_usd != null ? `+$${Math.round(bestTrade.pnl_usd).toLocaleString()}` : "—"}
          </span>
          <span className="text-[10px] font-medium" style={{ color: "rgba(74,222,128,0.7)" }}>
            {bestTrade?.symbol ?? ""}
          </span>
        </div>
      </div>

      {/* ── WORST TRADE ── */}
      <div className={CELL} style={{ ...DIV_STYLE, width: 138 }}>
        <span style={LABEL_STYLE}>WORST TRADE</span>
        <div className="flex items-baseline gap-1.5 whitespace-nowrap">
          <span className="text-[14px] font-bold leading-none" style={{ color: "#f87171" }}>
            {worstTrade?.pnl_usd != null ? `${worstTrade.pnl_usd >= 0 ? "+" : "-"}$${Math.round(Math.abs(worstTrade.pnl_usd)).toLocaleString()}` : "—"}
          </span>
          <span className="text-[10px] font-medium" style={{ color: "rgba(248,113,113,0.7)" }}>
            {worstTrade?.symbol ?? ""}
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
                  background: b.active ? b.color : "rgba(100,116,139,0.2)",
                  boxShadow: b.active ? `0 0 5px ${b.color}` : "none",
                  transition: "all 0.6s",
                  flexShrink: 0,
                }}
              />
            ))}
            <span className="text-[11px] font-bold ml-1" style={{ color: "#22d3ee" }}>
              {activeCount}/{BOT_KEYS.length}
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
