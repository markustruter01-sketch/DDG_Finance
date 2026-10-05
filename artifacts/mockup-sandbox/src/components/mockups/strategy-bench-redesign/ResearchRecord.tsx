import { useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  BookOpen,
  ChevronDown,
  Database,
  FlaskConical,
  LockKeyhole,
  ShieldCheck,
} from "lucide-react";
import "./_group.css";
import "./ResearchRecord.css";

type Experiment = {
  id: string | number;
  family: string;
  hypothesis: string;
  parameters_summary: string;
  pass_bar: unknown;
  data_window: unknown;
  metrics: { sharpe: number | null; return_pct: number | null; max_drawdown_pct: number | null };
  outcome: string;
  created_at: string;
};

type ExplorationRun = {
  id: string | number;
  family: string;
  parameters_summary: string;
  data_window: unknown;
  sharpe: number | null;
  return_pct: number | null;
  max_drawdown: number | null;
  source: string;
  created_at: string;
};

type SortKey = "sharpe" | "return_pct" | "max_drawdown" | "created_at";
type ResearchGroup = "Atlas" | "Momentum" | "Bullion" | "Forex" | "Fleet" | "Other";

const CATALOG = {
  schema_version: 1,
  generated_at: "2026-10-05T00:45:45.754501Z",
  snapshot_as_of: "2026-10-05T00:45:45.754501Z",
  source_label: "Helium research database · read-only export",
  row_counts: { experiments: 2, exploration_runs: 3 },
  experiments: [
    {
      id: 17,
      family: "bot2_momentum_fullmarket",
      hypothesis:
        "12-1 cross-sectional momentum, top 20 equal weight, monthly rebalance, on a full-market mechanically screened US equity universe produces positive risk-adjusted returns.",
      parameters_summary:
        "allocation=equal_weight; cash_model=one shared cash balance; max_deployment=1.0; momentum=12-1; rebalance=monthly first-trading-day; top_n=20; universe_size=500",
      pass_bar: { pooled_sharpe_min: 0.6, pooled_max_drawdown_max: 0.4 },
      data_window: { backtest_start: "2019-02-01", backtest_end: "2026-07-31", warmup_start: "2018-01-01" },
      metrics: { sharpe: 1.799, return_pct: 96.23, max_drawdown_pct: 18.3 },
      outcome: "PASS",
      created_at: "2026-08-29T01:59:27.614437Z",
    },
    {
      id: 19,
      family: "bot2_momentum_rank500_regime",
      hypothesis:
        "Adding a market regime filter to rank-500 12-1 momentum reduces the momentum-crash drawdown without destroying the return.",
      parameters_summary:
        "allocation=equal_weight; idle_capital=cash; market_regime=SPY prior 200-session SMA; top_n=20; universe_size=500",
      pass_bar: { sharpe_min: 0.6, max_drawdown_max: 0.4 },
      data_window: { backtest_start: "2019-02-01", backtest_end: "2026-07-31", warmup_start: "2018-01-01" },
      metrics: { sharpe: 0.887, return_pct: 209.2, max_drawdown_pct: 33.79 },
      outcome: "FAIL",
      created_at: "2026-08-29T03:45:41.438825Z",
    },
  ] satisfies Experiment[],
  exploration_runs: [
    {
      id: 1,
      family: "bot2_momentum_rank500",
      parameters_summary: "allocation=equal_weight; momentum=12-1; top_n=20; universe_size=500",
      data_window: { backtest_start: "2019-02-01", backtest_end: "2026-07-31" },
      sharpe: 0.702,
      return_pct: 3.218,
      max_drawdown: 72.016,
      source: "bench_gate",
      created_at: "2026-08-30T23:43:10.581668Z",
    },
    {
      id: 2,
      family: "bot2_momentum_rank500_regime",
      parameters_summary: "allocation=equal_weight; market_regime=SPY prior 200-session SMA; top_n=20",
      data_window: { backtest_start: "2019-02-01", backtest_end: "2026-07-31" },
      sharpe: 0.381,
      return_pct: 0.707,
      max_drawdown: 75.104,
      source: "bench_gate",
      created_at: "2026-08-30T23:44:43.929863Z",
    },
    {
      id: 3,
      family: "bot2_momentum_rank500",
      parameters_summary:
        "allocation=equal_weight; catastrophe_stop=0.2; idle_capital=cash; max_deployment=1.0; momentum=12-1; random_control_iterations=1000; random_control_seed=2712026; rebalance=monthly first-trading-day; screening=4 fields; slippage_each_leg_bps=10.0; top_n=20; universe_rule=top 500 by trailing 60-session median dollar volume; universe_size=500",
      data_window: { backtest_start: "2019-02-01", backtest_end: "2026-07-31", warmup_start: "2018-01-01" },
      sharpe: 0.7016876886753177,
      return_pct: 3.218342604572803,
      max_drawdown: 72.01566486898376,
      source: "bench_gate",
      created_at: "2026-08-31T00:03:17.861893Z",
    },
  ] satisfies ExplorationRun[],
};

const GROUP_ORDER: ResearchGroup[] = ["Atlas", "Momentum", "Bullion", "Forex", "Fleet", "Other"];
const PLOT = { width: 720, height: 322, left: 74, right: 18, top: 22, bottom: 56 };
const SHARPE_MAX = 2.1;
const DRAWDOWN_MAX = 80;

function researchGroup(family: string): ResearchGroup {
  const value = family.toLowerCase();
  if (value.includes("atlas")) return "Atlas";
  if (value.includes("momentum")) return "Momentum";
  if (value.includes("bullion") || value.includes("gold") || value.includes("silver")) return "Bullion";
  if (value.includes("forex") || value.includes("fx")) return "Forex";
  if (value.includes("fleet")) return "Fleet";
  return "Other";
}

function familyLabel(family: string) {
  return family
    .replace(/^bot\d+_/, "Bot 2 · ")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function familyColor(family: string) {
  if (family.includes("fullmarket")) return "#466b5c";
  if (family.includes("regime")) return "#a05f47";
  if (family.includes("rank500")) return "#657891";
  if (researchGroup(family) === "Bullion") return "#92773f";
  if (researchGroup(family) === "Forex") return "#74698a";
  if (researchGroup(family) === "Fleet") return "#497d77";
  if (researchGroup(family) === "Atlas") return "#9a654f";
  return "#68715f";
}

function formatDate(value: string | undefined) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    ...(value.includes("T") ? { hour: "2-digit", minute: "2-digit", timeZone: "UTC" } : {}),
  }).format(date) + (value.includes("T") ? " UTC" : "");
}

function formatNumber(value: number | null | undefined, digits = 2) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—";
}

function formatPercent(value: number | null | undefined, digits = 1) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

function formatDrawdown(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `−${Math.abs(value).toFixed(1)}%`;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "Not recorded";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "Not recorded";
  }
}

function formatPassBar(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return formatValue(value);
  const entries = Object.entries(value as Record<string, unknown>);
  if (!entries.length) return "Not recorded";
  return entries.map(([key, raw]) => {
    const drawdown = key.includes("drawdown");
    const threshold = typeof raw === "number" && drawdown && raw <= 1 ? raw * 100 : raw;
    const op = key.endsWith("_min") ? "≥" : key.endsWith("_max") ? "≤" : "=";
    const label = key.replace(/_(min|max)$/, "").replace(/_/g, " ");
    const valueText = typeof threshold === "number" ? `${drawdown ? threshold.toFixed(0) + "%" : threshold.toFixed(2)}` : String(threshold);
    return `${label} ${op} ${valueText}`;
  }).join(" · ");
}

function tone(outcome: string) {
  return /pass|verified|accept|success/i.test(outcome) ? "pass" : /fail|reject|negative/i.test(outcome) ? "fail" : "neutral";
}

type PlotRecord = {
  key: string;
  id: string | number;
  family: string;
  title: string;
  kind: "Experiment" | "Exploration run";
  sharpe: number;
  drawdown: number;
  returnPct: number | null;
  outcome?: string;
  createdAt: string;
};

export function ResearchRecord() {
  const [selectedPoint, setSelectedPoint] = useState("experiment-17");
  const [familyFilter, setFamilyFilter] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("created_at");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");

  const plotRecords = useMemo<PlotRecord[]>(() => [
    ...CATALOG.experiments.flatMap((experiment) =>
      typeof experiment.metrics.sharpe === "number" && typeof experiment.metrics.max_drawdown_pct === "number"
        ? [{
            key: `experiment-${experiment.id}`,
            id: experiment.id,
            family: experiment.family,
            title: `Experiment ${experiment.id}`,
            kind: "Experiment" as const,
            sharpe: experiment.metrics.sharpe,
            drawdown: Math.abs(experiment.metrics.max_drawdown_pct),
            returnPct: experiment.metrics.return_pct,
            outcome: experiment.outcome,
            createdAt: experiment.created_at,
          }]
        : [],
    ),
    ...CATALOG.exploration_runs.flatMap((run) =>
      typeof run.sharpe === "number" && typeof run.max_drawdown === "number"
        ? [{
            key: `run-${run.id}`,
            id: run.id,
            family: run.family,
            title: `Exploration ${run.id}`,
            kind: "Exploration run" as const,
            sharpe: run.sharpe,
            drawdown: Math.abs(run.max_drawdown),
            returnPct: run.return_pct,
            createdAt: run.created_at,
          }]
        : [],
    ),
  ], []);

  const selected = plotRecords.find((record) => record.key === selectedPoint) ?? plotRecords[0];
  const families = [...new Set(CATALOG.exploration_runs.map((run) => run.family))].sort();
  const visibleRuns = useMemo(() => {
    const filtered = familyFilter === "all"
      ? CATALOG.exploration_runs
      : CATALOG.exploration_runs.filter((run) => run.family === familyFilter);
    return [...filtered].sort((a, b) => {
      const left = a[sortKey];
      const right = b[sortKey];
      const comparison = sortKey === "created_at"
        ? new Date(String(left)).getTime() - new Date(String(right)).getTime()
        : Number(left) - Number(right);
      return comparison * (sortDirection === "asc" ? 1 : -1);
    });
  }, [familyFilter, sortDirection, sortKey]);

  function changeSort(key: SortKey) {
    if (key === sortKey) setSortDirection((direction) => direction === "asc" ? "desc" : "asc");
    else {
      setSortKey(key);
      setSortDirection("desc");
    }
  }

  const recordsForGroup = (group: ResearchGroup) =>
    CATALOG.experiments.filter((experiment) => researchGroup(experiment.family) === group);

  const xPosition = (value: number) =>
    PLOT.left + (value / SHARPE_MAX) * (PLOT.width - PLOT.left - PLOT.right);
  const yPosition = (value: number) =>
    PLOT.top + (1 - value / DRAWDOWN_MAX) * (PLOT.height - PLOT.top - PLOT.bottom);

  return (
    <main className="bench-shell rr-shell" data-testid="research-record">
      <div className="rr-frame">
        <header className="rr-topbar">
          <div className="rr-brand">
            <span className="rr-brand-mark"><FlaskConical size={18} strokeWidth={1.8} /></span>
            <span className="rr-brand-copy"><small>Research ledger</small><strong>Strategy Bench</strong></span>
          </div>
          <div className="rr-top-status">
            <span className="rr-readonly"><LockKeyhole size={14} /> Read-only research record</span>
            <span className="rr-separation"><ShieldCheck size={14} /> Execution is separate</span>
          </div>
        </header>

        <section className="rr-intro" aria-labelledby="rr-title">
          <div className="rr-intro-copy">
            <div className="rr-eyebrow"><BookOpen size={13} /> Catalog / Version {CATALOG.schema_version}</div>
            <h1 id="rr-title">Two ideas recorded.<br /><em>One cleared its stated bar.</em></h1>
            <p>Historical hypotheses and outcomes, gathered for inspection. Nothing here starts research or routes an order.</p>
          </div>
          <aside className="rr-snapshot" aria-label="Catalog snapshot provenance">
            <div className="rr-snapshot-heading"><Database size={15} /><span>Snapshot provenance</span></div>
            <dl>
              <div><dt>Source</dt><dd>{CATALOG.source_label}</dd></div>
              <div><dt>As of</dt><dd>{formatDate(CATALOG.snapshot_as_of)}</dd></div>
              <div><dt>Generated</dt><dd>{formatDate(CATALOG.generated_at)}</dd></div>
            </dl>
          </aside>
        </section>

        <section className="rr-count-strip" aria-label="Catalog record counts">
          <div className="rr-count-lead"><span className="rr-count-numeral">{CATALOG.row_counts.experiments}</span><span>registered ideas</span></div>
          <span className="rr-count-divider" />
          <div className="rr-count-cell"><span className="rr-count-numeral">{CATALOG.row_counts.exploration_runs}</span><span>exploration runs</span></div>
          <span className="rr-count-caption">Recorded evidence only · no live status implied</span>
        </section>

        <section className="rr-panel rr-chart-panel" aria-labelledby="rr-chart-title">
          <div className="rr-panel-heading">
            <div>
              <span className="rr-section-index">01 / Outcome map</span>
              <h2 id="rr-chart-title">Risk against return quality</h2>
              <p>Sharpe ratio versus maximum drawdown for recorded catalog results.</p>
            </div>
            <span className="rr-chart-axis-note">Lower drawdown · stronger Sharpe</span>
          </div>
          <div className="rr-chart-layout">
            <div className="rr-chart-wrap">
              <svg className="rr-scatter" viewBox={`0 0 ${PLOT.width} ${PLOT.height}`} role="group" aria-label="Scatter plot of Sharpe ratio against maximum drawdown. Select a mark to inspect its record.">
                {[0, 20, 40, 60, 80].map((tick) => (
                  <g key={`dd-${tick}`}>
                    <line x1={PLOT.left} x2={PLOT.width - PLOT.right} y1={yPosition(tick)} y2={yPosition(tick)} className="rr-grid-line" />
                    <text x={PLOT.left - 12} y={yPosition(tick) + 4} className="rr-axis-tick" textAnchor="end">{tick}%</text>
                  </g>
                ))}
                {[0, 0.5, 1, 1.5, 2].map((tick) => (
                  <g key={`sharpe-${tick}`}>
                    <line x1={xPosition(tick)} x2={xPosition(tick)} y1={PLOT.top} y2={PLOT.height - PLOT.bottom} className="rr-grid-line rr-grid-vertical" />
                    <text x={xPosition(tick)} y={PLOT.height - PLOT.bottom + 22} className="rr-axis-tick" textAnchor="middle">{tick.toFixed(1)}</text>
                  </g>
                ))}
                <line x1={PLOT.left} x2={PLOT.width - PLOT.right} y1={PLOT.height - PLOT.bottom} y2={PLOT.height - PLOT.bottom} className="rr-axis-line" />
                <line x1={PLOT.left} x2={PLOT.left} y1={PLOT.top} y2={PLOT.height - PLOT.bottom} className="rr-axis-line" />
                <text x={(PLOT.left + PLOT.width - PLOT.right) / 2} y={PLOT.height - 8} className="rr-axis-title" textAnchor="middle">Sharpe ratio</text>
                <text x="17" y={(PLOT.top + PLOT.height - PLOT.bottom) / 2} className="rr-axis-title rr-y-label" textAnchor="middle" transform={`rotate(-90 17 ${(PLOT.top + PLOT.height - PLOT.bottom) / 2})`}>Maximum drawdown</text>
                {plotRecords.map((record) => {
                  const isSelected = record.key === selected?.key;
                  return (
                    <g
                      key={record.key}
                      className={`rr-plot-mark${isSelected ? " is-selected" : ""}`}
                      role="button"
                      tabIndex={0}
                      aria-label={`${record.title}, ${familyLabel(record.family)}, Sharpe ${formatNumber(record.sharpe)}, maximum drawdown ${formatDrawdown(record.drawdown)}${record.outcome ? `, verdict ${record.outcome}` : ""}`}
                      aria-pressed={isSelected}
                      onClick={() => setSelectedPoint(record.key)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          setSelectedPoint(record.key);
                        }
                      }}
                    >
                      <title>{`${record.title} · Sharpe ${formatNumber(record.sharpe)} · Max drawdown ${formatDrawdown(record.drawdown)}`}</title>
                      <circle cx={xPosition(record.sharpe)} cy={yPosition(record.drawdown)} r="14" className="rr-mark-hitarea" />
                      <circle cx={xPosition(record.sharpe)} cy={yPosition(record.drawdown)} r={isSelected ? 7.5 : 6} fill={familyColor(record.family)} className="rr-mark-core" />
                      {isSelected && <circle cx={xPosition(record.sharpe)} cy={yPosition(record.drawdown)} r="11" className="rr-mark-ring" />}
                    </g>
                  );
                })}
              </svg>
              <div className="rr-chart-legend" aria-label="Chart family legend">
                {[...new Set(plotRecords.map((record) => record.family))].map((family) => (
                  <span key={family}><i style={{ backgroundColor: familyColor(family) }} />{familyLabel(family)}</span>
                ))}
              </div>
            </div>
            <aside className="rr-point-detail" aria-live="polite" aria-label="Selected chart result">
              {selected ? (
                <>
                  <span className="rr-detail-kicker">{selected.kind} · Record {selected.id}</span>
                  <strong className="rr-detail-title">{familyLabel(selected.family)}</strong>
                  <div className="rr-detail-metrics">
                    <div><span>Sharpe</span><b>{formatNumber(selected.sharpe, 3)}</b></div>
                    <div><span>Maximum drawdown</span><b>{formatDrawdown(selected.drawdown)}</b></div>
                    <div><span>Return</span><b>{formatPercent(selected.returnPct, 2)}</b></div>
                  </div>
                  <div className="rr-detail-footer">
                    {selected.outcome ? <span className={`rr-verdict ${tone(selected.outcome)}`}>{selected.outcome.toLowerCase()}</span> : <span>Historical exploration</span>}
                    <time>{formatDate(selected.createdAt)}</time>
                  </div>
                  <span className="rr-tap-hint">Select a point to inspect another result</span>
                </>
              ) : <p>No results with both Sharpe and drawdown values are recorded.</p>}
            </aside>
          </div>
          <div className="rr-benchmark-note">
            <span className="rr-note-rule" />
            <p>This snapshot contains no SPY buy-and-hold reference series; no benchmark marker is shown.</p>
          </div>
        </section>

        <section className="rr-experiments" aria-labelledby="rr-experiments-title">
          <div className="rr-section-header">
            <div>
              <span className="rr-section-index">02 / Registered hypotheses</span>
              <h2 id="rr-experiments-title">Experiments by research family</h2>
            </div>
            <span className="rr-section-count">{CATALOG.experiments.length} total records</span>
          </div>
          <div className="rr-groups">
            {GROUP_ORDER.map((group, index) => {
              const experiments = recordsForGroup(group);
              return (
                <section className={`rr-group rr-group-${group.toLowerCase()}`} key={group} aria-labelledby={`rr-group-${group.toLowerCase()}`}>
                  <header className="rr-group-heading">
                    <span className="rr-group-number">{String(index + 1).padStart(2, "0")}</span>
                    <h3 id={`rr-group-${group.toLowerCase()}`}>{group}</h3>
                    <span className="rr-group-count">{experiments.length} {experiments.length === 1 ? "record" : "records"}</span>
                  </header>
                  {experiments.length ? (
                    <div className="rr-group-records">
                      {experiments.map((experiment) => (
                        <article className="rr-experiment" key={experiment.id}>
                          <div className="rr-experiment-top">
                            <span className="rr-record-id">Record {experiment.id} <span>·</span> {familyLabel(experiment.family)}</span>
                            <span className={`rr-verdict ${tone(experiment.outcome)}`}>{experiment.outcome.toLowerCase()}</span>
                          </div>
                          <p className="rr-hypothesis">{experiment.hypothesis}</p>
                          <div className="rr-evidence-grid">
                            <div className="rr-evidence-cell">
                              <span className="rr-field-label">Pass bar</span>
                              <strong>{formatPassBar(experiment.pass_bar)}</strong>
                            </div>
                            <div className="rr-evidence-cell rr-result-cell">
                              <span className="rr-field-label">Result</span>
                              <div className="rr-result-values">
                                <span><b>{formatNumber(experiment.metrics.sharpe, 3)}</b><small>Sharpe</small></span>
                                <span><b>{formatPercent(experiment.metrics.return_pct, 2)}</b><small>Return</small></span>
                                <span><b>{formatDrawdown(experiment.metrics.max_drawdown_pct)}</b><small>Max drawdown</small></span>
                              </div>
                            </div>
                          </div>
                          <details className="rr-parameters">
                            <summary><span>Parameters and data window</span><ChevronDown size={15} /></summary>
                            <div className="rr-disclosure-content">
                              <div><span className="rr-field-label">Parameters</span><pre>{formatValue(experiment.parameters_summary)}</pre></div>
                              <div><span className="rr-field-label">Data window</span><pre>{formatValue(experiment.data_window)}</pre></div>
                              <p>Recorded {formatDate(experiment.created_at)} · outcome is historical, not actionable.</p>
                            </div>
                          </details>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <p className="rr-group-empty">No records in this snapshot.</p>
                  )}
                </section>
              );
            })}
          </div>
        </section>

        <section className="rr-panel rr-exploration-panel" aria-labelledby="rr-exploration-title">
          <div className="rr-panel-heading rr-table-heading">
            <div>
              <span className="rr-section-index">03 / Historical search space</span>
              <h2 id="rr-exploration-title">Exploration runs</h2>
              <p>Recorded parameter trials and observed metrics. Sort a column or narrow by family.</p>
            </div>
            <label className="rr-filter">
              <span>Family</span>
              <select value={familyFilter} onChange={(event) => setFamilyFilter(event.target.value)} aria-label="Filter exploration runs by family">
                <option value="all">All families</option>
                {families.map((family) => <option value={family} key={family}>{familyLabel(family)}</option>)}
              </select>
            </label>
          </div>
          <div className="rr-table-meta"><span>{visibleRuns.length} of {CATALOG.exploration_runs.length} runs</span><span>Table scrolls independently</span></div>
          <div className="rr-table-scroll" role="region" aria-label="Sortable exploration run records" tabIndex={0}>
            {visibleRuns.length ? (
              <table className="rr-table">
                <thead><tr>
                  <th scope="col">Record</th>
                  <th scope="col">Family</th>
                  {([
                    ["sharpe", "Sharpe"],
                    ["return_pct", "Return"],
                    ["max_drawdown", "Max drawdown"],
                    ["created_at", "Recorded"],
                  ] as [SortKey, string][]).map(([key, label]) => {
                    const SortIcon = sortKey === key ? sortDirection === "asc" ? ArrowUp : ArrowDown : ArrowUpDown;
                    return (
                      <th scope="col" key={key}>
                        <button type="button" className="rr-sort" onClick={() => changeSort(key)} aria-label={`Sort by ${label.toLowerCase()}`}>
                          {label}<SortIcon size={13} aria-hidden="true" />
                        </button>
                      </th>
                    );
                  })}
                  <th scope="col">Source</th>
                  <th scope="col">Parameters and window</th>
                </tr></thead>
                <tbody>
                  {visibleRuns.map((run) => (
                    <tr key={run.id}>
                      <td className="rr-mono">#{run.id}</td>
                      <td><span className="rr-family-tag"><i style={{ backgroundColor: familyColor(run.family) }} />{familyLabel(run.family)}</span></td>
                      <td className="rr-mono">{formatNumber(run.sharpe, 3)}</td>
                      <td className="rr-mono">{formatPercent(run.return_pct, 2)}</td>
                      <td className="rr-mono">{formatDrawdown(run.max_drawdown)}</td>
                      <td className="rr-mono">{formatDate(run.created_at)}</td>
                      <td className="rr-mono">{run.source}</td>
                      <td>
                        <details className="rr-run-details">
                          <summary>Inspect <ChevronDown size={13} /></summary>
                          <div className="rr-run-popover">
                            <span className="rr-field-label">Parameters</span><pre>{formatValue(run.parameters_summary)}</pre>
                            <span className="rr-field-label">Data window</span><pre>{formatValue(run.data_window)}</pre>
                          </div>
                        </details>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="rr-empty-runs"><strong>No runs for this family.</strong><span>Choose another family to view recorded exploration.</span></div>
            )}
          </div>
          <footer className="rr-table-foot"><span><LockKeyhole size={13} /> Read-only historical records</span><span>Source: {CATALOG.source_label}</span></footer>
        </section>

        <footer className="rr-page-foot">
          <span><ShieldCheck size={14} /> Research records do not represent live positions or execution.</span>
          <span>Snapshot as of {formatDate(CATALOG.snapshot_as_of)}</span>
        </footer>
      </div>
    </main>
  );
}

export default ResearchRecord;