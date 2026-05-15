import { useEffect, useState } from "react";

const entries = [
  {
    date: "May 15, 2026",
    title: "Generators & Lazy Evaluation",
    code: `def fibonacci():\n    a, b = 0, 1\n    while True:\n        yield a\n        a, b = b, a + b`,
    note: "Generators don't compute until you ask. Like a bot waiting for market open — no wasted cycles.",
    tags: ["generators", "memory", "iterators"],
    ink: "#22d3ee",
  },
  {
    date: "May 12, 2026",
    title: "Decorators as Middleware",
    code: `def rate_limit(fn):\n    @wraps(fn)\n    def wrapper(*args):\n        time.sleep(0.1)\n        return fn(*args)\n    return wrapper`,
    note: "A decorator wraps behaviour around a function — same concept as the API rate-limiter on Kraken.",
    tags: ["decorators", "closures", "higher-order"],
    ink: "#a78bfa",
  },
  {
    date: "May 8, 2026",
    title: "Context Managers & with",
    code: `class DBConn:\n    def __enter__(self): return connect()\n    def __exit__(self, *_): self.close()`,
    note: "The with block guarantees cleanup even on crash. Same guarantee I want for position exit logic.",
    tags: ["context", "RAII", "cleanup"],
    ink: "#34d399",
  },
];

export function ScrollInk() {
  const [visible, setVisible] = useState<number[]>([]);

  useEffect(() => {
    entries.forEach((_, i) => {
      setTimeout(() => setVisible(v => [...v, i]), i * 400 + 200);
    });
  }, []);

  return (
    <div
      className="min-h-screen w-full p-8 overflow-y-auto"
      style={{
        background: "radial-gradient(ellipse at 20% 0%, #0d1117 0%, #0a0c10 100%)",
        fontFamily: "'Georgia', 'Times New Roman', serif",
      }}
    >
      <div className="max-w-2xl mx-auto">
        <div className="flex items-center gap-3 mb-10">
          <div className="text-3xl">📜</div>
          <div>
            <h1 style={{ color: "#f5e6c8", fontSize: 22, fontWeight: 700, letterSpacing: "0.04em" }}>
              Python Learning Journal
            </h1>
            <p style={{ color: "#8b7355", fontSize: 12, marginTop: 2 }}>captain's log · digital dynamics v2.0</p>
          </div>
          <div className="ml-auto text-right">
            <div style={{ color: "#8b7355", fontSize: 10, letterSpacing: "0.08em" }}>ENTRIES</div>
            <div style={{ color: "#f5e6c8", fontSize: 22, fontWeight: 700 }}>{entries.length}</div>
          </div>
        </div>

        <div className="space-y-8">
          {entries.map((entry, i) => (
            <div
              key={i}
              className="transition-all duration-700"
              style={{
                opacity: visible.includes(i) ? 1 : 0,
                transform: visible.includes(i) ? "translateY(0)" : "translateY(16px)",
                borderLeft: `3px solid ${entry.ink}`,
                paddingLeft: 24,
                position: "relative",
              }}
            >
              <div
                style={{
                  position: "absolute",
                  left: -7,
                  top: 6,
                  width: 11,
                  height: 11,
                  borderRadius: "50%",
                  background: entry.ink,
                  boxShadow: `0 0 8px ${entry.ink}`,
                }}
              />
              <div style={{ color: "#8b7355", fontSize: 11, marginBottom: 4, fontFamily: "monospace" }}>
                {entry.date}
              </div>
              <h2 style={{ color: "#f5e6c8", fontSize: 16, fontWeight: 700, marginBottom: 10 }}>
                {entry.title}
              </h2>
              <pre
                style={{
                  background: "rgba(255,255,255,0.03)",
                  border: `1px solid rgba(${entry.ink === "#22d3ee" ? "34,211,238" : entry.ink === "#a78bfa" ? "167,139,250" : "52,211,153"},0.15)`,
                  borderRadius: 6,
                  padding: "12px 16px",
                  fontSize: 12,
                  color: entry.ink,
                  fontFamily: "'Fira Code', 'Courier New', monospace",
                  overflowX: "auto",
                  lineHeight: 1.7,
                  marginBottom: 10,
                }}
              >
                {entry.code}
              </pre>
              <p style={{ color: "#c9a96e", fontSize: 13, lineHeight: 1.7, fontStyle: "italic", marginBottom: 10 }}>
                "{entry.note}"
              </p>
              <div className="flex gap-2 flex-wrap">
                {entry.tags.map(t => (
                  <span
                    key={t}
                    style={{
                      background: "rgba(255,255,255,0.04)",
                      border: "1px solid rgba(255,255,255,0.1)",
                      color: "#8b7355",
                      borderRadius: 4,
                      padding: "2px 8px",
                      fontSize: 10,
                      fontFamily: "monospace",
                    }}
                  >
                    #{t}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="mt-12 pt-6" style={{ borderTop: "1px solid rgba(255,255,255,0.05)" }}>
          <div className="flex items-center gap-2">
            <div
              style={{
                width: 8,
                height: 16,
                background: "#c9a96e",
                borderRadius: 1,
                animation: "blink 1s step-end infinite",
              }}
            />
            <span style={{ color: "#8b7355", fontSize: 12, fontFamily: "monospace" }}>
              writing next entry...
            </span>
          </div>
        </div>
      </div>
      <style>{`@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }`}</style>
    </div>
  );
}
