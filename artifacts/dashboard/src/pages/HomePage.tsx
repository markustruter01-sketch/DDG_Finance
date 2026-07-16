/**
 * HomePage — mobile-first single-screen dashboard.
 * Rule 27: ALL P&L / equity numbers come verbatim from /fleet/equity.
 * Zero client-side arithmetic on financial figures.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "wouter";
import axios from "axios";
import { isNYSEOpen } from "@/lib/dashboard-shared";
import {
  useFleetData,
  getBotStatus,
  STATUS_COLORS,
  STATUS_LABELS,
  fmtEq,
  fmtPct,
  fmtDollar,
  type BotSlice,
  type BotStatus,
  type LivePos,
} from "@/hooks/useFleetData";

const BASE = import.meta.env.VITE_API_BASE_URL || "/trading-api";

// ── WF badge ─────────────────────────────────────────────────────────────────

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

// ── Status dot ────────────────────────────────────────────────────────────────

function StatusDot({ status, sm }: { status: BotStatus; sm?: boolean }) {
  const c = STATUS_COLORS[status];
  const size = sm ? 6 : 8;
  return (
    <span
      className="inline-block rounded-full shrink-0"
      style={{
        width:     size,
        height:    size,
        background: c,
        boxShadow: status !== "MKT_CLOSED" ? `0 0 7px ${c}aa` : undefined,
        marginTop: 1,
      }}
    />
  );
}

// ── Position display ──────────────────────────────────────────────────────────

function PositionChips({ positions }: { positions: LivePos[] }) {
  if (positions.length === 0)
    return <span className="text-[10px] text-slate-600 italic">No open positions</span>;
  return (
    <div className="flex flex-wrap gap-x-2.5 gap-y-0.5">
      {positions.map((p) => {
        const pct   = p.unrealized_plpc * 100;
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
        const pct   = p.unrealized_plpc * 100;
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
            <span className="text-slate-600 text-[9px] tabular-nums">{fmtDollar(p.unrealized_pl)}</span>
          </div>
        );
      })}
    </div>
  );
}

// ── Standard bot card (Moe / Larry) ──────────────────────────────────────────

interface BotCardProps {
  name:      string;
  bot:       BotSlice | undefined;
  wfStatus?: string | null;
  positions: LivePos[];
  accent:    string;
  mktOpen:   boolean;
}

function BotCard({ name, bot, wfStatus, positions, accent, mktOpen }: BotCardProps) {
  const [expanded, setExpanded] = useState(false);
  const status   = getBotStatus(bot, mktOpen, false);
  const sColor   = STATUS_COLORS[status];
  /* Rule 27 — use server-computed pnl & pnl_pct verbatim, zero arithmetic */
  const equity   = bot?.equity  ?? 0;
  const pnl      = bot?.pnl     ?? 0;
  const pnlPct   = bot?.pnl_pct ?? 0;
  const pnlColor = pnl >= 0 ? "#4ade80" : "#f87171";

  return (
    <div
      className="rounded-2xl overflow-hidden border transition-all duration-200 cursor-pointer select-none"
      style={{
        background:  "rgba(10,16,30,0.97)",
        borderColor: expanded ? `${accent}50` : "rgba(255,255,255,0.07)",
        boxShadow:   expanded ? `0 0 28px ${accent}14` : "none",
      }}
      onClick={() => setExpanded((v) => !v)}
    >
      <div style={{ height: 2, background: `linear-gradient(90deg, ${accent}cc, transparent)` }} />

      <div className="px-4 pt-3 pb-3">
        {/* Row 1 */}
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          <StatusDot status={status} />
          <span className="text-[14px] font-bold text-white">{name}</span>
          <span
            className="text-[8px] font-black tracking-widest uppercase px-1.5 py-0.5 rounded"
            style={{ color: sColor, background: `${sColor}18` }}
          >
            {STATUS_LABELS[status]}
          </span>
          <WFBadge status={wfStatus} />
          <span
            className="ml-auto text-slate-600 text-[12px] transition-transform duration-200 shrink-0"
            style={{ transform: expanded ? "rotate(180deg)" : undefined }}
          >▾</span>
        </div>

        {/* Row 2 — equity + server-computed P&L */}
        <div className="flex items-baseline gap-2 mb-3">
          <span className="text-[22px] font-bold tabular-nums text-white leading-none">{fmtEq(equity)}</span>
          <span className="text-[14px] font-semibold tabular-nums" style={{ color: pnlColor }}>
            {fmtPct(pnlPct)}
          </span>
          <span className="text-[11px] tabular-nums" style={{ color: `${pnlColor}99` }}>
            {fmtDollar(pnl)}
          </span>
        </div>

        <PositionChips positions={positions} />
      </div>

      {expanded && (
        <div
          className="px-4 pb-4"
          style={{ borderTop: "1px solid rgba(255,255,255,0.05)" }}
          onClick={(e) => e.stopPropagation()}
        >
          <PositionTable positions={positions} />
          {positions.length === 0 && (
            <p className="text-[10px] text-slate-600 mt-3">No open positions</p>
          )}
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[10px] font-mono text-slate-500">
            {bot?.win_rate != null && (
              <span>30d WR <span className="text-cyan-400">{(bot.win_rate * 100).toFixed(1)}%</span></span>
            )}
            {bot?.last_updated && (
              <span>upd <span className="text-slate-400">
                {new Date(bot.last_updated).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </span></span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Curly card (Jerome + Buck, two canonical sub-rows) ────────────────────────

interface CurlySubRowProps {
  label:     string;
  bot:       BotSlice | undefined;
  status:    BotStatus;
  wfStatus?: string | null;
}

function CurlySubRow({ label, bot, status, wfStatus }: CurlySubRowProps) {
  const pnlColor = (bot?.pnl ?? 0) >= 0 ? "#4ade80" : "#f87171";
  return (
    <div className="flex items-center gap-2 py-1.5">
      <StatusDot status={status} sm />
      <span className="text-[11px] text-slate-400 font-semibold w-16 shrink-0">{label}</span>
      <span className="text-[15px] font-bold text-white tabular-nums leading-none">
        {fmtEq(bot?.equity ?? 0)}
      </span>
      <span className="text-[12px] font-semibold tabular-nums" style={{ color: pnlColor }}>
        {fmtPct(bot?.pnl_pct ?? 0)}
      </span>
      <span className="text-[10px] tabular-nums" style={{ color: `${pnlColor}88` }}>
        {fmtDollar(bot?.pnl ?? 0)}
      </span>
      <WFBadge status={wfStatus} />
    </div>
  );
}

interface CurlyCardProps {
  jerome:     BotSlice | undefined;
  buck:       BotSlice | undefined;
  jeromeWF?:  string | null;
  buckWF?:    string | null;
  curlyCount: number;
  mktOpen:    boolean;
}

function CurlyCard({ jerome, buck, jeromeWF, buckWF, curlyCount, mktOpen }: CurlyCardProps) {
  const [expanded, setExpanded] = useState(false);
  const jStatus = getBotStatus(jerome, mktOpen, false);
  /* Buck is the ADX-idle bot — only it can be IDLE-BY-DESIGN */
  const bStatus = getBotStatus(buck, mktOpen, true);
  const overall: BotStatus =
    jStatus === "DOWN"  || bStatus === "DOWN"  ? "DOWN" :
    jStatus === "LIVE"  || bStatus === "LIVE"  ? "LIVE" :
    jStatus === "IDLE"  || bStatus === "IDLE"  ? "IDLE" :
    "MKT_CLOSED";
  const accent = "#f87171";

  return (
    <div
      className="rounded-2xl overflow-hidden border transition-all duration-200 cursor-pointer select-none"
      style={{
        background:  "rgba(10,16,30,0.97)",
        borderColor: expanded ? `${accent}50` : "rgba(255,255,255,0.07)",
        boxShadow:   expanded ? `0 0 28px ${accent}14` : "none",
      }}
      onClick={() => setExpanded((v) => !v)}
    >
      <div style={{ height: 2, background: `linear-gradient(90deg, ${accent}cc, transparent)` }} />

      <div className="px-4 pt-3 pb-3">
        {/* Header */}
        <div className="flex items-center gap-2 mb-2">
          <StatusDot status={overall} />
          <span className="text-[14px] font-bold text-white">Curly · Jerome + Buck</span>
          <span
            className="ml-auto text-slate-600 text-[12px] transition-transform duration-200 shrink-0"
            style={{ transform: expanded ? "rotate(180deg)" : undefined }}
          >▾</span>
        </div>

        {/* Jerome sub-row */}
        <CurlySubRow label="Curly"    bot={jerome} status={jStatus} wfStatus={jeromeWF} />
        {/* Buck sub-row */}
        <CurlySubRow label="Curly Jr" bot={buck}   status={bStatus} wfStatus={buckWF}   />

        <div className="mt-2">
          {curlyCount > 0
            ? <span className="text-[10px] text-slate-500">{curlyCount} position{curlyCount !== 1 ? "s" : ""} tracked</span>
            : <span className="text-[10px] text-slate-600 italic">No open positions</span>
          }
        </div>
      </div>

      {expanded && (
        <div
          className="px-4 pb-4"
          style={{ borderTop: "1px solid rgba(255,255,255,0.05)" }}
          onClick={(e) => e.stopPropagation()}
        >
          <p className="text-[10px] text-slate-600 mt-3 italic">
            Positions tracked in shared Alpaca account — see Stream › Bots for per-position detail.
          </p>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[10px] font-mono text-slate-500">
            {jerome?.win_rate != null && (
              <span>Curly WR <span className="text-cyan-400">{(jerome.win_rate * 100).toFixed(1)}%</span></span>
            )}
            {buck?.win_rate != null && (
              <span>Jr WR <span className="text-cyan-400">{(buck.win_rate * 100).toFixed(1)}%</span></span>
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
    CRISIS: { emoji: "🚨", color: "#ef4444", bg: "rgba(239,68,68,0.14)",  border: "rgba(239,68,68,0.40)"  },
    BEAR:   { emoji: "🐻", color: "#f97316", bg: "rgba(249,115,22,0.14)", border: "rgba(249,115,22,0.40)" },
    BULL:   { emoji: "🟢", color: "#22c55e", bg: "rgba(34,197,94,0.12)",  border: "rgba(34,197,94,0.35)"  },
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
          boxShadow:  tripped ? "0 0 8px #ef4444" : "0 0 5px #22c55e55",
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
  const {
    oracle, spy, jerome, buck, total,
    spyPos, otherPos, wfMap,
    regime, killTripped, lastCycle, mktOpen,
  } = useFleetData();

  const fleetPnl    = total?.pnl     ?? null;
  const fleetPnlPct = total?.pnl_pct ?? null;
  const fleetEq     = total?.equity  ?? null;
  const fleetWr     = total?.win_rate ?? null;
  const pnlColor    = (fleetPnl ?? 0) >= 0 ? "#4ade80" : "#f87171";
  const curlyCount  = (jerome?.positions ?? 0) + (buck?.positions ?? 0);

  return (
    <div className="min-h-screen bg-slate-950 font-mono text-white">

      {/* ═══ HEADER ══════════════════════════════════════════════════════════ */}
      <div
        className="sticky top-0 z-20 flex items-center gap-3 px-4 py-3 flex-wrap"
        style={{ background: "#030712", borderBottom: "1px solid rgba(34,211,238,0.10)" }}
      >
        <div className="flex items-baseline gap-2">
          <span className="text-[20px] font-bold text-white tabular-nums leading-none">
            {fleetEq != null ? fmtEq(fleetEq) : "—"}
          </span>
          {fleetPnl != null && (
            <span className="text-[13px] font-semibold tabular-nums" style={{ color: pnlColor }}>
              {fmtDollar(fleetPnl)}
              {fleetPnlPct != null && (
                <span className="text-[11px] ml-1 opacity-70">({fmtPct(fleetPnlPct)})</span>
              )}
            </span>
          )}
        </div>
        <MarketChip regime={regime} />
        <div className="ml-auto"><KillDot tripped={killTripped} /></div>
      </div>

      {/* ═══ BOT CARDS ═══════════════════════════════════════════════════════ */}
      <div className="mx-auto px-4 pt-4 pb-2 space-y-3" style={{ maxWidth: 600 }}>

        <BotCard
          name="Moe  ·  SPY/QQQ"
          bot={spy}
          wfStatus={wfMap.get("spy_qqq_trend")}
          positions={spyPos}
          accent="#fbbf24"
          mktOpen={mktOpen}
        />

        <BotCard
          name="Larry  ·  Oracle"
          bot={oracle}
          wfStatus={wfMap.get("oracle")}
          positions={otherPos}
          accent="#a78bfa"
          mktOpen={mktOpen}
        />

        <CurlyCard
          jerome={jerome}
          buck={buck}
          jeromeWF={wfMap.get("jerome_macro")}
          buckWF={wfMap.get("buck_futures")}
          curlyCount={curlyCount}
          mktOpen={mktOpen}
        />

        {/* ═══ FOOTER ══════════════════════════════════════════════════════ */}
        <div
          className="flex items-center justify-between gap-3 px-4 py-3 rounded-2xl border text-[10px] flex-wrap mt-1"
          style={{ background: "rgba(10,16,30,0.8)", borderColor: "rgba(255,255,255,0.06)" }}
        >
          <div className="flex items-center gap-4 flex-wrap">
            <span className="text-slate-500">
              30d WR{" "}
              <span className="font-bold tabular-nums" style={{ color: fleetWr != null ? "#22d3ee" : "#475569" }}>
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

      <div style={{ height: 96 }} />
    </div>
  );
}
