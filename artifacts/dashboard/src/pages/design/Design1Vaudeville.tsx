/**
 * Design 1 — STOOGES VAUDEVILLE
 * Warm stage-lighting palette · Bot performer cards · Applause / pie-in-face P&L
 */
import { useState } from "react";
import { useFleetData, getBotStatus, fmtEq, fmtPct, fmtDollar, type BotSlice, type BotStatus } from "@/hooks/useFleetData";

const THEMES = [
  { n: 1, label: "🎭 VAUDEVILLE" },
  { n: 2, label: "💻 TERMINAL"  },
  { n: 3, label: "🚀 MISSION"   },
  { n: 4, label: "🕹️ ARCADE"    },
  { n: 5, label: "🛸 FLEET"     },
];

function DesignNav({ current }: { current: number }) {
  return (
    <div className="sticky top-0 z-50 flex items-center gap-1 px-3 py-2 overflow-x-auto" style={{ background: "#000" }}>
      {THEMES.map((t) => (
        <a
          key={t.n}
          href={`/design/${t.n}`}
          className="shrink-0 text-[9px] font-bold px-2 py-1 rounded whitespace-nowrap"
          style={{
            background: current === t.n ? "#92400e" : "transparent",
            color: current === t.n ? "#fef3c7" : "#78716c",
          }}
        >
          {t.label}
        </a>
      ))}
      <a href="/" className="ml-auto shrink-0 text-[9px] text-stone-600">← Home</a>
    </div>
  );
}

const STATUSES: Record<BotStatus, { emoji: string; label: string; color: string }> = {
  LIVE:       { emoji: "🎬", label: "ON STAGE",    color: "#86efac" },
  MKT_CLOSED: { emoji: "🌙", label: "DARK NIGHT",  color: "#a8a29e" },
  DOWN:       { emoji: "💥", label: "BOTCHED",     color: "#fca5a5" },
  IDLE:       { emoji: "😴", label: "SITTING OUT", color: "#fde68a" },
};

const REGIME_LABEL: Record<string, { emoji: string; label: string }> = {
  BULL:   { emoji: "🎺", label: "BULL MARKET"  },
  BEAR:   { emoji: "💀", label: "BEAR HOUSE"   },
  CRISIS: { emoji: "🚨", label: "PANIC SCENE"  },
};

interface VBotProps {
  emoji:    string;
  name:     string;
  role:     string;
  bot:      BotSlice | undefined;
  status:   BotStatus;
  wfStatus?: string | null;
  accent:   string;
}

function VBotCard({ emoji, name, role, bot, status, wfStatus, accent }: VBotProps) {
  const [open, setOpen] = useState(false);
  const st = STATUSES[status];
  const pnl    = bot?.pnl     ?? 0;
  const pnlPct = bot?.pnl_pct ?? 0;
  const positive = pnl >= 0;

  return (
    <div
      className="rounded-2xl border-2 overflow-hidden cursor-pointer select-none"
      style={{
        background:  "rgba(28,15,5,0.95)",
        borderColor: open ? accent : "#78350f",
        boxShadow:   `0 4px 20px rgba(0,0,0,0.5)`,
      }}
      onClick={() => setOpen(v => !v)}
    >
      {/* Stage spotlight stripe */}
      <div style={{ height: 3, background: `linear-gradient(90deg, ${accent}, #78350f 60%, transparent)` }} />

      <div className="p-4">
        <div className="flex items-center gap-3">
          <span className="text-4xl leading-none">{emoji}</span>
          <div className="flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[16px] font-black text-amber-100">{name}</span>
              <span className="text-[9px] uppercase tracking-widest text-amber-700">{role}</span>
              <span
                className="text-[9px] font-bold px-1.5 py-0.5 rounded"
                style={{ color: st.color, background: `${st.color}20` }}
              >
                {st.emoji} {st.label}
              </span>
            </div>
            <div className="flex items-baseline gap-2 mt-1">
              <span className="text-[20px] font-black text-amber-50 tabular-nums">{fmtEq(bot?.equity ?? 0)}</span>
              <span className="text-[13px] font-semibold tabular-nums" style={{ color: positive ? "#86efac" : "#fca5a5" }}>
                {fmtPct(pnlPct)}
              </span>
            </div>
          </div>
          <div className="text-right shrink-0">
            <div className="text-[18px]">{positive ? "👏" : "🥧"}</div>
            <div className="text-[10px] font-semibold tabular-nums mt-0.5" style={{ color: positive ? "#86efac" : "#fca5a5" }}>
              {fmtDollar(pnl)}
            </div>
          </div>
        </div>
      </div>

      {open && (
        <div className="px-4 pb-4" style={{ borderTop: "1px solid #78350f" }} onClick={e => e.stopPropagation()}>
          <div className="mt-3 flex gap-3 text-[10px] text-amber-800 flex-wrap">
            {bot?.win_rate != null && <span>WR <span className="text-amber-400">{(bot.win_rate * 100).toFixed(1)}%</span></span>}
            {bot?.last_updated && <span>Updated <span className="text-amber-500">{new Date(bot.last_updated).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span></span>}
            {wfStatus && <span>WF Walk-fwd <span className="text-amber-300">{wfStatus}</span></span>}
          </div>
        </div>
      )}
    </div>
  );
}

export default function Design1Vaudeville() {
  const { oracle, spy, jerome, buck, total, wfMap, regime, killTripped, mktOpen } = useFleetData();

  const spyStatus    = getBotStatus(spy,    mktOpen, false);
  const oraStatus    = getBotStatus(oracle, mktOpen, false);
  const jerStatus    = getBotStatus(jerome, mktOpen, false);
  const buckStatus   = getBotStatus(buck,   mktOpen, true);

  const fleetEq  = total?.equity  ?? null;
  const fleetPnl = total?.pnl     ?? null;
  const fleetPct = total?.pnl_pct ?? null;
  const positive = (fleetPnl ?? 0) >= 0;
  const rl = REGIME_LABEL[regime ?? ""] ?? REGIME_LABEL["BULL"];

  return (
    <div className="min-h-screen font-mono" style={{ background: "linear-gradient(180deg, #1c0f05 0%, #12090200 100%)" }}>
      <DesignNav current={1} />

      {/* Header */}
      <div
        className="flex items-center gap-3 px-4 py-4 flex-wrap"
        style={{ borderBottom: "2px solid #78350f", background: "#1c0f05" }}
      >
        <div>
          <div className="text-[10px] uppercase tracking-widest text-amber-700 mb-0.5">STOOGE THEATRE · FLEET</div>
          <div className="flex items-baseline gap-2">
            <span className="text-[24px] font-black text-amber-100 tabular-nums">{fleetEq != null ? fmtEq(fleetEq) : "—"}</span>
            {fleetPnl != null && (
              <span className="text-[14px] font-semibold tabular-nums" style={{ color: positive ? "#86efac" : "#fca5a5" }}>
                {fmtDollar(fleetPnl)} ({fmtPct(fleetPct ?? 0)})
              </span>
            )}
          </div>
        </div>
        <div className="ml-auto flex flex-col items-end gap-1">
          <span className="text-[11px] font-bold text-amber-300">{rl.emoji} {rl.label}</span>
          {killTripped != null && (
            <span className="text-[9px] font-bold" style={{ color: killTripped ? "#fca5a5" : "#78716c" }}>
              {killTripped ? "⛔ KILL SWITCH TRIPPED" : "🎬 SHOW RUNNING"}
            </span>
          )}
        </div>
      </div>

      {/* Bot cards */}
      <div className="mx-auto px-4 pt-4 pb-2 space-y-3" style={{ maxWidth: 600 }}>
        <VBotCard emoji="🎩" name="Moe"      role="SPY/QQQ Momentum"   bot={spy}    status={spyStatus}  wfStatus={wfMap.get("spy_qqq_trend")} accent="#d97706" />
        <VBotCard emoji="🥧" name="Larry"    role="Oracle Momentum"    bot={oracle} status={oraStatus}  wfStatus={wfMap.get("oracle")}        accent="#b45309" />

        {/* Curly combined card */}
        <div className="rounded-2xl border-2 overflow-hidden" style={{ background: "rgba(28,15,5,0.95)", borderColor: "#78350f" }}>
          <div style={{ height: 3, background: "linear-gradient(90deg, #ef4444, #78350f 60%, transparent)" }} />
          <div className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-3xl">🎺</span>
              <span className="text-[15px] font-black text-amber-100">Curly</span>
              <span className="text-[9px] text-amber-700 uppercase tracking-widest">Jerome + Buck</span>
            </div>
            {/* Sub-rows */}
            {([
              { label: "Curly",    bot: jerome, status: jerStatus,  wf: wfMap.get("jerome_macro"), isADX: false },
              { label: "Curly Jr", bot: buck,   status: buckStatus, wf: wfMap.get("buck_futures"), isADX: true  },
            ] as const).map(({ label, bot, status, wf }) => {
              const st = STATUSES[status];
              const pnl = bot?.pnl ?? 0;
              return (
                <div key={label} className="flex items-center gap-2 py-1.5 border-b last:border-0" style={{ borderColor: "#78350f50" }}>
                  <span className="text-[12px] w-6">{st.emoji}</span>
                  <span className="text-[11px] text-amber-700 w-16 shrink-0">{label}</span>
                  <span className="text-[14px] font-bold text-amber-100 tabular-nums">{fmtEq(bot?.equity ?? 0)}</span>
                  <span className="text-[11px] tabular-nums ml-1" style={{ color: pnl >= 0 ? "#86efac" : "#fca5a5" }}>
                    {fmtPct(bot?.pnl_pct ?? 0)}
                  </span>
                  {wf && <span className="text-[9px] text-amber-800 ml-auto">{wf}</span>}
                </div>
              );
            })}
          </div>
        </div>

        {/* Footer */}
        <div className="text-center py-3 text-[9px] text-amber-900 tracking-widest uppercase">
          ✦ TONIGHT'S PERFORMANCE ✦
        </div>
      </div>
      <div style={{ height: 96 }} />
    </div>
  );
}
