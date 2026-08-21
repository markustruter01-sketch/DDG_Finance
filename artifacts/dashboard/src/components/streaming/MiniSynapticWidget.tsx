import { useEffect, useState } from "react";
import { useRiskMetrics } from "@/hooks/use-trading";

const BOX_W = 252;
const BOX_H = 108;
const BOX_Y = 100;

const INPUT_NODES_X = [270, 810];
const TITLE_X = 528;

export function MiniSynapticWidget() {
  const [activeFormula, setActiveFormula] = useState<number | null>(null);
  const riskMetrics = useRiskMetrics();
  const riskValue = (value: number | null | undefined) => {
    if (riskMetrics.isLoading) return "loading…";
    if (riskMetrics.isError) return "unavailable";
    return value != null ? value.toFixed(3) : "—";
  };
  const formulas = [
    { label: "Sharpe", equation: "S=(Rp-Rf)/σp", result: riskValue(riskMetrics.data?.sharpe_ratio) },
    { label: "Sortino", equation: "S=(Rp-MAR)/σd", result: riskValue(riskMetrics.data?.sortino_ratio) },
  ];

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
        viewBox="-12 25 1080 190"
        style={{ display: "block", width: "100%", height: "100%" }}
        preserveAspectRatio="xMidYMax meet"
      >
        {/* ── TITLE ── */}
        <text x={TITLE_X} y="70"
          fill="rgba(255,255,255,0.9)" fontSize="26" fontFamily="monospace" fontWeight="600"
          textAnchor="middle" letterSpacing="1"
          style={{ textTransform: "uppercase" }}>
          ◂ Synaptic Math Audit Engine v4.1
        </text>

        {/* ── FORMULA BOXES ── */}
       {formulas.map((f, i) => {
          const cx = INPUT_NODES_X[i];
          const bx = cx - BOX_W / 2;
          const isActive = activeFormula === i;
          return (
            <g key={f.label} className={isActive ? "mini-box-active" : "mini-box-idle"}>
              <rect x={bx} y={BOX_Y} width={BOX_W} height={BOX_H} rx="5" ry="5"
                fill="transparent"
                stroke={isActive ? "rgba(34,211,238,0.85)" : "rgba(6,182,212,0.22)"}
                strokeWidth="1.5" />
              <text x={cx} y={BOX_Y + 24} fill={isActive ? "#67e8f9" : "#0891b2"}
                fontSize="17" fontFamily="monospace" fontWeight="700"
                textAnchor="middle" letterSpacing="1">
                {f.label.toUpperCase()}
              </text>
              <text x={cx} y={BOX_Y + 63} fill={isActive ? "#ffffff" : "#e2e8f0"}
                fontSize="23" fontFamily="monospace" fontWeight="600" textAnchor="middle">
                {f.equation}
              </text>
              <text x={cx} y={BOX_Y + 95} fill={isActive ? "#22d3ee" : "#0891b2"}
                fontSize="23" fontFamily="monospace" fontWeight="700" textAnchor="middle">
                {f.result}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
