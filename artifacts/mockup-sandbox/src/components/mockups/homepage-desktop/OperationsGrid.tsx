import "./_group.css";

type BotTone = "cyan" | "amber" | "lime";

type Position = {
  symbol: string;
  side: "LONG" | "SHORT";
  size: string;
  pnl: string;
  tone: "positive" | "negative";
};

type Bot = {
  name: string;
  codename: string;
  tone: BotTone;
  status: string;
  statusDetail: string;
  equity: string;
  pnl: string;
  pnlPercent: string;
  sharpe: string;
  drawdown: string;
  winRate: string;
  trades: string;
  win: string;
  loss: string;
  exposure: string;
  cycle: string;
  cycleDetail: string;
  bars: number[];
  positions: Position[];
  activity: { time: string; text: string; detail: string; tone: "positive" | "warning" | "neutral" }[];
};

const bots: Bot[] = [
  {
    name: "Oracle",
    codename: "ORC-01",
    tone: "cyan",
    status: "RUNNING",
    statusDetail: "Trend capture / broad market",
    equity: "$113,150",
    pnl: "+$8,420",
    pnlPercent: "+8.05%",
    sharpe: "1.84",
    drawdown: "-6.2%",
    winRate: "68%",
    trades: "42",
    win: "+$2,140",
    loss: "-$780",
    exposure: "72%",
    cycle: "10:42:18",
    cycleDetail: "scanned 3 symbols",
    bars: [34, 38, 31, 43, 40, 51, 48, 61, 57, 65, 72, 69, 76, 82, 78, 89],
    positions: [
      { symbol: "SPY", side: "LONG", size: "$28,640", pnl: "+$1,284", tone: "positive" },
      { symbol: "QQQ", side: "LONG", size: "$24,180", pnl: "+$1,972", tone: "positive" },
      { symbol: "XLK", side: "LONG", size: "$18,640", pnl: "+$824", tone: "positive" },
    ],
    activity: [
      { time: "10:42", text: "Cycle complete", detail: "3 signals / 0 blocked", tone: "positive" },
      { time: "10:18", text: "QQQ stop lifted", detail: "trail 1.8% · protected", tone: "neutral" },
      { time: "09:57", text: "SPY entered", detail: "confidence 84 / momentum", tone: "positive" },
    ],
  },
  {
    name: "SPY/QQQ",
    codename: "SQT-02",
    tone: "amber",
    status: "RUNNING",
    statusDetail: "Relative value / pairs",
    equity: "$92,094",
    pnl: "-$1,280",
    pnlPercent: "-1.37%",
    sharpe: "0.91",
    drawdown: "-8.7%",
    winRate: "57%",
    trades: "31",
    win: "+$1,080",
    loss: "-$1,460",
    exposure: "64%",
    cycle: "10:41:52",
    cycleDetail: "spread within band",
    bars: [71, 69, 75, 65, 68, 61, 64, 58, 63, 55, 51, 56, 48, 46, 42, 45],
    positions: [
      { symbol: "SPY", side: "LONG", size: "$16,870", pnl: "-$684", tone: "negative" },
      { symbol: "QQQ", side: "SHORT", size: "$15,940", pnl: "-$596", tone: "negative" },
    ],
    activity: [
      { time: "10:41", text: "Spread rebalanced", detail: "z-score +0.42 / neutral", tone: "warning" },
      { time: "10:04", text: "Risk guard active", detail: "drawdown band 2 / 3", tone: "warning" },
      { time: "09:36", text: "Pair held", detail: "correlation 0.87", tone: "neutral" },
    ],
  },
  {
    name: "Jerome",
    codename: "JRM-03",
    tone: "lime",
    status: "RUNNING",
    statusDetail: "Macro rotation / commodities",
    equity: "$91,154",
    pnl: "+$5,700",
    pnlPercent: "+6.68%",
    sharpe: "1.21",
    drawdown: "-4.9%",
    winRate: "63%",
    trades: "27",
    win: "+$1,760",
    loss: "-$920",
    exposure: "81%",
    cycle: "10:39:07",
    cycleDetail: "macro sweep clear",
    bars: [28, 36, 33, 42, 39, 48, 55, 51, 60, 58, 66, 63, 70, 76, 73, 84],
    positions: [
      { symbol: "GLD", side: "LONG", size: "$21,480", pnl: "+$1,120", tone: "positive" },
      { symbol: "SLV", side: "LONG", size: "$14,200", pnl: "+$846", tone: "positive" },
      { symbol: "DBC", side: "LONG", size: "$19,880", pnl: "+$632", tone: "positive" },
      { symbol: "TLT", side: "SHORT", size: "$18,220", pnl: "+$1,406", tone: "positive" },
    ],
    activity: [
      { time: "10:39", text: "Macro sweep clear", detail: "4 positions / stops set", tone: "positive" },
      { time: "10:11", text: "TLT hedge added", detail: "duration delta reduced", tone: "neutral" },
      { time: "09:44", text: "GLD target raised", detail: "signal strength 78", tone: "positive" },
    ],
  },
];

const styles = `
  .operations-grid {
    --og-bg: #071d27;
    --og-panel: rgba(8, 30, 40, .68);
    --og-panel-strong: rgba(8, 27, 37, .88);
    --og-line: rgba(179, 237, 231, .15);
    --og-soft-line: rgba(179, 237, 231, .09);
    --og-text: #e6f3f1;
    --og-muted: #8ea9ab;
    --og-faint: #5c7b80;
    --og-cyan: #72eee4;
    --og-amber: #ffd27a;
    --og-lime: #b8f46b;
    --og-red: #ff9292;
    position: relative;
    min-height: 100dvh;
    overflow: hidden;
    color: var(--og-text);
    background:
      radial-gradient(ellipse at 18% -7%, rgba(121, 210, 218, .32), transparent 35%),
      radial-gradient(ellipse at 82% 17%, rgba(77, 148, 159, .26), transparent 33%),
      linear-gradient(150deg, #92bfc4 0%, #3d6876 24%, #102f3d 57%, #071a26 100%);
  }
  .operations-grid::before {
    content: "";
    position: absolute;
    inset: 0;
    pointer-events: none;
    opacity: .24;
    background:
      linear-gradient(116deg, rgba(255,255,255,.13), transparent 22%, transparent 62%, rgba(5, 21, 31, .24)),
      radial-gradient(ellipse at 20% 88%, rgba(15, 83, 80, .68) 0 11%, transparent 29%),
      radial-gradient(ellipse at 72% 91%, rgba(20, 80, 74, .55) 0 13%, transparent 32%);
    filter: blur(1px);
  }
  .operations-grid::after {
    content: "";
    position: fixed;
    z-index: 4;
    inset: 0;
    pointer-events: none;
    opacity: .055;
    background-image: repeating-linear-gradient(0deg, rgba(255,255,255,.8) 0, rgba(255,255,255,.8) 1px, transparent 1px, transparent 4px);
    mix-blend-mode: overlay;
  }
  .operations-grid, .operations-grid * { box-sizing: border-box; }
  .og-shell { position: relative; z-index: 1; width: min(1740px, 100%); margin: 0 auto; padding: 20px 24px 18px; }
  .og-header { display: flex; align-items: center; justify-content: space-between; gap: 24px; min-height: 54px; }
  .og-brand { display: flex; align-items: center; gap: 14px; }
  .og-mark { display: grid; width: 34px; height: 34px; place-items: center; border: 1px solid rgba(114,238,228,.44); border-radius: 9px; background: rgba(7, 35, 43, .6); color: var(--og-cyan); box-shadow: inset 0 1px rgba(255,255,255,.15); }
  .og-brand-name { font: 700 17px/1 'Space Grotesk', sans-serif; letter-spacing: -.04em; }
  .og-brand-sub { margin-top: 5px; color: var(--og-muted); font: 500 9px/1 'DM Mono', monospace; letter-spacing: .18em; text-transform: uppercase; }
  .og-header-meta { display: flex; align-items: center; gap: 23px; }
  .og-meta-block { padding-left: 21px; border-left: 1px solid var(--og-line); }
  .og-meta-label { display: block; color: var(--og-muted); font: 500 9px/1 'DM Mono', monospace; letter-spacing: .14em; text-transform: uppercase; }
  .og-meta-value { display: block; margin-top: 6px; font: 500 14px/1 'DM Mono', monospace; letter-spacing: -.03em; }
  .og-command { display: flex; align-items: center; gap: 9px; color: var(--og-muted); font: 500 10px 'DM Mono', monospace; }
  .og-live-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--og-lime); box-shadow: 0 0 0 4px rgba(184,244,107,.12); }
  .og-safety { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-top: 15px; min-height: 34px; padding: 0 12px; border-top: 1px solid rgba(197, 246, 239, .17); border-bottom: 1px solid rgba(197, 246, 239, .12); background: rgba(5, 25, 34, .32); color: var(--og-muted); font: 500 9px 'DM Mono', monospace; letter-spacing: .08em; text-transform: uppercase; }
  .og-safety-items { display: flex; align-items: center; gap: 21px; }
  .og-safety-item { display: inline-flex; align-items: center; gap: 7px; white-space: nowrap; }
  .og-safety-item strong { color: var(--og-text); font-weight: 500; }
  .og-check { color: var(--og-lime); font-size: 13px; }
  .og-regime { color: var(--og-lime); }
  .og-layout { display: grid; grid-template-columns: 50px minmax(0, 1fr); align-items: start; gap: 17px; margin-top: 18px; }
  .og-rail { display: flex; flex-direction: column; align-items: center; min-height: 730px; padding: 12px 0; border: 1px solid var(--og-line); border-radius: 12px; background: rgba(6, 25, 34, .46); box-shadow: inset 0 1px rgba(255,255,255,.1); }
  .og-rail-top { color: var(--og-cyan); }
  .og-rail-rule { width: 20px; height: 1px; margin: 16px 0; background: var(--og-line); }
  .og-rail-label { writing-mode: vertical-rl; transform: rotate(180deg); color: var(--og-faint); font: 500 9px 'DM Mono', monospace; letter-spacing: .19em; text-transform: uppercase; }
  .og-rail-index { display: flex; flex-direction: column; gap: 13px; margin-top: auto; color: var(--og-muted); font: 500 9px 'DM Mono', monospace; }
  .og-rail-index span:first-child { color: var(--og-cyan); }
  .og-main { min-width: 0; }
  .og-overview { display: grid; grid-template-columns: 1.25fr .78fr .78fr .72fr 1.25fr; gap: 1px; overflow: hidden; border: 1px solid var(--og-line); border-radius: 12px; background: var(--og-soft-line); box-shadow: 0 18px 45px rgba(2, 18, 26, .2), inset 0 1px rgba(255,255,255,.11); }
  .og-overview-cell { min-height: 76px; padding: 13px 17px; background: rgba(8, 34, 44, .72); }
  .og-overview-cell:first-child { background: rgba(8, 35, 45, .86); }
  .og-overline { display: block; color: var(--og-muted); font: 500 9px 'DM Mono', monospace; letter-spacing: .15em; text-transform: uppercase; }
  .og-overview-number { display: block; margin-top: 8px; color: var(--og-text); font: 500 21px/1 'DM Mono', monospace; letter-spacing: -.07em; }
  .og-overview-number.small { font-size: 17px; }
  .og-overview-number.positive { color: var(--og-lime); }
  .og-overview-number.warning { color: var(--og-amber); }
  .og-overview-sub { margin-top: 5px; color: var(--og-faint); font: 500 9px 'DM Mono', monospace; }
  .og-overview-wide { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
  .og-coverage { width: 98px; }
  .og-coverage-track { height: 4px; margin-top: 10px; overflow: hidden; border-radius: 3px; background: rgba(178, 222, 215, .14); }
  .og-coverage-fill { width: 100%; height: 100%; background: var(--og-lime); }
  .og-bot-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 13px; margin-top: 16px; }
  .og-card { min-width: 0; overflow: hidden; border: 1px solid var(--og-line); border-radius: 12px; background: var(--og-panel); box-shadow: 0 18px 48px rgba(2, 15, 24, .25), inset 0 1px rgba(255,255,255,.12); backdrop-filter: blur(17px) saturate(130%); }
  .og-card[data-tone="cyan"] { --bot-accent: var(--og-cyan); --bot-tint: rgba(114, 238, 228, .13); }
  .og-card[data-tone="amber"] { --bot-accent: var(--og-amber); --bot-tint: rgba(255, 210, 122, .13); }
  .og-card[data-tone="lime"] { --bot-accent: var(--og-lime); --bot-tint: rgba(184, 244, 107, .13); }
  .og-card-head { position: relative; padding: 15px 16px 13px; border-bottom: 1px solid var(--og-soft-line); background: linear-gradient(100deg, var(--bot-tint), transparent 57%); }
  .og-card-head::after { position: absolute; right: 0; bottom: -1px; left: 0; height: 2px; content: ""; background: var(--bot-accent); opacity: .78; }
  .og-card-title-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
  .og-bot-ident { display: flex; align-items: center; gap: 10px; }
  .og-bot-pip { width: 8px; height: 8px; flex: none; border-radius: 50%; background: var(--bot-accent); box-shadow: 0 0 0 4px var(--bot-tint); }
  .og-bot-name { font: 600 17px/1 'Space Grotesk', sans-serif; letter-spacing: -.04em; }
  .og-bot-code { margin-top: 4px; color: var(--og-muted); font: 500 9px 'DM Mono', monospace; letter-spacing: .12em; }
  .og-status { display: flex; align-items: center; gap: 6px; padding: 5px 7px; border: 1px solid color-mix(in srgb, var(--bot-accent) 32%, transparent); border-radius: 4px; color: var(--bot-accent); font: 500 9px 'DM Mono', monospace; letter-spacing: .1em; }
  .og-status-dot { width: 5px; height: 5px; border-radius: 50%; background: currentColor; }
  .og-card-descriptor { margin: 12px 0 0 18px; color: var(--og-muted); font: 500 10px 'DM Mono', monospace; }
  .og-summary { display: grid; grid-template-columns: 1.1fr .9fr; gap: 12px; padding: 14px 16px; border-bottom: 1px solid var(--og-soft-line); }
  .og-equity-label { color: var(--og-muted); font: 500 9px 'DM Mono', monospace; letter-spacing: .14em; text-transform: uppercase; }
  .og-equity { margin-top: 5px; font: 500 26px/1 'DM Mono', monospace; letter-spacing: -.09em; }
  .og-pnl-label { color: var(--og-muted); font: 500 9px 'DM Mono', monospace; letter-spacing: .12em; text-transform: uppercase; }
  .og-pnl { margin-top: 5px; font: 500 16px/1 'DM Mono', monospace; letter-spacing: -.06em; }
  .og-percent { margin-left: 5px; color: var(--og-muted); font-size: 10px; letter-spacing: -.03em; }
  .og-chart { display: flex; align-items: end; gap: 3px; height: 45px; margin-top: 14px; padding: 0 16px 12px; border-bottom: 1px solid var(--og-soft-line); }
  .og-bar { min-width: 3px; flex: 1; border-radius: 2px 2px 0 0; background: linear-gradient(180deg, var(--bot-accent), color-mix(in srgb, var(--bot-accent) 35%, transparent)); opacity: .79; transform-origin: bottom; }
  .og-chart-label { margin-left: auto; color: var(--og-faint); font: 500 8px 'DM Mono', monospace; }
  .og-section { padding: 13px 16px; border-bottom: 1px solid var(--og-soft-line); }
  .og-section-heading { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; color: var(--og-muted); font: 500 9px 'DM Mono', monospace; letter-spacing: .14em; text-transform: uppercase; }
  .og-section-heading span:last-child { color: var(--og-faint); letter-spacing: .05em; }
  .og-position-table { width: 100%; border-collapse: collapse; font: 500 10px 'DM Mono', monospace; }
  .og-position-table th { padding-bottom: 6px; color: var(--og-faint); font-size: 8px; font-weight: 500; letter-spacing: .1em; text-align: left; text-transform: uppercase; }
  .og-position-table th:not(:first-child), .og-position-table td:not(:first-child) { text-align: right; }
  .og-position-table td { padding: 5px 0; border-top: 1px solid rgba(179, 237, 231, .07); color: var(--og-text); }
  .og-position-table tr:first-child td { border-top: 0; }
  .og-side { margin-left: 5px; color: var(--og-faint); font-size: 8px; }
  .og-positive { color: var(--og-lime) !important; }
  .og-negative { color: var(--og-red) !important; }
  .og-kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; overflow: hidden; border: 1px solid var(--og-soft-line); border-radius: 5px; background: var(--og-soft-line); }
  .og-kpi { min-width: 0; padding: 9px 8px 8px; background: rgba(13, 42, 49, .46); }
  .og-kpi-label { display: block; overflow: hidden; color: var(--og-faint); font: 500 8px 'DM Mono', monospace; letter-spacing: .06em; text-overflow: ellipsis; text-transform: uppercase; white-space: nowrap; }
  .og-kpi-value { display: block; margin-top: 5px; color: var(--og-text); font: 500 14px/1 'DM Mono', monospace; letter-spacing: -.06em; }
  .og-extremes { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; }
  .og-extreme { padding: 9px 10px; border-left: 2px solid var(--og-lime); background: rgba(184, 244, 107, .065); }
  .og-extreme.loss { border-left-color: var(--og-red); background: rgba(255, 146, 146, .06); }
  .og-extreme-label { display: block; color: var(--og-muted); font: 500 8px 'DM Mono', monospace; letter-spacing: .1em; text-transform: uppercase; }
  .og-extreme-value { display: block; margin-top: 5px; font: 500 14px/1 'DM Mono', monospace; letter-spacing: -.06em; }
  .og-activity { padding: 13px 16px 15px; }
  .og-activity-list { display: grid; gap: 10px; }
  .og-activity-item { display: grid; grid-template-columns: 38px 8px minmax(0, 1fr); gap: 7px; align-items: start; }
  .og-activity-time { padding-top: 1px; color: var(--og-faint); font: 500 9px 'DM Mono', monospace; }
  .og-activity-line { position: relative; display: flex; justify-content: center; min-height: 28px; }
  .og-activity-line::after { position: absolute; top: 8px; bottom: -14px; width: 1px; content: ""; background: var(--og-soft-line); }
  .og-activity-item:last-child .og-activity-line::after { display: none; }
  .og-activity-dot { z-index: 1; width: 6px; height: 6px; margin-top: 3px; border: 1px solid var(--og-muted); border-radius: 50%; background: var(--og-bg); }
  .og-activity-dot.positive { border-color: var(--og-lime); background: var(--og-lime); }
  .og-activity-dot.warning { border-color: var(--og-amber); background: var(--og-amber); }
  .og-activity-text { min-width: 0; color: var(--og-text); font: 500 10px/1.1 'DM Mono', monospace; }
  .og-activity-detail { display: block; overflow: hidden; margin-top: 3px; color: var(--og-faint); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
  .og-footer { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-top: 13px; color: var(--og-faint); font: 500 9px 'DM Mono', monospace; letter-spacing: .08em; text-transform: uppercase; }
  .og-footer-state { display: inline-flex; align-items: center; gap: 7px; }
  .og-footer-state::before { width: 6px; height: 6px; content: ""; border-radius: 50%; background: var(--og-lime); }
  .og-footer-right { color: var(--og-muted); }
  @media (max-width: 1199px) {
    .operations-grid { overflow: auto; }
    .og-shell { padding: 16px; }
    .og-header { align-items: flex-start; flex-wrap: wrap; }
    .og-header-meta { width: 100%; justify-content: flex-start; overflow: auto; }
    .og-meta-block { padding-left: 0; border-left: 0; }
    .og-command { margin-left: auto; }
    .og-safety { align-items: flex-start; flex-direction: column; padding: 10px 12px; }
    .og-safety-items { flex-wrap: wrap; gap: 8px 17px; }
    .og-layout { display: block; margin-top: 14px; }
    .og-rail { display: none; }
    .og-overview { grid-template-columns: repeat(2, 1fr); }
    .og-overview-cell { min-height: 68px; }
    .og-overview-cell:last-child { grid-column: 1 / -1; }
    .og-bot-row { grid-template-columns: 1fr; }
    .desktop-only-detail { display: none !important; }
  }
`;

function MarkIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" width="17" height="17" fill="none">
      <path d="M4 15.5 8.2 11l3.1 2.6L19.5 6M4 19.5h16" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M19.5 6v4M19.5 6h-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

function BotPanel({ bot }: { bot: Bot }) {
  return (
    <article className="og-card" data-tone={bot.tone}>
      <header className="og-card-head">
        <div className="og-card-title-row">
          <div className="og-bot-ident">
            <span className="og-bot-pip" />
            <div>
              <div className="og-bot-name">{bot.name}</div>
              <div className="og-bot-code">{bot.codename} / ALLOCATION {bot.exposure}</div>
            </div>
          </div>
          <div className="og-status"><span className="og-status-dot" />{bot.status}</div>
        </div>
        <div className="og-card-descriptor">{bot.statusDetail}</div>
      </header>

      <section className="og-summary">
        <div>
          <div className="og-equity-label">Bot equity</div>
          <div className="og-equity">{bot.equity}</div>
        </div>
        <div>
          <div className="og-pnl-label">Session P&amp;L</div>
          <div className={`og-pnl ${bot.pnl.startsWith("+") ? "og-positive" : "og-negative"}`}>
            {bot.pnl}<span className="og-percent">{bot.pnlPercent}</span>
          </div>
        </div>
      </section>

      <div className="og-chart desktop-only-detail" aria-label={`${bot.name} equity trend`}>
        {bot.bars.map((bar, index) => <span className="og-bar" style={{ height: `${bar}%` }} key={`${bot.codename}-${index}`} />)}
        <span className="og-chart-label">16 CYCLES</span>
      </div>

      <section className="og-section desktop-only-detail">
        <div className="og-section-heading"><span>Open positions</span><span>{bot.positions.length.toString().padStart(2, "0")} LIVE</span></div>
        <table className="og-position-table">
          <thead><tr><th>Symbol</th><th>Notional</th><th>Unreal. P&amp;L</th></tr></thead>
          <tbody>
            {bot.positions.map((position) => (
              <tr key={`${bot.codename}-${position.symbol}`}>
                <td>{position.symbol}<span className="og-side">{position.side}</span></td>
                <td>{position.size}</td>
                <td className={position.tone === "positive" ? "og-positive" : "og-negative"}>{position.pnl}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="og-section desktop-only-detail">
        <div className="og-section-heading"><span>Performance matrix</span><span>30D WINDOW</span></div>
        <div className="og-kpi-grid">
          <div className="og-kpi"><span className="og-kpi-label">Sharpe</span><span className="og-kpi-value">{bot.sharpe}</span></div>
          <div className="og-kpi"><span className="og-kpi-label">Max DD</span><span className="og-kpi-value og-negative">{bot.drawdown}</span></div>
          <div className="og-kpi"><span className="og-kpi-label">Win rate</span><span className="og-kpi-value og-positive">{bot.winRate}</span></div>
          <div className="og-kpi"><span className="og-kpi-label">Trades</span><span className="og-kpi-value">{bot.trades}</span></div>
        </div>
        <div className="og-extremes" style={{ marginTop: "9px" }}>
          <div className="og-extreme"><span className="og-extreme-label">Biggest win</span><span className="og-extreme-value og-positive">{bot.win}</span></div>
          <div className="og-extreme loss"><span className="og-extreme-label">Biggest loss</span><span className="og-extreme-value og-negative">{bot.loss}</span></div>
        </div>
      </section>

      <section className="og-activity desktop-only-detail">
        <div className="og-section-heading"><span>Activity rail</span><span>LAST CYCLE {bot.cycle}</span></div>
        <div className="og-activity-list">
          {bot.activity.map((event) => (
            <div className="og-activity-item" key={`${bot.codename}-${event.time}`}>
              <span className="og-activity-time">{event.time}</span>
              <span className="og-activity-line"><span className={`og-activity-dot ${event.tone}`} /></span>
              <span className="og-activity-text">{event.text}<span className="og-activity-detail">{event.detail}</span></span>
            </div>
          ))}
        </div>
      </section>
    </article>
  );
}

export function OperationsGrid() {
  return (
    <main className="homepage-concept operations-grid">
      <style>{styles}</style>
      <div className="og-shell">
        <header className="og-header concept-header">
          <div className="og-brand">
            <div className="og-mark"><MarkIcon /></div>
            <div>
              <div className="og-brand-name">Fleet Command</div>
              <div className="og-brand-sub">Operations grid / live telemetry</div>
            </div>
          </div>
          <div className="og-header-meta">
            <div className="og-meta-block"><span className="og-meta-label">Fleet equity</span><span className="og-meta-value">$296,398</span></div>
            <div className="og-meta-block"><span className="og-meta-label">Total P&amp;L</span><span className="og-meta-value concept-positive">+$12,840 <small>(+4.53%)</small></span></div>
            <div className="og-meta-block"><span className="og-meta-label">24h move</span><span className="og-meta-value concept-positive">+$1,142 <small>(+0.39%)</small></span></div>
          </div>
          <div className="og-command"><span className="og-live-dot" />SYNCED 10:42:21 UTC</div>
        </header>

        <div className="og-safety">
          <div className="og-safety-items">
            <span className="og-safety-item"><span className="og-check">✓</span>Protective stops <strong>covered</strong></span>
            <span className="og-safety-item"><span className="og-check">✓</span>Open positions <strong>08</strong></span>
            <span className="og-safety-item">Market <strong className="og-regime">OPEN</strong></span>
            <span className="og-safety-item">Regime <strong className="og-regime">BULL</strong></span>
          </div>
          <span>Risk envelope / nominal</span>
        </div>

        <div className="og-layout">
          <aside className="og-rail" aria-label="Fleet navigation">
            <span className="og-rail-top"><MarkIcon /></span>
            <span className="og-rail-rule" />
            <span className="og-rail-label">Fleet overview</span>
            <div className="og-rail-index"><span>01</span><span>02</span><span>03</span></div>
          </aside>

          <section className="og-main">
            <div className="og-overview concept-desktop-grid">
              <div className="og-overview-cell">
                <span className="og-overline">Command posture</span>
                <span className="og-overview-number small">3 / 3 <span className="og-overview-sub">bots live</span></span>
              </div>
              <div className="og-overview-cell"><span className="og-overline">Open positions</span><span className="og-overview-number">08</span><span className="og-overview-sub">across fleet</span></div>
              <div className="og-overview-cell"><span className="og-overline">Gross exposure</span><span className="og-overview-number">72.4%</span><span className="og-overview-sub">of equity</span></div>
              <div className="og-overview-cell"><span className="og-overline">Last cycle</span><span className="og-overview-number small">10:42</span><span className="og-overview-sub">18 sec ago</span></div>
              <div className="og-overview-cell og-overview-wide">
                <div><span className="og-overline">Protection coverage</span><span className="og-overview-number small og-overview-number positive">100%</span></div>
                <div className="og-coverage"><span className="og-overline">08 / 08 stops</span><div className="og-coverage-track"><div className="og-coverage-fill" /></div></div>
              </div>
            </div>

            <div className="og-bot-row concept-bot-row">
              {bots.map((bot) => <BotPanel bot={bot} key={bot.codename} />)}
            </div>

            <footer className="og-footer">
              <span className="og-footer-state">All systems nominal</span>
              <span className="og-footer-right">Data stream stable · risk checks 08 / 08 · next fleet scan 00:42</span>
            </footer>
          </section>
        </div>
      </div>
    </main>
  );
}

export default OperationsGrid;