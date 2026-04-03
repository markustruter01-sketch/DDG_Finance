const TICKER_TEXT = "System Note: Our 6-bot fleet (Stocks, Crypto, Forex, Futures) is currently in its Self-Learning Phase. Powered by institutional algorithms and Gemini AI, the system auto-optimizes parameters every 3 hours, logging every trend and trade into a persistent neural journal to sharpen performance. Want to build this automated trading platform for yourself in 2 days? DM this channel to register interest, this will help us understand demand and create a instruction manual. No experience needed!";

function TickerBlock() {
  return (
    <>
      <span className="px-8" style={{ color: "rgba(34,211,238,0.8)" }}>{TICKER_TEXT}</span>
      <span className="px-6" style={{ color: "rgba(250,204,21,0.6)" }}>|</span>
      <span className="px-8 font-bold" style={{ color: "rgba(251,146,60,0.9)" }}>
        <span style={{ color: "#facc15" }}>WARNING</span>: This is not financial advice, only a system demonstration. Past performance does not guarantee future results. Trade at your own risk.
      </span>
      <span className="px-6" style={{ color: "rgba(34,211,238,0.4)" }}>|</span>
    </>
  );
}

export function SalesTicker() {
  return (
    <div className="relative overflow-hidden border-t border-cyan-500/20 bg-slate-950/90 py-2.5 shrink-0">
      <div className="absolute left-0 top-0 bottom-0 w-16 bg-gradient-to-r from-slate-950 to-transparent z-10" />
      <div className="absolute right-0 top-0 bottom-0 w-16 bg-gradient-to-l from-slate-950 to-transparent z-10" />
      <div
        className="flex whitespace-nowrap font-mono ticker-scroll"
        style={{ fontSize: "15px" }}
      >
        <TickerBlock />
        <TickerBlock />
      </div>
      <style>{`
        .ticker-scroll {
          animation: tickerScroll 15s linear infinite;
        }
        @keyframes tickerScroll {
          0% { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
      `}</style>
    </div>
  );
}
