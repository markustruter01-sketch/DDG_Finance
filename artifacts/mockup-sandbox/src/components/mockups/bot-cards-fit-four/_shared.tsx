import type { CSSProperties } from "react";
import { CalendarClock } from "lucide-react";

type BotPreview = {
  id: string;
  name: string;
  accent: string;
  status: string;
  equity: string;
  pnl: string;
  pnlPct: string;
  winRate: string;
  positions: string[];
  history: number[];
  lastCycle: string;
};

const bots: BotPreview[] = [
  {
    id: "oracle",
    name: "Atlas · Global Market Indices",
    accent: "#c084fc",
    status: "PAUSED",
    equity: "$90,362",
    pnl: "−$9,638",
    pnlPct: "−9.6%",
    winRate: "NULL",
    positions: ["AAPL · LONG", "MSFT · LONG", "SPY · LONG", "QQQ · LONG"],
    history: [14, 16, 13, 15, 17, 14, 18, 16, 68],
    lastCycle: "2026-10-09T01:22:58.065Z",
  },
  {
    id: "spy_qqq_trend",
    name: "Momentum · Stock Trend Cooldown",
    accent: "#f5a623",
    status: "ACTIVE",
    equity: "$113,227",
    pnl: "+$13,227",
    pnlPct: "+13.2%",
    winRate: "11.1%",
    positions: ["SPY · LONG", "QQQ · LONG", "VGT · LONG", "VUG · LONG"],
    history: [16, 19, 17, 20, 18, 23, 21, 26, 71],
    lastCycle: "2026-10-09T01:22:58.065Z",
  },
  {
    id: "jerome_macro",
    name: "Bullion · Precious Metals and Crypto",
    accent: "#ff6f73",
    status: "ACTIVE",
    equity: "$85,118",
    pnl: "−$14,882",
    pnlPct: "−14.9%",
    winRate: "NULL",
    positions: ["GLD · LONG", "SLV · LONG", "GDX · LONG"],
    history: [22, 20, 23, 18, 21, 19, 24, 22, 70],
    lastCycle: "2026-10-09T01:22:58.065Z",
  },
  {
    id: "forex_gump",
    name: "Forex · AI Currency Trading",
    accent: "#55b8e9",
    status: "NULL",
    equity: "NULL",
    pnl: "NULL",
    pnlPct: "NULL",
    winRate: "NULL",
    positions: [],
    history: [18, 20, 17, 21, 16, 20, 15, 19, 23],
    lastCycle: "NULL",
  },
];

function chartPath(points: number[]) {
  const min = Math.min(...points);
  const range = Math.max(...points) - min || 1;
  return points.map((value, index) => {
    const x = (index / (points.length - 1 || 1)) * 238 + 2;
    const y = 72 - ((value - min) / range) * 64;
    return `${index ? "L" : "M"} ${x} ${y}`;
  }).join(" ");
}

function BotCard({ bot, compact }: { bot: BotPreview; compact: boolean }) {
  const accentStyle = {
    "--accent": bot.accent,
    "--accent-soft": `${bot.accent}22`,
  } as CSSProperties;

  return (
    <article
      className="obs-bot-card"
      style={accentStyle}
      aria-label={`${bot.name} strategy engine`}
    >
      <div className="obs-card-head">
        <div>
          <div className="obs-bot-eyebrow">{bot.id.replace(/_/g, " ").toUpperCase()}</div>
          <h3 className="obs-bot-name">{bot.name}</h3>
        </div>
        <div className="obs-bot-code">{bot.status}</div>
      </div>
      <div className="obs-equity-line">
        <div>
          {compact && <div className="obs-label">Equity</div>}
          <div className="obs-equity">{bot.equity}</div>
        </div>
        <div className="obs-return">
          {bot.pnl}
          <span>{bot.pnlPct} / server</span>
        </div>
      </div>
      <div className="obs-chart" aria-label={`${bot.name} fleet equity history; per-bot history unavailable`}>
        <svg viewBox="0 0 242 80" aria-hidden="true">
          <line className="obs-chart-grid" x1="2" x2="240" y1="20" y2="20" />
          <line className="obs-chart-grid" x1="2" x2="240" y1="48" y2="48" />
          <path className="obs-chart-line" d={chartPath(bot.history)} />
        </svg>
        <div className="obs-note">Fleet history shown · per-bot curve NULL</div>
      </div>
      <div className="obs-metrics">
        <div className="obs-metric"><label>Sharpe</label><strong>NULL</strong></div>
        <div className="obs-metric"><label>Max DD</label><strong>NULL</strong></div>
        <div className="obs-metric"><label>Win rate</label><strong>{bot.winRate}</strong></div>
        <div className="obs-metric"><label>Trades</label><strong>NULL</strong></div>
      </div>
      <div className="obs-detail">Open positions ({bot.positions.length})</div>
      <div className="obs-chips">
        {bot.positions.length
          ? bot.positions.map((position) => <span className="obs-chip" key={`${bot.id}-${position}`}>{position}</span>)
          : <span className="obs-note">NULL · Unavailable from current API</span>}
      </div>
      {compact ? (
        <details className="obs-more">
          <summary>More audit detail</summary>
          <div className="obs-more-content">
            <div>
              <span className="obs-extra-label">Return attribution</span>
              <span className="obs-note">Fleet-level attribution only; bot scope NULL</span>
            </div>
            <div>
              <span className="obs-extra-label">Biggest win / loss</span>
              <span className="obs-note">NULL · per-bot trade distribution unavailable from current API</span>
            </div>
          </div>
        </details>
      ) : (
        <>
          <div className="obs-detail">Return attribution</div>
          <div className="obs-note">Fleet-level attribution only; bot scope NULL</div>
          <div className="obs-detail">Biggest win / loss</div>
          <div className="obs-note">NULL · per-bot trade distribution unavailable from current API</div>
        </>
      )}
      <div className="obs-cycle">
        <span><CalendarClock size={compact ? 10 : 11} aria-hidden="true" /> last cycle</span>
        <strong>{bot.lastCycle}</strong>
      </div>
    </article>
  );
}

export function PreviewPage({ compact }: { compact: boolean }) {
  return (
    <main className={`bot-preview ${compact ? "bot-preview--four" : "bot-preview--current"}`}>
      <div className="mockup-shell">
        <div className="mockup-topline">
          <strong>Fleet / Observatory</strong>
          <span className="mockup-preview-tag">Design preview · static screenshot fixture</span>
        </div>
        <section className="mockup-summary" aria-label="Snapshot context">
          <div className="mockup-summary-item">
            <div className="mockup-summary-label">Fleet equity</div>
            <div className="mockup-summary-value">$388,797</div>
          </div>
          <div className="mockup-summary-item">
            <div className="mockup-summary-label">24h change</div>
            <div className="mockup-summary-value">−$642</div>
          </div>
          <div className="mockup-summary-item">
            <div className="mockup-summary-label">Sharpe</div>
            <div className="mockup-summary-value">−1.19</div>
          </div>
          <div className="mockup-summary-item">
            <div className="mockup-summary-label">Open positions</div>
            <div className="mockup-summary-value">18</div>
          </div>
        </section>
        <section aria-labelledby="preview-strategy-engines">
          <div className="obs-section-head">
            <h2 className="obs-section-title" id="preview-strategy-engines">Strategy engines</h2>
            <div className="obs-meta">equity curves / risk evidence / UTC</div>
          </div>
          <div className="obs-bot-row">
            {bots.map((bot) => <BotCard bot={bot} compact={compact} key={bot.id} />)}
          </div>
        </section>
      </div>
    </main>
  );
}
