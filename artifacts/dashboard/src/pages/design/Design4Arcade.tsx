/**
 * Design 4 — ARCADE SCOREBOARD
 * Bots as players · P&L as scores · leaderboard · pixel-art neon accents
 */
import { useState } from "react";
import { useFleetData, getBotStatus, fmtPct, fmtDollar, type BotSlice, type BotStatus } from "@/hooks/useFleetData";

const LABELS = ["🎭", "💻", "🚀", "🕹️", "🛸"];

function DesignNav({ current }: { current: number }) {
  return (
    <div className="sticky top-0 z-50 flex items-center gap-1 px-3 py-2 overflow-x-auto" style={{ background: "#000", borderBottom: "1px solid #ff009020" }}>
      {[1,2,3,4,5].map((n, i) => (
        <a key={n} href={`/design/${n}`}
          className="shrink-0 text-[9px] font-black px-2 py-1 whitespace-nowrap"
          style={{ color: current === n ? "#ff0090" : "#330019", textShadow: current === n ? "0 0 8px #ff009099" : undefined }}>
          {LABELS[i]}{n}
        </a>
      ))}
      <a href="/" className="ml-auto shrink-0 text-[9px] text-[#220011]">← HOME</a>
    </div>
  );
}

function fmtScore(v: number): string {
  const abs = Math.round(Math.abs(v));
  return abs.toLocaleString().padStart(9, "\u2007");
}

const STATUS_ARC: Record<BotStatus, { label: string; color: string }> = {
  LIVE:       { label: "PLAYING", color: "#33ff99" },
  MKT_CLOSED: { label: "STANDBY", color: "#555555" },
  DOWN:       { label: "GAME OVR", color: "#ff3333" },
  IDLE:       { label: "PAUSED",  color: "#ffdd00" },
};

const ACCENTS = ["#ff0090", "#33ff99", "#ffdd00"];
const PLAYER_LABELS = ["1P", "2P", "3P"];
const PLAYER_NAMES  = ["MOE · SPY/QQQ", "LARRY · ORACLE", "CURLY · J+B"];

interface ArcPlayerProps {
  player:    number;
  name:      string;
  bots:      (BotSlice | undefined)[];
  statuses:  BotStatus[];
  wfStatuses: (string | null | undefined)[];
  accent:    string;
}

function ArcPlayerCard({ player, name, bots, statuses, wfStatuses, accent }: ArcPlayerProps) {
  const [open, setOpen] = useState(false);
  // Use first bot for primary display; show sub-rows if two bots
  const primaryBot = bots[0];
  const primaryStatus = statuses[0];
  const st = STATUS_ARC[primaryStatus];
  /* Rule 27: no summing — use primary bot equity; sub-rows show each bot separately */
  const equity = primaryBot?.equity ?? 0;
  /* Rule 27: no summing — use primary bot for score, sub-rows show each bot */
  const pnl    = primaryBot?.pnl     ?? 0;
  const pos = pnl >= 0;

  return (
    <div
      className="cursor-pointer select-none"
      style={{
        background: "#000",
        border: `1px solid ${accent}40`,
        boxShadow: open ? `0 0 20px ${accent}30, inset 0 0 40px ${accent}06` : "none",
        borderRadius: 4,
      }}
      onClick={() => setOpen(v => !v)}
    >
      {/* Player tag */}
      <div className="flex items-center justify-between px-3 py-2" style={{ borderBottom: `1px solid ${accent}25` }}>
        <div className="flex items-center gap-2">
          <span
            className="text-[10px] font-black px-2 py-0.5"
            style={{ color: "#000", background: accent, fontVariantNumeric: "tabular-nums" }}
          >{PLAYER_LABELS[player - 1]}</span>
          <span className="text-[10px] font-black tracking-[0.15em]" style={{ color: accent }}>{name}</span>
        </div>
        <span className="text-[9px] font-bold" style={{ color: st.color, textShadow: `0 0 6px ${st.color}99` }}>
          {st.label}
        </span>
      </div>

      {/* Score display */}
      <div className="px-3 py-3 flex items-center justify-between">
        <div>
          <div className="text-[8px] text-slate-700 tracking-widest mb-0.5">EQUITY</div>
          <div
            className="text-[22px] font-black tabular-nums leading-none"
            style={{ color: accent, textShadow: `0 0 12px ${accent}55`, letterSpacing: "0.05em" }}
          >
            {fmtScore(equity)}
          </div>
        </div>
        <div className="text-right">
          <div className="text-[8px] text-slate-700 tracking-widest mb-0.5">P/L</div>
          <div className="text-[16px] font-black tabular-nums" style={{ color: pos ? "#33ff99" : "#ff3333", textShadow: pos ? "0 0 8px #33ff9966" : "0 0 8px #ff333366" }}>
            {pos ? "+" : ""}{fmtScore(pnl)}
          </div>
          <div className="text-[10px] font-bold tabular-nums" style={{ color: pos ? "#33ff9999" : "#ff333399" }}>
            {fmtPct(primaryBot?.pnl_pct ?? 0)}
          </div>
        </div>
      </div>

      {open && (
        <div className="px-3 pb-3" style={{ borderTop: `1px solid ${accent}20` }} onClick={e => e.stopPropagation()}>
          {bots.length > 1 ? (
            /* Dual-bot: show sub-rows */
            <div className="mt-2 space-y-1.5">
              {bots.map((b, i) => {
                const bPnl = b?.pnl ?? 0;
                const bPos = bPnl >= 0;
                const wf = wfStatuses[i];
                const subSt = STATUS_ARC[statuses[i]];
                return (
                  <div key={i} className="flex items-center gap-2 text-[9px]" style={{ borderLeft: `2px solid ${accent}40`, paddingLeft: 8 }}>
                    <span className="text-slate-600">{i === 0 ? "CURLY" : "CURLY_JR"}</span>
                    <span className="font-black tabular-nums" style={{ color: accent }}>{fmtScore(b?.equity ?? 0)}</span>
                    <span className="font-bold tabular-nums" style={{ color: bPos ? "#33ff99" : "#ff3333" }}>{fmtPct(b?.pnl_pct ?? 0)}</span>
                    <span className="text-slate-700">{subSt.label}</span>
                    {wf && <span className="text-slate-700 ml-auto">{wf}</span>}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="mt-2 flex gap-4 text-[9px] text-slate-600">
              {primaryBot?.win_rate != null && <span>COMBO RATE <span style={{ color: accent }}>{(primaryBot.win_rate * 100).toFixed(0)}%</span></span>}
              {wfStatuses[0] && <span>WF <span style={{ color: accent }}>{wfStatuses[0]}</span></span>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function Design4Arcade() {
  const { oracle, spy, jerome, total, wfMap, regime, killTripped, mktOpen } = useFleetData();

  const spyStatus  = getBotStatus(spy,    mktOpen, false);
  const oraStatus  = getBotStatus(oracle, mktOpen, false);
  const jerStatus  = getBotStatus(jerome, mktOpen, false);

  const fleetEq  = total?.equity  ?? 0;
  const fleetPnl = total?.pnl     ?? 0;
  const fleetPct = total?.pnl_pct ?? 0;
  const pos = fleetPnl >= 0;

  // Sort bots by equity for leaderboard
  const bots = [
    { player: 1, name: PLAYER_NAMES[0], bots: [spy],          statuses: [spyStatus],               wfStatuses: [wfMap.get("spy_qqq_trend")],                    accent: ACCENTS[0], equity: spy?.equity    ?? 0 },
    { player: 2, name: PLAYER_NAMES[1], bots: [oracle],        statuses: [oraStatus],               wfStatuses: [wfMap.get("oracle")],                           accent: ACCENTS[1], equity: oracle?.equity ?? 0 },
    /* Curly sort key = Jerome's equity (primary bot — no summing per Rule 27) */
    { player: 3, name: PLAYER_NAMES[2], bots: [jerome],        statuses: [jerStatus],               wfStatuses: [wfMap.get("jerome_macro")],                           accent: ACCENTS[2], equity: jerome?.equity ?? 0 },
  ].sort((a, b) => b.equity - a.equity);

  return (
    <div className="min-h-screen font-mono" style={{ background: "#000", color: "#fff" }}>
      <DesignNav current={4} />

      {/* Header scoreboard */}
      <div className="px-4 py-4" style={{ borderBottom: "1px solid #330019", background: "#000" }}>
        <div className="text-center">
          <div className="text-[10px] tracking-[0.3em] font-black mb-1" style={{ color: "#ff0090", textShadow: "0 0 10px #ff009066" }}>
            STOOGE  TRADER  CHAMPIONSHIP
          </div>
          <div className="flex items-baseline justify-center gap-3">
            <span className="text-[28px] font-black tabular-nums" style={{ color: "#fff", textShadow: "0 0 15px #ffffff30" }}>
              {fmtScore(fleetEq)}
            </span>
            <span className="text-[14px] font-black tabular-nums" style={{ color: pos ? "#33ff99" : "#ff3333" }}>
              {pos ? "+" : ""}{fmtPct(fleetPct)}
            </span>
          </div>
          <div className="flex items-center justify-center gap-4 mt-1 text-[9px]">
            <span style={{ color: killTripped ? "#ff3333" : "#333333" }}>
              {killTripped ? "⚠ KILL SW" : "● ARMED"}
            </span>
            <span style={{ color: regime === "CRISIS" ? "#ff3333" : regime === "BEAR" ? "#ff9900" : "#33ff99" }}>
              {regime ?? "REGIME UNKNOWN"}
            </span>
          </div>
        </div>
      </div>

      {/* Leaderboard */}
      <div className="mx-auto px-4 pt-4 pb-2 space-y-3" style={{ maxWidth: 600 }}>
        <div className="text-[8px] tracking-widest text-slate-700 px-1">LEADERBOARD · RANKED BY EQUITY</div>
        {bots.map((b) => (
          <ArcPlayerCard key={b.player} {...b} />
        ))}

        <div className="text-center text-[8px] tracking-[0.3em] font-black py-2" style={{ color: "#220011" }}>
          INSERT COIN TO CONTINUE
        </div>
      </div>
      <div style={{ height: 96 }} />
    </div>
  );
}
