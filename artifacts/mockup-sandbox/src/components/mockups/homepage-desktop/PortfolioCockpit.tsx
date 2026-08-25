import type { CSSProperties } from "react";
import "./_group.css";

type Bot = {
  name: string;
  code: string;
  equity: string;
  pnl: string;
  pnlPercent: string;
  sharpe: string;
  drawdown: string;
  winRate: string;
  trades: string;
  biggestWin: string;
  biggestLoss: string;
  exposure: number;
  positions: { ticker: string; side: string; value: string; pnl: string }[];
  cycle: string;
  tone: "cyan" | "lime" | "amber";
  spark: number[];
};

const bots: Bot[] = [
  {
    name: "Oracle",
    code: "ORC-01 / MOMENTUM",
    equity: "$113,150",
    pnl: "+$8,420",
    pnlPercent: "+7.04%",
    sharpe: "1.84",
    drawdown: "-6.2%",
    winRate: "68%",
    trades: "42",
    biggestWin: "+$2,140",
    biggestLoss: "-$780",
    exposure: 72,
    positions: [
      { ticker: "SPY", side: "LONG", value: "$38,420", pnl: "+$1,420" },
      { ticker: "QQQ", side: "LONG", value: "$25,880", pnl: "+$980" },
      { ticker: "XLK", side: "LONG", value: "$17,140", pnl: "+$612" },
    ],
    cycle: "09:42:18 UTC",
    tone: "cyan",
    spark: [32, 35, 31, 42, 47, 43, 52, 56, 51, 62, 68, 74],
  },
  {
    name: "SPY / QQQ Trend",
    code: "TRD-02 / ETF ROTATION",
    equity: "$92,094",
    pnl: "-$1,280",
    pnlPercent: "-1.39%",
    sharpe: "0.91",
    drawdown: "-8.7%",
    winRate: "57%",
    trades: "31",
    biggestWin: "+$1,080",
    biggestLoss: "-$1,460",
    exposure: 64,
    positions: [
      { ticker: "SPY", side: "LONG", value: "$34,760", pnl: "+$184" },
      { ticker: "QQQ", side: "SHORT", value: "$24,190", pnl: "-$842" },
    ],
    cycle: "09:41:56 UTC",
    tone: "amber",
    spark: [62, 58, 64, 60, 54, 58, 50, 53, 47, 44, 48, 43],
  },
  {
    name: "Jerome",
    code: "JRM-03 / MACRO ALLOCATION",
    equity: "$91,154",
    pnl: "+$5,700",
    pnlPercent: "+6.67%",
    sharpe: "1.21",
    drawdown: "-4.9%",
    winRate: "63%",
    trades: "27",
    biggestWin: "+$1,760",
    biggestLoss: "-$920",
    exposure: 81,
    positions: [
      { ticker: "GLD", side: "LONG", value: "$21,470", pnl: "+$760" },
      { ticker: "SLV", side: "LONG", value: "$18,620", pnl: "+$524" },
      { ticker: "DBC", side: "LONG", value: "$16,890", pnl: "+$311" },
      { ticker: "TLT", side: "SHORT", value: "$16,850", pnl: "+$188" },
    ],
    cycle: "09:39:04 UTC",
    tone: "lime",
    spark: [28, 31, 30, 38, 35, 43, 45, 48, 53, 51, 59, 66],
  },
];

const toneColor: Record<Bot["tone"], string> = {
  cyan: "#7ce4df",
  lime: "#c4e879",
  amber: "#f0c27b",
};

function Icon({ name }: { name: "chevron" | "pulse" | "shield" | "arrow" | "radar" }) {
  if (name === "chevron") {
    return <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m5 3 5 5-5 5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>;
  }
  if (name === "shield") {
    return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2.4 16 5v4.1c0 4.2-2.6 7-6 8.5-3.4-1.5-6-4.3-6-8.5V5l6-2.6Z" fill="none" stroke="currentColor" strokeWidth="1.35" /><path d="m6.7 9.9 2.1 2.1 4.6-4.6" fill="none" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" strokeLinejoin="round" /></svg>;
  }
  if (name === "arrow") {
    return <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 12 12 3M5 3h7v7" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>;
  }
  if (name === "radar") {
    return <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="7.1" fill="none" stroke="currentColor" strokeWidth="1" opacity=".55" /><circle cx="10" cy="10" r="3.8" fill="none" stroke="currentColor" strokeWidth="1" opacity=".5" /><path d="M10 10 15.9 5.7M10 2.9v14.2M2.9 10h14.2" stroke="currentColor" strokeWidth="1" opacity=".36" /><path d="M10 10 15.9 5.7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>;
  }
  return <svg viewBox="0 0 18 18" aria-hidden="true"><path d="M2 9h3l1.4-4.3L10 14l1.8-5H16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

function Sparkline({ points, tone }: { points: number[]; tone: Bot["tone"] }) {
  const min = Math.min(...points);
  const max = Math.max(...points);
  const path = points.map((point, index) => {
    const x = (index / (points.length - 1)) * 100;
    const y = 33 - ((point - min) / (max - min || 1)) * 25;
    return `${index === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg className="sparkline" viewBox="0 0 100 36" preserveAspectRatio="none" aria-label="Equity history">
      <path d="M0 33 H100" stroke="rgba(217,240,234,.13)" strokeWidth=".8" />
      <path d={path} fill="none" stroke={toneColor[tone]} strokeWidth="1.8" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function ExposureDial({ value, tone, large = false }: { value: number; tone: Bot["tone"]; large?: boolean }) {
  const radius = large ? 43 : 29;
  const circumference = 2 * Math.PI * radius;
  const dash = (value / 100) * circumference;
  return (
    <div className={`exposure-dial ${large ? "exposure-dial-large" : ""}`} style={{ "--dial-color": toneColor[tone] } as CSSProperties}>
      <svg viewBox="0 0 112 112" aria-hidden="true">
        <circle cx="56" cy="56" r={radius} fill="none" stroke="rgba(206,231,225,.12)" strokeWidth={large ? "7" : "6"} strokeDasharray={`${circumference} ${circumference}`} strokeDashoffset="0" transform="rotate(-112 56 56)" strokeLinecap="round" />
        <circle cx="56" cy="56" r={radius} fill="none" stroke="var(--dial-color)" strokeWidth={large ? "7" : "6"} strokeDasharray={`${dash} ${circumference}`} strokeDashoffset="0" transform="rotate(-112 56 56)" strokeLinecap="round" />
      </svg>
      <div className="dial-reading">
        <strong>{value}%</strong>
        <span>exposure</span>
      </div>
    </div>
  );
}

function Metric({ label, value, negative = false }: { label: string; value: string; negative?: boolean }) {
  return (
    <div className="metric-cell">
      <span>{label}</span>
      <strong className={negative ? "concept-warning" : ""}>{value}</strong>
    </div>
  );
}

function BotCard({ bot, index }: { bot: Bot; index: number }) {
  const color = toneColor[bot.tone];
  const isNegative = bot.pnl.startsWith("-");
  return (
    <article className="bot-card concept-glass" style={{ "--bot-accent": color } as CSSProperties}>
      <div className="bot-card-topline">
        <span className="bot-index">0{index + 1}</span>
        <span className="bot-status"><i /> ONLINE</span>
      </div>
      <div className="bot-card-heading">
        <div>
          <h2>{bot.name}</h2>
          <p>{bot.code}</p>
        </div>
        <div className="bot-card-arrow"><Icon name="arrow" /></div>
      </div>

      <div className="bot-primary">
        <div>
          <span className="concept-label">Bot equity</span>
          <div className="bot-equity concept-number">{bot.equity}</div>
          <div className={`bot-pnl ${isNegative ? "concept-warning" : "concept-positive"}`}>{bot.pnl} <small>{bot.pnlPercent}</small></div>
        </div>
        <ExposureDial value={bot.exposure} tone={bot.tone} />
      </div>

      <div className="section-rule" />
      <div className="position-heading">
        <span className="concept-label">Live positions</span>
        <span className="position-count">{bot.positions.length.toString().padStart(2, "0")} / covered</span>
      </div>
      <div className="position-list">
        {bot.positions.map((position) => (
          <div className="position-row" key={position.ticker}>
            <span className={`position-side ${position.side === "SHORT" ? "short" : ""}`} />
            <strong>{position.ticker}</strong>
            <span className="position-value">{position.value}</span>
            <span className={position.pnl.startsWith("-") ? "concept-warning" : "concept-positive"}>{position.pnl}</span>
          </div>
        ))}
      </div>

      <div className="coverage-line">
        <Icon name="shield" />
        <span>Protective stops</span>
        <strong>100%</strong>
        <div className="coverage-track"><i /></div>
      </div>

      <div className="detail-metrics">
        <Metric label="Sharpe" value={bot.sharpe} />
        <Metric label="Max DD" value={bot.drawdown} negative />
        <Metric label="Win rate" value={bot.winRate} />
        <Metric label="Trades" value={bot.trades} />
        <Metric label="Best trade" value={bot.biggestWin} />
        <Metric label="Worst trade" value={bot.biggestLoss} negative />
      </div>

      <div className="bot-history">
        <div>
          <span className="concept-label">Equity path · 12 cycles</span>
          <span className="cycle-time">last {bot.cycle}</span>
        </div>
        <Sparkline points={bot.spark} tone={bot.tone} />
      </div>
    </article>
  );
}

function RiskRadar() {
  return (
    <aside className="cockpit-radar concept-glass">
      <div className="radar-heading">
        <div>
          <span className="concept-label">Flight instruments</span>
          <h2>Risk radar</h2>
        </div>
        <span className="radar-icon"><Icon name="radar" /></span>
      </div>
      <div className="radar-visual">
        <div className="radar-scan" />
        <div className="radar-crosshair horizontal" />
        <div className="radar-crosshair vertical" />
        <div className="radar-ring ring-one" />
        <div className="radar-ring ring-two" />
        <div className="radar-ring ring-three" />
        <span className="radar-blip blip-a" />
        <span className="radar-blip blip-b" />
        <span className="radar-blip blip-c" />
        <span className="radar-center" />
        <span className="radar-axis axis-x">+RISK</span>
        <span className="radar-axis axis-y">+RETURN</span>
      </div>
      <div className="radar-readings">
        <div><span>Concentration</span><strong>38.4%</strong><i className="reading-bar"><b style={{ width: "38%" }} /></i></div>
        <div><span>Portfolio beta</span><strong>1.08</strong><i className="reading-bar"><b style={{ width: "65%" }} /></i></div>
        <div><span>Stop coverage</span><strong className="concept-positive">100%</strong><i className="reading-bar"><b className="green" style={{ width: "100%" }} /></i></div>
      </div>
      <div className="radar-callout">
        <span className="callout-dot" />
        <div><span className="concept-label">Pilot note</span><strong>Risk within envelope</strong><p>No unhedged exposure detected across the fleet.</p></div>
      </div>
    </aside>
  );
}

const history = [
  ["09:42:18", "ORACLE", "XLK", "+$612", "ENTRY"],
  ["09:41:56", "SPY/QQQ", "QQQ", "-$842", "REBALANCE"],
  ["09:39:04", "JEROME", "TLT", "+$188", "STOP ADJUST"],
  ["09:33:47", "ORACLE", "SPY", "+$1,420", "TAKE PROFIT"],
  ["09:28:11", "JEROME", "GLD", "+$760", "ENTRY"],
];

export function PortfolioCockpit() {
  return (
    <div className="homepage-concept portfolio-cockpit">
      <style>{`
        .portfolio-cockpit {
          --cockpit-ink: #e6f0ec;
          --cockpit-dim: #91aaa6;
          --cockpit-faint: #68817d;
          --cockpit-panel: rgba(8, 30, 35, .68);
          --cockpit-panel-deep: rgba(7, 25, 31, .82);
          min-height: 100dvh;
          overflow: auto;
          background:
            radial-gradient(ellipse at 68% 5%, rgba(80, 156, 151, .35), transparent 35%),
            radial-gradient(ellipse at 18% 58%, rgba(25, 92, 99, .42), transparent 32%),
            linear-gradient(135deg, #294e57 0%, #173c45 48%, #0d252f 100%);
          color: var(--cockpit-ink);
          font-family: 'Space Grotesk', sans-serif;
          position: relative;
        }
        .portfolio-cockpit::before {
          background: linear-gradient(120deg, transparent 0%, rgba(178, 233, 216, .08) 48%, transparent 48.4%, transparent 100%), repeating-linear-gradient(0deg, rgba(192,236,221,.025) 0, rgba(192,236,221,.025) 1px, transparent 1px, transparent 42px);
          filter: none;
          opacity: .65;
        }
        .portfolio-cockpit::after {
          background: radial-gradient(ellipse at 50% 0%, rgba(203, 240, 223, .1), transparent 54%);
        }
        .cockpit-shell { max-width: 1640px; min-width: 1100px; margin: 0 auto; padding: 27px 34px 32px; position: relative; z-index: 1; }
        .cockpit-topbar { align-items: center; display: flex; justify-content: space-between; padding-bottom: 22px; border-bottom: 1px solid rgba(204, 239, 224, .17); }
        .brand-lockup { display: flex; align-items: center; gap: 14px; }
        .brand-mark { width: 31px; height: 31px; display: grid; place-items: center; border: 1px solid rgba(196,232,210,.45); color: #c4e879; transform: rotate(45deg); }
        .brand-mark span { width: 9px; height: 9px; border: 1px solid currentColor; transform: rotate(-45deg); }
        .brand-lockup h1 { margin: 0; font-size: 18px; letter-spacing: .2em; text-transform: uppercase; font-weight: 600; }
        .brand-lockup p { margin: 4px 0 0; color: var(--cockpit-dim); font: 10px 'DM Mono', monospace; letter-spacing: .12em; text-transform: uppercase; }
        .topbar-meta { display: flex; align-items: center; gap: 22px; }
        .market-chip { display: flex; align-items: center; gap: 8px; padding: 8px 11px; color: #c4e879; border: 1px solid rgba(196,232,121,.25); background: rgba(196,232,121,.07); font: 10px 'DM Mono', monospace; letter-spacing: .13em; }
        .market-chip i, .bot-status i { width: 6px; height: 6px; display: inline-block; border-radius: 50%; background: #c4e879; box-shadow: 0 0 0 3px rgba(196,232,121,.11); }
        .topbar-date { color: var(--cockpit-dim); font: 10px 'DM Mono', monospace; letter-spacing: .08em; }
        .fleet-hero { display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(340px, .7fr); gap: 22px; margin: 23px 0 19px; }
        .fleet-card { min-height: 193px; padding: 23px 26px; background: linear-gradient(125deg, rgba(12, 45, 49, .85), rgba(9, 29, 36, .67)); position: relative; overflow: hidden; }
        .fleet-card::after { content: ""; width: 360px; height: 360px; position: absolute; right: -140px; top: -190px; border-radius: 50%; border: 1px solid rgba(194,233,216,.11); box-shadow: 0 0 0 36px rgba(194,233,216,.025), 0 0 0 72px rgba(194,233,216,.025), 0 0 0 108px rgba(194,233,216,.025); }
        .eyebrow-line { display: flex; justify-content: space-between; align-items: center; position: relative; z-index: 1; }
        .telemetry { color: #7ce4df; font: 10px 'DM Mono', monospace; letter-spacing: .12em; }
        .fleet-main { display: flex; align-items: flex-end; gap: 38px; margin-top: 22px; position: relative; z-index: 1; }
        .fleet-equity { font: 500 50px 'DM Mono', monospace; line-height: .95; letter-spacing: -.07em; }
        .fleet-equity small { color: var(--cockpit-dim); display: block; font: 10px 'DM Mono', monospace; letter-spacing: .16em; margin: 9px 0 0 3px; text-transform: uppercase; }
        .fleet-pnl { border-left: 1px solid rgba(202,237,222,.2); padding-left: 28px; margin-bottom: 1px; }
        .fleet-pnl strong { color: #c4e879; display: block; font: 26px 'DM Mono', monospace; letter-spacing: -.05em; }
        .fleet-pnl span { color: #a5c8a0; display: block; font: 11px 'DM Mono', monospace; margin-top: 8px; }
        .fleet-foot { align-items: center; bottom: 21px; color: var(--cockpit-dim); display: flex; gap: 20px; position: absolute; right: 27px; z-index: 1; font: 10px 'DM Mono', monospace; }
        .fleet-foot b { color: var(--cockpit-ink); font-weight: 400; }
        .hero-stat { min-height: 193px; padding: 21px 23px; display: flex; flex-direction: column; justify-content: space-between; }
        .hero-stat-header { display: flex; justify-content: space-between; align-items: center; }
        .hero-stat-title { color: var(--cockpit-dim); font: 10px 'DM Mono', monospace; letter-spacing: .14em; text-transform: uppercase; }
        .hero-stat-header svg { width: 18px; height: 18px; color: #7ce4df; }
        .dial-cluster { display: flex; align-items: center; gap: 17px; }
        .exposure-dial { width: 84px; height: 84px; position: relative; display: grid; place-items: center; flex: 0 0 auto; }
        .exposure-dial-large { width: 116px; height: 116px; }
        .exposure-dial svg { width: 100%; height: 100%; transform: rotate(0deg); }
        .dial-reading { position: absolute; display: flex; flex-direction: column; align-items: center; }
        .dial-reading strong { color: var(--dial-color); font: 18px 'DM Mono', monospace; letter-spacing: -.08em; }
        .dial-reading span { color: var(--cockpit-faint); font: 8px 'DM Mono', monospace; letter-spacing: .08em; margin-top: 2px; text-transform: uppercase; }
        .hero-stat-number { color: #dceae3; font: 28px 'DM Mono', monospace; letter-spacing: -.06em; }
        .hero-stat-note { color: var(--cockpit-dim); font: 10px 'DM Mono', monospace; line-height: 1.55; max-width: 165px; }
        .hero-stat-note b { color: #c4e879; font-weight: 400; }
        .dashboard-grid { display: grid; grid-template-columns: minmax(0, 1fr) 282px; gap: 19px; align-items: start; }
        .bots-section { min-width: 0; }
        .section-heading { display: flex; justify-content: space-between; align-items: baseline; margin: 0 0 10px; }
        .section-heading h2 { margin: 0; color: #d4e7de; font-size: 13px; font-weight: 500; letter-spacing: .11em; text-transform: uppercase; }
        .section-heading span { color: var(--cockpit-faint); font: 10px 'DM Mono', monospace; letter-spacing: .1em; }
        .bot-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
        .bot-card { background: linear-gradient(145deg, rgba(14, 48, 52, .86), rgba(7, 28, 34, .76)); border-color: rgba(192, 228, 214, .16); box-shadow: 0 18px 42px rgba(2, 18, 23, .25), inset 0 1px rgba(227,248,236,.12); min-height: 480px; overflow: hidden; padding: 16px 17px 13px; position: relative; }
        .bot-card::before { background: var(--bot-accent); content: ""; height: 2px; left: 0; opacity: .84; position: absolute; right: 0; top: 0; }
        .bot-card-topline { display: flex; justify-content: space-between; align-items: center; }
        .bot-index { color: var(--bot-accent); font: 11px 'DM Mono', monospace; letter-spacing: .08em; opacity: .9; }
        .bot-status { align-items: center; color: #a4bcb4; display: flex; gap: 7px; font: 9px 'DM Mono', monospace; letter-spacing: .11em; }
        .bot-status i { background: var(--bot-accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--bot-accent) 12%, transparent); height: 5px; width: 5px; }
        .bot-card-heading { align-items: center; display: flex; justify-content: space-between; margin-top: 16px; }
        .bot-card-heading h2 { font-size: 17px; font-weight: 500; letter-spacing: -.02em; margin: 0; }
        .bot-card-heading p { color: var(--cockpit-faint); font: 9px 'DM Mono', monospace; letter-spacing: .09em; margin: 5px 0 0; text-transform: uppercase; }
        .bot-card-arrow { border: 1px solid rgba(201,235,220,.17); color: var(--bot-accent); display: grid; height: 26px; place-items: center; width: 26px; }
        .bot-card-arrow svg { height: 12px; width: 12px; }
        .bot-primary { align-items: center; display: flex; justify-content: space-between; margin: 20px 0 10px; }
        .bot-equity { color: #dceae3; font-size: 24px; line-height: 1; margin-top: 8px; }
        .bot-pnl { font: 12px 'DM Mono', monospace; margin-top: 9px; }
        .bot-pnl small { color: var(--cockpit-dim); font-size: 10px; margin-left: 6px; }
        .bot-primary .exposure-dial { margin-right: 2px; }
        .section-rule { border-top: 1px solid rgba(209,239,226,.13); }
        .position-heading { display: flex; justify-content: space-between; margin: 13px 0 7px; }
        .position-count { color: var(--cockpit-faint); font: 9px 'DM Mono', monospace; }
        .position-list { min-height: 78px; }
        .position-row { align-items: center; border-bottom: 1px solid rgba(209,239,226,.07); display: grid; grid-template-columns: 7px 1fr auto auto; gap: 8px; min-height: 25px; }
        .position-row strong { color: #d6e7df; font: 11px 'DM Mono', monospace; letter-spacing: .04em; }
        .position-row > span:not(.position-side) { font: 9px 'DM Mono', monospace; }
        .position-value { color: var(--cockpit-dim); }
        .position-side { background: #c4e879; border-radius: 1px; height: 8px; width: 3px; }
        .position-side.short { background: #f0c27b; }
        .coverage-line { align-items: center; color: var(--cockpit-dim); display: flex; font: 9px 'DM Mono', monospace; gap: 6px; margin-top: 13px; }
        .coverage-line svg { color: #c4e879; height: 14px; width: 14px; }
        .coverage-line strong { color: #c4e879; font-weight: 400; margin-left: auto; }
        .coverage-track { background: rgba(185,226,200,.12); height: 3px; margin-left: 5px; width: 34px; }
        .coverage-track i { background: #c4e879; display: block; height: 100%; width: 100%; }
        .detail-metrics { border-top: 1px solid rgba(209,239,226,.13); display: grid; grid-template-columns: repeat(3, 1fr); margin-top: 13px; padding-top: 11px; row-gap: 10px; }
        .metric-cell span { color: var(--cockpit-faint); display: block; font: 8px 'DM Mono', monospace; letter-spacing: .03em; margin-bottom: 4px; text-transform: uppercase; }
        .metric-cell strong { color: #cee3da; display: block; font: 11px 'DM Mono', monospace; font-weight: 400; }
        .bot-history { border-top: 1px solid rgba(209,239,226,.13); margin-top: 13px; padding-top: 10px; }
        .bot-history > div:first-child { display: flex; justify-content: space-between; }
        .cycle-time { color: var(--cockpit-faint); font: 8px 'DM Mono', monospace; }
        .sparkline { height: 35px; margin-top: 5px; overflow: visible; width: 100%; }
        .cockpit-radar { background: linear-gradient(180deg, rgba(14, 45, 50, .82), rgba(8, 27, 34, .76)); border-color: rgba(195,231,216,.18); padding: 18px 17px 16px; }
        .radar-heading { display: flex; justify-content: space-between; }
        .radar-heading h2 { font-size: 18px; font-weight: 500; letter-spacing: -.02em; margin: 6px 0 0; }
        .radar-icon { color: #7ce4df; height: 20px; width: 20px; }
        .radar-icon svg { height: 100%; width: 100%; }
        .radar-visual { background: radial-gradient(circle at 50% 50%, rgba(89,194,180,.17), rgba(9,35,40,.18) 42%, rgba(7,27,33,.44) 72%), repeating-radial-gradient(circle at center, transparent 0, transparent 28px, rgba(175,235,216,.08) 29px, transparent 30px); border: 1px solid rgba(193,232,215,.13); height: 218px; margin: 18px 0 16px; overflow: hidden; position: relative; }
        .radar-ring { border: 1px solid rgba(175,235,216,.16); border-radius: 50%; left: 50%; position: absolute; top: 50%; transform: translate(-50%, -50%); }
        .ring-one { height: 52px; width: 52px; } .ring-two { height: 116px; width: 116px; } .ring-three { height: 181px; width: 181px; }
        .radar-crosshair { background: rgba(184,229,211,.12); position: absolute; }
        .radar-crosshair.horizontal { height: 1px; left: 0; right: 0; top: 50%; } .radar-crosshair.vertical { bottom: 0; left: 50%; top: 0; width: 1px; }
        .radar-scan { background: linear-gradient(135deg, transparent 47%, rgba(116,227,206,.14) 50%, transparent 53%); height: 100%; position: absolute; transform: rotate(-30deg); transform-origin: 50% 50%; width: 100%; }
        .radar-center, .radar-blip { border-radius: 50%; display: block; position: absolute; }
        .radar-center { background: #7ce4df; box-shadow: 0 0 0 4px rgba(124,228,223,.12); height: 5px; left: calc(50% - 2px); top: calc(50% - 2px); width: 5px; }
        .radar-blip { height: 7px; width: 7px; } .blip-a { background: #c4e879; box-shadow: 0 0 0 4px rgba(196,232,121,.11); left: 66%; top: 29%; } .blip-b { background: #f0c27b; box-shadow: 0 0 0 4px rgba(240,194,123,.1); left: 27%; top: 38%; } .blip-c { background: #7ce4df; box-shadow: 0 0 0 4px rgba(124,228,223,.1); left: 72%; top: 69%; }
        .radar-axis { color: rgba(175,235,216,.43); font: 7px 'DM Mono', monospace; position: absolute; letter-spacing: .08em; } .axis-x { bottom: 8px; right: 9px; } .axis-y { left: 8px; top: 9px; transform: rotate(-90deg); transform-origin: 0 0; }
        .radar-readings { display: grid; gap: 12px; }
        .radar-readings > div { display: grid; grid-template-columns: 1fr auto; row-gap: 5px; }
        .radar-readings span { color: var(--cockpit-dim); font: 9px 'DM Mono', monospace; } .radar-readings strong { color: #d4e7de; font: 10px 'DM Mono', monospace; font-weight: 400; }
        .reading-bar { background: rgba(190,226,211,.1); display: block; grid-column: 1 / -1; height: 3px; } .reading-bar b { background: #7ce4df; display: block; height: 100%; } .reading-bar b.green { background: #c4e879; }
        .radar-callout { align-items: flex-start; background: rgba(196,232,121,.06); border: 1px solid rgba(196,232,121,.16); display: flex; gap: 10px; margin-top: 18px; padding: 11px; }
        .callout-dot { background: #c4e879; border-radius: 50%; box-shadow: 0 0 0 4px rgba(196,232,121,.1); flex: 0 0 auto; height: 6px; margin: 6px 0 0 2px; width: 6px; }
        .radar-callout strong { color: #d9ebce; display: block; font: 10px 'DM Mono', monospace; margin-top: 4px; } .radar-callout p { color: var(--cockpit-dim); font: 9px 'DM Mono', monospace; line-height: 1.5; margin: 5px 0 0; }
        .history-tape { border-top: 1px solid rgba(204,239,224,.17); margin-top: 22px; padding-top: 17px; }
        .history-tape .section-heading { margin-bottom: 10px; }
        .tape-table { background: rgba(7, 27, 33, .52); border: 1px solid rgba(203,237,222,.12); display: grid; grid-template-columns: 105px 1fr 1fr 1fr 1.1fr; }
        .tape-row { display: contents; }
        .tape-table > div { border-right: 1px solid rgba(203,237,222,.09); color: var(--cockpit-dim); font: 9px 'DM Mono', monospace; padding: 10px 12px; } .tape-table > div:last-child { border-right: 0; }
        .tape-table .tape-head { color: var(--cockpit-faint); font-size: 8px; letter-spacing: .1em; padding-bottom: 7px; padding-top: 9px; text-transform: uppercase; } .tape-table .tape-cell { color: #cfe3da; } .tape-cell.green { color: #c4e879; } .tape-cell.amber { color: #f0c27b; }
        .cockpit-footer { align-items: center; color: var(--cockpit-faint); display: flex; font: 9px 'DM Mono', monospace; justify-content: space-between; letter-spacing: .08em; margin-top: 18px; text-transform: uppercase; } .cockpit-footer strong { color: #c4e879; font-weight: 400; }
        @media (max-width: 1199px) {
          .cockpit-shell { min-width: 0; padding: 16px; }
          .cockpit-topbar { align-items: flex-start; flex-wrap: wrap; gap: 15px; }
          .topbar-meta { gap: 10px; }
          .topbar-date { display: none; }
          .fleet-hero { display: block; margin-top: 16px; }
          .fleet-card { min-height: 165px; }
          .hero-stat { display: none; }
          .dashboard-grid { display: block; }
          .bot-row { grid-template-columns: 1fr; }
          .bot-card { min-height: 0; }
          .cockpit-radar, .detail-metrics, .history-tape, .cockpit-footer { display: none; }
          .fleet-main { gap: 22px; margin-top: 18px; }
          .fleet-equity { font-size: 37px; }
          .fleet-foot { bottom: 15px; right: 18px; }
        }
      `}</style>

      <div className="cockpit-shell">
        <header className="cockpit-topbar">
          <div className="brand-lockup">
            <div className="brand-mark"><span /></div>
            <div><h1>Fleet Command</h1><p>Portfolio cockpit / live allocation deck</p></div>
          </div>
          <div className="topbar-meta">
            <div className="market-chip"><i /> MARKET OPEN</div>
            <div className="topbar-date">TUE 18 JUN 2024&nbsp;&nbsp; / &nbsp;&nbsp;09:42:21 UTC</div>
          </div>
        </header>

        <section className="fleet-hero" aria-label="Fleet overview">
          <div className="fleet-card concept-glass">
            <div className="eyebrow-line"><span className="concept-label">Fleet altitude / total account value</span><span className="telemetry">REGIME: BULL</span></div>
            <div className="fleet-main">
              <div className="fleet-equity">$296,398<small>Fleet equity</small></div>
              <div className="fleet-pnl"><strong>+$12,840</strong><span>+4.53% all time</span></div>
            </div>
            <div className="fleet-foot"><span>24h change <b className="concept-positive">+$1,142&nbsp; (+0.39%)</b></span><span>active bots <b>03 / 03</b></span></div>
          </div>
          <div className="hero-stat concept-glass">
            <div className="hero-stat-header"><span className="hero-stat-title">Risk envelope</span><Icon name="pulse" /></div>
            <div className="dial-cluster">
              <ExposureDial value={73} tone="cyan" large />
              <div><div className="hero-stat-number">1.08 β</div><p className="hero-stat-note"><b>Stable vector.</b><br />Portfolio beta is holding inside the target band.</p></div>
            </div>
          </div>
        </section>

        <div className="dashboard-grid concept-desktop-grid">
          <main className="bots-section">
            <div className="section-heading"><h2>Bot instruments</h2><span>03 airborne&nbsp;&nbsp; / &nbsp;&nbsp;08 open positions</span></div>
            <div className="bot-row concept-bot-row">{bots.map((bot, index) => <BotCard bot={bot} index={index} key={bot.name} />)}</div>
          </main>
          <RiskRadar />
        </div>

        <section className="history-tape desktop-only-detail">
          <div className="section-heading"><h2>History tape</h2><span>latest fleet decisions · UTC</span></div>
          <div className="tape-table">
            <div className="tape-head">Time</div><div className="tape-head">Agent</div><div className="tape-head">Symbol</div><div className="tape-head">Realized / live</div><div className="tape-head">Decision</div>
            {history.map(([time, agent, symbol, pnl, decision]) => (
              <div className="tape-row" key={`${time}-${agent}`}>
                <div className="tape-cell"><span>{time}</span></div>
                <div className="tape-cell">{agent}</div>
                <div className="tape-cell">{symbol}</div>
                <div className={`tape-cell ${pnl.startsWith("-") ? "amber" : "green"}`}>{pnl}</div>
                <div className="tape-cell">{decision}</div>
              </div>
            ))}
          </div>
        </section>

        <footer className="cockpit-footer desktop-only-detail"><span><strong>ALL PROTECTIVE STOPS COVERED</strong>&nbsp;&nbsp; / &nbsp;&nbsp;data link nominal</span><span>snapshot latency 220ms&nbsp;&nbsp; / &nbsp;&nbsp;next cycle in 00:37</span></footer>
      </div>
    </div>
  );
}