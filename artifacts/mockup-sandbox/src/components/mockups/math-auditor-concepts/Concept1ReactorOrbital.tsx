import React, { useEffect, useState } from "react";
import { Activity, ShieldAlert, Cpu, CheckCircle2 } from "lucide-react";

export function Concept1ReactorOrbital() {
  const [glitchPlanet, setGlitchPlanet] = useState<number | null>(null);

  // Randomly trigger error flashes
  useEffect(() => {
    const interval = setInterval(() => {
      if (Math.random() > 0.7) {
        setGlitchPlanet(Math.floor(Math.random() * 4) + 1);
        setTimeout(() => setGlitchPlanet(null), 1000);
      }
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="relative w-full h-full min-h-[100dvh] bg-[#02040a] text-blue-50 overflow-hidden font-mono selection:bg-blue-900 selection:text-white">
      {/* Dynamic Starfield Background */}
      <style>{`
        @keyframes pulse-core {
          0%, 100% { box-shadow: 0 0 40px 10px rgba(59, 130, 246, 0.4), 0 0 100px 30px rgba(139, 92, 246, 0.2), inset 0 0 20px rgba(255, 255, 255, 0.8); transform: scale(1); }
          50% { box-shadow: 0 0 60px 15px rgba(59, 130, 246, 0.6), 0 0 140px 40px rgba(139, 92, 246, 0.3), inset 0 0 30px rgba(255, 255, 255, 1); transform: scale(1.05); }
        }
        
        @keyframes orbit {
          from { transform: rotate(0deg) translateX(var(--radius)) rotate(0deg); }
          to { transform: rotate(360deg) translateX(var(--radius)) rotate(-360deg); }
        }
        
        @keyframes scroll-up {
          0% { transform: translateY(0); }
          100% { transform: translateY(-50%); }
        }

        .starfield {
          position: absolute;
          width: 200%;
          height: 200%;
          top: -50%;
          left: -50%;
          background-image: 
            radial-gradient(1px 1px at 25px 5px, white, rgba(255,255,255,0)),
            radial-gradient(1px 1px at 50px 25px, white, rgba(255,255,255,0)),
            radial-gradient(1px 1px at 125px 20px, rgba(255,255,255,0.8), rgba(255,255,255,0)),
            radial-gradient(1.5px 1.5px at 50px 75px, white, rgba(255,255,255,0)),
            radial-gradient(2px 2px at 15px 125px, white, rgba(255,255,255,0)),
            radial-gradient(2.5px 2.5px at 110px 80px, rgba(255,255,255,0.9), rgba(255,255,255,0));
          background-size: 200px 200px;
          animation: slow-pan 120s linear infinite;
          opacity: 0.4;
          z-index: 0;
        }

        @keyframes slow-pan {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }

        .orbit-track {
          border: 1px solid rgba(59, 130, 246, 0.1);
          border-radius: 50%;
          position: absolute;
          top: 50%;
          left: 50%;
          transform: translate(-50%, -50%);
        }

        .planet {
          position: absolute;
          top: calc(50% - 6px);
          left: calc(50% - 6px);
          width: 12px;
          height: 12px;
          border-radius: 50%;
          background: #fff;
          box-shadow: 0 0 10px 2px var(--color);
          animation: orbit var(--duration) linear infinite;
        }
        
        .planet::after {
          content: '';
          position: absolute;
          top: 50%;
          left: -40px;
          width: 40px;
          height: 2px;
          background: linear-gradient(90deg, transparent, var(--color));
          transform: translateY(-50%);
          opacity: 0.6;
        }

        .planet.glitch {
          background: #ef4444 !important;
          box-shadow: 0 0 20px 5px rgba(239, 68, 68, 0.8) !important;
          animation-play-state: paused;
          transform: rotate(var(--current-rotation)) translateX(calc(var(--radius) * 1.1)) rotate(calc(var(--current-rotation) * -1)) !important;
          transition: transform 0.1s cubic-bezier(0.4, 0, 0.2, 1);
        }
      `}</style>

      <div className="starfield" />

      {/* SYSTEM STATUS STRIP */}
      <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-blue-900 via-blue-400 to-purple-900 z-50"></div>
      <div className="absolute top-0 left-0 w-full px-6 py-3 flex justify-between items-center z-40 border-b border-white/5 bg-black/40 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <ShieldAlert className="w-5 h-5 text-blue-400" />
          <span className="tracking-[0.2em] text-xs font-bold text-blue-300">MATH_AUDITOR // KRAKEN_FLEET</span>
        </div>
        <div className="flex items-center gap-4 text-xs">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
            <span className="text-green-400">CORE ONLINE</span>
          </div>
          <span className="text-white/40">SYS_TIME: {new Date().toISOString().split('T')[1].split('.')[0]}</span>
        </div>
      </div>

      {/* CENTRAL REACTOR ORBITAL */}
      <div className="absolute inset-0 flex items-center justify-center z-10 pointer-events-none">
        
        {/* Tracks */}
        <div className="orbit-track w-[300px] h-[300px]"></div>
        <div className="orbit-track w-[450px] h-[450px]"></div>
        <div className="orbit-track w-[650px] h-[650px]"></div>
        <div className="orbit-track w-[850px] h-[850px] border-purple-500/10"></div>

        {/* Core Engine */}
        <div 
          className="relative w-32 h-32 rounded-full bg-blue-100 z-20 flex items-center justify-center"
          style={{ animation: 'pulse-core 4s ease-in-out infinite' }}
        >
          <div className="absolute inset-2 rounded-full bg-white/80 blur-sm"></div>
          <Cpu className="w-10 h-10 text-blue-900 z-10 opacity-80" />
        </div>

        {/* Planets (Audit Layers) */}
        {/* Layer 1: Data Integrity */}
        <div 
          className={`planet \${glitchPlanet === 1 ? 'glitch' : ''}`} 
          style={{ '--radius': '150px', '--duration': '8s', '--color': '#60a5fa' } as React.CSSProperties}
        >
          <div className="absolute -top-6 -left-10 w-32 text-center text-[10px] text-blue-200 uppercase tracking-wider opacity-80">
            Data_Integrity
          </div>
        </div>

        {/* Layer 2: PnL Verification */}
        <div 
          className={`planet \${glitchPlanet === 2 ? 'glitch' : ''}`} 
          style={{ '--radius': '225px', '--duration': '14s', '--color': '#818cf8' } as React.CSSProperties}
        >
          <div className="absolute -bottom-6 -left-10 w-32 text-center text-[10px] text-indigo-300 uppercase tracking-wider opacity-80">
            PnL_Verify
          </div>
        </div>

        {/* Layer 3: Risk Bounds */}
        <div 
          className={`planet \${glitchPlanet === 3 ? 'glitch' : ''}`} 
          style={{ '--radius': '325px', '--duration': '22s', '--color': '#c084fc' } as React.CSSProperties}
        >
          <div className="absolute -top-6 -left-10 w-32 text-center text-[10px] text-purple-300 uppercase tracking-wider opacity-80">
            Risk_Bounds
          </div>
        </div>

        {/* Layer 4: Order Validation */}
        <div 
          className={`planet \${glitchPlanet === 4 ? 'glitch' : ''}`} 
          style={{ '--radius': '425px', '--duration': '35s', '--color': '#e879f9' } as React.CSSProperties}
        >
          <div className="absolute -bottom-6 -left-10 w-32 text-center text-[10px] text-fuchsia-300 uppercase tracking-wider opacity-80">
            Order_Valid
          </div>
        </div>

      </div>

      {/* TOP RIGHT HUD - STATS */}
      <div className="absolute top-20 right-6 z-40 flex flex-col gap-4 w-72">
        <div className="bg-blue-950/20 backdrop-blur-xl border border-blue-500/20 rounded-lg p-5 shadow-[0_0_30px_rgba(59,130,246,0.1)] relative overflow-hidden">
          <div className="absolute top-0 right-0 w-20 h-20 bg-blue-500/10 blur-2xl rounded-full translate-x-1/2 -translate-y-1/2"></div>
          <h3 className="text-[10px] text-blue-300 uppercase tracking-[0.2em] mb-4 flex items-center gap-2">
            <Activity className="w-3 h-3" /> Audit Efficacy
          </h3>
          <div className="flex items-baseline gap-2">
            <span className="text-4xl font-light text-white">99.2</span>
            <span className="text-blue-400 font-bold">%</span>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="bg-purple-950/20 backdrop-blur-xl border border-purple-500/20 rounded-lg p-4 shadow-[0_0_20px_rgba(168,85,247,0.1)]">
             <h4 className="text-[9px] text-purple-300 uppercase tracking-widest mb-1">Checks Run Today</h4>
             <div className="text-xl text-white font-light">1,847</div>
          </div>
          
          <div className="bg-red-950/20 backdrop-blur-xl border border-red-500/20 rounded-lg p-4 shadow-[0_0_20px_rgba(239,68,68,0.1)]">
             <h4 className="text-[9px] text-red-300 uppercase tracking-widest mb-1">Errors Caught</h4>
             <div className="text-xl text-red-400 font-light font-bold">15</div>
          </div>
        </div>

        <div className="bg-black/40 backdrop-blur-md border border-white/5 rounded-lg p-3 flex justify-between items-center">
          <span className="text-[10px] text-gray-400 uppercase tracking-wider">Last Audit Cycle</span>
          <span className="text-xs text-blue-300">0.3s ago</span>
        </div>
      </div>

      {/* BOTTOM TELEMETRY FEED */}
      <div className="absolute bottom-0 left-0 w-full h-48 bg-gradient-to-t from-black via-black/80 to-transparent z-40 pointer-events-none flex items-end">
        <div className="w-full px-6 py-4 mask-image-to-t">
          <h3 className="text-[10px] text-blue-500/50 uppercase tracking-[0.3em] mb-4">Live Telemetry Feed</h3>
          
          <div className="h-24 overflow-hidden relative">
            <div className="absolute w-full flex flex-col gap-2" style={{ animation: 'scroll-up 20s linear infinite' }}>
              {[...Array(20)].map((_, i) => (
                <div key={i} className="flex items-center gap-4 text-xs font-mono opacity-60">
                  <span className="text-blue-500/60 w-24">[{new Date(Date.now() - i * 1500).toISOString().split('T')[1].substring(0, 12)}]</span>
                  {i % 7 === 0 ? (
                    <span className="text-red-400/80 w-32">[WARN_BOUNDS]</span>
                  ) : (
                    <span className="text-green-500/60 w-32">[OK_VERIFIED]</span>
                  )}
                  <span className="text-white/40">
                    {i % 3 === 0 ? 'Evaluating momentum constraints against baseline...' : 
                     i % 7 === 0 ? 'Margin limit exceeded projected risk threshold (Delta: +0.02%)' :
                     'Integrity check passed for block sequence 0x7F89...'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
      
      {/* CSS overlay gradient to blend bottom */}
      <style>{`
        .mask-image-to-t {
          mask-image: linear-gradient(to top, rgba(0,0,0,1) 50%, rgba(0,0,0,0) 100%);
          -webkit-mask-image: linear-gradient(to top, rgba(0,0,0,1) 50%, rgba(0,0,0,0) 100%);
        }
      `}</style>
    </div>
  );
}
