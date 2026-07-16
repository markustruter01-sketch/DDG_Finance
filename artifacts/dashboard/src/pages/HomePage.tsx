import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "wouter";
import axios from "axios";
import { isNYSEOpen } from "@/lib/dashboard-shared";

const BASE = import.meta.env.VITE_API_BASE_URL || "/trading-api";
const api = axios.create({ baseURL: BASE });

// ── Types ────────────────────────────────────────────────────────────────────

interface BotSlice {
  equity: number;
  starting: number;
  pnl: number;
  pnl_pct: number;
  positions: number;
  stale: boolean;
  paused: boolean;
  win_rate: number | null;
  last_updated: string | null;
}

type FleetEquityResp = {
  oracle?: BotSlice;
  spy_qqq_trend?: BotSlice;
  jerome_macro?: BotSlice;
  buck_futures?: BotSlice;
  fleet_total?: {
    equity: number;
    pnl: number;
    pnl_pct: number;
    positions: number;
    win_rate: number | null;
  };
  generated_at?: string;
};

interface MarketStateResp {
  regime?: string;
}

interface StatusSummaryResp {
  kill_switch?: { tripped: boolean };
  kill_switch_tripped?: boolean;
}

interface LivePos {
  symbol: string;
  qty: number;
  side: string;
  avg_entry_price: number;
  unrealized_pl: number;
  unrealized_plpc: number;
}

interface ClaudeReportResp {
  walk_forward_status?: Array<{
    bot_id: string;
    wf_status: string | null;
    snapshot_at: string | null;
  }>;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

type BotStatus = "LIVE" | "IDLE" | "DOWN";

function getStatus(bot: BotSlice | undefined, mktOpen: boolean): BotStatus {
  if (!bot) return "DOWN";
  if (bot.paused) return "IDLE";
  if (bot.stale) return mktOpen ? "DOWN" : "IDLE";
  return "LIVE";
}

function mergeStatus(a: BotStatus, b: BotStatus): BotStatus {
  if (a === "LIVE" || b === "LIVE") return "LIVE";
  if (a === "DOWN" || b === "DOWN") return "DOWN";
  return "IDLE";
}

const STATUS_COLORS: Record<BotStatus, string> = {
  LIVE: "#22c55e",
  IDLE: "#eab308",
  DOWN: "#ef4444",
};

const STATUS_LABELS: Record<BotStatus, string> = {
  LIVE: "LIVE",
  IDLE: "IDLE-BY-DESIGN",
  DOWN: "DOWN",
};

function fmt$(v: number): string {
  const abs = Math.abs(v);
  const s = v >= 0 ? "+" : "-";
  if (abs >= 1_000_000) return `${s}$${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${s}$${(abs / 1_000).toFixed(1)}k`;
  return `${s}$${abs.toFixed(0)}`;
}

function fmtEq(v: number): string {
  return `$${Math.round(v).toLocaleString()}`;
}

function fmtPct(v: number): string {
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}

const WF_MAP: Record<string, { label: string; color: string }> = {
  PASS:              { label: "PASS",   color: "#22c55e" },
  MARGINAL:          { label: "AMBER",  color: "#f59e0b" },
  FAIL:              { label: "FAIL",   color: "#ef4444" },
  INSUFFICIENT_DATA: { label: "INSUFF", color: "#64748b" },
};

function WFBadge({ status }: { status: string | null | undefined }) {
  const b = WF_MAP[status ?? ""] ?? { label: "N/A", color: "#475569" };
  return (
    <span
      className="text-[8px] font-black tracking-widest uppercase px-1.5 py-0.5 rounded border"
      style={{ color: b.color, borderColor: `${b.color}45`, background: `${b.color}12` }}
    >
      WF {b.label}
    </span>
  );
}

// ── Position display ──────────────────────────────────────────────────────────

function PositionChips({ positions }: { positions: LivePos[] }) {
  if (positions.length === 0) {
    return <span className="text-[10px] text-slate-600 italic">No open positions</span>;
  }
  return (
    <div className="flex flex-wrap gap-x-2.5 gap-y-0.5">
      {positions.map((p) => {
        const pct = p.unrealized_plpc * 100;
        const color = pct >= 0 ? "#4ade80" : "#f87171";
        return (
          <span key={p.symbol} className="text-[11px] font-mono font-semibold" style={{ color }}>
            {p.symbol} {pct >= 0 ? "+" : ""}{pct.toFixed(1)}%
          </span>
        );
      })}
    </div>
  );
}

function PositionTable({ positions }: { positions: LivePos[] }) {
  if (positions.length === 0) return null;
  return (
    <div className="mt-3 space-y-1.5">
      {positions.map((p) => {
        const pct = p.unrealized_plpc * 100;
        const color = pct >= 0 ? "#4ade80" : "#f87171";
        return (
          <div
            key={p.symbol}
            className="flex items-center gap-2 text-[10px] font-mono px-2.5 py-2 rounded-lg"
            style={{ background: "rgba(15,23,42,0.85)", border: "1px solid rgba(255,255,255,0.06)" }}
          >
            <span className="font-bold text-white shrink-0 w-14">{p.symbol}</span>
            <span className="text-slate-500 shrink-0 w-9">{p.side === "short" ? "SHORT" : "LONG"}</span>
            <span className="text-slate-500 shrink-0">×{Math.abs(p.qty).toFixed(2)}</span>
            <span className="text-slate-500 shrink-0">@${p.avg_entry_price.toFixed(2)}</span>
            <span className="ml-auto font-bold tabular-nums" style={{ color }}>
              {pct >= 0 ? "+" : ""}{pct.toFixed(2)}%
            </span>
            <span className="text-slate-600 text-[9px] tabular-nums">{fmt$(p.unrealized_pl)}</span>
          </div>
        );
      })}
    </div>
  );
}

// ── Bot Card ──────────────────────────────────────────────────────────────────

interface BotCardProps {
  name: string;
  bot?: BotSlice;
  bot2?: BotSlice;
  wfStatus?: string | null;
  positions: LivePos[];
  posCountFallback?: number;
  accent: string;
  mktOpen: boolean;
}

function BotCard({ name, bot, bot2, wfStatus, positions, posCountFallback, accent, mktOpen }: BotCardProps) {
  const [expanded, setExpanded] = useState(false);

  const s1 = getStatus(bot, mktOpen);
  const s2 = bot2 ? getStatus(bot2, mktOpen) : s1;
  const status = bot2 ? mergeStatus(s1, s2) : s1;
  const sColor = STATUS_COLORS[status];

  const equity   = (bot?.equity   ?? 0) + (bot2?.equity   ?? 0);
  const starting = (bot?.starting ?? 100_000) + (bot2?.starting ?? 100_000);
  const pnl      = equity - starting;
  const pnlPct   = starting > 0 ? (pnl / starting) * 100 : 0;
  const pnlColor = pnl >= 0 ? "#4ade80" : "#f87171";
  const posCount = posCountFallback ?? positions.length;

  return (
    <div
      className="rounded-2xl overflow-hidden border transition-all duration-200 cursor-pointer select-none"
      style={{
        background: "rgba(10,16,30,0.97)",
        borderColor: expanded ? `${accent}50` : "rgba(255,255,255,0.07)",
        boxShadow: expanded ? `0 0 28px ${accent}14` : "none",
      }}
      onClick={() => setExpanded((v) => !v)}
    >
      {/* Accent bar */}
      <div style={{ height: 2, background: `linear-gradient(90deg, ${accent}cc, transparent)` }} />

      {/* Card body */}
      <div className="px-4 pt-3 pb-3">
        {/* Row 1: status dot + name + status label + WF badge + chevron */}
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          <span
            className="inline-block rounded-full shrink-0"
            style={{ width: 8, height: 8, background: sColor, boxShadow: `0 0 7px ${sColor}aa`, marginTop: 1 }}
          />
          <span className="text-[14px] font-bold text-white">{name}</span>
          <span
            className="text-[8px] font-black tracking-widest uppercase px-1.5 py-0.5 rounded"
            style={{ color: sColor, background: `${sColor}15` }}
          >
            {STATUS_LABELS[status]}
          </span>
          <WFBadge status={wfStatus} />
          <span
            className="ml-auto text-slate-600 text-[12px] transition-transform duration-200 shrink-0"
            style={{ transform: expanded ? "rotate(180deg)" : "rotate(0deg)" }}
          >
            ▾
          </span>
        </div>

        {/* Row 2: equity + PnL */}
        <div className="flex items-baseline gap-2 mb-3">
          <span className="text-[22px] font-bold tabular-nums text-white leading-none">{fmtEq(equity)}</span>
          <span className="text-[14px] font-semibold tabular-nums" style={{ color: pnlColor }}>
            {fmtPct(pnlPct)}
          </span>
          <span className="text-[11px] tabular-nums" style={{ color: `${pnlColor}99` }}>
            {fmt$(pnl)}
          </span>
        </div>

        {/* Row 3: position chips */}
        <PositionChips positions={positions} />
        {positions.length === 0 && posCount > 0 && (
          <span className="text-[10px] text-slate-500">
            {posCount} position{posCount !== 1 ? "s" : ""} tracked
          </span>
        )}
      </div>

      {/* Expanded section */}
      {expanded && (
        <div
          className="px-4 pb-4"
          style={{ borderTop: "1px solid rgba(255,255,255,0.05)" }}
          onClick={(e) => e.stopPropagation()}
        >
          <PositionTable positions={positions} />

          {positions.length === 0 && posCount > 0 && (
            <p className="text-[10px] text-slate-600 mt-3 italic">
              Positions tracked in shared Alpaca account — see Stream › Bots for per-position detail.
            </p>
          )}
          {positions.length === 0 && posCount === 0 && (
            <p className="text-[10px] text-slate-600 mt-3">No open positions</p>
          )}

          {/* Stats row */}
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[10px] font-mono text-slate-500">
            {bot?.win_rate != null && (
              <span>30d WR <span className="text-cyan-400">{(bot.win_rate * 100).toFixed(1)}%</span></span>
            )}
            {bot2?.win_rate != null && (
              <span>Buck WR <span className="text-cyan-400">{(bot2.win_rate * 100).toFixed(1)}%</span></span>
            )}
            {bot?.last_updated && (
              <span>
                upd{" "}
                <span className="text-slate-400">
                  {new Date(bot.last_updated).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                </span>
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Header sub-components ─────────────────────────────────────────────────────

function MarketChip({ regime }: { regime: string | undefined }) {
  if (!regime || regime === "UNKNOWN") return null;
  const cfgs: Record<string, { emoji: string; color: string; bg: string; border: string }> = {
    CRISIS: { emoji: "🚨", color: "#ef4444", bg: "rgba(239,68,68,0.14)",  border: "rgba(239,68,68,0.4)"  },
    BEAR:   { emoji: "🐻", color: "#f97316", bg: "rgba(249,115,22,0.14)", border: "rgba(249,115,22,0.4)" },
    BULL:   { emoji: "🟢", color: "#22c55e", bg: "rgba(34,197,94,0.12)",  border: "rgba(34,197,94,0.35)" },
  };
  const c = cfgs[regime] ?? cfgs["BULL"];
  return (
    <span
      className="text-[10px] font-black tracking-widest uppercase px-2.5 py-1 rounded-full border"
      style={{ color: c.color, background: c.bg, borderColor: c.border }}
    >
      {c.emoji} {regime}
    </span>
  );
}

function KillDot({ tripped }: { tripped: boolean | undefined }) {
  if (tripped == null) return null;
  return (
    <div className="flex items-center gap-1.5 shrink-0">
      <span
        className="inline-block rounded-full"
        style={{
          width: 7, height: 7,
          background: tripped ? "#ef4444" : "#22c55e",
          boxShadow: tripped ? "0 0 8px #ef4444" : "0 0 5px #22c55e55",
        }}
      />
      <span
        className="text-[9px] font-mono font-bold tracking-widest uppercase"
        style={{ color: tripped ? "#ef4444" : "#475569" }}
      >
        {tripped ? "KS TRIPPED" : "ARMED"}
      </span>
    </div>
  );
}

// ── HomePage ──────────────────────────────────────────────────────────────────

export default function HomePage() {
  const [, navigate] = useLocation();
  const mktOpen = isNYSEOpen();

  const { data: fleet } = useQuery<FleetEquityResp>({
    queryKey: ["home-fleet-equity"],
    queryFn: async () => (await api.get("/fleet/equity")).data,
    refetchInterval: 15_000,
    staleTime: 10_000,
    retry: 1,
  });

  const { data: market } = useQuery<MarketStateResp>({
    queryKey: ["home-market-state"],
    queryFn: async () => (await api.get("/market-state")).data,
    refetchInterval: 60_000,
    staleTime: 30_000,
    retry: 1,
  });

  const { data: summary } = useQuery<StatusSummaryResp>({
    queryKey: ["home-status-summary"],
    queryFn: async () => (await api.get("/status/summary")).data,
    refetchInterval: 10_000,
    staleTime: 8_000,
    retry: 1,
  });

  const { data: livePosResp } = useQuery<{ positions: LivePos[] }>({
    queryKey: ["home-positions-live"],
    queryFn: async () => (await api.get("/positions/live")).data,
    refetchInterval: 15_000,
    staleTime: 10_000,
    retry: 1,
  });

  const { data: reportData } = useQuery<ClaudeReportResp>({
    queryKey: ["home-claude-report"],
    queryFn: async () => (await api.get("/claude-report")).data,
    refetchInterval: 5 * 60_000,
    staleTime: 4 * 60_000,
    retry: false,
  });

  // ── Data extracts ──────────────────────────────────────────────────────────
  const oracle = fleet?.oracle;
  const spy    = fleet?.spy_qqq_trend;
  const jerome = fleet?.jerome_macro;
  const buck   = fleet?.buck_futures;
  const total  = fleet?.fleet_total;

  const allPos   = livePosResp?.positions ?? [];
  const spyPos   = allPos.filter((p) => ["SPY", "QQQ"].includes(p.symbol));
  const otherPos = allPos.filter((p) => !["SPY", "QQQ"].includes(p.symbol));

  const wfMap = new Map(
    (reportData?.walk_forward_status ?? []).map((r) => [r.bot_id, r.wf_status]),
  );

  const fleetPnl    = total?.pnl     ?? null;
  const fleetPnlPct = total?.pnl_pct ?? null;
  const fleetEq     = total?.equity  ?? null;
  const fleetWr     = total?.win_rate ?? null;
  const regime      = market?.regime;
  const lastCycle   = fleet?.generated_at;
  const killTripped = summary?.kill_switch?.tripped ?? summary?.kill_switch_tripped;
  const pnlColor    = (fleetPnl ?? 0) >= 0 ? "#4ade80" : "#f87171";
  const curlyCount  = (jerome?.positions ?? 0) + (buck?.positions ?? 0);

  return (
    <div className="min-h-screen bg-slate-950 font-mono text-white">

      {/* ═══ HEADER STRIP ═══════════════════════════════════════════════════ */}
      <div
        className="sticky top-0 z-20 flex items-center gap-3 px-4 py-3 flex-wrap"
        style={{ background: "#030712", borderBottom: "1px solid rgba(34,211,238,0.10)" }}
      >
        {/* Fleet equity + P&L */}
        <div className="flex items-baseline gap-2">
          <span className="text-[20px] font-bold text-white tabular-nums leading-none">
            {fleetEq != null ? fmtEq(fleetEq) : "—"}
          </span>
          {fleetPnl != null && (
            <span className="text-[13px] font-semibold tabular-nums" style={{ color: pnlColor }}>
              {fleetPnl >= 0 ? "+" : "-"}${Math.round(Math.abs(fleetPnl)).toLocaleString()}
              {fleetPnlPct != null && (
                <span className="text-[11px] ml-1 opacity-70">
                  ({fmtPct(fleetPnlPct)})
                </span>
              )}
            </span>
          )}
        </div>

        <MarketChip regime={regime} />
        <div className="ml-auto"><KillDot tripped={killTripped} /></div>
      </div>

      {/* ═══ BOT CARDS ══════════════════════════════════════════════════════ */}
      <div className="mx-auto px-4 pt-4 pb-2 space-y-3" style={{ maxWidth: 600 }}>

        {/* Moe — SPY/QQQ trend */}
        <BotCard
          name="Moe  ·  SPY/QQQ"
          bot={spy}
          wfStatus={wfMap.get("spy_qqq_trend")}
          positions={spyPos}
          accent="#fbbf24"
          mktOpen={mktOpen}
        />

        {/* Larry — Oracle momentum equity */}
        <BotCard
          name="Larry  ·  Oracle"
          bot={oracle}
          wfStatus={wfMap.get("oracle")}
          positions={otherPos}
          accent="#a78bfa"
          mktOpen={mktOpen}
        />

        {/* Curly — Jerome + Buck (combined card) */}
        <BotCard
          name="Curly  ·  Jerome + Buck"
          bot={jerome}
          bot2={buck}
          wfStatus={wfMap.get("jerome_macro")}
          positions={[]}
          posCountFallback={curlyCount}
          accent="#f87171"
          mktOpen={mktOpen}
        />

        {/* ═══ FOOTER STRIP ════════════════════════════════════════════════ */}
        <div
          className="flex items-center justify-between gap-3 px-4 py-3 rounded-2xl border text-[10px] flex-wrap mt-1"
          style={{ background: "rgba(10,16,30,0.8)", borderColor: "rgba(255,255,255,0.06)" }}
        >
          <div className="flex items-center gap-4 flex-wrap">
            <span className="text-slate-500">
              30d WR{" "}
              <span
                className="font-bold tabular-nums"
                style={{ color: fleetWr != null ? "#22d3ee" : "#475569" }}
              >
                {fleetWr != null ? `${(fleetWr * 100).toFixed(1)}%` : "—"}
              </span>
            </span>
            {lastCycle && (
              <span className="text-slate-600">
                cycle{" "}
                <span className="text-slate-400">
                  {new Date(lastCycle).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                </span>
              </span>
            )}
          </div>
          <button
            className="font-semibold transition-colors text-[11px] hover:opacity-80"
            style={{ color: "#22d3ee" }}
            onClick={() => navigate("/stream")}
          >
            Full report →
          </button>
        </div>
      </div>

      {/* Spacer for bottom GlobalNav */}
      <div style={{ height: 96 }} />
    </div>
  );
}
