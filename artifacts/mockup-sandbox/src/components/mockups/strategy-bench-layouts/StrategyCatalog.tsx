import { useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  BarChart3,
  BookOpen,
  CalendarClock,
  ChevronDown,
  Database,
  FlaskConical,
  LockKeyhole,
  ShieldCheck,
} from "lucide-react";
import {
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { MOCK_CATALOG } from "./_shared/BenchCatalogFixture";
import "./_group.css";
import "./BenchRecord.css";
import "./StrategyCatalog.css";

type Experiment = (typeof MOCK_CATALOG.experiments)[number];
type ExplorationRun = (typeof MOCK_CATALOG.exploration_runs)[number];
type SortKey = "sharpe" | "return_pct" | "max_drawdown" | "created_at";
type ResearchGroup = "Atlas" | "Momentum" | "Bullion" | "Forex" | "Fleet" | "Other";
type ChartPoint = {
  id: string | number;
  family: string;
  sharpe: number;
  drawdown: number;
  return_pct: number | null;
  group: ResearchGroup;
  run: ExplorationRun;
};

const GROUPS: ResearchGroup[] = ["Atlas", "Momentum", "Bullion", "Forex", "Fleet", "Other"];
const GROUP_COLORS: Record<ResearchGroup, string> = {
  Atlas: "#9a654f",
  Momentum: "#466b5c",
  Bullion: "#92773f",
  Forex: "#74698a",
  Fleet: "#497d77",
  Other: "#68715f",
};

function researchGroup(family: string): ResearchGroup {
  const value = family.toLowerCase();
  if (value.includes("atlas")) return "Atlas";
  if (value.includes("momentum")) return "Momentum";
  if (value.includes("bullion") || value.includes("gold") || value.includes("silver")) return "Bullion";
  if (/\bforex\b|\bfx\b|foreign[_ -]?exchange|currency|oanda/.test(value)) return "Forex";
  if (value.includes("fleet")) return "Fleet";
  return "Other";
}

function familyLabel(family: string) {
  return family
    .replace(/^bot(\d+)_/i, "Bot $1 · ")
    .replace(/[_-]+/g, " ")
    .replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}

function formatDate(value: string | undefined) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    ...(value.includes("T")
      ? { hour: "2-digit", minute: "2-digit", timeZone: "UTC", timeZoneName: "short" as const }
      : {}),
  }).format(date);
}

function formatMetric(value: number | null | undefined, digits = 2) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—";
}

function formatPercent(value: number | null | undefined, digits = 1) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

function formatDrawdown(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "−" : ""}${Math.abs(value).toFixed(1)}%`;
}

function formatSummary(value: unknown) {
  if (value === null || value === undefined || value === "") return "Not recorded";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "Not recorded";
  }
}

function formatPassBar(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return formatSummary(value);
  const entries = Object.entries(value as Record<string, unknown>);
  if (!entries.length) return "Not recorded";
  return entries.map(([key, threshold]) => {
    const operator = key.endsWith("_min") ? "≥" : key.endsWith("_max") ? "≤" : "=";
    return `${key.replace(/_(min|max)$/, "").replace(/_/g, " ")} ${operator} ${formatSummary(threshold)}`;
  }).join(" · ");
}

function outcomeTone(outcome: string) {
  const normalized = outcome.toLowerCase();
  if (/fail|reject|negative|blocked|not.?pass/.test(normalized)) return "is-fail";
  if (/pass|verified|accept|success|ready/.test(normalized)) return "is-pass";
  return "is-neutral";
}

function outcomeLabel(outcome: string) {
  return outcome.replace(/[_-]+/g, " ").replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}

type TooltipProps = { active?: boolean; payload?: Array<{ payload?: ChartPoint }> };

function RunTooltip({ active, payload }: TooltipProps) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  return (
    <div className="bench-record-tooltip" role="status">
      <strong>{familyLabel(point.family)}</strong>
      <span>Run {point.id} · {point.group}</span>
      <dl>
        <div><dt>Sharpe</dt><dd>{formatMetric(point.sharpe, 3)}</dd></div>
        <div><dt>Maximum drawdown</dt><dd>{formatDrawdown(point.run.max_drawdown)}</dd></div>
        <div><dt>Return</dt><dd>{formatPercent(point.return_pct, 2)}</dd></div>
      </dl>
      <small>{point.run.source} · {formatDate(point.run.created_at)}</small>
    </div>
  );
}

export default function StrategyCatalog() {
  const experiments = MOCK_CATALOG.experiments as Experiment[];
  const runs = MOCK_CATALOG.exploration_runs as ExplorationRun[];
  const [selectedExperimentId, setSelectedExperimentId] = useState<string | null>(
    experiments[0] ? String(experiments[0].id) : null,
  );
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [familyFilter, setFamilyFilter] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("created_at");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");

  const outcomeCounts = useMemo(() => {
    const counts = new Map<string, number>();
    experiments.forEach((item) => {
      const key = item.outcome.trim() || "Not recorded";
      counts.set(key, (counts.get(key) ?? 0) + 1);
    });
    return [...counts.entries()];
  }, [experiments]);
  const families = useMemo(() => [...new Set(runs.map((run) => run.family))].sort((a, b) => a.localeCompare(b)), [runs]);
  const selectedExperiment = experiments.find((item) => String(item.id) === selectedExperimentId)
    ?? experiments[0]
    ?? null;
  const chartPoints = useMemo<ChartPoint[]>(() => runs.flatMap((run) => {
    if (
      typeof run.sharpe !== "number" || !Number.isFinite(run.sharpe)
      || typeof run.max_drawdown !== "number" || !Number.isFinite(run.max_drawdown)
    ) return [];
    return [{
      id: run.id,
      family: run.family,
      sharpe: run.sharpe,
      drawdown: Math.abs(run.max_drawdown),
      return_pct: run.return_pct,
      group: researchGroup(run.family),
      run,
    }];
  }), [runs]);
  const chartGroups = GROUPS.map((group) => ({
    group,
    points: chartPoints.filter((point) => point.group === group),
  })).filter(({ points }) => points.length > 0);
  const selectedRun = runs.find((run) => String(run.id) === selectedRunId) ?? null;
  const plottedIds = new Set(chartPoints.map((point) => String(point.id)));
  const visibleRuns = useMemo(() => {
    const filtered = familyFilter === "all" ? runs : runs.filter((run) => run.family === familyFilter);
    return [...filtered].sort((a, b) => {
      const left = a[sortKey];
      const right = b[sortKey];
      if (sortKey !== "created_at" && (typeof left !== "number" || typeof right !== "number")) {
        if (left == null && right != null) return 1;
        if (left != null && right == null) return -1;
        return 0;
      }
      const compare = sortKey === "created_at"
        ? new Date(String(left)).getTime() - new Date(String(right)).getTime()
        : Number(left) - Number(right);
      return compare * (sortDirection === "asc" ? 1 : -1);
    });
  }, [familyFilter, runs, sortDirection, sortKey]);

  function changeSort(key: SortKey) {
    if (sortKey === key) setSortDirection((direction) => direction === "asc" ? "desc" : "asc");
    else {
      setSortKey(key);
      setSortDirection("desc");
    }
  }

  const renderPoint = (rawProps: unknown) => {
    const props = rawProps as { cx?: number; cy?: number; fill?: string; payload?: ChartPoint };
    const point = props.payload;
    if (typeof props.cx !== "number" || typeof props.cy !== "number" || !point) return <g />;
    const select = () => setSelectedRunId(String(point.id));
    return (
      <g
        role="button"
        tabIndex={0}
        aria-label={`Inspect run ${point.id}, ${familyLabel(point.family)}, Sharpe ${formatMetric(point.sharpe, 3)}, maximum drawdown ${formatDrawdown(point.run.max_drawdown)}`}
        aria-pressed={selectedRunId === String(point.id)}
        onClick={(event) => { event.stopPropagation(); select(); }}
        onFocus={select}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            select();
          }
        }}
      >
        <circle cx={props.cx} cy={props.cy} r={12} fill="transparent" />
        <circle className="bench-record-dot" cx={props.cx} cy={props.cy} r={5.5} fill={props.fill ?? GROUP_COLORS[point.group]} />
      </g>
    );
  };

  return (
    <main className="bench-shell bench-catalog bench-record-page strategy-catalog-page" data-testid="page-bench-catalog">
      <section className="bench-content">
        <header className="bench-topbar strategy-masthead">
          <div className="strategy-masthead-brand">
            <div className="bench-brand-mark"><FlaskConical size={18} /></div>
            <div className="bench-title-group">
              <div className="bench-breadcrumb"><BookOpen size={13} /> Research / Bench</div>
              <h1>Strategy Bench</h1>
            </div>
          </div>
          <div className="strategy-masthead-status">
            <span className="bench-readonly"><Database size={13} /> Read-only catalog</span>
            <div className="bench-rail-note"><span className="bench-status-dot" /><div><strong>READ ONLY</strong><span>NO ORDER PATHS</span></div></div>
          </div>
        </header>

        <div className="bench-ledger-body bench-record-body strategy-catalog-body">
          <section className="strategy-meta-strip" aria-label="Snapshot summary and provenance">
            <div className="strategy-meta-overview">
              <div className="strategy-meta-kicker"><BookOpen size={13} /><span>Research record · Version {MOCK_CATALOG.schema_version}</span></div>
              <p>Registered hypotheses and historical outcomes for inspection. This page cannot start research or route an order.</p>
              <div className="strategy-meta-counts">
                <div className="strategy-count-block"><strong>{experiments.length}</strong><span>Hypotheses</span></div>
                {outcomeCounts.length ? outcomeCounts.map(([outcome, count]) => (
                  <span className={`bench-record-outcome ${outcomeTone(outcome)}`} key={outcome}><b>{count}</b> {outcomeLabel(outcome)}</span>
                )) : <span className="bench-record-outcome is-neutral">No outcomes recorded</span>}
                <div className="strategy-count-block strategy-runs-count"><strong>{runs.length}</strong><span>Exploration runs</span></div>
              </div>
            </div>
            <aside className="bench-record-provenance strategy-provenance-strip" aria-label="Catalog snapshot source">
              <div className="bench-record-provenance-title"><Database size={15} /> Snapshot provenance</div>
              <dl className="strategy-provenance-values">
                <div><dt>Source</dt><dd>{MOCK_CATALOG.source_label || MOCK_CATALOG.source}</dd></div>
                <div><dt>As of</dt><dd>{formatDate(MOCK_CATALOG.snapshot_as_of)}</dd></div>
                <div><dt>Generated</dt><dd>{formatDate(MOCK_CATALOG.generated_at)}</dd></div>
              </dl>
              <p>{MOCK_CATALOG.source_detail}</p>
            </aside>
          </section>

          <section className="strategy-workspace" aria-label="Registered hypothesis catalog and selected record">
            <section className="strategy-catalog-list bench-record-panel" aria-labelledby="hypothesis-list-title">
              <header className="strategy-panel-head">
                <div>
                  <span className="bench-record-section-label">01 · Registered hypotheses</span>
                  <h2 id="hypothesis-list-title">Research catalog</h2>
                  <p>{experiments.length} records, grouped by research family</p>
                </div>
                <span className="bench-record-section-count">{experiments.length} total</span>
              </header>
              <div className="strategy-catalog-records">
                {GROUPS.map((group, index) => {
                  const groupItems = experiments.filter((item) => researchGroup(item.family) === group);
                  if (groupItems.length === 0) return null;
                  return (
                    <section className="strategy-catalog-group" key={group} aria-label={`${group} hypotheses`}>
                      <div className="strategy-catalog-group-heading">
                        <span>{String(index + 1).padStart(2, "0")}</span>
                        <strong>{group}</strong>
                        <small>{groupItems.length} {groupItems.length === 1 ? "record" : "records"}</small>
                      </div>
                      {groupItems.map((experiment) => (
                        <button
                          key={experiment.id}
                          type="button"
                          className={`strategy-catalog-item ${String(selectedExperiment?.id) === String(experiment.id) ? "is-selected" : ""}`}
                          aria-current={String(selectedExperiment?.id) === String(experiment.id) ? "true" : undefined}
                          onClick={() => setSelectedExperimentId(String(experiment.id))}
                        >
                          <span className="strategy-item-topline"><span>Record {experiment.id}</span><span className={`bench-record-verdict ${outcomeTone(experiment.outcome)}`}>{outcomeLabel(experiment.outcome)}</span></span>
                          <strong>{familyLabel(experiment.family)}</strong>
                          <span className="strategy-item-hypothesis">{experiment.hypothesis || "No hypothesis was recorded."}</span>
                        </button>
                      ))}
                    </section>
                  );
                })}
                {experiments.length === 0 && <div className="strategy-empty"><strong>No hypotheses in this snapshot</strong><span>The current catalog contains no registered experiment records.</span></div>}
              </div>
            </section>

            <section className="strategy-record-detail bench-record-panel" aria-labelledby="selected-hypothesis-title" aria-live="polite">
              {selectedExperiment ? (
                <>
                  <div className="strategy-detail-kicker">
                    <span className="bench-record-section-label">Selected hypothesis · Record {selectedExperiment.id}</span>
                    <span className={`bench-record-verdict ${outcomeTone(selectedExperiment.outcome)}`}>{outcomeLabel(selectedExperiment.outcome)}</span>
                  </div>
                  <h2 id="selected-hypothesis-title">{familyLabel(selectedExperiment.family)}</h2>
                  <p className="strategy-detail-hypothesis">{selectedExperiment.hypothesis || "No hypothesis was recorded."}</p>
                  <div className="strategy-detail-evidence">
                    <section className="strategy-passbar">
                      <span className="bench-record-field-label">Declared pass bar</span>
                      <strong>{formatPassBar(selectedExperiment.pass_bar)}</strong>
                    </section>
                    <section className="strategy-results" aria-label="Recorded outcome metrics">
                      <span className="bench-record-field-label">Recorded result</span>
                      <div className="strategy-result-metrics">
                        <span><b>{formatMetric(selectedExperiment.metrics?.sharpe, 3)}</b><small>Sharpe</small></span>
                        <span><b>{formatPercent(selectedExperiment.metrics?.return_pct, 2)}</b><small>Return</small></span>
                        <span><b>{formatDrawdown(selectedExperiment.metrics?.max_drawdown_pct)}</b><small>Max drawdown</small></span>
                      </div>
                    </section>
                  </div>
                  <div className="strategy-detail-foot">Recorded {formatDate(selectedExperiment.created_at)} <span>Outcome is historical, not actionable.</span></div>
                  <details className="bench-record-disclosure strategy-detail-disclosure" open>
                    <summary><span>Parameters and data window</span><ChevronDown size={15} /></summary>
                    <div>
                      <section><span>Parameters</span><pre>{formatSummary(selectedExperiment.parameters_summary)}</pre></section>
                      <section><span>Data window</span><pre>{formatSummary(selectedExperiment.data_window)}</pre></section>
                    </div>
                  </details>
                </>
              ) : (
                <div className="strategy-empty-detail">
                  <BookOpen size={20} />
                  <strong>No hypothesis selected</strong>
                  <span>Choose a registered record to inspect its declared criteria and results.</span>
                </div>
              )}
            </section>
          </section>

          <section className="bench-record-panel bench-record-chart-panel strategy-chart-panel" aria-labelledby="bench-chart-title">
            <div className="bench-record-panel-heading">
              <div>
                <span className="bench-record-section-label">02 · Risk and return</span>
                <h2 id="bench-chart-title">Sharpe vs maximum drawdown</h2>
                <p>Each point is an exploration run with both chart metrics recorded.</p>
              </div>
              <span className="bench-record-chart-count">{chartPoints.length} of {runs.length} runs plotted</span>
            </div>
            <div className="bench-record-chart-layout">
              <div className="bench-record-chart-column">
                {chartPoints.length ? (
                  <div className="bench-record-chart" role="group" aria-label="Sharpe ratio against maximum drawdown. Select a point for run details.">
                    <ResponsiveContainer width="100%" height="100%">
                      <ScatterChart margin={{ top: 14, right: 20, bottom: 25, left: 6 }}>
                        <CartesianGrid stroke="rgba(55, 78, 69, .18)" vertical strokeDasharray="3 5" />
                        <XAxis type="number" dataKey="sharpe" name="Sharpe" tick={{ fill: "#5d7067", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "rgba(53, 75, 66, .45)" }} tickFormatter={(value: number) => Number(value).toFixed(1)} label={{ value: "Sharpe ratio", position: "insideBottom", offset: -13, fill: "#4f665c", fontSize: 11 }} />
                        <YAxis type="number" dataKey="drawdown" name="Maximum drawdown" reversed domain={[0, "auto"]} width={52} tick={{ fill: "#5d7067", fontSize: 10 }} tickLine={false} axisLine={false} tickFormatter={(value: number) => `−${Math.abs(value).toFixed(0)}%`} />
                        <Tooltip content={<RunTooltip />} cursor={{ stroke: "rgba(50, 83, 66, .42)", strokeDasharray: "3 4" }} />
                        {chartGroups.map(({ group, points }) => (
                          <Scatter key={group} name={group} data={points} fill={GROUP_COLORS[group]} shape={renderPoint} isAnimationActive={false} />
                        ))}
                      </ScatterChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <div className="bench-record-empty-chart"><BarChart3 size={20} /><strong>No runs can be plotted</strong><span>The catalog has no exploration runs with both Sharpe and maximum drawdown values.</span></div>
                )}
                {chartGroups.length > 0 && <div className="bench-record-legend" aria-label="Chart groups">{chartGroups.map(({ group }) => <span key={group}><i style={{ backgroundColor: GROUP_COLORS[group] }} />{group}</span>)}</div>}
              </div>
              <aside className="bench-record-selection" aria-live="polite" aria-label="Selected exploration run">
                {selectedRun ? (
                  <>
                    <span className="bench-record-selection-label">{plottedIds.has(String(selectedRun.id)) ? "Selected run" : "Selected run · chart metrics incomplete"}</span>
                    <strong>{familyLabel(selectedRun.family)}</strong>
                    <span className="bench-record-selection-id">Record {selectedRun.id} · {selectedRun.source}</span>
                    <dl>
                      <div><dt>Sharpe</dt><dd>{formatMetric(selectedRun.sharpe, 3)}</dd></div>
                      <div><dt>Maximum drawdown</dt><dd>{formatDrawdown(selectedRun.max_drawdown)}</dd></div>
                      <div><dt>Return</dt><dd>{formatPercent(selectedRun.return_pct, 2)}</dd></div>
                    </dl>
                    <time>{formatDate(selectedRun.created_at)}</time>
                  </>
                ) : <p>Select a point or a run below to inspect its recorded metrics.</p>}
              </aside>
            </div>
            <div className="bench-record-chart-notes">
              <span>{runs.length - chartPoints.length} {runs.length - chartPoints.length === 1 ? "run is" : "runs are"} missing one or both chart metrics; all remain in the table below.</span>
              <span>No SPY buy-and-hold reference is recorded in this catalog.</span>
            </div>
          </section>

          <section className="bench-record-panel bench-record-runs strategy-runs-panel" aria-labelledby="bench-runs-title">
            <div className="bench-record-panel-heading bench-record-runs-heading">
              <div><span className="bench-record-section-label">03 · Historical search space</span><h2 id="bench-runs-title">Exploration runs</h2><p>Recorded parameter trials and metrics. Filter by family or sort a column.</p></div>
              <label className="bench-record-filter"><span>Family</span><select value={familyFilter} onChange={(event) => setFamilyFilter(event.target.value)}><option value="all">All families</option>{families.map((family) => <option key={family} value={family}>{familyLabel(family)}</option>)}</select></label>
            </div>
            <div className="bench-record-table-meta"><span>{visibleRuns.length} of {runs.length} runs</span><span>All historical records remain inspectable</span></div>
            <div className="bench-record-table-scroll" role="region" aria-label="Exploration run records" tabIndex={0}>
              {visibleRuns.length ? (
                <table className="bench-record-table">
                  <thead><tr>
                    <th scope="col">Record</th><th scope="col">Family</th>
                    {([["sharpe", "Sharpe"], ["return_pct", "Return"], ["max_drawdown", "Max drawdown"], ["created_at", "Recorded"]] as [SortKey, string][]).map(([key, label]) => {
                      const SortIcon = sortKey === key ? sortDirection === "asc" ? ArrowUp : ArrowDown : ArrowUpDown;
                      return <th scope="col" key={key}><button type="button" className="bench-record-sort" aria-label={`Sort by ${label.toLowerCase()}`} aria-sort={sortKey === key ? (sortDirection === "asc" ? "ascending" : "descending") : "none"} onClick={() => changeSort(key)}>{label}<SortIcon size={12} aria-hidden="true" /></button></th>;
                    })}
                    <th scope="col">Source</th><th scope="col">Parameters and window</th>
                  </tr></thead>
                  <tbody>{visibleRuns.map((run) => (
                    <tr key={run.id}>
                      <td className="bench-record-mono"><button type="button" className="bench-record-run-link" onClick={() => setSelectedRunId(String(run.id))} aria-label={`Inspect exploration run ${run.id}`}>#{run.id}</button></td>
                      <td><span className="bench-record-family"><i style={{ backgroundColor: GROUP_COLORS[researchGroup(run.family)] }} />{familyLabel(run.family)}</span></td>
                      <td className="bench-record-mono">{formatMetric(run.sharpe, 3)}</td>
                      <td className="bench-record-mono">{formatPercent(run.return_pct, 2)}</td>
                      <td className="bench-record-mono">{formatDrawdown(run.max_drawdown)}</td>
                      <td className="bench-record-mono"><span className="bench-record-date"><CalendarClock size={12} />{formatDate(run.created_at)}</span></td>
                      <td className="bench-record-mono">{run.source || "Not recorded"}</td>
                      <td><details className="bench-record-run-details"><summary>Inspect <ChevronDown size={13} /></summary><div><section><span>Parameters</span><pre>{formatSummary(run.parameters_summary)}</pre></section><section><span>Data window</span><pre>{formatSummary(run.data_window)}</pre></section></div></details></td>
                    </tr>
                  ))}</tbody>
                </table>
              ) : <div className="bench-record-empty-runs"><strong>{runs.length === 0 ? "No exploration runs" : "No runs for this family"}</strong><span>{runs.length === 0 ? "The current catalog contains no exploration records." : "Choose another family to view recorded runs."}</span></div>}
            </div>
            <footer className="bench-record-table-foot"><span><LockKeyhole size={13} /> Read-only historical records</span><span>Source: {MOCK_CATALOG.source_label || MOCK_CATALOG.source}</span></footer>
          </section>
          <footer className="bench-record-page-foot"><span><ShieldCheck size={14} /> Research records do not represent live positions or execution.</span><span>Snapshot as of {formatDate(MOCK_CATALOG.snapshot_as_of)} <i className="strategy-static-note">Static sample records</i></span></footer>
        </div>
      </section>
    </main>
  );
}
