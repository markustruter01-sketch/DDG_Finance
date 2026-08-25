import type { CSSProperties } from "react";
import {
  Activity,
  BarChart3,
  CalendarClock,
  CheckCircle2,
  Crosshair,
  Gauge,
  ShieldCheck,
  TrendingUp,
  Waves,
} from "lucide-react";
import "./_group.css";

type Trade = {
  time: string;
  symbol: string;
  side: "LONG" | "SHORT";
  result: string;
  tone: "positive" | "negative";
};

type Bot = {
  name: string;
  code: string;
  eyebrow: string;
  equity: string;
  pnl: string;
  pnlPercent: string;
  sharpe: string;
  drawdown: string;
  winRate: string;
  trades: string;
  win: string;
  loss: string;
  exposure: number;
  positions: string[];
  attribution: string[];
  cycle: string;
  accent: string;
  accentSoft: string;
  spark: string;
  sparkArea: string;
  tradesHistory: Trade[];
};

const bots: Bot[] = [
  {
    name: "Oracle",
    code: "ORC / 01",
    eyebrow: "MOMENTUM · EQUITIES",
    equity: "$113,150",
    pnl: "+$8,420",
    pnlPercent: "+8.04%",
    sharpe: "1.84",
    drawdown: "-6.2%",
    winRate: "68%",
    trades: "42",
    win: "+$2,140",
    loss: "-$780",
    exposure: 72,
    positions: ["SPY", "QQQ", "XLK"],
    attribution: ["breakout +3.2%", "sector tilt +1.8%", "carry +0.9%"],
    cycle: "08:42:16 UTC",
    accent: "#8cf1d5",
    accentSoft: "rgba(140, 241, 213, .13)",
    spark: "M2 67 C18 64, 23 51, 38 55 S57 39, 72 44 S90 30, 102 34 S120 20, 137 26 S158 16, 173 20 S193 8, 208 12 S226 3, 240 6",
    sparkArea: "M2 67 C18 64, 23 51, 38 55 S57 39, 72 44 S90 30, 102 34 S120 20, 137 26 S158 16, 173 20 S193 8, 208 12 S226 3, 240 6 L240 76 L2 76 Z",
    tradesHistory: [
      { time: "09:38", symbol: "XLK", side: "LONG", result: "+$412", tone: "positive" },
      { time: "08:56", symbol: "QQQ", side: "LONG", result: "+$286", tone: "positive" },
      { time: "YDAY 15:41", symbol: "SPY", side: "SHORT", result: "-$164", tone: "negative" },
    ],
  },
  {
    name: "SPY/QQQ Trend",
    code: "SQT / 02",
    eyebrow: "ROTATION · INDEX ETFs",
    equity: "$92,094",
    pnl: "-$1,280",
    pnlPercent: "-1.37%",
    sharpe: "0.91",
    drawdown: "-8.7%",
    winRate: "57%",
    trades: "31",
    win: "+$1,080",
    loss: "-$1,460",
    exposure: 64,
    positions: ["SPY", "QQQ"],
    attribution: ["QQQ drag -1.6%", "trend flip +0.7%", "cash +0.2%"],
    cycle: "08:40:02 UTC",
    accent: "#f2be78",
    accentSoft: "rgba(242, 190, 120, .14)",
    spark: "M2 23 C18 19, 24 28, 39 25 S57 35, 74 30 S88 47, 104 42 S121 36, 137 49 S151 42, 170 56 S190 45, 207 59 S226 53, 240 67",
    sparkArea: "M2 23 C18 19, 24 28, 39 25 S57 35, 74 30 S88 47, 104 42 S121 36, 137 49 S151 42, 170 56 S190 45, 207 59 S226 53, 240 67 L240 76 L2 76 Z",
    tradesHistory: [
      { time: "09:31", symbol: "SPY", side: "SHORT", result: "-$318", tone: "negative" },
      { time: "08:45", symbol: "QQQ", side: "LONG", result: "+$204", tone: "positive" },
      { time: "YDAY 14:16", symbol: "QQQ", side: "LONG", result: "-$512", tone: "negative" },
    ],
  },
  {
    name: "Jerome",
    code: "JRM / 03",
    eyebrow: "MACRO · COMMODITIES",
    equity: "$91,154",
    pnl: "+$5,700",
    pnlPercent: "+6.67%",
    sharpe: "1.21",
    drawdown: "-4.9%",
    winRate: "63%",
    trades: "27",
    win: "+$1,760",
    loss: "-$920",
    exposure: 81,
    positions: ["GLD", "SLV", "DBC", "TLT"],
    attribution: ["metals +2.5%", "duration +1.2%", "energy +0.8%"],
    cycle: "08:37:49 UTC",
    accent: "#b6a6ff",
    accentSoft: "rgba(182, 166, 255, .14)",
    spark: "M2 62 C19 57, 27 62, 41 48 S56 52, 71 38 S90 45, 103 34 S121 26, 139 31 S158 23, 174 29 S193 10, 208 18 S226 10, 240 13",
    sparkArea: "M2 62 C19 57, 27 62, 41 48 S56 52, 71 38 S90 45, 103 34 S121 26, 139 31 S158 23, 174 29 S193 10, 208 18 S226 10, 240 13 L240 76 L2 76 Z",
    tradesHistory: [
      { time: "09:12", symbol: "GLD", side: "LONG", result: "+$672", tone: "positive" },
      { time: "08:22", symbol: "TLT", side: "LONG", result: "+$188", tone: "positive" },
      { time: "YDAY 12:04", symbol: "DBC", side: "SHORT", result: "-$236", tone: "negative" },
    ],
  },
];

const styles = `
  .observatory {
    --obs-ink: #effaf5;
    --obs-muted: #98b5b1;
    --obs-dim: #6f8b8a;
    --obs-line: rgba(184, 239, 225, .13);
    --obs-panel: rgba(7, 29, 38, .68);
    --obs-panel-deep: rgba(5, 22, 31, .82);
    min-height: 100dvh;
    position: relative;
    padding: 22px 28px 34px;
    overflow: hidden;
    color: var(--obs-ink);
    background:
      radial-gradient(ellipse at 8% 0%, rgba(160, 220, 214, .25), transparent 32%),
      radial-gradient(ellipse at 94% 22%, rgba(68, 139, 145, .30), transparent 34%),
      linear-gradient(145deg, rgba(12, 43, 52, .76), rgba(5, 23, 32, .36) 50%, rgba(14, 40, 46, .70));
  }
  .observatory::before {
    content: "";
    position: fixed;
    inset: 0;
    pointer-events: none;
    opacity: .22;
    background:
      linear-gradient(100deg, transparent 0 19%, rgba(190, 237, 223, .08) 19.1%, transparent 19.4% 100%),
      linear-gradient(168deg, transparent 0 58%, rgba(135, 214, 205, .11) 58.1%, transparent 58.3% 100%);
    mix-blend-mode: screen;
  }
  .observatory::after {
    content: "";
    position: fixed;
    inset: 0;
    z-index: 5;
    pointer-events: none;
    opacity: .06;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 140 140' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.84' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.75'/%3E%3C/svg%3E");
  }
  .observatory *, .observatory *::before, .observatory *::after { box-sizing: border-box; }
  .obs-shell { position: relative; z-index: 1; max-width: 1740px; margin: 0 auto; }
  .obs-topline { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 28px; color: var(--obs-muted); font: 500 10px 'DM Mono', monospace; letter-spacing: .11em; text-transform: uppercase; }
  .obs-brand { display: flex; align-items: center; gap: 11px; color: var(--obs-ink); font: 600 12px 'Space Grotesk', sans-serif; letter-spacing: .13em; }
  .obs-mark { width: 25px; height: 25px; display: grid; place-items: center; color: #071b24; background: #8cf1d5; border-radius: 8px 8px 8px 2px; box-shadow: 0 0 0 4px rgba(140,241,213,.08); }
  .obs-session { display: flex; align-items: center; gap: 10px; }
  .obs-session span { display: inline-flex; align-items: center; gap: 7px; }
  .obs-dot { width: 6px; height: 6px; display: inline-block; border-radius: 99px; background: #b7ef75; box-shadow: 0 0 0 4px rgba(183,239,117,.10); }
  .obs-dot.amber { background: #f2be78; box-shadow: 0 0 0 4px rgba(242,190,120,.10); }
  .obs-hero { display: flex; justify-content: space-between; align-items: end; gap: 28px; margin-bottom: 23px; }
  .obs-kicker { margin: 0 0 9px; color: #8cf1d5; font: 500 10px 'DM Mono', monospace; letter-spacing: .21em; text-transform: uppercase; }
  .obs-title { max-width: 710px; margin: 0; font: 600 clamp(31px, 3.1vw, 49px)/.98 'Space Grotesk', sans-serif; letter-spacing: -.055em; }
  .obs-title em { color: #8cf1d5; font-style: normal; }
  .obs-subtitle { max-width: 545px; margin: 13px 0 0; color: var(--obs-muted); font: 400 13px/1.45 'Space Grotesk', sans-serif; }
  .obs-asof { min-width: 210px; padding: 14px 16px; border-left: 1px solid rgba(140,241,213,.42); color: var(--obs-muted); font: 10px/1.7 'DM Mono', monospace; letter-spacing: .06em; text-transform: uppercase; }
  .obs-asof strong { display: block; color: var(--obs-ink); font-size: 15px; font-weight: 500; letter-spacing: -.04em; }
  .obs-summary { display: grid; grid-template-columns: 1.7fr 1fr 1fr 1fr 1.5fr; gap: 1px; margin-bottom: 32px; overflow: hidden; border: 1px solid var(--obs-line); border-radius: 14px; background: var(--obs-line); box-shadow: 0 20px 55px rgba(1, 13, 19, .20); }
  .obs-summary-cell { min-height: 88px; padding: 17px 19px; background: rgba(7, 31, 39, .70); }
  .obs-summary-cell:first-child { background: rgba(12, 49, 54, .72); }
  .obs-summary-cell:last-child { display: flex; align-items: center; justify-content: space-between; gap: 13px; }
  .obs-label { color: var(--obs-dim); font: 500 9px 'DM Mono', monospace; letter-spacing: .17em; text-transform: uppercase; }
  .obs-value { margin-top: 6px; color: var(--obs-ink); font: 500 25px 'DM Mono', monospace; letter-spacing: -.065em; }
  .obs-value.large { font-size: 32px; }
  .obs-value.positive { color: #b7ef75; }
  .obs-value.negative { color: #ff9a91; }
  .obs-under { display: flex; gap: 8px; align-items: baseline; margin-top: 3px; color: var(--obs-muted); font: 10px 'DM Mono', monospace; }
  .obs-under strong { color: #b7ef75; font-weight: 500; }
  .obs-regime { display: flex; align-items: center; gap: 12px; }
  .obs-regime-icon { color: #b7ef75; }
  .obs-regime strong { display: block; margin-top: 5px; color: #b7ef75; font: 500 17px 'DM Mono', monospace; }
  .obs-stops { color: #b7ef75; font: 500 10px 'DM Mono', monospace; line-height: 1.4; }
  .obs-section-head { display: flex; align-items: end; justify-content: space-between; gap: 18px; margin-bottom: 14px; }
  .obs-section-title { margin: 0; color: var(--obs-ink); font: 500 16px 'Space Grotesk', sans-serif; letter-spacing: -.025em; }
  .obs-section-meta { color: var(--obs-dim); font: 10px 'DM Mono', monospace; letter-spacing: .08em; text-transform: uppercase; }
  .obs-section-title .tiny-mark { display: inline-block; width: 6px; height: 6px; margin: 0 9px 2px 0; border-radius: 2px; background: #8cf1d5; }
  .obs-bot-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
  .obs-bot-card { position: relative; min-width: 0; overflow: hidden; border: 1px solid var(--obs-line); border-radius: 15px; background: linear-gradient(145deg, var(--obs-panel), rgba(6, 24, 33, .78)); box-shadow: 0 18px 45px rgba(1, 14, 20, .19), inset 0 1px rgba(231,255,248,.08); }
  .obs-bot-card::before { content: ""; position: absolute; inset: 0 0 auto; height: 2px; background: linear-gradient(90deg, var(--accent), transparent 72%); opacity: .85; }
  .obs-card-inner { padding: 18px 18px 16px; }
  .obs-card-head { display: flex; align-items: start; justify-content: space-between; gap: 12px; }
  .obs-bot-name { margin: 3px 0 3px; color: var(--obs-ink); font: 600 20px 'Space Grotesk', sans-serif; letter-spacing: -.045em; }
  .obs-bot-eyebrow { color: var(--accent); font: 500 9px 'DM Mono', monospace; letter-spacing: .15em; }
  .obs-bot-code { color: var(--obs-dim); font: 9px 'DM Mono', monospace; letter-spacing: .08em; }
  .obs-equity-line { display: flex; align-items: end; justify-content: space-between; gap: 10px; margin-top: 18px; }
  .obs-equity { color: var(--obs-ink); font: 500 27px 'DM Mono', monospace; letter-spacing: -.07em; }
  .obs-return { padding-bottom: 4px; text-align: right; font: 500 12px 'DM Mono', monospace; }
  .obs-return.positive { color: #b7ef75; }
  .obs-return.negative { color: #ff9a91; }
  .obs-return span { display: block; margin-top: 3px; color: var(--obs-dim); font-size: 9px; font-weight: 400; }
  .obs-chart { height: 93px; margin-top: 12px; padding: 10px 0 4px; border-top: 1px solid var(--obs-line); border-bottom: 1px solid var(--obs-line); }
  .obs-chart svg { width: 100%; height: 100%; overflow: visible; }
  .obs-chart-grid { stroke: rgba(198,239,226,.09); stroke-width: 1; stroke-dasharray: 2 5; }
  .obs-chart-area { fill: var(--accent-soft); }
  .obs-chart-line { fill: none; stroke: var(--accent); stroke-width: 2; stroke-linecap: round; vector-effect: non-scaling-stroke; }
  .obs-chart-end { fill: var(--accent); stroke: #0a2731; stroke-width: 2; }
  .obs-chart-caption { display: flex; justify-content: space-between; margin-top: -1px; color: var(--obs-dim); font: 9px 'DM Mono', monospace; text-transform: uppercase; }
  .obs-metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 16px; }
  .obs-metric { padding-right: 7px; border-right: 1px solid var(--obs-line); }
  .obs-metric:last-child { border-right: 0; }
  .obs-metric-label { display: block; color: var(--obs-dim); font: 9px 'DM Mono', monospace; letter-spacing: .07em; text-transform: uppercase; }
  .obs-metric-value { display: block; margin-top: 5px; color: var(--obs-ink); font: 500 14px 'DM Mono', monospace; letter-spacing: -.04em; }
  .obs-metric-value.good { color: #b7ef75; }
  .obs-metric-value.risk { color: #ffbd89; }
  .obs-exposure { display: flex; align-items: center; gap: 10px; margin-top: 16px; }
  .obs-exposure-label { width: 70px; color: var(--obs-muted); font: 9px 'DM Mono', monospace; text-transform: uppercase; }
  .obs-bar { height: 5px; flex: 1; overflow: hidden; border-radius: 99px; background: rgba(210,246,234,.08); }
  .obs-bar > i { display: block; height: 100%; border-radius: inherit; background: var(--accent); box-shadow: 0 0 14px var(--accent-soft); }
  .obs-exposure-number { width: 30px; color: var(--obs-ink); font: 10px 'DM Mono', monospace; text-align: right; }
  .obs-detail-divider { display: flex; align-items: center; gap: 10px; margin: 19px 0 13px; color: var(--obs-dim); font: 9px 'DM Mono', monospace; letter-spacing: .13em; text-transform: uppercase; }
  .obs-detail-divider::after { content: ""; height: 1px; flex: 1; background: var(--obs-line); }
  .obs-chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .obs-chip { display: inline-flex; align-items: center; padding: 6px 8px; border: 1px solid var(--obs-line); border-radius: 5px; color: #c5ded8; background: rgba(180,239,225,.045); font: 10px 'DM Mono', monospace; }
  .obs-chip.accent { border-color: color-mix(in srgb, var(--accent) 32%, transparent); color: var(--accent); background: var(--accent-soft); }
  .obs-attribution { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
  .obs-attribution-item { min-width: 0; padding: 7px 8px; border-radius: 6px; background: rgba(0,0,0,.12); }
  .obs-attribution-item span { display: block; overflow: hidden; color: var(--obs-muted); font: 9px 'DM Mono', monospace; text-overflow: ellipsis; white-space: nowrap; }
  .obs-attribution-item strong { display: block; margin-top: 4px; color: var(--accent); font: 500 10px 'DM Mono', monospace; }
  .obs-wins { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .obs-winloss { display: flex; align-items: center; justify-content: space-between; gap: 4px; padding: 8px 9px; border: 1px solid var(--obs-line); border-radius: 6px; }
  .obs-winloss span { color: var(--obs-dim); font: 9px 'DM Mono', monospace; text-transform: uppercase; }
  .obs-winloss strong { font: 500 11px 'DM Mono', monospace; }
  .obs-winloss.win strong { color: #b7ef75; }
  .obs-winloss.loss strong { color: #ff9a91; }
  .obs-history { margin-top: 10px; }
  .obs-trade { display: grid; grid-template-columns: 66px 1fr 46px 60px; align-items: center; gap: 5px; min-height: 28px; border-bottom: 1px solid rgba(184,239,225,.07); color: var(--obs-muted); font: 9px 'DM Mono', monospace; }
  .obs-trade:last-child { border-bottom: 0; }
  .obs-trade-symbol { color: var(--obs-ink); font-weight: 500; }
  .obs-trade-side { color: var(--accent); font-size: 8px; letter-spacing: .08em; }
  .obs-trade-result { text-align: right; font-size: 10px; }
  .obs-trade-result.positive { color: #b7ef75; }
  .obs-trade-result.negative { color: #ff9a91; }
  .obs-cycle { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-top: 13px; padding-top: 11px; border-top: 1px solid var(--obs-line); color: var(--obs-dim); font: 9px 'DM Mono', monospace; }
  .obs-cycle strong { color: var(--obs-muted); font-weight: 400; }
  .obs-evidence { display: grid; grid-template-columns: 1.15fr .85fr; gap: 14px; margin-top: 31px; }
  .obs-evidence-panel { min-width: 0; padding: 18px; border: 1px solid var(--obs-line); border-radius: 15px; background: rgba(5, 25, 34, .62); box-shadow: inset 0 1px rgba(231,255,248,.06); }
  .obs-evidence-panel .obs-section-head { margin-bottom: 15px; }
  .obs-evidence-title { display: flex; align-items: center; gap: 9px; }
  .obs-evidence-title svg { color: #8cf1d5; }
  .obs-correlation { display: grid; grid-template-columns: 1.25fr repeat(3, minmax(60px, 1fr)); gap: 1px; overflow: hidden; border: 1px solid var(--obs-line); border-radius: 8px; background: var(--obs-line); }
  .obs-correlation > div { min-width: 0; padding: 11px 10px; background: rgba(6, 28, 37, .77); color: var(--obs-muted); font: 10px 'DM Mono', monospace; }
  .obs-correlation .corr-head { padding-top: 9px; padding-bottom: 9px; color: var(--obs-dim); font-size: 8px; letter-spacing: .09em; text-transform: uppercase; }
  .obs-correlation .corr-label { color: var(--obs-ink); font-weight: 500; }
  .obs-correlation .corr-num { text-align: center; font-weight: 500; }
  .obs-correlation .high { color: #f2be78; background: rgba(242,190,120,.09); }
  .obs-correlation .low { color: #8cf1d5; background: rgba(140,241,213,.07); }
  .obs-correlation .neg { color: #ff9a91; background: rgba(255,154,145,.06); }
  .obs-legend { display: flex; gap: 16px; margin-top: 12px; color: var(--obs-dim); font: 9px 'DM Mono', monospace; }
  .obs-legend span { display: inline-flex; align-items: center; gap: 6px; }
  .obs-legend i { width: 7px; height: 7px; display: inline-block; border-radius: 2px; background: #f2be78; }
  .obs-legend .legend-low { background: #8cf1d5; }
  .obs-timeline { display: grid; gap: 0; }
  .obs-timeline-row { display: grid; grid-template-columns: 75px 10px 1fr 65px; align-items: center; gap: 8px; min-height: 39px; border-bottom: 1px solid rgba(184,239,225,.08); font: 10px 'DM Mono', monospace; }
  .obs-timeline-row:last-child { border-bottom: 0; }
  .obs-timeline-time { color: var(--obs-dim); font-size: 9px; }
  .obs-timeline-mark { width: 7px; height: 7px; border-radius: 99px; background: #8cf1d5; box-shadow: 0 0 0 3px rgba(140,241,213,.10); }
  .obs-timeline-mark.warn { background: #ff9a91; box-shadow: 0 0 0 3px rgba(255,154,145,.10); }
  .obs-timeline-copy { min-width: 0; overflow: hidden; color: var(--obs-muted); text-overflow: ellipsis; white-space: nowrap; }
  .obs-timeline-copy strong { color: var(--obs-ink); font-weight: 500; }
  .obs-timeline-pnl { text-align: right; }
  .obs-footer { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-top: 21px; color: var(--obs-dim); font: 9px 'DM Mono', monospace; letter-spacing: .05em; }
  .obs-footer-left { display: flex; align-items: center; gap: 8px; }
  .obs-footer-left svg { color: #b7ef75; }
  .obs-footer-right { display: flex; gap: 16px; }
  @media (max-width: 1199px) {
    .observatory { min-height: 100dvh; padding: 16px; overflow: auto; }
    .obs-topline { margin-bottom: 22px; }
    .obs-hero { align-items: start; flex-direction: column; }
    .obs-asof { min-width: 0; width: 100%; }
    .obs-summary { grid-template-columns: 1fr 1fr; }
    .obs-summary-cell:last-child { grid-column: span 2; }
    .obs-bot-row { grid-template-columns: 1fr; }
    .obs-evidence { grid-template-columns: 1fr; }
    .obs-desktop-density { display: none !important; }
  }
  @media (max-width: 560px) {
    .obs-topline { align-items: start; flex-direction: column; }
    .obs-session { flex-wrap: wrap; }
    .obs-title { font-size: 34px; }
    .obs-summary { grid-template-columns: 1fr; }
    .obs-summary-cell:last-child { grid-column: auto; }
    .obs-summary-cell { min-height: 76px; }
    .obs-metrics { gap: 6px; }
    .obs-metric-label { font-size: 8px; }
    .obs-metric-value { font-size: 12px; }
    .obs-attribution { grid-template-columns: 1fr; }
    .obs-attribution-item { display: flex; justify-content: space-between; }
    .obs-footer { align-items: start; flex-direction: column; }
  }
`;

function Sparkline({ bot }: { bot: Bot }) {
  return (
    <div className="obs-chart" aria-label={`${bot.name} equity curve`}>
      <svg viewBox="0 0 242 80" role="img">
        <line className="obs-chart-grid" x1="2" x2="240" y1="20" y2="20" />
        <line className="obs-chart-grid" x1="2" x2="240" y1="48" y2="48" />
        <path className="obs-chart-area" d={bot.sparkArea} />
        <path className="obs-chart-line" d={bot.spark} />
        <circle className="obs-chart-end" cx="240" cy={bot.name === "SPY/QQQ Trend" ? "67" : bot.name === "Oracle" ? "6" : "13"} r="3.5" />
      </svg>
      <div className="obs-chart-caption"><span>30D equity path</span><span>now</span></div>
    </div>
  );
}

function BotCard({ bot }: { bot: Bot }) {
  const style = { "--accent": bot.accent, "--accent-soft": bot.accentSoft } as CSSProperties;
  const isPositive = bot.pnl.startsWith("+");
  return (
    <article className="obs-bot-card" style={style}>
      <div className="obs-card-inner">
        <div className="obs-card-head">
          <div>
            <div className="obs-bot-eyebrow">{bot.eyebrow}</div>
            <h3 className="obs-bot-name">{bot.name}</h3>
          </div>
          <div className="obs-bot-code">{bot.code}</div>
        </div>

        <div className="obs-equity-line">
          <div className="obs-equity">{bot.equity}</div>
          <div className={`obs-return ${isPositive ? "positive" : "negative"}`}>
            {bot.pnl} <span>{bot.pnlPercent} / since launch</span>
          </div>
        </div>
        <Sparkline bot={bot} />

        <div className="obs-metrics">
          <div className="obs-metric"><span className="obs-metric-label">Sharpe</span><span className="obs-metric-value good">{bot.sharpe}</span></div>
          <div className="obs-metric"><span className="obs-metric-label">Max DD</span><span className="obs-metric-value risk">{bot.drawdown}</span></div>
          <div className="obs-metric"><span className="obs-metric-label">Win rate</span><span className="obs-metric-value">{bot.winRate}</span></div>
          <div className="obs-metric"><span className="obs-metric-label">Trades</span><span className="obs-metric-value">{bot.trades}</span></div>
        </div>
        <div className="obs-exposure">
          <span className="obs-exposure-label">Exposure</span>
          <span className="obs-bar"><i style={{ width: `${bot.exposure}%` }} /></span>
          <span className="obs-exposure-number">{bot.exposure}%</span>
        </div>

        <div className="obs-desktop-density">
          <div className="obs-detail-divider">open positions <span>{bot.positions.length.toString().padStart(2, "0")}</span></div>
          <div className="obs-chips">{bot.positions.map((position) => <span className="obs-chip accent" key={position}>{position}</span>)}</div>

          <div className="obs-detail-divider">return attribution</div>
          <div className="obs-attribution">
            {bot.attribution.map((item) => {
              const [label, value] = item.split(" ");
              return <div className="obs-attribution-item" key={item}><span>{label}</span><strong>{value}</strong></div>;
            })}
          </div>

          <div className="obs-detail-divider">distribution</div>
          <div className="obs-wins">
            <div className="obs-winloss win"><span>biggest win</span><strong>{bot.win}</strong></div>
            <div className="obs-winloss loss"><span>biggest loss</span><strong>{bot.loss}</strong></div>
          </div>

          <div className="obs-detail-divider">last executions</div>
          <div className="obs-history">
            {bot.tradesHistory.map((trade) => (
              <div className="obs-trade" key={`${bot.code}-${trade.time}-${trade.symbol}`}>
                <span>{trade.time}</span><span className="obs-trade-symbol">{trade.symbol}</span><span className="obs-trade-side">{trade.side}</span><span className={`obs-trade-result ${trade.tone}`}>{trade.result}</span>
              </div>
            ))}
          </div>
          <div className="obs-cycle"><span><CalendarClock size={11} /> last cycle</span><strong>{bot.cycle}</strong></div>
        </div>
      </div>
    </article>
  );
}

export function AnalyticsObservatory() {
  return (
    <main className="homepage-concept observatory">
      <style>{styles}</style>
      <div className="obs-shell">
        <div className="obs-topline">
          <div className="obs-brand"><span className="obs-mark"><Crosshair size={15} strokeWidth={2.5} /></span><span>FLEET / OBSERVATORY</span></div>
          <div className="obs-session">
            <span><i className="obs-dot" /> MARKET OPEN</span>
            <span><i className="obs-dot" /> SYNCED 08:43:02 UTC</span>
            <span><i className="obs-dot amber" /> PAPER + LIVE</span>
          </div>
        </div>

        <header className="obs-hero">
          <div>
            <p className="obs-kicker">quantitative command surface / 03 active strategies</p>
            <h1 className="obs-title">Understand the <em>why</em> behind the green.</h1>
            <p className="obs-subtitle">A live read on the fleet's return engine — from the headline outcome down to the positions, risk, and executions that produced it.</p>
          </div>
          <div className="obs-asof"><strong>Tuesday · 14 May 2024</strong>observed across 03 venues<br />window: trailing 30 trading days</div>
        </header>

        <section className="obs-summary" aria-label="Fleet summary">
          <div className="obs-summary-cell">
            <div className="obs-label">Fleet equity</div>
            <div className="obs-value large">$296,398</div>
            <div className="obs-under"><strong>+$12,840</strong><span>+4.53% all time</span></div>
          </div>
          <div className="obs-summary-cell">
            <div className="obs-label">24h movement</div>
            <div className="obs-value positive">+$1,142</div>
            <div className="obs-under"><strong>+0.39%</strong><span>vs. prior close</span></div>
          </div>
          <div className="obs-summary-cell">
            <div className="obs-label">Open positions</div>
            <div className="obs-value">08</div>
            <div className="obs-under"><span>across 09 symbols</span></div>
          </div>
          <div className="obs-summary-cell">
            <div className="obs-label">Market regime</div>
            <div className="obs-regime"><TrendingUp className="obs-regime-icon" size={20} /><strong>BULL</strong></div>
          </div>
          <div className="obs-summary-cell">
            <ShieldCheck size={24} color="#b7ef75" />
            <div><div className="obs-label">Risk coverage</div><div className="obs-stops">ALL PROTECTIVE<br />STOPS COVERED</div></div>
          </div>
        </section>

        <section aria-labelledby="engines-heading">
          <div className="obs-section-head">
            <h2 className="obs-section-title" id="engines-heading"><i className="tiny-mark" />Strategy engines</h2>
            <div className="obs-section-meta">equity curves / risk-adjusted evidence / UTC</div>
          </div>
          <div className="obs-bot-row">
            {bots.map((bot) => <BotCard bot={bot} key={bot.code} />)}
          </div>
        </section>

        <section className="obs-evidence obs-desktop-density" aria-label="Evidence deck">
          <div className="obs-evidence-panel">
            <div className="obs-section-head">
              <div className="obs-evidence-title"><BarChart3 size={16} /><h2 className="obs-section-title">Evidence deck · correlated positions</h2></div>
              <div className="obs-section-meta">live notional overlap</div>
            </div>
            <div className="obs-correlation">
              <div className="corr-head">symbol</div><div className="corr-head">oracle</div><div className="corr-head">trend</div><div className="corr-head">jerome</div>
              <div className="corr-label">SPY <span className="obs-dim">/ broad beta</span></div><div className="corr-num high">+72%</div><div className="corr-num high">+64%</div><div className="corr-num low">—</div>
              <div className="corr-label">QQQ <span className="obs-dim">/ growth beta</span></div><div className="corr-num high">+41%</div><div className="corr-num high">+58%</div><div className="corr-num low">—</div>
              <div className="corr-label">XLK <span className="obs-dim">/ sector</span></div><div className="corr-num high">+24%</div><div className="corr-num low">—</div><div className="corr-num low">—</div>
              <div className="corr-label">GLD · SLV <span className="obs-dim">/ metals</span></div><div className="corr-num low">—</div><div className="corr-num low">—</div><div className="corr-num high">+56%</div>
              <div className="corr-label">TLT <span className="obs-dim">/ duration hedge</span></div><div className="corr-num low">—</div><div className="corr-num low">—</div><div className="corr-num neg">-18%</div>
            </div>
            <div className="obs-legend"><span><i /> elevated exposure</span><span><i className="legend-low" /> no overlap</span><span><i style={{ background: "#ff9a91" }} /> inverse hedge</span></div>
          </div>

          <div className="obs-evidence-panel">
            <div className="obs-section-head">
              <div className="obs-evidence-title"><Activity size={16} /><h2 className="obs-section-title">Recent trade history</h2></div>
              <div className="obs-section-meta">latest fleet events</div>
            </div>
            <div className="obs-timeline">
              <div className="obs-timeline-row"><span className="obs-timeline-time">09:38:12</span><i className="obs-timeline-mark" /><span className="obs-timeline-copy"><strong>Oracle</strong> opened XLK long</span><span className="obs-timeline-pnl" style={{ color: "#b7ef75" }}>+$412</span></div>
              <div className="obs-timeline-row"><span className="obs-timeline-time">09:31:04</span><i className="obs-timeline-mark warn" /><span className="obs-timeline-copy"><strong>SPY/QQQ</strong> trimmed SPY short</span><span className="obs-timeline-pnl" style={{ color: "#ff9a91" }}>-$318</span></div>
              <div className="obs-timeline-row"><span className="obs-timeline-time">09:12:47</span><i className="obs-timeline-mark" /><span className="obs-timeline-copy"><strong>Jerome</strong> added GLD long</span><span className="obs-timeline-pnl" style={{ color: "#b7ef75" }}>+$672</span></div>
              <div className="obs-timeline-row"><span className="obs-timeline-time">08:56:20</span><i className="obs-timeline-mark" /><span className="obs-timeline-copy"><strong>Oracle</strong> extended QQQ long</span><span className="obs-timeline-pnl" style={{ color: "#b7ef75" }}>+$286</span></div>
              <div className="obs-timeline-row"><span className="obs-timeline-time">08:42:16</span><i className="obs-timeline-mark" /><span className="obs-timeline-copy"><strong>Risk layer</strong> stops revalidated</span><span className="obs-timeline-pnl" style={{ color: "#8cf1d5" }}>CLEAR</span></div>
            </div>
          </div>
        </section>

        <footer className="obs-footer">
          <div className="obs-footer-left"><CheckCircle2 size={13} /> DATA INTEGRITY 99.98% · ALL FEEDS NOMINAL</div>
          <div className="obs-footer-right"><span><Waves size={11} /> LATENCY 42MS</span><span><Gauge size={11} /> RISK ENGINE ARMED</span><span>BUILD 2.4.18</span></div>
        </footer>
      </div>
    </main>
  );
}
