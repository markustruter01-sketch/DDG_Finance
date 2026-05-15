import { useEffect, useRef, useState } from "react";

type Node = { id: string; label: string; x: number; y: number; color: string; size: number; level: number };
type Edge = { from: string; to: string };

const nodes: Node[] = [
  { id: "python", label: "Python", x: 400, y: 300, color: "#f59e0b", size: 36, level: 1 },
  { id: "generators", label: "Generators", x: 220, y: 160, color: "#22d3ee", size: 26, level: 2 },
  { id: "decorators", label: "Decorators", x: 580, y: 160, color: "#a78bfa", size: 26, level: 2 },
  { id: "async", label: "Async/Await", x: 180, y: 390, color: "#f97316", size: 24, level: 2 },
  { id: "context", label: "Context Mgr", x: 600, y: 400, color: "#34d399", size: 22, level: 2 },
  { id: "typing", label: "Type Hints", x: 390, y: 480, color: "#ec4899", size: 22, level: 2 },
  { id: "yield", label: "yield", x: 100, y: 80, color: "#22d3ee", size: 16, level: 3 },
  { id: "lazy", label: "lazy eval", x: 300, y: 60, color: "#22d3ee", size: 16, level: 3 },
  { id: "closures", label: "closures", x: 680, y: 80, color: "#a78bfa", size: 16, level: 3 },
  { id: "hof", label: "HOF", x: 740, y: 220, color: "#a78bfa", size: 16, level: 3 },
  { id: "event_loop", label: "event loop", x: 60, y: 300, color: "#f97316", size: 16, level: 3 },
  { id: "dataclass", label: "dataclass", x: 280, y: 530, color: "#ec4899", size: 16, level: 3 },
];

const edges: Edge[] = [
  { from: "python", to: "generators" },
  { from: "python", to: "decorators" },
  { from: "python", to: "async" },
  { from: "python", to: "context" },
  { from: "python", to: "typing" },
  { from: "generators", to: "yield" },
  { from: "generators", to: "lazy" },
  { from: "decorators", to: "closures" },
  { from: "decorators", to: "hof" },
  { from: "async", to: "event_loop" },
  { from: "typing", to: "dataclass" },
];

export function BrainGraph() {
  const [hovered, setHovered] = useState<string | null>(null);
  const [pulse, setPulse] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setPulse(p => (p + 1) % nodes.length), 600);
    return () => clearInterval(id);
  }, []);

  const getNode = (id: string) => nodes.find(n => n.id === id)!;

  return (
    <div
      className="min-h-screen w-full relative overflow-hidden"
      style={{ background: "radial-gradient(ellipse at 50% 40%, #0a0f1e 0%, #050709 100%)" }}
    >
      <div className="absolute inset-0" style={{ backgroundImage: "radial-gradient(circle, rgba(255,255,255,0.03) 1px, transparent 1px)", backgroundSize: "32px 32px" }} />

      <div className="absolute top-6 left-8">
        <h1 style={{ color: "#e2e8f0", fontSize: 20, fontWeight: 700, letterSpacing: "0.04em" }}>
          Knowledge Graph
        </h1>
        <p style={{ color: "#475569", fontSize: 12, marginTop: 2 }}>python learning · 12 nodes · 11 connections</p>
      </div>

      <svg width="100%" height="580" style={{ position: "absolute", top: 60 }}>
        <defs>
          {nodes.map(n => (
            <radialGradient key={n.id} id={`glow-${n.id}`}>
              <stop offset="0%" stopColor={n.color} stopOpacity="0.4" />
              <stop offset="100%" stopColor={n.color} stopOpacity="0" />
            </radialGradient>
          ))}
        </defs>

        {edges.map((e, i) => {
          const a = getNode(e.from);
          const b = getNode(e.to);
          const isActive = hovered === e.from || hovered === e.to;
          return (
            <g key={i}>
              <line x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                stroke={isActive ? a.color : "rgba(255,255,255,0.08)"}
                strokeWidth={isActive ? 2 : 1}
                strokeDasharray={isActive ? "none" : "4 4"}
                style={{ transition: "all 0.3s" }}
              />
              {isActive && (
                <circle r={4} fill={a.color} opacity={0.8}>
                  <animateMotion dur="1.5s" repeatCount="indefinite"
                    path={`M${a.x},${a.y} L${b.x},${b.y}`} />
                </circle>
              )}
            </g>
          );
        })}

        {nodes.map((n, i) => {
          const isHovered = hovered === n.id;
          const isPulsing = pulse === i;
          return (
            <g key={n.id} style={{ cursor: "pointer" }}
              onMouseEnter={() => setHovered(n.id)}
              onMouseLeave={() => setHovered(null)}
            >
              <circle cx={n.x} cy={n.y} r={n.size * 2.5}
                fill={`url(#glow-${n.id})`}
                opacity={isHovered || isPulsing ? 1 : 0.3}
                style={{ transition: "opacity 0.3s" }}
              />
              <circle cx={n.x} cy={n.y} r={n.size}
                fill={isHovered ? n.color : "rgba(0,0,0,0.8)"}
                stroke={n.color}
                strokeWidth={isHovered ? 3 : 2}
                style={{
                  filter: isHovered ? `drop-shadow(0 0 8px ${n.color})` : isPulsing ? `drop-shadow(0 0 4px ${n.color})` : "none",
                  transition: "all 0.3s",
                }}
              />
              <text x={n.x} y={n.y + 1} textAnchor="middle" dominantBaseline="middle"
                fill={isHovered ? "#000" : n.color}
                fontSize={n.level === 1 ? 11 : n.level === 2 ? 9 : 8}
                fontWeight={700}
                fontFamily="monospace"
                style={{ transition: "fill 0.3s", pointerEvents: "none" }}
              >
                {n.label}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="absolute bottom-6 left-8 right-8">
        <div className="flex gap-4 flex-wrap">
          {[
            { color: "#f59e0b", label: "Core" },
            { color: "#22d3ee", label: "Iteration" },
            { color: "#a78bfa", label: "Patterns" },
            { color: "#f97316", label: "Concurrency" },
            { color: "#34d399", label: "Resources" },
            { color: "#ec4899", label: "Types" },
          ].map(l => (
            <div key={l.label} className="flex items-center gap-1.5">
              <div style={{ width: 8, height: 8, borderRadius: "50%", background: l.color }} />
              <span style={{ color: "#64748b", fontSize: 11 }}>{l.label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
