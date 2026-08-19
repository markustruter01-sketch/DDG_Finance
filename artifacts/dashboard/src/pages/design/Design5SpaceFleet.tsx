/**
 * Design 5 — SPACE FLEET (polished)
 * Dark-space vibe · each bot a ship · WF health bar · position cargo payload
 */
import { useState } from "react";
import { useFleetData, getBotStatus, fmtEq, fmtPct, fmtDollar, type BotSlice, type BotStatus } from "@/hooks/useFleetData";

const LABELS = ["🎭", "💻", "🚀", "🕹️", "🛸"];

function DesignNav({ current }: { current: number }) {
  return (
    <div className="sticky top-0 z-50 flex items-center gap-1 px-3 py-2 overflow-x-auto" style={{ background: "#030712", borderBottom: "1px solid #22d3ee15" }}>
      {[1,2,3,4,5].map((n, i) => (
        <a key={n} href={`/design/${n}`}
          className="shrink-0 text-[9px] font-black px-2 py-1 whitespace-nowrap"
          style={{
            color: current === n ? "#22d3ee" : "#0e3340",
            textShadow: current === n ? "0 0 8px #22d3ee88" : undefined,
          }}>
          {LABELS[i]}{n}
        </a>
      ))}
      <a href="/" className="ml-auto shrink-0 text-[9px] text-[#0e2233]">← HOME</a>
    </div>
  );
}

// CSS-only starfield via box-shadow
const STAR_SHADOW = Array.from({ length: 80 }, (_, i) => {
  const x = Math.floor((i * 37 + 13) % 100);
  const y = Math.floor((i * 53 + 7)  % 100);
  const op = 0.2 + (i % 5) * 0.1;
  return `${x}vw ${y}vh 0px 0px rgba(255,255,255,${op.toFixed(1)})`;
}).join(", ");

const WF_HEALTH: Record<string, { pct: number; color: string; label: string }> = {
  PASS:              { pct: 100, color: "#22c55e", label: "SHIELDS 100%" },
  MARGINAL:          { pct: 55,  color: "#f59e0b", label: "SHIELDS 55%"  },
  FAIL:              { pct: 15,  color: "#ef4444", label: "SHIELDS 15%"  },
  INSUFFICIENT_DATA: { pct: 0,   color: "#64748b", label: "NO DATA"      },
};

const STATUS_SHIP: Record<BotStatus, { label: string; color: string; glow: string }> = {
  LIVE:       { label: "ONLINE",   color: "#22c55e", glow: "#22c55e66" },
  MKT_CLOSED: { label: "DOCKED",   color: "#64748b", glow: "transparent" },
  DOWN:       { label: "DISTRESS", color: "#ef4444", glow: "#ef444466" },
  IDLE:       { label: "STANDBY",  color: "#eab308", glow: "#eab30866" },
};

function HealthBar({ wfStatus }: { wfStatus: string | null | undefined }) {
  const h = WF_HEALTH[wfStatus ?? ""] ?? WF_HEALTH["INSUFFICIENT_DATA"];
  return (
    <div className="flex items-center gap-2">
      <div className="text-[8px] uppercase tracking-widest text-slate-600 shrink-0 w-14">SHIELDS</div>
      <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: "#0f172a" }}>
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{
            width:      `${h.pct}%`,
            background: h.color,
            boxShadow:  `0 0 6px ${h.color}`,
          }}
        />
      </div>
      <span className="text-[8px] tabular-nums shrink-0" style={{ color: h.color }}>{h.label}</span>
    </div>
  );
}

interface ShipProps {
  shipName:  string;
  callsign:  string;
  bot:       BotSlice | undefined;
  status:    BotStatus;
  wfStatus?: string | null;
  accent:    string;
  cargo?:    string[];
}

function ShipCard({ shipName, callsign, bot, status, wfStatus, accent, cargo = [] }: ShipProps) {
  const [open, setOpen] = useState(false);
  const st     = STATUS_SHIP[status];
  const pnl    = bot?.pnl     ?? 0;
  const pnlPct = bot?.pnl_pct ?? 0;
  const posClr = pnl >= 0 ? "#4ade80" : "#f87171";

  return (
    <div
      className="rounded-2xl overflow-hidden cursor-pointer select-none"
      style={{
        background:  "rgba(8,12,24,0.97)",
        border:      `1px solid ${accent}35`,
        boxShadow:   open ? `0 0 30px ${accent}18, 0 0 60px ${accent}08` : "none",
        transition:  "box-shadow 0.3s",
      }}
      onClick={() => setOpen(v => !v)}
    >
      {/* Ship hull stripe */}
      <div style={{ height: 2, background: `linear-gradient(90deg, ${accent}, ${accent}44 50%, transparent)` }} />

      <div className="px-4 pt-3 pb-3">
        {/* Row 1: ship name + status */}
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          <span className="text-[10px] font-black tracking-[0.15em] uppercase" style={{ color: accent, textShadow: `0 0 8px ${accent}66` }}>
            {shipName}
          </span>
          <span className="text-[9px] text-slate-600">{callsign}</span>
          <div className="ml-auto flex items-center gap-1.5">
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: st.color, boxShadow: `0 0 6px ${st.glow}`, flexShrink: 0 }} />
            <span className="text-[8px] font-bold tracking-widest uppercase" style={{ color: st.color }}>{st.label}</span>
          </div>
        </div>

        {/* Row 2: equity + P&L */}
        <div className="flex items-baseline gap-2 mb-2">
          <span className="text-[22px] font-bold tabular-nums text-white leading-none">{fmtEq(bot?.equity ?? 0)}</span>
          <span className="text-[13px] font-semibold tabular-nums" style={{ color: posClr }}>{fmtPct(pnlPct)}</span>
          <span className="text-[10px] tabular-nums" style={{ color: `${posClr}88` }}>{fmtDollar(pnl)}</span>
        </div>

        {/* WF health bar */}
        <HealthBar wfStatus={wfStatus} />

        {/* Cargo payload (position tickers) */}
        {cargo.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-x-2 gap-y-0.5">
            {cargo.map((sym) => (
              <span key={sym} className="text-[9px] px-1.5 py-0.5 rounded" style={{ background: `${accent}15`, color: `${accent}cc`, border: `1px solid ${accent}25` }}>
                {sym}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Expanded */}
      {open && (
        <div className="px-4 pb-3" style={{ borderTop: "1px solid rgba(255,255,255,0.05)" }} onClick={e => e.stopPropagation()}>
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

export default function Design5SpaceFleet() {
  const { oracle, spy, jerome, total, wfMap, positionsByBot, regime, killTripped, mktOpen } = useFleetData();
  const spyPos = positionsByBot?.spy_qqq_trend?.positions ?? [];
  const oraclePos = positionsByBot?.oracle?.positions ?? [];

  const spyStatus  = getBotStatus(spy,    mktOpen, false);
  const oraStatus  = getBotStatus(oracle, mktOpen, false);
  const jerStatus  = getBotStatus(jerome, mktOpen, false);

  const fleetEq  = total?.equity  ?? null;
  const fleetPnl = total?.pnl     ?? null;
  const fleetPct = total?.pnl_pct ?? null;
  const pos = (fleetPnl ?? 0) >= 0;
  const pnlColor = pos ? "#4ade80" : "#f87171";

  const oraWF  = wfMap.get("oracle");
  const spyWF  = wfMap.get("spy_qqq_trend");
  const jerWF  = wfMap.get("jerome_macro");

  const curlyStatus: BotStatus = jerStatus;

  const regimeColor = regime === "CRISIS" ? "#ef4444" : regime === "BEAR" ? "#f97316" : "#22c55e";

  return (
    <div className="min-h-screen font-mono text-white" style={{ background: "#030712", position: "relative", overflow: "hidden" }}>
      {/* CSS starfield */}
      <div style={{ position: "fixed", inset: 0, boxShadow: STAR_SHADOW, pointerEvents: "none" }} />

      <DesignNav current={5} />

      {/* Fleet header */}
      <div
        className="sticky top-9 z-10 flex items-center gap-3 px-4 py-3 flex-wrap"
        style={{ background: "rgba(3,7,18,0.92)", borderBottom: "1px solid rgba(34,211,238,0.12)", backdropFilter: "blur(8px)" }}
      >
        <div>
          <div className="text-[8px] uppercase tracking-[0.2em] text-slate-700 mb-0.5">STOOGE FLEET · TOTAL ASSETS</div>
          <div className="flex items-baseline gap-2">
            <span className="text-[22px] font-bold tabular-nums text-white" style={{ textShadow: "0 0 20px #22d3ee25" }}>
              {fleetEq != null ? fmtEq(fleetEq) : "—"}
            </span>
            {fleetPnl != null && (
              <span className="text-[13px] font-semibold tabular-nums" style={{ color: pnlColor }}>
                {fmtDollar(fleetPnl)} ({fmtPct(fleetPct ?? 0)})
              </span>
            )}
          </div>
        </div>

        <div className="ml-auto flex items-center gap-3">
          {regime && (
            <span className="text-[9px] font-black tracking-widest uppercase px-2 py-1 rounded-full"
              style={{ color: regimeColor, border: `1px solid ${regimeColor}40`, background: `${regimeColor}12` }}>
              {regime}
            </span>
          )}
          {killTripped != null && (
            <div className="flex items-center gap-1.5">
              <div style={{ width: 7, height: 7, borderRadius: "50%", background: killTripped ? "#ef4444" : "#22c55e", boxShadow: killTripped ? "0 0 8px #ef4444" : "0 0 5px #22c55e55" }} />
              <span className="text-[8px] uppercase tracking-widest" style={{ color: killTripped ? "#ef4444" : "#475569" }}>
                {killTripped ? "KS TRIPPED" : "ARMED"}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Ship cards */}
      <div className="mx-auto px-4 pt-4 pb-2 space-y-3" style={{ maxWidth: 600, position: "relative", zIndex: 1 }}>

        <ShipCard
          shipName="SPY-HAWK"
          callsign="Moe · SPY/QQQ"
          bot={spy}
          status={spyStatus}
          wfStatus={spyWF}
          accent="#fbbf24"
          cargo={spyPos.map(p => `${p.symbol} ${(p.unrealized_plpc * 100).toFixed(1)}%`)}
        />

        <ShipCard
          shipName="ORACLE-7"
          callsign="Larry · Oracle"
          bot={oracle}
          status={oraStatus}
          wfStatus={oraWF}
          accent="#a78bfa"
          cargo={oraclePos.map(p => `${p.symbol} ${(p.unrealized_plpc * 100).toFixed(1)}%`)}
        />

        {/* Curly dual ship card */}
        <div className="rounded-2xl overflow-hidden" style={{ border: "1px solid #f8717135", background: "rgba(8,12,24,0.97)", boxShadow: "none" }}>
          <div style={{ height: 2, background: "linear-gradient(90deg, #f87171cc, #f8717144 50%, transparent)" }} />
          <div className="px-4 pt-3 pb-1">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-[10px] font-black tracking-[0.15em] uppercase" style={{ color: "#f87171", textShadow: "0 0 8px #f8717166" }}>
                TITAN-CLASS
              </span>
              <span className="text-[9px] text-slate-600">Curly · Jerome</span>
            </div>
            {([
              { name: "MACRO-J", label: "Curly (Jerome)", bot: jerome, status: jerStatus, wf: jerWF, isADX: false },
            ] as const).map(({ name, label, bot, status, wf }) => {
              const pnl = bot?.pnl ?? 0;
              const posC = pnl >= 0 ? "#4ade80" : "#f87171";
              const st = STATUS_SHIP[status];
              const wfH = WF_HEALTH[wf ?? ""] ?? WF_HEALTH["INSUFFICIENT_DATA"];
              return (
                <div key={name} className="mb-3 pl-3" style={{ borderLeft: "1px solid #f8717130" }}>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[9px] font-black" style={{ color: "#f87171" }}>{name}</span>
                    <span className="text-[8px] text-slate-600">{label}</span>
                    <div style={{ width: 5, height: 5, borderRadius: "50%", background: st.color, boxShadow: `0 0 4px ${st.color}`, marginLeft: "auto" }} />
                    <span className="text-[8px]" style={{ color: st.color }}>{st.label}</span>
                  </div>
                  <div className="flex items-baseline gap-2 mb-1">
                    <span className="text-[17px] font-bold tabular-nums text-white">{fmtEq(bot?.equity ?? 0)}</span>
                    <span className="text-[12px] tabular-nums" style={{ color: posC }}>{fmtPct(bot?.pnl_pct ?? 0)}</span>
                    <span className="text-[10px] tabular-nums" style={{ color: `${posC}88` }}>{fmtDollar(pnl)}</span>
                  </div>
                  {/* Mini health bar */}
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
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between text-[9px] py-2 px-1" style={{ borderTop: "1px solid rgba(255,255,255,0.04)", color: "#1e3a5f" }}>
          <span className="uppercase tracking-widest">FLEET STATUS: {pos ? "PROFITABLE" : "IN THE RED"}</span>
          {total?.win_rate != null && (
            <span>30D WR <span className="text-cyan-900">{(total.win_rate * 100).toFixed(1)}%</span></span>
          )}
        </div>
      </div>
      <div style={{ height: 96 }} />
    </div>
  );
}
