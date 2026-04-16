import {
  useRiskMetrics,
  useJournal,
  useAttribution,
  useKrakenFleetSummary,
  useSentiment,
  useStatusSummary,
  useLatestAllocation,
  useAuditorPerformance,
} from "@/hooks/use-trading";
import { DDGBadge } from "@/components/DDGBadge";

const C = {
  bg:      "#020617",
  panel:   "rgba(15,23,42,0.85)",
  border:  "rgba(255,255,255,0.07)",
  dim:     "rgba(148,163,184,0.45)",
  label:   "rgba(148,163,184,0.65)",
  text:    "rgba(226,232,240,0.88)",
  green:   "#34d399",
  red:     "#f87171",
  amber:   "#fbbf24",
  blue:    "#60a5fa",
  violet:  "#a78bfa",
  cyan:    "#22d3ee",
  orange:  "#fb923c",
};

function fmt(v: number | null | undefined, decimals = 2, suffix = ""): string {
  if (v == null) return "—";
  return `${v.toFixed(decimals)}${suffix}`;
}
function fmtPct(v: number | null | undefined): string { return fmt(v, 1, "%"); }
function fmtK(v: number | null | undefined): string {
  if (v == null) return "—";
  if (Math.abs(v) >= 1000) return `${(v / 1000).toFixed(1)}k`;
  return v.toFixed(0);
}
function fmtMoney(v: number | null | undefined): string {
  if (v == null) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}$${fmtK(v)}`;
}
function color(v: number | null | undefined, neutral = 0): string {
  if (v == null) return C.dim;
  return v > neutral ? C.green : v < neutral ? C.red : C.dim;
}

interface MetricCardProps {
  label: string;
  value: string;
  sub?: string;
  accent?: string;
  glow?: string;
}
function MetricCard({ label, value, sub, accent = C.cyan, glow }: MetricCardProps) {
  return (
    <div
      style={{
        background: C.panel,
        border: `1px solid ${C.border}`,
        borderRadius: 10,
        padding: "10px 14px",
        display: "flex",
        flexDirection: "column",
        gap: 3,
        backdropFilter: "blur(12px)",
        boxShadow: glow ? `0 0 16px ${glow}` : undefined,
        flex: 1,
        minWidth: 0,
      }}
    >
      <span style={{ fontSize: 8, fontFamily: "monospace", letterSpacing: "0.15em", textTransform: "uppercase", color: C.dim }}>
        {label}
      </span>
      <span style={{ fontSize: 22, fontFamily: "monospace", fontWeight: 800, color: accent, lineHeight: 1.1, letterSpacing: "-0.02em" }}>
        {value}
      </span>
      {sub && (
        <span style={{ fontSize: 9, fontFamily: "monospace", color: C.label }}>
          {sub}
        </span>
      )}
    </div>
  );
}

interface BotRowProps {
  name: string;
  icon: string;
  equity: number;
  startCap: number;
  trades: number;
  wins: number;
  pnlUsd: number;
  color: string;
}
function BotRow({ name, icon, equity, startCap, trades, wins, pnlUsd, color: accentColor }: BotRowProps) {
  const winRate = trades > 0 ? (wins / trades) * 100 : null;
  const pnl = equity - startCap;
  const pnlPct = startCap > 0 ? (pnl / startCap) * 100 : null;
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "22px 1fr 48px 40px 56px",
        gap: "0 6px",
        alignItems: "center",
        padding: "4px 8px",
        borderRadius: 6,
        background: "rgba(255,255,255,0.02)",
        borderBottom: `1px solid ${C.border}`,
      }}
    >
      <span style={{ fontSize: 12 }}>{icon}</span>
      <span style={{ fontSize: 9, fontFamily: "monospace", fontWeight: 700, color: accentColor, letterSpacing: "0.05em", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {name}
      </span>
      <span style={{ fontSize: 9, fontFamily: "monospace", textAlign: "right", color: winRate != null ? (winRate >= 50 ? C.green : C.red) : C.dim }}>
        {winRate != null ? `${winRate.toFixed(0)}%` : "—"}
      </span>
      <span style={{ fontSize: 9, fontFamily: "monospace", textAlign: "right", color: C.label }}>
        {trades}
      </span>
      <span style={{ fontSize: 9, fontFamily: "monospace", textAlign: "right", color: pnl >= 0 ? C.green : C.red, fontWeight: 700 }}>
        {fmtMoney(pnl)}
      </span>
    </div>
  );
}

const BOT_META: Record<string, { icon: string; color: string; startCap: number }> = {
  "davy-jones":     { icon: "⚓", color: "#22d3ee",  startCap: 100_000 },
  "blackbeard":     { icon: "☠️", color: "#f87171",  startCap: 100_000 },
  "calypso":        { icon: "🌊", color: "#818cf8",  startCap: 100_000 },
  "poseidon":       { icon: "🔱", color: "#60a5fa",  startCap: 100_000 },
  "kraken-current": { icon: "🐙", color: "#34d399",  startCap: 100_000 },
};

export default function StreamingPerformanceScreen() {
  const risk      = useRiskMetrics();
  const journal   = useJournal();
  const attr      = useAttribution();
  const fleet     = useKrakenFleetSummary();
  const sentiment = useSentiment();
  const status    = useStatusSummary();
  const alloc     = useLatestAllocation();
  const audPerf   = useAuditorPerformance();

  const rm   = risk.data;
  const j    = journal.data;
  const at   = attr.data;
  const fl   = fleet.data;
  const sent = sentiment.data;
  const st   = status.data;
  const al   = alloc.data;
  const ap   = audPerf.data;

  const regime = st?.groq?.regime ?? "—";
  const cryptoFG = sent?.crypto_fear_greed?.value;
  const marketFG = sent?.market_fear_greed?.value;

  function fgColor(v: number | null | undefined) {
    if (v == null) return C.dim;
    if (v < 25) return C.red;
    if (v < 45) return C.orange;
    if (v < 55) return C.amber;
    if (v < 75) return C.green;
    return "#4ade80";
  }
  function fgLabel(v: number | null | undefined) {
    if (v == null) return "—";
    if (v < 25) return "Extreme Fear";
    if (v < 45) return "Fear";
    if (v < 55) return "Neutral";
    if (v < 75) return "Greed";
    return "Extreme Greed";
  }

  const fleetPnL = (() => {
    let total = 0;
    if (fl?.bots) {
      for (const b of fl.bots) {
        total += (b.equity_usd ?? 0) - b.starting_balance_usd;
      }
    }
    return total;
  })();

  const assetClasses = at?.asset_class_attribution ? Object.entries(at.asset_class_attribution) : [];
  const allSlots = al?.allocation ?? [];

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        background: `radial-gradient(ellipse at 20% 0%, rgba(6,18,50,1) 0%, ${C.bg} 70%)`,
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: "10px 14px 10px",
        boxSizing: "border-box",
        position: "relative",
      }}
    >
      {/* ── HEADER ── */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 11, fontFamily: "monospace", fontWeight: 900, letterSpacing: "0.25em", textTransform: "uppercase", color: C.cyan }}>
            ◈ RAW PERFORMANCE
          </span>
          <span style={{ fontSize: 9, fontFamily: "monospace", color: C.dim, letterSpacing: "0.1em" }}>
            FLEET · 8 BOTS · $800K CAPITAL
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <span style={{ fontSize: 9, fontFamily: "monospace", color: C.dim }}>
            REGIME: <span style={{ color: regime === "Bull" ? C.green : regime === "Bear" ? C.red : C.amber, fontWeight: 700 }}>{regime.toUpperCase()}</span>
          </span>
          <span style={{ fontSize: 9, fontFamily: "monospace", color: fmtMoney(fleetPnL).startsWith("+") ? C.green : C.red, fontWeight: 700 }}>
            FLEET P&L: {fmtMoney(fleetPnL)}
          </span>
        </div>
      </div>

      {/* ── ROW 1: RISK RATIOS ── */}
      <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
        <MetricCard
          label="Sharpe Ratio"
          value={fmt(rm?.sharpe_ratio, 2)}
          sub={rm?.sharpe_ratio != null ? (rm.sharpe_ratio >= 1 ? "✓ Good" : rm.sharpe_ratio >= 0 ? "Marginal" : "⚠ Negative") : "insufficient data"}
          accent={rm?.sharpe_ratio != null ? (rm.sharpe_ratio >= 1 ? C.green : rm.sharpe_ratio >= 0 ? C.amber : C.red) : C.dim}
          glow={rm?.sharpe_ratio != null && rm.sharpe_ratio >= 1 ? "rgba(52,211,153,0.15)" : undefined}
        />
        <MetricCard
          label="Sortino Ratio"
          value={fmt(rm?.sortino_ratio, 2)}
          sub="downside-adj return"
          accent={rm?.sortino_ratio != null ? (rm.sortino_ratio >= 1 ? C.green : rm.sortino_ratio >= 0 ? C.amber : C.red) : C.dim}
        />
        <MetricCard
          label="Max Drawdown"
          value={rm?.max_drawdown_pct != null ? `-${fmt(rm.max_drawdown_pct, 1)}%` : "—"}
          sub="peak-to-trough"
          accent={rm?.max_drawdown_pct != null ? (rm.max_drawdown_pct < 5 ? C.green : rm.max_drawdown_pct < 15 ? C.amber : C.red) : C.dim}
        />
        <MetricCard
          label="Calmar Ratio"
          value={fmt(rm?.calmar_ratio, 2)}
          sub="ann.return / max DD"
          accent={rm?.calmar_ratio != null ? (rm.calmar_ratio >= 0.5 ? C.green : rm.calmar_ratio >= 0 ? C.amber : C.red) : C.dim}
        />
        <MetricCard
          label="Annual Volatility"
          value={fmtPct(rm?.volatility_annual_pct)}
          sub="annualised std dev"
          accent={rm?.volatility_annual_pct != null ? (rm.volatility_annual_pct < 20 ? C.green : rm.volatility_annual_pct < 40 ? C.amber : C.red) : C.dim}
        />
        <MetricCard
          label="Ann. Return"
          value={fmtPct(rm?.annualised_return_pct)}
          sub={`${rm?.period_days ?? 0} day window`}
          accent={rm?.annualised_return_pct != null ? (rm.annualised_return_pct >= 0 ? C.green : C.red) : C.dim}
          glow={rm?.annualised_return_pct != null && rm.annualised_return_pct > 0 ? "rgba(52,211,153,0.1)" : undefined}
        />
      </div>

      {/* ── ROW 2: THREE COLUMNS ── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1.4fr 1fr", gap: 8, flex: 1, minHeight: 0 }}>

        {/* ── LEFT: TRADE STATS + ASSET ATTRIBUTION ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8, minHeight: 0 }}>

          {/* Trade stats panel */}
          <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "10px 12px", backdropFilter: "blur(12px)", flexShrink: 0 }}>
            <div style={{ fontSize: 8, fontFamily: "monospace", letterSpacing: "0.15em", textTransform: "uppercase", color: C.dim, marginBottom: 8 }}>
              ◈ Trade Statistics
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 12px" }}>
              {[
                { label: "Total Trades",  value: j?.summary.total != null ? String(j.summary.total) : "—",      accent: C.text },
                { label: "Win Rate",      value: at?.overall.win_rate != null ? fmtPct(at.overall.win_rate * 100) : (j?.summary.wins != null && j.summary.total ? fmtPct((j.summary.wins / j.summary.total) * 100) : "—"), accent: at?.overall.win_rate != null ? color(at.overall.win_rate - 0.5) : C.dim },
                { label: "Wins",          value: j?.summary.wins != null ? String(j.summary.wins) : "—",         accent: C.green },
                { label: "Losses",        value: j?.summary.losses != null ? String(j.summary.losses) : "—",     accent: C.red },
                { label: "Avg P&L",       value: j?.summary.avg_pnl != null ? `${j.summary.avg_pnl > 0 ? "+" : ""}${j.summary.avg_pnl.toFixed(1)}%` : "—", accent: color(j?.summary.avg_pnl) },
                { label: "Best Trade",    value: at?.overall.avg_pnl_pct != null ? `${at.overall.avg_pnl_pct > 0 ? "+" : ""}${at.overall.avg_pnl_pct.toFixed(1)}%` : "—", accent: C.green },
              ].map(({ label, value, accent }) => (
                <div key={label}>
                  <div style={{ fontSize: 7, fontFamily: "monospace", color: C.dim, letterSpacing: "0.1em", textTransform: "uppercase" }}>{label}</div>
                  <div style={{ fontSize: 15, fontFamily: "monospace", fontWeight: 800, color: accent, lineHeight: 1.2 }}>{value}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Auditor breakdown */}
          {ap && (
            <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "10px 12px", backdropFilter: "blur(12px)", flexShrink: 0 }}>
              <div style={{ fontSize: 8, fontFamily: "monospace", letterSpacing: "0.15em", textTransform: "uppercase", color: C.dim, marginBottom: 8 }}>
                ◈ Auditor Analysis ({ap.days_analysed ?? 0}d)
              </div>
              {[
                { label: "Alpaca",  data: ap.alpaca },
                { label: "Kraken",  data: ap.kraken },
              ].filter(r => r.data).map(({ label, data }) => (
                <div key={label} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
                  <span style={{ fontSize: 9, fontFamily: "monospace", fontWeight: 700, color: C.label, width: 44, flexShrink: 0 }}>{label}</span>
                  <div style={{ flex: 1, height: 5, background: "rgba(255,255,255,0.06)", borderRadius: 3, overflow: "hidden" }}>
                    <div style={{ height: "100%", width: `${data!.win_rate ?? 0}%`, background: (data!.win_rate ?? 0) >= 50 ? C.green : C.red, borderRadius: 3 }} />
                  </div>
                  <span style={{ fontSize: 9, fontFamily: "monospace", color: (data!.win_rate ?? 0) >= 50 ? C.green : C.red, width: 32, textAlign: "right", flexShrink: 0 }}>
                    {fmtPct(data!.win_rate)}
                  </span>
                  <span style={{ fontSize: 8, fontFamily: "monospace", color: C.dim, flexShrink: 0 }}>
                    {data!.total}T
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Asset class attribution */}
          {assetClasses.length > 0 && (
            <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "10px 12px", backdropFilter: "blur(12px)", flex: 1, minHeight: 0, overflow: "hidden" }}>
              <div style={{ fontSize: 8, fontFamily: "monospace", letterSpacing: "0.15em", textTransform: "uppercase", color: C.dim, marginBottom: 8 }}>
                ◈ Asset Class Performance
              </div>
              {assetClasses.map(([cls, data]) => (
                <div key={cls} style={{ marginBottom: 7 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2 }}>
                    <span style={{ fontSize: 8, fontFamily: "monospace", color: C.label, letterSpacing: "0.08em" }}>{cls.replace(/_/g, " ").toUpperCase()}</span>
                    <span style={{ fontSize: 8, fontFamily: "monospace", color: data.win_rate >= 0.5 ? C.green : C.red }}>
                      {fmtPct(data.win_rate * 100)} WR · {data.count}T
                    </span>
                  </div>
                  <div style={{ height: 4, background: "rgba(255,255,255,0.05)", borderRadius: 2, overflow: "hidden" }}>
                    <div style={{ height: "100%", width: `${data.win_rate * 100}%`, background: data.win_rate >= 0.5 ? C.green : C.red, borderRadius: 2 }} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ── CENTER: BOT PERFORMANCE MATRIX ── */}
        <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "10px 12px", backdropFilter: "blur(12px)", display: "flex", flexDirection: "column", minHeight: 0 }}>
          <div style={{ fontSize: 8, fontFamily: "monospace", letterSpacing: "0.15em", textTransform: "uppercase", color: C.dim, marginBottom: 6, flexShrink: 0 }}>
            ◈ Bot Performance Matrix
          </div>

          {/* Column headers */}
          <div style={{ display: "grid", gridTemplateColumns: "22px 1fr 48px 40px 56px", gap: "0 6px", padding: "0 8px 4px", flexShrink: 0, borderBottom: `1px solid ${C.border}`, marginBottom: 4 }}>
            {["", "Bot", "Win%", "Trades", "P&L"].map((h, i) => (
              <span key={i} style={{ fontSize: 7, fontFamily: "monospace", color: C.dim, textAlign: i >= 2 ? "right" : "left", letterSpacing: "0.1em", textTransform: "uppercase" }}>{h}</span>
            ))}
          </div>

          {/* Kraken bots */}
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 2, overflowY: "auto" }}>
            {fl?.bots && fl.bots.length > 0 ? fl.bots.map((bot) => {
              const meta = BOT_META[bot.bot_id] ?? { icon: "🤖", color: C.label, startCap: 100_000 };
              return (
                <BotRow
                  key={bot.bot_id}
                  name={bot.display_name}
                  icon={meta.icon}
                  equity={bot.equity_usd}
                  startCap={meta.startCap}
                  trades={bot.trades}
                  wins={bot.wins}
                  pnlUsd={bot.pnl_usd}
                  color={meta.color}
                />
              );
            }) : (
              <div style={{ color: C.dim, fontSize: 9, fontFamily: "monospace", textAlign: "center", marginTop: 20 }}>
                Loading fleet data...
              </div>
            )}

            {/* Oracle / Alpaca row from auditor */}
            {ap?.alpaca && (
              <div style={{ marginTop: 6, borderTop: `1px solid ${C.border}`, paddingTop: 6 }}>
                <BotRow
                  name="Oracle (Alpaca)"
                  icon="🔮"
                  equity={st?.portfolio_totals?.equity ?? 100_000}
                  startCap={100_000}
                  trades={ap.alpaca.total}
                  wins={ap.alpaca.wins}
                  pnlUsd={(st?.portfolio_totals?.equity ?? 100_000) - 100_000}
                  color={C.violet}
                />
              </div>
            )}
          </div>

          {/* Divider + equity summary */}
          <div style={{ borderTop: `1px solid ${C.border}`, marginTop: 8, paddingTop: 8, flexShrink: 0 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 6 }}>
              {[
                { label: "Fleet Equity",  value: `$${((fl?.bots?.reduce((s, b) => s + b.equity_usd, 0) ?? 0) / 1000).toFixed(0)}k`, accent: C.cyan },
                { label: "Total Trades",  value: String(fl?.bots?.reduce((s, b) => s + b.trades, 0) ?? 0), accent: C.text },
                { label: "Fleet WinRate", value: (() => {
                  const bots = fl?.bots ?? [];
                  const wins = bots.reduce((s, b) => s + b.wins, 0);
                  const total = bots.reduce((s, b) => s + b.trades, 0);
                  return total > 0 ? fmtPct((wins / total) * 100) : "—";
                })(), accent: C.green },
              ].map(({ label, value, accent }) => (
                <div key={label} style={{ textAlign: "center" }}>
                  <div style={{ fontSize: 7, fontFamily: "monospace", color: C.dim, textTransform: "uppercase", letterSpacing: "0.08em" }}>{label}</div>
                  <div style={{ fontSize: 14, fontFamily: "monospace", fontWeight: 800, color: accent }}>{value}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ── RIGHT: SENTIMENT + REGIME + ALLOCATION ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8, minHeight: 0 }}>

          {/* Sentiment */}
          <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "10px 12px", backdropFilter: "blur(12px)", flexShrink: 0 }}>
            <div style={{ fontSize: 8, fontFamily: "monospace", letterSpacing: "0.15em", textTransform: "uppercase", color: C.dim, marginBottom: 8 }}>
              ◈ Market Sentiment
            </div>
            {[
              { label: "Crypto Fear & Greed", value: cryptoFG },
              { label: "Market Fear & Greed",  value: marketFG },
            ].map(({ label, value }) => (
              <div key={label} style={{ marginBottom: 8 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
                  <span style={{ fontSize: 8, fontFamily: "monospace", color: C.label }}>{label}</span>
                  <span style={{ fontSize: 9, fontFamily: "monospace", fontWeight: 700, color: fgColor(value) }}>
                    {value != null ? `${value} · ${fgLabel(value)}` : "—"}
                  </span>
                </div>
                <div style={{ height: 5, background: "rgba(255,255,255,0.05)", borderRadius: 3, overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${value ?? 0}%`, background: fgColor(value), borderRadius: 3 }} />
                </div>
              </div>
            ))}
          </div>

          {/* Regime & System */}
          <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "10px 12px", backdropFilter: "blur(12px)", flexShrink: 0 }}>
            <div style={{ fontSize: 8, fontFamily: "monospace", letterSpacing: "0.15em", textTransform: "uppercase", color: C.dim, marginBottom: 8 }}>
              ◈ System Status
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "5px 10px" }}>
              {[
                { label: "Regime",       value: regime,                                    accent: regime === "Bull" ? C.green : regime === "Bear" ? C.red : C.amber },
                { label: "System",       value: st?.system_health.system_status ?? "—",     accent: st?.system_health.system_status === "online" ? C.green : C.red },
                { label: "Market",       value: st?.market_open ? "OPEN" : "CLOSED",        accent: st?.market_open ? C.green : C.dim },
                { label: "Kill Switch",  value: st?.kill_switch_tripped ? "TRIPPED" : "SAFE", accent: st?.kill_switch_tripped ? C.red : C.green },
                { label: "Positions",    value: String(st?.position_count ?? "—"),           accent: C.text },
                { label: "Auto-Trade",   value: st?.auto_trading ? "ON" : "OFF",             accent: st?.auto_trading ? C.green : C.amber },
              ].map(({ label, value, accent }) => (
                <div key={label}>
                  <div style={{ fontSize: 7, fontFamily: "monospace", color: C.dim, letterSpacing: "0.08em", textTransform: "uppercase" }}>{label}</div>
                  <div style={{ fontSize: 11, fontFamily: "monospace", fontWeight: 800, color: accent, textTransform: "uppercase" }}>{value}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Kelly / Allocation weighting */}
          <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, padding: "10px 12px", backdropFilter: "blur(12px)", flex: 1, minHeight: 0, overflow: "hidden", display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 8, fontFamily: "monospace", letterSpacing: "0.15em", textTransform: "uppercase", color: C.dim, marginBottom: 6, flexShrink: 0 }}>
              ◈ Kelly Weighting (Oracle)
            </div>
            {allSlots.length > 0 ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 4, overflowY: "auto", flex: 1 }}>
                {allSlots.slice(0, 7).map((slot) => {
                  const pct = Math.min((slot.kelly_fraction ?? 0) * 100, 100);
                  return (
                    <div key={slot.ticker}>
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2 }}>
                        <span style={{ fontSize: 8, fontFamily: "monospace", fontWeight: 700, color: C.text }}>{slot.ticker}</span>
                        <div style={{ display: "flex", gap: 6 }}>
                          <span style={{ fontSize: 7, fontFamily: "monospace", color: C.amber }}>K={fmtPct(pct)}</span>
                          <span style={{ fontSize: 7, fontFamily: "monospace", color: C.dim }}>C={slot.conviction_score?.toFixed(1)}</span>
                        </div>
                      </div>
                      <div style={{ height: 3, background: "rgba(255,255,255,0.05)", borderRadius: 2, overflow: "hidden" }}>
                        <div style={{ height: "100%", width: `${pct}%`, background: `linear-gradient(90deg, ${C.violet}, ${C.cyan})`, borderRadius: 2 }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div style={{ color: C.dim, fontSize: 9, fontFamily: "monospace", textAlign: "center", marginTop: 16 }}>
                No active allocation
              </div>
            )}
          </div>
        </div>
      </div>

      <DDGBadge style={{ position: "absolute", bottom: 10, left: 10, zIndex: 50 }} />
    </div>
  );
}
