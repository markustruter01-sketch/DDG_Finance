import { useState } from "react";

const LINE_H = 24;

const entries = [
  {
    date: "15", month: "MAY", day: "FRI", page: 1,
    title: "Generators & Lazy Evaluation",
    code: `def fibonacci():
    a, b = 0, 1
    while True:
        yield a          # pause & return value
        a, b = b, a + b  # resume here next call

gen = fibonacci()
# Only computed on demand — memory stays flat
result = [next(gen) for _ in range(6)]
# → [0, 1, 1, 2, 3, 5, 8, 13]`,
    insight: "Generators don't compute until you ask — like a bot in standby waiting for market open. No wasted CPU cycles.",
    tradingWhy: "Current bots load full trade history into memory on startup, causing a 2–4s delay before the first signal fires. Replacing list comprehensions with generators in the data pipeline means equity snapshots stream one-at-a-time rather than loading 5,000 rows upfront.",
    bullets: [
      "Replace alpaca_data loader with a generator — cuts startup RAM from ~180MB to ~12MB",
      "Pair with asyncio.Queue so Davy Jones & Blackbeard can pull candles independently at their own pace",
      "Generator-based backtester will let me replay any date range without holding the full OHLCV set",
    ],
    next: "Study: itertools.islice, itertools.chain — chaining generators across multiple data sources",
    tags: ["generators", "yield", "memory", "iterators"],
  },
  {
    date: "12", month: "MAY", day: "TUE", page: 2,
    title: "Decorators as Middleware",
    code: `from functools import wraps

def rate_limit(delay=0.1):
    def decorator(fn):
        @wraps(fn)          # preserves fn.__name__
        def wrapper(*a, **kw):
            time.sleep(delay)
            return fn(*a, **kw)
        return wrapper
    return decorator

@rate_limit(delay=0.2)
def place_order(symbol, qty, side): ...`,
    insight: "A decorator injects behaviour around a function without touching its body — the same principle as middleware layers in the API stack.",
    tradingWhy: "The Kraken REST client currently has rate-limiting copy-pasted into four different call sites. One @rate_limit decorator replaces all four, and adding @retry_on_stale and @log_latency stacks cleanly on top without any changes to the underlying order logic.",
    bullets: [
      "@retry_on_429 around every Kraken REST call — handles burst rejections without crashing the bot",
      "@require_market_open gates any order placement — one decorator replaces 11 scattered if-checks",
      "@audit_trail logs entry/exit equity automatically, feeding the Math Auditor without manual instrumentation",
    ],
    next: "Study: class-based decorators, __call__ protocol — needed for stateful decorators that track per-symbol history",
    tags: ["decorators", "closures", "HOF", "middleware"],
  },
  {
    date: "8", month: "MAY", day: "FRI", page: 3,
    title: "Context Managers & Guaranteed Cleanup",
    code: `from contextlib import contextmanager

@contextmanager
def live_position(symbol: str):
    pos = open_position(symbol)
    try:
        yield pos           # bot logic runs here
    except Exception as e:
        emergency_close(pos, reason=str(e))
        raise
    finally:
        log_position_closed(pos)  # always runs`,
    insight: "The with block guarantees cleanup even on crash or exception — exactly what live position management needs when a bot dies mid-trade.",
    tradingWhy: "Right now, if Poseidon crashes mid-position, the close logic never fires and the position stays open until manual intervention. Wrapping all position entry/exit in a context manager means crash = guaranteed close, every time, with full audit logging in the finally block.",
    bullets: [
      "Wrap every bot's main loop in with live_position() — orphaned positions drop to near-zero risk",
      "DB connection pooling via @contextmanager eliminates the 'too many connections' errors hitting Neon at peak",
      "Use contextlib.suppress for known-safe errors (e.g., closing an already-closed position) instead of bare try/except",
    ],
    next: "Study: contextlib.ExitStack — stacking multiple context managers for multi-leg trade entry sequences",
    tags: ["context", "RAII", "cleanup", "error-handling"],
  },
];

export default function StreamingLearningScreen() {
  const [page, setPage] = useState(0);
  const [turning, setTurning] = useState(false);
  const entry = entries[page];

  function goTo(idx: number) {
    if (idx === page || turning || idx < 0 || idx >= entries.length) return;
    setTurning(true);
    setTimeout(() => { setPage(idx); setTurning(false); }, 230);
  }

  return (
    <div style={{
      width: "100%",
      height: "100%",
      background: "radial-gradient(ellipse at 50% 35%, #0c1a0e 0%, #020617 100%)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: "20px 48px 72px",
      boxSizing: "border-box",
      overflow: "hidden",
    }}>
      <div style={{
        width: "100%",
        maxWidth: 960,
        height: "100%",
        maxHeight: 580,
        position: "relative",
        filter: "drop-shadow(0 16px 48px rgba(0,0,0,.75))",
      }}>
        {/* Stacked page backs */}
        {[3, 2].map(n => (
          <div key={n} style={{
            position: "absolute", inset: 0,
            background: `hsl(42,28%,${78 - n * 4}%)`,
            borderRadius: 2,
            transform: `translate(${n * 4}px, ${n * 2}px)`,
            zIndex: n,
          }} />
        ))}

        {/* Main page */}
        <div style={{
          position: "relative", zIndex: 10,
          width: "100%", height: "100%",
          background: "linear-gradient(180deg,#f5eccd 0%,#efe2b2 100%)",
          borderRadius: 2,
          display: "flex",
          overflow: "hidden",
          opacity: turning ? 0 : 1,
          transform: turning ? "rotateY(6deg) scale(.98)" : "none",
          transition: "opacity .23s ease, transform .23s ease",
        }}>

          {/* Spiral binding */}
          <div style={{
            width: 36, flexShrink: 0,
            background: "linear-gradient(180deg,#d4c89a,#c8b87e)",
            borderRight: "2px solid #b8a060",
            display: "flex", flexDirection: "column",
            alignItems: "center", paddingTop: 20, gap: 20, zIndex: 2,
          }}>
            {Array.from({ length: 20 }).map((_, i) => (
              <div key={i} style={{
                width: 22, height: 12,
                borderRadius: 7,
                border: "2.5px solid #7a6030",
                background: "linear-gradient(180deg,#999 30%,#444)",
                flexShrink: 0,
                boxShadow: "inset 0 1px 2px rgba(0,0,0,.3), 1px 1px 2px rgba(0,0,0,.2)",
              }} />
            ))}
          </div>

          {/* Page body */}
          <div style={{ flex: 1, position: "relative", overflow: "hidden" }}>

            {/* Ruled lines */}
            <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }} preserveAspectRatio="none">
              {Array.from({ length: 22 }).map((_, i) => (
                <line key={i} x1="0" y1={48 + i * LINE_H} x2="100%" y2={48 + i * LINE_H} stroke="#c4a85036" strokeWidth="1" />
              ))}
              <line x1="68" y1="0" x2="68" y2="100%" stroke="#c0403050" strokeWidth="1.5" />
            </svg>

            {/* Header strip */}
            <div style={{
              position: "absolute", top: 0, left: 0, right: 0, height: 40,
              background: "linear-gradient(180deg,#e6d490,rgba(230,212,144,0))",
              borderBottom: "1.5px solid #c4a85050",
              display: "flex", alignItems: "center",
              paddingLeft: 80, paddingRight: 18, gap: 10,
            }}>
              <span style={{ color: "#5a4010", fontSize: 11, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", opacity: .7, fontFamily: "Georgia,serif" }}>
                Python Learning Journal
              </span>
              <span style={{ color: "#8a6828", opacity: .45, fontSize: 11 }}>—</span>
              <span style={{ color: "#8a6828", fontSize: 10, opacity: .5, fontFamily: "Georgia,serif" }}>Digital Dynamics</span>
              <span style={{ marginLeft: "auto", color: "#8a6828", fontSize: 10, opacity: .55, fontStyle: "italic", fontFamily: "Georgia,serif" }}>
                p.{entry.page} / {entries.length}
              </span>
            </div>

            {/* Date in margin */}
            <div style={{ position: "absolute", left: 4, top: 46, width: 60, textAlign: "center" }}>
              <div style={{ color: "#8a6828", fontSize: 8, fontWeight: 700, opacity: .7 }}>{entry.day}</div>
              <div style={{ color: "#5a4010", fontSize: 17, fontWeight: 800, lineHeight: 1.1, fontFamily: "Georgia,serif" }}>{entry.date}</div>
              <div style={{ color: "#8a6828", fontSize: 8, opacity: .6 }}>{entry.month}</div>
            </div>

            {/* Content */}
            <div style={{ paddingLeft: 80, paddingRight: 22, paddingTop: 46, paddingBottom: 40 }}>

              {/* Title */}
              <h2 style={{
                color: "#1a2c4a", fontSize: 18, fontWeight: 700, fontStyle: "italic",
                margin: "0 0 3px", lineHeight: `${LINE_H}px`,
                fontFamily: "Georgia,serif", letterSpacing: ".01em",
              }}>
                {entry.title}
              </h2>
              <div style={{ height: 2, margin: "0 0 7px", background: "linear-gradient(90deg,#1a2c4a65,transparent)", borderRadius: 1, width: "55%" }} />

              {/* Code block */}
              <div style={{
                background: "rgba(0,0,0,.045)",
                border: "1px solid rgba(139,104,40,.2)",
                borderRadius: 3, padding: "8px 12px", marginBottom: 8,
                position: "relative",
                boxShadow: "inset 0 1px 3px rgba(0,0,0,.05)",
              }}>
                <div style={{ position: "absolute", top: -6, left: 20, width: 46, height: 12, background: "rgba(200,180,120,.38)", borderRadius: 2, transform: "rotate(-1.2deg)" }} />
                <pre style={{ margin: 0, fontSize: 10.5, lineHeight: "17px", color: "#1a2c4a", fontFamily: "'Courier New',monospace", whiteSpace: "pre-wrap", letterSpacing: ".01em" }}>
                  {entry.code}
                </pre>
              </div>

              {/* Key insight */}
              <p style={{ color: "#1f4a28", fontSize: 12.5, fontStyle: "italic", lineHeight: "20px", margin: "0 0 9px", fontFamily: "Georgia,serif" }}>
                ↳ {entry.insight}
              </p>

              {/* Thin divider */}
              <div style={{ height: 1, background: "linear-gradient(90deg,#c4a85045,transparent)", margin: "0 0 8px", width: "80%" }} />

              {/* Trading impact */}
              <div style={{ marginBottom: 8 }}>
                <span style={{ color: "#5a4010", fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".1em", fontFamily: "monospace", opacity: .75 }}>
                  ⬡ Impact on Future Trades
                </span>
                <p style={{ color: "#2c3e2a", fontSize: 11.5, lineHeight: "19px", margin: "3px 0 0", fontFamily: "Georgia,serif" }}>
                  {entry.tradingWhy}
                </p>
              </div>

              {/* Action items */}
              <div style={{ marginBottom: 8 }}>
                <span style={{ color: "#5a4010", fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".1em", fontFamily: "monospace", opacity: .75 }}>
                  ⬡ Action Items
                </span>
                <ul style={{ margin: "4px 0 0", paddingLeft: 14, listStyle: "none" }}>
                  {entry.bullets.map((b, i) => (
                    <li key={i} style={{ color: "#2c3e2a", fontSize: 11, lineHeight: "18px", marginBottom: 2, display: "flex", gap: 6, alignItems: "flex-start", fontFamily: "Georgia,serif" }}>
                      <span style={{ color: "#8a6828", flexShrink: 0, marginTop: 1 }}>→</span>
                      {b}
                    </li>
                  ))}
                </ul>
              </div>

              {/* Next steps */}
              <div style={{ borderTop: "1px dashed #c4a85040", paddingTop: 6, marginBottom: 8 }}>
                <span style={{ color: "#5a4010", fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".1em", fontFamily: "monospace", opacity: .75 }}>✏ Next — </span>
                <span style={{ color: "#5a3a10", fontSize: 11, fontStyle: "italic", fontFamily: "Georgia,serif" }}>{entry.next}</span>
              </div>

              {/* Tags */}
              <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                {entry.tags.map(t => (
                  <span key={t} style={{ border: "1.5px solid #8a682858", color: "#8a6828", borderRadius: 2, padding: "1px 7px", fontSize: 10, fontFamily: "monospace", letterSpacing: ".04em", opacity: .8 }}>
                    #{t}
                  </span>
                ))}
              </div>
            </div>

            {/* Bottom nav strip */}
            <div style={{
              position: "absolute", bottom: 0, left: 0, right: 0, height: 36,
              borderTop: "1px solid #c4a85038",
              display: "flex", alignItems: "center",
              paddingLeft: 80, paddingRight: 18, gap: 10,
              background: "linear-gradient(0deg,#e6d490,rgba(230,212,144,0))",
            }}>
              <button
                onClick={() => goTo(page - 1)}
                disabled={page === 0}
                style={{ background: "none", border: "none", color: page === 0 ? "#c4a85070" : "#5a4010", cursor: page === 0 ? "default" : "pointer", fontSize: 15, fontFamily: "serif", padding: "0 4px" }}
              >←</button>
              <div style={{ flex: 1, display: "flex", justifyContent: "center", gap: 8 }}>
                {entries.map((_, i) => (
                  <button
                    key={i}
                    onClick={() => goTo(i)}
                    style={{ width: i === page ? 22 : 7, height: 7, borderRadius: 4, background: i === page ? "#5a4010" : "#c4a850", border: "none", cursor: "pointer", padding: 0, opacity: i === page ? 1 : .45, transition: "all .25s" }}
                  />
                ))}
              </div>
              <button
                onClick={() => goTo(page + 1)}
                disabled={page === entries.length - 1}
                style={{ background: "none", border: "none", color: page === entries.length - 1 ? "#c4a85070" : "#5a4010", cursor: page === entries.length - 1 ? "default" : "pointer", fontSize: 15, fontFamily: "serif", padding: "0 4px" }}
              >→</button>
              <span style={{ position: "absolute", right: 18, color: "#8a6828", fontSize: 9.5, opacity: .5, fontStyle: "italic", fontFamily: "Georgia,serif" }}>
                {entry.day}, {entry.date} {entry.month} 2026
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
