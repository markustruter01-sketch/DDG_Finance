import { useEffect, useState } from "react";

const FORMULAS = [
  { label: "Sharpe",  equation: "S=(Rp−Rf)/σp",  result: "1.63"   },
  { label: "Kelly",   equation: "f*=(bp−q)/b",    result: "13.8%"  },
  { label: "VaR",     equation: "VaR=μ−zσ√t",    result: "$4,820" },
  { label: "Sortino", equation: "S=(Rp−MAR)/σd",  result: "2.12"   },
];

type Pt = { x: number; y: number };

const INPUT_NODES: Pt[]  = [
  { x: 188, y: 230 }, { x: 484, y: 230 }, { x: 780, y: 230 }, { x: 1076, y: 230 },
];
const HIDDEN1: Pt[] = [
  { x: 300, y: 370 }, { x: 510, y: 360 }, { x: 730, y: 375 }, { x: 950, y: 365 },
];
const HIDDEN2: Pt[] = [
  { x: 390, y: 490 }, { x: 640, y: 480 }, { x: 870, y: 493 },
];
const OUTPUT: Pt = { x: 640, y: 580 };
const PERIPHERAL: Pt[] = [
  { x: 145, y: 340 }, { x: 1130, y: 330 }, { x: 260, y: 530 }, { x: 1015, y: 525 },
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

const TILE_BOTTOM = 158;

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
    <div
      style={{
        position: "relative",
        width: 216,
        pointerEvents: "none",
      }}
    >
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
          50%       { filter: drop-shadow(0 0 7px rgba(6,182,212,1));   opacity: 1; }
        }
        @keyframes mini-glow-slow {
          0%, 100% { filter: drop-shadow(0 0 3px rgba(6,182,212,0.4)); opacity: 0.65; }
          50%       { filter: drop-shadow(0 0 9px rgba(34,211,238,0.9)); opacity: 1; }
        }
        @keyframes mini-formula-glow {
          0%, 100% { box-shadow: 0 0 6px rgba(6,182,212,0.12), inset 0 0 6px rgba(6,182,212,0.02); }
          50%       { box-shadow: 0 0 14px rgba(6,182,212,0.35), inset 0 0 8px rgba(6,182,212,0.06); }
        }
        @keyframes mini-formula-active {
          0%, 100% { box-shadow: 0 0 14px rgba(34,211,238,0.6), inset 0 0 10px rgba(34,211,238,0.1); border-color: rgba(34,211,238,0.8); }
          50%       { box-shadow: 0 0 24px rgba(34,211,238,0.9), inset 0 0 14px rgba(34,211,238,0.15); }
        }
        .mini-pulse       { stroke-dasharray: 8 600; animation: mini-pulse-travel linear infinite; }
        .mini-cable       { stroke-dasharray: 6 300; animation: mini-cable-pulse linear infinite; }
        .mini-node-beat   { animation: mini-glow-beat 3s ease-in-out infinite; }
        .mini-node-slow   { animation: mini-glow-slow 4.5s ease-in-out infinite; }
        .mini-formula-idle   { animation: mini-formula-glow 3s ease-in-out infinite; }
        .mini-formula-active { animation: mini-formula-active 0.6s ease-in-out infinite; }
      `}} />

      {/* Algorithm Checks title */}
      <div style={{ fontSize: 17, color: "#ffffff", fontFamily: "monospace", fontWeight: 600, letterSpacing: "0.08em", padding: "0 4px 6px 4px", whiteSpace: "nowrap" }}>
        Synaptic Math Audit Engine v4.1
      </div>

      {/* Formula boxes row */}
      <div style={{ display: "flex", gap: 4, padding: "0 4px 4px 4px" }}>
        {FORMULAS.map((f, i) => (
          <div
            key={f.label}
            className={activeFormula === i ? "mini-formula-active" : "mini-formula-idle"}
            style={{
              flex: 1,
              border: `1px solid ${activeFormula === i ? "rgba(34,211,238,0.8)" : "rgba(6,182,212,0.18)"}`,
              borderRadius: 5,
              background: "rgba(0,0,0,0.55)",
              backdropFilter: "blur(4px)",
              padding: "4px 5px",
              display: "flex",
              flexDirection: "column",
              gap: 2,
            }}
          >
            <div style={{
              fontSize: 7,
              color: activeFormula === i ? "#67e8f9" : "#0891b2",
              fontFamily: "monospace",
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}>
              {f.label}
            </div>
            <div style={{
              fontSize: 8,
              color: activeFormula === i ? "#ffffff" : "#e2e8f0",
              fontFamily: "monospace",
              fontWeight: 600,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}>
              {f.equation}
            </div>
            <div style={{
              fontSize: 8,
              color: activeFormula === i ? "#22d3ee" : "#0891b2",
              fontFamily: "monospace",
              fontWeight: 700,
              textAlign: "right",
            }}>
              {f.result}
            </div>
          </div>
        ))}
      </div>

      {/* Neural network SVG — viewBox crops to the network region */}
      <svg
        viewBox="90 140 1100 490"
        width="341"
        height="152"
        style={{ display: "block" }}
        preserveAspectRatio="xMidYMid meet"
      >
        {/* Formula → Input cables static */}
        {INPUT_NODES.map((n, i) => (
          <path
            key={`mc-s-${i}`}
            d={`M ${n.x},${TILE_BOTTOM} C ${n.x},${TILE_BOTTOM + 30} ${n.x},${n.y - 30} ${n.x},${n.y}`}
            stroke="#0891b2" strokeWidth="1.2" fill="none" opacity="0.3"
          />
        ))}

        {/* Formula → Input cables animated */}
        {INPUT_NODES.map((n, i) => (
          <path
            key={`mc-p-${i}`}
            d={`M ${n.x},${TILE_BOTTOM} C ${n.x},${TILE_BOTTOM + 30} ${n.x},${n.y - 30} ${n.x},${n.y}`}
            stroke={activeFormula === i ? "#67e8f9" : "#22d3ee"}
            strokeWidth="3" fill="none" strokeLinecap="round"
            className="mini-cable"
            style={{ animationDuration: `${2 + i * 0.4}s`, animationDelay: `${-i * 0.6}s` }}
          />
        ))}

        {/* Static connections */}
        <g stroke="#0891b2" strokeWidth="0.9" fill="none" opacity="0.22">
          {CONN_PAIRS.map(([a, b], i) => (
            <path key={`ms-${i}`} d={cubicPath(a, b)} />
          ))}
        </g>

        {/* Animated pulse paths */}
        {CONN_PAIRS.map(([a, b], i) => (
          <path
            key={`mp-${i}`}
            d={cubicPath(a, b)}
            stroke="#22d3ee"
            strokeWidth="2" strokeLinecap="round" fill="none"
            className="mini-pulse"
            style={{ animationDuration: `${PULSE_DUR[i % PULSE_DUR.length]}s`, animationDelay: `${-i * 0.38}s` }}
          />
        ))}

        {/* Input layer nodes */}
        {INPUT_NODES.map((n, i) => (
          <circle key={`mi-${i}`} cx={n.x} cy={n.y} r="9"
            fill={activeFormula === i ? "#67e8f9" : "#06b6d4"}
            className={activeFormula === i ? "mini-node-beat" : "mini-node-slow"}
          />
        ))}

        {/* Hidden layer 1 */}
        {HIDDEN1.map((n, i) => (
          <circle key={`mh1-${i}`} cx={n.x} cy={n.y} r="7.5"
            fill="#06b6d4" className="mini-node-beat"
          />
        ))}

        {/* Hidden layer 2 */}
        {HIDDEN2.map((n, i) => (
          <circle key={`mh2-${i}`} cx={n.x} cy={n.y} r="10"
            fill="#06b6d4" className="mini-node-slow"
          />
        ))}

        {/* Peripheral nodes */}
        {PERIPHERAL.map((n, i) => (
          <circle key={`mper-${i}`} cx={n.x} cy={n.y} r="5.5"
            fill="#06b6d4" opacity="0.55" className="mini-node-slow"
          />
        ))}

        {/* Output node */}
        <circle cx={OUTPUT.x} cy={OUTPUT.y} r="16" fill="#06b6d4" className="mini-node-beat" />
        <circle cx={OUTPUT.x} cy={OUTPUT.y} r="24" fill="none" stroke="#22d3ee40" strokeWidth="1.2" />
        <circle cx={OUTPUT.x} cy={OUTPUT.y} r="34" fill="none" stroke="#22d3ee20" strokeWidth="0.9" />

        {/* Output label */}
        <text x={OUTPUT.x} y={OUTPUT.y + 2} fill="#020617" fontSize="13" fontFamily="monospace"
          textAnchor="middle" fontWeight="bold" opacity="0.9">
          100%
        </text>

        {/* Layer labels */}
        <text x="100" y="236" fill="#0891b2" fontSize="11" fontFamily="monospace" opacity="0.55" letterSpacing="1">IN</text>
        <text x="100" y="376" fill="#0891b2" fontSize="11" fontFamily="monospace" opacity="0.55" letterSpacing="1">H1</text>
        <text x="100" y="494" fill="#0891b2" fontSize="11" fontFamily="monospace" opacity="0.55" letterSpacing="1">H2</text>
        <text x="100" y="586" fill="#0891b2" fontSize="11" fontFamily="monospace" opacity="0.55" letterSpacing="1">OUT</text>
      </svg>
    </div>
  );
}
