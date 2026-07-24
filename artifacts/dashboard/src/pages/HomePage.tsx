/**
 * HomePage — Space Fleet edition
 * Animations: warp starfield pulse · constellation star map · scrolling comms ticker
 * Rule 27: all P&L values are server-computed — zero arithmetic on the client
 */
import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { useLocation } from "wouter";
import {
  useFleetData,
  getBotStatus,
  fmtEq, fmtPct, fmtDollar,
  type BotSlice, type BotStatus,
} from "@/hooks/useFleetData";
import { useExportReport } from "@/hooks/use-kraken";
import { useToast } from "@/hooks/use-toast";

// ── Keyframes (injected once) ─────────────────────────────────────────────────

const CSS_ANIMATIONS = `
@keyframes ticker-scroll {
  0%   { transform: translateX(0); }
  100% { transform: translateX(-50%); }
}
@keyframes constellation-spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
@keyframes star-twinkle {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.45; }
}
@keyframes warp-out {
  0%   { transform: scale(1);    opacity: 1; }
  35%  { transform: scale(1.22); opacity: 0.65; }
  100% { transform: scale(1);    opacity: 1; }
}
@keyframes warp-star-streak {
  0%   { transform: scale(1);   }
  30%  { transform: scale(1.3); }
  100% { transform: scale(1);   }
}
`;

function StyleTag() {
  return <style>{CSS_ANIMATIONS}</style>;
}

// ── Starfield (CSS box-shadow, warp-pulse on data refresh) ────────────────────

function buildStarShadow(count = 100) {
  return Array.from({ length: count }, (_, i) => {
    const x   = ((i * 37 + 13) % 97).toFixed(1);
    const y   = ((i * 53 + 7)  % 97).toFixed(1);
    const op  = (0.15 + (i % 6) * 0.08).toFixed(2);
    const sz  = i % 12 === 0 ? "1.5px" : "0px";
    return `${x}vw ${y}vh ${sz} 0px rgba(255,255,255,${op})`;
  }).join(", ");
}

const STAR_SHADOW = buildStarShadow();

function Starfield({ warp }: { warp: boolean }) {
  return (
    <div
      style={{
        position: "fixed", inset: 0, pointerEvents: "none", zIndex: 0,
        boxShadow: STAR_SHADOW,
        animation: warp ? "warp-star-streak 0.7s ease-out forwards" : undefined,
        willChange: "transform",
      }}
    />
  );
}

// ── Constellation map ─────────────────────────────────────────────────────────

interface BotStar {
  id:    string;
  label: string;
  equity: number;
  pnl:    number;
  angle:  number; // degrees, fixed per bot
}

function ConstellationMap({ stars }: { stars: BotStar[] }) {
  const CX = 100, CY = 100, MAX_R = 68, MIN_R = 32;
  const equities = stars.map(s => s.equity).filter(Boolean);
  const minEq = Math.min(...equities);
  const maxEq = Math.max(...equities);
  const range = maxEq - minEq || 1;

  const pts = stars.map(s => {
    const r   = MIN_R + ((s.equity - minEq) / range) * (MAX_R - MIN_R);
    const rad = (s.angle * Math.PI) / 180;
    const x   = CX + r * Math.cos(rad);
    const y   = CY + r * Math.sin(rad);
    const pos = s.pnl >= 0;
    const dotColor = pos ? "#22d3ee" : s.pnl < -5000 ? "#f87171" : "#f59e0b";
    const glowColor = pos ? "#22d3ee" : "#f87171";
    const dotR = 3 + (r / MAX_R) * 4;
    return { ...s, x, y, r, dotR, dotColor, glowColor, pos };
  });

  return (
    <div className="flex flex-col items-center" style={{ gap: 4 }}>
      <div className="text-[8px] uppercase tracking-[0.25em] text-slate-700 mb-1">FLEET CONSTELLATION</div>
      <svg
        width="200" height="200"
        viewBox="0 0 200 200"
        style={{ overflow: "visible" }}
      >
        {/* Rotating group */}
        <g style={{ animation: "constellation-spin 90s linear infinite", transformOrigin: "100px 100px" }}>
          {/* Connection lines between all pairs */}
          {pts.flatMap((a, i) =>
            pts.slice(i + 1).map(b => (
              <line
                key={`${a.id}-${b.id}`}
                x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                stroke="rgba(34,211,238,0.08)" strokeWidth="0.8"
              />
            ))
          )}

          {/* Bot stars */}
          {pts.map(p => (
            <g key={p.id}>
              {/* Glow halo */}
              <circle
                cx={p.x} cy={p.y} r={p.dotR + 4}
                fill={`${p.glowColor}12`}
                style={{ animation: `star-twinkle ${2 + pts.indexOf(p) * 0.7}s ease-in-out infinite` }}
              />
              {/* Core dot */}
              <circle
                cx={p.x} cy={p.y} r={p.dotR}
                fill={p.dotColor}
                style={{
                  filter: `drop-shadow(0 0 4px ${p.glowColor})`,
                  animation: `star-twinkle ${3 + pts.indexOf(p) * 0.5}s ease-in-out infinite`,
                }}
              />
            </g>
          ))}
        </g>

        {/* Fleet center (non-rotating) */}
        <circle cx={CX} cy={CY} r={3} fill="#22d3ee" opacity={0.5}
          style={{ filter: "drop-shadow(0 0 5px #22d3ee)" }} />
        <circle cx={CX} cy={CY} r={8} fill="none" stroke="#22d3ee18" strokeWidth="0.5" />
        <circle cx={CX} cy={CY} r={16} fill="none" stroke="#22d3ee0a" strokeWidth="0.5" />

        {/* Labels (static, don't rotate) */}
        {pts.map(p => {
          const lx = CX + (p.x - CX) * 1.38;
          const ly = CY + (p.y - CY) * 1.38;
          return (
            <text
              key={`lbl-${p.id}`}
              x={lx} y={ly}
              textAnchor="middle" dominantBaseline="middle"
              fontSize="7"
              fill={p.dotColor}
              opacity={0.7}
            >
              {p.label}
            </text>
          );
        })}
      </svg>
    </div>
  );
}

// ── Comms ticker ──────────────────────────────────────────────────────────────

function CommsTicker({ segments }: { segments: string[] }) {
  const text = segments.join("  ·  ");
  const doubled = `${text}  ·  ${text}`;          // seamless loop

  return (
    <div
      style={{
        overflow: "hidden",
        borderTop:    "1px solid rgba(34,211,238,0.10)",
        borderBottom: "1px solid rgba(34,211,238,0.10)",
        background: "rgba(3,7,18,0.85)",
        backdropFilter: "blur(4px)",
        padding: "6px 0",
      }}
    >
      <div
        style={{
          display: "inline-block",
          whiteSpace: "nowrap",
          animation: "ticker-scroll 28s linear infinite",
          fontSize: 10,
          fontFamily: "monospace",
          color: "#22d3ee",
          letterSpacing: "0.08em",
          opacity: 0.8,
        }}
      >
        {doubled}
      </div>
    </div>
  );
}

// ── WF badge ──────────────────────────────────────────────────────────────────

const WF_CFG: Record<string, { label: string; color: string }> = {
  PASS:              { label: "PASS",   color: "#22c55e" },
  MARGINAL:          { label: "AMBER",  color: "#f59e0b" },
  FAIL:              { label: "FAIL",   color: "#ef4444" },
  INSUFFICIENT_DATA: { label: "INSUFF", color: "#64748b" },
};

function WFBadge({ status }: { status: string | null | undefined }) {
  const b = WF_CFG[status ?? ""] ?? { label: "N/A", color: "#334155" };
  return (
    <span className="text-[8px] font-black tracking-widest uppercase px-1.5 py-0.5 rounded border"
      style={{ color: b.color, borderColor: `${b.color}40`, background: `${b.color}12` }}>
      WF {b.label}
    </span>
  );
}

// ── WF health bar ─────────────────────────────────────────────────────────────

const WF_HEALTH: Record<string, { pct: number; color: string; label: string }> = {
  PASS:              { pct: 100, color: "#22c55e", label: "SHIELDS 100%" },
  MARGINAL:          { pct: 55,  color: "#f59e0b", label: "SHIELDS 55%"  },
  FAIL:              { pct: 15,  color: "#ef4444", label: "SHIELDS 15%"  },
  INSUFFICIENT_DATA: { pct: 0,   color: "#64748b", label: "NO DATA"      },
};

function HealthBar({ wfStatus }: { wfStatus: string | null | undefined }) {
  const h = WF_HEALTH[wfStatus ?? ""] ?? WF_HEALTH["INSUFFICIENT_DATA"];
  return (
    <div className="flex items-center gap-2">
      <div className="text-[8px] uppercase tracking-widest text-slate-600 shrink-0 w-14">SHIELDS</div>
      <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: "#0f172a" }}>
        <div className="h-full rounded-full transition-all duration-700"
          style={{ width: `${h.pct}%`, background: h.color, boxShadow: `0 0 6px ${h.color}` }} />
      </div>
      <span className="text-[8px] tabular-nums shrink-0" style={{ color: h.color }}>{h.label}</span>
    </div>
  );
}

// ── Ship card (single bot) ────────────────────────────────────────────────────

const STATUS_SHIP: Record<BotStatus, { label: string; color: string }> = {
  LIVE:       { label: "ONLINE",   color: "#22c55e" },
  MKT_CLOSED: { label: "DOCKED",   color: "#64748b" },
  DOWN:       { label: "DISTRESS", color: "#ef4444" },
  IDLE:       { label: "STANDBY",  color: "#eab308" },
};

interface ShipCardProps {
  shipName:  string;
  callsign:  string;
  bot:       BotSlice | undefined;
  status:    BotStatus;
  wfStatus?: string | null;
  accent:    string;
  posChips?: { symbol: string; plPct: number }[];
}

function ShipCard({ shipName, callsign, bot, status, wfStatus, accent, posChips = [] }: ShipCardProps) {
  const [open, setOpen] = useState(false);
  const st     = STATUS_SHIP[status];
  const pnl    = bot?.pnl     ?? 0;
  const pnlPct = bot?.pnl_pct ?? 0;
  const posClr = pnl >= 0 ? "#4ade80" : "#f87171";

  return (
    <div
      className="rounded-2xl overflow-hidden cursor-pointer select-none transition-shadow duration-300"
      style={{
        background:  "rgba(8,12,24,0.97)",
        border:      `1px solid ${accent}35`,
        boxShadow:   open ? `0 0 30px ${accent}18, 0 0 60px ${accent}08` : "none",
      }}
      onClick={() => setOpen(v => !v)}
    >
      <div style={{ height: 2, background: `linear-gradient(90deg, ${accent}, ${accent}44 50%, transparent)` }} />
      <div className="px-4 pt-3 pb-3">
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          <span className="text-[10px] font-black tracking-[0.15em] uppercase"
            style={{ color: accent, textShadow: `0 0 8px ${accent}66` }}>
            {shipName}
          </span>
          <span className="text-[9px] text-slate-600">{callsign}</span>
          <div className="ml-auto flex items-center gap-1.5">
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: st.color,
              boxShadow: `0 0 6px ${st.color}`, flexShrink: 0 }} />
            <span className="text-[8px] font-bold tracking-widest uppercase" style={{ color: st.color }}>
              {st.label}
            </span>
          </div>
        </div>

        <div className="flex items-baseline gap-2 mb-2">
          <span className="text-[22px] font-bold tabular-nums text-white leading-none">{fmtEq(bot?.equity ?? 0)}</span>
          <span className="text-[13px] font-semibold tabular-nums" style={{ color: posClr }}>{fmtPct(pnlPct)}</span>
          <span className="text-[10px] tabular-nums" style={{ color: `${posClr}88` }}>{fmtDollar(pnl)}</span>
          <WFBadge status={wfStatus} />
        </div>

        <HealthBar wfStatus={wfStatus} />

        {posChips.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-x-2 gap-y-0.5">
            {posChips.map(p => {
              const c = p.plPct >= 0 ? `${accent}cc` : "#f87171cc";
              return (
                <span key={p.symbol} className="text-[9px] px-1.5 py-0.5 rounded"
                  style={{ background: `${accent}12`, color: c, border: `1px solid ${accent}22` }}>
                  {p.symbol} {p.plPct >= 0 ? "+" : ""}{p.plPct.toFixed(1)}%
                </span>
              );
            })}
          </div>
        )}
      </div>

      {open && (
        <div className="px-4 pb-3" style={{ borderTop: "1px solid rgba(255,255,255,0.05)" }}
          onClick={e => e.stopPropagation()}>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[9px] text-slate-600">
            {bot?.win_rate != null && <span>30D WR <span className="text-cyan-500">{(bot.win_rate * 100).toFixed(1)}%</span></span>}
            {bot?.positions != null && <span>POSITIONS <span className="text-cyan-500">{bot.positions}</span></span>}
            {bot?.last_updated && <span>PING <span className="text-cyan-500">{new Date(bot.last_updated).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span></span>}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Curly dual-ship card (Jerome + Buck, two sub-rows, no summing) ─────────────

interface CurlyShipCardProps {
  jerome: BotSlice | undefined; jeromeStatus: BotStatus; jeromeWF?: string | null;
  buck:   BotSlice | undefined; buckStatus:   BotStatus; buckWF?:   string | null;
}

function CurlyShipCard({ jerome, jeromeStatus, jeromeWF, buck, buckStatus, buckWF }: CurlyShipCardProps) {
  const [open, setOpen] = useState(false);
  const accent = "#f87171";
  const overall: BotStatus =
    jeromeStatus === "DOWN"  || buckStatus === "DOWN"  ? "DOWN"  :
    jeromeStatus === "LIVE"  || buckStatus === "LIVE"  ? "LIVE"  :
    jeromeStatus === "IDLE"  || buckStatus === "IDLE"  ? "IDLE"  : "MKT_CLOSED";
  const st = STATUS_SHIP[overall];

  return (
    <div className="rounded-2xl overflow-hidden cursor-pointer select-none transition-shadow duration-300"
      style={{ background: "rgba(8,12,24,0.97)", border: `1px solid ${accent}35`,
        boxShadow: open ? `0 0 30px ${accent}18` : "none" }}
      onClick={() => setOpen(v => !v)}>
      <div style={{ height: 2, background: `linear-gradient(90deg, ${accent}cc, ${accent}44 50%, transparent)` }} />
      <div className="px-4 pt-3 pb-3">
        <div className="flex items-center gap-2 mb-3">
          <span className="text-[10px] font-black tracking-[0.15em] uppercase"
            style={{ color: accent, textShadow: `0 0 8px ${accent}66` }}>TITAN-CLASS</span>
          <span className="text-[9px] text-slate-600">Curly · Jerome + Buck</span>
          <div className="ml-auto flex items-center gap-1.5">
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: st.color,
              boxShadow: `0 0 6px ${st.color}`, flexShrink: 0 }} />
            <span className="text-[8px] font-bold tracking-widest uppercase" style={{ color: st.color }}>{st.label}</span>
          </div>
        </div>

        {([
          { name: "MACRO-J", label: "Curly (Jerome)",  bot: jerome, status: jeromeStatus, wf: jeromeWF },
          { name: "BUCK-F",  label: "Curly Jr (Buck)", bot: buck,   status: buckStatus,   wf: buckWF   },
        ] as const).map(({ name, label, bot, status, wf }) => {
          const pnl = bot?.pnl ?? 0;
          const posC = pnl >= 0 ? "#4ade80" : "#f87171";
          const subSt = STATUS_SHIP[status];
          const wfH = WF_HEALTH[wf ?? ""] ?? WF_HEALTH["INSUFFICIENT_DATA"];
          return (
            <div key={name} className="mb-3 pl-3" style={{ borderLeft: "1px solid #f8717130" }}>
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[9px] font-black" style={{ color: accent }}>{name}</span>
                <span className="text-[8px] text-slate-600">{label}</span>
                <div style={{ width: 5, height: 5, borderRadius: "50%", background: subSt.color,
                  boxShadow: `0 0 4px ${subSt.color}`, marginLeft: "auto" }} />
                <span className="text-[8px]" style={{ color: subSt.color }}>{subSt.label}</span>
              </div>
              <div className="flex items-baseline gap-2 mb-1">
                <span className="text-[17px] font-bold tabular-nums text-white">{fmtEq(bot?.equity ?? 0)}</span>
                <span className="text-[12px] tabular-nums" style={{ color: posC }}>{fmtPct(bot?.pnl_pct ?? 0)}</span>
                <span className="text-[10px] tabular-nums" style={{ color: `${posC}88` }}>{fmtDollar(pnl)}</span>
                <WFBadge status={wf} />
              </div>
              <div className="flex items-center gap-2">
                <div className="flex-1 h-1 rounded-full overflow-hidden" style={{ background: "#0f172a" }}>
                  <div className="h-full rounded-full" style={{ width: `${wfH.pct}%`, background: wfH.color, boxShadow: `0 0 4px ${wfH.color}` }} />
                </div>
                <span className="text-[8px] shrink-0" style={{ color: wfH.color }}>{wfH.label}</span>
              </div>
            </div>
          );
        })}
      </div>

      {open && (
        <div className="px-4 pb-3" style={{ borderTop: "1px solid rgba(255,255,255,0.05)" }}
          onClick={e => e.stopPropagation()}>
          <p className="text-[9px] text-slate-700 mt-3 italic">
            Positions tracked in shared Alpaca account — see Stream for detail.
          </p>
        </div>
      )}
    </div>
  );
}

// ── Market + kill-switch chips ────────────────────────────────────────────────

function RegimeChip({ regime }: { regime: string | undefined }) {
  if (!regime || regime === "UNKNOWN") return null;
  const cfgs: Record<string, { color: string; bg: string; border: string }> = {
    CRISIS: { color: "#ef4444", bg: "rgba(239,68,68,0.14)",  border: "rgba(239,68,68,0.40)"  },
    BEAR:   { color: "#f97316", bg: "rgba(249,115,22,0.14)", border: "rgba(249,115,22,0.40)" },
    BULL:   { color: "#22c55e", bg: "rgba(34,197,94,0.12)",  border: "rgba(34,197,94,0.35)"  },
  };
  const c = cfgs[regime] ?? cfgs["BULL"];
  return (
    <span className="text-[9px] font-black tracking-widest uppercase px-2 py-1 rounded-full border"
      style={{ color: c.color, background: c.bg, borderColor: c.border }}>
      {regime}
    </span>
  );
}

// ── Export dropdown ───────────────────────────────────────────────────────────

function ExportDropdown({
  spy, oracle, jerome, buck, total, regime, killTripped,
}: {
  spy?: BotSlice; oracle?: BotSlice; jerome?: BotSlice; buck?: BotSlice;
  total?: BotSlice; regime?: string; killTripped?: boolean | null;
}) {
  const [open, setOpen]     = useState(false);
  const [busy, setBusy]     = useState<string | null>(null);
  const ref                 = useRef<HTMLDivElement>(null);
  const exportReport        = useExportReport();
  const { toast }           = useToast();
  const [, navigate]        = useLocation();

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const handleExportReport = useCallback(async () => {
    setBusy("report");
    try {
      const result = await exportReport.mutateAsync();
      const now = new Date();
      const ts = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}-${String(now.getHours()).padStart(2, "0")}${String(now.getMinutes()).padStart(2, "0")}`;
      const filename = `quant-terminal-report-${ts}.txt`;
      const blob = new Blob([result.report], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = filename; a.click();
      URL.revokeObjectURL(url);
      toast({ title: "Report downloaded", description: filename });
      setOpen(false);
    } catch (err: any) {
      toast({ variant: "destructive", title: "Export failed", description: err?.message ?? "Could not generate report." });
    } finally { setBusy(null); }
  }, [exportReport, toast]);

  const handleClaudeBrief = useCallback(async () => {
    setBusy("brief");
    try {
      const base = import.meta.env.VITE_API_BASE_URL || "/trading-api";
      const res = await fetch(`${base}/claude-context`);
      if (!res.ok) throw new Error("Request failed");
      const data = await res.json();
      const text = data.prompt as string;
      const date = new Date().toISOString().slice(0, 10);
      const blob = new Blob([text], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `claude-brief-${date}.txt`; a.click();
      URL.revokeObjectURL(url);
      toast({ title: "Claude Brief downloaded", description: `claude-brief-${date}.txt` });
      setOpen(false);
    } catch {
      toast({ title: "Download failed", description: "Check the trading API is running.", variant: "destructive" });
    } finally { setBusy(null); }
  }, [toast]);

  const handleCopyFleetStatus = useCallback(async () => {
    setBusy("copy");
    const lines = [
      `STOOGE FLEET STATUS — ${new Date().toLocaleString()}`,
      `──────────────────────────────────`,
      `FLEET TOTAL  ${fmtEq(total?.equity ?? 0)}  ${fmtPct(total?.pnl_pct ?? 0)}  ${fmtDollar(total?.pnl ?? 0)}`,
      ``,
      `SPY-HAWK     ${fmtEq(spy?.equity ?? 0)}  ${fmtPct(spy?.pnl_pct ?? 0)}  ${fmtDollar(spy?.pnl ?? 0)}`,
      `ORACLE-7     ${fmtEq(oracle?.equity ?? 0)}  ${fmtPct(oracle?.pnl_pct ?? 0)}  ${fmtDollar(oracle?.pnl ?? 0)}`,
      `MACRO-J      ${fmtEq(jerome?.equity ?? 0)}  ${fmtPct(jerome?.pnl_pct ?? 0)}  ${fmtDollar(jerome?.pnl ?? 0)}`,
      `BUCK-F       ${fmtEq(buck?.equity ?? 0)}  ${fmtPct(buck?.pnl_pct ?? 0)}  ${fmtDollar(buck?.pnl ?? 0)}`,
      ``,
      `REGIME: ${regime ?? "UNKNOWN"}`,
      `KILL SWITCH: ${killTripped == null ? "UNKNOWN" : killTripped ? "TRIPPED ⚠" : "ARMED"}`,
    ].join("\n");
    try {
      await navigator.clipboard.writeText(lines);
      toast({ title: "Fleet status copied", description: "Paste into any AI or document." });
    } catch {
      const ta = document.createElement("textarea");
      ta.value = lines; document.body.appendChild(ta); ta.select();
      document.execCommand("copy"); document.body.removeChild(ta);
      toast({ title: "Fleet status copied" });
    } finally { setBusy(null); setOpen(false); }
  }, [spy, oracle, jerome, buck, total, regime, killTripped, toast]);

  const items = [
    {
      id: "report",
      icon: "📥",
      label: "Export Full Report",
      sub: "quant-terminal-report-{ts}.txt",
      action: handleExportReport,
      accent: "#22d3ee",
    },
    {
      id: "brief",
      icon: "🧠",
      label: "Claude Brief",
      sub: "Paste into new Claude session",
      action: handleClaudeBrief,
      accent: "#a78bfa",
    },
    {
      id: "copy",
      icon: "📋",
      label: "Copy Fleet Status",
      sub: "Snapshot to clipboard",
      action: handleCopyFleetStatus,
      accent: "#4ade80",
    },
    {
      id: "stream",
      icon: "📡",
      label: "Full Stream Report",
      sub: "Live positions & analytics",
      action: () => { navigate("/stream"); setOpen(false); },
      accent: "#f59e0b",
    },
  ];

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        onClick={() => setOpen(v => !v)}
        style={{
          display: "flex", alignItems: "center", gap: 5,
          fontSize: 10, fontFamily: "monospace", fontWeight: 700,
          letterSpacing: "0.12em", textTransform: "uppercase",
          padding: "4px 10px", borderRadius: 8,
          background: open ? "rgba(34,211,238,0.12)" : "rgba(34,211,238,0.06)",
          border: "1px solid rgba(34,211,238,0.22)",
          color: "#22d3ee", cursor: "pointer",
          transition: "all 0.15s",
        }}
      >
        <span>EXPORT</span>
        <span style={{ fontSize: 8, opacity: 0.7, transform: open ? "rotate(180deg)" : "none", transition: "transform 0.2s", display: "inline-block" }}>▼</span>
      </button>

      {open && (
        <div
          style={{
            position: "absolute", top: "calc(100% + 6px)", right: 0,
            minWidth: 240, borderRadius: 12,
            background: "rgba(6,10,22,0.98)",
            border: "1px solid rgba(34,211,238,0.16)",
            boxShadow: "0 16px 48px rgba(0,0,0,0.7), 0 0 0 1px rgba(34,211,238,0.08)",
            backdropFilter: "blur(12px)",
            zIndex: 100,
            overflow: "hidden",
          }}
        >
          <div style={{ padding: "8px 12px 6px", fontSize: 8, letterSpacing: "0.2em", color: "#334155", fontFamily: "monospace", textTransform: "uppercase", borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
            REPORTS &amp; EXPORTS
          </div>
          {items.map((item) => (
            <button
              key={item.id}
              disabled={busy === item.id}
              onClick={item.action}
              style={{
                display: "flex", alignItems: "center", gap: 10,
                width: "100%", padding: "10px 14px",
                background: "transparent", border: "none",
                cursor: busy === item.id ? "not-allowed" : "pointer",
                opacity: busy !== null && busy !== item.id ? 0.4 : 1,
                borderBottom: "1px solid rgba(255,255,255,0.04)",
                textAlign: "left",
                transition: "background 0.12s",
              }}
              onMouseEnter={e => (e.currentTarget.style.background = `${item.accent}12`)}
              onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
            >
              <span style={{ fontSize: 16, flexShrink: 0 }}>
                {busy === item.id ? "⏳" : item.icon}
              </span>
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: item.accent, fontFamily: "monospace", letterSpacing: "0.05em" }}>
                  {busy === item.id ? "Working…" : item.label}
                </div>
                <div style={{ fontSize: 9, color: "#475569", fontFamily: "monospace", marginTop: 1 }}>
                  {item.sub}
                </div>
              </div>
            </button>
          ))}
        </div>
      )}
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

  // Warp pulse: fires whenever lastCycle changes (new data arrived)
  const [warp, setWarp] = useState(false);
  const prevCycle = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (lastCycle && lastCycle !== prevCycle.current) {
      prevCycle.current = lastCycle;
      setWarp(true);
      const t = setTimeout(() => setWarp(false), 800);
      return () => clearTimeout(t);
    }
  }, [lastCycle]);

  const spyStatus    = getBotStatus(spy,    mktOpen, false);
  const oraStatus    = getBotStatus(oracle, mktOpen, false);
  const jeromeStatus = getBotStatus(jerome, mktOpen, false);
  const buckStatus   = getBotStatus(buck,   mktOpen, true);

  const fleetEq  = total?.equity  ?? null;
  const fleetPnl = total?.pnl     ?? null;
  const fleetPct = total?.pnl_pct ?? null;
  const pos = (fleetPnl ?? 0) >= 0;
  const pnlColor = pos ? "#4ade80" : "#f87171";

  // Constellation stars (fixed angles, radius from equity)
  const stars = useMemo<BotStar[]>(() => [
    { id: "spy",    label: "MOE",    equity: spy?.equity    ?? 100000, pnl: spy?.pnl    ?? 0, angle: -45  },
    { id: "oracle", label: "LARRY",  equity: oracle?.equity ?? 100000, pnl: oracle?.pnl ?? 0, angle: 225  },
    { id: "jerome", label: "CURLY",  equity: jerome?.equity ?? 100000, pnl: jerome?.pnl ?? 0, angle: 135  },
    { id: "buck",   label: "BUCK",   equity: buck?.equity   ?? 100000, pnl: buck?.pnl   ?? 0, angle: 315  },
  ], [spy, oracle, jerome, buck]);

  // Ticker segments
  const tickerSegments = useMemo(() => {
    const segs: string[] = [
      spy    ? `SPY-HAWK  ${fmtPct(spy.pnl_pct)}  ${fmtDollar(spy.pnl)}`       : null,
      oracle ? `ORACLE-7  ${fmtPct(oracle.pnl_pct)}  ${fmtDollar(oracle.pnl)}` : null,
      jerome ? `MACRO-J   ${fmtPct(jerome.pnl_pct)}  ${fmtDollar(jerome.pnl)}` : null,
      buck   ? `BUCK-F    ${fmtPct(buck.pnl_pct)}  ${fmtDollar(buck.pnl)}`     : null,
      total  ? `FLEET  ${fmtPct(total.pnl_pct)}  ${fmtDollar(total.pnl)}`      : null,
      `REGIME: ${regime ?? "…"}`,
      killTripped == null ? null : killTripped ? "KILL SWITCH: TRIPPED ⚠" : "KILL SWITCH: ARMED",
    ].filter(Boolean) as string[];
    return segs.length ? segs : ["LOADING FLEET DATA…"];
  }, [spy, oracle, jerome, buck, total, regime, killTripped]);

  const spyChips   = spyPos.map(p => ({ symbol: p.symbol, plPct: p.unrealized_plpc * 100 }));
  const oraChips   = otherPos.map(p => ({ symbol: p.symbol, plPct: p.unrealized_plpc * 100 }));
  const regimeColor = regime === "CRISIS" ? "#ef4444" : regime === "BEAR" ? "#f97316" : "#22c55e";

  return (
    <div className="min-h-screen font-mono text-white" style={{ background: "#030712", position: "relative" }}>
      <StyleTag />
      <Starfield warp={warp} />

      {/* ── Header ── */}
      <div
        className="sticky top-0 z-20 flex items-center gap-3 px-4 py-3 flex-wrap"
        style={{ background: "rgba(3,7,18,0.92)", borderBottom: "1px solid rgba(34,211,238,0.10)", backdropFilter: "blur(8px)" }}
      >
        <div>
          <div className="text-[8px] uppercase tracking-[0.2em] text-slate-700 mb-0.5">STOOGE FLEET · TOTAL ASSETS</div>
          <div className="flex items-baseline gap-2">
            <span className="text-[22px] font-bold tabular-nums text-white leading-none"
              style={{ textShadow: "0 0 20px #22d3ee25" }}>
              {fleetEq != null ? fmtEq(fleetEq) : "—"}
            </span>
            {fleetPnl != null && (
              <span className="text-[13px] font-semibold tabular-nums" style={{ color: pnlColor }}>
                {fmtDollar(fleetPnl)} ({fmtPct(fleetPct ?? 0)})
              </span>
            )}
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2 flex-wrap">
          <RegimeChip regime={regime} />
          {killTripped != null && (
            <div className="flex items-center gap-1.5">
              <div style={{ width: 7, height: 7, borderRadius: "50%",
                background: killTripped ? "#ef4444" : "#22c55e",
                boxShadow: killTripped ? "0 0 8px #ef4444" : "0 0 5px #22c55e55" }} />
              <span className="text-[8px] uppercase tracking-widest"
                style={{ color: killTripped ? "#ef4444" : "#475569" }}>
                {killTripped ? "KS TRIPPED" : "ARMED"}
              </span>
            </div>
          )}
          <ExportDropdown
            spy={spy} oracle={oracle} jerome={jerome} buck={buck}
            total={total ?? undefined} regime={regime} killTripped={killTripped}
          />
        </div>
      </div>

      {/* ── Ship cards ── */}
      <div className="mx-auto px-4 pt-4 pb-2 space-y-3" style={{ maxWidth: 600, position: "relative", zIndex: 1 }}>
        <ShipCard shipName="SPY-HAWK"  callsign="Moe · SPY/QQQ"  bot={spy}    status={spyStatus}
          wfStatus={wfMap.get("spy_qqq_trend")} accent="#fbbf24" posChips={spyChips} />
        <ShipCard shipName="ORACLE-7"  callsign="Larry · Oracle"  bot={oracle} status={oraStatus}
          wfStatus={wfMap.get("oracle")}        accent="#a78bfa" posChips={oraChips} />
        <CurlyShipCard
          jerome={jerome} jeromeStatus={jeromeStatus} jeromeWF={wfMap.get("jerome_macro")}
          buck={buck}     buckStatus={buckStatus}     buckWF={wfMap.get("buck_futures")} />

        {/* ── Animation zone ── */}
        <div className="rounded-2xl overflow-hidden" style={{ background: "rgba(6,10,22,0.85)", border: "1px solid rgba(34,211,238,0.08)" }}>

          {/* Constellation map */}
          <div className="flex justify-center py-4">
            <ConstellationMap stars={stars} />
          </div>

          {/* Comms ticker */}
          <CommsTicker segments={tickerSegments} />
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between text-[9px] py-2 px-1"
          style={{ color: "#1e3a5f" }}>
          <span className="uppercase tracking-widest" style={{ color: pos ? "#22c55e66" : "#ef444466" }}>
            FLEET STATUS: {pos ? "PROFITABLE" : "IN THE RED"}
          </span>
          <button className="font-bold transition-colors hover:opacity-80"
            style={{ color: "#22d3ee66" }}
            onClick={() => navigate("/stream")}>
            Full report →
          </button>
        </div>
      </div>

      <div style={{ height: 96 }} />
    </div>
  );
}
