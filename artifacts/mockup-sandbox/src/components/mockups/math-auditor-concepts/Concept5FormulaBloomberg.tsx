import React, { useEffect, useState } from 'react';

export function Concept5FormulaBloomberg() {
  const [mounted, setMounted] = useState(false);
  
  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) return null;

  return (
    <div className="min-h-screen bg-black text-[#ffb000] font-mono overflow-hidden select-none p-1 pb-2 flex flex-col h-screen">
      <style>{`
        @keyframes scrollLeft {
          0% { transform: translateX(100%); }
          100% { transform: translateX(-100%); }
        }
        .animate-ticker {
          animation: scrollLeft 20s linear infinite;
        }
        @keyframes blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0; }
        }
        .animate-blink {
          animation: blink 1s step-end infinite;
        }
        @keyframes randomStream1 {
          0% { content: "1.2345"; }
          20% { content: "1.2401"; }
          40% { content: "1.2399"; }
          60% { content: "1.2382"; }
          80% { content: "1.2410"; }
          100% { content: "1.2345"; }
        }
        @keyframes randomStream2 {
          0% { content: "0.084"; }
          25% { content: "0.087"; }
          50% { content: "0.081"; }
          75% { content: "0.089"; }
          100% { content: "0.084"; }
        }
        @keyframes flashRed {
          0%, 100% { background-color: transparent; color: #ff3333; }
          50% { background-color: #ff3333; color: black; }
        }
        .flash-error {
          animation: flashRed 1s infinite;
        }
        
        .number-stream-1::after { content: "0.00"; animation: randomStream1 2s infinite; }
        .number-stream-2::after { content: "0.00"; animation: randomStream2 1.5s infinite; }
        
        @keyframes scrollUp {
          0% { transform: translateY(0); }
          100% { transform: translateY(-50%); }
        }
        .scroll-container {
          display: flex;
          flex-direction: column;
          animation: scrollUp 10s linear infinite;
        }
      `}</style>

      {/* Top Ticker */}
      <div className="bg-[#ffb000] text-black font-bold text-sm tracking-widest whitespace-nowrap overflow-hidden py-0.5 border-b-2 border-black flex-none">
        <div className="animate-ticker inline-block">
          QUANT AUDIT TERMINAL&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;MATH AUDITOR v4&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;99.2% PASS&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;1847 CHECKS&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;15 ERRORS&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;SYSTEM NOMINAL&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;LATENCY 4MS&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;QUANT AUDIT TERMINAL
        </div>
      </div>

      <div className="flex-1 grid grid-cols-2 grid-rows-3 gap-1 mt-1">
        {/* Panel 1: Sharpe Ratio */}
        <div className="border border-[#ffb000] flex flex-col">
          <div className="bg-[#ffb000] text-black font-bold px-2 py-0.5 uppercase flex justify-between">
            <span>F1: SHARPE CALC</span>
            <span>[RUNNING]</span>
          </div>
          <div className="p-2 text-xs flex-1 flex flex-col justify-between">
            <div className="flex justify-between text-[#00ffff]">
              <span>RP (RETURN PORTFOLIO)</span>
              <span className="number-stream-1"></span>
            </div>
            <div className="flex justify-between text-[#00ffff]">
              <span>RF (RISK FREE RATE)</span>
              <span>0.0450</span>
            </div>
            <div className="flex justify-between text-[#00ffff]">
              <span>STD DEV (PORTFOLIO)</span>
              <span className="number-stream-2"></span>
            </div>
            <div className="border-t border-[#ffb000] my-1 border-dashed"></div>
            <div className="text-[#33ff33] text-sm">
              <span className="opacity-70">Formula: (Rp - Rf) / σp</span>
            </div>
            <div className="flex justify-between font-bold text-lg">
              <span>SHARPE RATIO</span>
              <span className="text-[#33ff33]">2.8<span className="animate-blink">_</span></span>
            </div>
          </div>
        </div>

        {/* Panel 2: Kelly Sizing */}
        <div className="border border-[#ffb000] flex flex-col">
          <div className="bg-[#ffb000] text-black font-bold px-2 py-0.5 uppercase flex justify-between">
            <span>F2: KELLY SIZING</span>
            <span>[OPTIMAL]</span>
          </div>
          <div className="p-2 text-xs flex-1 flex flex-col gap-1 overflow-hidden relative">
            <div className="flex justify-between text-[#00ffff]"><span>WIN PROB (W)</span><span>0.65</span></div>
            <div className="flex justify-between text-[#00ffff]"><span>LOSS PROB (L)</span><span>0.35</span></div>
            <div className="flex justify-between text-[#00ffff]"><span>PAYOFF RATIO (R)</span><span>1.50</span></div>
            <div className="border-t border-[#ffb000] border-dashed my-0.5"></div>
            <div className="text-[#ffb000]">K% = W - (L / R)</div>
            <div className="text-[#ffb000]">K% = 0.65 - (0.35 / 1.50)</div>
            <div className="text-[#ffb000]">K% = 0.65 - 0.233</div>
            <div className="flex justify-between text-[#33ff33] font-bold mt-1 text-lg">
              <span>KELLY FRACTION</span>
              <span>41.67%</span>
            </div>
            <div className="text-xs text-[#00ffff] mt-1">HALF-KELLY REC: 20.83%</div>
          </div>
        </div>

        {/* Panel 3: VaR Calculation */}
        <div className="border border-[#ffb000] flex flex-col">
          <div className="bg-[#ffb000] text-black font-bold px-2 py-0.5 uppercase flex justify-between">
            <span>F3: VAR PIPELINE</span>
            <span>[99% CI]</span>
          </div>
          <div className="p-2 text-xs flex-1 font-mono">
            <div className="mb-1">ESTIMATING VAR(99%, 1D)</div>
            <div className="grid grid-cols-2 gap-1 text-[#00ffff]">
              <div>Z-SCORE(99%)</div><div className="text-right">2.326</div>
              <div>PORTFOLIO VAL</div><div className="text-right">$10.5M</div>
              <div>VOLATILITY(1D)</div><div className="text-right">0.015</div>
            </div>
            <div className="border-t border-[#ffb000] border-dashed my-1"></div>
            <div className="flex justify-between text-[#ff3333]">
              <span>PARAMETRIC VAR</span>
              <span>$366,345</span>
            </div>
            <div className="flex justify-between text-[#ff3333]">
              <span>HISTORICAL VAR</span>
              <span>$392,100</span>
            </div>
            <div className="flex justify-between text-[#ff3333]">
              <span>MONTE CARLO VAR</span>
              <span>$388,500</span>
            </div>
            <div className="mt-1 flex gap-2">
              <span className="bg-[#ff3333] text-black px-1">LIMIT: $500K</span>
              <span className="text-[#33ff33]">OK</span>
            </div>
          </div>
        </div>

        {/* Panel 4: P&L Reconciliation */}
        <div className="border border-[#ffb000] flex flex-col">
          <div className="bg-[#ffb000] text-black font-bold px-2 py-0.5 uppercase flex justify-between">
            <span>F4: P&L RECONCILIATION</span>
            <span>[TRADE #88492]</span>
          </div>
          <div className="p-2 text-xs flex-1">
            <div className="text-[#00ffff] mb-1">ASSET: BTC/USD | DIR: LONG | QTY: 2.5</div>
            <table className="w-full text-left">
              <tbody>
                <tr><td>ENTRY PRICE</td><td className="text-right text-[#00ffff]">$62,400.00</td></tr>
                <tr><td>EXIT PRICE</td><td className="text-right text-[#00ffff]">$63,150.00</td></tr>
                <tr><td>GROSS PNL</td><td className="text-right text-[#33ff33]">+$1,875.00</td></tr>
                <tr><td>FEES (0.1%)</td><td className="text-right text-[#ff3333]">-$157.69</td></tr>
                <tr><td>SLIPPAGE</td><td className="text-right text-[#ff3333]">-$12.50</td></tr>
              </tbody>
            </table>
            <div className="border-t border-[#ffb000] border-dashed my-1"></div>
            <div className="flex justify-between font-bold">
              <span>NET PNL</span>
              <span className="text-[#33ff33]">+$1,704.81</span>
            </div>
            <div className="flex justify-between text-[10px] mt-1 text-[#00ffff]">
              <span>AUDIT MATCH</span>
              <span className="bg-[#33ff33] text-black px-1">TRUE</span>
            </div>
          </div>
        </div>

        {/* Panel 5: Risk-Adjusted Return Waterfall */}
        <div className="border border-[#ffb000] flex flex-col">
          <div className="bg-[#ffb000] text-black font-bold px-2 py-0.5 uppercase flex justify-between">
            <span>F5: RISK-ADJUSTED WATERFALL</span>
            <span>[MONTHLY]</span>
          </div>
          <div className="p-2 text-xs flex-1 font-mono">
            <div className="flex justify-between mb-0.5">
              <span>NOMINAL RETURN</span><span className="text-[#33ff33]">+8.4%</span>
            </div>
            <div className="pl-2 border-l border-[#ffb000] flex flex-col gap-0.5 my-1 text-[#00ffff]">
              <div className="flex justify-between"><span>- BENCHMARK (SPY)</span><span>-2.1%</span></div>
              <div className="flex justify-between"><span>- FINANCING COST</span><span>-0.4%</span></div>
              <div className="flex justify-between"><span>- VOL PENALTY</span><span>-1.2%</span></div>
            </div>
            <div className="flex justify-between font-bold">
              <span>ALPHA (RAW)</span><span className="text-[#33ff33]">+4.7%</span>
            </div>
            <div className="pl-2 border-l border-[#ffb000] flex flex-col gap-0.5 my-1 text-[#00ffff]">
              <div className="flex justify-between"><span>* BETA ADJ (0.8)</span><span></span></div>
              <div className="flex justify-between"><span>- TAIL RISK RES.</span><span>-0.5%</span></div>
            </div>
            <div className="flex justify-between font-bold text-sm mt-1">
              <span>TRUE ALPHA</span><span className="text-[#33ff33] bg-[#002200] px-1">+4.2%</span>
            </div>
          </div>
        </div>

        {/* Panel 6: Audit Log */}
        <div className="border border-[#ffb000] flex flex-col overflow-hidden relative">
          <div className="bg-[#ffb000] text-black font-bold px-2 py-0.5 uppercase flex justify-between z-10 relative">
            <span>F6: AUDIT LOG</span>
            <span className="animate-blink">LIVE</span>
          </div>
          <div className="p-2 text-[10px] flex-1 overflow-hidden relative font-mono text-[#00ffff] leading-tight">
            <div className="absolute inset-0 overflow-hidden">
              <div className="scroll-container">
                <div className="flex flex-col gap-0.5">
                  <div>14:02:01.112 [MACD] RECON: <span className="text-[#33ff33]">PASS</span></div>
                  <div>14:02:01.442 [RSI] BOUNDS: <span className="text-[#33ff33]">PASS</span></div>
                  <div>14:02:01.889 [VAR] HIST: <span className="text-[#33ff33]">PASS</span></div>
                  <div>14:02:02.001 [POS] SIZE: <span className="text-[#33ff33]">PASS</span></div>
                  <div>14:02:02.105 [PNL] T-882: <span className="text-[#33ff33]">PASS</span></div>
                  <div className="flash-error">14:02:02.333 [FEE] DRIFT: FAIL (0.01%)</div>
                  <div>14:02:02.551 [BAL] SYNC: <span className="text-[#33ff33]">PASS</span></div>
                  <div>14:02:02.881 [VOL] CALC: <span className="text-[#33ff33]">PASS</span></div>
                  <div>14:02:03.111 [BTA] EST: <span className="text-[#33ff33]">PASS</span></div>
                  <div>14:02:03.442 [SHP] CHK: <span className="text-[#33ff33]">PASS</span></div>
                  <div>14:02:04.112 [MACD] RECON: <span className="text-[#33ff33]">PASS</span></div>
                  <div>14:02:04.442 [RSI] BOUNDS: <span className="text-[#33ff33]">PASS</span></div>
                  <div className="flash-error">14:02:04.889 [VAR] LMT: WARN (98%)</div>
                  <div>14:02:05.001 [POS] SIZE: <span className="text-[#33ff33]">PASS</span></div>
                  <div>14:02:05.105 [PNL] T-883: <span className="text-[#33ff33]">PASS</span></div>
                  <div>14:02:05.333 [FEE] CHK: <span className="text-[#33ff33]">PASS</span></div>
                </div>
                {/* Duplicate for infinite scroll */}
                <div className="flex flex-col gap-0.5 mt-0.5">
                  <div>14:02:01.112 [MACD] RECON: <span className="text-[#33ff33]">PASS</span></div>
                  <div>14:02:01.442 [RSI] BOUNDS: <span className="text-[#33ff33]">PASS</span></div>
                  <div>14:02:01.889 [VAR] HIST: <span className="text-[#33ff33]">PASS</span></div>
                  <div>14:02:02.001 [POS] SIZE: <span className="text-[#33ff33]">PASS</span></div>
                  <div>14:02:02.105 [PNL] T-882: <span className="text-[#33ff33]">PASS</span></div>
                  <div className="flash-error">14:02:02.333 [FEE] DRIFT: FAIL (0.01%)</div>
                  <div>14:02:02.551 [BAL] SYNC: <span className="text-[#33ff33]">PASS</span></div>
                  <div>14:02:02.881 [VOL] CALC: <span className="text-[#33ff33]">PASS</span></div>
                  <div>14:02:03.111 [BTA] EST: <span className="text-[#33ff33]">PASS</span></div>
                  <div>14:02:03.442 [SHP] CHK: <span className="text-[#33ff33]">PASS</span></div>
                  <div>14:02:04.112 [MACD] RECON: <span className="text-[#33ff33]">PASS</span></div>
                  <div>14:02:04.442 [RSI] BOUNDS: <span className="text-[#33ff33]">PASS</span></div>
                  <div className="flash-error">14:02:04.889 [VAR] LMT: WARN (98%)</div>
                  <div>14:02:05.001 [POS] SIZE: <span className="text-[#33ff33]">PASS</span></div>
                  <div>14:02:05.105 [PNL] T-883: <span className="text-[#33ff33]">PASS</span></div>
                  <div>14:02:05.333 [FEE] CHK: <span className="text-[#33ff33]">PASS</span></div>
                </div>
              </div>
            </div>
            {/* Overlay gradient to fade out top and bottom */}
            <div className="absolute inset-x-0 top-0 h-4 bg-gradient-to-b from-black to-transparent z-10 pointer-events-none"></div>
            <div className="absolute inset-x-0 bottom-0 h-4 bg-gradient-to-t from-black to-transparent z-10 pointer-events-none"></div>
          </div>
        </div>
      </div>
    </div>
  );
}
