import React, { useEffect, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, Cpu, ActivitySquare } from "lucide-react";

export function Concept2NeuralSynaptic() {
  const [hasError, setHasError] = useState(false);

  useEffect(() => {
    // Randomly trigger error state for visual effect
    const interval = setInterval(() => {
      setHasError(true);
      setTimeout(() => setHasError(false), 2000);
    }, 8000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="min-h-screen bg-[#020617] text-slate-200 overflow-hidden relative font-mono selection:bg-cyan-900/50">
      <style dangerouslySetInnerHTML={{ __html: `
        @keyframes pulse-dot {
          0% { stroke-dashoffset: 1000; opacity: 0; }
          10% { opacity: 1; }
          90% { opacity: 1; }
          100% { stroke-dashoffset: 0; opacity: 0; }
        }
        @keyframes glow-pulse {
          0%, 100% { filter: drop-shadow(0 0 4px rgba(6, 182, 212, 0.5)); opacity: 0.8; }
          50% { filter: drop-shadow(0 0 12px rgba(6, 182, 212, 1)); opacity: 1; }
        }
        @keyframes error-flash {
          0%, 100% { filter: drop-shadow(0 0 4px rgba(239, 68, 68, 0.5)); fill: #7f1d1d; }
          50% { filter: drop-shadow(0 0 20px rgba(239, 68, 68, 1)); fill: #ef4444; }
        }
        .path-pulse {
          stroke-dasharray: 10 1000;
          animation: pulse-dot 4s linear infinite;
        }
        .path-pulse-delayed {
          stroke-dasharray: 10 1000;
          animation: pulse-dot 5s linear infinite;
          animation-delay: -2s;
        }
        .path-pulse-fast {
          stroke-dasharray: 15 1000;
          animation: pulse-dot 3s linear infinite;
          animation-delay: -1s;
        }
        .node-glow {
          animation: glow-pulse 3s ease-in-out infinite;
        }
        .node-glow-delayed {
          animation: glow-pulse 4s ease-in-out infinite;
          animation-delay: -1.5s;
        }
        .error-node {
          animation: error-flash 0.5s ease-in-out infinite;
        }
      `}} />

      {/* Background radial gradient */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-cyan-950/20 via-[#020617] to-[#020617] pointer-events-none" />

      {/* Header */}
      <header className="absolute top-0 left-0 right-0 p-6 z-10 flex items-center justify-between border-b border-cyan-900/30 bg-[#020617]/50 backdrop-blur-md">
        <div className="flex items-center gap-4">
          <div className="relative flex h-3 w-3">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-3 w-3 bg-cyan-500"></span>
          </div>
          <h1 className="text-sm font-semibold tracking-[0.2em] text-cyan-50">SYNAPTIC AUDIT ENGINE v4.1</h1>
        </div>
        <div className="flex items-center gap-6 text-xs text-cyan-600/70 uppercase tracking-widest">
          <span>Neural Net: Online</span>
          <span>Latency: 12ms</span>
        </div>
      </header>

      {/* Neural Web SVG Centrepiece */}
      <div className="absolute inset-0 flex items-center justify-center opacity-70 mt-16">
        <svg width="800" height="600" viewBox="0 0 800 600" className="max-w-full max-h-full overflow-visible">
          {/* Static connection lines */}
          <g stroke="#0891b2" strokeWidth="1" opacity="0.3" fill="none">
            <path d="M 100,300 C 200,300 250,150 400,200" />
            <path d="M 100,300 C 200,300 250,450 400,400" />
            <path d="M 400,200 C 500,250 600,150 700,300" />
            <path d="M 400,400 C 500,350 600,450 700,300" />
            <path d="M 400,200 C 450,300 350,350 400,400" />
            <path d="M 250,150 C 350,50 450,100 600,150" />
            <path d="M 250,450 C 350,550 450,500 600,450" />
            <path d="M 600,150 C 650,200 650,250 700,300" />
            <path d="M 600,450 C 650,400 650,350 700,300" />
          </g>

          {/* Animated pulse paths */}
          <g stroke={hasError ? "#f97316" : "#22d3ee"} strokeWidth="2" strokeLinecap="round" fill="none" className="transition-colors duration-300">
            <path d="M 100,300 C 200,300 250,150 400,200" className="path-pulse" />
            <path d="M 100,300 C 200,300 250,450 400,400" className="path-pulse-delayed" />
            <path d="M 400,200 C 500,250 600,150 700,300" className="path-pulse-fast" />
            <path d="M 400,400 C 500,350 600,450 700,300" className="path-pulse" />
            <path d="M 250,150 C 350,50 450,100 600,150" className="path-pulse-delayed" />
            <path d="M 250,450 C 350,550 450,500 600,450" className="path-pulse-fast" />
          </g>

          {/* Nodes */}
          <g>
            <circle cx="100" cy="300" r="4" fill="#06b6d4" className="node-glow" />
            <circle cx="250" cy="150" r="6" fill="#06b6d4" className="node-glow-delayed" />
            <circle cx="250" cy="450" r="5" fill="#06b6d4" className="node-glow" />
            <circle cx="400" cy="200" r="8" fill="#06b6d4" className="node-glow-delayed" />
            <circle cx="400" cy="400" r="7" fill={hasError ? "#ef4444" : "#06b6d4"} className={hasError ? "error-node" : "node-glow"} />
            <circle cx="600" cy="150" r="5" fill="#06b6d4" className="node-glow-delayed" />
            <circle cx="600" cy="450" r="6" fill={hasError ? "#ef4444" : "#06b6d4"} className={hasError ? "error-node" : "node-glow"} />
            <circle cx="700" cy="300" r="9" fill="#06b6d4" className="node-glow" />
            
            {/* Core processing nodes */}
            <circle cx="380" cy="220" r="3" fill="#67e8f9" className="node-glow" />
            <circle cx="420" cy="180" r="2" fill="#67e8f9" className="node-glow" />
            <circle cx="390" cy="420" r="3" fill={hasError ? "#fca5a5" : "#67e8f9"} className={hasError ? "error-node" : "node-glow"} />
          </g>
        </svg>
      </div>

      {/* Floating Stats */}
      <div className="absolute inset-0 z-20 pointer-events-none mt-16 p-8">
        <div className="grid grid-cols-2 gap-8 max-w-5xl mx-auto h-full relative">
          
          <div className="absolute top-1/4 left-0">
            <StatCard 
              label="Pass Rate" 
              value="99.2%" 
              trend="+0.1%"
              icon={<CheckCircle2 className="w-4 h-4 text-cyan-400" />}
            />
          </div>

          <div className="absolute bottom-1/3 left-10">
            <StatCard 
              label="Checks Run" 
              value="1,847" 
              icon={<ActivitySquare className="w-4 h-4 text-cyan-400" />}
            />
          </div>

          <div className="absolute top-1/3 right-0">
             <StatCard 
              label="Active Pathways" 
              value="312" 
              icon={<Activity className="w-4 h-4 text-cyan-400" />}
            />
          </div>

          <div className="absolute bottom-1/4 right-10">
            <StatCard 
              label="Errors Caught" 
              value="15" 
              error={hasError}
              icon={<AlertTriangle className={`w-4 h-4 ${hasError ? 'text-red-400' : 'text-cyan-400'}`} />}
            />
          </div>

        </div>
      </div>

      {/* Bottom Timeline */}
      <div className="absolute bottom-0 left-0 right-0 p-6 z-20 border-t border-cyan-900/30 bg-[#020617]/80 backdrop-blur-md">
        <div className="max-w-6xl mx-auto">
          <h3 className="text-xs uppercase tracking-widest text-cyan-600 mb-4 font-semibold">Live Event Stream</h3>
          <div className="flex items-center gap-4 overflow-hidden">
            <EventItem status="pass" id="CHK-8842" time="12ms ago" />
            <EventItem status="pass" id="CHK-8841" time="45ms ago" />
            <EventItem status="pass" id="CHK-8840" time="120ms ago" />
            <EventItem status={hasError ? "fail" : "pass"} id="CHK-8839" time="240ms ago" />
            <EventItem status="pass" id="CHK-8838" time="450ms ago" />
            <EventItem status="pass" id="CHK-8837" time="890ms ago" />
            <EventItem status="fail" id="CHK-8836" time="1.2s ago" />
            <div className="flex-1 h-px bg-gradient-to-r from-cyan-900/50 to-transparent" />
          </div>
        </div>
      </div>

    </div>
  );
}

function StatCard({ label, value, trend, icon, error }: { label: string; value: string; trend?: string; icon: React.ReactNode; error?: boolean }) {
  return (
    <div className={`p-4 rounded-xl border bg-black/40 backdrop-blur-md transition-colors duration-300 w-48 ${error ? 'border-red-500/50 shadow-[0_0_15px_rgba(239,68,68,0.2)]' : 'border-cyan-500/20 shadow-[0_0_15px_rgba(6,182,212,0.1)]'}`}>
      <div className="flex items-center gap-2 mb-2">
        {icon}
        <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">{label}</span>
      </div>
      <div className="flex items-baseline gap-2">
        <div className={`text-3xl font-light tracking-tight ${error ? 'text-red-100' : 'text-cyan-50'}`}>{value}</div>
        {trend && <div className="text-xs text-cyan-400">{trend}</div>}
      </div>
    </div>
  );
}

function EventItem({ status, id, time }: { status: 'pass' | 'fail'; id: string; time: string }) {
  return (
    <div className={`flex flex-col gap-1 border-l-2 pl-3 py-1 ${status === 'pass' ? 'border-cyan-500/50' : 'border-red-500/80'}`}>
      <div className="flex items-center gap-2">
        {status === 'pass' ? (
          <CheckCircle2 className="w-3 h-3 text-cyan-500" />
        ) : (
          <AlertTriangle className="w-3 h-3 text-red-500" />
        )}
        <span className={`text-xs font-medium ${status === 'pass' ? 'text-cyan-100' : 'text-red-100'}`}>{id}</span>
      </div>
      <span className="text-[10px] text-slate-500 font-mono">{time}</span>
    </div>
  );
}
