import { useEffect, useState } from "react";

const FORMULAS = [
  { label: "Sharpe",  equation: "S=(Rp-Rf)/σp",  result: "1.63"   },
  { label: "Kelly",   equation: "f*=(bp-q)/b",    result: "13.8%"  },
  { label: "VaR",     equation: "VaR=μ-zσ√t",    result: "$4,820" },
  { label: "Sortino", equation: "S=(Rp-MAR)/σd",  result: "2.12"   },
];

type Pt = { x: number; y: number };

const INPUT_NODES: Pt[] = [
  { x: 100, y: 270 }, { x: 300, y: 270 }, { x: 500, y: 270 }, { x: 700, y: 270 },
];
const HIDDEN1: Pt[] = [
  { x: 170, y: 390 }, { x: 310, y: 380 }, { x: 490, y: 395 }, { x: 630, y: 385 },
];
const HIDDEN2: Pt[] = [
  { x: 240, y: 490 }, { x: 400, y: 480 }, { x: 560, y: 493 },
];
const OUTPUT: Pt = { x: 400, y: 575 };
const PERIPHERAL: Pt[] = [
  { x: 52, y: 360 }, { x: 748, y: 350 }, { x: 140, y: 530 }, { x: 660, y: 525 },
];

const CONN_PAIRS: [Pt, Pt][] = [
  [INPUT_NODES[0], HIDDEN1[0]], [INPUT_NODES[0], HIDDEN1[1]],
  [INPUT_NODES[1], HIDDEN1[0]], [INPUT_NODES[1], HIDDEN1[1]], [INPUT_NODES[1], HIDDEN1[2]],
  [INPUT_NODES[2], HIDDEN1[1]], [INPUT_NODES[2], HIDDEN1[2]], [INPUT_NODES[2], HIDDEN1[3]],
  [INPUT_NODES[3], HIDDEN1[2]], [INPUT_NODES[3], HIDDEN1[3]],
  [HIDDEN1[0], HIDDEN2[0]], [HIDDEN1[0], HIDDEN2[1]],
  [HIDDEN1[1], HIDDEN2[0]], [HIDDEN1[1], HIDDEN2[1]],
  [HIDDEN1[2], HIDDEN2[1]], [HIDDEN1[2], HIDDEN2[2]],
  [HIDDEN1[3], HIDDEN2[1]], [HIDDEN1[3], HIDDEN2[2]],
  [HIDDEN2[0], OUTPUT], [HIDDEN2[1], OUTPUT], [HIDDEN2[2], OUTPUT],
  [PERIPHERAL[0], HIDDEN1[0]], [PERIPHERAL[1], HIDDEN1[3]],
  [PERIPHERAL[2], HIDDEN2[0]], [PERIPHERAL[3], HIDDEN2[2]],
];

const PULSE_DUR = [3, 3.5, 4, 4.5, 5, 3.8, 4.2, 5.5, 3.2, 4.8, 3.6, 5.2, 4.4, 3.9, 5.1, 4.7, 3.3, 5.3, 4.1, 4.9, 3.7, 5.4, 4.6, 3.1, 5.0];

const BOX_W = 158;
const BOX_H = 88;
const BOX_Y = 105;
const TILE_BOTTOM = BOX_Y + BOX_H + 2;

function cubicPath(a: Pt, b: Pt) {
  const mid = (a.y + b.y) / 2;
  return `M ${a.x},${a.y} C ${a.x},${mid} ${b.x},${mid} ${b.x},${b.y}`;
}

export function MiniSynapticWidget() {
  const [activeFormula, setActiveFormula] = useState<number | null>(null);

  useEffect(() => {
    const id = setInterval(() => {
      setActiveFormula(Math.floor(Math.random() * 4));
      setTimeout(() => setActiveFormula(null), 1400);
    }, 3200);
    return () => clearInterval(id);
  }, []);

  return (
    <div style={{ width: "100%", height: "100%", overflow: "hidden", pointerEvents: "none" }}>
      <style dangerouslySetInnerHTML={{ __html: `
        @keyframes mini-pulse-travel {
          0%   { stroke-dashoffset: 800; opacity: 0; }
          5%   { opacity: 0.9; }
          90%  { opacity: 0.9; }
          100% { stroke-dashoffset: 0; opacity: 0; }
        }
        @keyframes mini-cable-pulse {
          0%   { stroke-dashoffset: 300; opacity: 0; }
          8%   { opacity: 0.9; }
          88%  { opacity: 0.9; }
          100% { stroke-dashoffset: 0; opacity: 0; }
        }
        @keyframes mini-glow-beat {
          0%, 100% { filter: drop-shadow(0 0 2px rgba(6,182,212,0.5)); opacity: 0.75; }
          50%       { filter: drop-shadow(0 0 6px rgba(6,182,212,1));   opacity: 1; }
        }
        @keyframes mini-glow-slow {
          0%, 100% { filter: drop-shadow(0 0 2px rgba(6,182,212,0.4)); opacity: 0.65; }
          50%       { filter: drop-shadow(0 0 8px rgba(34,211,238,0.9)); opacity: 1; }
        }
        @keyframes mini-formula-glow {
          0%, 100% { filter: drop-shadow(0 0 3px rgba(6,182,212,0.2)); }
          50%       { filter: drop-shadow(0 0 9px rgba(6,182,212,0.5)); }
        }
        @keyframes mini-formula-active {
          0%, 100% { filter: drop-shadow(0 0 10px rgba(34,211,238,0.7)); }
          50%       { filter: drop-shadow(0 0 20px rgba(34,211,238,1)); }
        }
        .mini-pulse       { stroke-dasharray: 8 600; animation: mini-pulse-travel linear infinite; }
        .mini-cable       { stroke-dasharray: 6 300; animation: mini-cable-pulse linear infinite; }
        .mini-node-beat   { animation: mini-glow-beat 3s ease-in-out infinite; }
        .mini-node-slow   { animation: mini-glow-slow 4.5s ease-in-out infinite; }
        .mini-box-idle    { animation: mini-formula-glow 3s ease-in-out infinite; }
        .mini-box-active  { animation: mini-formula-active 0.6s ease-in-out infinite; }
      `}} />

      {/*
        viewBox: x=0..800, y=20..660 → 800×640 content area
        At 216px wide: scale = 216/800 = 0.27
        Rendered size: 216px × (640×0.27)=172.8px
        Title fontSize=38 → ~10px rendered
        Box H=88 → ~24px rendered
      */}
      <svg
        viewBox="0 20 800 640"
        width="100%"
        height="100%"
        preserveAspectRatio="xMidYMin meet"
        style={{ display: "block" }}
      >
        {/* ── TITLE ── */}
        <text
          x="400" y="82"
          fill="#ffffff"
          fontSize="38"
          fontFamily="monospace"
          fontWeight="600"
          textAnchor="middle"
          letterSpacing="2"
        >
          Synaptic Math Audit Engine v4.1
        </text>

        {/* ── FORMULA BOXES ── */}
        {FORMULAS.map((f, i) => {
          const cx = INPUT_NODES[i].x;
          const bx = cx - BOX_W / 2;
          const isActive = activeFormula === i;
          return (
            <g key={f.label} className={isActive ? "mini-box-active" : "mini-box-idle"}>
              <rect
                x={bx} y={BOX_Y}
                width={BOX_W} height={BOX_H}
                rx="6" ry="6"
                fill="rgba(0,0,0,0.6)"
                stroke={isActive ? "rgba(34,211,238,0.85)" : "rgba(6,182,212,0.22)"}
                strokeWidth="1.5"
              />
              <text x={cx} y={BOX_Y + 22} fill={isActive ? "#67e8f9" : "#0891b2"}
                fontSize="16" fontFamily="monospace" fontWeight="700"
                textAnchor="middle" letterSpacing="1.5">
                {f.label.toUpperCase()}
              </text>
              <text x={cx} y={BOX_Y + 52} fill={isActive ? "#ffffff" : "#e2e8f0"}
                fontSize="20" fontFamily="monospace" fontWeight="600" textAnchor="middle">
                {f.equation}
              </text>
              <text x={cx} y={BOX_Y + 78} fill={isActive ? "#22d3ee" : "#0891b2"}
                fontSize="20" fontFamily="monospace" fontWeight="700" textAnchor="middle">
                {f.result}
              </text>
            </g>
          );
        })}

        {/* ── CABLES: formula boxes → input nodes ── */}
        {INPUT_NODES.map((n, i) => (
          <path key={`mc-s-${i}`}
            d={`M ${n.x},${TILE_BOTTOM} C ${n.x},${TILE_BOTTOM + 30} ${n.x},${n.y - 30} ${n.x},${n.y}`}
            stroke="#0891b2" strokeWidth="1.5" fill="none" opacity="0.3" />
        ))}
        {INPUT_NODES.map((n, i) => (
          <path key={`mc-p-${i}`}
            d={`M ${n.x},${TILE_BOTTOM} C ${n.x},${TILE_BOTTOM + 30} ${n.x},${n.y - 30} ${n.x},${n.y}`}
            stroke={activeFormula === i ? "#67e8f9" : "#22d3ee"}
            strokeWidth="3" fill="none" strokeLinecap="round"
            className="mini-cable"
            style={{ animationDuration: `${2 + i * 0.4}s`, animationDelay: `${-i * 0.6}s` }} />
        ))}

        {/* ── STATIC CONNECTIONS ── */}
        <g stroke="#0891b2" strokeWidth="1" fill="none" opacity="0.22">
          {CONN_PAIRS.map(([a, b], i) => (
            <path key={`ms-${i}`} d={cubicPath(a, b)} />
          ))}
        </g>

        {/* ── ANIMATED PULSES ── */}
        {CONN_PAIRS.map(([a, b], i) => (
          <path key={`mp-${i}`}
            d={cubicPath(a, b)}
            stroke="#22d3ee" strokeWidth="2.5" strokeLinecap="round" fill="none"
            className="mini-pulse"
            style={{ animationDuration: `${PULSE_DUR[i % PULSE_DUR.length]}s`, animationDelay: `${-i * 0.38}s` }} />
        ))}

        {/* ── INPUT NODES ── */}
        {INPUT_NODES.map((n, i) => (
          <circle key={`mi-${i}`} cx={n.x} cy={n.y} r="10"
            fill={activeFormula === i ? "#67e8f9" : "#06b6d4"}
            className={activeFormula === i ? "mini-node-beat" : "mini-node-slow"} />
        ))}

        {/* ── HIDDEN LAYER 1 ── */}
        {HIDDEN1.map((n, i) => (
          <circle key={`mh1-${i}`} cx={n.x} cy={n.y} r="8"
            fill="#06b6d4" className="mini-node-beat" />
        ))}

        {/* ── HIDDEN LAYER 2 ── */}
        {HIDDEN2.map((n, i) => (
          <circle key={`mh2-${i}`} cx={n.x} cy={n.y} r="11"
            fill="#06b6d4" className="mini-node-slow" />
        ))}

        {/* ── PERIPHERAL NODES ── */}
        {PERIPHERAL.map((n, i) => (
          <circle key={`mper-${i}`} cx={n.x} cy={n.y} r="6"
            fill="#06b6d4" opacity="0.55" className="mini-node-slow" />
        ))}

        {/* ── OUTPUT NODE ── */}
        <circle cx={OUTPUT.x} cy={OUTPUT.y} r="18" fill="#06b6d4" className="mini-node-beat" />
        <circle cx={OUTPUT.x} cy={OUTPUT.y} r="27" fill="none" stroke="#22d3ee40" strokeWidth="1.4" />
        <circle cx={OUTPUT.x} cy={OUTPUT.y} r="38" fill="none" stroke="#22d3ee20" strokeWidth="1" />
        <text x={OUTPUT.x} y={OUTPUT.y + 5} fill="#020617" fontSize="14" fontFamily="monospace"
          textAnchor="middle" fontWeight="bold" opacity="0.9">
          100%
        </text>

        {/* ── LAYER LABELS ── */}
        <text x="6"  y="276" fill="#0891b2" fontSize="13" fontFamily="monospace" opacity="0.5" letterSpacing="0.5">IN</text>
        <text x="6"  y="396" fill="#0891b2" fontSize="13" fontFamily="monospace" opacity="0.5" letterSpacing="0.5">H1</text>
        <text x="6"  y="496" fill="#0891b2" fontSize="13" fontFamily="monospace" opacity="0.5" letterSpacing="0.5">H2</text>
        <text x="6"  y="581" fill="#0891b2" fontSize="13" fontFamily="monospace" opacity="0.5" letterSpacing="0.5">OUT</text>
      </svg>
    </div>
  );
}
