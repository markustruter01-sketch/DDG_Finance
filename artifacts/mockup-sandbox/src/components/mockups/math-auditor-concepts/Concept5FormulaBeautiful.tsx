import React, { useEffect, useState } from 'react';

export function Concept5FormulaBeautiful() {
  const [activeStage, setActiveStage] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setActiveStage((prev) => (prev + 1) % 4);
    }, 4000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="min-h-screen bg-[#111312] text-[#e8e9e2] font-serif p-8 relative overflow-hidden flex flex-col">
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,600;0,800;1,400&display=swap');
        
        .font-playfair {
          font-family: 'Playfair Display', serif;
        }

        .chalk-text {
          color: #f4f5f0;
          text-shadow: 0 0 4px rgba(244, 245, 240, 0.4), 0 0 10px rgba(244, 245, 240, 0.2);
        }

        .gold-glow {
          color: #fcd34d;
          text-shadow: 0 0 8px rgba(252, 211, 77, 0.6), 0 0 15px rgba(252, 211, 77, 0.4);
        }

        .green-glow {
          color: #4ade80;
          text-shadow: 0 0 8px rgba(74, 222, 128, 0.6), 0 0 15px rgba(74, 222, 128, 0.4);
        }

        .red-glow {
          color: #f87171;
          text-shadow: 0 0 8px rgba(248, 113, 113, 0.6), 0 0 15px rgba(248, 113, 113, 0.4);
        }

        @keyframes typewrite {
          from { width: 0; opacity: 0; }
          to { width: 100%; opacity: 1; }
        }

        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(10px); }
          to { opacity: 1; transform: translateY(0); }
        }

        @keyframes stamp {
          0% { opacity: 0; transform: scale(2) rotate(-10deg); }
          50% { opacity: 1; transform: scale(0.9) rotate(-10deg); }
          100% { opacity: 1; transform: scale(1) rotate(-10deg); }
        }
        
        @keyframes shake {
          0%, 100% { transform: translateX(0); }
          10%, 30%, 50%, 70%, 90% { transform: translateX(-5px); }
          20%, 40%, 60%, 80% { transform: translateX(5px); }
        }

        .animate-type {
          display: inline-block;
          overflow: hidden;
          white-space: nowrap;
          animation: typewrite 1.5s steps(40, end) forwards;
        }

        .animate-fade {
          animation: fadeIn 1s ease-out forwards;
        }

        .animate-stamp {
          animation: stamp 0.5s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards;
        }
        
        .animate-shake {
          animation: shake 0.6s cubic-bezier(.36,.07,.19,.97) both;
        }

        /* Chalk dust overlay */
        .chalk-dust {
          position: absolute;
          top: 0; left: 0; right: 0; bottom: 0;
          background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)' opacity='0.05'/%3E%3C/svg%3E");
          pointer-events: none;
          z-index: 10;
        }
      `}</style>
      
      <div className="chalk-dust"></div>

      {/* Header */}
      <header className="flex justify-between items-end border-b border-white/20 pb-6 mb-12 z-20">
        <div>
          <h1 className="font-playfair text-4xl tracking-widest chalk-text uppercase mb-2">Quant Formula Verification Engine</h1>
          <p className="text-white/60 italic text-lg">Continuous Cryptographic Audit Protocol</p>
        </div>
        <div className="text-right">
          <div className="text-sm text-white/50 tracking-widest uppercase mb-1">System Status</div>
          <div className="green-glow text-xl tracking-wider">ACTIVE & VERIFYING</div>
        </div>
      </header>

      <div className="flex-1 grid grid-cols-12 gap-12 z-20">
        
        {/* Main Board */}
        <div className="col-span-9 flex flex-col gap-16 relative">
          
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] bg-white/5 rounded-full blur-[100px] pointer-events-none mix-blend-screen"></div>

          {/* Sharpe Ratio */}
          <div className="relative">
            <div className="text-white/40 mb-2 text-sm uppercase tracking-widest">Theorem 1. Sharpe Ratio Verification</div>
            <div className="text-5xl font-playfair chalk-text leading-tight flex items-center flex-wrap gap-4">
              <span>S = (</span>
              <span className={activeStage >= 1 ? "gold-glow font-mono" : ""}>
                {activeStage >= 1 ? "0.125" : "Rₚ"}
              </span>
              <span>−</span>
              <span className={activeStage >= 1 ? "gold-glow font-mono" : ""}>
                {activeStage >= 1 ? "0.042" : "R𝒻"}
              </span>
              <span>) /</span>
              <span className={activeStage >= 1 ? "gold-glow font-mono" : ""}>
                {activeStage >= 1 ? "0.18" : "σₚ"}
              </span>
              
              {activeStage >= 2 && (
                <span className="ml-4 animate-fade flex items-center gap-4">
                  <span>=</span>
                  <span className="gold-glow font-mono font-bold">0.461</span>
                </span>
              )}
            </div>
            {activeStage >= 3 && (
              <div className="absolute -right-8 top-0 green-glow text-3xl font-bold border-4 border-[#4ade80] px-4 py-1 rounded animate-stamp transform -rotate-12 bg-[#111312]/80 backdrop-blur-sm">
                ✓ VERIFIED
              </div>
            )}
          </div>

          {/* Kelly Criterion */}
          <div className="relative">
            <div className="text-white/40 mb-2 text-sm uppercase tracking-widest">Theorem 2. Kelly Criterion Allocation</div>
            <div className="text-5xl font-playfair chalk-text leading-tight flex items-center flex-wrap gap-4">
              <span>f* = (</span>
              <span className={activeStage >= 2 ? "gold-glow font-mono" : ""}>
                {activeStage >= 2 ? "1.5 × 0.55" : "b·p"}
              </span>
              <span>−</span>
              <span className={activeStage >= 2 ? "gold-glow font-mono" : ""}>
                {activeStage >= 2 ? "0.45" : "q"}
              </span>
              <span>) /</span>
              <span className={activeStage >= 2 ? "gold-glow font-mono" : ""}>
                {activeStage >= 2 ? "1.5" : "b"}
              </span>
              
              {activeStage >= 3 && (
                <span className="ml-4 animate-fade flex items-center gap-4">
                  <span>=</span>
                  <span className="gold-glow font-mono font-bold">0.25</span>
                </span>
              )}
            </div>
          </div>

          {/* VaR - Failed Audit Example */}
          <div className="relative">
            <div className="text-white/40 mb-2 text-sm uppercase tracking-widest">Theorem 3. Value at Risk (99%)</div>
            <div className={`text-5xl font-playfair chalk-text leading-tight flex items-center flex-wrap gap-4 ${activeStage === 3 ? 'animate-shake' : ''}`}>
              <span>VaR =</span>
              <span className={activeStage >= 1 ? "gold-glow font-mono" : ""}>
                {activeStage >= 1 ? "0.08" : "μ"}
              </span>
              <span>−</span>
              <span className={activeStage >= 1 ? "gold-glow font-mono" : ""}>
                {activeStage >= 1 ? "2.33" : "z"}
              </span>
              <span className={activeStage >= 2 ? "red-glow font-mono font-bold border-b-2 border-red-500" : ""}>
                {activeStage >= 2 ? "NaN" : "σ"}
              </span>
              <span>√</span>
              <span className={activeStage >= 1 ? "gold-glow font-mono" : ""}>
                {activeStage >= 1 ? "10" : "t"}
              </span>
            </div>
            {activeStage >= 3 && (
              <div className="absolute -right-8 top-0 red-glow text-3xl font-bold border-4 border-[#f87171] px-4 py-1 rounded animate-stamp transform rotate-6 bg-[#111312]/80 backdrop-blur-sm">
                ⚠ ANOMALY DETECTED
              </div>
            )}
          </div>
          
        </div>

        {/* Side Panel Stats */}
        <div className="col-span-3 border-l border-white/20 pl-12 flex flex-col gap-12 z-20">
          
          <div>
            <div className="text-white/40 uppercase tracking-widest text-sm mb-6">Global Audit Integrity</div>
            <div className="relative w-48 h-48 flex items-center justify-center">
              <svg className="w-full h-full transform -rotate-90" viewBox="0 0 100 100">
                <circle cx="50" cy="50" r="45" fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth="4" />
                <circle cx="50" cy="50" r="45" fill="none" stroke="#fcd34d" strokeWidth="4" strokeDasharray="282.7" strokeDashoffset="2.2" className="transition-all duration-1000 ease-out" />
              </svg>
              <div className="absolute text-center">
                <div className="text-5xl font-playfair gold-glow">99.2<span className="text-3xl">%</span></div>
                <div className="text-xs tracking-widest text-white/50 mt-2 uppercase">Pass Rate</div>
              </div>
            </div>
          </div>

          <div className="border-t border-white/10 pt-8">
            <div className="text-4xl font-playfair chalk-text mb-2">1,847</div>
            <div className="text-xs uppercase tracking-widest text-white/50">Formulas Verified Today</div>
          </div>

          <div className="border-t border-white/10 pt-8">
            <div className="text-4xl font-playfair red-glow mb-2">15</div>
            <div className="text-xs uppercase tracking-widest text-white/50">Anomalies Caught</div>
          </div>
          
        </div>
      </div>

      {/* Footer Log */}
      <div className="mt-auto pt-12 border-t border-white/20 z-20">
        <div className="text-sm text-white/40 uppercase tracking-widest mb-4">Recent Verification Log</div>
        <div className="flex gap-8 overflow-hidden">
          {['Black-Scholes Call', 'Sortino Ratio', 'Information Ratio', 'Treynor Measure'].map((name, i) => (
            <div key={i} className="flex items-center gap-3 bg-white/5 px-4 py-2 rounded-full border border-white/10">
              <span className="text-[#4ade80]">✓</span>
              <span className="text-sm italic">{name}</span>
              <span className="text-xs text-white/40 font-mono">14:0{i}:22</span>
            </div>
          ))}
        </div>
      </div>

    </div>
  );
}
