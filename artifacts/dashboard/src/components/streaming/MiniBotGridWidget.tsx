import { getBotIdentity } from "@/lib/bot-identity";

// Per-bot accent colours — purely visual, not a bot-list definition.
// The runtime bot list derives from fleetEq keys filtered by stale===false.
const BOT_COLORS: Record<string, string> = {
  oracle:        "#a78bfa",
  spy_qqq_trend: "#fbbf24",
  jerome_macro:  "#f87171",
};

// Keys that fleet/equity returns that are NOT bot entries
const FLEET_META_KEYS = new Set(["fleet_total", "generated_at", "errors"]);

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
  // Fleet data unavailable — explicit error state, no hardcoded fallback
  if (fleetEq == null) {
    return (
      <div style={{ pointerEvents: "none", userSelect: "none" }}>
        <div
          style={{
            color:         "rgba(248,113,113,0.7)",
            fontSize:      10,
            fontFamily:    "monospace",
            letterSpacing: "0.12em",
          }}
        >
          ◂ Fleet data unavailable
        </div>
      </div>
    );
  }

  // Derive active bot list from fleet equity keys — stale bots are excluded
  const activeBotIds = Object.keys(fleetEq).filter(
    k => !FLEET_META_KEYS.has(k) && !(fleetEq[k] as BotEquitySlice)?.stale
  );

  if (activeBotIds.length === 0) {
    return (
      <div style={{ pointerEvents: "none", userSelect: "none" }}>
        <div
          style={{
            color:         "rgba(248,113,113,0.6)",
            fontSize:      10,
            fontFamily:    "monospace",
            letterSpacing: "0.12em",
          }}
        >
          ◂ No active bots
        </div>
      </div>
    );
  }

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
          gridTemplateColumns: `repeat(${activeBotIds.length}, 1fr)`,
          gap:                 6,
        }}
      >
        {activeBotIds.map(botId => {
          const identity = getBotIdentity(botId);
          const eq       = fleetEq[botId] as BotEquitySlice | undefined;
          const pnl      = eq?.pnl ?? null;
          const active   = eq != null && !(eq.stale ?? false);
          const pnlColor = pnl == null ? "#64748b" : pnl >= 0 ? "#4ade80" : "#f87171";
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
                {pnl == null ? "—" : fmtPnl(pnl)}
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
