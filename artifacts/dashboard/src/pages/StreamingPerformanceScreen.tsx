import {
  useRiskMetrics,
  useJournal,
  useAttribution,
  useKrakenFleetSummary,
  useSentiment,
  useStatusSummary,
  useVault,
} from "@/hooks/use-trading";
import { DDGBadge } from "@/components/DDGBadge";

/* ── palette ─────────────────────────────────────────────── */
const C = {
  bg:     "#020617",
  panel:  "rgba(15,23,42,0.88)",
  border: "rgba(255,255,255,0.07)",
  dim:    "rgba(148,163,184,0.45)",
  label:  "rgba(148,163,184,0.7)",
  text:   "rgba(226,232,240,0.9)",
  green:  "#34d399",
  red:    "#f87171",
  amber:  "#fbbf24",
  blue:   "#60a5fa",
  violet: "#a78bfa",
  cyan:   "#22d3ee",
  orange: "#fb923c",
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
const BOT_META: Record<string, { icon: string; color: string; startCap: number; label: string }> = {
  "davy-jones":     { icon: "⚓", color: C.cyan,   startCap: 100_000, label: "Davy Jones" },
  "blackbeard":     { icon: "☠️", color: C.red,    startCap: 100_000, label: "Blackbeard" },
  "calypso":        { icon: "🌊", color: C.violet, startCap: 100_000, label: "Calypso" },
  "apex-predator":  { icon: "🦅", color: C.orange, startCap: 100_000, label: "Apex Predator" },
  "poseidon":       { icon: "🔱", color: C.blue,   startCap: 100_000, label: "Poseidon" },
  "kraken-current": { icon: "🐙", color: C.green,  startCap: 100_000, label: "Kraken Current" },
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
  const fleet   = useKrakenFleetSummary();
  const sent    = useSentiment();
  const status  = useStatusSummary();
  const vaultData = useVault();

  const rm  = risk.data;
  const j   = journal.data;
  const at  = attr.data;
  const fl  = fleet.data;
  const sg  = sent.data;
  const st  = status.data;
  const totalVaulted = vaultData.data?.total_vaulted_usd ?? null;

  const cryptoFG = sg?.crypto_fear_greed?.value;
  const marketFG = sg?.market_fear_greed?.value;
  const regime   = st?.groq?.regime ?? "—";

  /* fleet P&L from equity – starting cap */
  const fleetBots = fl?.bots ?? [];
  const fleetPnL  = fleetBots.reduce((s, b) => s + b.equity_usd - b.starting_balance_usd, 0);
  const fleetEquity = fleetBots.reduce((s, b) => s + b.equity_usd, 0);
  const fleetTrades = fl?.total_trades ?? fleetBots.reduce((s, b) => s + b.trades, 0);
  const fleetWins   = fl?.total_wins   ?? fleetBots.reduce((s, b) => s + b.wins, 0);
  // Single canonical win rate — always the server-computed value, no client-side arithmetic drift
  const fleetWinRate = fl?.fleet_win_rate ?? (fleetTrades > 0 ? (fleetWins / fleetTrades) * 100 : null);

  /* overall win rate — attribution returns 0-100 already */
  const overallWinRate = at?.overall.win_rate ?? null;
  const totalTrades    = j?.summary.total ?? 0;

  /* ── sub-components ──────────────────────────────────────── */

  function RiskCard({
    label, value, sub, accent, note,
  }: { label: string; value: string; sub?: string; accent: string; note?: string }) {
    return (
      <div style={{
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
    <div style={{
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
    }}>

      {/* ══ HEADER ═══════════════════════════════════════════════ */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 12, fontFamily: "monospace", fontWeight: 900, letterSpacing: "0.22em", textTransform: "uppercase", color: C.cyan }}>
            ◈ RAW PERFORMANCE
          </span>
          <span style={{ fontSize: 10, fontFamily: "monospace", color: C.dim, letterSpacing: "0.1em" }}>
            FLEET · 8 BOTS · $800K CAPITAL
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <span style={{ fontSize: 11, fontFamily: "monospace" }}>
            REGIME:{" "}
            <span style={{ color: regime === "Bull" ? C.green : regime === "Bear" ? C.red : C.amber, fontWeight: 900 }}>
              {regime.toUpperCase()}
            </span>
          </span>
          <span style={{ fontSize: 14, fontFamily: "monospace", fontWeight: 900, color: pnlColor(fleetPnL) }}>
            FLEET P&L: {fmtMoney(fleetPnL)}
          </span>
          <span style={{ fontSize: 11, fontFamily: "monospace", color: "rgba(251,191,36,0.8)" }}>
            VAULT:{" "}
            <span style={{ fontWeight: 900, color: "#fbbf24" }}>
              {totalVaulted != null ? `$${Math.round(totalVaulted).toLocaleString()}` : "—"}
            </span>
          </span>
        </div>
      </div>

      {/* ══ ROW 1: RISK RATIO CARDS ══════════════════════════════ */}
      <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
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
          sub={rm?.insufficient_data ? `Need 30+ days (${rm.data_points ?? 0} pts so far)` : rm?.period_days ? `${rm.period_days}d window · ${rm.data_points ?? 0} pts` : "Awaiting data"}
          accent={rm?.annualised_return_pct != null ? (rm.annualised_return_pct >= 0 ? C.green : C.red) : C.dim}
        />
      </div>

      {/* ══ ROW 2: MAIN CONTENT ══════════════════════════════════ */}
      <div style={{ display: "grid", gridTemplateColumns: "1.1fr 1fr", gap: 8, flex: 1, minHeight: 0 }}>

        {/* ── LEFT: BOT PERFORMANCE MATRIX ─────────────────────── */}
        <div style={{
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
                  { label: "Fleet Equity", value: fleetEquity > 0 ? `$${(fleetEquity / 1000).toFixed(0)}k` : "—", color: C.cyan },
                  { label: "Total Trades", value: fleetTrades > 0 ? String(fleetTrades) : "—", color: C.text },
                  { label: "Win Rate", value: fleetWinRate != null ? fmtPct(fleetWinRate, 0) : "—", color: fleetWinRate != null ? (fleetWinRate >= 50 ? C.green : C.red) : C.dim },
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
            {fleetBots.length > 0 ? fleetBots.map((bot) => {
              const meta = BOT_META[bot.bot_id] ?? { icon: "🤖", color: C.label, startCap: 100_000, label: bot.bot_id };
              const pnl  = bot.equity_usd - meta.startCap;
              const wr   = bot.trades > 0 ? (bot.wins / bot.trades) * 100 : null;
              return (
                <div key={bot.bot_id} style={{
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
                      ${(bot.equity_usd / 1000).toFixed(1)}k equity
                    </div>
                  </div>
                  {/* win rate with mini bar */}
                  <div style={{ textAlign: "right" }}>
                    <div style={{ fontSize: 16, fontFamily: "monospace", fontWeight: 900, color: wr != null ? (wr >= 50 ? C.green : C.red) : C.dim }}>
                      {wr != null ? `${wr.toFixed(0)}%` : "—"}
                    </div>
                    <div style={{ height: 3, background: "rgba(255,255,255,0.06)", borderRadius: 2, marginTop: 3, overflow: "hidden" }}>
                      <div style={{ height: "100%", width: `${wr ?? 0}%`, background: wr != null ? (wr >= 50 ? C.green : C.red) : "transparent", borderRadius: 2, transition: "width 0.6s ease" }} />
                    </div>
                  </div>
                  <div style={{ fontSize: 14, fontFamily: "monospace", color: C.label, textAlign: "right" }}>
                    {bot.trades}
                  </div>
                  <div style={{ fontSize: 18, fontFamily: "monospace", fontWeight: 900, color: pnlColor(pnl), textAlign: "right" }}>
                    {fmtMoney(pnl)}
                  </div>
                </div>
              );
            }) : (
              <div style={{ padding: 24, textAlign: "center", color: C.dim, fontSize: 12, fontFamily: "monospace" }}>
                Loading fleet data…
              </div>
            )}
          </div>
        </div>

        {/* ── RIGHT: STATS + SENTIMENT + STATUS ────────────────── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8, minHeight: 0 }}>

          {/* Trade stats — big numbers */}
          <div style={{
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
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
              {[
                { label: "Total Trades", value: fleetTrades > 0 ? String(fleetTrades) : "—", color: C.text },
                { label: "Win Rate",     value: fleetWinRate != null ? `${fleetWinRate.toFixed(0)}%` : "—", color: fleetWinRate != null ? (fleetWinRate >= 50 ? C.green : C.red) : C.dim },
                { label: "Total Wins",   value: fleetTrades > 0 ? String(fleetWins) : "—", color: C.green },
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
          <div style={{
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
              { label: "Crypto Fear & Greed", value: cryptoFG },
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
          <div style={{
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
                { label: "Kill Switch", value: st?.kill_switch_tripped ? "TRIPPED" : "SAFE",      color: st?.kill_switch_tripped ? C.red : C.green },
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

      <DDGBadge style={{ position: "absolute", bottom: 10, left: 10, zIndex: 50 }} />
    </div>
  );
}
