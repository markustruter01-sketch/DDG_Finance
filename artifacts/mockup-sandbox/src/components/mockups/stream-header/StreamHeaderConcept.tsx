import React, { useState, useEffect } from "react";

const BOT_DOTS = [
  { name: "Oracle",   color: "#8b5cf6", active: true  },
  { name: "Davy Jones", color: "#22d3ee", active: true  },
  { name: "Blackbeard", color: "#f97316", active: true  },
  { name: "Navigator", color: "#10b981", active: true  },
  { name: "Poseidon",  color: "#3b82f6", active: true  },
  { name: "Kraken",   color: "#ec4899", active: true  },
];

const METRICS = [
  {
    id: "pnl",
    label: "TOTAL P&L",
    value: "+$14,209",
    sub: "+11.3%",
    positive: true,
    width: "w-[160px]",
  },
  {
    id: "vault",
    label: "VAULT",
    value: "$3,847",
    sub: "secured",
    positive: null,
    width: "w-[130px]",
  },
  {
    id: "best",
    label: "BEST TRADE",
    value: "+18.4%",
    sub: "BTC/USD",
    positive: true,
    width: "w-[140px]",
  },
  {
    id: "worst",
    label: "WORST TRADE",
    value: "−3.1%",
    sub: "COIN",
    positive: false,
    width: "w-[140px]",
  },
  {
    id: "winrate",
    label: "WIN RATE",
    value: "68%",
    sub: "34W / 16L",
    positive: null,
    width: "w-[120px]",
  },
  {
    id: "trades",
    label: "TRADES",
    value: "34W / 16L",
    sub: "50 total",
    positive: null,
    width: "w-[120px]",
  },
  {
    id: "mathaudit",
    label: "MATH AUDIT",
    value: "99.2%",
    sub: "1,040 checks",
    positive: true,
    width: "w-[140px]",
  },
];

export function StreamHeaderConcept() {
  const [pulse, setPulse] = useState(true);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const t = setInterval(() => setTick(n => n + 1), 2000);
    return () => clearInterval(t);
  }, []);

  const time = new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });

  return (
    <div
      className="flex flex-col w-full font-mono"
      style={{ background: "#020617", minHeight: "100vh" }}
    >
      <style dangerouslySetInnerHTML={{ __html: `
        @keyframes hdr-ping {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.4; transform: scale(1.4); }
        }
        @keyframes hdr-shimmer {
          0% { background-position: -200% center; }
          100% { background-position: 200% center; }
        }
        @keyframes hdr-tick {
          0%, 49% { opacity: 1; }
          50%, 100% { opacity: 0; }
        }
        .hdr-live-dot {
          animation: hdr-ping 1.4s ease-in-out infinite;
        }
        .hdr-colon {
          animation: hdr-tick 1s step-end infinite;
        }
      `}} />

      {/* ── THE HEADER BAR ── */}
      <div
        className="w-full shrink-0 flex items-stretch"
        style={{
          height: 52,
          background: "linear-gradient(90deg, rgba(2,6,23,0.98) 0%, rgba(8,16,40,0.98) 50%, rgba(2,6,23,0.98) 100%)",
          borderBottom: "1px solid rgba(34,211,238,0.12)",
          boxShadow: "0 1px 0 rgba(0,0,0,0.6), 0 2px 16px rgba(6,182,212,0.04)",
        }}
      >

        {/* Live indicator */}
        <div className="flex items-center gap-2.5 px-4 shrink-0" style={{ borderRight: "1px solid rgba(255,255,255,0.06)" }}>
          <div className="relative flex items-center justify-center w-2 h-2">
            <span
              className="hdr-live-dot absolute inline-flex rounded-full"
              style={{ width: 8, height: 8, background: "#22c55e", boxShadow: "0 0 6px #22c55e" }}
            />
          </div>
          <span className="text-[10px] font-black tracking-[0.2em] uppercase" style={{ color: "#22c55e" }}>LIVE</span>
        </div>

        {/* Metrics */}
        <div className="flex items-stretch flex-1 overflow-hidden">
          {METRICS.map((m, i) => (
            <React.Fragment key={m.id}>
              <div
                className={`flex flex-col items-start justify-center px-4 shrink-0 ${m.width}`}
                style={{ borderRight: "1px solid rgba(255,255,255,0.05)" }}
              >
                <span
                  className="text-[8px] font-bold uppercase tracking-[0.18em] mb-0.5"
                  style={{ color: "rgba(100,116,139,0.8)" }}
                >
                  {m.label}
                </span>
                {m.id === "trades" ? (
                  <div className="flex items-baseline gap-1">
                    <span className="text-[14px] font-bold leading-none" style={{ color: "#4ade80" }}>34W</span>
                    <span className="text-[11px] font-bold leading-none" style={{ color: "rgba(100,116,139,0.5)" }}>/</span>
                    <span className="text-[14px] font-bold leading-none" style={{ color: "#f87171" }}>16L</span>
                    <span className="text-[10px] font-medium ml-0.5" style={{ color: "rgba(100,116,139,0.6)" }}>50 total</span>
                  </div>
                ) : (
                  <div className="flex items-baseline gap-1.5">
                    <span
                      className="text-[14px] font-bold leading-none"
                      style={{
                        color:
                          m.positive === true  ? "#4ade80" :
                          m.positive === false ? "#f87171" :
                          m.id === "vault"     ? "#a78bfa" :
                          m.id === "winrate"   ? "#22d3ee" :
                          m.id === "mathaudit" ? "#22d3ee" :
                          "#e2e8f0",
                      }}
                    >
                      {m.value}
                    </span>
                    <span
                      className="text-[10px] font-medium"
                      style={{
                        color:
                          m.positive === true  ? "rgba(74,222,128,0.7)" :
                          m.positive === false ? "rgba(248,113,113,0.7)" :
                          "rgba(100,116,139,0.6)",
                      }}
                    >
                      {m.sub}
                    </span>
                  </div>
                )}
              </div>
            </React.Fragment>
          ))}
        </div>

        {/* Active bots section */}
        <div
          className="flex items-center gap-3 px-4 shrink-0"
          style={{ borderLeft: "1px solid rgba(255,255,255,0.05)" }}
        >
          <div className="flex flex-col items-start">
            <span className="text-[8px] font-bold uppercase tracking-[0.18em] mb-1" style={{ color: "rgba(100,116,139,0.8)" }}>
              ACTIVE BOTS
            </span>
            <div className="flex items-center gap-1.5">
              {BOT_DOTS.map((b) => (
                <div
                  key={b.name}
                  title={b.name}
                  className="rounded-full"
                  style={{
                    width: 8, height: 8,
                    background: b.active ? b.color : "rgba(100,116,139,0.2)",
                    boxShadow: b.active ? `0 0 5px ${b.color}` : "none",
                    transition: "all 0.3s",
                  }}
                />
              ))}
              <span className="text-[11px] font-bold ml-1" style={{ color: "#22d3ee" }}>6/6</span>
            </div>
          </div>

          {/* Clock */}
          <div
            className="flex flex-col items-end"
            style={{ borderLeft: "1px solid rgba(255,255,255,0.05)", paddingLeft: 12 }}
          >
            <span className="text-[8px] font-bold uppercase tracking-[0.18em] mb-0.5" style={{ color: "rgba(100,116,139,0.5)" }}>
              UTC
            </span>
            <span className="text-[12px] font-bold tabular-nums" style={{ color: "rgba(148,163,184,0.6)" }}>
              {time}
            </span>
          </div>
        </div>
      </div>

      {/* ── CONTEXT: show bar floating over a mock stream page ── */}
      <div
        className="flex-1 relative overflow-hidden"
        style={{ background: "radial-gradient(ellipse 70% 50% at 50% 40%, rgba(8,145,178,0.06) 0%, transparent 70%)" }}
      >
        {/* Mock neural web dots for context */}
        <svg className="absolute inset-0 w-full h-full opacity-20" preserveAspectRatio="xMidYMid meet">
          <g stroke="#0891b2" strokeWidth="0.6" fill="none" opacity="0.5">
            <path d="M 200,180 C 300,180 350,100 500,140" />
            <path d="M 200,180 C 300,180 350,260 500,240" />
            <path d="M 500,140 C 600,160 680,100 800,180" />
            <path d="M 500,240 C 600,220 680,260 800,180" />
            <path d="M 800,180 C 900,180 950,120 1080,160" />
            <path d="M 150,300 C 250,280 300,180 400,200" />
            <path d="M 1100,300 C 1000,280 950,180 850,200" />
          </g>
          <circle cx="200" cy="180" r="5" fill="#06b6d4" opacity="0.8"/>
          <circle cx="500" cy="140" r="7" fill="#06b6d4" opacity="0.8"/>
          <circle cx="500" cy="240" r="6" fill="#06b6d4" opacity="0.8"/>
          <circle cx="800" cy="180" r="9" fill="#06b6d4" opacity="0.8"/>
          <circle cx="1080" cy="160" r="5" fill="#06b6d4" opacity="0.8"/>
        </svg>

        {/* Annotation labels */}
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="text-center">
            <p className="text-[11px] font-mono uppercase tracking-[0.3em] mb-2" style={{ color: "rgba(34,211,238,0.3)" }}>
              streaming page content
            </p>
            <p className="text-[10px] font-mono" style={{ color: "rgba(100,116,139,0.4)" }}>
              header bar sits above — fixed across all sub-pages
            </p>
          </div>
        </div>

        {/* Callout arrows pointing up to the bar */}
        <div className="absolute top-4 left-6 flex flex-col items-start gap-1">
          <div className="text-[8px] font-bold uppercase tracking-widest" style={{ color: "rgba(34,211,238,0.5)" }}>↑ never changes on tab switch</div>
        </div>
        <div className="absolute top-4 right-6 flex flex-col items-end gap-1">
          <div className="text-[8px] font-bold uppercase tracking-widest" style={{ color: "rgba(34,211,238,0.5)" }}>refreshes every 15s ↑</div>
        </div>
      </div>
    </div>
  );
}
