import { Fragment, useMemo, useState, type CSSProperties } from "react";
import { Activity, BarChart3, CalendarClock, CheckCircle2, Crosshair, Download, Gauge, ShieldCheck, Waves } from "lucide-react";
import { useFleetData, fmtDollar, fmtEq, fmtPct, getBotStatus } from "@/hooks/useFleetData";
import { usePerformanceHistory, usePerformanceSummary, useCorrelation, useAttribution, useRiskMetrics } from "@/hooks/use-performance";
import { useBotRegistry, useFleetHistory } from "@/hooks/use-portfolio";
import { useRecentTrades } from "@/hooks/use-journal";
import { useExportReport } from "@/hooks/use-report";
import { useLocation } from "wouter";
import RunnerStatusIndicator from "@/components/RunnerStatusIndicator";
import type { RunnerStatusResponse } from "@/hooks/useFleetData";
import { getBotColors } from "@/lib/bot-colors";

const css = `.observatory{--ink:#effaf5;--muted:#98b5b1;--dim:#789694;--line:rgba(184,239,225,.14);min-height:100dvh;padding:22px clamp(16px,3vw,42px) 34px;color:var(--ink);background:radial-gradient(ellipse at 8% 0%,#a0dcd633,transparent 32%),radial-gradient(ellipse at 94% 22%,#448b9144,transparent 34%),linear-gradient(145deg,#0c2b34,#051720 55%,#0e282e);font-family:system-ui,sans-serif}.observatory *{box-sizing:border-box}.obs-shell{max-width:1740px;margin:auto}.obs-topline,.obs-hero,.obs-section-head,.obs-card-head,.obs-equity-line,.obs-cycle,.obs-footer{display:flex;align-items:center;justify-content:space-between;gap:16px}.obs-topline{margin-bottom:28px;color:var(--muted);font:10px monospace;letter-spacing:.12em;text-transform:uppercase}.obs-brand{display:flex;gap:10px;align-items:center;color:var(--ink);font-weight:bold}.obs-mark{display:grid;place-items:center;width:26px;height:26px;color:#071b24;background:#8cf1d5;border-radius:8px 8px 8px 2px}.obs-session{display:flex;gap:14px;flex-wrap:wrap}.obs-dot{display:inline-block;width:6px;height:6px;margin-right:6px;border-radius:50%;background:#b7ef75}.obs-hero{align-items:end;margin-bottom:24px}.obs-kicker,.obs-label,.obs-meta,.obs-bot-eyebrow{color:#8cf1d5;font:10px monospace;letter-spacing:.15em;text-transform:uppercase}.obs-title{margin:8px 0 12px;font-size:clamp(31px,3.1vw,49px);letter-spacing:-.05em}.obs-title em{color:#8cf1d5;font-style:normal}.obs-subtitle{max-width:560px;margin:0;color:var(--muted);font-size:13px;line-height:1.45}.obs-asof{min-width:210px;padding:12px 16px;border-left:1px solid #8cf1d566;color:var(--muted);font:10px/1.7 monospace}.obs-asof strong{display:block;color:var(--ink);font-size:14px}.obs-summary{display:grid;grid-template-columns:1.7fr 1fr 1fr 1fr 1.5fr;gap:1px;margin-bottom:32px;overflow:hidden;border:1px solid var(--line);border-radius:14px;background:var(--line)}.obs-summary-cell{min-height:88px;padding:17px 19px;background:#071f27dd}.obs-summary-cell:first-child{background:#0c3136dd}.obs-value{margin-top:6px;font:25px monospace;letter-spacing:-.06em}.obs-value.large{font-size:32px}.positive{color:#b7ef75}.negative{color:#ff9a91}.obs-under{display:flex;gap:8px;margin-top:4px;color:var(--muted);font:10px monospace}.obs-regime{display:flex;align-items:center;gap:10px;margin-top:10px;color:#b7ef75;font:17px monospace}.obs-section-head{align-items:end;margin-bottom:14px}.obs-section-title{margin:0;font-size:16px;font-weight:500}.obs-meta{color:var(--dim);font-size:10px}.obs-bot-row{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.obs-bot-card,.obs-evidence-panel{min-width:0;padding:18px;border:1px solid var(--line);border-radius:15px;background:#071d26b8;box-shadow:inset 0 1px #e7fff814}.obs-bot-card{border-top:2px solid var(--accent)}.obs-bot-name{margin:4px 0;font-size:20px}.obs-bot-code{color:var(--dim);font:9px monospace}.obs-equity-line{align-items:end;margin-top:18px}.obs-equity{font:27px monospace;letter-spacing:-.07em}.obs-return{text-align:right;color:var(--accent);font:12px monospace}.obs-return span{display:block;margin-top:3px;color:var(--dim);font-size:9px}.obs-chart{height:93px;margin-top:12px;padding:8px 0 4px;border-block:1px solid var(--line)}.obs-chart svg{width:100%;height:100%}.obs-chart-grid{stroke:#c6efe21a;stroke-dasharray:2 5}.obs-chart-area{fill:var(--accent-soft)}.obs-chart-line{fill:none;stroke:var(--accent);stroke-width:2;stroke-linecap:round}.obs-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:16px}.obs-metric{border-right:1px solid var(--line)}.obs-metric:last-child{border:0}.obs-metric label{display:block;color:var(--dim);font:9px monospace;text-transform:uppercase}.obs-metric strong{display:block;margin-top:5px;font:14px monospace}.obs-exposure{display:flex;gap:10px;align-items:center;margin-top:16px;color:var(--muted);font:9px monospace}.obs-bar{height:5px;flex:1;border-radius:9px;background:#d2f6ea14}.obs-bar i{display:block;height:100%;border-radius:inherit;background:var(--accent)}.obs-detail{margin-top:18px;padding-top:12px;border-top:1px solid var(--line);color:var(--dim);font:9px monospace;text-transform:uppercase}.obs-chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:9px}.obs-chip{padding:6px 8px;border:1px solid #8cf1d555;border-radius:5px;color:#8cf1d5;background:#8cf1d514;font:10px monospace;text-transform:none}.obs-note{color:var(--muted);font-size:10px;text-transform:none}.obs-evidence{display:grid;grid-template-columns:1.15fr .85fr;gap:14px;margin-top:31px}.obs-correlation{display:grid;grid-template-columns:1.25fr repeat(3,1fr);gap:1px;overflow:auto;border:1px solid var(--line);background:var(--line)}.obs-correlation>div{padding:10px;background:#061c25dd;color:var(--muted);font:10px monospace}.obs-correlation .head{color:var(--dim);font-size:8px;text-transform:uppercase}.obs-correlation .label{color:var(--ink)}.obs-correlation .num{text-align:center}.obs-timeline-row{display:grid;grid-template-columns:75px 10px 1fr 65px;align-items:center;gap:8px;min-height:39px;border-bottom:1px solid #b8efe214;color:var(--muted);font:10px monospace}.obs-timeline-row:last-child{border:0}.obs-timeline-mark{width:7px;height:7px;border-radius:50%;background:#8cf1d5}.obs-timeline-copy{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.obs-timeline-copy strong{color:var(--ink)}.obs-footer{margin-top:21px;color:var(--dim);font:9px monospace}.obs-footer-left,.obs-footer-right{display:flex;gap:14px;align-items:center}.obs-button{padding:7px 10px;border:1px solid var(--line);border-radius:7px;color:var(--ink);background:#ffffff0d;cursor:pointer;font:10px monospace}@media(max-width:1199px){.obs-hero{align-items:start;flex-direction:column}.obs-asof{width:100%}.obs-summary{grid-template-columns:1fr 1fr}.obs-summary-cell:last-child{grid-column:span 2}.obs-bot-row,.obs-evidence{grid-template-columns:1fr}.obs-evidence-panel{overflow:hidden}}@media(max-width:767px){.observatory{display:none}}@media(max-width:560px){.obs-summary{grid-template-columns:1fr}.obs-summary-cell:last-child{grid-column:auto}.obs-footer{align-items:start;flex-direction:column}}`;

const mobileVisualTreatment = `.observatory{background-image:linear-gradient(rgba(7,24,31,.34),rgba(7,24,31,.48)),url("/observatory-home-background.jpg");background-position:center;background-size:cover;background-attachment:fixed}.observatory::before{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;background:linear-gradient(180deg,rgba(255,255,255,.08),rgba(4,22,30,.18))}.observatory .obs-shell{position:relative;z-index:1}.observatory,.observatory *{text-shadow:0 2px 7px rgba(0,0,0,.58),0 1px 2px rgba(0,0,0,.72)}.observatory .obs-mark,.observatory svg,.observatory .obs-dot{filter:drop-shadow(0 1px 4px rgba(0,0,0,.62))}.observatory .obs-summary,.observatory .obs-bot-card,.observatory .obs-evidence-panel{background:rgba(9,33,42,.42);border-color:rgba(232,255,247,.28);box-shadow:0 18px 48px rgba(2,17,22,.28),inset 0 1px rgba(255,255,255,.20);backdrop-filter:blur(18px) saturate(135%);-webkit-backdrop-filter:blur(18px) saturate(135%)}.observatory .obs-summary-cell{background:rgba(10,42,48,.46)}.observatory .obs-summary-cell:first-child{background:rgba(22,65,66,.48)}.observatory .obs-chip,.observatory .obs-button{background:rgba(255,255,255,.13);border-color:rgba(255,255,255,.30);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}.observatory .obs-note{ text-shadow:0 1px 4px rgba(0,0,0,.85) }`;

// Match the mobile homepage card treatment exactly: neutral white glass rather
// than teal/green panel fills that tint the scenic desktop background.
const mobileGlassBoxTreatment = `.observatory .obs-summary,.observatory .obs-bot-card,.observatory .obs-evidence-panel{background:rgba(255,255,255,0.12);border-color:rgba(100,116,139,0.22);box-shadow:0 8px 20px rgba(15,23,42,0.10);backdrop-filter:blur(7.84px) saturate(125%);-webkit-backdrop-filter:blur(7.84px) saturate(125%)}.observatory .obs-summary-cell,.observatory .obs-summary-cell:first-child{background:rgba(255,255,255,0.12)}.observatory .obs-correlation{background:rgba(100,116,139,0.22)}.observatory .obs-correlation>div{background:rgba(255,255,255,0.12)}`;

const riskMetricsCss = `.obs-risk-section{margin:-10px 0 30px}.obs-risk-head{align-items:center;margin-bottom:10px}.obs-risk-heading{display:flex;align-items:center;gap:9px}.obs-risk-context{display:flex;align-items:center;justify-content:flex-end;gap:7px 13px;flex-wrap:wrap;color:var(--muted);font:9px/1.5 monospace;text-align:right}.obs-risk-source{color:#8cf1d5}.obs-risk-source.estimate,.obs-risk-state{color:#ffd28b}.obs-risk-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px}.obs-risk-card{min-width:0;padding:13px 15px;border:1px solid var(--line);border-radius:12px;background:rgba(7,29,38,.66);box-shadow:inset 0 1px rgba(255,255,255,.08);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px)}.obs-risk-value{margin-top:7px;color:var(--ink);font:clamp(20px,2vw,28px)/1.1 monospace;letter-spacing:-.06em;font-variant-numeric:tabular-nums}.obs-risk-value.positive{color:#b7ef75}.obs-risk-value.negative{color:#ff9a91}.obs-risk-value.warning{color:#ffd28b}.obs-risk-foot{margin-top:6px;color:var(--muted);font:9px/1.4 monospace}.obs-risk-disclaimer{margin:9px 0 0;color:#ffd28b;font:10px/1.5 monospace}.obs-risk-error{color:#ffaaa2}@media(max-width:1199px){.obs-risk-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:767px){.obs-risk-head{align-items:flex-start;flex-direction:column}.obs-risk-context{justify-content:flex-start;text-align:left}.obs-risk-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:560px){.obs-risk-grid{grid-template-columns:1fr}}`;

function value(v: number | null | undefined, format: (n:number)=>string = n => String(n)) { return v == null ? "NULL" : format(v); }
function metricValue(v: number | null | undefined, format: (n:number)=>string = n => String(n)) { return v == null || !Number.isFinite(v) ? "—" : format(v); }
function path(points: number[]) { if (!points.length) return ""; const min=Math.min(...points), max=Math.max(...points), range=max-min||1; return points.map((v,i)=>`${i?'L':'M'} ${(i/(points.length-1||1))*238+2} ${72-((v-min)/range)*64}`).join(" "); }
function ratioTone(v: number | null | undefined) { return v == null ? "" : v >= 1 ? "positive" : v >= 0 ? "warning" : "negative"; }
function percentTone(v: number | null | undefined) { return v == null ? "" : v >= 0 ? "positive" : "negative"; }
function fmtRiskRatio(v: number | null | undefined) { return v == null ? "—" : v.toFixed(2); }
function fmtRiskPct(v: number | null | undefined, signed = false) { return v == null ? "—" : `${signed && v >= 0 ? "+" : ""}${v.toFixed(1)}%`; }
function fmtRiskDate(v: string | null | undefined) { if (!v) return null; const d = new Date(v); return Number.isNaN(d.getTime()) ? v : d.toISOString().slice(0, 10); }

const dashboardOverviewCss = `
.observatory{padding-top:10px;background-image:linear-gradient(rgba(7,24,31,.34),rgba(7,24,31,.48)),var(--dashboard-nature-image)}
.obs-topline{margin-bottom:8px}
.obs-brand{font-size:0}
.obs-session>span{display:none}
.obs-hero,.obs-risk-section{display:none}
.obs-runner-status{display:none!important}
.obs-summary.obs-summary-compact{grid-template-columns:repeat(14,minmax(0,1fr));margin:0 0 25px}
.obs-summary.obs-summary-compact .obs-summary-cell{min-width:0;min-height:82px;padding:11px 10px}
.obs-summary.obs-summary-compact .obs-quick-primary,.obs-summary.obs-summary-compact .obs-quick-change,.obs-summary.obs-summary-compact .obs-quick-status{grid-column:span 2}
.obs-summary-compact .obs-label{overflow:hidden;font-size:8px;letter-spacing:.08em;text-overflow:ellipsis;white-space:nowrap}
.obs-overview-value{overflow:hidden;margin-top:7px;color:var(--ink);font:clamp(14px,1.08vw,17px)/1.05 monospace;letter-spacing:-.055em;text-overflow:ellipsis;white-space:nowrap;font-variant-numeric:tabular-nums}
.obs-overview-value.positive{color:#b7ef75}.obs-overview-value.negative{color:#ff9a91}.obs-overview-value.warning{color:#ffd28b}
.obs-summary-compact .obs-under{display:block;overflow:hidden;margin-top:5px;font:8px/1.35 monospace;text-overflow:ellipsis;white-space:nowrap}
.obs-overview-regime{margin-top:9px;color:#b7ef75;font:14px/1.1 monospace;white-space:nowrap}
.obs-quick-status-lines{display:grid;gap:5px;margin-top:7px}
.obs-quick-status-line{display:flex;justify-content:space-between;gap:6px;color:var(--muted);font:8px/1.2 monospace;text-transform:uppercase}
.obs-quick-status-line strong{overflow:hidden;color:var(--ink);font-weight:700;text-overflow:ellipsis;white-space:nowrap}
.obs-quick-status-line strong.positive{color:#b7ef75}.obs-quick-status-line strong.negative{color:#ff9a91}.obs-quick-status-line strong.warning{color:#ffd28b}
@media(max-width:1199px){.obs-summary.obs-summary-compact{grid-template-columns:repeat(8,minmax(0,1fr))}}
@media(max-width:900px){.obs-summary.obs-summary-compact{grid-template-columns:repeat(6,minmax(0,1fr))}}
`;

export default function ObservatoryHome({
  runnerStatus,
  runnerStatusError,
}: {
  runnerStatus?: RunnerStatusResponse;
  runnerStatusError?: boolean;
}) {
  const [, navigate] = useLocation();
  const registryQuery = useBotRegistry();
  const { fleet, total, allPos, regime, killTripped, killSwitchArmed, lastCycle, oracle, spy, jerome, mktOpen } = useFleetData();
  const history = useFleetHistory(); const performance = usePerformanceHistory(); const summary = usePerformanceSummary();
  const correlation = useCorrelation(); const attribution = useAttribution(); const risk = useRiskMetrics(); const trades = useRecentTrades(8);
  const [exportOpen,setExportOpen] = useState(false); const report = useExportReport();
  const downloadReport = async () => {
    try {
      const result = await report.mutateAsync();
      const link = document.createElement("a"); link.href = URL.createObjectURL(new Blob([result.report], {type:"text/plain"}));
      link.download = `quant-terminal-report-${new Date().toISOString().slice(0,16).replace(/[:T]/g,"-")}.txt`; link.click(); URL.revokeObjectURL(link.href);
    } catch { /* existing report mutation surfaces its own error state */ }
  };
  const points = useMemo(()=> (history.data?.history ?? performance.data?.snapshots ?? []).map(p => Number("total_equity" in p ? p.total_equity : p.equity)).filter(Number.isFinite), [history.data,performance.data]);
  const slices = { oracle, spy_qqq_trend: spy, jerome_macro: jerome };
  const bots = (registryQuery.data?.bots ?? [])
    .filter((bot) => bot.status !== "retired")
    .sort((a, b) => a.display_order - b.display_order)
    .map((bot) => ({
      id: bot.id,
      name: bot.subtitle ? `${bot.display_name} · ${bot.subtitle}` : bot.display_name,
      slice: slices[bot.id as keyof typeof slices],
      paused: bot.status === "paused",
      accent: getBotColors(bot.color).hex,
    }));
  const symbols = Array.from(new Set(allPos.map(p=>p.symbol)));
  const corr = correlation.data;
  const unavailable = "Unavailable from current API";
  const riskData = risk.data;
  const riskAsOf = fmtRiskDate(riskData?.as_of);
  const riskSource = riskData?.source === "performance_snapshots"
    ? "DAILY PERFORMANCE SNAPSHOTS"
    : riskData?.source === "trade_journal"
      ? "ESTIMATED · CLOSED-TRADE JOURNAL"
      : riskData?.source === "account_snapshot"
        ? "CURRENT ACCOUNT SNAPSHOT"
        : riskData?.source === "none"
          ? "NO PERFORMANCE DATA"
          : riskData
            ? "SERVER-REPORTED METRICS"
            : risk.isError
              ? "RISK FEED UNAVAILABLE"
              : "LOADING RISK DATA";
  const runnerVerdict = runnerStatusError ? "UNKNOWN" : runnerStatus?.verdict ?? "UNKNOWN";
  const runnerTone = runnerVerdict === "ALIVE" ? "positive" : runnerVerdict === "STALE" ? "negative" : "warning";
  const killLabel = killTripped == null || killSwitchArmed == null ? "UNKNOWN" : killTripped ? "TRIPPED" : killSwitchArmed ? "ARMED" : "DISARMED";
  const killTone = killTripped ? "negative" : killTripped == null || killSwitchArmed == null ? "warning" : "positive";
  const riskStatus = riskData
    ? `${riskData.source === "trade_journal" ? "EST. · " : ""}${riskData.data_points} OBS`
    : risk.isError ? "UNAVAILABLE" : "LOADING";
  const riskDetails = `${riskSource}${riskData ? ` · ${riskData.data_points} observations${riskData.period_days ? ` · ${riskData.period_days} periods` : ""}` : ""}${riskAsOf ? ` · As of ${riskAsOf} UTC` : ""}${riskData?.message ? ` · ${riskData.message}` : ""}`;
  const riskCards = [
    { label: "Sharpe ratio", value: fmtRiskRatio(riskData?.sharpe_ratio), detail: "Risk-adjusted excess return", tone: ratioTone(riskData?.sharpe_ratio) },
    { label: "Sortino ratio", value: fmtRiskRatio(riskData?.sortino_ratio), detail: "Downside-adjusted return", tone: ratioTone(riskData?.sortino_ratio) },
    { label: "Calmar ratio", value: fmtRiskRatio(riskData?.calmar_ratio), detail: "Annualized return ÷ max drawdown", tone: ratioTone(riskData?.calmar_ratio) },
    { label: "Max drawdown", value: riskData?.max_drawdown_pct == null ? "—" : `−${Math.abs(riskData.max_drawdown_pct).toFixed(1)}%`, detail: "Peak-to-trough loss", tone: riskData?.max_drawdown_pct == null ? "" : riskData.max_drawdown_pct < 5 ? "positive" : riskData.max_drawdown_pct < 15 ? "warning" : "negative" },
    { label: "Annual volatility", value: fmtRiskPct(riskData?.volatility_annual_pct), detail: "Annualized standard deviation", tone: riskData?.volatility_annual_pct == null ? "" : riskData.volatility_annual_pct < 20 ? "positive" : riskData.volatility_annual_pct < 40 ? "warning" : "negative" },
    { label: "Annual return", value: fmtRiskPct(riskData?.annualised_return_pct, true), detail: riskData?.insufficient_data ? "Insufficient history to annualize" : "Annualized portfolio return", tone: percentTone(riskData?.annualised_return_pct) },
  ];
    return <main className="observatory"><style>{css + riskMetricsCss + mobileVisualTreatment + mobileGlassBoxTreatment + dashboardOverviewCss}</style><div className="obs-shell">
     <div className="obs-topline"><div className="obs-brand" aria-label="Fleet Observatory"><span className="obs-mark"><Crosshair size={15}/></span>FLEET / OBSERVATORY</div><div className="obs-session"><span style={{ color: killTripped == null || killSwitchArmed == null ? "#fbbf24" : undefined }}><i className="obs-dot" style={{ background: killTripped == null || killSwitchArmed == null ? "#f59e0b" : undefined, boxShadow: killTripped == null || killSwitchArmed == null ? "0 0 9px #f59e0b" : undefined }}/> {killTripped == null || killSwitchArmed == null ? "KILL SWITCH UNKNOWN" : killTripped ? "KILL SWITCH" : killSwitchArmed ? "SYSTEM ARMED" : "SYSTEM DISARMED"}</span><span><i className="obs-dot"/> SYNCED {lastCycle ? new Date(lastCycle).toISOString().slice(11,19)+" UTC" : "NULL"}</span><button className="obs-button" onClick={()=>setExportOpen(v=>!v)} aria-label="Open export options" aria-expanded={exportOpen}><Download size={13} aria-hidden="true"/></button>{exportOpen&&<><button className="obs-button" onClick={downloadReport} disabled={report.isPending}>Export full report</button><button className="obs-button" onClick={()=>navigate("/stream")}>Full report</button></>}</div></div>
       <section className="obs-summary obs-summary-compact" aria-label="Fleet quick information">
         <div className="obs-summary-cell obs-quick-primary" title="Total fleet equity and lifetime profit or loss">
           <div className="obs-label">Fleet equity</div>
           <div className="obs-overview-value">{metricValue(total?.equity,fmtEq)}</div>
           <div className="obs-under"><strong>{metricValue(total?.pnl,fmtDollar)}</strong><span>{metricValue(total?.pnl_pct,fmtPct)} lifetime</span></div>
         </div>
         <div className="obs-summary-cell obs-quick-change" title="Server-reported 24-hour profit or loss">
           <div className="obs-label">24h change</div>
           <div className={`obs-overview-value ${percentTone(total?.pnl_24h)}`}>{metricValue(total?.pnl_24h,fmtDollar)}</div>
           <div className="obs-under">{metricValue(total?.pnl_24h_pct,fmtPct)} vs prior close</div>
         </div>
         <div className="obs-summary-cell" title={`Sortino ratio · ${riskDetails}`}>
           <div className="obs-label">Sortino</div>
           <div className={`obs-overview-value ${ratioTone(riskData?.sortino_ratio)}`}>{fmtRiskRatio(riskData?.sortino_ratio)}</div>
         </div>
         <div className="obs-summary-cell" title={`Sharpe ratio · ${riskDetails}`}>
           <div className="obs-label">Sharpe</div>
           <div className={`obs-overview-value ${ratioTone(riskData?.sharpe_ratio)}`}>{fmtRiskRatio(riskData?.sharpe_ratio)}</div>
         </div>
         <div className="obs-summary-cell" title={`Calmar ratio · ${riskDetails}`}>
           <div className="obs-label">Calmar</div>
           <div className={`obs-overview-value ${ratioTone(riskData?.calmar_ratio)}`}>{fmtRiskRatio(riskData?.calmar_ratio)}</div>
         </div>
         <div className="obs-summary-cell" title={`Maximum drawdown · ${riskDetails}`}>
           <div className="obs-label">Max drawdown</div>
           <div className={`obs-overview-value ${riskData?.max_drawdown_pct == null ? "" : riskData.max_drawdown_pct < 5 ? "positive" : riskData.max_drawdown_pct < 15 ? "warning" : "negative"}`}>{riskData?.max_drawdown_pct == null ? "—" : `−${Math.abs(riskData.max_drawdown_pct).toFixed(1)}%`}</div>
         </div>
         <div className="obs-summary-cell" title={`Annualized volatility · ${riskDetails}`}>
           <div className="obs-label">Volatility</div>
           <div className={`obs-overview-value ${riskData?.volatility_annual_pct == null ? "" : riskData.volatility_annual_pct < 20 ? "positive" : riskData.volatility_annual_pct < 40 ? "warning" : "negative"}`}>{fmtRiskPct(riskData?.volatility_annual_pct)}</div>
         </div>
         <div className="obs-summary-cell" title={`Annualized portfolio return · ${riskDetails}`}>
           <div className="obs-label">Annual return</div>
           <div className={`obs-overview-value ${percentTone(riskData?.annualised_return_pct)}`}>{fmtRiskPct(riskData?.annualised_return_pct,true)}</div>
         </div>
         <div className="obs-summary-cell" title="Server-reported number of open positions">
           <div className="obs-label">Open positions</div>
           <div className="obs-overview-value">{metricValue(total?.positions,n=>String(n).padStart(2,"0"))}</div>
           <div className="obs-under">{symbols.length ? `${symbols.length} symbols` : "symbol data unavailable"}</div>
         </div>
         <div className="obs-summary-cell" title="Current server-reported market regime">
           <div className="obs-label">Market regime</div>
           <div className="obs-overview-regime">{regime ?? "—"}</div>
         </div>
         <div className="obs-summary-cell obs-quick-status" title={riskDetails}>
           <div className="obs-label">System status</div>
           <div className="obs-quick-status-lines">
             <div className="obs-quick-status-line"><span>Runner</span><strong className={runnerTone}>{runnerVerdict}</strong></div>
             <div className="obs-quick-status-line"><span>Kill switch</span><strong className={killTone}>{killLabel}</strong></div>
             <div className="obs-quick-status-line"><span>Risk data</span><strong className={risk.isError ? "negative" : riskData?.source === "trade_journal" ? "warning" : riskData ? "positive" : "warning"}>{riskStatus}</strong></div>
           </div>
         </div>
       </section>
      <section className="obs-risk-section" aria-labelledby="risk-performance-title">
        <div className="obs-section-head obs-risk-head">
          <div>
            <h2 className="obs-section-title obs-risk-heading" id="risk-performance-title"><ShieldCheck size={16} color="#8cf1d5"/> Risk-adjusted performance</h2>
            <div className="obs-meta">Fleet-level metrics · annualized where noted</div>
          </div>
          <div className="obs-risk-context" aria-live="polite">
            <span className={`obs-risk-source${riskData?.source === "trade_journal" ? " estimate" : ""}`}>{risk.isFetching && riskData ? "UPDATING · " : ""}{riskSource}</span>
            <span>{riskData ? `${riskData.data_points} observations${riskData.period_days ? ` · ${riskData.period_days} periods` : ""}` : risk.isError ? "No current response" : "Waiting for response"}</span>
            <span>{riskAsOf ? `Data as of ${riskAsOf} UTC` : risk.dataUpdatedAt ? `Received ${new Date(risk.dataUpdatedAt).toLocaleTimeString()}` : "As-of date unavailable"}</span>
          </div>
        </div>
        <div className="obs-risk-grid">
          {riskCards.map((metric) => <article className="obs-risk-card" key={metric.label} aria-label={`${metric.label}: ${metric.value}`}>
            <div className="obs-label">{metric.label}</div>
            <div className={`obs-risk-value ${metric.tone}`}>{metric.value}</div>
            <div className="obs-risk-foot">{metric.detail}</div>
          </article>)}
        </div>
        {riskData?.message && <p className={`obs-risk-disclaimer${riskData.source === "trade_journal" ? "" : " obs-risk-error"}`}>{riskData.message}</p>}
        {risk.isError && <p className="obs-risk-disclaimer obs-risk-error">Risk metrics are unavailable from the API. Values are not being replaced with estimates.</p>}
      </section>
      <section aria-labelledby="engines" data-testid="section-strategy-engines">
        <div className="obs-section-head">
          <h2 className="obs-section-title" id="engines">▰ Strategy engines</h2>
          <div className="obs-meta">equity curves / risk evidence / UTC</div>
        </div>
        {registryQuery.isLoading && !registryQuery.data && (
          <div className="obs-note" data-testid="status-strategy-engines-loading">
            Loading bot registry…
          </div>
        )}
        {registryQuery.isError && !registryQuery.data && (
          <div className="obs-note" data-testid="status-strategy-engines-unavailable">
            Bot registry unavailable
          </div>
        )}
        {!registryQuery.isLoading && !registryQuery.isError && bots.length === 0 && (
          <div className="obs-note" data-testid="status-strategy-engines-empty">
            No registered strategy engines
          </div>
        )}
        <div className="obs-bot-row">
          {bots.map((bot) => {
            const positions = allPos.filter((position) => position.bot_id === bot.id);
            const slice = bot.slice;
            const status = bot.paused
              ? "PAUSED"
              : slice
                ? getBotStatus(slice, mktOpen, false)
                : "NULL";

            return (
              <article
                className="obs-bot-card"
                data-testid={`card-strategy-engine-${bot.id}`}
                aria-label={`${bot.name} strategy engine`}
                style={{
                  "--accent": bot.accent,
                  "--accent-soft": `${bot.accent}22`,
                } as CSSProperties}
                key={bot.id}
              >
                <div className="obs-card-head">
                  <div>
                    <div className="obs-bot-eyebrow">{bot.id.replace(/_/g, " ").toUpperCase()}</div>
                    <h3 className="obs-bot-name">{bot.name}</h3>
                  </div>
                  <div
                    className="obs-bot-code"
                    data-testid={`status-strategy-engine-${bot.id}`}
                  >
                    {status}
                  </div>
                </div>
                <div className="obs-equity-line">
                  <div className="obs-equity">{value(slice?.equity, fmtEq)}</div>
                  <div className="obs-return">
                    {value(slice?.pnl, fmtDollar)}
                    <span>{value(slice?.pnl_pct, fmtPct)} / server</span>
                  </div>
                </div>
                <div
                  className="obs-chart"
                  aria-label={`${bot.name} fleet equity history (per-bot history unavailable)`}
                >
                  <svg viewBox="0 0 242 80">
                    <line className="obs-chart-grid" x1="2" x2="240" y1="20" y2="20" />
                    <line className="obs-chart-grid" x1="2" x2="240" y1="48" y2="48" />
                    {points.length > 1 && <path className="obs-chart-line" d={path(points)} />}
                  </svg>
                  <div className="obs-note">Fleet history shown · per-bot curve NULL</div>
                </div>
                <div className="obs-metrics">
                  <div className="obs-metric"><label>Sharpe</label><strong>NULL</strong></div>
                  <div className="obs-metric"><label>Max DD</label><strong>NULL</strong></div>
                  <div className="obs-metric">
                    <label>Win rate</label>
                    <strong>{value(slice?.win_rate, (number) => `${(number * 100).toFixed(1)}%`)}</strong>
                  </div>
                  <div className="obs-metric"><label>Trades</label><strong>NULL</strong></div>
                </div>
                <div className="obs-detail">Open positions ({positions.length})</div>
                <div className="obs-chips">
                  {positions.length > 0
                    ? positions.map((position) => (
                      <span className="obs-chip" key={`${bot.id}-${position.symbol}`}>
                        {position.symbol} · {position.side}
                      </span>
                    ))
                    : <span className="obs-note">{slice ? "None reported" : `NULL · ${unavailable}`}</span>}
                </div>
                <div className="obs-detail">Return attribution</div>
                <div className="obs-note">
                  {attribution.data
                    ? "Fleet-level attribution only; bot scope NULL"
                    : `NULL · ${unavailable}`}
                </div>
                <div className="obs-detail">Biggest win / loss</div>
                <div className="obs-note">
                  NULL · per-bot trade distribution unavailable from current API
                </div>
                <div className="obs-cycle">
                  <span><CalendarClock size={11} /> last cycle</span>
                  <strong>{lastCycle ? new Date(lastCycle).toISOString() : "NULL"}</strong>
                </div>
              </article>
            );
          })}
        </div>
      </section>
      <section className="obs-evidence" aria-label="Evidence deck"><div className="obs-evidence-panel"><div className="obs-section-head"><h2 className="obs-section-title"><BarChart3 size={16}/> Correlated positions</h2><div className="obs-meta">API matrix</div></div>{corr?.tickers?.length?<div className="obs-correlation"><div className="head">symbol</div>{corr.tickers.map(t=><div className="head" key={t}>{t}</div>)}{corr.tickers.map(row=><Fragment key={row}><div className="label">{row}</div>{corr.tickers.map(column=><div className="num" key={`${row}-${column}`}>{corr.matrix[row]?.[column] == null ? "NULL" : corr.matrix[row][column].toFixed(2)}</div>)}</Fragment>)}</div>:<div className="obs-note">NULL · {correlation.isError?unavailable:"No correlation data returned"}</div>}<div className="obs-note" style={{marginTop:10}}>Bot-level correlation is NULL because the current API exposes ticker correlation, not per-strategy correlation.</div></div><div className="obs-evidence-panel"><div className="obs-section-head"><h2 className="obs-section-title"><Activity size={16}/> Recent trade history</h2><div className="obs-meta">latest API events</div></div>{trades.data?.trades?.length?trades.data.trades.map(t=><div className="obs-timeline-row" key={t.trade_id}><span>{new Date(t.closed_at).toLocaleTimeString()}</span><i className="obs-timeline-mark"/><span className="obs-timeline-copy"><strong>{t.symbol}</strong> {t.status.replace("_"," ")}</span><span className={t.pnl_usd==null?"obs-note":t.pnl_usd<0?"negative":"positive"}>{t.pnl_usd==null?"NULL":fmtDollar(t.pnl_usd)}</span></div>):<div className="obs-note">NULL · {trades.isError?unavailable:"No recent trades returned"}</div>}</div></section>
    <footer className="obs-footer"><div className="obs-footer-left"><CheckCircle2 size={13}/> DATA STATUS · {fleet ? "LIVE FEEDS NOMINAL" : "NULL · loading fleet data"}</div><div className="obs-footer-right"><span><Waves size={11}/> API REFRESH</span><span><Gauge size={11}/> RISK {risk.data?"AVAILABLE":"NULL"}</span></div></footer>
  </div></main>;
}