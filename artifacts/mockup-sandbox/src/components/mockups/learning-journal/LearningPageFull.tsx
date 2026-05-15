import { useState } from "react";

// ── Static mock data mirroring real platform values ──────────────────────────
const STATS = {
  pnl: "+$11,885", pnlPct: "+2.0%",
  vault: "$546",
  best: "+$268", bestSym: "HPE",
  worst: "-$75", worstSym: "FDX",
  winRate: "64%", winLoss: "175W/99L",
  tradesW: "175W", tradesL: "99L",
  mathAudit: "100.0%", mathChecks: "1,000 checks",
  equity: "$611,885", equityPct: "+2.0%",
};

const BOT_DOTS = [
  { color: "#8b5cf6", active: true },
  { color: "#22d3ee", active: true },
  { color: "#f97316", active: true },
  { color: "#10b981", active: true },
  { color: "#3b82f6", active: false },
  { color: "#ec4899", active: true },
];

const TABS = [
  { label: "LIVE",        color: "#a5b4fc", active: false },
  { label: "MATH",        color: "#67e8f9", active: false },
  { label: "BOTS",        color: "#34d399", active: false },
  { label: "HEALTH",      color: "#fca5a5", active: false },
  { label: "LEARNING",    color: "#6ee7b7", active: true  },
  { label: "ORB",         color: "#c4b5fd", active: false },
  { label: "PERFORMANCE", color: "#fdba74", active: false },
];

const NAV = [
  { label: "HOME",   icon: "⊞", active: false, color: "#3b82f6" },
  { label: "BOTS",   icon: "⊕", active: false, color: "#a855f7" },
  { label: "STREAM", icon: "◉", active: true,  color: "#f43f5e" },
  { label: "CMD",    icon: ">_", active: false, color: "#10b981" },
];

// ── Journal entries ──────────────────────────────────────────────────────────
const entries = [
  {
    date: "15", month: "MAY", day: "FRI",
    title: "Generators & Lazy Evaluation",
    code: `def fibonacci():
    a, b = 0, 1
    while True:
        yield a
        a, b = b, a + b

gen = fibonacci()
print([next(gen) for _ in range(6)])
# → [0, 1, 1, 2, 3, 5, 8, 13]`,
    note: "Generators don't compute until you ask — like a bot in standby waiting for market open. No wasted CPU cycles.",
    tags: ["generators", "yield", "iterators"],
    page: 1,
  },
  {
    date: "12", month: "MAY", day: "TUE",
    title: "Decorators as Middleware",
    code: `from functools import wraps

def rate_limit(fn):
    @wraps(fn)
    def wrapper(*args, **kw):
        time.sleep(0.1)
        return fn(*args, **kw)
    return wrapper

@rate_limit
def place_order(symbol, qty): ...`,
    note: "A decorator injects behaviour without touching the function body — same as the API middleware on Kraken.",
    tags: ["decorators", "closures", "HOF"],
    page: 2,
  },
  {
    date: "8", month: "MAY", day: "FRI",
    title: "Context Managers",
    code: `class DBConn:
    def __enter__(self):
        self.conn = connect()
        return self.conn
    def __exit__(self, *exc):
        self.conn.close()

with DBConn() as db:
    db.execute("SELECT equity FROM bots")`,
    note: "The with block guarantees cleanup even on crash — exactly what I want around live position close logic.",
    tags: ["context", "RAII", "with"],
    page: 3,
  },
];

const LINE_COUNT = 17;
const LINE_H = 26;

// ── Component ────────────────────────────────────────────────────────────────
export function LearningPageFull() {
  const [page, setPage] = useState(0);
  const [turning, setTurning] = useState(false);
  const entry = entries[page];

  function goTo(idx: number) {
    if (idx === page || turning || idx < 0 || idx >= entries.length) return;
    setTurning(true);
    setTimeout(() => { setPage(idx); setTurning(false); }, 240);
  }

  const LABEL: React.CSSProperties = {
    color: "rgba(100,116,139,0.8)", fontSize: 8, fontWeight: 700,
    textTransform: "uppercase", letterSpacing: "0.18em", marginBottom: 2,
  };

  return (
    <div style={{
      width: "100vw", height: "100vh",
      background: "#020617",
      display: "flex", flexDirection: "column",
      overflow: "hidden",
      fontFamily: "'Inter', system-ui, sans-serif",
    }}>

      {/* ══════════════════════════════════════════════════════════════════════
          STREAM HEADER BAR
      ══════════════════════════════════════════════════════════════════════ */}
      <div style={{
        height: 52, flexShrink: 0,
        display: "flex", alignItems: "stretch",
        background: "linear-gradient(90deg, rgba(2,6,23,0.98) 0%, rgba(8,16,40,0.98) 50%, rgba(2,6,23,0.98) 100%)",
        borderBottom: "1px solid rgba(34,211,238,0.12)",
        fontFamily: "monospace",
        zIndex: 30,
      }}>
        {/* LIVE */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "0 16px", borderRight: "1px solid rgba(255,255,255,0.06)", flexShrink: 0 }}>
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#22c55e", boxShadow: "0 0 6px #22c55e", display: "inline-block" }} />
          <span style={{ fontSize: 10, fontWeight: 900, letterSpacing: "0.2em", color: "#22c55e" }}>LIVE</span>
        </div>
        {/* TOTAL P&L */}
        <Cell label="TOTAL P&L" w={148}>
          <Val color="#4ade80">{STATS.pnl}</Val>
          <Sub color="rgba(74,222,128,0.7)">{STATS.pnlPct}</Sub>
        </Cell>
        {/* VAULT */}
        <Cell label="VAULT" w={128}>
          <Val color="#a78bfa">{STATS.vault}</Val>
          <Sub color="rgba(100,116,139,0.6)">secured</Sub>
        </Cell>
        {/* BEST TRADE */}
        <Cell label="BEST TRADE" w={138}>
          <Val color="#4ade80">{STATS.best}</Val>
          <Sub color="rgba(74,222,128,0.7)">{STATS.bestSym}</Sub>
        </Cell>
        {/* WORST TRADE */}
        <Cell label="WORST TRADE" w={138}>
          <Val color="#f87171">{STATS.worst}</Val>
          <Sub color="rgba(248,113,113,0.7)">{STATS.worstSym}</Sub>
        </Cell>
        {/* WIN RATE */}
        <Cell label="WIN RATE" w={118}>
          <Val color="#22d3ee">{STATS.winRate}</Val>
          <Sub color="rgba(100,116,139,0.6)">{STATS.winLoss}</Sub>
        </Cell>
        {/* TRADES */}
        <Cell label="TRADES" w={108}>
          <Val color="#4ade80">{STATS.tradesW}</Val>
          <span style={{ color: "rgba(100,116,139,0.4)", fontSize: 11, fontWeight: 700, margin: "0 2px" }}>/</span>
          <Val color="#f87171">{STATS.tradesL}</Val>
        </Cell>
        {/* MATH AUDIT */}
        <Cell label="MATH AUDIT" w={168}>
          <Val color="#22d3ee">{STATS.mathAudit}</Val>
          <Sub color="rgba(100,116,139,0.6)">{STATS.mathChecks}</Sub>
        </Cell>
        {/* PLATFORM EQUITY — pushed right */}
        <Cell label="PLATFORM EQUITY" w={168} ml="auto">
          <Val color="#fbbf24">{STATS.equity}</Val>
          <Sub color="rgba(251,191,36,0.6)">{STATS.equityPct}</Sub>
        </Cell>
        {/* ACTIVE BOTS */}
        <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "0 16px", borderLeft: "1px solid rgba(255,255,255,0.05)", flexShrink: 0 }}>
          <div>
            <div style={LABEL}>ACTIVE BOTS</div>
            <div style={{ display: "flex", gap: 6 }}>
              {BOT_DOTS.map((b, i) => (
                <span key={i} style={{
                  width: 8, height: 8, borderRadius: "50%",
                  background: b.active ? b.color : "rgba(100,116,139,0.2)",
                  boxShadow: b.active ? `0 0 5px ${b.color}` : "none",
                  display: "inline-block",
                }} />
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ══════════════════════════════════════════════════════════════════════
          TAB BAR
      ══════════════════════════════════════════════════════════════════════ */}
      <div style={{
        height: 48, flexShrink: 0,
        display: "flex", alignItems: "center",
        background: "rgba(8,16,40,0.95)",
        borderBottom: "1px solid rgba(255,255,255,0.06)",
        paddingLeft: 16,
        gap: 2,
      }}>
        {TABS.map((t) => (
          <button key={t.label} style={{
            padding: "6px 14px",
            borderRadius: 6,
            border: t.active ? `1px solid ${t.color}50` : "1px solid transparent",
            background: t.active ? `${t.color}18` : "transparent",
            color: t.active ? t.color : "rgba(100,116,139,0.7)",
            fontSize: 11, fontWeight: t.active ? 700 : 500,
            letterSpacing: "0.08em",
            cursor: "pointer",
            transition: "all 0.2s",
            fontFamily: "monospace",
          }}>
            {t.label}
          </button>
        ))}
        {/* Dot indicators */}
        <div style={{ display: "flex", gap: 4, marginLeft: 8 }}>
          {TABS.map((t, i) => (
            <span key={i} style={{
              width: 5, height: 5, borderRadius: "50%",
              background: t.active ? "#6ee7b7" : "rgba(100,116,139,0.25)",
              display: "inline-block",
            }} />
          ))}
        </div>
        {/* INTERVAL / AUTO-CYCLE */}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8, paddingRight: 16 }}>
          <span style={{ color: "rgba(100,116,139,0.5)", fontSize: 10, fontFamily: "monospace", letterSpacing: "0.1em" }}>INTERVAL</span>
          <div style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 4, padding: "2px 10px", color: "#94a3b8", fontSize: 12, fontFamily: "monospace" }}>15</div>
          <span style={{ color: "rgba(100,116,139,0.4)", fontSize: 10, fontFamily: "monospace" }}>s</span>
          <div style={{
            background: "rgba(34,197,94,0.12)", border: "1px solid rgba(34,197,94,0.4)",
            borderRadius: 6, padding: "4px 12px",
            color: "#22c55e", fontSize: 10, fontWeight: 700, letterSpacing: "0.12em", fontFamily: "monospace",
            display: "flex", alignItems: "center", gap: 5,
          }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#22c55e", boxShadow: "0 0 4px #22c55e", display: "inline-block" }} />
            AUTO-CYCLE
          </div>
        </div>
      </div>

      {/* ══════════════════════════════════════════════════════════════════════
          MAIN CONTENT — Journal Page
      ══════════════════════════════════════════════════════════════════════ */}
      <div style={{
        flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
        background: "radial-gradient(ellipse at 50% 40%, #0c1a0e 0%, #020617 100%)",
        padding: "20px 40px 80px",
        overflow: "hidden",
      }}>
        {/* Journal book */}
        <div style={{
          width: "100%", maxWidth: 900,
          height: "100%", maxHeight: 580,
          position: "relative",
          filter: "drop-shadow(0 12px 40px rgba(0,0,0,0.7))",
        }}>
          {/* Page stack shadows */}
          {[3, 2].map(n => (
            <div key={n} style={{
              position: "absolute", inset: 0,
              background: `hsl(42, 30%, ${79 - n * 4}%)`,
              borderRadius: 2,
              transform: `translate(${n * 4}px, ${n * 2}px)`,
              zIndex: n,
            }} />
          ))}

          {/* Main page */}
          <div style={{
            position: "relative", zIndex: 10,
            width: "100%", height: "100%",
            background: "linear-gradient(180deg, #f5eccd 0%, #efe2b2 100%)",
            borderRadius: 2,
            display: "flex",
            overflow: "hidden",
            opacity: turning ? 0 : 1,
            transform: turning ? "rotateY(6deg) scale(0.98)" : "none",
            transition: "opacity 0.24s ease, transform 0.24s ease",
          }}>
            {/* Spiral binding */}
            <div style={{
              width: 38, flexShrink: 0,
              background: "linear-gradient(180deg, #d4c89a 0%, #c8b87e 100%)",
              borderRight: "2px solid #b8a060",
              display: "flex", flexDirection: "column",
              alignItems: "center", paddingTop: 24, gap: 22, zIndex: 2,
            }}>
              {Array.from({ length: 18 }).map((_, i) => (
                <div key={i} style={{
                  width: 22, height: 13, borderRadius: 7,
                  border: "2.5px solid #7a6030",
                  background: "linear-gradient(180deg, #999 30%, #444)",
                  flexShrink: 0,
                  boxShadow: "inset 0 1px 2px rgba(0,0,0,0.3), 1px 1px 2px rgba(0,0,0,0.2)",
                }} />
              ))}
            </div>

            {/* Page body */}
            <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>
              {/* Ruled lines */}
              <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }} preserveAspectRatio="none">
                {Array.from({ length: LINE_COUNT }).map((_, i) => (
                  <line key={i} x1="0" y1={52 + i * LINE_H} x2="100%" y2={52 + i * LINE_H} stroke="#c4a85038" strokeWidth="1" />
                ))}
                <line x1="70" y1="0" x2="70" y2="100%" stroke="#c0403055" strokeWidth="1.5" />
              </svg>

              {/* Header strip */}
              <div style={{
                position: "absolute", top: 0, left: 0, right: 0, height: 44,
                background: "linear-gradient(180deg, #e6d490 0%, rgba(230,212,144,0) 100%)",
                borderBottom: "1.5px solid #c4a85055",
                display: "flex", alignItems: "center",
                paddingLeft: 84, paddingRight: 20, gap: 10,
              }}>
                <span style={{ color: "#5a4010", fontSize: 12, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", opacity: 0.7, fontFamily: "serif" }}>
                  Python Learning Journal
                </span>
                <span style={{ color: "#8a6828", opacity: 0.5, fontSize: 11 }}>—</span>
                <span style={{ color: "#8a6828", fontSize: 11, opacity: 0.55, fontFamily: "serif" }}>Digital Dynamics</span>
                <span style={{ marginLeft: "auto", color: "#8a6828", fontSize: 11, opacity: 0.6, fontStyle: "italic", fontFamily: "serif" }}>
                  p.{entry.page} / {entries.length}
                </span>
              </div>

              {/* Date in margin */}
              <div style={{ position: "absolute", left: 8, top: 50, width: 56, textAlign: "center" }}>
                <div style={{ color: "#8a6828", fontSize: 8, fontWeight: 700, opacity: 0.75 }}>{entry.day}</div>
                <div style={{ color: "#5a4010", fontSize: 18, fontWeight: 800, lineHeight: 1.1, fontFamily: "serif" }}>{entry.date}</div>
                <div style={{ color: "#8a6828", fontSize: 8, opacity: 0.65 }}>{entry.month}</div>
              </div>

              {/* Content */}
              <div style={{ paddingLeft: 84, paddingRight: 24, paddingTop: 52 }}>
                {/* Title */}
                <h2 style={{
                  color: "#1a2c4a", fontSize: 20, fontWeight: 700, fontStyle: "italic",
                  margin: 0, lineHeight: `${LINE_H}px`, fontFamily: "Georgia, serif",
                  letterSpacing: "0.01em",
                }}>
                  {entry.title}
                </h2>
                <div style={{
                  height: 2, margin: "3px 0 8px",
                  background: "linear-gradient(90deg, #1a2c4a70, transparent)",
                  borderRadius: 1, width: "60%",
                }} />

                {/* Code block */}
                <div style={{
                  background: "rgba(0,0,0,0.045)",
                  border: "1px solid rgba(139,104,40,0.22)",
                  borderRadius: 3,
                  padding: "10px 14px",
                  marginBottom: 10,
                  position: "relative",
                  boxShadow: "inset 0 1px 3px rgba(0,0,0,0.05)",
                }}>
                  {/* Tape strip */}
                  <div style={{
                    position: "absolute", top: -7, left: 22,
                    width: 50, height: 13,
                    background: "rgba(200,180,120,0.4)", borderRadius: 2,
                    transform: "rotate(-1.5deg)",
                  }} />
                  <pre style={{
                    margin: 0, fontSize: 11.5, lineHeight: "18px",
                    color: "#1a2c4a",
                    fontFamily: "'Courier New', Courier, monospace",
                    whiteSpace: "pre-wrap", letterSpacing: "0.015em",
                  }}>
                    {entry.code}
                  </pre>
                </div>

                {/* Note */}
                <p style={{
                  color: "#1f4a28", fontSize: 13, fontStyle: "italic",
                  lineHeight: `${LINE_H}px`, margin: "0 0 10px",
                  fontFamily: "Georgia, serif", letterSpacing: "0.01em",
                }}>
                  ↳ {entry.note}
                </p>

                {/* Tags */}
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {entry.tags.map(t => (
                    <span key={t} style={{
                      border: "1.5px solid #8a682860", color: "#8a6828",
                      borderRadius: 2, padding: "1px 8px", fontSize: 10,
                      fontFamily: "monospace", letterSpacing: "0.05em", opacity: 0.8,
                    }}>
                      #{t}
                    </span>
                  ))}
                </div>
              </div>

              {/* Bottom nav strip */}
              <div style={{
                position: "absolute", bottom: 0, left: 0, right: 0, height: 38,
                borderTop: "1px solid #c4a85038",
                display: "flex", alignItems: "center",
                paddingLeft: 84, paddingRight: 20, gap: 10,
                background: "linear-gradient(0deg, #e6d490 0%, rgba(230,212,144,0) 100%)",
              }}>
                <button onClick={() => goTo(page - 1)} disabled={page === 0} style={{
                  background: "none", border: "none",
                  color: page === 0 ? "#c4a85080" : "#5a4010",
                  cursor: page === 0 ? "default" : "pointer",
                  fontSize: 16, fontFamily: "serif", padding: "0 4px",
                }}>←</button>
                <div style={{ flex: 1, display: "flex", justifyContent: "center", gap: 8 }}>
                  {entries.map((_, i) => (
                    <button key={i} onClick={() => goTo(i)} style={{
                      width: i === page ? 24 : 8, height: 8, borderRadius: 4,
                      background: i === page ? "#5a4010" : "#c4a850",
                      border: "none", cursor: "pointer", padding: 0,
                      opacity: i === page ? 1 : 0.45,
                      transition: "all 0.25s",
                    }} />
                  ))}
                </div>
                <button onClick={() => goTo(page + 1)} disabled={page === entries.length - 1} style={{
                  background: "none", border: "none",
                  color: page === entries.length - 1 ? "#c4a85080" : "#5a4010",
                  cursor: page === entries.length - 1 ? "default" : "pointer",
                  fontSize: 16, fontFamily: "serif", padding: "0 4px",
                }}>→</button>
                <span style={{ position: "absolute", right: 20, color: "#8a6828", fontSize: 10, opacity: 0.55, fontStyle: "italic", fontFamily: "serif" }}>
                  {entry.day}, {entry.date} {entry.month} {new Date().getFullYear()}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ══════════════════════════════════════════════════════════════════════
          BOTTOM NAV (floating pill)
      ══════════════════════════════════════════════════════════════════════ */}
      <div style={{
        position: "absolute", bottom: 20, left: "50%", transform: "translateX(-50%)",
        display: "flex", gap: 10, zIndex: 100,
      }}>
        {NAV.map(n => (
          <div key={n.label} style={{
            minWidth: 62, padding: "10px 14px",
            borderRadius: 16, display: "flex", flexDirection: "column",
            alignItems: "center", gap: 4, cursor: "pointer",
            ...(n.active ? {
              background: `linear-gradient(135deg, ${n.color}26, ${n.color}12)`,
              border: `1px solid ${n.color}55`,
              boxShadow: `0 4px 24px ${n.color}30, inset 0 1px 0 ${n.color}20`,
              transform: "translateY(-1px) scale(1.04)",
            } : {
              background: "rgba(15,23,42,0.85)",
              border: "1px solid rgba(255,255,255,0.08)",
              boxShadow: "0 4px 16px rgba(0,0,0,0.5)",
            }),
          }}>
            <span style={{ fontSize: 18, color: n.active ? n.color : "rgba(148,163,184,0.65)", lineHeight: 1 }}>{n.icon}</span>
            <span style={{ fontSize: 9, fontWeight: 900, letterSpacing: "0.18em", textTransform: "uppercase", color: n.active ? n.color : "rgba(100,116,139,0.85)" }}>{n.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Tiny helpers ─────────────────────────────────────────────────────────────
function Cell({ label, w, ml, children }: { label: string; w: number; ml?: string; children: React.ReactNode }) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", justifyContent: "center",
      padding: "0 16px", flexShrink: 0, width: w,
      borderRight: "1px solid rgba(255,255,255,0.05)",
      marginLeft: ml,
    }}>
      <div style={{ color: "rgba(100,116,139,0.8)", fontSize: 8, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.18em", marginBottom: 2 }}>
        {label}
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6, whiteSpace: "nowrap" }}>
        {children}
      </div>
    </div>
  );
}

function Val({ color, children }: { color: string; children: React.ReactNode }) {
  return <span style={{ fontSize: 14, fontWeight: 700, color, lineHeight: 1 }}>{children}</span>;
}

function Sub({ color, children }: { color: string; children: React.ReactNode }) {
  return <span style={{ fontSize: 10, fontWeight: 500, color }}>{children}</span>;
}
