import { getBotIdentity } from "@/lib/bot-identity";

// Active bot IDs in display order — exactly the 3 live bots.
// buck_futures is retired (last heartbeat May 30) and excluded here.
const ACTIVE_BOT_IDS = ["oracle", "spy_qqq_trend", "jerome_macro"] as const;

// Per-bot accent colours (not from identity — purely visual)
const BOT_COLORS: Record<string, string> = {
  oracle:        "#a78bfa",
  spy_qqq_trend: "#fbbf24",
  jerome_macro:  "#f87171",
};

interface BotEquitySlice {
  pnl:    number;
  stale?: boolean;
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
          gridTemplateColumns: "repeat(3, 1fr)",
          gap:                 6,
        }}
      >
        {ACTIVE_BOT_IDS.map(botId => {
          const identity = getBotIdentity(botId);
          const eq       = fleetEq?.[botId];
          const pnl      = eq?.pnl ?? 0;
          // Absent fleet key or stale flag = inactive (retired bots always stale)
          const active   = eq != null && !(eq.stale ?? false);
          const pnlColor = pnl >= 0 ? "#4ade80" : "#f87171";
          const color    = BOT_COLORS[botId] ?? "#64748b";

          return (
            <div
              key={botId}
              className={active ? "botcard-active" : "botcard-idle"}
              style={{
                background:   "rgba(0,0,0,0.45)",
                border:       `1.5px solid ${active ? "rgba(34,211,238,0.85)" : "rgba(6,182,212,0.22)"}`,
                borderRadius: 5,
                padding:      "7px 10px",
                minWidth:     90,
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
                    background:   color,
                    boxShadow:    `0 0 5px ${color}99`,
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
                  {identity.shortName}
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

              {/* Active / Stale label */}
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
                {active ? "active" : "stale"}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
