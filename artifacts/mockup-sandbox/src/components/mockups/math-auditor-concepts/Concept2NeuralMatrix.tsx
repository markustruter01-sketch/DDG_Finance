import React, { useEffect, useState, useMemo } from "react";

export function Concept2NeuralMatrix() {
  const [columns, setColumns] = useState<{ id: number; left: number; duration: number; delay: number; text: string }[]>([]);

  useEffect(() => {
    // Generate random matrix rain characters
    const chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!@#$%^&*()_+-=[]{}|;':,.<>?/~`";
    const cols = [];
    for (let i = 0; i < 50; i++) {
      const dropLength = Math.floor(Math.random() * 20) + 10;
      let drop = "";
      for (let j = 0; j < dropLength; j++) {
        drop += chars.charAt(Math.floor(Math.random() * chars.length)) + "\\n";
      }
      cols.push({
        id: i,
        left: i * 2,
        duration: Math.random() * 2 + 1,
        delay: Math.random() * 2,
        text: drop,
      });
    }
    setColumns(cols);
  }, []);

  const [logs, setLogs] = useState<string[]>([]);
  useEffect(() => {
    const interval = setInterval(() => {
      const id = Math.floor(Math.random() * 999);
      const hex = Math.random().toString(16).substring(2, 10).toUpperCase();
      const status = Math.random() > 0.9 ? 'FAILED' : 'OK';
      const newLog = \`[sys.\${id}] 0x\${hex} - AUDIT CHECK \${status}\`;
      setLogs((prev) => [...prev, newLog].slice(-20));
    }, 500);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="relative w-full h-full min-h-screen bg-black overflow-hidden font-mono text-green-500 select-none">
      <style dangerouslySetInnerHTML={{__html: \`
        .matrix-rain {
          position: absolute;
          top: 0;
          left: 0;
          width: 100%;
          height: 100%;
          overflow: hidden;
          z-index: 0;
          opacity: 0.15;
          pointer-events: none;
        }
        .matrix-column {
          position: absolute;
          top: -100%;
          font-size: 14px;
          line-height: 14px;
          white-space: pre-wrap;
          word-break: break-all;
          width: 14px;
          text-align: center;
          animation-name: fall;
          animation-timing-function: linear;
          animation-iteration-count: infinite;
        }
        @keyframes fall {
          to { top: 100%; }
        }
        .node-pulse {
          animation: pulse 2s infinite alternate;
        }
        .node-pulse-error {
          animation: pulse-error 0.5s infinite alternate;
        }
        @keyframes pulse {
          0% { filter: drop-shadow(0 0 2px #22c55e); }
          100% { filter: drop-shadow(0 0 10px #22c55e); }
        }
        @keyframes pulse-error {
          0% { filter: drop-shadow(0 0 5px #ef4444); }
          100% { filter: drop-shadow(0 0 20px #ef4444); }
        }
        @keyframes scanline {
          0% { transform: translateY(-100%); }
          100% { transform: translateY(100vh); }
        }
        .scanline-effect {
          position: absolute;
          top: 0;
          left: 0;
          width: 100%;
          height: 10%;
          background: linear-gradient(to bottom, transparent, rgba(34, 197, 94, 0.2), transparent);
          animation: scanline 4s linear infinite;
          pointer-events: none;
          z-index: 10;
        }
        .crt-overlay {
          position: absolute;
          top: 0;
          left: 0;
          width: 100%;
          height: 100%;
          background: repeating-linear-gradient(
            0deg,
            rgba(0, 0, 0, 0.15),
            rgba(0, 0, 0, 0.15) 1px,
            transparent 1px,
            transparent 2px
          );
          pointer-events: none;
          z-index: 20;
        }
        .glitch-text {
          position: relative;
        }
        .glitch-text::before, .glitch-text::after {
          content: attr(data-text);
          position: absolute;
          top: 0;
          left: 0;
          width: 100%;
          height: 100%;
          background: black;
        }
        .glitch-text::before {
          left: 2px;
          text-shadow: -1px 0 red;
          clip: rect(24px, 550px, 90px, 0);
          animation: glitch-anim 3s infinite linear alternate-reverse;
        }
        .glitch-text::after {
          left: -2px;
          text-shadow: -1px 0 blue;
          clip: rect(85px, 550px, 140px, 0);
          animation: glitch-anim 2.5s infinite linear alternate-reverse;
        }
        @keyframes glitch-anim {
          0% { clip: rect(10px, 9999px, 83px, 0); }
          5% { clip: rect(62px, 9999px, 18px, 0); }
          10% { clip: rect(32px, 9999px, 4px, 0); }
          15% { clip: rect(81px, 9999px, 76px, 0); }
          20% { clip: rect(96px, 9999px, 2px, 0); }
          25% { clip: rect(17px, 9999px, 11px, 0); }
          30% { clip: rect(54px, 9999px, 84px, 0); }
          35% { clip: rect(72px, 9999px, 55px, 0); }
          40% { clip: rect(83px, 9999px, 20px, 0); }
          45% { clip: rect(24px, 9999px, 63px, 0); }
          50% { clip: rect(41px, 9999px, 9px, 0); }
          55% { clip: rect(91px, 9999px, 71px, 0); }
          60% { clip: rect(14px, 9999px, 49px, 0); }
          65% { clip: rect(66px, 9999px, 33px, 0); }
          70% { clip: rect(3px, 9999px, 95px, 0); }
          75% { clip: rect(88px, 9999px, 42px, 0); }
          80% { clip: rect(21px, 9999px, 68px, 0); }
          85% { clip: rect(59px, 9999px, 15px, 0); }
          90% { clip: rect(38px, 9999px, 87px, 0); }
          95% { clip: rect(75px, 9999px, 26px, 0); }
          100% { clip: rect(11px, 9999px, 52px, 0); }
        }
      \`}} />

      {/* Background Rain */}
      <div className="matrix-rain">
        {columns.map(col => (
          <div 
            key={col.id} 
            className="matrix-column" 
            style={{ 
              left: \`\${col.left}%\`, 
              animationDuration: \`\${col.duration}s\`, 
              animationDelay: \`\${col.delay}s\` 
            }}
          >
            {col.text}
          </div>
        ))}
      </div>
      
      {/* Overlay Graph */}
      <div className="absolute inset-0 z-0 flex items-center justify-center opacity-40 pointer-events-none">
        <svg viewBox="0 0 800 600" className="w-full h-full max-w-4xl max-h-[80vh]">
          <defs>
            <linearGradient id="edge-grad" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#22c55e" stopOpacity="0.2" />
              <stop offset="100%" stopColor="#22c55e" stopOpacity="0.8" />
            </linearGradient>
            <linearGradient id="edge-error" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#ef4444" stopOpacity="0.8" />
              <stop offset="100%" stopColor="#ef4444" stopOpacity="0.2" />
            </linearGradient>
          </defs>
          
          {/* Edges */}
          <line x1="400" y1="300" x2="200" y2="150" stroke="url(#edge-grad)" strokeWidth="2" />
          <line x1="400" y1="300" x2="600" y2="150" stroke="url(#edge-grad)" strokeWidth="2" />
          <line x1="400" y1="300" x2="200" y2="450" stroke="url(#edge-error)" strokeWidth="3" strokeDasharray="5,5" className="animate-[pulse-error_1s_infinite]" />
          <line x1="400" y1="300" x2="600" y2="450" stroke="url(#edge-grad)" strokeWidth="2" />
          <line x1="200" y1="150" x2="100" y2="250" stroke="url(#edge-grad)" strokeWidth="1" />
          <line x1="600" y1="150" x2="700" y2="250" stroke="url(#edge-grad)" strokeWidth="1" />
          <line x1="200" y1="450" x2="100" y2="350" stroke="url(#edge-error)" strokeWidth="2" />
          
          {/* Nodes */}
          <circle cx="400" cy="300" r="15" fill="#000" stroke="#22c55e" strokeWidth="3" className="node-pulse" />
          <circle cx="200" cy="150" r="10" fill="#000" stroke="#22c55e" strokeWidth="2" className="node-pulse" />
          <circle cx="600" cy="150" r="10" fill="#000" stroke="#22c55e" strokeWidth="2" className="node-pulse" />
          <circle cx="200" cy="450" r="12" fill="#000" stroke="#ef4444" strokeWidth="3" className="node-pulse-error" />
          <circle cx="600" cy="450" r="10" fill="#000" stroke="#22c55e" strokeWidth="2" className="node-pulse" />
          <circle cx="100" cy="250" r="6" fill="#000" stroke="#22c55e" strokeWidth="1" className="node-pulse" />
          <circle cx="700" cy="250" r="6" fill="#000" stroke="#22c55e" strokeWidth="1" className="node-pulse" />
          <circle cx="100" cy="350" r="8" fill="#000" stroke="#ef4444" strokeWidth="2" className="node-pulse-error" />
        </svg>
      </div>

      <div className="relative z-10 flex flex-col h-full min-h-screen p-8">
        {/* Header */}
        <header className="mb-12 text-center">
          <h1 
            className="text-5xl md:text-7xl font-bold tracking-tighter text-green-500 drop-shadow-[0_0_15px_rgba(34,197,94,0.8)] glitch-text"
            data-text="AUDIT NETWORK INTEGRITY: 99.2%"
          >
            AUDIT NETWORK INTEGRITY: 99.2%
          </h1>
          <p className="mt-4 text-xl tracking-widest text-green-400/80 uppercase drop-shadow-[0_0_5px_rgba(34,197,94,0.5)]">
            System Subroutine v4.2.0 • Online
          </p>
        </header>

        {/* Main Content */}
        <div className="flex-grow flex flex-col md:flex-row gap-8 justify-between">
          
          {/* Left Panel */}
          <div className="w-full md:w-1/3 max-w-sm flex flex-col gap-6">
            <div className="border border-green-500/50 bg-black/60 p-6 backdrop-blur-sm shadow-[0_0_20px_rgba(34,197,94,0.1)] rounded-none">
              <h2 className="text-2xl border-b border-green-500/50 pb-2 mb-4 drop-shadow-[0_0_5px_rgba(34,197,94,0.8)]">
                &gt; SYS_STATS
              </h2>
              <div className="space-y-4 text-lg">
                <div className="flex justify-between items-end border-b border-green-500/20 pb-1">
                  <span className="text-green-400/70">PASS_RATE</span>
                  <span className="text-2xl drop-shadow-[0_0_5px_rgba(34,197,94,0.8)]">99.2%</span>
                </div>
                <div className="flex justify-between items-end border-b border-green-500/20 pb-1">
                  <span className="text-green-400/70">CHECKS_RUN_TODAY</span>
                  <span className="text-2xl drop-shadow-[0_0_5px_rgba(34,197,94,0.8)]">1,847</span>
                </div>
                <div className="flex justify-between items-end border-b border-red-500/30 pb-1">
                  <span className="text-red-400/70">ERRORS_CAUGHT</span>
                  <span className="text-2xl text-red-500 drop-shadow-[0_0_8px_rgba(239,68,68,0.8)] animate-pulse">15</span>
                </div>
                <div className="flex justify-between items-end border-b border-green-500/20 pb-1">
                  <span className="text-green-400/70">NETWORK_NODES</span>
                  <span className="text-2xl drop-shadow-[0_0_5px_rgba(34,197,94,0.8)]">247</span>
                </div>
              </div>
            </div>

            <div className="border border-green-500/30 bg-black/60 p-6 backdrop-blur-sm shadow-[0_0_15px_rgba(34,197,94,0.1)]">
              <h2 className="text-xl border-b border-green-500/30 pb-2 mb-4 text-green-400/80">
                &gt; NODE_STATUS
              </h2>
              <div className="space-y-2 text-sm">
                <div className="flex items-center gap-3">
                  <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse shadow-[0_0_5px_rgba(34,197,94,1)]"></div>
                  <span>NODE_0X1A: OK</span>
                </div>
                <div className="flex items-center gap-3">
                  <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse shadow-[0_0_5px_rgba(34,197,94,1)]"></div>
                  <span>NODE_0X1B: OK</span>
                </div>
                <div className="flex items-center gap-3 text-red-500">
                  <div className="w-2 h-2 bg-red-500 rounded-full animate-[pulse-error_0.5s_infinite] shadow-[0_0_8px_rgba(239,68,68,1)]"></div>
                  <span>NODE_0X1C: FAIL_DETECTED</span>
                </div>
                <div className="flex items-center gap-3">
                  <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse shadow-[0_0_5px_rgba(34,197,94,1)]"></div>
                  <span>NODE_0X1D: OK</span>
                </div>
              </div>
            </div>
          </div>

        </div>

        {/* Bottom Log */}
        <div className="mt-8 border border-green-500/40 bg-black/80 h-48 p-4 overflow-hidden shadow-[0_0_20px_rgba(34,197,94,0.15)] relative">
          <div className="absolute top-0 left-0 w-full h-full bg-gradient-to-b from-black via-transparent to-transparent z-10 pointer-events-none"></div>
          <div className="absolute bottom-0 left-0 w-full h-full bg-gradient-to-t from-black via-transparent to-transparent z-10 pointer-events-none"></div>
          <div className="flex flex-col justify-end h-full">
            {logs.map((log, i) => (
              <div 
                key={i} 
                className={\`text-xs md:text-sm \${log.includes('FAILED') ? 'text-red-500 drop-shadow-[0_0_3px_rgba(239,68,68,0.8)]' : 'text-green-500/70'}\`}
              >
                {log}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Global Effects */}
      <div className="scanline-effect"></div>
      <div className="crt-overlay"></div>
    </div>
  );
}
