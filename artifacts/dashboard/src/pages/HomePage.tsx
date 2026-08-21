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
  type BotSlice, type BotStatus, type LivePos, type EntryWindow,
} from "@/hooks/useFleetData";
import { useExportReport } from "@/hooks/use-report";
import { useToast } from "@/hooks/use-toast";
import { getBotIdentity } from "@/lib/bot-identity";
import FleetSparkline from "@/components/FleetSparkline";
import WorldMapWidget from "@/components/WorldMapWidget";

// ── Keyframes (injected once) ─────────────────────────────────────────────────

const CSS_ANIMATIONS = `
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
      <div className="text-[8px] uppercase tracking-[0.25em] text-white mb-1">FLEET CONSTELLATION</div>
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
        background: "rgba(255,255,255,0.12)",
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
  MARGINAL:          { label: "AMBER",  color: "#000000" },
  FAIL:              { label: "FAIL",   color: "#000000" },
  INSUFFICIENT_DATA: { label: "INSUFF", color: "#334155" },
};

function WFBadge({ status }: { status: string | null | undefined }) {
  const b = WF_CFG[status ?? ""] ?? { label: "N/A", color: "#000000" };
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
  MARGINAL:          { pct: 55,  color: "#000000", label: "SHIELDS 55%"  },
  FAIL:              { pct: 15,  color: "#000000", label: "SHIELDS 15%"  },
  INSUFFICIENT_DATA: { pct: 0,   color: "#64748b", label: "NO DATA"      },
};

function HealthBar({ wfStatus }: { wfStatus: string | null | undefined }) {
  const h = WF_HEALTH[wfStatus ?? ""] ?? WF_HEALTH["INSUFFICIENT_DATA"];
  return (
    <div className="flex items-center gap-2">
        <div className="text-[8px] uppercase tracking-widest text-white shrink-0 w-14">SHIELDS</div>
      <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(148,163,184,0.28)" }}>
        <div className="h-full rounded-full transition-all duration-700"
          style={{ width: `${h.pct}%`, background: h.color, boxShadow: `0 0 6px ${h.color}` }} />
      </div>
      <span className="text-[8px] tabular-nums shrink-0" style={{ color: h.color }}>{h.label}</span>
    </div>
  );
}

function formatCountdown(totalSeconds: number) {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  return [hours, minutes, secs].map((value) => String(value).padStart(2, "0")).join(":");
}

function EntryWindowCountdown({ entryWindow }: { entryWindow?: EntryWindow }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, []);

  if (!entryWindow) {
    return (
      <div className="mt-3 text-[9px] tracking-wide text-white">
        ⏱ Window schedule syncing…
      </div>
    );
  }

  if (entryWindow.mode === "runner_interval") {
    return (
      <div
        className="mt-3 flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[9px] font-bold tracking-wide text-amber-200"
        title={`Server schedule: ${entryWindow.source}`}
        style={{ background: "rgba(251,191,36,0.07)", border: "1px solid rgba(251,191,36,0.20)" }}
      >
        <span aria-hidden>⏱</span>
        <span>Hourly entry scans · runner-timed</span>
      </div>
    );
  }

  const startsAt = Date.parse(entryWindow.window_start_utc!);
  const endsAt = Date.parse(entryWindow.window_end_utc!);
  const open = now >= startsAt && now < endsAt;
  const secondsUntil = (Date.parse(entryWindow.next_window_start_utc!) - now) / 1000;

  return (
    <div
      className="mt-3 flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[9px] font-bold tracking-wide"
      title={`Server schedule: ${entryWindow.source}`}
      style={{
        color: open ? "#16a34a" : "#000000",
        background: open ? "rgba(34,197,94,0.10)" : "rgba(34,211,238,0.06)",
        border: `1px solid ${open ? "rgba(74,222,128,0.32)" : "rgba(34,211,238,0.16)"}`,
      }}
    >
      {open ? (
        <>
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-green-400 animate-pulse" />
          <span>ENTRY WINDOW OPEN</span>
        </>
      ) : (
        <>
          <span aria-hidden>⏱</span>
          <span>Next entry window in</span>
          <span className="tabular-nums text-white">{formatCountdown(secondsUntil)}</span>
        </>
      )}
    </div>
  );
}

// ── Ship card (single bot) ────────────────────────────────────────────────────

const STATUS_SHIP: Record<BotStatus, { label: string; color: string }> = {
  LIVE:       { label: "ONLINE",   color: "#22c55e" },
  MKT_CLOSED: { label: "DOCKED",   color: "#334155" },
  DOWN:       { label: "DISTRESS", color: "#000000" },
  IDLE:       { label: "STANDBY",  color: "#000000" },
};

// ── Position detail list (Rule 27: server P&L only — no client arithmetic) ────

function EtfPositionList({ positions, accent, strategyPositionCount }: {
  positions: LivePos[];
  accent: string;
  strategyPositionCount: number;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);

  const sgov = positions.find(p => p.symbol === "SGOV");
  const real = positions.filter(p => p.symbol !== "SGOV");

  return (
    <div className="mt-2 space-y-1">
      {strategyPositionCount === 0 && (
        <div className="text-[9px] italic text-white">
          In cash — no open positions
        </div>
      )}
      {real.map(pos => {
        const isLong = pos.qty > 0 || pos.side === "long";
        const plPct  = pos.unrealized_plpc * 100;
        const plUsd  = pos.unrealized_pl;
        const isUp   = plPct >= 0;
        const isOpen = expanded === pos.symbol;
        const plClr  = isUp ? "#16a34a" : "#000000";

        return (
          <div
            key={pos.symbol}
            className="cursor-pointer rounded"
             style={{ background: `${accent}18`, border: `1px solid ${accent}45` }}
            onClick={e => { e.stopPropagation(); setExpanded(isOpen ? null : pos.symbol); }}
          >
            <div className="flex items-center gap-2 px-2 py-1.5">
              <span className="font-bold font-mono text-[10px] text-white w-9 shrink-0">{pos.symbol}</span>
              {isLong ? (
                <span className="text-[7px] font-bold px-1 py-0.5 rounded-sm border shrink-0"
                  style={{ color: "#4ade80", borderColor: "rgba(74,222,128,0.30)", background: "rgba(74,222,128,0.10)" }}>
                  LONG
                </span>
              ) : (
                <span className="text-[7px] font-bold px-1 py-0.5 rounded-sm border shrink-0"
                  style={{ color: "#000000", borderColor: "rgba(15,23,42,0.24)", background: "rgba(15,23,42,0.06)" }}>
                  SHORT
                </span>
              )}
              {pos.market_value != null && (
                <span className="font-mono text-[8px] tabular-nums text-white/70 whitespace-nowrap">
                  SIZE ${pos.market_value.toLocaleString("en-US", { maximumFractionDigits: 0 })}
                </span>
              )}
              <span className="flex-1" />
              <span className="font-mono text-[10px] font-semibold tabular-nums" style={{ color: plClr }}>
                {isUp ? "+" : ""}{plPct.toFixed(1)}%
              </span>
                <span className="font-mono text-[10px] tabular-nums ml-1" style={{ color: plClr }}>
                {plUsd >= 0 ? "+$" : "-$"}{Math.abs(plUsd).toLocaleString("en-US", { maximumFractionDigits: 0 })}
              </span>
            </div>
            {isOpen && (
                  <div className="flex gap-4 px-2 pb-1.5" style={{ borderTop: "1px solid rgba(0,0,0,0.16)" }}>
                <div className="pt-1">
                  <div className="text-[7px] uppercase tracking-widest text-white">Entry</div>
                  <div className="font-mono text-[9px] text-white">
                    ${pos.avg_entry_price?.toFixed(2)}
                  </div>
                </div>
                {pos.market_value != null && (
                  <div className="pt-1">
                    <div className="text-[7px] uppercase tracking-widest text-white">Size</div>
                    <div className="font-mono text-[9px] text-white">
                      ${pos.market_value.toLocaleString("en-US", { maximumFractionDigits: 0 })}
                    </div>
                  </div>
                )}
                {pos.current_price != null && (
                  <div className="pt-1">
                    <div className="text-[7px] uppercase tracking-widest text-white">Now</div>
                    <div className="font-mono text-[9px] text-white">
                      ${pos.current_price.toFixed(2)}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
      {sgov && (
        <div className="flex items-center gap-2 px-2 py-1 rounded"
          style={{ border: "1px solid rgba(71,85,105,0.20)", background: "rgba(71,85,105,0.06)" }}>
           <span className="font-mono text-[10px] w-9 shrink-0" style={{ color: "#000000" }}>SGOV</span>
           <span className="text-[8px] italic" style={{ color: "#000000" }}>cash park</span>
        </div>
      )}
    </div>
  );
}

// ── Ship card ─────────────────────────────────────────────────────────────────

interface ShipCardProps {
  shipName:       string;
  callsign:       string;
  bot:            BotSlice | undefined;
  status:         BotStatus;
  wfStatus?:      string | null;
  accent:         string;
  livePositions?: LivePos[];
  strategyPositionCount?: number;
  posChips?:      { symbol: string; plPct: number }[];
  entryWindow?:    EntryWindow;
}

function elapsedStatus(iso: string | null | undefined) {
  if (!iso) return { label: "LAST SEEN —", color: "#64748b" };
  const age = Math.max(0, Date.now() - new Date(iso).getTime());
  const seconds = Math.floor(age / 1000);
  const label = seconds < 60 ? `${seconds}s ago`
    : seconds < 3600 ? `${Math.floor(seconds / 60)}m ago`
    : `${Math.floor(seconds / 3600)}h ago`;
  const color = seconds <= 300 ? "#16a34a" : "#000000";
  return { label: `UPDATED ${label}`, color };
}

function ShipCard({ shipName, callsign, bot, status, wfStatus, accent, livePositions, strategyPositionCount, posChips = [], entryWindow }: ShipCardProps) {
  const [open, setOpen] = useState(true);
  const st     = STATUS_SHIP[status];
  const pnl    = bot?.pnl     ?? 0;
  const pnlPct = bot?.pnl_pct ?? 0;
  const posClr = pnl >= 0 ? "#16a34a" : "#000000";
  const freshness = elapsedStatus(bot?.last_updated);

  return (
    <div
      className="rounded-2xl overflow-hidden cursor-pointer select-none transition-shadow duration-300"
      style={{
        background:  "rgba(255,255,255,0.12)",
        border:      `1px solid ${accent}55`,
        boxShadow:   open ? `0 14px 34px rgba(15,23,42,0.16), 0 0 28px ${accent}18` : "0 8px 20px rgba(15,23,42,0.10)",
        backdropFilter: "blur(11.2px) saturate(125%)",
        WebkitBackdropFilter: "blur(11.2px) saturate(125%)",
      }}
      onClick={() => setOpen(v => !v)}
    >
      <div style={{ height: 2, background: `linear-gradient(90deg, ${accent}, ${accent}44 50%, transparent)` }} />
      <div className="px-4 pt-3 pb-3">
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          <span className="text-[10px] font-black tracking-[0.15em] uppercase"
            style={{ color: "#000000", textShadow: "none" }}>
            {shipName}
          </span>
          <span className="text-[9px] text-white">{callsign}</span>
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
           <span className="text-[10px] tabular-nums" style={{ color: posClr }}>{fmtDollar(pnl)}</span>
          <WFBadge status={wfStatus} />
        </div>

        <HealthBar wfStatus={wfStatus} />

        {livePositions != null && strategyPositionCount != null
          ? <EtfPositionList positions={livePositions} accent={accent} strategyPositionCount={strategyPositionCount} />
          : posChips.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-x-2 gap-y-0.5">
              {posChips.map(p => {
                const c = p.plPct >= 0 ? "#16a34a" : "#000000";
                return (
                  <span key={p.symbol} className="text-[9px] px-1.5 py-0.5 rounded"
                    style={{ background: `${accent}12`, color: c, border: `1px solid ${accent}22` }}>
                    {p.symbol} {p.plPct >= 0 ? "+" : ""}{p.plPct.toFixed(1)}%
                  </span>
                );
              })}
            </div>
          )
        }

        <EntryWindowCountdown entryWindow={entryWindow} />
      </div>

      {open && (
         <div className="px-4 pb-3" style={{ borderTop: "1px solid rgba(0,0,0,0.16)" }}
          onClick={e => e.stopPropagation()}>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[9px] text-white">
            {bot?.win_rate != null && <span>30D WR <span className="text-cyan-500">{(bot.win_rate * 100).toFixed(1)}%</span></span>}
            <span>POSITIONS <span className="text-cyan-500">{strategyPositionCount ?? "—"}</span></span>
            <span style={{ color: freshness.color === "#16a34a" ? "#16a34a" : "#000000" }}>{freshness.label}</span>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Market + kill-switch chips ────────────────────────────────────────────────

function RegimeChip({ regime }: { regime: string | undefined }) {
  if (!regime || regime === "UNKNOWN") return null;
  const cfgs: Record<string, { color: string; bg: string; border: string }> = {
    CRISIS: { color: "#000000", bg: "rgba(15,23,42,0.06)", border: "rgba(15,23,42,0.20)" },
    BEAR:   { color: "#000000", bg: "rgba(15,23,42,0.06)", border: "rgba(15,23,42,0.20)" },
    BULL:   { color: "#16a34a", bg: "rgba(34,197,94,0.12)", border: "rgba(34,197,94,0.35)" },
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
  fleet, spy, oracle, jerome, total, regime, killTripped,
}: {
  fleet?: Record<string, unknown>;
  spy?: BotSlice; oracle?: BotSlice; jerome?: BotSlice;
  total?: { equity?: number; pnl?: number; pnl_pct?: number };
  regime?: string; killTripped?: boolean | null;
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
      `${Object.keys(fleet ?? {}).filter(k => !["fleet_total", "generated_at", "errors"].includes(k)).length}-BOT FLEET STATUS — ${new Date().toLocaleString()}`,
      `──────────────────────────────────`,
      `FLEET TOTAL  ${fmtEq(total?.equity ?? 0)}  ${fmtPct(total?.pnl_pct ?? 0)}  ${fmtDollar(total?.pnl ?? 0)}`,
      ``,
      `${getBotIdentity("spy_qqq_trend").displayName.padEnd(16)}  ${fmtEq(spy?.equity ?? 0)}  ${fmtPct(spy?.pnl_pct ?? 0)}  ${fmtDollar(spy?.pnl ?? 0)}`,
      `${getBotIdentity("oracle").displayName.padEnd(16)}  ${fmtEq(oracle?.equity ?? 0)}  ${fmtPct(oracle?.pnl_pct ?? 0)}  ${fmtDollar(oracle?.pnl ?? 0)}`,
      `${getBotIdentity("jerome_macro").displayName.padEnd(16)}  ${fmtEq(jerome?.equity ?? 0)}  ${fmtPct(jerome?.pnl_pct ?? 0)}  ${fmtDollar(jerome?.pnl ?? 0)}`,
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
  }, [spy, oracle, jerome, total, regime, killTripped, toast]);

  const items = [
    {
      id: "report",
      icon: "📥",
      label: "Export Full Report",
      sub: "quant-terminal-report-{ts}.txt",
      action: handleExportReport,
      accent: "#000000",
    },
    {
      id: "brief",
      icon: "🧠",
      label: "Claude Brief",
      sub: "Paste into new Claude session",
      action: handleClaudeBrief,
      accent: "#000000",
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
      accent: "#000000",
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
          color: "#000000", cursor: "pointer",
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
            background: "rgba(255,255,255,0.16)",
            border: "1px solid rgba(34,211,238,0.16)",
            boxShadow: "0 16px 48px rgba(0,0,0,0.7), 0 0 0 1px rgba(34,211,238,0.08)",
            backdropFilter: "blur(24px)",
            zIndex: 100,
            overflow: "hidden",
          }}
        >
          <div style={{ padding: "8px 12px 6px", fontSize: 8, letterSpacing: "0.2em", color: "#334155", fontFamily: "monospace", textTransform: "uppercase", borderBottom: "1px solid rgba(100,116,139,0.16)" }}>
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
                <div style={{ fontSize: 9, color: "#64748b", fontFamily: "monospace", marginTop: 1 }}>
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
    fleet, oracle, spy, jerome, total,
    positionsByBot, wfMap,
    regime, killTripped, lastCycle, mktOpen, entryWindows,
  } = useFleetData();

  // Warp pulse: fires whenever lastCycle changes (new data arrived)
  const [warp, setWarp] = useState(false);
  const [, setClock] = useState(Date.now());
  const prevCycle = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (!lastCycle || lastCycle === prevCycle.current) return;
    prevCycle.current = lastCycle;
    setWarp(true);
    const t = setTimeout(() => setWarp(false), 800);
    return () => clearTimeout(t);
  }, [lastCycle]);

  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const spyStatus    = getBotStatus(spy,    mktOpen, false);
  const oraStatus    = getBotStatus(oracle, mktOpen, false);
  const jeromeStatus = getBotStatus(jerome, mktOpen, false);

  const fleetEq  = total?.equity  ?? null;
  const fleetPnl = total?.pnl     ?? null;
  const fleetPct = total?.pnl_pct ?? null;
  const pos = (fleetPnl ?? 0) >= 0;
  const pnlColor = pos ? "#16a34a" : "#000000";

  // 24h P&L from server fleet_total — no client arithmetic
  const pnl24h    = total?.pnl_24h    ?? null;
  const pnl24hPct = total?.pnl_24h_pct ?? null;
  const activeBotCount = Object.keys(fleet ?? {}).filter(
    k => !["fleet_total", "generated_at", "errors"].includes(k),
  ).length;

  const regimeColor = regime === "BULL" ? "#16a34a" : "#000000";

  return (
    <div className="min-h-screen font-mono text-white mobile-home-shell" style={{ background: "#e8eef2", position: "relative" }}>
      <StyleTag />
      <div className="mobile-home-background" aria-hidden="true" />
      <Starfield warp={warp} />

      {/* ── Header ── */}
      <header className="home-command-header">
        <div className="home-command-topline">
          <div className="home-brand">
            <div className="home-brand-mark" aria-hidden="true">✦</div>
            <div>
              <div className="home-brand-kicker">TRADING PLATFORM</div>
              <div className="home-brand-title">FLEET COMMAND</div>
            </div>
          </div>
          <div className="home-header-actions">
            <div className="home-live-state">
              <span className={`home-live-dot ${killTripped ? "is-alert" : ""}`} />
              <span>{killTripped ? "KILL SWITCH" : "SYSTEM ARMED"}</span>
            </div>
            <RegimeChip regime={regime} />
            <ExportDropdown
              fleet={fleet} spy={spy} oracle={oracle} jerome={jerome}
              total={total ?? undefined} regime={regime} killTripped={killTripped}
            />
          </div>
        </div>
        <div className="home-command-summary">
          <div>
            <div className="home-summary-label">{activeBotCount || "—"}-BOT FLEET <span>·</span> TOTAL ASSETS</div>
            <div className="home-equity-value">{fleetEq != null ? fmtEq(fleetEq) : "—"}</div>
          </div>
          <div className="home-performance-grid">
            {fleetPnl != null && (
              <div>
                <div className="home-summary-label">ALL-TIME P&amp;L</div>
                <div className="home-performance-value" style={{ color: pnlColor }}>
                  {fmtDollar(fleetPnl)} <span>({fmtPct(fleetPct ?? 0)})</span>
                </div>
              </div>
            )}
            {total && (
              <div>
                <div className="home-summary-label">LAST 24 HOURS</div>
                <div className="home-performance-value" style={{ color: pnl24h != null && pnl24h >= 0 ? "#16a34a" : "#000000" }}>
                  {pnl24h == null ? "—" : `${pnl24h >= 0 ? "+" : ""}${fmtDollar(pnl24h)}`}
                  {pnl24hPct != null && <span> ({pnl24hPct >= 0 ? "+" : ""}{pnl24hPct.toFixed(2)}%)</span>}
                </div>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* ── Ship cards ── */}
      <div className="mx-auto px-4 pt-4 pb-2 space-y-3" style={{ maxWidth: 600, position: "relative", zIndex: 1 }}>
        <ShipCard shipName={getBotIdentity("spy_qqq_trend").displayName} callsign={getBotIdentity("spy_qqq_trend").icon} bot={spy}    status={spyStatus}
          wfStatus={wfMap.get("spy_qqq_trend")} accent="#fbbf24" livePositions={positionsByBot?.spy_qqq_trend?.positions} strategyPositionCount={positionsByBot?.spy_qqq_trend?.strategy_count} entryWindow={entryWindows?.spy_qqq_trend} />
        <ShipCard shipName={getBotIdentity("oracle").displayName}        callsign={getBotIdentity("oracle").icon}        bot={oracle} status={oraStatus}
          wfStatus={wfMap.get("oracle")}        accent="#a78bfa" livePositions={positionsByBot?.oracle?.positions} strategyPositionCount={positionsByBot?.oracle?.strategy_count} entryWindow={entryWindows?.oracle} />
        <ShipCard shipName={getBotIdentity("jerome_macro").displayName}  callsign={getBotIdentity("jerome_macro").icon}  bot={jerome} status={jeromeStatus}
          wfStatus={wfMap.get("jerome_macro")}  accent="#f87171" livePositions={positionsByBot?.jerome_macro?.positions} strategyPositionCount={positionsByBot?.jerome_macro?.strategy_count} entryWindow={entryWindows?.jerome_macro} />

        {/* Footer */}
        <div className="flex items-center justify-between text-[9px] py-2 px-1"
          style={{ color: "#ffffff" }}>
          <span className="uppercase tracking-widest" style={{ color: pos ? "#16a34a" : "#000000" }}>
            FLEET STATUS: {pos ? "PROFITABLE" : "IN THE RED"}
          </span>
          <button className="font-bold transition-colors hover:opacity-80"
            style={{ color: "#22d3ee" }}
            onClick={() => navigate("/stream")}>
            Full report →
          </button>
        </div>

        {/* ── Life-of-platform equity sparkline ── */}
        <FleetSparkline />

        {/* ── Pulsing capital deployment map ── */}
        <WorldMapWidget />
      </div>

      <div style={{ height: 96 }} />
    </div>
  );
}
