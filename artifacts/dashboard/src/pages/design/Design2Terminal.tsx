/**
 * Design 2 — RETRO TERMINAL
 * CRT green-phosphor · scanlines · ASCII borders · blinking cursor
 */
import { useState } from "react";
import { useFleetData, getBotStatus, fmtEq, fmtPct, fmtDollar, type BotSlice, type BotStatus } from "@/hooks/useFleetData";

const THEMES = [
  { n: 1 }, { n: 2 }, { n: 3 }, { n: 4 }, { n: 5 },
];
const LABELS = ["🎭 VAUD", "💻 TERM", "🚀 MISS", "🕹️ ARC", "🛸 FLEET"];

function DesignNav({ current }: { current: number }) {
  return (
    <div className="sticky top-0 z-50 flex items-center gap-1 px-3 py-2 overflow-x-auto" style={{ background: "#000", borderBottom: "1px solid #00331a" }}>
      {THEMES.map((t, i) => (
        <a key={t.n} href={`/design/${t.n}`}
          className="shrink-0 text-[9px] font-bold px-2 py-1 rounded whitespace-nowrap"
          style={{ color: current === t.n ? "#33ff33" : "#004d1a", background: current === t.n ? "#001a0a" : "transparent" }}>
          {LABELS[i]}
        </a>
      ))}
      <a href="/" className="ml-auto shrink-0 text-[9px]" style={{ color: "#003b15" }}>← HOME</a>
    </div>
  );
}

// Scanlines overlay via CSS
const SCANLINES_STYLE: React.CSSProperties = {
  backgroundImage: "repeating-linear-gradient(0deg, rgba(0,0,0,0.25) 0px, rgba(0,0,0,0.25) 1px, transparent 1px, transparent 3px)",
  pointerEvents: "none",
  position: "fixed",
  inset: 0,
  zIndex: 10,
};

const STATUS_SYM: Record<BotStatus, string> = {
  LIVE:       "[ ACTIVE  ]",
  MKT_CLOSED: "[ MKT CLO ]",
  DOWN:       "[ FAULT!  ]",
  IDLE:       "[ IDLE    ]",
};

const STATUS_CLR: Record<BotStatus, string> = {
  LIVE: "#33ff33", MKT_CLOSED: "#336633", DOWN: "#ff4444", IDLE: "#cccc00",
};

function AsciiBox({ children, glow = false }: { children: React.ReactNode; glow?: boolean }) {
  return (
    <div style={{
      border: "1px solid #00550d",
      background: "#000d02",
      boxShadow: glow ? "0 0 12px #33ff3340, inset 0 0 8px #33ff3308" : "none",
    }}>
      {children}
    </div>
  );
}

interface TermBotProps {
  tag:      string;
  name:     string;
  bot:      BotSlice | undefined;
  status:   BotStatus;
  wfStatus?: string | null;
}

function TermBotCard({ tag, name, bot, status, wfStatus }: TermBotProps) {
  const [open, setOpen] = useState(false);
  const pnl    = bot?.pnl     ?? 0;
  const pnlPct = bot?.pnl_pct ?? 0;
  const pnlStr = `${pnl >= 0 ? "+" : ""}${fmtEq(Math.abs(pnl))}`;
  const sym    = STATUS_SYM[status];
  const clr    = STATUS_CLR[status];

  return (
    <AsciiBox glow={status === "LIVE"}>
      <div className="cursor-pointer select-none" onClick={() => setOpen(v => !v)}>
        <div className="flex items-center justify-between px-3 py-1.5" style={{ borderBottom: "1px solid #00550d" }}>
          <span className="text-[10px] font-bold" style={{ color: "#33ff33" }}>
            ┌─ {tag}: {name.toUpperCase()} ─
          </span>
          <span className="text-[9px]" style={{ color: clr }}>{sym}</span>
        </div>
        <div className="px-3 py-2">
          <div className="flex items-baseline gap-3">
            <span className="text-[20px] font-black tabular-nums" style={{ color: "#33ff33", textShadow: "0 0 8px #33ff3360" }}>
              {fmtEq(bot?.equity ?? 0)}
            </span>
            <span className="text-[13px] font-bold tabular-nums" style={{ color: pnl >= 0 ? "#33ff33" : "#ff4444" }}>
              {pnl >= 0 ? "▲" : "▼"}{fmtPct(Math.abs(pnlPct)).replace("+", "")}
            </span>
            <span className="text-[11px] tabular-nums" style={{ color: pnl >= 0 ? "#006622" : "#660000" }}>
              {pnlStr}
            </span>
          </div>
          {wfStatus && (
            <div className="text-[9px] mt-1" style={{ color: "#006622" }}>
              WF_STATUS: [{wfStatus.toUpperCase().replace("_", "-")}]
            </div>
          )}
        </div>
      </div>
      {open && (
        <div className="px-3 pb-2" style={{ borderTop: "1px solid #004d1a" }}>
          <div className="text-[9px] mt-2 space-y-0.5" style={{ color: "#006622" }}>
            {bot?.win_rate != null && <div>&gt; WIN_RATE_30D: {(bot.win_rate * 100).toFixed(1)}%</div>}
            {bot?.positions != null && <div>&gt; OPEN_POSITIONS: {bot.positions}</div>}
            {bot?.last_updated && <div>&gt; LAST_UPDATE: {new Date(bot.last_updated).toISOString().slice(0, 19)}Z</div>}
            <div>&gt; <span className="animate-pulse" style={{ color: "#33ff33" }}>_</span></div>
          </div>
        </div>
      )}
    </AsciiBox>
  );
}

export default function Design2Terminal() {
  const { oracle, spy, jerome, total, wfMap, regime, killTripped, mktOpen } = useFleetData();

  const spyStatus  = getBotStatus(spy,    mktOpen, false);
  const oraStatus  = getBotStatus(oracle, mktOpen, false);
  const jerStatus  = getBotStatus(jerome, mktOpen, false);

  const fleetEq  = total?.equity  ?? null;
  const fleetPnl = total?.pnl     ?? null;
  const fleetPct = total?.pnl_pct ?? null;
  const pos = (fleetPnl ?? 0) >= 0;

  return (
    <div className="min-h-screen font-mono" style={{ background: "#000802", color: "#33ff33" }}>
      {/* Scanlines overlay */}
      <div style={SCANLINES_STYLE} />

      <DesignNav current={2} />

      {/* Header */}
      <div className="px-4 pt-4 pb-3" style={{ borderBottom: "1px solid #00550d" }}>
        <div className="text-[9px] mb-1" style={{ color: "#006622" }}>
          STOOGE QUANT TERMINAL v4.2 ·{" "}
          <span style={{ color: killTripped ? "#ff4444" : "#33ff33" }}>
            {killTripped ? "⚠ KILL_SWITCH=TRIPPED" : "KILL_SWITCH=ARMED"}
          </span>
          {" "}·{" "}
          REGIME=[{regime ?? "UNKNOWN"}]
        </div>
        <div className="flex items-baseline gap-3">
          <span className="text-[24px] font-black tabular-nums" style={{ color: "#33ff33", textShadow: "0 0 10px #33ff3355" }}>
            {fleetEq != null ? fmtEq(fleetEq) : "------"}
          </span>
          {fleetPnl != null && (
            <span className="text-[14px] font-bold tabular-nums" style={{ color: pos ? "#33ff33" : "#ff4444" }}>
              {pos ? "▲" : "▼"}{fmtPct(Math.abs(fleetPct ?? 0)).replace("+", "")} ({fmtDollar(fleetPnl)})
            </span>
          )}
        </div>
        <div className="text-[9px] mt-1" style={{ color: "#004d1a" }}>
          FLEET_EQUITY_REPORT · DATA SOURCE: /FLEET/EQUITY
        </div>
      </div>

      {/* Bot cards */}
      <div className="mx-auto px-4 pt-4 pb-2 space-y-3" style={{ maxWidth: 600 }}>
        <TermBotCard tag="BOT1" name="Moe · SPY/QQQ"  bot={spy}    status={spyStatus}  wfStatus={wfMap.get("spy_qqq_trend")} />
        <TermBotCard tag="BOT2" name="Larry · Oracle"  bot={oracle} status={oraStatus}  wfStatus={wfMap.get("oracle")} />

        {/* Curly dual card */}
        <AsciiBox>
          <div className="px-3 py-1.5" style={{ borderBottom: "1px solid #00550d" }}>
            <span className="text-[10px] font-bold" style={{ color: "#33ff33" }}>┌─ BOT3: CURLY · JEROME ─</span>
          </div>
          {([
            { tag: "JEROME", label: "CURLY", bot: jerome, status: jerStatus, wf: wfMap.get("jerome_macro"), isADX: false },
          ] as const).map(({ tag, label, bot, status, wf }) => {
            const pnl = bot?.pnl ?? 0;
            const clr = STATUS_CLR[status];
            return (
              <div key={tag} className="px-3 py-2" style={{ borderBottom: "1px solid #001a08" }}>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[9px]" style={{ color: "#006622" }}>{label}:</span>
                  <span className="text-[9px]" style={{ color: clr }}>{STATUS_SYM[status]}</span>
                  {wf && <span className="text-[9px] ml-auto" style={{ color: "#004d1a" }}>WF:[{wf}]</span>}
                </div>
                <div className="flex items-baseline gap-3">
                  <span className="text-[17px] font-black tabular-nums" style={{ color: "#33ff33" }}>{fmtEq(bot?.equity ?? 0)}</span>
                  <span className="text-[11px] tabular-nums" style={{ color: pnl >= 0 ? "#33ff33" : "#ff4444" }}>
                    {pnl >= 0 ? "▲" : "▼"}{fmtPct(Math.abs(bot?.pnl_pct ?? 0)).replace("+", "")}
                  </span>
                  <span className="text-[10px] tabular-nums" style={{ color: "#006622" }}>{fmtDollar(pnl)}</span>
                </div>
              </div>
            );
          })}
        </AsciiBox>

        {/* Footer */}
        <div className="text-[9px] text-center py-2" style={{ color: "#004d1a" }}>
          END OF REPORT · PRESS ANY KEY TO CONTINUE <span className="animate-pulse">▌</span>
        </div>
      </div>
      <div style={{ height: 96 }} />
    </div>
  );
}
