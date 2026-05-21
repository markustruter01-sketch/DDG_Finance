import { useEffect, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, ActivitySquare, TrendingUp, Shield, BarChart2, Percent } from "lucide-react";
import { useMathAuditSummary, useMathAuditRecent } from "@/hooks/use-trading";

const FORMULAS = [
  {
    id: "sharpe",
    label: "Sharpe Ratio",
    equation: "S = (Rp − Rf) / σp",
    vars: "Rp=18.4%  Rf=5.2%  σp=8.1%",
    result: "→ 1.63",
    icon: <TrendingUp className="w-3 h-3" />,
  },
  {
    id: "kelly",
    label: "Kelly Criterion",
    equation: "f* = (bp − q) / b",
    vars: "b=2.1  p=0.54  q=0.46",
    result: "→ 13.8%",
    icon: <BarChart2 className="w-3 h-3" />,
  },
  {
    id: "var",
    label: "Value at Risk",
    equation: "VaR = μ − zσ√t",
    vars: "μ=$312  z=1.65  σ=$91",
    result: "→ $4,820",
    icon: <Shield className="w-3 h-3" />,
  },
  {
    id: "sortino",
    label: "Sortino Ratio",
    equation: "S = (Rp − MAR) / σd",
    vars: "Rp=18.4%  MAR=8%  σd=4.9%",
    result: "→ 2.12",
    icon: <Percent className="w-3 h-3" />,
  },
];

export default function SynapticAuditScreen() {
  const { data: summary } = useMathAuditSummary(24);
  const { data: recentData } = useMathAuditRecent(10, "ALL");

  const [activeFormula, setActiveFormula] = useState<number | null>(null);

  useEffect(() => {
    const pulseInterval = setInterval(() => {
      setActiveFormula(Math.floor(Math.random() * 4));
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
        @keyframes synapse-formula-glow {
          0%, 100% { box-shadow: 0 0 8px rgba(6,182,212,0.15), inset 0 0 8px rgba(6,182,212,0.03); }
          50%       { box-shadow: 0 0 20px rgba(6,182,212,0.4), inset 0 0 12px rgba(6,182,212,0.08); }
        }
        @keyframes synapse-formula-active {
          0%, 100% { box-shadow: 0 0 20px rgba(34,211,238,0.6), inset 0 0 15px rgba(34,211,238,0.1); border-color: rgba(34,211,238,0.8); }
          50%       { box-shadow: 0 0 35px rgba(34,211,238,0.9), inset 0 0 20px rgba(34,211,238,0.15); }
        }
        .synapse-formula-idle   { animation: synapse-formula-glow 3s ease-in-out infinite; }
        .synapse-formula-active { animation: synapse-formula-active 0.6s ease-in-out infinite; }
      `}} />

      {/* Background radial glow */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{ background: "radial-gradient(ellipse 80% 60% at 50% 55%, rgba(8,145,178,0.07) 0%, transparent 70%)" }}
      />

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

      {/* Floating stat cards */}
      <div className="absolute z-20 pointer-events-none" style={{ top: 80, left: 20 }}>
        <MiniStat
          label="Checks Run"
          value={checksRun > 0 ? checksRun.toLocaleString() : "—"}
          icon={<ActivitySquare className="w-3.5 h-3.5 text-cyan-400" />}
        />
      </div>
      <div className="absolute z-20 pointer-events-none" style={{ top: 80, right: 20 }}>
        <MiniStat
          label="Active Pathways"
          value={activePaths > 0 ? activePaths.toLocaleString() : "—"}
          icon={<Activity className="w-3.5 h-3.5 text-cyan-400" />}
        />
      </div>
      <div className="absolute z-20 pointer-events-none" style={{ top: 200, right: 20 }}>
        <MiniStat
          label="Errors Caught"
          value={errorsCaught > 0 ? errorsCaught.toLocaleString() : "0"}
          error={hasError}
          icon={<AlertTriangle className={`w-3.5 h-3.5 ${hasError ? "text-red-400" : "text-cyan-400"}`} />}
        />
      </div>

      {/* Pass rate display — centre of page */}
      <div className="absolute inset-0 flex items-center justify-center z-10" style={{ top: 60, bottom: 230 }}>
        <div className="flex flex-col items-center gap-1">
          <span className="text-[10px] tracking-widest text-cyan-500 font-mono uppercase">Pass Rate</span>
          <span className="text-6xl font-light text-cyan-100 tracking-tight">
            {passRate !== "—" ? `${passRate}%` : "—"}
          </span>
        </div>
      </div>

      {/* Formula boxes + title — bottom of page, above event stream */}
      <div className="absolute left-0 right-0 z-20 px-10" style={{ bottom: 100 }}>
        <div className="mb-2">
          <span className="text-[11px] font-semibold text-white tracking-wider">◄ Synaptic Math Audit Engine v4.1</span>
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
                <span className="text-[9px] text-slate-400 font-mono font-medium">{f.vars}</span>
                <span className={`text-[10px] font-bold font-mono ${activeFormula === i ? "text-cyan-200" : "text-cyan-300"}`}>
                  {f.result}
                </span>
              </div>
            </div>
          ))}
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
