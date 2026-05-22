import { useEffect, useState } from "react";

const FORMULAS = [
  { label: "Sharpe",  equation: "S=(Rp-Rf)/σp",  result: "1.63"   },
  { label: "Kelly",   equation: "f*=(bp-q)/b",    result: "13.8%"  },
  { label: "VaR",     equation: "VaR=μ-zσ√t",    result: "$4,820" },
  { label: "Sortino", equation: "S=(Rp-MAR)/σd",  result: "2.12"   },
];

const INPUT_NODES_X = [210, 646, 1082, 1518];

const BOX_W = 420;
const BOX_H = 180;
const BOX_Y = 100;
const TITLE_X = 864;

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
        @keyframes mini-formula-glow {
          0%, 100% { filter: drop-shadow(0 0 3px rgba(6,182,212,0.2)); }
          50%       { filter: drop-shadow(0 0 9px rgba(6,182,212,0.5)); }
        }
        @keyframes mini-formula-active {
          0%, 100% { filter: drop-shadow(0 0 10px rgba(34,211,238,0.7)); }
          50%       { filter: drop-shadow(0 0 20px rgba(34,211,238,1)); }
        }
        .mini-box-idle   { animation: mini-formula-glow 3s ease-in-out infinite; }
        .mini-box-active { animation: mini-formula-active 0.6s ease-in-out infinite; }
      `}} />

      <svg
        viewBox="-20 30 1768 280"
        style={{ display: "block", width: "100%", height: "100%" }}
        preserveAspectRatio="xMidYMax meet"
      >
        {/* ── TITLE ── */}
        <text x={TITLE_X} y="70"
          fill="rgba(255,255,255,0.9)" fontSize="44" fontFamily="monospace" fontWeight="600"
          textAnchor="middle" letterSpacing="1"
          style={{ textTransform: "uppercase" }}>
          ◂ Synaptic Math Audit Engine v4.1
        </text>

        {/* ── FORMULA BOXES ── */}
        {FORMULAS.map((f, i) => {
          const cx = INPUT_NODES_X[i];
          const bx = cx - BOX_W / 2;
          const isActive = activeFormula === i;
          return (
            <g key={f.label} className={isActive ? "mini-box-active" : "mini-box-idle"}>
              <rect x={bx} y={BOX_Y} width={BOX_W} height={BOX_H} rx="5" ry="5"
                fill="rgba(0,0,0,0.6)"
                stroke={isActive ? "rgba(34,211,238,0.85)" : "rgba(6,182,212,0.22)"}
                strokeWidth="1.5" />
              <text x={cx} y={BOX_Y + 40} fill={isActive ? "#67e8f9" : "#0891b2"}
                fontSize="28" fontFamily="monospace" fontWeight="700"
                textAnchor="middle" letterSpacing="1">
                {f.label.toUpperCase()}
              </text>
              <text x={cx} y={BOX_Y + 105} fill={isActive ? "#ffffff" : "#e2e8f0"}
                fontSize="38" fontFamily="monospace" fontWeight="600" textAnchor="middle">
                {f.equation}
              </text>
              <text x={cx} y={BOX_Y + 158} fill={isActive ? "#22d3ee" : "#0891b2"}
                fontSize="38" fontFamily="monospace" fontWeight="700" textAnchor="middle">
                {f.result}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
