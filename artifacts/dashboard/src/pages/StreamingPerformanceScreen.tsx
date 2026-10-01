import {
  useRiskMetrics,
  useJournal,
  useAttribution,
  useSentiment,
  useStatusSummary,
  useVault,
  useVaultHistory,
  useFleetEquity,
  useBotRegistry,
} from "@/hooks/use-trading";
import { Activity } from "lucide-react";
import { getBotIdentity } from "@/lib/bot-identity";
import { DDGBadge } from "@/components/DDGBadge";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  type TooltipProps,
} from "recharts";
import type { ValueType, NameType } from "recharts/types/component/DefaultTooltipContent";

/* ── palette ─────────────────────────────────────────────── */
const C = {
  bg:     "#102322",
  panel:  "rgba(18,39,36,0.82)",
  border: "rgba(219,239,221,0.15)",
  dim:    "rgba(223,233,220,0.4)",
  label:  "rgba(223,233,220,0.63)",
  text:   "#eff4e9",
  green:  "#a9d8ad",
  red:    "#ee9a8c",
  amber:  "#e2c47d",
  blue:   "#9cc8d2",
  violet: "#cfb9f3",
  cyan:   "#75cdb5",
  orange: "#e6bc85",
};

/* ── helpers ─────────────────────────────────────────────── */
function fmt(v: number | null | undefined, d = 2): string {
  if (v == null) return "—";
  return v.toFixed(d);
}
function fmtPct(v: number | null | undefined, d = 1): string {
  if (v == null) return "—";
  return `${v.toFixed(d)}%`;
}
function fmtMoney(v: number | null | undefined): string {
  if (v == null) return "—";
  const sign = v >= 0 ? "+" : "";
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `${sign}$${(v / 1_000_000).toFixed(2)}M`;
  if (abs >= 1000) return `${sign}$${(v / 1000).toFixed(1)}k`;
  return `${sign}$${v.toFixed(0)}`;
}
function pnlColor(v: number | null | undefined): string {
  if (v == null) return C.dim;
  return v >= 0 ? C.green : C.red;
}
function ratioColor(v: number | null | undefined, goodThreshold = 1): string {
  if (v == null) return C.dim;
  return v >= goodThreshold ? C.green : v >= 0 ? C.amber : C.red;
}

/* ── bot config ──────────────────────────────────────────── */
const BOT_META: Record<string, { icon: string; color: string; label: string }> = {
  "oracle":         { icon: getBotIdentity("oracle").icon,         color: "#a78bfa", label: getBotIdentity("oracle").displayName },
  "spy_qqq_trend":  { icon: getBotIdentity("spy_qqq_trend").icon,  color: C.cyan,    label: getBotIdentity("spy_qqq_trend").displayName },
  "jerome_macro":   { icon: getBotIdentity("jerome_macro").icon,   color: C.orange,  label: getBotIdentity("jerome_macro").displayName },
  // buck_futures retired May 2026 — removed from performance view
};

/* ── fear & greed helpers ────────────────────────────────── */
function fgColor(v: number | null | undefined) {
  if (v == null) return C.dim;
  if (v < 25) return C.red;
  if (v < 45) return C.orange;
  if (v < 55) return C.amber;
  if (v < 75) return C.green;
  return "#4ade80";
}
function fgLabel(v: number | null | undefined) {
  if (v == null) return "No data";
  if (v < 25) return "Extreme Fear";
  if (v < 45) return "Fear";
  if (v < 55) return "Neutral";
  if (v < 75) return "Greed";
  return "Extreme Greed";
}

/* ═══════════════════════════════════════════════════════════ */
export default function StreamingPerformanceScreen() {
  const risk    = useRiskMetrics();
  const journal = useJournal();
  const attr    = useAttribution();
  const sent    = useSentiment();
  const status  = useStatusSummary();
  const vaultData    = useVault();
  const vaultHistory = useVaultHistory(90);

  const rm  = risk.data;
  const j   = journal.data;
  const at  = attr.data;
  const sg  = sent.data;
  const st  = status.data;
  const fleetEqQuery = useFleetEquity();
  const fleetEq = fleetEqQuery.data;
  const registryQuery = useBotRegistry();
  const registry = registryQuery.data;

  const marketFG = sg?.market_fear_greed?.value;
  const regime   = st?.groq?.regime ?? "—";

  /* Bot matrix: only the canonical active Alpaca ETF fleet. */
  const registryBots = (registry?.bots ?? []).filter((bot) =>
    ["oracle", "spy_qqq_trend", "jerome_macro"].includes(bot.id),
  );

  /* Fleet equity lookup by bot ID */
  const fleetEqByBotId: Record<string, { equity: number; pnl: number; positions: number } | undefined> = fleetEq ? {
    oracle:         fleetEq.oracle,
    spy_qqq_trend:  fleetEq.spy_qqq_trend,
    jerome_macro:   fleetEq.jerome_macro,
  } : {};

  /* Full fleet totals from single source of truth (fleet_equity API) */
  const fleetEquity = fleetEq?.fleet_total?.equity ?? null;

  /* Fleet win rate comes from the canonical fleet equity source. */
  const fleetTrades  = j?.summary?.total ?? null;
  const fleetWins    = j?.summary?.wins  ?? null;
  const fleetWinRate = fleetEq?.fleet_total?.win_rate != null ? fleetEq.fleet_total.win_rate * 100 : null;

  /* Distinct metric: attribution's all-time per-trade rate, server-computed. */
  const attributionWinRate = at?.overall.win_rate ?? null;
  const sourceError = risk.isError || journal.isError || attr.isError || sent.isError || status.isError || vaultData.isError || vaultHistory.isError || fleetEqQuery.isError || registryQuery.isError;
  const hasSnapshot = Boolean(rm || j || at || sg || st || fleetEq || vaultData.data);
  const sourceLoading = risk.isLoading || journal.isLoading || attr.isLoading || sent.isLoading || status.isLoading || vaultData.isLoading || vaultHistory.isLoading || fleetEqQuery.isLoading || registryQuery.isLoading;
  const sourceState = hasSnapshot
    ? sourceError ? "Partial source error" : "API snapshot"
    : sourceLoading ? "Loading API data"
    : sourceError ? "API unavailable"
    : "No API snapshot";

  /* ── sub-components ──────────────────────────────────────── */

  function RiskCard({
    label, value, sub, accent, note,
  }: { label: string; value: string; sub?: string; accent: string; note?: string }) {
    return (
      <div data-testid="performance-risk-card" style={{
        flex: 1,
        background: C.panel,
        border: `1px solid ${C.border}`,
        borderRadius: 12,
        padding: "14px 18px",
        display: "flex",
        flexDirection: "column",
        gap: 4,
        backdropFilter: "blur(14px)",
        minWidth: 0,
      }}>
        <span style={{ fontSize: 10, fontFamily: "monospace", letterSpacing: "0.14em", textTransform: "uppercase", color: C.dim }}>
          {label}
        </span>
        <span style={{ fontSize: 32, fontFamily: "monospace", fontWeight: 900, color: accent, lineHeight: 1, letterSpacing: "-0.03em" }}>
          {value}
        </span>
        {sub && (
          <span style={{ fontSize: 10, fontFamily: "monospace", color: C.label, marginTop: 2 }}>{sub}</span>
        )}
        {note && (
          <span style={{ fontSize: 9, fontFamily: "monospace", color: C.dim, fontStyle: "italic" }}>{note}</span>
        )}
      </div>
    );
  }

  return (
    <div className="stream-screen stream-screen-performance" data-testid="performance-screen" style={{
      width: "100%",
      height: "100%",
      background: `linear-gradient(90deg, rgba(8,21,23,.91), rgba(9,23,23,.79) 53%, rgba(10,25,24,.75)), linear-gradient(180deg, rgba(12,25,25,.12), rgba(8,19,21,.77) 78%, #0a1a1b), url("/streaming-forest-atmosphere.jpg") center 43% / cover`,
      overflow: "hidden",
      display: "flex",
      flexDirection: "column",
      gap: 8,
      padding: "10px 14px 10px",
      boxSizing: "border-box",
      position: "relative",
    }}>
      <style>{`
        .stream-screen-performance[data-testid="performance-screen"] { color:${C.text} !important; background:linear-gradient(90deg,rgba(8,21,23,.91),rgba(9,23,23,.79) 53%,rgba(10,25,24,.75)),linear-gradient(180deg,rgba(12,25,25,.12),rgba(8,19,21,.77) 78%,#0a1a1b),url("/streaming-forest-atmosphere.jpg") center 43% / cover !important; font-family:"Geist","Aptos",sans-serif !important; }
        .stream-screen-performance > header { min-height: 43px; display:flex; align-items:center; justify-content:space-between; gap:16px; border-bottom:1px solid rgba(219,239,221,.12); padding:0 3px 8px; }
        .stream-screen-performance .perf-brand { display:flex; align-items:center; gap:11px; min-width:0; }
        .stream-screen-performance .perf-mark { width:32px;height:32px;display:grid;place-items:center;border:1px solid rgba(190,222,196,.3);border-radius:10px;background:rgba(201,231,205,.08);color:#c1e3bb; }
        .stream-screen-performance .perf-brand small { display:block;color:rgba(208,225,207,.55);font:600 8px/1.2 "Geist Mono",monospace;letter-spacing:.16em; }
        .stream-screen-performance .perf-brand h1 { margin:3px 0 0;color:#f2f3e8;font:600 18px/1 "Geist",sans-serif;letter-spacing:-.04em; }
        .stream-screen-performance .perf-meta { display:flex;align-items:center;gap:7px;flex-wrap:wrap;justify-content:flex-end; }
        .stream-screen-performance .perf-pill { display:flex;align-items:center;gap:6px;padding:6px 9px;border:1px solid rgba(199,221,201,.16);border-radius:99px;background:rgba(12,31,29,.58);color:rgba(232,239,225,.8);font:600 8px "Geist Mono",monospace;letter-spacing:.06em;text-transform:uppercase;white-space:nowrap; }
        .stream-screen-performance .perf-pill-dot { width:5px;height:5px;border-radius:50%;background:${sourceError ? "#e2c47d" : hasSnapshot ? "#a9d8ad" : "#9cc8d2"}; }
        .stream-screen-performance [data-testid="performance-risk-card"] { border-color:rgba(214,232,211,.16) !important; border-radius:12px !important; background:linear-gradient(145deg,rgba(27,48,45,.72),rgba(11,27,27,.74)) !important; box-shadow:inset 0 1px rgba(255,255,255,.07),0 10px 25px rgba(0,0,0,.12); }
        .stream-screen-performance [data-testid="performance-panel"] { border-color:rgba(219,239,221,.15) !important; border-radius:14px !important; background:linear-gradient(145deg,rgba(22,42,40,.79),rgba(11,27,28,.80)) !important; box-shadow:inset 0 1px rgba(255,255,255,.08),0 14px 35px rgba(0,0,0,.14); }
        @media(max-width:900px) {
          .stream-screen-performance { height:100% !important; min-height:0 !important; overflow-x:hidden !important; overflow-y:auto !important; }
          .stream-screen-performance > [data-testid="performance-risk-metrics"] { display:grid !important; grid-template-columns:repeat(3,minmax(0,1fr)); }
          .stream-screen-performance > [data-testid="performance-overview"] { flex:0 0 auto !important; grid-template-columns:1fr !important; grid-template-rows:minmax(320px,auto) minmax(480px,auto) !important; min-height:800px !important; }
          .stream-screen-performance > [data-testid="performance-overview"] > [data-testid="performance-panel"] { min-height:320px !important; }
          .stream-screen-performance > [data-testid="performance-overview"] > div:nth-child(2) { min-height:480px !important; }
          .stream-screen-performance > header { align-items:flex-start; }
        }
        @media(max-width:700px) {
          .stream-screen-performance { padding:12px 12px 96px !important; }
          .stream-screen-performance > [data-testid="performance-risk-metrics"] { grid-template-columns:repeat(2,minmax(0,1fr)); }
          .stream-screen-performance [data-testid="performance-trade-stats-grid"] { grid-template-columns:repeat(2,minmax(0,1fr)) !important; }
          .stream-screen-performance .perf-meta .perf-pill:nth-child(2) { display:none; }
        }
      `}</style>

      <header data-testid="performance-header">
        <div className="perf-brand">
          <div className="perf-mark"><Activity size={16} /></div>
          <div><small>STREAMING / FLEET</small><h1>Performance</h1></div>
        </div>
        <div className="perf-meta">
          <div className="perf-pill"><span className="perf-pill-dot" />{sourceState}</div>
          <div className="perf-pill">{st?.market_open == null ? "Market unknown" : st.market_open ? "Market open" : "Market closed"}</div>
          <div className="perf-pill">90 day view</div>
        </div>
      </header>

      {/* ══ ROW 1: RISK RATIO CARDS ══════════════════════════════ */}
      <div data-testid="performance-risk-metrics" style={{ display: "flex", gap: 8, flexShrink: 0 }}>
        <RiskCard
          label="Sharpe Ratio"
          value={fmt(rm?.sharpe_ratio)}
          sub={rm?.sharpe_ratio != null ? (rm.sharpe_ratio >= 1 ? "✓ Good risk-adj return" : rm.sharpe_ratio >= 0 ? "Marginal" : "⚠ Below zero") : undefined}
          note={rm?.message && rm.sharpe_ratio == null ? rm.message : undefined}
          accent={ratioColor(rm?.sharpe_ratio)}
        />
        <RiskCard
          label="Sortino Ratio"
          value={fmt(rm?.sortino_ratio)}
          sub="Downside-adjusted return"
          accent={ratioColor(rm?.sortino_ratio)}
        />
        <RiskCard
          label="Max Drawdown"
          value={rm?.max_drawdown_pct != null ? `-${fmt(rm.max_drawdown_pct, 1)}%` : "—"}
          sub="Peak-to-trough loss"
          accent={rm?.max_drawdown_pct != null ? (rm.max_drawdown_pct < 5 ? C.green : rm.max_drawdown_pct < 15 ? C.amber : C.red) : C.dim}
        />
        <RiskCard
          label="Calmar Ratio"
          value={fmt(rm?.calmar_ratio)}
          sub="Ann. return ÷ max DD"
          accent={ratioColor(rm?.calmar_ratio, 0.5)}
        />
        <RiskCard
          label="Ann. Volatility"
          value={fmtPct(rm?.volatility_annual_pct)}
          sub="Annualised std deviation"
          accent={rm?.volatility_annual_pct != null ? (rm.volatility_annual_pct < 20 ? C.green : rm.volatility_annual_pct < 40 ? C.amber : C.red) : C.dim}
        />
        <RiskCard
          label="Ann. Return"
          value={fmtPct(rm?.annualised_return_pct)}
          sub={rm?.insufficient_data ? `Need 30+ days (${rm.data_points != null ? rm.data_points : "unavailable"} pts so far)` : rm?.period_days ? `${rm.period_days}d window · ${rm.data_points != null ? rm.data_points : "unavailable"} pts` : "Awaiting data"}
          accent={rm?.annualised_return_pct != null ? (rm.annualised_return_pct >= 0 ? C.green : C.red) : C.dim}
        />
      </div>

      {/* ══ ROW 2: MAIN CONTENT ══════════════════════════════════ */}
      <div data-testid="performance-overview" style={{ display: "grid", gridTemplateColumns: "1.1fr 1fr", gap: 8, flex: 1, minHeight: 0 }}>

        {/* ── LEFT: BOT PERFORMANCE MATRIX ─────────────────────── */}
        <div data-testid="performance-panel" style={{
          background: C.panel,
          border: `1px solid ${C.border}`,
          borderRadius: 12,
          backdropFilter: "blur(14px)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          minHeight: 0,
        }}>
          {/* header */}
          <div style={{ padding: "12px 18px 8px", borderBottom: `1px solid ${C.border}`, flexShrink: 0 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: 10, fontFamily: "monospace", letterSpacing: "0.14em", textTransform: "uppercase", color: C.dim }}>
                ◈ Bot Performance Matrix
              </span>
              <div style={{ display: "flex", gap: 20 }}>
                {[
                  { label: "Fleet Equity", value: fleetEquity != null ? `$${(fleetEquity / 1000).toFixed(0)}k` : "—", color: C.cyan },
                  { label: "Total Trades", value: fleetTrades != null ? String(fleetTrades) : "—", color: C.text },
                  { label: "Win Rate", value: fleetWinRate != null ? fmtPct(fleetWinRate, 1) : "—", color: fleetWinRate != null ? (fleetWinRate >= 50 ? C.green : C.red) : C.dim },
                ].map(({ label, value, color }) => (
                  <div key={label} style={{ textAlign: "right" }}>
                    <div style={{ fontSize: 8, fontFamily: "monospace", color: C.dim, letterSpacing: "0.1em", textTransform: "uppercase" }}>{label}</div>
                    <div style={{ fontSize: 18, fontFamily: "monospace", fontWeight: 900, color }}>{value}</div>
                  </div>
                ))}
              </div>
            </div>
            {/* col headers */}
            <div style={{ display: "grid", gridTemplateColumns: "32px 1fr 72px 52px 80px", gap: "0 8px", marginTop: 10, paddingBottom: 4 }}>
              {["", "BOT", "WIN RATE", "TRADES", "P&L"].map((h, i) => (
                <span key={i} style={{ fontSize: 8, fontFamily: "monospace", color: C.dim, textAlign: i >= 2 ? "right" : "left", letterSpacing: "0.12em", textTransform: "uppercase" }}>{h}</span>
              ))}
            </div>
          </div>

          {/* bot rows */}
          <div style={{ flex: 1, overflowY: "auto", padding: "6px 0" }}>
            {registryBots.length > 0 ? registryBots.map((bot) => {
              const meta = BOT_META[bot.id] ?? { icon: "🤖", color: C.label, label: bot.id };
              const botEq = fleetEqByBotId[bot.id];
              const equity = botEq?.equity ?? null;
              const pnl    = botEq?.pnl ?? null;
              return (
                <div key={bot.id} style={{
                  display: "grid",
                  gridTemplateColumns: "32px 1fr 72px 52px 80px",
                  gap: "0 8px",
                  alignItems: "center",
                  padding: "10px 18px",
                  borderBottom: `1px solid rgba(255,255,255,0.03)`,
                }}>
                  <span style={{ fontSize: 18 }}>{meta.icon}</span>
                  <div>
                    <div style={{ fontSize: 14, fontFamily: "monospace", fontWeight: 800, color: meta.color, letterSpacing: "0.04em" }}>
                      {meta.label}
                    </div>
                    <div style={{ fontSize: 9, fontFamily: "monospace", color: C.dim, marginTop: 2 }}>
                      {equity != null ? `$${(equity / 1000).toFixed(1)}k equity` : "— equity"}
                    </div>
                  </div>
                  {/* win rate — no per-bot breakdown available; shown at fleet level */}
                  <div style={{ textAlign: "right" }}>
                    <div style={{ fontSize: 16, fontFamily: "monospace", fontWeight: 900, color: C.dim }}>—</div>
                    <div style={{ height: 3, background: "rgba(255,255,255,0.06)", borderRadius: 2, marginTop: 3 }} />
                  </div>
                  <div style={{ fontSize: 14, fontFamily: "monospace", color: C.dim, textAlign: "right" }}>—</div>
                  <div style={{ fontSize: 18, fontFamily: "monospace", fontWeight: 900, color: pnlColor(pnl), textAlign: "right" }}>
                    {fmtMoney(pnl)}
                  </div>
                </div>
              );
            }) : (
              <div style={{ padding: 24, textAlign: "center", color: C.dim, fontSize: 12, fontFamily: "monospace" }}>
                {registryQuery.isLoading
                  ? "Loading fleet data…"
                  : registryQuery.isError
                    ? "Fleet registry unavailable"
                    : "No active bots are registered."}
              </div>
            )}
          </div>
        </div>

        {/* ── RIGHT: STATS + SENTIMENT + STATUS ────────────────── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8, minHeight: 0 }}>

          {/* Trade stats — big numbers */}
          <div data-testid="performance-panel" style={{
            background: C.panel,
            border: `1px solid ${C.border}`,
            borderRadius: 12,
            padding: "14px 18px",
            backdropFilter: "blur(14px)",
            flexShrink: 0,
          }}>
            <div style={{ fontSize: 10, fontFamily: "monospace", letterSpacing: "0.14em", textTransform: "uppercase", color: C.dim, marginBottom: 12 }}>
              ◈ Fleet Trade Statistics
            </div>
            <div data-testid="performance-trade-stats-grid" style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
              {[
                { label: "Total Trades", value: fleetTrades != null ? String(fleetTrades) : "—", color: C.text },
                { label: "All-time per-trade win rate (attribution)", value: attributionWinRate != null ? `${attributionWinRate.toFixed(0)}%` : "—", color: attributionWinRate != null ? (attributionWinRate >= 50 ? C.green : C.red) : C.dim },
                { label: "Total Wins",   value: fleetWins != null ? String(fleetWins) : "—", color: C.green },
                { label: "Avg P&L",      value: at?.overall.avg_pnl_pct != null ? `${at.overall.avg_pnl_pct > 0 ? "+" : ""}${at.overall.avg_pnl_pct.toFixed(1)}%` : (j?.summary.avg_pnl != null ? `${j.summary.avg_pnl > 0 ? "+" : ""}${j.summary.avg_pnl.toFixed(1)}%` : "—"), color: pnlColor(at?.overall.avg_pnl_pct ?? j?.summary.avg_pnl) },
              ].map(({ label, value, color }) => (
                <div key={label}>
                  <div style={{ fontSize: 9, fontFamily: "monospace", color: C.dim, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 4 }}>{label}</div>
                  <div style={{ fontSize: 26, fontFamily: "monospace", fontWeight: 900, color, lineHeight: 1 }}>{value}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Sentiment */}
          <div data-testid="performance-panel" style={{
            background: C.panel,
            border: `1px solid ${C.border}`,
            borderRadius: 12,
            padding: "14px 18px",
            backdropFilter: "blur(14px)",
            flexShrink: 0,
          }}>
            <div style={{ fontSize: 10, fontFamily: "monospace", letterSpacing: "0.14em", textTransform: "uppercase", color: C.dim, marginBottom: 12 }}>
              ◈ Market Sentiment
            </div>
            {[
              { label: "Market Fear & Greed",  value: marketFG },
            ].map(({ label, value }) => (
              <div key={label} style={{ marginBottom: 10 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 5 }}>
                  <span style={{ fontSize: 11, fontFamily: "monospace", color: C.label }}>{label}</span>
                  <span style={{ fontSize: 20, fontFamily: "monospace", fontWeight: 900, color: fgColor(value) }}>
                    {value != null ? value : "—"}
                    <span style={{ fontSize: 11, fontWeight: 400, marginLeft: 8, color: fgColor(value) }}>
                      {fgLabel(value)}
                    </span>
                  </span>
                </div>
                <div style={{ height: 8, background: "rgba(255,255,255,0.05)", borderRadius: 4, overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${value ?? 0}%`, background: `linear-gradient(90deg, ${C.red}, ${C.amber} 50%, ${C.green})`, borderRadius: 4 }} />
                </div>
              </div>
            ))}
          </div>

          {/* System Status */}
          <div data-testid="performance-panel" style={{
            background: C.panel,
            border: `1px solid ${C.border}`,
            borderRadius: 12,
            padding: "14px 18px",
            backdropFilter: "blur(14px)",
            flex: 1,
            minHeight: 0,
          }}>
            <div style={{ fontSize: 10, fontFamily: "monospace", letterSpacing: "0.14em", textTransform: "uppercase", color: C.dim, marginBottom: 12 }}>
              ◈ System Status
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px 20px" }}>
              {[
                { label: "Regime",      value: regime,                                           color: regime === "Bull" ? C.green : regime === "Bear" ? C.red : C.amber },
                { label: "System",      value: (st?.system_health.system_status ?? "—").toUpperCase(), color: st?.system_health.system_status === "online" ? C.green : C.red },
                { label: "Market",      value: st?.market_open ? "OPEN" : "CLOSED",               color: st?.market_open ? C.green : C.dim },
                { label: "Kill Switch", value: st?.kill_switch_tripped == null ? "UNKNOWN" : st.kill_switch_tripped ? "TRIPPED" : "SAFE", color: st?.kill_switch_tripped == null ? C.amber : st.kill_switch_tripped ? C.red : C.green },
                { label: "Positions",   value: String(st?.position_count ?? "—"),                 color: C.text },
                { label: "Auto-Trade",  value: st?.auto_trading ? "ON" : "OFF",                   color: st?.auto_trading ? C.green : C.amber },
              ].map(({ label, value, color }) => (
                <div key={label}>
                  <div style={{ fontSize: 9, fontFamily: "monospace", color: C.dim, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 3 }}>{label}</div>
                  <div style={{ fontSize: 20, fontFamily: "monospace", fontWeight: 900, color, textTransform: "uppercase" }}>{value}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ══ ROW 3: VAULT GROWTH CHART ════════════════════════════ */}
      {(() => {
        const snapshots = vaultHistory.data?.snapshots ?? [];
        const hasData   = snapshots.length >= 1;
        const chartData = snapshots.map((s) => ({
          date:  s.date.slice(5),
          total: s.cumulative_vaulted,
          daily: s.daily_vaulted,
        }));

        function vaultTooltip({ active, payload, label }: TooltipProps<ValueType, NameType>) {
          if (!active || !payload?.length) return null;
          const cumulative = typeof payload[0]?.value === "number" ? payload[0].value : null;
          const daily      = typeof payload[1]?.value === "number" ? payload[1].value : null;
          return (
            <div style={{
              background: "rgba(2,6,23,0.96)",
              border: "1px solid rgba(251,191,36,0.25)",
              borderRadius: 8,
              padding: "8px 12px",
              fontFamily: "monospace",
              fontSize: 11,
            }}>
              <div style={{ color: C.dim, marginBottom: 4 }}>{String(label ?? "")}</div>
              {cumulative != null && (
                <div style={{ color: "#fbbf24", fontWeight: 900 }}>
                  Total: ${cumulative.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                </div>
              )}
              {daily != null && (
                <div style={{ color: C.green, marginTop: 2 }}>
                  +${daily.toLocaleString(undefined, { maximumFractionDigits: 0 })} today
                </div>
              )}
            </div>
          );
        }

        return (
          <div data-testid="performance-panel" style={{
            background: C.panel,
            border: `1px solid ${C.border}`,
            borderRadius: 12,
            backdropFilter: "blur(14px)",
            flexShrink: 0,
            height: 130,
            padding: "10px 18px 8px",
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexShrink: 0 }}>
              <span style={{ fontSize: 10, fontFamily: "monospace", letterSpacing: "0.14em", textTransform: "uppercase", color: C.dim }}>
                ◈ Vault Growth — 90-Day Trend
              </span>
              <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
                {vaultHistory.data?.total_vaulted_usd != null && (
                  <span style={{ fontSize: 11, fontFamily: "monospace" }}>
                    <span style={{ color: C.dim }}>Total Vaulted: </span>
                    <span style={{ color: "#fbbf24", fontWeight: 900 }}>
                      ${Math.round(vaultHistory.data.total_vaulted_usd).toLocaleString()}
                    </span>
                  </span>
                )}
                {hasData && (
                  <span style={{ fontSize: 10, fontFamily: "monospace", color: C.dim }}>
                    {snapshots.length} data points
                  </span>
                )}
              </div>
            </div>

            <div style={{ flex: 1, minHeight: 0 }}>
              {vaultHistory.isLoading ? (
                <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: C.dim, fontSize: 11, fontFamily: "monospace" }}>
                  Loading vault history…
                </div>
              ) : !hasData ? (
                <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: C.dim, fontSize: 11, fontFamily: "monospace" }}>
                  {vaultHistory.data?.total_vaulted_usd
                    ? `$${Math.round(vaultHistory.data.total_vaulted_usd).toLocaleString()} vaulted — historical breakdown accumulating`
                    : "No vault history yet — profits accrue here after first sweep"}
                </div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData} margin={{ top: 2, right: 4, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="vaultGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%"  stopColor="#fbbf24" stopOpacity={0.25} />
                        <stop offset="95%" stopColor="#fbbf24" stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid
                      strokeDasharray="3 3"
                      stroke="rgba(255,255,255,0.04)"
                      vertical={false}
                    />
                    <XAxis
                      dataKey="date"
                      tick={{ fill: "rgba(148,163,184,0.5)", fontSize: 9, fontFamily: "monospace" }}
                      axisLine={false}
                      tickLine={false}
                      interval="preserveStartEnd"
                    />
                    <YAxis
                      tick={{ fill: "rgba(148,163,184,0.5)", fontSize: 9, fontFamily: "monospace" }}
                      axisLine={false}
                      tickLine={false}
                      width={48}
                      tickFormatter={(v) => v >= 1000 ? `$${(v / 1000).toFixed(0)}k` : `$${v}`}
                      domain={[0, (dataMax: number) => Math.ceil(dataMax * 1.1)]}
                    />
                    <Tooltip content={vaultTooltip} />
                    <Area
                      type="monotone"
                      dataKey="total"
                      stroke="#fbbf24"
                      strokeWidth={2}
                      fill="url(#vaultGrad)"
                      dot={false}
                      activeDot={{ r: 3, fill: "#fbbf24", stroke: "none" }}
                      name="Cumulative"
                    />
                    <Area
                      type="monotone"
                      dataKey="daily"
                      stroke={C.green}
                      strokeWidth={1}
                      fill="none"
                      dot={false}
                      activeDot={{ r: 2, fill: C.green, stroke: "none" }}
                      strokeDasharray="3 2"
                      name="Daily"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>
        );
      })()}

      <DDGBadge style={{ position: "absolute", bottom: 10, left: 10, zIndex: 50 }} />
    </div>
  );
}
