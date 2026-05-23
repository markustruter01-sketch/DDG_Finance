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
  { id: "listing_pump",      short: "Listing", color: "#fb923c" },
  { id: "event_trader",      short: "Event",   color: "#8b5cf6" },
  { id: "depeg_hunter",      short: "Depeg",   color: "#fb7185" },
  { id: "memecoin_velocity", short: "Meme",    color: "#a3e635" },
  { id: "momentum_alpha",   short: "Mom-A",   color: "#22d3ee" },
  { id: "momentum_beta",    short: "Mom-B",   color: "#a78bfa" },
  { id: "momentum_gamma",   short: "Mom-G",   color: "#fb7185" },
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
          gridTemplateRows:    "repeat(2, auto)",
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
              style={{
                background:   "transparent",
                border:       `1px solid ${active ? bot.color + "50" : "rgba(100,116,139,0.18)"}`,
                borderRadius: 8,
                padding:      "7px 10px",
                minWidth:     110,
                boxShadow:    active ? `0 0 10px ${bot.color}22` : "none",
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
                    background:   active ? "#4ade80" : "#f87171",
                    boxShadow:    active ? "0 0 6px #4ade8099" : "none",
                  }}
                />
                <span
                  style={{
                    color:         bot.color,
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
                  color:         active ? "rgba(74,222,128,0.6)" : "rgba(248,113,113,0.6)",
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
