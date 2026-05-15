import { useEffect, useState } from "react";

const skills = [
  { name: "Core Python",     xp: 840, max: 1000, color: "#f59e0b", icon: "🐍", level: 8, topics: ["syntax", "types", "control flow"] },
  { name: "Iterators",       xp: 520, max: 1000, color: "#22d3ee", icon: "⟳", level: 5, topics: ["generators", "yield", "lazy eval"] },
  { name: "Patterns",        xp: 390, max: 1000, color: "#a78bfa", icon: "◈", level: 3, topics: ["decorators", "closures", "HOF"] },
  { name: "Async",           xp: 710, max: 1000, color: "#f97316", icon: "⚡", level: 7, topics: ["asyncio", "event loop", "tasks"] },
  { name: "Type System",     xp: 260, max: 1000, color: "#ec4899", icon: "T",  level: 2, topics: ["hints", "dataclass", "Protocol"] },
  { name: "Meta / Advanced", xp: 120, max: 1000, color: "#64748b", icon: "∞", level: 1, topics: ["metaclass", "slots", "__dunder__"] },
];

const recentUnlocks = [
  { icon: "🏆", name: "Yield Master",     desc: "Wrote 5 generator functions",    rarity: "RARE",    color: "#f59e0b" },
  { icon: "🎖️", name: "Wrap Artist",      desc: "Used decorators in production",  rarity: "UNCOMMON", color: "#a78bfa" },
  { icon: "⚡", name: "Non-Blocking",     desc: "First asyncio coroutine shipped", rarity: "EPIC",    color: "#f97316" },
];

export function XPLedger() {
  const [bars, setBars] = useState<number[]>(skills.map(() => 0));

  useEffect(() => {
    skills.forEach((s, i) => {
      setTimeout(() => {
        setBars(prev => {
          const next = [...prev];
          next[i] = (s.xp / s.max) * 100;
          return next;
        });
      }, i * 180 + 300);
    });
  }, []);

  const totalXP = skills.reduce((a, s) => a + s.xp, 0);
  const overallLevel = Math.floor(totalXP / 500);

  return (
    <div
      className="min-h-screen w-full p-6 overflow-y-auto"
      style={{
        background: "linear-gradient(180deg, #0c0e14 0%, #0f1117 100%)",
        fontFamily: "'Inter', sans-serif",
      }}
    >
      <div className="max-w-2xl mx-auto space-y-5">
        <div className="flex items-center justify-between p-4 rounded-xl" style={{ background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.2)" }}>
          <div className="flex items-center gap-4">
            <div
              style={{
                width: 56, height: 56, borderRadius: "50%",
                background: "linear-gradient(135deg, #f59e0b, #f97316)",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 24, boxShadow: "0 0 24px rgba(245,158,11,0.4)",
              }}
            >🧙</div>
            <div>
              <div style={{ color: "#f5e6c8", fontSize: 18, fontWeight: 800 }}>Python Apprentice</div>
              <div style={{ color: "#92400e", fontSize: 12 }}>Digital Dynamics Trading Bot Dev</div>
            </div>
          </div>
          <div className="text-right">
            <div style={{ color: "#f59e0b", fontSize: 32, fontWeight: 900, lineHeight: 1 }}>LVL {overallLevel}</div>
            <div style={{ color: "#92400e", fontSize: 11 }}>{totalXP.toLocaleString()} total XP</div>
          </div>
        </div>

        <div>
          <div style={{ color: "#475569", fontSize: 11, letterSpacing: "0.1em", marginBottom: 10 }}>SKILL TREE</div>
          <div className="space-y-3">
            {skills.map((s, i) => (
              <div key={s.name} className="p-3 rounded-lg" style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.05)" }}>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span style={{ fontSize: 16 }}>{s.icon}</span>
                    <span style={{ color: "#e2e8f0", fontSize: 13, fontWeight: 600 }}>{s.name}</span>
                    <div className="flex gap-1 ml-1">
                      {s.topics.map(t => (
                        <span key={t} style={{ color: s.color, fontSize: 9, background: `${s.color}15`, border: `1px solid ${s.color}30`, borderRadius: 3, padding: "1px 5px" }}>{t}</span>
                      ))}
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span style={{ color: "#475569", fontSize: 11 }}>{s.xp}/{s.max} XP</span>
                    <span style={{ color: s.color, fontSize: 12, fontWeight: 700, minWidth: 52, textAlign: "right" }}>LVL {s.level}</span>
                  </div>
                </div>
                <div style={{ background: "rgba(255,255,255,0.06)", borderRadius: 4, height: 6, overflow: "hidden" }}>
                  <div
                    style={{
                      height: "100%",
                      borderRadius: 4,
                      background: `linear-gradient(90deg, ${s.color}cc, ${s.color})`,
                      width: `${bars[i]}%`,
                      transition: "width 1s cubic-bezier(0.4,0,0.2,1)",
                      boxShadow: `0 0 8px ${s.color}60`,
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        <div>
          <div style={{ color: "#475569", fontSize: 11, letterSpacing: "0.1em", marginBottom: 10 }}>RECENT UNLOCKS</div>
          <div className="space-y-2">
            {recentUnlocks.map((u, i) => (
              <div key={i} className="flex items-center gap-3 p-3 rounded-lg" style={{ background: `${u.color}08`, border: `1px solid ${u.color}25` }}>
                <span style={{ fontSize: 20 }}>{u.icon}</span>
                <div className="flex-1">
                  <div style={{ color: "#e2e8f0", fontSize: 13, fontWeight: 600 }}>{u.name}</div>
                  <div style={{ color: "#64748b", fontSize: 11 }}>{u.desc}</div>
                </div>
                <span style={{ color: u.color, fontSize: 10, fontWeight: 700, background: `${u.color}15`, border: `1px solid ${u.color}30`, borderRadius: 4, padding: "3px 8px" }}>{u.rarity}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
