import {
  Activity,
  BarChart3,
  Bot,
  CircleHelp,
  Clock3,
  Gauge,
  Globe2,
  Leaf,
  LineChart,
  Waves,
} from "lucide-react";
import type { ReactNode } from "react";
import {
  useAttribution,
  useBotRegistry,
  useFleetEquity,
  useJournal,
  useRiskMetrics,
  useSentiment,
  useStatusSummary,
  useVault,
  useVaultHistory,
} from "../streaming-current/_shared/mockData";
import { getBotIdentity } from "../streaming-current/_shared/identity";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";
import type { NameType, ValueType } from "recharts/types/component/DefaultTooltipContent";

const palette = {
  ink: "#eff4e9",
  muted: "rgba(223,233,220,.63)",
  faint: "rgba(223,233,220,.4)",
  glass: "rgba(12, 27, 27, .76)",
  border: "rgba(219, 239, 221, .15)",
  green: "#a9d8ad",
  mint: "#75cdb5",
  gold: "#e2c47d",
  coral: "#ee9a8c",
  blue: "#9cc8d2",
};

const BOT_META: Record<string, { color: string; label: string; icon: typeof Globe2 }> = {
  oracle: { color: "#cfb9f3", label: getBotIdentity("oracle").displayName, icon: Globe2 },
  spy_qqq_trend: { color: "#91d5ce", label: getBotIdentity("spy_qqq_trend").displayName, icon: LineChart },
  jerome_macro: { color: "#e6bc85", label: getBotIdentity("jerome_macro").displayName, icon: Waves },
};

function fmt(value: number | null | undefined, places = 2) {
  return value == null ? "—" : value.toFixed(places);
}

function fmtPct(value: number | null | undefined, places = 1) {
  return value == null ? "—" : `${value.toFixed(places)}%`;
}

function fmtMoney(value: number | null | undefined) {
  if (value == null) return "—";
  const prefix = value >= 0 ? "+" : "";
  const absolute = Math.abs(value);
  if (absolute >= 1_000_000) return `${prefix}$${(value / 1_000_000).toFixed(2)}M`;
  if (absolute >= 1_000) return `${prefix}$${(value / 1_000).toFixed(1)}k`;
  return `${prefix}$${value.toFixed(0)}`;
}

function ratioTone(value: number | null | undefined, threshold = 1) {
  if (value == null) return palette.faint;
  return value >= threshold ? palette.green : value >= 0 ? palette.gold : palette.coral;
}

function pnlTone(value: number | null | undefined) {
  if (value == null) return palette.faint;
  return value >= 0 ? palette.green : palette.coral;
}

function fearGreedTone(value: number | null | undefined) {
  if (value == null) return palette.faint;
  if (value < 25) return palette.coral;
  if (value < 45) return "#dfa27f";
  if (value < 55) return palette.gold;
  if (value < 75) return palette.green;
  return "#77dda0";
}

function fearGreedLabel(value: number | null | undefined) {
  if (value == null) return "No data";
  if (value < 25) return "Extreme Fear";
  if (value < 45) return "Fear";
  if (value < 55) return "Neutral";
  if (value < 75) return "Greed";
  return "Extreme Greed";
}

function SectionLabel({ children }: { children: ReactNode }) {
  return <div className="perf-kicker">{children}</div>;
}

function RiskTile({
  label,
  value,
  note,
  color,
}: {
  label: string;
  value: string;
  note: string;
  color: string;
}) {
  return (
    <div className="perf-risk-tile">
      <div className="perf-risk-label">{label}</div>
      <div className="perf-risk-value" style={{ color }}>{value}</div>
      <div className="perf-risk-note">{note}</div>
    </div>
  );
}

function VaultTooltip({ active, payload, label }: TooltipProps<ValueType, NameType>) {
  if (!active || !payload?.length) return null;
  const cumulative = typeof payload[0]?.value === "number" ? payload[0].value : null;
  const daily = typeof payload[1]?.value === "number" ? payload[1].value : null;
  return (
    <div className="perf-tooltip">
      <div className="perf-tooltip-date">{String(label ?? "")}</div>
      {cumulative != null && <div className="perf-tooltip-total">Total: ${cumulative.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>}
      {daily != null && <div className="perf-tooltip-daily">+${daily.toLocaleString(undefined, { maximumFractionDigits: 0 })} today</div>}
    </div>
  );
}

export function Performance() {
  const risk = useRiskMetrics();
  const journal = useJournal();
  const attribution = useAttribution();
  const sentiment = useSentiment();
  const status = useStatusSummary();
  const vault = useVault();
  const vaultHistory = useVaultHistory(90);
  const fleetQuery = useFleetEquity();
  const registryQuery = useBotRegistry();

  const rm = risk.data;
  const j = journal.data;
  const at = attribution.data;
  const sg = sentiment.data;
  const st = status.data;
  const fleetEq = fleetQuery.data;
  const fleetTrades = j?.summary?.total ?? null;
  const fleetWins = j?.summary?.wins ?? null;
  const fleetWinRate = fleetEq?.fleet_total?.win_rate != null ? fleetEq.fleet_total.win_rate * 100 : null;
  const attributionWinRate = at?.overall.win_rate ?? null;
  const marketFearGreed = sg?.market_fear_greed?.value;
  const regime = st?.groq?.regime ?? "—";
  const registryBots = (registryQuery.data?.bots ?? []).filter((bot) =>
    ["oracle", "spy_qqq_trend", "jerome_macro"].includes(bot.id),
  );

  const fleetEquity = fleetEq?.fleet_total?.equity ?? null;
  const snapshots = vaultHistory.data?.snapshots ?? [];
  const chartData = snapshots.map((snapshot) => ({
    date: snapshot.date.slice(5),
    total: snapshot.cumulative_vaulted,
    daily: snapshot.daily_vaulted,
  }));
  const annualReturnNote = rm?.insufficient_data
    ? `Need 30+ days · ${rm.data_points != null ? rm.data_points : "unavailable"} points so far`
    : rm?.period_days
      ? `${rm.period_days}d window · ${rm.data_points != null ? rm.data_points : "unavailable"} points`
      : "Awaiting data";
  const averagePnl = at?.overall.avg_pnl_pct ?? j?.summary.avg_pnl ?? null;
  const systemStatus = st?.system_health.system_status;
  const killSwitch = st?.kill_switch_tripped;

  return (
    <main className="perf-page">
      <style>{`
        .perf-page {
          --perf-ink: ${palette.ink};
          --perf-muted: ${palette.muted};
          --perf-faint: ${palette.faint};
          height: 100dvh;
          min-height: 700px;
          width: 100%;
          box-sizing: border-box;
          overflow: hidden;
          position: relative;
          isolation: isolate;
          padding: 20px 26px 18px;
          display: flex;
          flex-direction: column;
          gap: 12px;
          color: var(--perf-ink);
          background: #102322;
          font-family: "Geist", "Aptos", sans-serif;
        }
        .perf-page *, .perf-page *::before, .perf-page *::after { box-sizing: border-box; }
        .perf-backdrop {
          position: absolute;
          inset: 0;
          z-index: -2;
          background-image: url("/__mockup/images/streaming-forest-atmosphere.jpg");
          background-position: center 43%;
          background-size: cover;
          opacity: .36;
          filter: saturate(.64) contrast(.9);
        }
        .perf-page::before {
          position: absolute;
          inset: 0;
          content: "";
          z-index: -1;
          background:
            linear-gradient(90deg, rgba(8,21,23,.92) 0%, rgba(9,23,23,.82) 53%, rgba(10,25,24,.72) 100%),
            linear-gradient(180deg, rgba(12,25,25,.16) 0%, rgba(8,19,21,.77) 78%, #0a1a1b 100%);
        }
        .perf-topbar { height: 46px; flex: 0 0 46px; display:flex; align-items:center; justify-content:space-between; gap:24px; }
        .perf-titleblock { display:flex; align-items:center; gap:14px; min-width:0; }
        .perf-mark { width:38px; height:38px; display:grid; place-items:center; border:1px solid rgba(190,222,196,.3); border-radius:13px; background:rgba(201,231,205,.08); color:#c1e3bb; box-shadow:inset 0 1px rgba(255,255,255,.12); }
        .perf-titlecopy { display:flex; align-items:baseline; gap:13px; min-width:0; }
        .perf-eyebrow { color:rgba(208,225,207,.55); font:600 9px/1 "Geist Mono", monospace; letter-spacing:.19em; text-transform:uppercase; white-space:nowrap; }
        .perf-heading { margin:0; font:600 21px/1 "Geist", sans-serif; letter-spacing:-.045em; color:#f2f3e8; }
        .perf-context { font:11px/1 "Geist Mono", monospace; color:rgba(218,229,213,.53); white-space:nowrap; }
        .perf-topmeta { display:flex; align-items:center; gap:8px; }
        .perf-status-pill { height:30px; display:flex; align-items:center; gap:7px; padding:0 10px; border:1px solid rgba(199,221,201,.16); border-radius:99px; background:rgba(12,31,29,.58); color:rgba(232,239,225,.8); font:600 9px "Geist Mono", monospace; letter-spacing:.09em; text-transform:uppercase; white-space:nowrap; }
        .perf-status-pill svg { color:#a8d6a5; }
        .perf-live-dot { width:6px; height:6px; border-radius:50%; background:#a9d8ad; box-shadow:0 0 0 3px rgba(169,216,173,.12); }
        .perf-risk-strip { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:9px; flex:0 0 94px; }
        .perf-risk-tile {
          padding:12px 14px 10px;
          min-width:0;
          border:1px solid rgba(214,232,211,.16);
          border-radius:13px;
          background:linear-gradient(145deg,rgba(27,48,45,.72),rgba(11,27,27,.74));
          backdrop-filter:blur(18px) saturate(115%);
          box-shadow:inset 0 1px rgba(255,255,255,.09), 0 10px 25px rgba(0,0,0,.12);
        }
        .perf-risk-label { color:rgba(214,228,209,.57); font:600 9px/1.2 "Geist Mono",monospace; letter-spacing:.13em; text-transform:uppercase; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .perf-risk-value { margin-top:9px; font:600 26px/.95 "Geist Mono",monospace; letter-spacing:-.075em; }
        .perf-risk-note { margin-top:7px; color:rgba(218,229,214,.54); font:10px/1.1 "Geist Mono",monospace; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .perf-content { display:grid; grid-template-columns:minmax(0,1.08fr) minmax(0,.92fr); gap:12px; min-height:0; flex:1; }
        .perf-panel {
          min-width:0;
          border:1px solid ${palette.border};
          border-radius:16px;
          background:linear-gradient(145deg,rgba(22,42,40,.79),rgba(11,27,28,.80));
          backdrop-filter:blur(20px) saturate(115%);
          box-shadow:inset 0 1px rgba(255,255,255,.09),0 14px 35px rgba(0,0,0,.14);
        }
        .perf-matrix { display:flex; flex-direction:column; overflow:hidden; }
        .perf-panel-head { display:flex; justify-content:space-between; align-items:flex-start; gap:18px; padding:16px 18px 12px; border-bottom:1px solid rgba(218,233,215,.11); }
        .perf-kicker { color:rgba(211,228,208,.57); font:600 9px/1.2 "Geist Mono",monospace; letter-spacing:.16em; text-transform:uppercase; }
        .perf-panel-title { margin:6px 0 0; color:#f1f2e7; font:550 17px/1 "Geist",sans-serif; letter-spacing:-.025em; }
        .perf-inline-stats { display:flex; gap:19px; }
        .perf-inline-stat { text-align:right; }
        .perf-inline-stat span { display:block; color:rgba(212,228,209,.48); font:600 8px/1.4 "Geist Mono",monospace; letter-spacing:.11em; text-transform:uppercase; white-space:nowrap; }
        .perf-inline-stat strong { display:block; margin-top:4px; font:600 15px/1 "Geist Mono",monospace; color:#dfe8d8; }
        .perf-matrix-table { padding:0 17px; }
        .perf-table-head,.perf-bot-row { display:grid; grid-template-columns:minmax(190px,1.8fr) minmax(70px,.7fr) minmax(65px,.55fr) minmax(85px,.8fr); column-gap:12px; align-items:center; }
        .perf-table-head { min-height:32px; color:rgba(208,226,206,.43); font:600 8px/1 "Geist Mono",monospace; letter-spacing:.13em; text-transform:uppercase; }
        .perf-table-head span:not(:first-child), .perf-table-cell { text-align:right; }
        .perf-bot-row { min-height:67px; border-top:1px solid rgba(219,235,216,.08); }
        .perf-bot-identity { display:flex; align-items:center; gap:11px; min-width:0; }
        .perf-bot-glyph { width:32px; height:32px; flex:0 0 32px; display:grid; place-items:center; border:1px solid rgba(210,231,211,.16); border-radius:10px; background:rgba(239,247,233,.055); }
        .perf-bot-glyph svg { width:15px; height:15px; }
        .perf-bot-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font:600 12px/1.2 "Geist",sans-serif; }
        .perf-bot-sub { margin-top:4px; color:rgba(212,226,209,.48); font:9px/1 "Geist Mono",monospace; }
        .perf-table-cell { font:500 11px/1 "Geist Mono",monospace; color:rgba(226,234,219,.8); }
        .perf-table-cell.perf-unavailable { color:rgba(221,232,218,.32); }
        .perf-pnl-cell { font-weight:600; }
        .perf-matrix-foot { margin-top:auto; min-height:35px; display:flex; align-items:center; gap:7px; padding:0 18px; border-top:1px solid rgba(219,235,216,.08); color:rgba(215,228,211,.45); font:9px "Geist Mono",monospace; }
        .perf-matrix-foot svg { color:rgba(215,228,211,.48); }
        .perf-side { min-height:0; display:grid; grid-template-rows:auto auto 1fr; gap:10px; }
        .perf-stats { padding:14px 16px 15px; }
        .perf-stat-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin-top:13px; }
        .perf-stat { min-width:0; }
        .perf-stat-name { min-height:23px; color:rgba(211,226,207,.48); font:600 8px/1.25 "Geist Mono",monospace; letter-spacing:.08em; text-transform:uppercase; }
        .perf-stat-value { margin-top:3px; color:#eef0e4; font:600 21px/1 "Geist Mono",monospace; letter-spacing:-.06em; white-space:nowrap; }
        .perf-sentiment { padding:12px 16px 13px; }
        .perf-sentiment-line { display:flex; align-items:center; gap:12px; margin-top:10px; }
        .perf-gauge { width:33px; height:33px; flex:0 0 33px; display:grid; place-items:center; border:1px solid rgba(218,235,214,.14); border-radius:11px; background:rgba(231,240,220,.055); color:#dfc57f; }
        .perf-sentiment-main { flex:1; min-width:0; }
        .perf-sentiment-label { display:flex; align-items:baseline; justify-content:space-between; gap:10px; color:rgba(219,230,214,.63); font:10px "Geist Mono",monospace; }
        .perf-sentiment-label strong { font-size:13px; font-weight:600; }
        .perf-meter { height:5px; margin-top:7px; overflow:hidden; border-radius:9px; background:rgba(237,239,219,.11); }
        .perf-meter-fill { height:100%; border-radius:inherit; background:linear-gradient(90deg,#d58376 0%,#ddc17c 52%,#94d09b 100%); }
        .perf-system { padding:13px 16px 14px; min-height:0; }
        .perf-system-heading { display:flex; align-items:center; justify-content:space-between; }
        .perf-regime { padding:5px 8px; border:1px solid rgba(154,207,158,.24); border-radius:7px; color:#b4dfa9; background:rgba(140,190,136,.08); font:600 9px "Geist Mono",monospace; text-transform:uppercase; }
        .perf-system-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px 10px; margin-top:13px; }
        .perf-system-item { min-width:0; }
        .perf-system-name { color:rgba(210,225,207,.46); font:600 8px/1.25 "Geist Mono",monospace; letter-spacing:.1em; text-transform:uppercase; }
        .perf-system-value { margin-top:5px; color:#e6ebdf; font:600 12px/1 "Geist Mono",monospace; text-transform:uppercase; white-space:nowrap; }
        .perf-system-value::before { content:""; display:inline-block; width:5px; height:5px; margin:0 6px 1px 0; border-radius:50%; background:currentColor; opacity:.85; }
        .perf-vault { flex:0 0 174px; min-height:174px; display:flex; flex-direction:column; padding:11px 16px 8px; overflow:hidden; }
        .perf-vault-head { display:flex; justify-content:space-between; align-items:center; gap:16px; min-height:30px; }
        .perf-vault-title { display:flex; align-items:center; gap:8px; }
        .perf-vault-title svg { color:#d9c47e; }
        .perf-vault-meta { display:flex; align-items:center; gap:17px; color:rgba(214,226,208,.51); font:9px "Geist Mono",monospace; }
        .perf-vault-total { color:#e4cc8b; font-size:11px; font-weight:600; }
        .perf-vault-chart { flex:1; min-height:0; }
        .perf-chart-empty { height:100%; display:grid; place-items:center; color:rgba(220,229,214,.51); font:10px "Geist Mono",monospace; text-align:center; }
        .perf-tooltip { padding:9px 11px; border:1px solid rgba(220,199,132,.3); border-radius:9px; background:rgba(10,23,23,.96); color:#e9eddf; font:10px "Geist Mono",monospace; box-shadow:0 8px 24px rgba(0,0,0,.28); }
        .perf-tooltip-date { margin-bottom:5px; color:rgba(220,229,214,.52); }
        .perf-tooltip-total { color:#e4cc8b; font-weight:600; }
        .perf-tooltip-daily { margin-top:3px; color:#a9d8ad; }
        @media (max-width: 1050px) {
          .perf-page { overflow:auto; min-height:100dvh; height:auto; }
          .perf-risk-strip { grid-template-columns:repeat(3,minmax(0,1fr)); flex-basis:auto; }
          .perf-content { grid-template-columns:1fr; }
          .perf-matrix { min-height:310px; }
          .perf-side { grid-template-rows:auto auto auto; }
          .perf-system { min-height:142px; }
          .perf-vault { min-height:174px; }
        }
        @media (max-width: 650px) {
          .perf-page { padding:16px; gap:11px; }
          .perf-topbar { height:auto; flex-basis:auto; align-items:flex-start; }
          .perf-titlecopy { display:block; }
          .perf-eyebrow { margin-bottom:6px; }
          .perf-context { display:none; }
          .perf-topmeta { flex-direction:column; align-items:flex-end; }
          .perf-status-pill { height:26px; font-size:8px; padding:0 8px; }
          .perf-risk-strip { grid-template-columns:repeat(2,minmax(0,1fr)); }
          .perf-risk-tile { padding:11px; }
          .perf-risk-value { font-size:23px; }
          .perf-panel-head { flex-direction:column; }
          .perf-inline-stats { width:100%; justify-content:space-between; }
          .perf-matrix-table { padding:0 11px; }
          .perf-table-head,.perf-bot-row { grid-template-columns:minmax(100px,1.5fr) 56px 50px 70px; column-gap:7px; }
          .perf-bot-name { font-size:11px; }
          .perf-bot-row { min-height:62px; }
          .perf-stat-grid { grid-template-columns:repeat(2,minmax(0,1fr)); row-gap:13px; }
          .perf-system-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
          .perf-vault-head { align-items:flex-start; flex-direction:column; gap:5px; }
          .perf-vault-meta { width:100%; justify-content:space-between; }
        }
      `}</style>
      <div className="perf-backdrop" aria-hidden="true" />

      <header className="perf-topbar">
        <div className="perf-titleblock">
          <div className="perf-mark"><Leaf size={18} strokeWidth={1.7} /></div>
          <div className="perf-titlecopy">
            <span className="perf-eyebrow">STREAMING / FLEET</span>
            <h1 className="perf-heading">Performance</h1>
            <span className="perf-context">Risk &amp; portfolio evidence</span>
          </div>
        </div>
        <div className="perf-topmeta">
          <div className="perf-status-pill"><span className="perf-live-dot" />Streaming</div>
          <div className="perf-status-pill"><Activity size={12} />{st?.market_open == null ? "Market unknown" : st.market_open ? "Market open" : "Market closed"}</div>
          <div className="perf-status-pill"><Clock3 size={12} />90 day view</div>
        </div>
      </header>

      <section className="perf-risk-strip" aria-label="Fleet risk metrics">
        <RiskTile
          label="Sharpe ratio"
          value={fmt(rm?.sharpe_ratio)}
          note={rm?.sharpe_ratio == null ? (rm?.message ?? "Unavailable") : rm.sharpe_ratio >= 1 ? "Good risk-adjusted return" : rm.sharpe_ratio >= 0 ? "Marginal" : "Below zero"}
          color={ratioTone(rm?.sharpe_ratio)}
        />
        <RiskTile label="Sortino ratio" value={fmt(rm?.sortino_ratio)} note="Downside-adjusted return" color={ratioTone(rm?.sortino_ratio)} />
        <RiskTile
          label="Max drawdown"
          value={rm?.max_drawdown_pct != null ? `-${fmt(rm.max_drawdown_pct, 1)}%` : "—"}
          note="Peak-to-trough loss"
          color={rm?.max_drawdown_pct != null ? (rm.max_drawdown_pct < 5 ? palette.green : rm.max_drawdown_pct < 15 ? palette.gold : palette.coral) : palette.faint}
        />
        <RiskTile label="Calmar ratio" value={fmt(rm?.calmar_ratio)} note="Annual return ÷ max DD" color={ratioTone(rm?.calmar_ratio, 0.5)} />
        <RiskTile
          label="Annual volatility"
          value={fmtPct(rm?.volatility_annual_pct)}
          note="Annualised standard deviation"
          color={rm?.volatility_annual_pct != null ? (rm.volatility_annual_pct < 20 ? palette.green : rm.volatility_annual_pct < 40 ? palette.gold : palette.coral) : palette.faint}
        />
        <RiskTile
          label="Annual return"
          value={fmtPct(rm?.annualised_return_pct)}
          note={annualReturnNote}
          color={rm?.annualised_return_pct != null ? (rm.annualised_return_pct >= 0 ? palette.green : palette.coral) : palette.faint}
        />
      </section>

      <section className="perf-content">
        <article className="perf-panel perf-matrix">
          <div className="perf-panel-head">
            <div>
              <SectionLabel>Portfolio attribution</SectionLabel>
              <h2 className="perf-panel-title">Bot performance matrix</h2>
            </div>
            <div className="perf-inline-stats">
              <div className="perf-inline-stat">
                <span>Fleet equity</span>
                <strong>{fleetEquity != null ? `$${(fleetEquity / 1000).toFixed(1)}k` : "—"}</strong>
              </div>
              <div className="perf-inline-stat">
                <span>Total trades</span>
                <strong>{fleetTrades != null ? fleetTrades : "—"}</strong>
              </div>
              <div className="perf-inline-stat">
                <span>Fleet win rate</span>
                <strong style={{ color: fleetWinRate == null ? palette.faint : fleetWinRate >= 50 ? palette.green : palette.coral }}>
                  {fleetWinRate != null ? fmtPct(fleetWinRate, 1) : "—"}
                </strong>
              </div>
            </div>
          </div>
          <div className="perf-matrix-table">
            <div className="perf-table-head">
              <span>Strategy</span><span>Win rate</span><span>Trades</span><span>P&amp;L</span>
            </div>
            {registryBots.length > 0 ? registryBots.map((bot) => {
              const meta = BOT_META[bot.id] ?? { color: palette.muted, label: bot.id, icon: Bot };
              const botEquity = fleetEq?.[bot.id as keyof typeof fleetEq];
              const pnl = botEquity && "pnl" in botEquity ? botEquity.pnl : null;
              const equity = botEquity && "equity" in botEquity ? botEquity.equity : null;
              const positions = botEquity && "positions" in botEquity ? botEquity.positions : null;
              const BotIcon = meta.icon;
              return (
                <div className="perf-bot-row" key={bot.id}>
                  <div className="perf-bot-identity">
                    <div className="perf-bot-glyph" style={{ color: meta.color }}><BotIcon /></div>
                    <div style={{ minWidth: 0 }}>
                      <div className="perf-bot-name" style={{ color: meta.color }}>{meta.label}</div>
                      <div className="perf-bot-sub">{equity != null ? `$${(equity / 1000).toFixed(1)}k equity` : "Equity unavailable"}{positions != null ? ` · ${positions} open` : ""}</div>
                    </div>
                  </div>
                  <div className="perf-table-cell perf-unavailable" aria-label="Per-bot win rate unavailable">—</div>
                  <div className="perf-table-cell perf-unavailable" aria-label="Per-bot trade count unavailable">—</div>
                  <div className="perf-table-cell perf-pnl-cell" style={{ color: pnlTone(pnl) }}>{fmtMoney(pnl)}</div>
                </div>
              );
            }) : (
              <div className="perf-chart-empty">
                {registryQuery.isLoading ? "Loading fleet data…" : registryQuery.isError ? "Fleet registry unavailable" : "No active bots are registered."}
              </div>
            )}
          </div>
          <div className="perf-matrix-foot">
            <CircleHelp size={12} />
            Per-bot win rate and trade count are not supplied by the source.
          </div>
        </article>

        <div className="perf-side">
          <article className="perf-panel perf-stats">
            <SectionLabel>Closed-trade record</SectionLabel>
            <h2 className="perf-panel-title">Fleet trade statistics</h2>
            <div className="perf-stat-grid">
              <div className="perf-stat">
                <div className="perf-stat-name">Total trades</div>
                <div className="perf-stat-value">{fleetTrades ?? "—"}</div>
              </div>
              <div className="perf-stat">
                <div className="perf-stat-name">All-time win rate · attribution</div>
                <div className="perf-stat-value" style={{ color: attributionWinRate == null ? palette.faint : attributionWinRate >= 50 ? palette.green : palette.coral }}>
                  {attributionWinRate != null ? `${attributionWinRate.toFixed(0)}%` : "—"}
                </div>
              </div>
              <div className="perf-stat">
                <div className="perf-stat-name">Total wins</div>
                <div className="perf-stat-value" style={{ color: palette.green }}>{fleetWins ?? "—"}</div>
              </div>
              <div className="perf-stat">
                <div className="perf-stat-name">Average P&amp;L</div>
                <div className="perf-stat-value" style={{ color: pnlTone(averagePnl) }}>
                  {averagePnl != null ? `${averagePnl > 0 ? "+" : ""}${averagePnl.toFixed(1)}%` : "—"}
                </div>
              </div>
            </div>
          </article>

          <article className="perf-panel perf-sentiment">
            <SectionLabel>Market sentiment</SectionLabel>
            <div className="perf-sentiment-line">
              <div className="perf-gauge"><Gauge size={17} strokeWidth={1.6} /></div>
              <div className="perf-sentiment-main">
                <div className="perf-sentiment-label">
                  <span>Market Fear &amp; Greed</span>
                  <strong style={{ color: fearGreedTone(marketFearGreed) }}>
                    {marketFearGreed != null ? marketFearGreed : "—"} <span style={{ fontWeight: 400 }}>{fearGreedLabel(marketFearGreed)}</span>
                  </strong>
                </div>
                <div className="perf-meter"><div className="perf-meter-fill" style={{ width: `${marketFearGreed ?? 0}%` }} /></div>
              </div>
            </div>
          </article>

          <article className="perf-panel perf-system">
            <div className="perf-system-heading">
              <SectionLabel>System status</SectionLabel>
              <span className="perf-regime">{regime} regime</span>
            </div>
            <div className="perf-system-grid">
              <div className="perf-system-item">
                <div className="perf-system-name">System</div>
                <div className="perf-system-value" style={{ color: systemStatus === "online" ? palette.green : systemStatus == null ? palette.gold : palette.coral }}>{systemStatus?.toUpperCase() ?? "—"}</div>
              </div>
              <div className="perf-system-item">
                <div className="perf-system-name">Market</div>
                <div className="perf-system-value" style={{ color: st?.market_open ? palette.green : st?.market_open === false ? palette.faint : palette.gold }}>{st?.market_open == null ? "—" : st.market_open ? "OPEN" : "CLOSED"}</div>
              </div>
              <div className="perf-system-item">
                <div className="perf-system-name">Kill switch</div>
                <div className="perf-system-value" style={{ color: killSwitch == null ? palette.gold : killSwitch ? palette.coral : palette.green }}>
                  {killSwitch == null ? "UNKNOWN" : killSwitch ? "TRIPPED" : "SAFE"}
                </div>
              </div>
              <div className="perf-system-item">
                <div className="perf-system-name">Positions</div>
                <div className="perf-system-value" style={{ color: palette.ink }}>{st?.position_count ?? "—"}</div>
              </div>
              <div className="perf-system-item">
                <div className="perf-system-name">Auto-trade</div>
                <div className="perf-system-value" style={{ color: st?.auto_trading ? palette.green : st?.auto_trading === false ? palette.gold : palette.faint }}>
                  {st?.auto_trading == null ? "—" : st.auto_trading ? "ON" : "OFF"}
                </div>
              </div>
              <div className="perf-system-item">
                <div className="perf-system-name">Vaulted</div>
                <div className="perf-system-value" style={{ color: "#e2c47d" }}>{vault.data?.total_vaulted_usd != null ? `$${Math.round(vault.data.total_vaulted_usd).toLocaleString()}` : "—"}</div>
              </div>
            </div>
          </article>
        </div>
      </section>

      <section className="perf-panel perf-vault" aria-label="Vault growth trend">
        <div className="perf-vault-head">
          <div className="perf-vault-title">
            <BarChart3 size={14} />
            <SectionLabel>Vault growth · 90-day trend</SectionLabel>
          </div>
          <div className="perf-vault-meta">
            {vaultHistory.data?.total_vaulted_usd != null && (
              <span>Total vaulted <strong className="perf-vault-total">${Math.round(vaultHistory.data.total_vaulted_usd).toLocaleString()}</strong></span>
            )}
            {snapshots.length > 0 && <span>{snapshots.length} data points</span>}
          </div>
        </div>
        <div className="perf-vault-chart">
          {vaultHistory.isLoading ? (
            <div className="perf-chart-empty">Loading vault history…</div>
          ) : snapshots.length === 0 ? (
            <div className="perf-chart-empty">
              {vaultHistory.data?.total_vaulted_usd
                ? `$${Math.round(vaultHistory.data.total_vaulted_usd).toLocaleString()} vaulted — historical breakdown accumulating`
                : "No vault history yet — profits accrue here after first sweep"}
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 5, right: 10, left: 4, bottom: 0 }}>
                <defs>
                  <linearGradient id="perfVaultFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#dfc477" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#dfc477" stopOpacity={0.01} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 5" stroke="rgba(229,237,219,.10)" vertical={false} />
                <XAxis dataKey="date" tick={{ fill: "rgba(220,231,213,.48)", fontSize: 9, fontFamily: "monospace" }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                <YAxis tick={{ fill: "rgba(220,231,213,.45)", fontSize: 9, fontFamily: "monospace" }} axisLine={false} tickLine={false} width={47} tickFormatter={(value) => value >= 1000 ? `$${(value / 1000).toFixed(0)}k` : `$${value}`} domain={[0, (max: number) => Math.ceil(max * 1.1)]} />
                <Tooltip content={<VaultTooltip />} />
                <Area type="monotone" dataKey="total" stroke="#dfc477" strokeWidth={2} fill="url(#perfVaultFill)" dot={false} activeDot={{ r: 3, fill: "#dfc477", stroke: "none" }} name="Cumulative" />
                <Area type="monotone" dataKey="daily" stroke="#a9d8ad" strokeWidth={1.25} fill="none" dot={false} activeDot={{ r: 2, fill: "#a9d8ad", stroke: "none" }} strokeDasharray="3 3" name="Daily" />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>
      </section>
    </main>
  );
}