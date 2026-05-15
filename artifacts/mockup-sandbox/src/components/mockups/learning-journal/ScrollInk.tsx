import { useState } from "react";

const entries = [
  {
    date: "May 15",
    year: "2026",
    day: "Friday",
    title: "Generators & Lazy Evaluation",
    code: `def fibonacci():
    a, b = 0, 1
    while True:
        yield a
        a, b = b, a + b

# Only computed when asked
gen = fibonacci()
print([next(gen) for _ in range(6)])`,
    note: "Generators don't compute until you ask — like a bot in standby waiting for market open. No wasted CPU cycles.",
    tags: ["generators", "yield", "iterators", "memory"],
    pageNum: 1,
    inkColor: "#1a3a5c",
  },
  {
    date: "May 12",
    year: "2026",
    day: "Tuesday",
    title: "Decorators as Middleware",
    code: `from functools import wraps

def rate_limit(fn):
    @wraps(fn)
    def wrapper(*args, **kw):
        time.sleep(0.1)   # throttle
        return fn(*args, **kw)
    return wrapper

@rate_limit
def place_order(symbol, qty): ...`,
    note: "A decorator injects behaviour without touching the function body — same idea as my API middleware layer on Kraken.",
    tags: ["decorators", "closures", "HOF", "patterns"],
    pageNum: 2,
    inkColor: "#1a3a5c",
  },
  {
    date: "May 8",
    year: "2026",
    day: "Friday",
    title: "Context Managers",
    code: `class DBConn:
    def __enter__(self):
        self.conn = connect()
        return self.conn

    def __exit__(self, *exc):
        self.conn.close()

with DBConn() as db:
    db.execute("SELECT 1")`,
    note: "The with block guarantees cleanup even on crash or exception — exactly the guarantee I want around live position logic.",
    tags: ["context", "RAII", "cleanup", "with"],
    pageNum: 3,
    inkColor: "#1a3a5c",
  },
];

const LINE_COUNT = 22;
const LINE_H = 24;

export function ScrollInk() {
  const [page, setPage] = useState(0);
  const [turning, setTurning] = useState(false);

  const entry = entries[page];

  function goTo(idx: number) {
    if (idx === page || turning) return;
    setTurning(true);
    setTimeout(() => { setPage(idx); setTurning(false); }, 260);
  }

  return (
    <div
      style={{
        width: "100%",
        height: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#2c2416",
        backgroundImage: "radial-gradient(ellipse at 50% 50%, #3a2f1f 0%, #1e1610 100%)",
        padding: 20,
        boxSizing: "border-box",
        fontFamily: "'Georgia', 'Times New Roman', serif",
      }}
    >
      <div
        style={{
          width: "100%",
          maxWidth: 820,
          height: 540,
          position: "relative",
          display: "flex",
          filter: "drop-shadow(0 8px 32px rgba(0,0,0,0.6))",
        }}
      >
        {/* ── Page stack illusion (pages behind) ── */}
        {[3, 2].map(n => (
          <div
            key={n}
            style={{
              position: "absolute",
              inset: 0,
              background: `hsl(42, 35%, ${82 - n * 3}%)`,
              borderRadius: 2,
              transform: `translate(${n * 3}px, ${n * 2}px)`,
              zIndex: n,
            }}
          />
        ))}

        {/* ── Main journal page ── */}
        <div
          style={{
            position: "relative",
            zIndex: 10,
            width: "100%",
            height: "100%",
            background: "linear-gradient(180deg, #f5eccd 0%, #f0e4ba 100%)",
            borderRadius: 2,
            display: "flex",
            overflow: "hidden",
            opacity: turning ? 0 : 1,
            transform: turning ? "rotateY(8deg) scale(0.98)" : "none",
            transition: "opacity 0.25s ease, transform 0.25s ease",
          }}
        >
          {/* ── Spiral binding ── */}
          <div
            style={{
              width: 36,
              flexShrink: 0,
              background: "linear-gradient(180deg, #d4c89a 0%, #c8b87e 100%)",
              borderRight: "2px solid #b8a060",
              position: "relative",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              paddingTop: 28,
              gap: 24,
              zIndex: 2,
            }}
          >
            {Array.from({ length: 17 }).map((_, i) => (
              <div
                key={i}
                style={{
                  width: 22,
                  height: 14,
                  borderRadius: 7,
                  border: "2.5px solid #7a6030",
                  background: "linear-gradient(180deg, #888 30%, #444)",
                  flexShrink: 0,
                  boxShadow: "inset 0 1px 2px rgba(0,0,0,0.3), 1px 1px 2px rgba(0,0,0,0.2)",
                }}
              />
            ))}
          </div>

          {/* ── Page content ── */}
          <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>
            {/* Horizontal ruled lines */}
            <svg
              style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}
              preserveAspectRatio="none"
            >
              {Array.from({ length: LINE_COUNT }).map((_, i) => (
                <line
                  key={i}
                  x1="0" y1={56 + i * LINE_H}
                  x2="100%" y2={56 + i * LINE_H}
                  stroke="#c4a85040"
                  strokeWidth="1"
                />
              ))}
              {/* Red margin line */}
              <line x1="72" y1="0" x2="72" y2="100%" stroke="#c0403060" strokeWidth="1.5" />
            </svg>

            {/* Top header strip */}
            <div
              style={{
                position: "absolute",
                top: 0, left: 0, right: 0,
                height: 48,
                background: "linear-gradient(180deg, #e8d898 0%, rgba(232,216,152,0) 100%)",
                borderBottom: "1.5px solid #c4a85060",
                display: "flex",
                alignItems: "center",
                paddingLeft: 88,
                paddingRight: 24,
                gap: 12,
              }}
            >
              <span style={{ color: "#5a4010", fontSize: 13, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", opacity: 0.7 }}>
                Python Learning Journal
              </span>
              <span style={{ color: "#8a6828", fontSize: 11, opacity: 0.6 }}>·</span>
              <span style={{ color: "#8a6828", fontSize: 11, opacity: 0.6 }}>Digital Dynamics</span>
              <span style={{ marginLeft: "auto", color: "#8a6828", fontSize: 11, opacity: 0.6, fontStyle: "italic" }}>
                p.{entry.pageNum} / {entries.length}
              </span>
            </div>

            {/* Main content */}
            <div style={{ paddingLeft: 88, paddingRight: 28, paddingTop: 58, paddingBottom: 12 }}>
              {/* Date + day in margin area (positioned left of margin line) */}
              <div
                style={{
                  position: "absolute",
                  left: 38,
                  top: 56,
                  width: 28,
                  textAlign: "center",
                }}
              >
                <div style={{ color: "#8a6828", fontSize: 9, fontWeight: 700, lineHeight: 1.2, opacity: 0.8 }}>{entry.day.slice(0,3).toUpperCase()}</div>
                <div style={{ color: "#5a4010", fontSize: 14, fontWeight: 700, lineHeight: 1 }}>{entry.date.split(" ")[1]}</div>
                <div style={{ color: "#8a6828", fontSize: 8, lineHeight: 1.2, opacity: 0.7 }}>{entry.date.split(" ")[0].toUpperCase()}</div>
              </div>

              {/* Title — on the line */}
              <div style={{ lineHeight: `${LINE_H}px`, marginBottom: 0 }}>
                <h2
                  style={{
                    color: "#1a2c4a",
                    fontSize: 19,
                    fontWeight: 700,
                    fontStyle: "italic",
                    margin: 0,
                    lineHeight: `${LINE_H}px`,
                    letterSpacing: "0.01em",
                  }}
                >
                  {entry.title}
                </h2>
              </div>

              {/* Divider — looks like an underline drawn by hand */}
              <div
                style={{
                  height: 2,
                  background: "linear-gradient(90deg, #1a2c4a80, transparent)",
                  borderRadius: 1,
                  margin: "4px 0 8px",
                  width: "70%",
                }}
              />

              {/* Code block — typewriter-on-paper look */}
              <div
                style={{
                  background: "rgba(0,0,0,0.04)",
                  border: "1px solid rgba(139,104,40,0.25)",
                  borderRadius: 3,
                  padding: "10px 14px",
                  marginBottom: 10,
                  position: "relative",
                  boxShadow: "inset 0 1px 3px rgba(0,0,0,0.06)",
                }}
              >
                {/* Tape strip top-left */}
                <div
                  style={{
                    position: "absolute",
                    top: -6,
                    left: 20,
                    width: 48,
                    height: 12,
                    background: "rgba(200,180,120,0.45)",
                    borderRadius: 2,
                    transform: "rotate(-1deg)",
                  }}
                />
                <pre
                  style={{
                    margin: 0,
                    fontSize: 11,
                    lineHeight: "18px",
                    color: "#1a2c4a",
                    fontFamily: "'Courier New', Courier, monospace",
                    whiteSpace: "pre-wrap",
                    letterSpacing: "0.02em",
                  }}
                >
                  {entry.code}
                </pre>
              </div>

              {/* Handwritten note */}
              <p
                style={{
                  color: "#2c4a1a",
                  fontSize: 13,
                  fontStyle: "italic",
                  lineHeight: `${LINE_H}px`,
                  margin: "0 0 10px",
                  letterSpacing: "0.01em",
                }}
              >
                ↳ {entry.note}
              </p>

              {/* Tags — look like rubber stamps */}
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {entry.tags.map(t => (
                  <span
                    key={t}
                    style={{
                      border: "1.5px solid #8a682870",
                      color: "#8a6828",
                      borderRadius: 2,
                      padding: "1px 7px",
                      fontSize: 10,
                      fontFamily: "monospace",
                      letterSpacing: "0.05em",
                      opacity: 0.85,
                      textTransform: "lowercase",
                    }}
                  >
                    #{t}
                  </span>
                ))}
              </div>
            </div>

            {/* ── Bottom navigation ── */}
            <div
              style={{
                position: "absolute",
                bottom: 0, left: 36, right: 0,
                height: 40,
                borderTop: "1px solid #c4a85040",
                display: "flex",
                alignItems: "center",
                paddingLeft: 52,
                paddingRight: 24,
                gap: 12,
                background: "linear-gradient(0deg, #e8d898 0%, rgba(232,216,152,0) 100%)",
              }}
            >
              <button
                onClick={() => goTo(page - 1)}
                disabled={page === 0}
                style={{
                  background: "none",
                  border: "none",
                  color: page === 0 ? "#c4a850a0" : "#5a4010",
                  cursor: page === 0 ? "default" : "pointer",
                  fontSize: 16,
                  padding: "0 4px",
                  fontFamily: "serif",
                }}
              >
                ←
              </button>
              <div style={{ display: "flex", gap: 8, flex: 1, justifyContent: "center" }}>
                {entries.map((_, i) => (
                  <button
                    key={i}
                    onClick={() => goTo(i)}
                    style={{
                      width: i === page ? 24 : 8,
                      height: 8,
                      borderRadius: 4,
                      background: i === page ? "#5a4010" : "#c4a850",
                      border: "none",
                      cursor: "pointer",
                      padding: 0,
                      opacity: i === page ? 1 : 0.5,
                      transition: "all 0.25s",
                    }}
                  />
                ))}
              </div>
              <button
                onClick={() => goTo(page + 1)}
                disabled={page === entries.length - 1}
                style={{
                  background: "none",
                  border: "none",
                  color: page === entries.length - 1 ? "#c4a850a0" : "#5a4010",
                  cursor: page === entries.length - 1 ? "default" : "pointer",
                  fontSize: 16,
                  padding: "0 4px",
                  fontFamily: "serif",
                }}
              >
                →
              </button>
              <span style={{ color: "#8a6828", fontSize: 10, opacity: 0.6, fontStyle: "italic", position: "absolute", right: 24 }}>
                {entry.day}, {entry.date} {entry.year}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
