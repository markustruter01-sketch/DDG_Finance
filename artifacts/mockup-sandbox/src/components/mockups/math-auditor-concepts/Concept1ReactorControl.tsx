import React, { useEffect, useState } from "react";

export function Concept1ReactorControl() {
  const [currentTime, setCurrentTime] = useState(new Date().toISOString());
  
  useEffect(() => {
    const interval = setInterval(() => {
      setCurrentTime(new Date().toISOString());
    }, 100);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="min-h-screen bg-[#0a0f12] text-[#e0e8f5] font-mono overflow-hidden relative selection:bg-green-500/30 flex flex-col">
      <style>{`
        @keyframes spin-slow {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        @keyframes spin-slow-reverse {
          from { transform: rotate(360deg); }
          to { transform: rotate(0deg); }
        }
        @keyframes pulse-glow {
          0%, 100% { filter: drop-shadow(0 0 10px rgba(16, 185, 129, 0.4)); }
          50% { filter: drop-shadow(0 0 25px rgba(16, 185, 129, 0.8)); }
        }
        @keyframes blink-led {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
        @keyframes scanline {
          0% { transform: translateY(-100%); }
          100% { transform: translateY(100vh); }
        }
        @keyframes particle-out {
          0% { transform: scale(0) translate(0, 0); opacity: 1; }
          100% { transform: scale(1) translate(var(--tx), var(--ty)); opacity: 0; }
        }
        .reactor-ring-1 { animation: spin-slow 20s linear infinite; }
        .reactor-ring-2 { animation: spin-slow-reverse 15s linear infinite; }
        .reactor-ring-3 { animation: spin-slow 25s linear infinite; }
        .reactor-ring-4 { animation: spin-slow-reverse 18s linear infinite; }
        .reactor-ring-5 { animation: spin-slow 30s linear infinite; }
        .core-pulse { animation: pulse-glow 2s ease-in-out infinite; }
        .led-blink { animation: blink-led 1s step-end infinite; }
        .led-blink-fast { animation: blink-led 0.3s step-end infinite; }
        
        /* CRT overlay effect */
        .crt-overlay::before {
          content: " ";
          display: block;
          position: absolute;
          top: 0;
          left: 0;
          bottom: 0;
          right: 0;
          background: linear-gradient(
            to bottom,
            rgba(18, 16, 16, 0) 50%,
            rgba(0, 0, 0, 0.25) 50%
          );
          background-size: 100% 4px;
          z-index: 50;
          pointer-events: none;
        }
      `}</style>

      {/* Background Grid */}
      <div className="absolute inset-0 z-0 opacity-10" style={{
        backgroundImage: 'linear-gradient(#222 1px, transparent 1px), linear-gradient(90deg, #222 1px, transparent 1px)',
        backgroundSize: '40px 40px'
      }}></div>
      
      {/* CRT Scanline */}
      <div className="absolute inset-0 z-40 pointer-events-none overflow-hidden crt-overlay">
        <div className="w-full h-2 bg-green-500/10 blur-sm absolute top-0 left-0" style={{ animation: 'scanline 8s linear infinite' }}></div>
      </div>

      {/* Top Alert Banner */}
      <div className="w-full bg-[#1a1111] border-b border-red-900/50 p-2 text-center text-red-500 text-xs tracking-widest uppercase font-bold relative z-10 flex justify-between px-6">
        <span className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-red-500 led-blink-fast"></div> ALERT CONDITION: MINOR ERRORS DETECTED</span>
        <span>SYS.TIME: {currentTime}</span>
        <span>SECTOR 7G OVERRIDE</span>
      </div>

      <div className="flex-1 grid grid-cols-12 gap-6 p-6 relative z-10 h-full max-h-[calc(100vh-2.5rem)]">
        
        {/* Left Panel - Control Sidebar */}
        <div className="col-span-3 flex flex-col gap-6">
          <div className="bg-[#11181c] border border-[#2a363d] rounded-sm p-4 shadow-[0_0_15px_rgba(0,0,0,0.5)]">
            <h2 className="text-[#647f8c] text-xs uppercase tracking-widest mb-4 border-b border-[#2a363d] pb-2">Primary Metrics</h2>
            
            <div className="flex justify-center my-6">
              <div className="relative w-32 h-32 flex items-center justify-center">
                <svg className="absolute inset-0 w-full h-full -rotate-90">
                  <circle cx="64" cy="64" r="58" fill="none" stroke="#2a363d" strokeWidth="8" />
                  <circle cx="64" cy="64" r="58" fill="none" stroke="#10b981" strokeWidth="8" strokeDasharray="364" strokeDashoffset="2.91" className="drop-shadow-[0_0_5px_#10b981]" />
                </svg>
                <div className="text-center">
                  <div className="text-2xl font-bold text-green-400">99.2%</div>
                  <div className="text-[10px] text-[#647f8c] uppercase mt-1">Pass Rate</div>
                </div>
              </div>
            </div>

            <div className="space-y-4">
              <div>
                <div className="text-[10px] text-[#647f8c] uppercase mb-1">Checks Run Today</div>
                <div className="text-xl text-[#e0e8f5] font-bold tracking-wider">1,847</div>
              </div>
              <div>
                <div className="text-[10px] text-[#647f8c] uppercase mb-1">Errors Caught</div>
                <div className="text-xl text-amber-500 font-bold tracking-wider">15</div>
              </div>
              <div>
                <div className="text-[10px] text-[#647f8c] uppercase mb-1">Last Audit</div>
                <div className="text-sm text-[#e0e8f5] tracking-wider">0.3s ago</div>
              </div>
            </div>
          </div>

          <div className="bg-[#11181c] border border-[#2a363d] rounded-sm p-4 flex-1 shadow-[0_0_15px_rgba(0,0,0,0.5)]">
            <h2 className="text-[#647f8c] text-xs uppercase tracking-widest mb-4 border-b border-[#2a363d] pb-2">Subsystem Status</h2>
            <div className="space-y-3">
              {[
                { name: "P&L Integrity", status: "ok" },
                { name: "Position Sizing", status: "warn" },
                { name: "Risk Calc", status: "ok" },
                { name: "Commission Math", status: "ok" },
                { name: "Vault Reconciliation", status: "ok" },
              ].map((sys, i) => (
                <div key={i} className="flex items-center justify-between p-2 bg-[#0a0f12] border border-[#1a2327]">
                  <div className="flex items-center gap-3">
                    <div className={`w-2 h-2 rounded-full ${sys.status === 'ok' ? 'bg-green-500 drop-shadow-[0_0_3px_#10b981] led-blink' : 'bg-amber-500 drop-shadow-[0_0_3px_#f59e0b] led-blink-fast'}`}></div>
                    <span className={`text-xs uppercase ${sys.status === 'ok' ? 'text-[#8ba7b6]' : 'text-amber-400'}`}>{sys.name}</span>
                  </div>
                  <span className={`text-[10px] ${sys.status === 'ok' ? 'text-green-500' : 'text-amber-500'}`}>
                    {sys.status === 'ok' ? 'NOMINAL' : 'WARN'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Center - Reactor Core */}
        <div className="col-span-9 flex flex-col">
          <div className="flex-1 flex items-center justify-center relative border border-[#2a363d] bg-[#11181c] rounded-sm overflow-hidden shadow-inner">
            <div className="absolute top-4 left-4 text-[#647f8c] text-xs uppercase tracking-widest">Reactor Core View</div>
            <div className="absolute top-4 right-4 text-green-500 text-xs uppercase tracking-widest flex items-center gap-2">
              Status: NOMINAL <div className="w-2 h-2 rounded-full bg-green-500 led-blink"></div>
            </div>
            
            {/* SVG Reactor Core */}
            <div className="relative w-[500px] h-[500px] flex items-center justify-center">
              
              {/* Outer Ring 5 - Vault Reconciliation */}
              <svg className="absolute inset-0 w-full h-full reactor-ring-5 opacity-40">
                <circle cx="250" cy="250" r="230" fill="none" stroke="#2a363d" strokeWidth="2" strokeDasharray="4 8" />
                <path d="M 250 20 A 230 230 0 0 1 480 250" fill="none" stroke="#647f8c" strokeWidth="4" />
                <path d="M 250 480 A 230 230 0 0 1 20 250" fill="none" stroke="#647f8c" strokeWidth="4" />
                <text x="250" y="15" fill="#647f8c" fontSize="10" textAnchor="middle" letterSpacing="2">VAULT RECONCILIATION</text>
              </svg>

              {/* Ring 4 - Commission Math */}
              <svg className="absolute inset-0 w-full h-full reactor-ring-4 opacity-60">
                <circle cx="250" cy="250" r="190" fill="none" stroke="#374852" strokeWidth="8" strokeDasharray="1 10" />
                <circle cx="250" cy="250" r="190" fill="none" stroke="#10b981" strokeWidth="2" strokeDasharray="100 800" className="drop-shadow-[0_0_5px_#10b981]" />
                <text x="250" y="55" fill="#8ba7b6" fontSize="10" textAnchor="middle" letterSpacing="1">COMMISSION MATH</text>
              </svg>

              {/* Ring 3 - Risk Calc */}
              <svg className="absolute inset-0 w-full h-full reactor-ring-3">
                <circle cx="250" cy="250" r="150" fill="none" stroke="#455a66" strokeWidth="1" />
                <circle cx="250" cy="250" r="140" fill="none" stroke="#10b981" strokeWidth="4" strokeDasharray="40 20 10 20" opacity="0.8" className="drop-shadow-[0_0_8px_#10b981]" />
                <text x="250" y="95" fill="#10b981" fontSize="10" textAnchor="middle" letterSpacing="3">RISK CALC</text>
              </svg>

              {/* Ring 2 - Position Sizing (Warning State) */}
              <svg className="absolute inset-0 w-full h-full reactor-ring-2">
                <circle cx="250" cy="250" r="100" fill="none" stroke="#f59e0b" strokeWidth="12" strokeDasharray="5 15" className="drop-shadow-[0_0_10px_rgba(245,158,11,0.5)]" />
                <circle cx="250" cy="250" r="110" fill="none" stroke="#f59e0b" strokeWidth="1" strokeDasharray="2 4" />
                <text x="250" y="135" fill="#f59e0b" fontSize="10" textAnchor="middle" letterSpacing="1">POSITION SIZING</text>
              </svg>

              {/* Ring 1 - P&L Integrity */}
              <svg className="absolute inset-0 w-full h-full reactor-ring-1">
                <circle cx="250" cy="250" r="60" fill="none" stroke="#10b981" strokeWidth="3" strokeDasharray="50 10" className="drop-shadow-[0_0_5px_#10b981]" />
                <text x="250" y="185" fill="#10b981" fontSize="9" textAnchor="middle">P&L INT.</text>
              </svg>

              {/* Core Center */}
              <div className="absolute w-20 h-20 rounded-full bg-gradient-to-br from-green-400 to-green-700 flex items-center justify-center core-pulse">
                <div className="w-16 h-16 rounded-full bg-[#0a0f12] flex items-center justify-center">
                  <div className="w-8 h-8 rounded-full bg-green-500 blur-md"></div>
                </div>
              </div>

              {/* Reticle Overlay */}
              <div className="absolute inset-0 pointer-events-none">
                <div className="absolute top-1/2 left-0 w-full h-[1px] bg-[#647f8c] opacity-20"></div>
                <div className="absolute left-1/2 top-0 w-[1px] h-full bg-[#647f8c] opacity-20"></div>
                <div className="absolute top-1/2 left-1/2 w-4 h-4 border border-[#647f8c] -translate-x-1/2 -translate-y-1/2 rounded-full opacity-50"></div>
              </div>

            </div>
          </div>

          {/* Bottom Audit Log */}
          <div className="h-48 bg-[#11181c] border border-[#2a363d] rounded-sm mt-6 p-4 shadow-[0_0_15px_rgba(0,0,0,0.5)] flex flex-col relative overflow-hidden">
            <h2 className="text-[#647f8c] text-xs uppercase tracking-widest mb-3 flex items-center justify-between">
              <span>Live Audit Stream</span>
              <span className="text-[9px] bg-[#2a363d] px-2 py-0.5 rounded text-[#8ba7b6]">AUTOSCROLL</span>
            </h2>
            <div className="flex-1 overflow-hidden font-mono text-[11px] space-y-1 opacity-80" style={{ maskImage: 'linear-gradient(to bottom, transparent, black 20%)' }}>
              <div className="text-[#647f8c]">[10:45:01.223] SYSTEM: Initializing core mathematics validation sequence...</div>
              <div className="text-green-500">[10:45:01.301] OK: Bot ID-492 P&L cross-check nominal (Delta: $0.00)</div>
              <div className="text-green-500">[10:45:01.442] OK: Margin requirements verified for all active fleet positions</div>
              <div className="text-amber-500">[10:45:01.550] WARN: Position sizing anomaly detected on SOL-USD (Off by 0.0001%)</div>
              <div className="text-[#647f8c]">[10:45:01.602] SYSTEM: Applying auto-correction to rounding buffer...</div>
              <div className="text-green-500">[10:45:01.881] OK: Exchange commission reconciliation matched with local ledger</div>
              <div className="text-green-500">[10:45:02.105] OK: Risk limits within bounds (Total Exposure: 14.2%)</div>
              <div className="text-[#e0e8f5] bg-[#2a363d]/50 p-1 mt-1 border-l-2 border-[#647f8c]">
                > Block validation complete. Next cycle in 0.8s.
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
