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
import "./ResearchOverview.css";

type Catalog = typeof MOCK_CATALOG;
type Experiment = Catalog["experiments"][number];
type ExplorationRun = Catalog["exploration_runs"][number];
type SortKey = "sharpe" | "return_pct" | "max_drawdown" | "created_at";
type ResearchGroup = "Atlas" | "Momentum" | "Bullion" | "Forex" | "Fleet" | "Other";
type ChartPoint = ExplorationRun & { drawdown: number; group: ResearchGroup };

const GROUPS: ResearchGroup[] = ["Atlas", "Momentum", "Bullion", "Forex", "Fleet", "Other"];
const GROUP_COLORS: Record<ResearchGroup, string> = {
  Atlas: "#9a654f",
  Momentum: "#466b5c",
  Bullion: "#92773f",
  Forex: "#74698a",
  Fleet: "#497d77",
  Other: "#68715f",
};

function formatDate(value?: string) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    ...(value.includes("T") ? { hour: "2-digit", minute: "2-digit", timeZone: "UTC", timeZoneName: "short" } : {}),
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

function formatSummary(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not recorded";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  try { return JSON.stringify(value, null, 2); } catch { return "Not recorded"; }
}

function familyLabel(family: string) {
  return family.replace(/^bot(\d+)_/i, "Bot $1 · ").replace(/[_-]+/g, " ")
    .replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}

function researchGroup(family: string): ResearchGroup {
  const value = family.toLowerCase();
  if (value.includes("atlas")) return "Atlas";
  if (value.includes("momentum")) return "Momentum";
  if (value.includes("bullion") || value.includes("gold") || value.includes("silver")) return "Bullion";
  if (/\bforex\b|\bfx\b|foreign[_ -]?exchange|currency|oanda/.test(value)) return "Forex";
  if (value.includes("fleet")) return "Fleet";
  return "Other";
}

function outcomeTone(outcome: string) {
  const value = outcome.toLowerCase();
  if (/fail|reject|negative|blocked|not.?pass/.test(value)) return "is-fail";
  if (/pass|verified|accept|success|ready/.test(value)) return "is-pass";
  return "is-neutral";
}

function outcomeLabel(value: string) {
  return value.replace(/[_-]+/g, " ").replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
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

function isPassed(outcome: string) {
  return /^(pass|passed|verified|accepted|success)$/i.test(outcome.trim());
}

function isSpyReference(run: ExplorationRun) {
  const record = run as ExplorationRun & { benchmark_name?: unknown; reference_name?: unknown; record_kind?: unknown; record_type?: unknown };
  const identity = [run.family, run.source, record.benchmark_name, record.reference_name, record.record_kind, record.record_type]
    .filter((value): value is string => typeof value === "string").join(" ");
  return (/\b(?:benchmark|baseline|reference)\b/i.test(identity)
      || /^spy[_\s-]+buy[\s_-]*(?:and[\s_-]*)?hold$/i.test(run.family.trim()))
    && /\bspy\b/i.test(identity)
    && /buy[\s_-]*(?:and[\s_-]*)?hold/i.test(identity);
}

function RunTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload?: ChartPoint }> }) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  return (
    <div className="bench-record-tooltip" role="status">
      <strong>{familyLabel(point.family)}</strong>
      <span>Run {point.id} · {point.group}</span>
      <dl>
        <div><dt>Sharpe</dt><dd>{formatMetric(point.sharpe, 3)}</dd></div>
        <div><dt>Maximum drawdown</dt><dd>{formatDrawdown(point.max_drawdown)}</dd></div>
        <div><dt>Return</dt><dd>{formatPercent(point.return_pct, 2)}</dd></div>
      </dl>
      <small>{point.source} · {formatDate(point.created_at)}</small>
    </div>
  );
}

export default function ResearchOverview() {
  const catalog = MOCK_CATALOG;
  const experiments = catalog.experiments;
  const runs = catalog.exploration_runs;
  const [familyFilter, setFamilyFilter] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("created_at");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  const outcomeCounts = useMemo(() => {
    const counts = new Map<string, number>();
    experiments.forEach((experiment) => {
      const outcome = experiment.outcome.trim() || "Not recorded";
      counts.set(outcome.toLowerCase(), (counts.get(outcome.toLowerCase()) ?? 0) + 1);
    });
    return [...counts.entries()].sort(([a], [b]) => {
      const order = ["pass", "fail", "pending", "dissolved"];
      const rankA = order.indexOf(a);
      const rankB = order.indexOf(b);
      return rankA !== -1 || rankB !== -1
        ? (rankA === -1 ? order.length : rankA) - (rankB === -1 ? order.length : rankB)
        : a.localeCompare(b);
    });
  }, [experiments]);
  const passedCount = experiments.filter((experiment) => isPassed(experiment.outcome)).length;
  const families = useMemo(() => [...new Set(runs.map((run) => run.family))].sort((a, b) => a.localeCompare(b)), [runs]);
  const chartPoints = useMemo<ChartPoint[]>(() => runs.flatMap((run) => (
    typeof run.sharpe === "number" && Number.isFinite(run.sharpe)
      && typeof run.max_drawdown === "number" && Number.isFinite(run.max_drawdown)
      ? [{ ...run, drawdown: Math.abs(run.max_drawdown), group: researchGroup(run.family) }]
      : []
  )), [runs]);
  const referenceRun = runs.find(isSpyReference) ?? null;
  const referencePoint = referenceRun
    ? chartPoints.find((point) => String(point.id) === String(referenceRun.id)) ?? null
    : null;
  const selectedRun = selectedRunId ? runs.find((run) => String(run.id) === selectedRunId) ?? null : null;
  const plottedIds = new Set(chartPoints.map((point) => String(point.id)));
  const chartGroups = GROUPS.map((group) => ({
    group,
    points: chartPoints.filter((point) => point.group === group && String(point.id) !== String(referencePoint?.id)),
  })).filter(({ points }) => points.length);
  const visibleRuns = useMemo(() => {
    const filtered = familyFilter === "all" ? runs : runs.filter((run) => run.family === familyFilter);
    return [...filtered].sort((a, b) => {
      const left = a[sortKey];
      const right = b[sortKey];
      if (sortKey !== "created_at" && (
        typeof left !== "number" || !Number.isFinite(left) || typeof right !== "number" || !Number.isFinite(right)
      )) {
        if (left == null && right != null) return 1;
        if (left != null && right == null) return -1;
        if (typeof left === "number" && Number.isFinite(left)) return -1;
        if (typeof right === "number" && Number.isFinite(right)) return 1;
        return 0;
      }
      const comparison = sortKey === "created_at"
        ? new Date(String(left)).getTime() - new Date(String(right)).getTime()
        : Number(left) - Number(right);
      return comparison * (sortDirection === "asc" ? 1 : -1);
    });
  }, [familyFilter, runs, sortDirection, sortKey]);

  const changeSort = (key: SortKey) => {
    if (sortKey === key) setSortDirection((direction) => direction === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDirection("desc"); }
  };
  const renderPoint = (rawProps: unknown) => {
    const props = rawProps as { cx?: number; cy?: number; fill?: string; payload?: ChartPoint };
    const point = props.payload;
    if (typeof props.cx !== "number" || typeof props.cy !== "number" || !point) return <g />;
    const selectPoint = () => setSelectedRunId(String(point.id));
    return (
      <g
        role="button"
        tabIndex={0}
        aria-label={`Inspect run ${point.id}, ${familyLabel(point.family)}, Sharpe ${formatMetric(point.sharpe, 3)}, maximum drawdown ${formatDrawdown(point.max_drawdown)}`}
        aria-pressed={selectedRunId === String(point.id)}
        onClick={(event) => { event.stopPropagation(); selectPoint(); }}
        onFocus={selectPoint}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectPoint(); }
        }}
      >
        <circle cx={props.cx} cy={props.cy} r={12} fill="transparent" />
        <circle className="bench-record-dot" cx={props.cx} cy={props.cy} r={5.5} fill={props.fill ?? GROUP_COLORS[point.group]} />
      </g>
    );
  };

  return (
    <main className="bench-shell bench-catalog bench-record-page research-overview" data-testid="page-bench">
      <aside className="bench-rail">
        <div className="bench-rail-brand">
          <div className="bench-brand-mark"><FlaskConical size={18} /></div>
          <div><span className="bench-overline">RESEARCH LEDGER</span><strong>Strategy Bench</strong></div>
        </div>
        <div className="bench-rail-rule" />
        <div className="bench-rail-spacer" />
        <div className="bench-rail-note"><span className="bench-status-dot" /><div><strong>READ ONLY</strong><span>NO ORDER PATHS</span></div></div>
        <div className="bench-rail-meta"><span>Record set</span><code>Version {catalog.schema_version}</code><span>Execution</span><code>Separate system</code></div>
      </aside>

      <section className="bench-content">
        <header className="bench-topbar">
          <div className="bench-title-group">
            <div className="bench-breadcrumb"><BookOpen size={13} /> Research / Bench</div>
            <h1>Strategy Bench</h1>
          </div>
          <span className="bench-readonly"><Database size={13} /> Read-only catalog</span>
        </header>

        <div className="bench-ledger-body bench-record-body">
          <section className="ro-overview" aria-labelledby="ro-title">
            <div className="ro-overview-main">
              <div className="bench-record-eyebrow"><BookOpen size={14} /> Research record · Version {catalog.schema_version}</div>
              <div className="ro-overview-titleline">
                <div>
                  <h2 id="ro-title">{experiments.length} research ideas recorded.</h2>
                  <p>Historical hypotheses and outcomes for inspection. This page cannot start research or route an order.</p>
                </div>
                <div className="ro-pass-tally" aria-label={`${passedCount} hypotheses passed`}>
                  <strong>{passedCount}</strong><span>passed</span>
                </div>
              </div>
              <div className="bench-record-outcomes" aria-label="Experiment outcome counts">
                {outcomeCounts.map(([outcome, count]) => (
                  <span className={`bench-record-outcome ${outcomeTone(outcome)}`} key={outcome}>
                    <b>{count}</b> {outcomeLabel(outcome)}
                  </span>
                ))}
                {!outcomeCounts.length && <span className="bench-record-outcome is-neutral">No outcomes recorded</span>}
              </div>
            </div>
            <aside className="bench-record-provenance ro-provenance" aria-label="Catalog snapshot source">
              <div className="bench-record-provenance-title"><Database size={15} /> Snapshot provenance</div>
              <dl>
                <div><dt>Source</dt><dd>{catalog.source_label || catalog.source}</dd></div>
                <div><dt>As of</dt><dd>{formatDate(catalog.snapshot_as_of)}</dd></div>
                <div><dt>Generated</dt><dd>{formatDate(catalog.generated_at)}</dd></div>
              </dl>
              {catalog.source_detail && <p>{catalog.source_detail}</p>}
            </aside>
            <div className="ro-overview-footer">
              <span><b>{experiments.length}</b> registered hypotheses</span>
              <span><b>{runs.length}</b> historical exploration runs</span>
              <span className="ro-sample"><i /> Static sample records</span>
            </div>
          </section>

          <section className="bench-record-panel bench-record-chart-panel ro-chart-panel" aria-labelledby="bench-chart-title">
            <div className="bench-record-panel-heading">
              <div>
                <span className="bench-record-section-label">01 · Risk and return</span>
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
                        {referencePoint && <Scatter name="SPY buy-and-hold" data={[referencePoint]} fill="#20332f" shape="diamond" isAnimationActive={false} />}
                      </ScatterChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <div className="bench-record-empty-chart"><BarChart3 size={20} /><strong>No runs can be plotted</strong><span>The catalog has no exploration runs with both Sharpe and maximum drawdown values.</span></div>
                )}
                {!!chartGroups.length && (
                  <div className="bench-record-legend" aria-label="Chart groups">
                    {chartGroups.map(({ group }) => <span key={group}><i style={{ backgroundColor: GROUP_COLORS[group] }} />{group}</span>)}
                    {referencePoint && <span><i className="is-benchmark" />SPY buy-and-hold</span>}
                  </div>
                )}
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
                ) : <p>Hover over or select a point to inspect its recorded metrics.</p>}
              </aside>
            </div>
            <div className="bench-record-chart-notes">
              <span>{runs.length - chartPoints.length} {runs.length - chartPoints.length === 1 ? "run is" : "runs are"} missing one or both chart metrics; all remain in the table below.</span>
              <span>{referenceRun ? (referencePoint ? "SPY buy-and-hold is marked as a reference point." : "A SPY buy-and-hold record exists but lacks the metrics needed for a reference point.") : "No SPY buy-and-hold reference is recorded in this catalog."}</span>
            </div>
          </section>

          <section className="bench-record-experiments" aria-labelledby="bench-experiments-title">
            <div className="bench-record-section-heading">
              <div><span className="bench-record-section-label">02 · Registered hypotheses</span><h2 id="bench-experiments-title">Experiments by research family</h2><p>Declared pass bars and recorded outcomes. Parameters and data windows open on demand.</p></div>
              <span className="bench-record-section-count">{experiments.length} total records</span>
            </div>
            <div className="bench-record-groups">
              {GROUPS.map((group, index) => {
                const grouped = experiments.filter((experiment) => researchGroup(experiment.family) === group);
                return (
                  <section className={`bench-record-group bench-record-group-${group.toLowerCase()}`} key={group} aria-labelledby={`ro-group-${group.toLowerCase()}`}>
                    <header><span>{String(index + 1).padStart(2, "0")}</span><h3 id={`ro-group-${group.toLowerCase()}`}>{group}</h3><small>{grouped.length} {grouped.length === 1 ? "record" : "records"}</small></header>
                    {grouped.length ? (
                      <div className="bench-record-group-items">
                        {grouped.map((experiment) => <HypothesisRecord key={experiment.id} experiment={experiment} />)}
                      </div>
                    ) : <p className="bench-record-group-empty">No registered experiments in this snapshot.</p>}
                  </section>
                );
              })}
            </div>
          </section>

          <section className="bench-record-panel bench-record-runs" aria-labelledby="bench-runs-title">
            <div className="bench-record-panel-heading bench-record-runs-heading">
              <div><span className="bench-record-section-label">03 · Historical search space</span><h2 id="bench-runs-title">Exploration runs</h2><p>Recorded parameter trials and metrics. Filter by family or sort a column.</p></div>
              <label className="bench-record-filter"><span>Family</span>
                <select value={familyFilter} onChange={(event) => setFamilyFilter(event.target.value)} aria-label="Filter exploration runs by family">
                  <option value="all">All families</option>{families.map((family) => <option key={family} value={family}>{familyLabel(family)}</option>)}
                </select>
              </label>
            </div>
            <div className="bench-record-table-meta"><span>{visibleRuns.length} of {runs.length} runs</span><span>Scroll this table to inspect more records</span></div>
            <div className="bench-record-table-scroll" role="region" aria-label="Exploration run records" tabIndex={0}>
              {visibleRuns.length ? (
                <table className="bench-record-table">
                  <thead><tr>
                    <th scope="col">Record</th><th scope="col">Family</th>
                    {([
                      ["sharpe", "Sharpe"], ["return_pct", "Return"], ["max_drawdown", "Max drawdown"], ["created_at", "Recorded"],
                    ] as [SortKey, string][]).map(([key, label]) => {
                      const Icon = sortKey === key ? sortDirection === "asc" ? ArrowUp : ArrowDown : ArrowUpDown;
                      return <th scope="col" key={key}><button type="button" className="bench-record-sort" aria-label={`Sort by ${label.toLowerCase()}`} aria-sort={sortKey === key ? sortDirection === "asc" ? "ascending" : "descending" : "none"} onClick={() => changeSort(key)}>{label}<Icon size={12} aria-hidden="true" /></button></th>;
                    })}
                    <th scope="col">Source</th><th scope="col">Parameters and window</th>
                  </tr></thead>
                  <tbody>{visibleRuns.map((run) => (
                    <tr key={run.id}>
                      <td className="bench-record-mono"><button type="button" className="bench-record-run-link" onClick={() => setSelectedRunId(String(run.id))} aria-label={`Inspect exploration run ${run.id}`}>#{run.id}</button></td>
                      <td><span className="bench-record-family"><i style={{ backgroundColor: GROUP_COLORS[researchGroup(run.family)] }} />{familyLabel(run.family)}</span></td>
                      <td className="bench-record-mono">{formatMetric(run.sharpe, 3)}</td><td className="bench-record-mono">{formatPercent(run.return_pct, 2)}</td><td className="bench-record-mono">{formatDrawdown(run.max_drawdown)}</td>
                      <td className="bench-record-mono"><span className="bench-record-date"><CalendarClock size={12} aria-hidden="true" />{formatDate(run.created_at)}</span></td>
                      <td className="bench-record-mono">{run.source}</td>
                      <td><RunDetails run={run} /></td>
                    </tr>
                  ))}</tbody>
                </table>
              ) : <div className="bench-record-empty-runs"><strong>No runs match this family</strong><span>Choose another family to inspect the historical records.</span></div>}
            </div>
            <div className="bench-record-table-foot"><span><LockKeyhole size={12} /> Historical records only · no execution controls</span><span>Snapshot {formatDate(catalog.snapshot_as_of)}</span></div>
          </section>

          <footer className="bench-record-page-foot"><span><LockKeyhole size={12} /> Read-only research ledger · no order paths</span><span>Static sample records · {catalog.row_counts.experiments} hypotheses · {catalog.row_counts.exploration_runs} exploration runs</span></footer>
        </div>
      </section>
    </main>
  );
}

function HypothesisRecord({ experiment }: { experiment: Experiment }) {
  return (
    <article className="bench-record-experiment">
      <div className="bench-record-experiment-top">
        <div><span>Record {experiment.id}</span><strong>{familyLabel(experiment.family)}</strong></div>
        <span className={`bench-record-verdict ${outcomeTone(experiment.outcome)}`}>{outcomeLabel(experiment.outcome)}</span>
      </div>
      <p className="bench-record-hypothesis" title={experiment.hypothesis}>{experiment.hypothesis || "No hypothesis was recorded."}</p>
      <div className="bench-record-evidence">
        <div><span>Pass bar</span><strong>{formatPassBar(experiment.pass_bar)}</strong></div>
        <div className="bench-record-result"><span>Result</span><div>
          <span><b>{formatMetric(experiment.metrics?.sharpe, 3)}</b><small>Sharpe</small></span>
          <span><b>{formatPercent(experiment.metrics?.return_pct, 2)}</b><small>Return</small></span>
          <span><b>{formatDrawdown(experiment.metrics?.max_drawdown_pct)}</b><small>Max drawdown</small></span>
        </div></div>
      </div>
      <details className="bench-record-disclosure">
        <summary><span>Parameters and data window</span><ChevronDown size={15} /></summary>
        <div>
          <section><span>Parameters</span><pre>{formatSummary(experiment.parameters_summary)}</pre></section>
          <section><span>Data window</span><pre>{formatSummary(experiment.data_window)}</pre></section>
          <p>Recorded {formatDate(experiment.created_at)} · outcome is historical, not actionable.</p>
        </div>
      </details>
    </article>
  );
}

function RunDetails({ run }: { run: ExplorationRun }) {
  return (
    <details className="bench-record-run-details">
      <summary><span>Inspect</span><ChevronDown size={13} /></summary>
      <div>
        <section><span>Parameters</span><pre>{formatSummary(run.parameters_summary)}</pre></section>
        <section><span>Data window</span><pre>{formatSummary(run.data_window)}</pre></section>
        <p>Source: {run.source} · recorded {formatDate(run.created_at)}</p>
      </div>
    </details>
  );
}
