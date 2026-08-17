/**
 * Design 3 — MISSION CONTROL
 * NASA flight-console · GO/NO-GO status lights · subsystem telemetry panels
 */
import { useState } from "react";
import { useFleetData, getBotStatus, fmtEq, fmtPct, fmtDollar, type BotSlice, type BotStatus } from "@/hooks/useFleetData";

const LABELS = ["🎭", "💻", "🚀", "🕹️", "🛸"];

function DesignNav({ current }: { current: number }) {
  return (
    <div className="sticky top-0 z-50 flex items-center gap-1 px-3 py-2 overflow-x-auto" style={{ background: "#060d1f", borderBottom: "1px solid #0ea5e933" }}>
      {[1,2,3,4,5].map((n, i) => (
        <a key={n} href={`/design/${n}`}
          className="shrink-0 text-[9px] font-black px-2 py-1 rounded tracking-widest"
          style={{ color: current === n ? "#fff" : "#1e3a5f", background: current === n ? "#0ea5e9" : "transparent" }}>
          {LABELS[i]} {n}
        </a>
      ))}
      <a href="/" className="ml-auto shrink-0 text-[9px] text-blue-950">← HOME</a>
    </div>
  );
}

const STATUS_LIGHT: Record<BotStatus, { label: string; color: string; ring: string }> = {
  LIVE:       { label: "GO",       color: "#22c55e", ring: "#22c55e55" },
  MKT_CLOSED: { label: "STANDBY", color: "#64748b", ring: "#64748b33" },
  DOWN:       { label: "ABORT",   color: "#ef4444", ring: "#ef444455" },
  IDLE:       { label: "HOLD",    color: "#eab308", ring: "#eab30855" },
};

function StatusLight({ status, large }: { status: BotStatus; large?: boolean }) {
  const s = STATUS_LIGHT[status];
  const sz = large ? 20 : 14;
  return (
    <div className="flex items-center gap-2">
      <div style={{
        width: sz, height: sz, borderRadius: "50%",
        background: s.color,
        boxShadow: `0 0 ${large ? 14 : 8}px ${s.color}`,
        border: `2px solid ${s.ring}`,
        flexShrink: 0,
      }} />
      <span className="text-[9px] font-black tracking-widest uppercase" style={{ color: s.color }}>
        {s.label}
      </span>
    </div>
  );
}

interface MCBotProps {
  mission: string;
  subsys:  string;
  bot:     BotSlice | undefined;
  status:  BotStatus;
  wfStatus?: string | null;
  accent:  string;
}

function MCBotPanel({ mission, subsys, bot, status, wfStatus, accent }: MCBotProps) {
  const [open, setOpen] = useState(false);
  const pnl    = bot?.pnl     ?? 0;
  const pnlPct = bot?.pnl_pct ?? 0;
  const posClr = pnl >= 0 ? "#22c55e" : "#ef4444";

  return (
    <div
      className="rounded-xl overflow-hidden cursor-pointer select-none"
      style={{
        background:   "#060d1f",
        border:       `1px solid ${accent}30`,
        boxShadow:    open ? `0 0 20px ${accent}20` : "none",
      }}
      onClick={() => setOpen(v => !v)}
    >
      {/* Panel header bar */}
      <div className="flex items-center justify-between px-4 py-2" style={{ background: `${accent}15`, borderBottom: `1px solid ${accent}30` }}>
        <div className="flex items-center gap-2">
          <span className="text-[9px] font-black tracking-widest text-slate-500">{mission}</span>
          <span className="text-[10px] font-black tracking-widest" style={{ color: accent }}>{subsys}</span>
        </div>
        <StatusLight status={status} />
      </div>

      {/* Telemetry readings */}
      <div className="px-4 py-3">
        <div className="grid grid-cols-3 gap-3">
          <div>
            <div className="text-[8px] uppercase tracking-widest text-slate-600 mb-1">EQUITY</div>
            <div className="text-[16px] font-black tabular-nums text-white leading-none">{fmtEq(bot?.equity ?? 0)}</div>
          </div>
          <div>
            <div className="text-[8px] uppercase tracking-widest text-slate-600 mb-1">P/L%</div>
            <div className="text-[16px] font-black tabular-nums leading-none" style={{ color: posClr }}>{fmtPct(pnlPct)}</div>
          </div>
          <div>
            <div className="text-[8px] uppercase tracking-widest text-slate-600 mb-1">P/L $</div>
            <div className="text-[14px] font-bold tabular-nums leading-none" style={{ color: `${posClr}cc` }}>{fmtDollar(pnl)}</div>
          </div>
        </div>

        {wfStatus && (
          <div className="mt-2 flex items-center gap-2">
            <div className="text-[8px] uppercase tracking-widest text-slate-600">WF STATUS</div>
            <div
              className="text-[8px] font-black tracking-widest px-2 py-0.5 rounded"
              style={{
                color: wfStatus === "PASS" ? "#22c55e" : wfStatus === "MARGINAL" ? "#f59e0b" : wfStatus === "FAIL" ? "#ef4444" : "#64748b",
                background: "#ffffff0a",
                border: "1px solid currentColor",
              }}
            >
              {wfStatus.toUpperCase().replace("_", " ")}
            </div>
          </div>
        )}
      </div>

      {open && (
        <div className="px-4 pb-3" style={{ borderTop: `1px solid ${accent}20` }} onClick={e => e.stopPropagation()}>
          <div className="mt-3 grid grid-cols-2 gap-2 text-[9px]">
            {bot?.win_rate != null && (
              <div>
                <span className="text-slate-600 uppercase tracking-widest">WIN RATE </span>
                <span style={{ color: accent }}>{(bot.win_rate * 100).toFixed(1)}%</span>
              </div>
            )}
            {bot?.positions != null && (
              <div>
                <span className="text-slate-600 uppercase tracking-widest">POSITIONS </span>
                <span style={{ color: accent }}>{bot.positions}</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function Design3MissionControl() {
  const { oracle, spy, jerome, total, wfMap, regime, killTripped, mktOpen } = useFleetData();

  const spyStatus  = getBotStatus(spy,    mktOpen, false);
  const oraStatus  = getBotStatus(oracle, mktOpen, false);
  const jerStatus  = getBotStatus(jerome, mktOpen, false);

  const fleetEq  = total?.equity  ?? null;
  const fleetPct = total?.pnl_pct ?? null;
  const fleetPnl = total?.pnl     ?? null;
  const pos = (fleetPnl ?? 0) >= 0;
  const regimeStatus: BotStatus = regime === "CRISIS" ? "DOWN" : regime === "BEAR" ? "IDLE" : "LIVE";

  return (
    <div className="min-h-screen font-mono" style={{ background: "#060d1f", color: "white" }}>
      <DesignNav current={3} />

      {/* Mission header */}
      <div className="px-4 py-4" style={{ borderBottom: "1px solid #0ea5e920", background: "#040a17" }}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-[8px] uppercase tracking-[0.2em] text-sky-900 mb-1">STOOGE FLEET · MISSION CONTROL</div>
            <div className="flex items-baseline gap-3">
              <span className="text-[26px] font-black tabular-nums text-white" style={{ textShadow: "0 0 20px #0ea5e930" }}>
                {fleetEq != null ? fmtEq(fleetEq) : "—"}
              </span>
              {fleetPnl != null && (
                <span className="text-[14px] font-bold tabular-nums" style={{ color: pos ? "#22c55e" : "#ef4444" }}>
                  {fmtPct(fleetPct ?? 0)} · {fmtDollar(fleetPnl)}
                </span>
              )}
            </div>
          </div>
          <div className="flex flex-col gap-2 items-end">
            <div className="flex items-center gap-2">
              <span className="text-[8px] text-slate-600 uppercase tracking-widest">MARKET</span>
              <StatusLight status={regimeStatus} />
            </div>
            {killTripped != null && (
              <div className="flex items-center gap-2">
                <span className="text-[8px] text-slate-600 uppercase tracking-widest">KILL SW</span>
                <StatusLight status={killTripped ? "DOWN" : "LIVE"} />
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Subsystem panels */}
      <div className="mx-auto px-4 pt-4 pb-2 space-y-3" style={{ maxWidth: 600 }}>
        <MCBotPanel mission="SUBSYS-A" subsys="MOE · SPY/QQQ"    bot={spy}    status={spyStatus}  wfStatus={wfMap.get("spy_qqq_trend")} accent="#fbbf24" />
        <MCBotPanel mission="SUBSYS-B" subsys="LARRY · ORACLE"   bot={oracle} status={oraStatus}  wfStatus={wfMap.get("oracle")}        accent="#a78bfa" />

        {/* Curly dual panel */}
        <div className="rounded-xl overflow-hidden" style={{ border: "1px solid #f8717130", background: "#060d1f" }}>
          <div className="flex items-center justify-between px-4 py-2" style={{ background: "#f8717110", borderBottom: "1px solid #f8717130" }}>
            <span className="text-[10px] font-black tracking-widest" style={{ color: "#f87171" }}>CURLY · JEROME</span>
            <StatusLight status={jerStatus} />
          </div>
          {([
            { label: "SUBSYS-C · CURLY (JEROME)", bot: jerome, status: jerStatus, wf: wfMap.get("jerome_macro"), isADX: false },
          ] as const).map(({ label, bot, status, wf }) => {
            const pnl = bot?.pnl ?? 0;
            const posClr = pnl >= 0 ? "#22c55e" : "#ef4444";
            return (
              <div key={label} className="px-4 py-3" style={{ borderBottom: "1px solid #f8717115" }}>
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-[8px] text-slate-600 uppercase tracking-widest">{label}</span>
                  <StatusLight status={status} />
                  {wf && <span className="text-[8px] text-slate-700 ml-auto">{wf}</span>}
                </div>
                <div className="flex items-baseline gap-3">
                  <span className="text-[16px] font-black text-white tabular-nums">{fmtEq(bot?.equity ?? 0)}</span>
                  <span className="text-[13px] font-bold tabular-nums" style={{ color: posClr }}>{fmtPct(bot?.pnl_pct ?? 0)}</span>
                  <span className="text-[11px] tabular-nums" style={{ color: `${posClr}99` }}>{fmtDollar(pnl)}</span>
                </div>
              </div>
            );
          })}
        </div>

        {/* Flight status footer */}
        <div className="flex items-center justify-between text-[9px] py-2 px-1">
          <span className="text-slate-700 uppercase tracking-widest">FLEET STATUS: {pos ? "NOMINAL" : "DEGRADED"}</span>
          <span className="text-slate-700">REGIME: {regime ?? "UNKNOWN"}</span>
        </div>
      </div>
      <div style={{ height: 96 }} />
    </div>
  );
}
