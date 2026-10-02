import { useState } from "react";
import {
  Activity,
  AlertTriangle,
  Check,
  CheckCircle2,
  CircleDashed,
  Clock3,
  FileCheck2,
  Fingerprint,
  Radio,
  ShieldCheck,
  TrendingUp,
  TriangleAlert,
} from "lucide-react";
import { useMathAuditRecent, useMathAuditSummary, useRiskMetrics } from "@/hooks/use-trading";

type AuditStatus = "PASS" | "WARN" | "FAIL";
type AuditFilter = "ALL" | AuditStatus;

function relativeTime(timestamp: string): string {
  const time = new Date(timestamp).getTime();
  if (!Number.isFinite(time)) return "—";
  const diff = Math.max(0, (Date.now() - time) / 1000);
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  return `${Math.round(diff / 3600)}h ago`;
}

function eventClock(timestamp: string): string {
  const time = new Date(timestamp);
  if (Number.isNaN(time.getTime())) return "—";
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(time);
}

function AuditMark({ status }: { status: AuditStatus }) {
  if (status === "PASS") return <CheckCircle2 aria-hidden="true" />;
  if (status === "WARN") return <TriangleAlert aria-hidden="true" />;
  return <AlertTriangle aria-hidden="true" />;
}

export default function SynapticAuditScreen() {
  const [filter, setFilter] = useState<AuditFilter>("ALL");
  const [activeFormula, setActiveFormula] = useState<number | null>(null);
  const summary = useMathAuditSummary(24);
  const recent = useMathAuditRecent(30, filter);
  const riskMetrics = useRiskMetrics();

  const counts = summary.data ? [summary.data.pass, summary.data.warn, summary.data.fail] : null;
  const countTotal = counts?.reduce((sum, count) => sum + count, 0) ?? null;
  const totalChecks = summary.data?.total_logged ?? countTotal;
  const passRate = summary.data?.pass != null && totalChecks != null && totalChecks > 0
    ? ((summary.data.pass / totalChecks) * 100).toFixed(1)
    : "—";
  const hasFailure = (summary.data?.fail ?? 0) > 0;
  const events = recent.data?.rows?.slice(0, 8) ?? [];
  const feedLoading = recent.isLoading && !recent.data;
  const feedUnavailable = recent.isError && !recent.data;
  const summaryUnavailable = summary.isError && !summary.data;

  const riskValue = (value: number | null | undefined) => {
    if (value != null) return value.toFixed(3);
    if (riskMetrics.isLoading && !riskMetrics.data) return "loading…";
    if (riskMetrics.isError || !riskMetrics.data) return "unavailable";
    return "—";
  };

  const formulas = [
    {
      id: "sharpe",
      label: "Sharpe ratio",
      notation: "S = (Rₚ − R𝒻) / σₚ",
      detail: "Excess return · total volatility",
      result: riskValue(riskMetrics.data?.sharpe_ratio),
      value: riskMetrics.data?.sharpe_ratio,
      icon: TrendingUp,
    },
    {
      id: "sortino",
      label: "Sortino ratio",
      notation: "S = (Rₚ − MAR) / σ𝒹",
      detail: "Excess return · downside deviation",
      result: riskValue(riskMetrics.data?.sortino_ratio),
      value: riskMetrics.data?.sortino_ratio,
      icon: Activity,
    },
  ];

  const filters: { id: AuditFilter; label: string; count?: number }[] = [
    { id: "ALL", label: "All events" },
    { id: "PASS", label: "Pass", count: summary.data?.pass },
    { id: "WARN", label: "Warn", count: summary.data?.warn },
    { id: "FAIL", label: "Fail", count: summary.data?.fail },
  ];
  const auditStatus = feedUnavailable
    ? "Audit feed unavailable"
    : feedLoading
      ? "Loading audit feed"
      : recent.isError
        ? "Refresh failed · cached rows"
        : "Rows returned by audit service";

  return (
    <div className="stream-screen stream-screen-math synaptic-audit">
      <style>{`
        .synaptic-audit,.synaptic-audit *{box-sizing:border-box}
        .synaptic-audit{--ink:#edf2e9;--muted:#a4b0a6;--faint:#78877e;--edge:rgba(218,232,216,.13);height:100%;min-height:700px;position:relative;isolation:isolate;overflow:auto;color:var(--ink);background:transparent;font-family:"DM Sans","Avenir Next",ui-sans-serif,system-ui,sans-serif;letter-spacing:-.01em}
        .sa-backdrop{display:none}
        .sa-topbar{height:62px;padding:0 clamp(18px,3vw,34px);display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid rgba(229,239,225,.12);background:rgba(10,22,19,.55);backdrop-filter:blur(22px)}
        .sa-brand,.sa-top-meta,.sa-title-copy,.sa-title-side,.sa-section-title,.sa-filterbar,.sa-event-name,.sa-event-bot,.sa-event-status,.sa-event-time,.sa-value-status{display:flex;align-items:center}
        .sa-brand{gap:11px}.sa-brand-symbol{width:33px;height:33px;display:grid;place-items:center;border:1px solid rgba(193,231,202,.22);border-radius:10px;color:#c3e8ca;background:rgba(184,223,194,.09)}
        .sa-brand-name{color:#edf3e9;font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase}.sa-breadcrumb{margin-left:7px;color:#9ead9f;font-size:11px}.sa-breadcrumb strong{margin-left:8px;color:#e6eee3;font-weight:550}
        .sa-top-meta{gap:11px;color:#aab7aa;font-size:9px}.sa-state{display:flex;align-items:center;gap:7px}.sa-state-dot{width:6px;height:6px;border-radius:50%;background:#9fb39f}.sa-state.is-error{color:#e4c891}.sa-state.is-error .sa-state-dot{background:#e4c891}
        .sa-top-divider{height:16px;width:1px;background:rgba(218,232,216,.18)}.sa-range{display:flex;align-items:center;gap:7px;padding:7px 9px;border:1px solid rgba(225,238,224,.13);border-radius:8px;background:rgba(226,239,223,.06);color:#c9d6c7}
        .sa-main{height:calc(100% - 62px);min-height:650px;padding:20px clamp(18px,3vw,34px);display:flex;flex-direction:column;gap:13px}
        .sa-title-row{min-height:54px;display:flex;align-items:center;justify-content:space-between;gap:18px}.sa-title-copy{gap:13px}.sa-title-icon{width:39px;height:39px;display:grid;place-items:center;border:1px solid rgba(209,230,206,.18);border-radius:12px;color:#c8e6c9;background:rgba(204,227,201,.095)}
        .sa-eyebrow{color:#b3d0b4;font-size:8px;font-weight:700;letter-spacing:.16em;text-transform:uppercase}.sa-heading{margin:4px 0 0;color:#f1f4ec;font-size:22px;font-weight:550;line-height:1;letter-spacing:-.045em}.sa-subtitle{margin-top:5px;color:#aab6aa;font-size:10px}
        .sa-title-side{gap:8px;color:#90a092;font-size:8px;letter-spacing:.09em}.sa-window{display:flex;align-items:center;gap:7px;padding:8px 10px;border:1px solid rgba(225,238,224,.12);border-radius:8px;background:rgba(13,26,22,.5);color:#c3d0c2;font-size:9px}
        .sa-panel{border:1px solid var(--edge);background:linear-gradient(135deg,rgba(31,48,41,.77),rgba(14,27,24,.76));backdrop-filter:blur(22px) saturate(115%);box-shadow:0 14px 36px rgba(2,12,10,.18),inset 0 1px rgba(245,255,244,.05)}
        .sa-summary{min-height:78px;display:grid;grid-template-columns:repeat(3,minmax(0,1fr)) minmax(240px,1.35fr);overflow:hidden;border-radius:13px}
        .sa-stat{padding:12px 15px;display:flex;align-items:center;gap:11px;border-right:1px solid rgba(218,232,216,.1)}.sa-stat-icon{width:29px;height:29px;display:grid;place-items:center;flex:0 0 auto;border-radius:9px}.sa-stat-icon svg{width:14px;height:14px}
        .sa-stat.pass .sa-stat-icon{color:#b9e5c5;background:rgba(126,183,141,.14)}.sa-stat.warn .sa-stat-icon{color:#e7c88e;background:rgba(197,160,95,.14)}.sa-stat.fail .sa-stat-icon{color:#e6a29a;background:rgba(193,106,96,.14)}
        .sa-stat-label{color:#a7b4a8;font-size:9px}.sa-stat-value{margin-top:4px;font:500 19px/1 "IBM Plex Mono",monospace;letter-spacing:-.06em}.sa-stat.pass .sa-stat-value{color:#d5ead7}.sa-stat.warn .sa-stat-value{color:#ecd5a8}.sa-stat.fail .sa-stat-value{color:#edb5ae}
        .sa-rate{padding:12px 17px;display:flex;justify-content:space-between;align-items:center;background:linear-gradient(100deg,rgba(170,207,171,.055),rgba(170,207,171,.015))}
        .sa-rate-label{color:#a7b7a7;font-size:9px;letter-spacing:.1em;text-transform:uppercase}.sa-rate-value{margin-top:3px;color:#e5f0e1;font:500 24px/1 "IBM Plex Mono",monospace;letter-spacing:-.075em}.sa-rate-foot{margin-top:4px;color:#8c9d8e;font-size:8px}.sa-rate-mark{width:39px;height:39px;display:grid;place-items:center;border:1px solid rgba(182,223,187,.28);border-radius:50%;color:#c4e5c9;background:radial-gradient(circle,rgba(182,223,187,.13),rgba(182,223,187,.015))}
        .sa-notice{padding:7px 11px;border:1px solid rgba(218,232,216,.12);border-radius:8px;color:#d9c593;background:rgba(35,31,20,.45);font-size:9px}
        .sa-workbench{min-height:197px;display:grid;grid-template-columns:minmax(0,1.62fr) minmax(280px,.88fr);gap:13px}.sa-formula-panel,.sa-integrity-panel,.sa-events-panel{border-radius:13px}.sa-formula-panel{padding:14px 15px 12px}
        .sa-section-title{justify-content:space-between;gap:10px}.sa-section-label{color:#e1e9df;font-size:11px;font-weight:600}.sa-section-kicker{margin-top:3px;color:#8f9f92;font-size:8px}
        .sa-source{display:inline-flex;align-items:center;gap:6px;padding:6px 8px;border:1px solid rgba(183,219,187,.13);border-radius:7px;color:#a8c5ad;background:rgba(181,216,185,.06);font:8px "IBM Plex Mono",monospace}.sa-source-dot{width:5px;height:5px;border-radius:50%;background:#a9d8b3}
        .sa-formula-list{margin-top:10px;display:grid;gap:7px}.sa-formula{width:100%;min-height:60px;padding:8px 10px;display:grid;grid-template-columns:minmax(138px,.87fr) minmax(155px,1.15fr) minmax(108px,.68fr);align-items:center;gap:9px;border:1px solid rgba(221,236,219,.1);border-radius:9px;background:rgba(5,17,15,.28);color:inherit;text-align:left;cursor:pointer;transition:background .2s,border-color .2s}
        .sa-formula:hover,.sa-formula.is-active{border-color:rgba(187,227,192,.38);background:rgba(183,222,189,.08)}.sa-formula-name{display:flex;align-items:center;gap:8px}.sa-formula-icon{width:25px;height:25px;display:grid;place-items:center;flex:0 0 auto;border-radius:8px;color:#bfdfc0;background:rgba(184,218,185,.1)}.sa-formula-icon svg{width:12px;height:12px}
        .sa-formula-title{color:#e2ebe0;font-size:10px;font-weight:600}.sa-formula-detail{display:block;margin-top:3px;color:#89998d;font-size:7px}.sa-equation{color:#dbe4da;font:500 12px "IBM Plex Mono",monospace;letter-spacing:-.045em;white-space:nowrap}
        .sa-value{padding-left:9px;border-left:1px solid rgba(220,236,217,.1);text-align:right}.sa-value-status{justify-content:flex-end;gap:4px;color:#9eb5a0;font-size:7px;letter-spacing:.07em;text-transform:uppercase}.sa-value-status svg{width:10px;height:10px;color:#b7ddbd}.sa-value-status.is-unavailable,.sa-value-status.is-empty{color:#d5b37c}
        .sa-number{margin-top:3px;color:#cbe7ce;font:500 16px/1 "IBM Plex Mono",monospace;letter-spacing:-.07em}
        .sa-integrity-panel{padding:15px 16px;position:relative;overflow:hidden}.sa-integrity-panel:after{content:"";position:absolute;width:170px;height:170px;right:-80px;bottom:-110px;border:1px solid rgba(193,220,185,.1);border-radius:50%;box-shadow:0 0 0 20px rgba(193,220,185,.018),0 0 0 42px rgba(193,220,185,.014);pointer-events:none}
        .sa-right-head{display:flex;align-items:center;justify-content:space-between}.sa-integrity-tag{display:inline-flex;align-items:center;gap:6px;color:#c7e4c9;font-size:8px;letter-spacing:.085em;text-transform:uppercase}.sa-integrity-tag svg{width:13px;height:13px}.sa-total-mini{color:#94a596;font-size:8px}
        .sa-big-rate{margin-top:13px;display:flex;align-items:baseline;gap:7px}.sa-big-rate strong{color:#e5f0e1;font:500 37px/.95 "IBM Plex Mono",monospace;letter-spacing:-.095em}.sa-big-rate span{color:#93a697;font-size:9px}
        .sa-rate-track{height:4px;margin-top:10px;overflow:hidden;border-radius:4px;background:rgba(230,241,224,.1)}.sa-rate-track span{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,#8fbf98,#c4e5c6)}
        .sa-integrity-copy{margin-top:8px;max-width:280px;color:#a8b6a8;font-size:9px;line-height:1.5}.sa-integrity-footer{margin-top:10px;padding-top:8px;display:flex;justify-content:space-between;gap:6px;border-top:1px solid rgba(218,232,216,.1);color:#92a193;font-size:8px}.sa-integrity-footer strong{color:#c9ddc8;font:500 9px "IBM Plex Mono",monospace}
        .sa-events-panel{min-height:180px;flex:1;display:flex;flex-direction:column;padding:11px 15px 8px}.sa-events-top{display:flex;justify-content:space-between;align-items:center;gap:10px;min-height:28px}.sa-events-heading{display:flex;align-items:center;gap:8px}.sa-events-icon{width:13px;height:13px;color:#bbd9bd}.sa-events-title{color:#e2eae0;font-size:11px;font-weight:600}.sa-events-count{color:#8fa091;font:8px "IBM Plex Mono",monospace}
        .sa-filterbar{gap:3px}.sa-filter{display:flex;align-items:center;gap:5px;padding:5px 7px;border:1px solid transparent;border-radius:6px;background:transparent;color:#9eac9f;cursor:pointer;font:500 8px "DM Sans",sans-serif;transition:color .18s,background .18s,border-color .18s}
        .sa-filter:hover{color:#e6eee2}.sa-filter.is-selected{border-color:rgba(218,234,215,.15);color:#dceadc;background:rgba(208,229,204,.085)}.sa-filter-count{color:#758678;font:7px "IBM Plex Mono",monospace}
        .sa-table-head,.sa-event-row{display:grid;grid-template-columns:minmax(210px,1.45fr) minmax(170px,1fr) 75px 110px;align-items:center;column-gap:10px}.sa-table-head{min-height:25px;margin-top:5px;border-bottom:1px solid rgba(220,234,217,.1);color:#819183;font-size:7px;text-transform:uppercase;letter-spacing:.11em}
        .sa-event-list{min-height:0;overflow-y:auto;scrollbar-width:thin;scrollbar-color:rgba(190,215,189,.23) transparent}.sa-event-row{min-height:31px;border-bottom:1px solid rgba(220,234,217,.075);color:#d1dbd0;font-size:9px}.sa-event-row:last-child{border-bottom:0}
        .sa-event-name{min-width:0;gap:7px}.sa-event-mark{width:14px;height:14px;display:grid;place-items:center;flex:0 0 auto}.sa-event-mark svg{width:11px;height:11px}.sa-event-mark.pass,.sa-event-status.pass{color:#b9ddbf}.sa-event-mark.warn,.sa-event-status.warn{color:#e6ca94}.sa-event-mark.fail,.sa-event-status.fail{color:#e8aaa1}
        .sa-event-formula{overflow:hidden;color:#dce5da;font-weight:520;text-overflow:ellipsis;white-space:nowrap}.sa-event-bot{gap:5px;color:#a9b6a8;font:8px "IBM Plex Mono",monospace}.sa-event-bot svg{width:10px;height:10px;color:#809482}
        .sa-event-status{gap:5px;font-size:8px;font-weight:650;letter-spacing:.07em}.sa-status-dot{width:5px;height:5px;border-radius:50%;background:currentColor}.sa-event-time{display:flex;justify-content:space-between;color:#c1cec0;font:8px "IBM Plex Mono",monospace}.sa-event-time span{color:#829184;font-family:"DM Sans",sans-serif}
        .sa-empty{min-height:94px;display:flex;align-items:center;justify-content:center;gap:8px;color:#c9b482;font-size:10px}.sa-empty svg{width:13px;height:13px}
        .sa-feed-note{padding-top:6px;display:flex;align-items:center;justify-content:space-between;gap:8px;color:#829084;font-size:7px}.sa-feed-note svg{width:10px;height:10px;color:#a4c4a8}
        .sa-button-focus:focus-visible{outline:2px solid #c4e5c6;outline-offset:2px}
        @media(max-width:900px){.synaptic-audit{min-height:740px}.sa-main{height:auto;min-height:650px;padding:16px}.sa-summary{grid-template-columns:repeat(2,minmax(0,1fr))}.sa-workbench{grid-template-columns:1fr}.sa-integrity-panel{min-height:170px}.sa-events-panel{min-height:260px}.sa-topbar{padding:0 16px}.sa-table-head,.sa-event-row{grid-template-columns:minmax(150px,1.2fr) minmax(120px,1fr) 65px 90px;gap:7px}}
        @media(max-width:600px){.sa-main{padding:13px}.sa-title-row{align-items:flex-start}.sa-title-side{display:none}.sa-top-meta{gap:7px;font-size:8px}.sa-range{padding:6px}.sa-brand-name{display:none}.sa-formula{grid-template-columns:minmax(110px,.9fr) minmax(115px,1fr) minmax(90px,.7fr);gap:5px;padding:8px}.sa-equation{font-size:9px}.sa-formula-detail{font-size:6px}.sa-events-panel{padding:9px}.sa-events-top{align-items:flex-start;flex-direction:column}.sa-table-head,.sa-event-row{grid-template-columns:minmax(100px,1.2fr) minmax(85px,1fr) 56px 74px;gap:5px}.sa-table-head{font-size:6px}.sa-event-row{font-size:8px}.sa-event-bot{font-size:7px}.sa-event-time{font-size:7px}}
        @media(prefers-reduced-motion:reduce){.sa-formula,.sa-filter{transition:none}}
      `}</style>
      <div className="sa-backdrop" aria-hidden="true" />
      <header className="sa-topbar">
        <div className="sa-brand">
          <span className="sa-brand-symbol"><Fingerprint size={16} strokeWidth={1.6} /></span>
          <span className="sa-brand-name">Synaptic</span>
          <span className="sa-breadcrumb">/ <strong>Audit</strong></span>
        </div>
        <div className="sa-top-meta">
          <span className={`sa-state ${feedUnavailable ? "is-error" : ""}`} data-testid="audit-feed-status" aria-live="polite">
            <i className="sa-state-dot" />{auditStatus}
          </span>
          <span className="sa-top-divider" />
          <span className="sa-range"><Clock3 size={11} /> Rolling 24 hours</span>
        </div>
      </header>

      <main className="sa-main">
        <div className="sa-title-row">
          <div className="sa-title-copy">
            <div className="sa-title-icon"><FileCheck2 size={19} strokeWidth={1.5} /></div>
            <div>
              <div className="sa-eyebrow">Fleet integrity · quantitative checks</div>
              <h1 className="sa-heading">Metric audit</h1>
              <div className="sa-subtitle">Reported audit events and risk metric values, with source availability made explicit.</div>
            </div>
          </div>
          <div className="sa-title-side">
            <span>LAST AUDIT</span>
            <span className="sa-window"><Radio size={11} />{summary.data?.last_audit_ts ? eventClock(summary.data.last_audit_ts) : summaryUnavailable ? "Unavailable" : "—"}</span>
          </div>
        </div>

        {summary.isError && summary.data && <div className="sa-notice" role="status">Audit summary refresh failed · showing the last response</div>}
        {summaryUnavailable && <div className="sa-notice" role="status">Audit summary unavailable · counts and pass rate are not inferred</div>}

        <section className="sa-summary sa-panel" aria-label="Audit totals">
          <div className="sa-stat pass"><div className="sa-stat-icon"><Check size={16} /></div><div><div className="sa-stat-label">Passed</div><div className="sa-stat-value" data-testid="audit-pass-count">{summary.data?.pass?.toLocaleString() ?? (summary.isLoading ? "Loading…" : "—")}</div></div></div>
          <div className="sa-stat warn"><div className="sa-stat-icon"><TriangleAlert size={15} /></div><div><div className="sa-stat-label">Warnings</div><div className="sa-stat-value" data-testid="audit-warn-count">{summary.data?.warn?.toLocaleString() ?? (summary.isLoading ? "Loading…" : "—")}</div></div></div>
          <div className="sa-stat fail"><div className="sa-stat-icon"><AlertTriangle size={15} /></div><div><div className="sa-stat-label">Failed</div><div className="sa-stat-value" data-testid="audit-fail-count">{summary.data?.fail?.toLocaleString() ?? (summary.isLoading ? "Loading…" : "—")}</div></div></div>
          <div className="sa-rate">
            <div><div className="sa-rate-label">Checks passing</div><div className="sa-rate-value" data-testid="audit-pass-rate">{passRate}<span style={{ fontSize: 12, letterSpacing: "-.02em" }}> {passRate === "—" ? "" : "%"}</span></div><div className="sa-rate-foot">{summary.data?.total_logged?.toLocaleString() ?? "—"} checks logged in this window</div></div>
            <div className="sa-rate-mark"><ShieldCheck size={20} strokeWidth={1.5} /></div>
          </div>
        </section>

        <section className="sa-workbench" aria-label="Formula references and risk metrics">
          <div className="sa-formula-panel sa-panel">
            <div className="sa-section-title">
              <div><div className="sa-section-label">Reference formulas</div><div className="sa-section-kicker">Canonical definitions · values from the risk metric service</div></div>
              <div className="sa-source"><span className="sa-source-dot" /> /performance/risk-metrics</div>
            </div>
            <div className="sa-formula-list">
              {formulas.map((formula, index) => {
                const FormulaIcon = formula.icon;
                const unavailable = formula.result === "unavailable";
                const empty = formula.result === "—";
                const stale = riskMetrics.isError && formula.value != null;
                const valueStatus = riskMetrics.isLoading && !riskMetrics.data
                  ? "AWAITING DATA"
                  : unavailable
                    ? "UNAVAILABLE"
                    : stale
                      ? "CACHED RESPONSE"
                      : empty
                        ? "NO VALUE"
                        : "VALUE RECEIVED";
                return (
                  <button
                    type="button"
                    key={formula.id}
                    onClick={() => setActiveFormula(activeFormula === index ? null : index)}
                    className={`sa-formula sa-button-focus ${activeFormula === index ? "is-active" : ""}`}
                    aria-pressed={activeFormula === index}
                    aria-label={`Inspect ${formula.label}`}
                    data-testid={`audit-formula-${formula.id}`}
                  >
                    <span className="sa-formula-name"><span className="sa-formula-icon"><FormulaIcon /></span><span><span className="sa-formula-title">{formula.label}</span><span className="sa-formula-detail">{formula.detail}</span></span></span>
                    <span className="sa-equation">{formula.notation}</span>
                    <span className="sa-value">
                      <span className={`sa-value-status ${unavailable || empty ? "is-unavailable" : ""}`}>
                        {riskMetrics.isLoading && !riskMetrics.data ? <CircleDashed /> : unavailable || empty ? <AlertTriangle /> : <CheckCircle2 />}
                        {valueStatus}
                      </span>
                      <span className="sa-number">{formula.result}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          <aside className="sa-integrity-panel sa-panel">
            <div className="sa-right-head"><span className="sa-integrity-tag"><ShieldCheck />Reported audit ratio</span><span className="sa-total-mini">ROLLING 24H</span></div>
            <div className="sa-big-rate"><strong>{passRate}{passRate === "—" ? "" : "%"}</strong><span>checks passed</span></div>
            <div className="sa-rate-track"><span style={{ width: passRate === "—" ? "0%" : `${passRate}%` }} /></div>
            <div className="sa-integrity-copy">
              {summaryUnavailable
                ? "Audit summary unavailable. No pass rate or check counts are inferred."
                : summary.isLoading && !summary.data
                  ? "Awaiting the audit summary response. Formula references remain visible while data loads."
                  : summary.isError
                    ? "The audit summary refresh failed. This ratio is calculated only from the last reported summary."
                    : hasFailure
                      ? `${summary.data?.fail.toLocaleString()} failed checks were reported. Risk metric values are displayed beside definitions, not recalculated here.`
                      : riskMetrics.isError
                        ? "Risk metric service unavailable. Audit events remain independently available below."
                        : "Risk metric service values are shown beside their canonical formula references; this view does not recompute them."}
            </div>
            <div className="sa-integrity-footer"><span>Checks logged</span><strong>{totalChecks?.toLocaleString() ?? "—"}</strong><span>Window <strong>24h</strong></span></div>
          </aside>
        </section>

        <section className="sa-events-panel sa-panel" aria-label="Recent audit events">
          <div className="sa-events-top">
            <div className="sa-events-heading"><Activity className="sa-events-icon" /><span className="sa-events-title">Recent audit events</span><span className="sa-events-count">{feedUnavailable || feedLoading ? "—" : `${events.length} shown`}</span></div>
            <div className="sa-filterbar" role="group" aria-label="Filter audit events">
              {filters.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setFilter(item.id)}
                  className={`sa-filter sa-button-focus ${filter === item.id ? "is-selected" : ""}`}
                  aria-pressed={filter === item.id}
                  data-testid={`audit-filter-${item.id.toLowerCase()}`}
                >
                  {item.label}{item.count != null && <span className="sa-filter-count">{item.count.toLocaleString()}</span>}
                </button>
              ))}
            </div>
          </div>
          <div className="sa-table-head"><span>Audit check</span><span>Bot</span><span>Status</span><span>Recorded</span></div>
          {feedLoading ? (
            <div className="sa-empty" role="status"><CircleDashed />Loading audit events…</div>
          ) : feedUnavailable ? (
            <div className="sa-empty" role="status"><AlertTriangle />Audit event feed unavailable</div>
          ) : events.length === 0 ? (
            <div className="sa-empty"><CircleDashed />No {filter.toLowerCase()} events in this window</div>
          ) : (
            <div className="sa-event-list">
              {events.map((event, index) => {
                const status = event.status as AuditStatus;
                return (
                  <div className="sa-event-row" key={`${event.audit_timestamp}-${event.bot_id}-${index}`} data-testid={`audit-event-${status.toLowerCase()}-${index}`}>
                    <div className="sa-event-name"><span className={`sa-event-mark ${status.toLowerCase()}`}><AuditMark status={status} /></span><span className="sa-event-formula">{event.formula_name}</span></div>
                    <span className="sa-event-bot"><Fingerprint />{event.bot_id || "Unattributed"}</span>
                    <span className={`sa-event-status ${status.toLowerCase()}`}><i className="sa-status-dot" />{status}</span>
                    <span className="sa-event-time">{eventClock(event.audit_timestamp)}<span>{relativeTime(event.audit_timestamp)}</span></span>
                  </div>
                );
              })}
            </div>
          )}
          <div className="sa-feed-note"><span><Radio /> Recent rows returned by the math audit service</span><span>{recent.isError && recent.data ? "Refresh failed · showing cached rows" : "/admin/math-audit/recent"}</span></div>
        </section>
      </main>
    </div>
  );
}