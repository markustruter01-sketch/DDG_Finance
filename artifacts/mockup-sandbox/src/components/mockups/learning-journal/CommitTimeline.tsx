import { useEffect, useState } from "react";

const commits = [
  { hash: "a3f8c2d", msg: "feat(generators): lazy eval & yield keyword", date: "3h ago", xp: "+120 XP", branch: "python/core", files: 2, lines: "+47 -3", color: "#22d3ee", tags: ["yield", "memory"] },
  { hash: "b91e047", msg: "feat(decorators): higher-order fn wrapping", date: "2d ago", xp: "+95 XP", branch: "python/patterns", files: 1, lines: "+33 -0", color: "#a78bfa", tags: ["closures", "HOF"] },
  { hash: "c5d3a19", msg: "feat(context-mgr): with statement & RAII", date: "5d ago", xp: "+80 XP", branch: "python/core", files: 3, lines: "+62 -8", color: "#34d399", tags: ["cleanup", "ctx"] },
  { hash: "f2b8e61", msg: "fix(async): asyncio event loop understanding", date: "8d ago", xp: "+140 XP", branch: "python/async", files: 2, lines: "+55 -12", color: "#f59e0b", tags: ["async", "await"] },
  { hash: "d7c0f44", msg: "feat(dataclasses): typed attrs & __post_init__", date: "12d ago", xp: "+70 XP", branch: "python/typing", files: 1, lines: "+28 -0", color: "#f97316", tags: ["types", "OOP"] },
];

export function CommitTimeline() {
  const [hovered, setHovered] = useState<number | null>(null);
  const [visible, setVisible] = useState<number[]>([]);

  useEffect(() => {
    commits.forEach((_, i) => {
      setTimeout(() => setVisible(v => [...v, i]), i * 250 + 100);
    });
  }, []);

  return (
    <div
      className="min-h-screen w-full p-8"
      style={{ background: "linear-gradient(135deg, #0d1117 0%, #161b22 100%)", fontFamily: "monospace" }}
    >
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center gap-3 mb-8">
          <div className="text-2xl">⬡</div>
          <div>
            <h1 style={{ color: "#e6edf3", fontSize: 20, fontWeight: 700, letterSpacing: "0.02em" }}>
              python-learning
            </h1>
            <p style={{ color: "#7d8590", fontSize: 12 }}>feat/core-concepts · {commits.length} commits ahead</p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <div style={{ background: "#238636", borderRadius: 20, padding: "4px 12px", fontSize: 11, color: "#3fb950" }}>
              ● main
            </div>
          </div>
        </div>

        <div style={{ position: "relative" }}>
          <div
            style={{
              position: "absolute",
              left: 19,
              top: 0,
              bottom: 0,
              width: 2,
              background: "linear-gradient(to bottom, #21262d, #21262d 90%, transparent)",
            }}
          />

          <div className="space-y-3">
            {commits.map((c, i) => (
              <div
                key={i}
                className="flex gap-4 cursor-pointer"
                style={{
                  opacity: visible.includes(i) ? 1 : 0,
                  transform: visible.includes(i) ? "translateX(0)" : "translateX(-20px)",
                  transition: "all 0.4s ease",
                }}
                onMouseEnter={() => setHovered(i)}
                onMouseLeave={() => setHovered(null)}
              >
                <div style={{ position: "relative", flexShrink: 0, paddingTop: 12 }}>
                  <div
                    style={{
                      width: 16,
                      height: 16,
                      borderRadius: "50%",
                      background: hovered === i ? c.color : "#21262d",
                      border: `2px solid ${c.color}`,
                      boxShadow: hovered === i ? `0 0 12px ${c.color}` : "none",
                      transition: "all 0.2s",
                      zIndex: 1,
                      position: "relative",
                    }}
                  />
                </div>

                <div
                  style={{
                    flex: 1,
                    background: hovered === i ? "rgba(255,255,255,0.04)" : "rgba(255,255,255,0.02)",
                    border: `1px solid ${hovered === i ? c.color + "40" : "rgba(255,255,255,0.06)"}`,
                    borderRadius: 8,
                    padding: "10px 14px",
                    transition: "all 0.2s",
                  }}
                >
                  <div className="flex items-start justify-between gap-2 flex-wrap">
                    <div className="flex items-center gap-2">
                      <span style={{ color: c.color, fontSize: 11, fontWeight: 700 }}>{c.hash}</span>
                      <span style={{ color: "#e6edf3", fontSize: 13 }}>{c.msg}</span>
                    </div>
                    <span
                      style={{
                        background: "rgba(46,160,67,0.15)",
                        border: "1px solid rgba(46,160,67,0.3)",
                        color: "#3fb950",
                        fontSize: 10,
                        borderRadius: 4,
                        padding: "2px 7px",
                        flexShrink: 0,
                      }}
                    >
                      {c.xp}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 mt-2 flex-wrap">
                    <span style={{ color: "#7d8590", fontSize: 11 }}>🕐 {c.date}</span>
                    <span style={{ color: "#7d8590", fontSize: 11 }}>📂 {c.branch}</span>
                    <span style={{ color: "#7d8590", fontSize: 11 }}>📄 {c.files} files</span>
                    <span style={{ color: "#3fb950", fontSize: 11 }}>+</span>
                    <span style={{ color: "#f85149", fontSize: 11 }}>{c.lines}</span>
                  </div>
                  <div className="flex gap-1 mt-2 flex-wrap">
                    {c.tags.map(t => (
                      <span
                        key={t}
                        style={{
                          background: "rgba(255,255,255,0.05)",
                          border: "1px solid rgba(255,255,255,0.08)",
                          color: c.color,
                          fontSize: 10,
                          borderRadius: 3,
                          padding: "1px 6px",
                        }}
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-8 p-4" style={{ background: "rgba(255,255,255,0.02)", borderRadius: 8, border: "1px solid rgba(255,255,255,0.06)" }}>
          <div className="flex items-center justify-between">
            <span style={{ color: "#7d8590", fontSize: 12 }}>Total XP earned</span>
            <span style={{ color: "#f59e0b", fontSize: 18, fontWeight: 700 }}>+505 XP</span>
          </div>
          <div style={{ background: "#21262d", borderRadius: 4, height: 6, marginTop: 8 }}>
            <div style={{ background: "linear-gradient(90deg, #f59e0b, #f97316)", width: "67%", height: "100%", borderRadius: 4 }} />
          </div>
          <div className="flex justify-between mt-1">
            <span style={{ color: "#7d8590", fontSize: 10 }}>Level 6</span>
            <span style={{ color: "#7d8590", fontSize: 10 }}>505 / 750 XP → Level 7</span>
          </div>
        </div>
      </div>
    </div>
  );
}
