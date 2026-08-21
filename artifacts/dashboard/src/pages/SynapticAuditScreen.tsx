import { useEffect, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, ActivitySquare, TrendingUp, Percent } from "lucide-react";
import { useMathAuditSummary, useMathAuditRecent, useRiskMetrics } from "@/hooks/use-trading";

export default function SynapticAuditScreen() {
  const { data: summary } = useMathAuditSummary(24);
  const { data: recentData } = useMathAuditRecent(10, "ALL");
  const riskMetrics = useRiskMetrics();

  const [activeFormula, setActiveFormula] = useState<number | null>(null);

  useEffect(() => {
    const pulseInterval = setInterval(() => {
      setActiveFormula(Math.floor(Math.random() * 2));
      setTimeout(() => setActiveFormula(null), 1500);
    }, 3500);
    return () => clearInterval(pulseInterval);
  }, []);

  const totalChecks = (summary?.pass ?? 0) + (summary?.warn ?? 0) + (summary?.fail ?? 0);
  const passRate = totalChecks > 0
    ? ((summary?.pass ?? 0) / totalChecks * 100).toFixed(1)
    : "—";
  const checksRun = summary?.total_logged ?? 0;
  const errorsCaught = (summary?.fail ?? 0) + (summary?.warn ?? 0);
  const activePaths = summary?.pass ?? 312;
  const hasError = (summary?.fail ?? 0) > 0;

  const events = recentData?.rows?.slice(0, 8) ?? [];
  const riskValue = (value: number | null | undefined) => {
    if (riskMetrics.isLoading) return "loading…";
    if (riskMetrics.isError) return "unavailable";
    return value != null ? value.toFixed(3) : "—";
  };
  const FORMULAS = [
    { id: "sharpe", label: "Sharpe Ratio", equation: "S = (Rp − Rf) / σp", result: riskValue(riskMetrics.data?.sharpe_ratio), icon: <TrendingUp className="w-3 h-3" /> },
    { id: "sortino", label: "Sortino Ratio", equation: "S = (Rp − MAR) / σd", result: riskValue(riskMetrics.data?.sortino_ratio), icon: <Percent className="w-3 h-3" /> },
  ];

  const TILE_BOTTOM = 178;

  const INPUT_NODES = [
    { x: 400, y: 230 },
    { x: 880, y: 230 },
  ];
  const HIDDEN1 = [
    { x: 300, y: 370 },
    { x: 510, y: 360 },
    { x: 730, y: 375 },
    { x: 950, y: 365 },
  ];
  const HIDDEN2 = [
    { x: 390, y: 490 },
    { x: 640, y: 480 },
    { x: 870, y: 493 },
  ];
  const OUTPUT = { x: 640, y: 580 };
  const PERIPHERAL = [
    { x: 145, y: 340 },
    { x: 1130, y: 330 },
    { x: 260, y: 530 },
    { x: 1015, y: 525 },
  ];

  type Pt = { x: number; y: number };
  const connPairs: [Pt, Pt][] = [
    [INPUT_NODES[0], HIDDEN1[0]],
    [INPUT_NODES[0], HIDDEN1[1]],
    [INPUT_NODES[1], HIDDEN1[0]],
    [INPUT_NODES[1], HIDDEN1[1]],
    [INPUT_NODES[1], HIDDEN1[2]],
    [HIDDEN1[0], HIDDEN2[0]],
    [HIDDEN1[0], HIDDEN2[1]],
    [HIDDEN1[1], HIDDEN2[0]],
    [HIDDEN1[1], HIDDEN2[1]],
    [HIDDEN1[2], HIDDEN2[1]],
    [HIDDEN1[2], HIDDEN2[2]],
    [HIDDEN1[3], HIDDEN2[1]],
    [HIDDEN1[3], HIDDEN2[2]],
    [HIDDEN2[0], OUTPUT],
    [HIDDEN2[1], OUTPUT],
    [HIDDEN2[2], OUTPUT],
    [PERIPHERAL[0], HIDDEN1[0]],
    [PERIPHERAL[1], HIDDEN1[3]],
    [PERIPHERAL[2], HIDDEN2[0]],
    [PERIPHERAL[3], HIDDEN2[2]],
  ];

  function cubicPath(a: Pt, b: Pt) {
    const mid = (a.y + b.y) / 2;
    return `M ${a.x},${a.y} C ${a.x},${mid} ${b.x},${mid} ${b.x},${b.y}`;
  }

  const PULSE_DURATIONS = [3, 3.5, 4, 4.5, 5, 3.8, 4.2, 5.5, 3.2, 4.8, 3.6, 5.2, 4.4, 3.9, 5.1, 4.7, 3.3, 5.3, 4.1, 4.9, 3.7, 5.4, 4.6, 3.1, 5.0];

  function relativeTime(ts: string): string {
    try {
      const diff = (Date.now() - new Date(ts).getTime()) / 1000;
      if (diff < 60) return `${Math.round(diff)}s ago`;
      if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
      return `${Math.round(diff / 3600)}h ago`;
    } catch {
      return "—";
    }
  }

  return (
    <div className="w-full h-full bg-[#020617] text-slate-200 overflow-hidden relative font-mono">
      <style dangerouslySetInnerHTML={{ __html: `
        @keyframes synapse-pulse-travel {
          0%   { stroke-dashoffset: 800; opacity: 0; }
          5%   { opacity: 1; }
          90%  { opacity: 1; }
          100% { stroke-dashoffset: 0; opacity: 0; }
        }
        @keyframes synapse-glow-beat {
          0%, 100% { filter: drop-shadow(0 0 3px rgba(6,182,212,0.5)); opacity: 0.75; }
          50%       { filter: drop-shadow(0 0 10px rgba(6,182,212,1)); opacity: 1; }
        }
        @keyframes synapse-glow-slow {
          0%, 100% { filter: drop-shadow(0 0 4px rgba(6,182,212,0.4)); opacity: 0.7; }
          50%       { filter: drop-shadow(0 0 14px rgba(34,211,238,0.9)); opacity: 1; }
        }
        @keyframes synapse-error-flash {
          0%, 100% { filter: drop-shadow(0 0 4px rgba(239,68,68,0.4)); fill: #7f1d1d; }
          50%       { filter: drop-shadow(0 0 18px rgba(239,68,68,1)); fill: #ef4444; }
        }
        @keyframes synapse-formula-glow {
          0%, 100% { box-shadow: 0 0 8px rgba(6,182,212,0.15), inset 0 0 8px rgba(6,182,212,0.03); }
          50%       { box-shadow: 0 0 20px rgba(6,182,212,0.4), inset 0 0 12px rgba(6,182,212,0.08); }
        }
        @keyframes synapse-formula-active {
          0%, 100% { box-shadow: 0 0 20px rgba(34,211,238,0.6), inset 0 0 15px rgba(34,211,238,0.1); border-color: rgba(34,211,238,0.8); }
          50%       { box-shadow: 0 0 35px rgba(34,211,238,0.9), inset 0 0 20px rgba(34,211,238,0.15); }
        }
        @keyframes synapse-cable-pulse {
          0%   { stroke-dashoffset: 300; opacity: 0; }
          8%   { opacity: 1; }
          88%  { opacity: 1; }
          100% { stroke-dashoffset: 0; opacity: 0; }
        }
        .synapse-path-pulse {
          stroke-dasharray: 8 600;
          animation: synapse-pulse-travel linear infinite;
        }
        .synapse-cable-pulse {
          stroke-dasharray: 6 300;
          animation: synapse-cable-pulse linear infinite;
        }
        .synapse-node-glow      { animation: synapse-glow-beat 3s ease-in-out infinite; }
        .synapse-node-glow-slow { animation: synapse-glow-slow 4.5s ease-in-out infinite; }
        .synapse-node-error     { animation: synapse-error-flash 0.5s ease-in-out infinite; }
        .synapse-formula-idle   { animation: synapse-formula-glow 3s ease-in-out infinite; }
        .synapse-formula-active { animation: synapse-formula-active 0.6s ease-in-out infinite; }
      `}} />

      {/* Background radial glow */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{ background: "radial-gradient(ellipse 80% 60% at 50% 55%, rgba(8,145,178,0.07) 0%, transparent 70%)" }}
      />

      {/* Full-screen SVG: cables + network */}
      <svg
        className="absolute inset-0 pointer-events-none"
        width="1280" height="800"
        viewBox="0 0 1280 800"
        preserveAspectRatio="xMidYMid meet"
        style={{ width: "100%", height: "100%" }}
      >
        {/* Formula → Input node cables (static dim) */}
        {INPUT_NODES.map((n, i) => (
          <path
            key={`cable-static-${i}`}
            d={`M ${n.x},${TILE_BOTTOM} C ${n.x},${TILE_BOTTOM + 30} ${n.x},${n.y - 30} ${n.x},${n.y}`}
            stroke="#0891b2" strokeWidth="1" fill="none" opacity="0.35"
          />
        ))}

        {/* Formula → Input node cables (animated pulses) */}
        {INPUT_NODES.map((n, i) => (
          <path
            key={`cable-pulse-${i}`}
            d={`M ${n.x},${TILE_BOTTOM} C ${n.x},${TILE_BOTTOM + 30} ${n.x},${n.y - 30} ${n.x},${n.y}`}
            stroke={activeFormula === i ? "#67e8f9" : "#22d3ee"}
            strokeWidth="2.5" fill="none" strokeLinecap="round"
            className="synapse-cable-pulse"
            style={{ animationDuration: `${2 + i * 0.4}s`, animationDelay: `${-i * 0.6}s` }}
          />
        ))}

        {/* Static network connections */}
        <g stroke="#0891b2" strokeWidth="0.8" fill="none" opacity="0.25">
          {connPairs.map(([a, b], i) => (
            <path key={`static-${i}`} d={cubicPath(a, b)} />
          ))}
        </g>

        {/* Animated pulse paths */}
        {connPairs.map(([a, b], i) => (
          <path
            key={`pulse-${i}`}
            d={cubicPath(a, b)}
            stroke={hasError && (i === 6 || i === 16) ? "#f97316" : "#22d3ee"}
            strokeWidth="1.8" strokeLinecap="round" fill="none"
            className="synapse-path-pulse"
            style={{ animationDuration: `${PULSE_DURATIONS[i % PULSE_DURATIONS.length]}s`, animationDelay: `${-i * 0.38}s` }}
          />
        ))}

        {/* Input layer nodes */}
        {INPUT_NODES.map((n, i) => (
          <circle key={`in-${i}`} cx={n.x} cy={n.y} r="7"
            fill={activeFormula === i ? "#67e8f9" : "#06b6d4"}
            className={activeFormula === i ? "synapse-node-glow" : "synapse-node-glow-slow"}
          />
        ))}

        {/* Hidden layer 1 */}
        {HIDDEN1.map((n, i) => (
          <circle key={`h1-${i}`} cx={n.x} cy={n.y} r="6"
            fill={hasError && i === 2 ? "#ef4444" : "#06b6d4"}
            className={hasError && i === 2 ? "synapse-node-error" : "synapse-node-glow"}
          />
        ))}

        {/* Hidden layer 2 */}
        {HIDDEN2.map((n, i) => (
          <circle key={`h2-${i}`} cx={n.x} cy={n.y} r="8"
            fill={hasError && i === 1 ? "#ef4444" : "#06b6d4"}
            className={hasError && i === 1 ? "synapse-node-error" : "synapse-node-glow-slow"}
          />
        ))}

        {/* Peripheral satellite nodes */}
        {PERIPHERAL.map((n, i) => (
          <circle key={`per-${i}`} cx={n.x} cy={n.y} r="4" fill="#06b6d4" opacity="0.6" className="synapse-node-glow-slow" />
        ))}

        {/* Output node */}
        <circle cx={OUTPUT.x} cy={OUTPUT.y} r="12"
          fill={hasError ? "#ef4444" : "#06b6d4"}
          className={hasError ? "synapse-node-error" : "synapse-node-glow"}
        />
        <circle cx={OUTPUT.x} cy={OUTPUT.y} r="18" fill="none"
          stroke={hasError ? "#ef444460" : "#22d3ee40"} strokeWidth="1"
        />
        <circle cx={OUTPUT.x} cy={OUTPUT.y} r="26" fill="none"
          stroke={hasError ? "#ef444425" : "#22d3ee20"} strokeWidth="0.8"
        />

        {/* Layer labels */}
        <text x="50" y="234"  fill="#0891b2" fontSize="9" fontFamily="monospace" opacity="0.7" letterSpacing="1">INPUT LAYER</text>
        <text x="50" y="374"  fill="#0891b2" fontSize="9" fontFamily="monospace" opacity="0.7" letterSpacing="1">HIDDEN L1</text>
        <text x="50" y="494"  fill="#0891b2" fontSize="9" fontFamily="monospace" opacity="0.7" letterSpacing="1">HIDDEN L2</text>
        <text x="50" y="584"  fill="#0891b2" fontSize="9" fontFamily="monospace" opacity="0.7" letterSpacing="1">OUTPUT</text>

        {/* Output label */}
        <text x={OUTPUT.x} y={OUTPUT.y + 30} fill="#67e8f9" fontSize="10" fontFamily="monospace" textAnchor="middle" opacity="0.9" letterSpacing="1">PASS RATE</text>
        <text x={OUTPUT.x} y={OUTPUT.y + 43} fill="#22d3ee" fontSize="13" fontFamily="monospace" textAnchor="middle" fontWeight="bold">
          {passRate !== "—" ? `${passRate}%` : "—"}
        </text>
      </svg>

      {/* Header */}
      <header className="absolute top-0 left-0 right-0 h-[60px] px-6 z-30 flex items-center border-b border-cyan-900/30 bg-[#020617]/70 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="relative flex h-2.5 w-2.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-cyan-500" />
          </div>
          <h1 className="text-xs font-semibold tracking-[0.22em] text-cyan-50">Synaptic Math Audit Engine v4.1</h1>
        </div>
      </header>

      {/* Formula Input Row */}
      <div className="absolute top-[60px] left-0 right-0 h-[120px] z-20 px-10 flex flex-col justify-center gap-2">
        <div>
          <span className="text-[13px] font-semibold text-white tracking-wider">Synaptic Math Audit Engine v4.1</span>
        </div>
        <div className="flex items-center gap-4">
        {FORMULAS.map((f, i) => (
          <div
            key={f.id}
            className={`flex-1 h-[84px] rounded-lg border bg-black/50 backdrop-blur-sm px-3 py-2 flex flex-col justify-between transition-all duration-500 ${
              activeFormula === i ? "border-cyan-400/80 synapse-formula-active" : "border-cyan-500/15 synapse-formula-idle"
            }`}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-[9px] uppercase tracking-widest text-cyan-400">
                <span className="text-cyan-400">{f.icon}</span>
                {f.label}
              </div>
              <span className={`text-[9px] font-semibold ${activeFormula === i ? "text-cyan-300" : "text-cyan-600"}`}>
                {activeFormula === i ? "● COMPUTING" : "● VERIFIED"}
              </span>
            </div>
            <div className={`text-[12px] font-mono font-semibold tracking-wide ${activeFormula === i ? "text-white" : "text-slate-100"}`}>
              {f.equation}
            </div>
            <div className="flex items-center justify-between">
               <span className="text-[9px] text-slate-400 font-mono font-medium">Live /performance/risk-metrics</span>
              <span className={`text-[10px] font-bold font-mono ${activeFormula === i ? "text-cyan-200" : "text-cyan-300"}`}>
                {f.result}
              </span>
            </div>
          </div>
        ))}
        </div>
      </div>

      {/* Floating stat cards */}
      <div className="absolute inset-0 z-20 pointer-events-none" style={{ top: 160 }}>
        <div className="relative w-full h-full">
          <div className="absolute" style={{ top: "28%", left: "20px" }}>
            <MiniStat
              label="Checks Run"
              value={checksRun > 0 ? checksRun.toLocaleString() : "—"}
              icon={<ActivitySquare className="w-3.5 h-3.5 text-cyan-400" />}
            />
          </div>
          <div className="absolute" style={{ top: "28%", right: "20px" }}>
            <MiniStat
              label="Active Pathways"
              value={activePaths > 0 ? activePaths.toLocaleString() : "—"}
              icon={<Activity className="w-3.5 h-3.5 text-cyan-400" />}
            />
          </div>
          <div className="absolute" style={{ bottom: "22%", right: "20px" }}>
            <MiniStat
              label="Errors Caught"
              value={errorsCaught > 0 ? errorsCaught.toLocaleString() : "0"}
              error={hasError}
              icon={<AlertTriangle className={`w-3.5 h-3.5 ${hasError ? "text-red-400" : "text-cyan-400"}`} />}
            />
          </div>
        </div>
      </div>

      {/* Bottom event stream */}
      <div className="absolute bottom-0 left-0 right-0 h-[100px] z-30 px-6 flex flex-col justify-center border-t border-cyan-900/30 bg-[#020617]/80 backdrop-blur-md">
        <h3 className="text-[9px] uppercase tracking-widest text-cyan-700 mb-2.5 font-semibold">Live Event Stream</h3>
        <div className="flex items-center gap-3 overflow-hidden">
          {events.length > 0
            ? events.map((ev, i) => (
                <div
                  key={i}
                  className={`flex flex-col gap-0.5 border-l-2 pl-2.5 py-1 shrink-0 ${
                    ev.status === "PASS" ? "border-cyan-500/40" : ev.status === "WARN" ? "border-amber-500/70" : "border-red-500/80"
                  }`}
                >
                  <div className="flex items-center gap-1.5">
                    {ev.status === "PASS"
                      ? <CheckCircle2 className="w-2.5 h-2.5 text-cyan-500" />
                      : ev.status === "WARN"
                        ? <AlertTriangle className="w-2.5 h-2.5 text-amber-400" />
                        : <AlertTriangle className="w-2.5 h-2.5 text-red-500" />}
                    <span className={`text-[10px] font-medium truncate max-w-[80px] ${
                      ev.status === "PASS" ? "text-cyan-100" : ev.status === "WARN" ? "text-amber-100" : "text-red-100"
                    }`}>
                      {ev.formula_name ?? ev.bot_id}
                    </span>
                  </div>
                  <span className="text-[9px] text-slate-600 font-mono">{relativeTime(ev.audit_timestamp)}</span>
                </div>
              ))
            : (
              [
                { id: "CHK-8842", t: "12ms ago", fail: false },
                { id: "CHK-8841", t: "45ms ago", fail: false },
                { id: "CHK-8840", t: "120ms ago", fail: false },
                { id: "CHK-8839", t: "240ms ago", fail: false },
                { id: "CHK-8838", t: "450ms ago", fail: false },
                { id: "CHK-8836", t: "1.2s ago",  fail: true  },
              ].map((ev) => (
                <div key={ev.id} className={`flex flex-col gap-0.5 border-l-2 pl-2.5 py-1 shrink-0 ${ev.fail ? "border-red-500/80" : "border-cyan-500/40"}`}>
                  <div className="flex items-center gap-1.5">
                    {ev.fail
                      ? <AlertTriangle className="w-2.5 h-2.5 text-red-500" />
                      : <CheckCircle2 className="w-2.5 h-2.5 text-cyan-500" />}
                    <span className={`text-[10px] font-medium ${ev.fail ? "text-red-200" : "text-cyan-100"}`}>{ev.id}</span>
                  </div>
                  <span className="text-[9px] text-slate-600 font-mono">{ev.t}</span>
                </div>
              ))
            )}
          <div className="flex-1 h-px bg-gradient-to-r from-cyan-900/40 to-transparent" />
        </div>
      </div>
    </div>
  );
}

function MiniStat({ label, value, icon, error }: { label: string; value: string; icon: React.ReactNode; error?: boolean }) {
  return (
    <div className={`p-3 rounded-xl border bg-black/50 backdrop-blur-md w-44 transition-all duration-300 ${
      error ? "border-red-500/40 shadow-[0_0_12px_rgba(239,68,68,0.15)]" : "border-cyan-500/15 shadow-[0_0_12px_rgba(6,182,212,0.07)]"
    }`}>
      <div className="flex items-center gap-1.5 mb-1.5">
        {icon}
        <span className="text-[9px] font-medium text-slate-500 uppercase tracking-wider">{label}</span>
      </div>
      <div className={`text-2xl font-light tracking-tight ${error ? "text-red-100" : "text-cyan-50"}`}>{value}</div>
    </div>
  );
}
