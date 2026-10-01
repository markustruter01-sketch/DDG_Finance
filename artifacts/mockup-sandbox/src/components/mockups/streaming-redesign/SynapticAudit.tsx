import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleDashed,
  Clock3,
  Command,
  FileCheck2,
  Fingerprint,
  Leaf,
  Radio,
  ShieldCheck,
  TrendingUp,
  TriangleAlert,
} from "lucide-react";
import {
  useMathAuditRecent,
  useMathAuditSummary,
  useRiskMetrics,
} from "../streaming-current/_shared/mockData";

type AuditStatus = "PASS" | "WARN" | "FAIL";
type AuditFilter = "ALL" | AuditStatus;

function relativeTime(timestamp: string): string {
  try {
    const diff = (Date.now() - new Date(timestamp).getTime()) / 1000;
    if (diff < 60) return `${Math.round(diff)}s ago`;
    if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
    return `${Math.round(diff / 3600)}h ago`;
  } catch {
    return "—";
  }
}

function eventClock(timestamp: string): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(new Date(timestamp));
  } catch {
    return "—";
  }
}

function AuditMark({ status }: { status: AuditStatus }) {
  if (status === "PASS") return <CheckCircle2 aria-hidden="true" />;
  if (status === "WARN") return <TriangleAlert aria-hidden="true" />;
  return <AlertTriangle aria-hidden="true" />;
}

export function SynapticAudit() {
  const { data: summary } = useMathAuditSummary(24);
  const { data: recentData } = useMathAuditRecent(10, "ALL");
  const riskMetrics = useRiskMetrics();
  const [activeFormula, setActiveFormula] = useState<number | null>(null);
  const [filter, setFilter] = useState<AuditFilter>("ALL");

  useEffect(() => {
    let nextFormula = 0;
    let pulseTimeout: number | undefined;
    const pulseInterval = window.setInterval(() => {
      setActiveFormula(nextFormula);
      nextFormula = (nextFormula + 1) % 2;
      if (pulseTimeout !== undefined) window.clearTimeout(pulseTimeout);
      pulseTimeout = window.setTimeout(() => setActiveFormula(null), 1500);
    }, 3500);
    return () => {
      window.clearInterval(pulseInterval);
      if (pulseTimeout !== undefined) window.clearTimeout(pulseTimeout);
    };
  }, []);

  const auditCounts =
    summary == null ? null : [summary.pass, summary.warn, summary.fail];
  const totalChecks =
    auditCounts?.every((count) => count != null)
      ? auditCounts.reduce((sum, count) => sum + count, 0)
      : null;
  const passRate =
    totalChecks != null && totalChecks > 0 && summary?.pass != null
      ? ((summary.pass / totalChecks) * 100).toFixed(1)
      : "—";
  const hasError = summary?.fail != null && summary.fail > 0;
  const rawEvents = recentData?.rows?.slice(0, 8) ?? [];
  const events = useMemo(
    () => rawEvents.filter((event) => filter === "ALL" || event.status === filter),
    [rawEvents, filter],
  );
  const feedUnavailable = recentData?.rows == null;
  const riskValue = (value: number | null | undefined) => {
    if (riskMetrics.isLoading) return "loading…";
    if (riskMetrics.isError) return "unavailable";
    return value != null ? value.toFixed(3) : "—";
  };

  const formulas = [
    {
      id: "sharpe",
      label: "Sharpe ratio",
      notation: "S = (Rₚ − R𝒻) / σₚ",
      detail: "Excess return · total volatility",
      result: riskValue(riskMetrics.data?.sharpe_ratio),
      icon: TrendingUp,
    },
    {
      id: "sortino",
      label: "Sortino ratio",
      notation: "S = (Rₚ − MAR) / σ𝒹",
      detail: "Excess return · downside deviation",
      result: riskValue(riskMetrics.data?.sortino_ratio),
      icon: Activity,
    },
  ];

  const statuses: { id: AuditFilter; label: string; count?: number }[] = [
    { id: "ALL", label: "All events" },
    { id: "PASS", label: "Pass", count: summary?.pass },
    { id: "WARN", label: "Warn", count: summary?.warn },
    { id: "FAIL", label: "Fail", count: summary?.fail },
  ];

  return (
    <div className="synaptic-audit">
      <style>{`
        .synaptic-audit, .synaptic-audit * { box-sizing: border-box; }
        .synaptic-audit {
          --ink: #edf2e9;
          --muted: #a4b0a6;
          --faint: #78877e;
          --glass: rgba(16, 29, 26, .70);
          --glass-deep: rgba(11, 22, 20, .84);
          --edge: rgba(218, 232, 216, .13);
          --mint: #b7e6c8;
          width: 100%;
          height: 100%;
          min-height: 760px;
          position: relative;
          isolation: isolate;
          overflow: hidden;
          color: var(--ink);
          background: #172522;
          font-family: "DM Sans", "Avenir Next", ui-sans-serif, system-ui, sans-serif;
          letter-spacing: -.01em;
        }
        .sa-backdrop, .sa-shade, .sa-grain { position: absolute; inset: 0; pointer-events: none; }
        .sa-backdrop {
          z-index: -3;
          background-image: url("/__mockup/images/streaming-forest-atmosphere.jpg");
          background-position: center 54%;
          background-size: cover;
          filter: saturate(.63) brightness(.64);
          transform: scale(1.015);
        }
        .sa-shade {
          z-index: -2;
          background:
            linear-gradient(90deg, rgba(8, 18, 17, .82) 0%, rgba(10, 21, 19, .71) 54%, rgba(8, 18, 17, .79) 100%),
            linear-gradient(180deg, rgba(9, 20, 18, .48) 0%, rgba(8, 18, 17, .31) 40%, rgba(8, 18, 17, .83) 100%);
        }
        .sa-grain {
          z-index: -1;
          opacity: .12;
          background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.88' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.22'/%3E%3C/svg%3E");
        }
        .sa-topbar {
          height: 66px;
          padding: 0 34px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          border-bottom: 1px solid rgba(229, 239, 225, .12);
          background: rgba(10, 22, 19, .57);
          backdrop-filter: blur(22px);
        }
        .sa-brand, .sa-brand-symbol, .sa-top-meta, .sa-breadcrumb, .sa-live,
        .sa-range, .sa-title-row, .sa-section-title, .sa-filterbar, .sa-filter,
        .sa-event-name, .sa-event-bot, .sa-status, .sa-right-head, .sa-value-status {
          display: flex;
          align-items: center;
        }
        .sa-brand { gap: 12px; }
        .sa-brand-symbol {
          width: 34px; height: 34px; justify-content: center;
          border: 1px solid rgba(193, 231, 202, .22);
          border-radius: 11px;
          color: #c3e8ca;
          background: rgba(184, 223, 194, .10);
        }
        .sa-brand-name {
          color: #edf3e9; font-size: 12px; font-weight: 650;
          letter-spacing: .12em; text-transform: uppercase;
        }
        .sa-breadcrumb { margin-left: 16px; gap: 9px; color: #9ead9f; font-size: 12px; }
        .sa-breadcrumb strong { color: #e6eee3; font-weight: 520; }
        .sa-top-meta { gap: 19px; color: #b9c5b8; font-size: 11px; }
        .sa-live {
          gap: 8px; color: #c2e9c9; font-size: 10px; font-weight: 700;
          letter-spacing: .11em; text-transform: uppercase;
        }
        .sa-live-dot {
          width: 7px; height: 7px; border-radius: 50%;
          background: #a9ddb7; box-shadow: 0 0 14px rgba(169, 221, 183, .65);
        }
        .sa-top-divider { width: 1px; height: 18px; background: rgba(218, 232, 216, .18); }
        .sa-range {
          gap: 8px; padding: 8px 11px; border: 1px solid rgba(225, 238, 224, .13);
          border-radius: 9px; background: rgba(226, 239, 223, .07);
          color: #d4dfd2; font-size: 11px;
        }
        .sa-main {
          height: calc(100% - 66px);
          min-height: 694px;
          padding: 23px 34px 21px;
          display: flex;
          flex-direction: column;
          gap: 15px;
        }
        .sa-title-row { min-height: 54px; justify-content: space-between; }
        .sa-title-copy { display: flex; align-items: center; gap: 14px; }
        .sa-title-icon {
          width: 42px; height: 42px; display: grid; place-items: center;
          border-radius: 14px; border: 1px solid rgba(209, 230, 206, .18);
          color: #c8e6c9; background: rgba(204, 227, 201, .095);
          box-shadow: inset 0 1px rgba(255,255,255,.1);
        }
        .sa-eyebrow {
          color: #b3d0b4; font-size: 9px; font-weight: 700;
          text-transform: uppercase; letter-spacing: .18em;
        }
        .sa-heading {
          margin: 4px 0 0; color: #f1f4ec; font-size: 24px;
          line-height: 1; font-weight: 560; letter-spacing: -.045em;
        }
        .sa-subtitle { margin-top: 6px; color: #aab6aa; font-size: 11px; }
        .sa-title-side { display: flex; align-items: center; gap: 11px; }
        .sa-window {
          display: flex; align-items: center; gap: 8px; padding: 9px 11px;
          border: 1px solid rgba(225,238,224,.12); border-radius: 9px;
          background: rgba(13, 26, 22, .50); color: #c3d0c2; font-size: 11px;
        }
        .sa-window svg { color: #a9c3a9; }
        .sa-meta-caption { color: #8f9e92; font-size: 10px; letter-spacing: .05em; }
        .sa-panel {
          border: 1px solid var(--edge);
          background: linear-gradient(135deg, rgba(31, 48, 41, .74), rgba(14, 27, 24, .71));
          backdrop-filter: blur(23px) saturate(115%);
          box-shadow: 0 16px 42px rgba(2, 12, 10, .19), inset 0 1px rgba(245, 255, 244, .06);
        }
        .sa-summary {
          min-height: 83px; display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr)) minmax(275px, 1.35fr);
          overflow: hidden; border-radius: 14px;
        }
        .sa-stat {
          padding: 14px 18px; display: flex; align-items: center; gap: 13px;
          border-right: 1px solid rgba(218, 232, 216, .10);
        }
        .sa-stat-icon {
          width: 31px; height: 31px; display: grid; place-items: center;
          flex: 0 0 auto; border-radius: 10px;
        }
        .sa-stat-icon svg { width: 15px; height: 15px; }
        .sa-stat.pass .sa-stat-icon { color: #b9e5c5; background: rgba(126, 183, 141, .14); }
        .sa-stat.warn .sa-stat-icon { color: #e7c88e; background: rgba(197, 160, 95, .14); }
        .sa-stat.fail .sa-stat-icon { color: #e6a29a; background: rgba(193, 106, 96, .14); }
        .sa-stat-label { color: #a7b4a8; font-size: 10px; letter-spacing: .035em; }
        .sa-stat-value { margin-top: 4px; font: 500 21px/1 "IBM Plex Mono", "SFMono-Regular", monospace; letter-spacing: -.06em; }
        .sa-stat.pass .sa-stat-value { color: #d5ead7; }
        .sa-stat.warn .sa-stat-value { color: #ecd5a8; }
        .sa-stat.fail .sa-stat-value { color: #edb5ae; }
        .sa-rate {
          padding: 13px 20px; display: flex; justify-content: space-between; align-items: center;
          background: linear-gradient(100deg, rgba(170, 207, 171, .055), rgba(170, 207, 171, .015));
        }
        .sa-rate-label {
          color: #a7b7a7; font-size: 10px; letter-spacing: .10em; text-transform: uppercase;
        }
        .sa-rate-value { margin-top: 4px; color: #e5f0e1; font: 500 26px/1 "IBM Plex Mono", monospace; letter-spacing: -.075em; }
        .sa-rate-foot { margin-top: 5px; color: #8c9d8e; font-size: 9px; }
        .sa-rate-mark {
          width: 46px; height: 46px; display: grid; place-items: center; border-radius: 50%;
          border: 1px solid rgba(182, 223, 187, .28);
          color: #c4e5c9; background: radial-gradient(circle, rgba(182,223,187,.13), rgba(182,223,187,.015));
        }
        .sa-workbench {
          min-height: 208px;
          display: grid; grid-template-columns: minmax(0, 1.62fr) minmax(310px, .88fr);
          gap: 15px;
        }
        .sa-formula-panel, .sa-integrity-panel, .sa-events-panel { border-radius: 14px; }
        .sa-formula-panel { padding: 16px 18px 14px; }
        .sa-section-title { justify-content: space-between; gap: 12px; }
        .sa-section-label {
          color: #e1e9df; font-size: 12px; font-weight: 600; letter-spacing: -.01em;
        }
        .sa-section-kicker {
          margin-top: 4px; color: #8f9f92; font-size: 9px; letter-spacing: .035em;
        }
        .sa-source {
          display: inline-flex; align-items: center; gap: 7px; padding: 6px 8px;
          border-radius: 7px; color: #a8c5ad; font-size: 9px;
          border: 1px solid rgba(183, 219, 187, .13); background: rgba(181, 216, 185, .06);
        }
        .sa-source-dot { width: 5px; height: 5px; background: #a9d8b3; border-radius: 50%; }
        .sa-formula-list { margin-top: 13px; display: grid; gap: 8px; }
        .sa-formula {
          min-height: 64px; width: 100%; display: grid;
          grid-template-columns: minmax(145px, .87fr) minmax(210px, 1.25fr) minmax(120px, .68fr);
          align-items: center; gap: 12px; padding: 10px 13px;
          border: 1px solid rgba(221, 236, 219, .10);
          border-radius: 10px; background: rgba(5, 17, 15, .28);
          color: inherit; text-align: left; cursor: pointer;
          transition: background .22s ease, border-color .22s ease, transform .22s ease;
        }
        .sa-formula:hover { transform: translateY(-1px); background: rgba(195, 223, 194, .07); border-color: rgba(195, 223, 194, .27); }
        .sa-formula.is-active { border-color: rgba(187, 227, 192, .43); background: rgba(183, 222, 189, .085); }
        .sa-formula-name { display: flex; align-items: center; gap: 9px; }
        .sa-formula-icon {
          width: 27px; height: 27px; display: grid; place-items: center; flex: 0 0 auto;
          border-radius: 8px; color: #bfdfc0; background: rgba(184, 218, 185, .10);
        }
        .sa-formula-icon svg { width: 13px; height: 13px; }
        .sa-formula-title { color: #e2ebe0; font-size: 11px; font-weight: 600; }
        .sa-formula-detail { margin-top: 3px; color: #89998d; font-size: 8px; }
        .sa-equation {
          color: #dbe4da; font: 500 14px/1.2 "IBM Plex Mono", "SFMono-Regular", monospace;
          letter-spacing: -.045em; white-space: nowrap;
        }
        .sa-value {
          padding-left: 14px; border-left: 1px solid rgba(220, 236, 217, .10);
          text-align: right;
        }
        .sa-value-status {
          justify-content: flex-end; gap: 5px; color: #9eb5a0;
          font-size: 8px; text-transform: uppercase; letter-spacing: .09em;
        }
        .sa-value-status svg { width: 10px; height: 10px; color: #b7ddbd; }
        .sa-value-status.is-unavailable, .sa-value-status.is-empty { color: #d5b37c; }
        .sa-number {
          margin-top: 3px; color: #cbe7ce; font: 500 19px/1 "IBM Plex Mono", monospace;
          letter-spacing: -.075em;
        }
        .sa-integrity-panel { padding: 17px 18px; position: relative; overflow: hidden; }
        .sa-integrity-panel:after {
          content: ""; position: absolute; width: 200px; height: 200px; right: -95px; bottom: -130px;
          border: 1px solid rgba(193, 220, 185, .10); border-radius: 50%;
          box-shadow: 0 0 0 22px rgba(193,220,185,.018), 0 0 0 47px rgba(193,220,185,.014);
          pointer-events: none;
        }
        .sa-right-head { justify-content: space-between; }
        .sa-integrity-tag {
          display: inline-flex; align-items: center; gap: 6px; color: #c7e4c9;
          font-size: 9px; letter-spacing: .085em; text-transform: uppercase;
        }
        .sa-integrity-tag svg { width: 13px; height: 13px; }
        .sa-total-mini { color: #94a596; font-size: 9px; }
        .sa-big-rate { margin-top: 18px; display: flex; align-items: baseline; gap: 8px; }
        .sa-big-rate strong {
          color: #e5f0e1; font: 500 43px/.95 "IBM Plex Mono", monospace;
          letter-spacing: -.095em;
        }
        .sa-big-rate span { color: #93a697; font-size: 10px; }
        .sa-rate-track { height: 4px; margin-top: 13px; overflow: hidden; border-radius: 4px; background: rgba(230,241,224,.10); }
        .sa-rate-track span { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg,#8fbf98,#c4e5c6); }
        .sa-integrity-copy { margin-top: 9px; max-width: 295px; color: #a8b6a8; font-size: 10px; line-height: 1.5; }
        .sa-integrity-footer {
          margin-top: 14px; padding-top: 11px; display: flex; justify-content: space-between;
          border-top: 1px solid rgba(218,232,216,.10); color: #92a193; font-size: 9px;
        }
        .sa-integrity-footer strong { color: #c9ddc8; font: 500 10px "IBM Plex Mono", monospace; }
        .sa-events-panel {
          flex: 1; min-height: 0; display: flex; flex-direction: column;
          padding: 14px 18px 10px;
        }
        .sa-events-top { display: flex; justify-content: space-between; align-items: center; min-height: 29px; }
        .sa-events-heading { display: flex; align-items: center; gap: 9px; }
        .sa-events-icon { color: #bbd9bd; width: 14px; height: 14px; }
        .sa-events-title { color: #e2eae0; font-size: 12px; font-weight: 600; }
        .sa-events-count { color: #8fa091; font: 9px "IBM Plex Mono", monospace; }
        .sa-filterbar { gap: 4px; }
        .sa-filter {
          gap: 6px; padding: 6px 8px; border: 1px solid transparent; border-radius: 7px;
          background: transparent; color: #9eac9f; cursor: pointer;
          font: 500 9px "DM Sans", ui-sans-serif, sans-serif;
          transition: color .18s ease, background .18s ease, border-color .18s ease;
        }
        .sa-filter:hover { color: #e6eee2; }
        .sa-filter.is-selected {
          color: #dceadc; border-color: rgba(218,234,215,.15);
          background: rgba(208,229,204,.085);
        }
        .sa-filter-count { color: #758678; font: 8px "IBM Plex Mono", monospace; }
        .sa-table-head, .sa-event-row {
          display: grid; grid-template-columns: minmax(260px, 1.45fr) minmax(220px, 1fr) 112px 130px;
          align-items: center; column-gap: 14px;
        }
        .sa-table-head {
          min-height: 28px; margin-top: 7px;
          border-bottom: 1px solid rgba(220,234,217,.10);
          color: #819183; font-size: 8px; text-transform: uppercase; letter-spacing: .12em;
        }
        .sa-event-list { min-height: 0; overflow-y: auto; scrollbar-width: thin; scrollbar-color: rgba(190,215,189,.23) transparent; }
        .sa-event-row {
          min-height: 34px; border-bottom: 1px solid rgba(220,234,217,.075);
          color: #d1dbd0; font-size: 10px;
        }
        .sa-event-row:last-child { border-bottom: 0; }
        .sa-event-name { gap: 9px; min-width: 0; }
        .sa-event-mark { width: 15px; height: 15px; display: grid; place-items: center; flex: 0 0 auto; }
        .sa-event-mark svg { width: 12px; height: 12px; }
        .sa-event-mark.pass, .sa-event-status.pass { color: #b9ddbf; }
        .sa-event-mark.warn, .sa-event-status.warn { color: #e6ca94; }
        .sa-event-mark.fail, .sa-event-status.fail { color: #e8aaa1; }
        .sa-event-formula { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #dce5da; font-weight: 520; }
        .sa-event-bot { gap: 7px; color: #a9b6a8; font: 9px "IBM Plex Mono", monospace; }
        .sa-event-bot svg { width: 11px; height: 11px; color: #809482; }
        .sa-event-status { gap: 6px; font-size: 9px; font-weight: 650; letter-spacing: .08em; }
        .sa-event-status .sa-status-dot { width: 5px; height: 5px; border-radius: 50%; background: currentColor; }
        .sa-event-time { display: flex; justify-content: space-between; color: #c1cec0; font: 9px "IBM Plex Mono", monospace; }
        .sa-event-time span { color: #829184; font-family: "DM Sans", sans-serif; }
        .sa-empty {
          min-height: 112px; display: flex; align-items: center; justify-content: center;
          gap: 9px; color: #c9b482; font-size: 11px;
        }
        .sa-empty svg { width: 14px; height: 14px; }
        .sa-footline { display: flex; align-items: center; justify-content: space-between; padding-top: 5px; color: #829084; font-size: 8px; }
        .sa-footline-left { display: flex; align-items: center; gap: 7px; }
        .sa-footline-left svg { width: 10px; height: 10px; color: #a4c4a8; }
        .sa-footline-right { color: #94a394; font: 8px "IBM Plex Mono", monospace; }
        @media (max-width: 900px) {
          .synaptic-audit { min-height: 760px; overflow-y: auto; }
          .sa-main { min-height: auto; height: auto; padding: 19px; }
          .sa-summary { grid-template-columns: repeat(2,minmax(0,1fr)); }
          .sa-workbench { grid-template-columns: 1fr; }
          .sa-integrity-panel { min-height: 190px; }
          .sa-events-panel { min-height: 280px; }
          .sa-table-head, .sa-event-row { grid-template-columns: minmax(160px,1.2fr) minmax(130px,1fr) 72px 95px; gap: 8px; }
          .sa-topbar { padding: 0 19px; }
        }
      `}</style>

      <div className="sa-backdrop" />
      <div className="sa-shade" />
      <div className="sa-grain" />

      <header className="sa-topbar">
        <div className="sa-brand">
          <div className="sa-brand-symbol"><Fingerprint size={17} strokeWidth={1.6} /></div>
          <span className="sa-brand-name">Synaptic</span>
          <span className="sa-breadcrumb"><span>/</span><strong>Audit</strong></span>
        </div>
        <div className="sa-top-meta">
          <span className="sa-live"><i className="sa-live-dot" />Stream active</span>
          <span className="sa-top-divider" />
          <span>Audit service <strong style={{ color: "#d8e4d6", fontWeight: 550 }}>healthy</strong></span>
          <span className="sa-range"><Clock3 size={12} /> Rolling 24 hours <ChevronDown size={12} /></span>
        </div>
      </header>

      <main className="sa-main">
        <div className="sa-title-row">
          <div className="sa-title-copy">
            <div className="sa-title-icon"><FileCheck2 size={20} strokeWidth={1.5} /></div>
            <div>
              <div className="sa-eyebrow">Fleet integrity · quantitative checks</div>
              <h1 className="sa-heading">Metric audit</h1>
              <div className="sa-subtitle">Service-reported risk metrics, checked against their canonical formulas.</div>
            </div>
          </div>
          <div className="sa-title-side">
            <span className="sa-meta-caption">LAST WINDOW</span>
            <span className="sa-window"><Radio size={12} />24h <span style={{ color: "#809083" }}>·</span> continuously sampled</span>
          </div>
        </div>

        <section className="sa-summary sa-panel" aria-label="Audit totals">
          <div className="sa-stat pass">
            <div className="sa-stat-icon"><Check size={17} /></div>
            <div><div className="sa-stat-label">Passed</div><div className="sa-stat-value">{summary?.pass?.toLocaleString() ?? "—"}</div></div>
          </div>
          <div className="sa-stat warn">
            <div className="sa-stat-icon"><TriangleAlert size={16} /></div>
            <div><div className="sa-stat-label">Warnings</div><div className="sa-stat-value">{summary?.warn?.toLocaleString() ?? "—"}</div></div>
          </div>
          <div className="sa-stat fail">
            <div className="sa-stat-icon"><AlertTriangle size={16} /></div>
            <div><div className="sa-stat-label">Failed</div><div className="sa-stat-value">{summary?.fail?.toLocaleString() ?? "—"}</div></div>
          </div>
          <div className="sa-rate">
            <div>
              <div className="sa-rate-label">Checks passing</div>
              <div className="sa-rate-value">{passRate}<span style={{ fontSize: 14, letterSpacing: "-.02em" }}>%</span></div>
              <div className="sa-rate-foot">{summary?.total_logged?.toLocaleString() ?? "—"} checks logged in this window</div>
            </div>
            <div className="sa-rate-mark"><ShieldCheck size={22} strokeWidth={1.5} /></div>
          </div>
        </section>

        <section className="sa-workbench" aria-label="Formula verification">
          <div className="sa-formula-panel sa-panel">
            <div className="sa-section-title">
              <div>
                <div className="sa-section-label">Reference formulas</div>
                <div className="sa-section-kicker">Canonical equations · service-reported values from risk feed</div>
              </div>
              <div className="sa-source"><span className="sa-source-dot" /> /performance/risk-metrics</div>
            </div>
            <div className="sa-formula-list">
              {formulas.map((formula, index) => {
                const FormulaIcon = formula.icon;
                const isUnavailable = formula.result === "unavailable";
                const isEmpty = formula.result === "—";
                const valueStatus = riskMetrics.isLoading
                  ? "AWAITING DATA"
                  : isUnavailable
                    ? "UNAVAILABLE"
                    : isEmpty
                      ? "NO VALUE"
                      : "VALUE RECEIVED";
                return (
                  <button
                    type="button"
                    key={formula.id}
                    onClick={() => setActiveFormula(index)}
                    className={`sa-formula ${activeFormula === index ? "is-active" : ""}`}
                    aria-label={`Inspect ${formula.label}`}
                  >
                    <div className="sa-formula-name">
                      <span className="sa-formula-icon"><FormulaIcon /></span>
                      <span>
                        <span className="sa-formula-title">{formula.label}</span>
                        <span className="sa-formula-detail" style={{ display: "block" }}>{formula.detail}</span>
                      </span>
                    </div>
                    <div className="sa-equation">{formula.notation}</div>
                    <div className="sa-value">
                      <div className={`sa-value-status ${isUnavailable ? "is-unavailable" : isEmpty ? "is-empty" : ""}`}>
                        {riskMetrics.isLoading ? <CircleDashed /> : isUnavailable || isEmpty ? <AlertTriangle /> : <CheckCircle2 />}
                        {valueStatus}
                      </div>
                      <div className="sa-number">{formula.result}</div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          <aside className="sa-integrity-panel sa-panel">
            <div className="sa-right-head">
              <span className="sa-integrity-tag"><ShieldCheck />Integrity signal</span>
              <span className="sa-total-mini">24H / ALL STRATEGIES</span>
            </div>
            <div className="sa-big-rate"><strong>{passRate}%</strong><span>checks pass</span></div>
            <div className="sa-rate-track"><span style={{ width: passRate === "—" ? "0%" : `${passRate}%` }} /></div>
            <div className="sa-integrity-copy">
              {riskMetrics.isLoading
                ? "Awaiting the risk metric service response. Formula references remain available while values load."
                : riskMetrics.isError
                  ? "Risk metric service unavailable. Values are not presented as zero; review the audit evidence below."
                  : riskMetrics.data?.sharpe_ratio == null || riskMetrics.data?.sortino_ratio == null
                    ? "A service-reported value is missing. Review the formula references and recent audit evidence below."
                    : hasError
                      ? `${summary?.fail?.toLocaleString()} failed checks require review. Warnings remain visible in the event ledger below.`
                      : "Sharpe and Sortino service values are present beside their canonical formula references."}
            </div>
            <div className="sa-integrity-footer">
              <span>Checks evaluated</span>
              <strong>{totalChecks?.toLocaleString() ?? "—"}</strong>
              <span>Window <strong>24h</strong></span>
            </div>
          </aside>
        </section>

        <section className="sa-events-panel sa-panel" aria-label="Recent audit events">
          <div className="sa-events-top">
            <div className="sa-events-heading">
              <Activity className="sa-events-icon" />
              <span className="sa-events-title">Recent audit events</span>
              <span className="sa-events-count">{feedUnavailable ? "—" : `${events.length} shown`}</span>
            </div>
            <div className="sa-filterbar" role="group" aria-label="Filter audit events">
              {statuses.map((status) => (
                <button
                  key={status.id}
                  type="button"
                  onClick={() => setFilter(status.id)}
                  className={`sa-filter ${filter === status.id ? "is-selected" : ""}`}
                  aria-pressed={filter === status.id}
                >
                  {status.label}
                  {status.count != null && <span className="sa-filter-count">{status.count.toLocaleString()}</span>}
                </button>
              ))}
            </div>
          </div>
          {feedUnavailable ? (
            <div className="sa-empty"><AlertTriangle />Audit feed unavailable</div>
          ) : events.length === 0 ? (
            <div className="sa-empty"><CircleDashed />No {filter.toLowerCase()} events in this window</div>
          ) : (
            <>
              <div className="sa-table-head">
                <span>Audit check</span><span>Strategy</span><span>Status</span><span>Event time</span>
              </div>
              <div className="sa-event-list">
                {events.map((event, index) => (
                  <div className="sa-event-row" key={`${event.audit_timestamp}-${event.formula_name}-${index}`}>
                    <div className="sa-event-name">
                      <span className={`sa-event-mark ${event.status.toLowerCase()}`}>
                        <AuditMark status={event.status as AuditStatus} />
                      </span>
                      <span className="sa-event-formula">{event.formula_name ?? event.bot_id}</span>
                    </div>
                    <div className="sa-event-bot"><Command />{event.bot_id}</div>
                    <div className={`sa-event-status ${event.status.toLowerCase()}`}>
                      <i className="sa-status-dot" />{event.status}
                    </div>
                    <div className="sa-event-time">{eventClock(event.audit_timestamp)}<span>{relativeTime(event.audit_timestamp)}</span></div>
                  </div>
                ))}
              </div>
            </>
          )}
          <div className="sa-footline">
            <span className="sa-footline-left"><Leaf />Evidence stream · audit events ordered by timestamp</span>
            <span className="sa-footline-right">LATEST <ArrowUpRight size={10} style={{ display: "inline", verticalAlign: "middle" }} /></span>
          </div>
        </section>
      </main>
    </div>
  );
}