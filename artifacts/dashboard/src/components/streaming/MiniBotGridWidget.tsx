interface BotSlot {
  id:    string;
  short: string;
  color: string;
}

const BOT_SLOTS: BotSlot[] = [
  { id: "oracle",            short: "Oracle",  color: "#a78bfa" },
  { id: "spy_qqq_trend",     short: "SPY/QQQ", color: "#fbbf24" },
  { id: "jerome_macro",      short: "Jerome",  color: "#f87171" },
  { id: "forex_gump",        short: "Forex",   color: "#60a5fa" },
  { id: "depeg_hunter",      short: "Depeg",   color: "#38bdf8" },
  { id: "momentum_alpha",    short: "Mom-A",   color: "#22d3ee" },
  { id: "momentum_beta",     short: "Mom-B",   color: "#a78bfa" },
  { id: "momentum_gamma",    short: "Mom-G",   color: "#fb7185" },
];

interface BotEquitySlice {
  pnl:    number;
  paused: boolean;
}

interface Props {
  fleetEq: Record<string, BotEquitySlice> | null | undefined;
}

function fmtPnl(v: number): string {
  const abs = Math.abs(v);
  const s   = v >= 0 ? "+" : "-";
  if (abs >= 1_000_000) return `${s}$${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000)     return `${s}$${(abs / 1_000).toFixed(1)}k`;
  return `${s}$${abs.toFixed(0)}`;
}

export function MiniBotGridWidget({ fleetEq }: Props) {
  return (
    <div
      style={{
        pointerEvents: "none",
        userSelect:    "none",
      }}
    >
      <style dangerouslySetInnerHTML={{ __html: `
        @keyframes botcard-glow-idle {
          0%, 100% { box-shadow: 0 0 4px rgba(6,182,212,0.12), inset 0 0 6px rgba(6,182,212,0.03); }
          50%       { box-shadow: 0 0 9px rgba(6,182,212,0.22), inset 0 0 8px rgba(6,182,212,0.05); }
        }
        @keyframes botcard-glow-active {
          0%, 100% { box-shadow: 0 0 10px rgba(34,211,238,0.35), inset 0 0 8px rgba(34,211,238,0.06); }
          50%       { box-shadow: 0 0 18px rgba(34,211,238,0.55), inset 0 0 12px rgba(34,211,238,0.10); }
        }
        .botcard-idle   { animation: botcard-glow-idle   3s ease-in-out infinite; }
        .botcard-active { animation: botcard-glow-active 2.4s ease-in-out infinite; }
      `}} />

      <div
        style={{
          color:         "rgba(148,163,184,0.5)",
          fontSize:      9,
          fontFamily:    "monospace",
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          marginBottom:  9,
        }}
      >
        ◂ Bot Grid Status
      </div>

      <div
        style={{
          display:             "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap:                 6,
        }}
      >
        {BOT_SLOTS.map(bot => {
          const eq     = fleetEq?.[bot.id];
          const pnl    = eq?.pnl    ?? 0;
          const active = !(eq?.paused ?? false);
          const pnlColor = pnl >= 0 ? "#4ade80" : "#f87171";

          return (
            <div
              key={bot.id}
              className={active ? "botcard-active" : "botcard-idle"}
              style={{
                background:   "rgba(0,0,0,0.45)",
                border:       `1.5px solid ${active ? "rgba(34,211,238,0.85)" : "rgba(6,182,212,0.22)"}`,
                borderRadius: 5,
                padding:      "7px 10px",
                minWidth:     110,
                backdropFilter: "blur(4px)",
              }}
            >
              {/* Name row + status dot */}
              <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 5 }}>
                <span
                  style={{
                    width:        5,
                    height:       5,
                    borderRadius: "50%",
                    flexShrink:   0,
                    background:   bot.color,
                    boxShadow:    `0 0 5px ${bot.color}99`,
                  }}
                />
                <span
                  style={{
                    color:         active ? "rgba(34,211,238,0.9)" : "rgba(6,182,212,0.55)",
                    fontSize:      9,
                    fontFamily:    "monospace",
                    fontWeight:    700,
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                  }}
                >
                  {bot.short}
                </span>
              </div>

              {/* PnL */}
              <div
                style={{
                  color:      pnlColor,
                  fontSize:   15,
                  fontFamily: "monospace",
                  fontWeight: 700,
                }}
              >
                {fmtPnl(pnl)}
              </div>

              {/* Active / Paused label */}
              <div
                style={{
                  color:         active ? "rgba(34,211,238,0.55)" : "rgba(6,182,212,0.35)",
                  fontSize:      8,
                  fontFamily:    "monospace",
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  marginTop:     3,
                }}
              >
                {active ? "active" : "paused"}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
