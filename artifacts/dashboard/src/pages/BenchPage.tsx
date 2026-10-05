import { useEffect, useMemo, useState } from "react";
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
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
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
import { parseCatalogResponse } from "@/lib/benchApi";

type Experiment = {
  id: string | number;
  family: string;
  hypothesis: string;
  parameters_summary: string;
  pass_bar: unknown;
  data_window: unknown;
  metrics: {
    sharpe: number | null;
    return_pct: number | null;
    max_drawdown_pct: number | null;
  };
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

type Catalog = {
  schema_version: string | number;
  generated_at: string;
  snapshot_as_of: string;
  source: string;
  source_label: string;
  source_detail?: string;
  row_counts: { experiments: number; exploration_runs: number };
  experiments: Experiment[];
  exploration_runs: ExplorationRun[];
};

type SortKey = "sharpe" | "return_pct" | "max_drawdown" | "created_at";
type ResearchGroup = "Atlas" | "Momentum" | "Bullion" | "Forex" | "Fleet" | "Other";
type ChartPoint = {
  id: string | number;
  family: string;
  sharpe: number;
  drawdown: number;
  return_pct: number | null;
  source: string;
  created_at: string;
  group: ResearchGroup;
  run: ExplorationRun;
};

const CATALOG_URL = `${import.meta.env.BASE_URL}trading-api/research/strategy-bench/catalog`;
const RESEARCH_GROUPS: ResearchGroup[] = ["Atlas", "Momentum", "Bullion", "Forex", "Fleet", "Other"];
const GROUP_COLORS: Record<ResearchGroup, string> = {
  Atlas: "#9a654f",
  Momentum: "#466b5c",
  Bullion: "#92773f",
  Forex: "#74698a",
  Fleet: "#497d77",
  Other: "#68715f",
};

function formatDate(value: string | undefined) {
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

function formatPercent(value: number | null | undefined, digits = 1) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

function formatDrawdown(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "-" : ""}${Math.abs(value).toFixed(1)}%`;
}

function outcomeTone(outcome: string) {
  const normalized = outcome.toLowerCase();
  if (/fail|reject|negative|blocked|not.?pass/.test(normalized)) return "is-fail";
  if (/pass|verified|accept|success|ready/.test(normalized)) return "is-pass";
  return "is-neutral";
}

function researchGroup(family: string): ResearchGroup {
  const value = family.toLowerCase();
  if (value.includes("atlas")) return "Atlas";
  if (value.includes("momentum")) return "Momentum";
  if (
    value.includes("bullion")
    || value.includes("gold")
    || value.includes("silver")
  ) return "Bullion";
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

function formatPassBar(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return formatSummary(value);
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length === 0) return "Not recorded";
  return entries.map(([key, threshold]) => {
    const operator = key.endsWith("_min") ? "≥" : key.endsWith("_max") ? "≤" : "=";
    const label = key.replace(/_(min|max)$/, "").replace(/_/g, " ");
    return `${label} ${operator} ${formatSummary(threshold)}`;
  }).join(" · ");
}

function isPassedOutcome(outcome: string) {
  return /^(pass|passed|verified|accepted|success)$/i.test(outcome.trim());
}

function isSpyBuyAndHold(run: ExplorationRun) {
  const row = run as ExplorationRun & {
    benchmark_name?: unknown;
    reference_name?: unknown;
    record_kind?: unknown;
    record_type?: unknown;
  };
  const identity = [
    run.family,
    run.source,
    row.benchmark_name,
    row.reference_name,
    row.record_kind,
    row.record_type,
  ].filter((value): value is string => typeof value === "string").join(" ");
  const explicitlyNamedReference = /\b(?:benchmark|baseline|reference)\b/i.test(identity)
    || /^spy[_\s-]+buy[\s_-]*(?:and[\s_-]*)?hold$/i.test(run.family.trim());
  // Do not infer a benchmark from strategy parameters or from a run that merely mentions SPY.
  return explicitlyNamedReference
    && /\bspy\b/i.test(identity)
    && /buy[\s_-]*(?:and[\s_-]*)?hold/i.test(identity);
}

type RunTooltipProps = {
  active?: boolean;
  payload?: Array<{ payload?: ChartPoint }>;
};

function RunTooltip({ active, payload }: RunTooltipProps) {
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
      <small>{point.source} · {formatDate(point.created_at)}</small>
    </div>
  );
}

function CatalogSkeleton() {
  return (
    <main className="bench-shell bench-catalog bench-record-page" data-testid="status-bench-loading" aria-busy="true">
      <aside className="bench-rail">
        <div className="bench-rail-brand">
          <div className="bench-brand-mark"><FlaskConical size={18} /></div>
          <div><span className="bench-overline">RESEARCH LEDGER</span><strong>Strategy Bench</strong></div>
        </div>
        <div className="bench-rail-rule" />
        <div className="bench-rail-spacer" />
        <div className="bench-rail-note"><span className="bench-status-dot" /><div><strong>READ ONLY</strong><span>NO ORDER PATHS</span></div></div>
      </aside>
      <section className="bench-content">
        <header className="bench-topbar">
          <div className="bench-title-group"><div className="bench-breadcrumb"><BookOpen size={13} /> Research / Bench</div><h1>Strategy Bench</h1></div>
          <span className="bench-readonly"><Database size={13} /> Research records</span>
        </header>
        <div className="bench-ledger-body bench-record-body">
          <div className="bench-record-skeleton" data-testid="panel-bench-loading">
            <span className="bench-record-eyebrow">Research catalog</span>
            <div className="bench-record-skeleton-line" />
            <div className="bench-record-skeleton-line" />
            <div className="bench-record-skeleton-line" />
            </div>
        </div>
      </section>
    </main>
  );
}

export default function BenchPage() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [familyFilter, setFamilyFilter] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("created_at");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    // This catalog is an audit surface only; its sole request is explicitly GET.
    fetch(CATALOG_URL, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: controller.signal,
    }).then(async (response) => {
      const payload = await parseCatalogResponse<Catalog>(response);
      if (!payload || !Array.isArray(payload.experiments) || !Array.isArray(payload.exploration_runs)) {
        throw new Error(`HTTP ${response.status}: The response body does not match the research catalog contract.`);
      }
      setCatalog(payload);
    }).catch((caught: unknown) => {
      if (!controller.signal.aborted) {
        setCatalog(null);
        setError(caught instanceof Error ? caught.message : "The research catalog could not be loaded.");
      }
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [attempt]);

  const experiments = catalog?.experiments ?? [];
  const runs = catalog?.exploration_runs ?? [];
  const outcomeCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const experiment of experiments) {
      const outcome = experiment.outcome.trim() || "Not recorded";
      const key = outcome.toLowerCase();
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    const outcomeOrder = ["pass", "fail", "pending", "dissolved"];
    return [...counts.entries()].sort(([left], [right]) => {
      const leftRank = outcomeOrder.indexOf(left);
      const rightRank = outcomeOrder.indexOf(right);
      if (leftRank !== -1 || rightRank !== -1) {
        return (leftRank === -1 ? outcomeOrder.length : leftRank)
          - (rightRank === -1 ? outcomeOrder.length : rightRank);
      }
      return left.localeCompare(right);
    });
  }, [experiments]);
  const passedCount = experiments.filter((experiment) => isPassedOutcome(experiment.outcome)).length;
  const families = useMemo(
    () => [...new Set(runs.map((run) => run.family))].sort((a, b) => a.localeCompare(b)),
    [runs],
  );
  const chartPoints = useMemo<ChartPoint[]>(() => runs.flatMap((run) => {
    if (
      typeof run.sharpe !== "number"
      || !Number.isFinite(run.sharpe)
      || typeof run.max_drawdown !== "number"
      || !Number.isFinite(run.max_drawdown)
    ) return [];
    const group = researchGroup(run.family);
    return [{
      id: run.id,
      family: run.family,
      sharpe: run.sharpe,
      drawdown: Math.abs(run.max_drawdown),
      return_pct: run.return_pct,
      source: run.source,
      created_at: run.created_at,
      group,
      run,
    }];
  }), [runs]);
  const spyReference = runs.find(isSpyBuyAndHold) ?? null;
  const spyBenchmark = spyReference
    ? chartPoints.find((point) => String(point.id) === String(spyReference.id)) ?? null
    : null;
  const selectedRun = selectedRunId
    ? runs.find((run) => String(run.id) === selectedRunId) ?? null
    : null;
  const plottedRunIds = new Set(chartPoints.map((point) => String(point.id)));
  const chartGroups = RESEARCH_GROUPS.map((group) => ({
    group,
    points: chartPoints.filter((point) => point.group === group && String(point.id) !== String(spyBenchmark?.id)),
  })).filter(({ points }) => points.length > 0);
  const visibleRuns = useMemo(() => {
    const filtered = familyFilter === "all" ? runs : runs.filter((run) => run.family === familyFilter);
    return [...filtered].sort((a, b) => {
      const left = a[sortKey];
      const right = b[sortKey];
      if (sortKey !== "created_at" && (
        typeof left !== "number" || !Number.isFinite(left)
        || typeof right !== "number" || !Number.isFinite(right)
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

  function changeSort(key: SortKey) {
    if (sortKey === key) setSortDirection((direction) => direction === "asc" ? "desc" : "asc");
    else {
      setSortKey(key);
      setSortDirection("desc");
    }
  }

  if (loading && !catalog) return <CatalogSkeleton />;

  const headline = experiments.length === 0
    ? "No research ideas recorded yet."
    : `${experiments.length} research idea${experiments.length === 1 ? "" : "s"} recorded. ${passedCount} passed.`;

  const renderPoint = (rawProps: unknown) => {
    const props = rawProps as { cx?: number; cy?: number; fill?: string; payload?: ChartPoint };
    const point = props.payload;
    if (typeof props.cx !== "number" || typeof props.cy !== "number" || !point) return <g />;
    const selectPoint = () => setSelectedRunId(String(point.id));
    return (
      <g
        role="button"
        tabIndex={0}
        aria-label={`Inspect run ${point.id}, ${familyLabel(point.family)}, Sharpe ${formatMetric(point.sharpe, 3)}, maximum drawdown ${formatDrawdown(point.run.max_drawdown)}`}
        aria-pressed={selectedRunId === String(point.id)}
        data-testid={`plot-run-${point.id}`}
        onClick={(event) => { event.stopPropagation(); selectPoint(); }}
        onFocus={selectPoint}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            selectPoint();
          }
        }}
      >
        <circle cx={props.cx} cy={props.cy} r={12} fill="transparent" />
        <circle className="bench-record-dot" cx={props.cx} cy={props.cy} r={5.5} fill={props.fill ?? GROUP_COLORS[point.group]} />
      </g>
    );
  };

  const outcomeLabel = (outcome: string) => outcome
    .replace(/[_-]+/g, " ")
    .replace(/\b[a-z]/g, (letter) => letter.toUpperCase());

  return (
    <main className="bench-shell bench-catalog bench-record-page" data-testid="page-bench">
      <aside className="bench-rail">
        <div className="bench-rail-brand">
          <div className="bench-brand-mark"><FlaskConical size={18} /></div>
          <div><span className="bench-overline">RESEARCH LEDGER</span><strong>Strategy Bench</strong></div>
        </div>
        <div className="bench-rail-rule" />
        <div className="bench-rail-spacer" />
        <div className="bench-rail-note"><span className="bench-status-dot" /><div><strong>READ ONLY</strong><span>NO ORDER PATHS</span></div></div>
        <div className="bench-rail-meta"><span>Record set</span><code>{catalog ? `Version ${catalog.schema_version}` : "Unavailable"}</code><span>Execution</span><code>Separate system</code></div>
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
          {error ? (
            <section className="bench-record-panel bench-record-message" role="alert" data-testid="status-bench-error">
              <TriangleAlert size={24} />
              <strong>Research records are unavailable</strong>
              <p>The catalog could not be read. No research action was submitted.</p>
              <p className="bench-record-error-detail" data-testid="text-bench-error-detail">{error}</p>
              <button className="bench-record-retry" data-testid="button-retry-bench" onClick={() => setAttempt((value) => value + 1)}>
                <RefreshCw size={14} /> Retry catalog read
              </button>
            </section>
          ) : catalog ? (
            <>
              <div className="bench-record-intro">
                <section className="bench-record-headline" aria-labelledby="bench-record-title">
                  <div className="bench-record-eyebrow"><BookOpen size={14} /> Research record · Version {catalog.schema_version}</div>
                  <h2 id="bench-record-title" data-testid="text-bench-headline">{headline}</h2>
                  <p>Historical hypotheses and outcomes for inspection. This page cannot start research or route an order.</p>
                  <div className="bench-record-outcomes" aria-label="Experiment outcome counts">
                    {outcomeCounts.length > 0 ? outcomeCounts.map(([outcome, count]) => (
                      <span className={`bench-record-outcome ${outcomeTone(outcome)}`} key={outcome}>
                        <b>{count}</b> {outcomeLabel(outcome)}
                      </span>
                    )) : <span className="bench-record-outcome is-neutral">No outcomes recorded</span>}
                  </div>
                </section>
                <aside className="bench-record-provenance" aria-label="Catalog snapshot source">
                  <div className="bench-record-provenance-title"><Database size={15} /> Snapshot provenance</div>
                  <dl>
                    <div><dt>Source</dt><dd data-testid="text-bench-source">{catalog.source_label || catalog.source}</dd></div>
                    <div><dt>As of</dt><dd data-testid="text-bench-as-of">{formatDate(catalog.snapshot_as_of)}</dd></div>
                    <div><dt>Generated</dt><dd>{formatDate(catalog.generated_at)}</dd></div>
                  </dl>
                  {catalog.source_detail && <p>{catalog.source_detail}</p>}
                </aside>
              </div>

              <section className="bench-record-panel bench-record-chart-panel" aria-labelledby="bench-chart-title">
                <div className="bench-record-panel-heading">
                  <div>
                    <span className="bench-record-section-label">01 · Risk and return</span>
                    <h2 id="bench-chart-title">Sharpe vs maximum drawdown</h2>
                    <p>Each point is an exploration run with both chart metrics recorded.</p>
                  </div>
                  <span className="bench-record-chart-count" data-testid="text-plotted-run-count">
                    {chartPoints.length} of {runs.length} runs plotted
                  </span>
                </div>
                <div className="bench-record-chart-layout">
                  <div className="bench-record-chart-column">
                    {chartPoints.length > 0 ? (
                      <div className="bench-record-chart" role="group" aria-label="Sharpe ratio against maximum drawdown. Select a point for run details.">
                        <ResponsiveContainer width="100%" height="100%">
                          <ScatterChart margin={{ top: 14, right: 20, bottom: 25, left: 6 }}>
                            <CartesianGrid stroke="rgba(55, 78, 69, .18)" vertical strokeDasharray="3 5" />
                            <XAxis
                              type="number"
                              dataKey="sharpe"
                              name="Sharpe"
                              tick={{ fill: "#5d7067", fontSize: 11 }}
                              tickLine={false}
                              axisLine={{ stroke: "rgba(53, 75, 66, .45)" }}
                              tickFormatter={(value: number) => Number(value).toFixed(1)}
                              label={{ value: "Sharpe ratio", position: "insideBottom", offset: -13, fill: "#4f665c", fontSize: 11 }}
                            />
                            <YAxis
                              type="number"
                              dataKey="drawdown"
                              name="Maximum drawdown"
                              reversed
                              domain={[0, "auto"]}
                              width={52}
                              tick={{ fill: "#5d7067", fontSize: 10 }}
                              tickLine={false}
                              axisLine={false}
                              tickFormatter={(value: number) => `−${Math.abs(value).toFixed(0)}%`}
                            />
                            <Tooltip content={<RunTooltip />} cursor={{ stroke: "rgba(50, 83, 66, .42)", strokeDasharray: "3 4" }} />
                            {chartGroups.map(({ group, points }) => (
                              <Scatter
                                key={group}
                                name={group}
                                data={points}
                                fill={GROUP_COLORS[group]}
                                shape={renderPoint}
                                isAnimationActive={false}
                              />
                            ))}
                            {spyBenchmark && (
                              <Scatter
                                name="SPY buy-and-hold"
                                data={[spyBenchmark]}
                                fill="#20332f"
                                shape="diamond"
                                isAnimationActive={false}
                              />
                            )}
                          </ScatterChart>
                        </ResponsiveContainer>
                      </div>
                    ) : (
                      <div className="bench-record-empty-chart" data-testid="status-no-plottable-runs">
                        <BarChart3 size={20} />
                        <strong>No runs can be plotted</strong>
                        <span>The catalog has no exploration runs with both Sharpe and maximum drawdown values.</span>
                      </div>
                    )}
                    {chartGroups.length > 0 && (
                      <div className="bench-record-legend" aria-label="Chart groups">
                        {chartGroups.map(({ group }) => (
                          <span key={group}><i style={{ backgroundColor: GROUP_COLORS[group] }} />{group}</span>
                        ))}
                        {spyBenchmark && <span><i className="is-benchmark" />SPY buy-and-hold</span>}
                      </div>
                    )}
                  </div>
                  <aside className="bench-record-selection" aria-live="polite" aria-label="Selected exploration run">
                    {selectedRun ? (
                      <>
                        <span className="bench-record-selection-label">
                          {plottedRunIds.has(String(selectedRun.id)) ? "Selected run" : "Selected run · chart metrics incomplete"}
                        </span>
                        <strong>{familyLabel(selectedRun.family)}</strong>
                        <span className="bench-record-selection-id">Record {selectedRun.id} · {selectedRun.source}</span>
                        <dl>
                          <div><dt>Sharpe</dt><dd>{formatMetric(selectedRun.sharpe, 3)}</dd></div>
                          <div><dt>Maximum drawdown</dt><dd>{formatDrawdown(selectedRun.max_drawdown)}</dd></div>
                          <div><dt>Return</dt><dd>{formatPercent(selectedRun.return_pct, 2)}</dd></div>
                        </dl>
                        <time>{formatDate(selectedRun.created_at)}</time>
                      </>
                    ) : (
                      <p>Hover over or select a point to inspect its recorded metrics.</p>
                    )}
                  </aside>
                </div>
                <div className="bench-record-chart-notes">
                  <span>{runs.length - chartPoints.length} {runs.length - chartPoints.length === 1 ? "run is" : "runs are"} missing one or both chart metrics; all remain in the table below.</span>
                  <span>
                    {spyReference
                      ? spyBenchmark
                        ? "SPY buy-and-hold is marked as a reference point."
                        : "A SPY buy-and-hold record exists but lacks the metrics needed for a reference point."
                      : "No SPY buy-and-hold reference is recorded in this catalog."}
                  </span>
                </div>
              </section>

              <section className="bench-record-experiments" aria-labelledby="bench-experiments-title">
                <div className="bench-record-section-heading">
                  <div>
                    <span className="bench-record-section-label">02 · Registered hypotheses</span>
                    <h2 id="bench-experiments-title">Experiments by research family</h2>
                    <p>Declared pass bars and recorded outcomes. Parameters and data windows open on demand.</p>
                  </div>
                  <span className="bench-record-section-count" data-testid="value-experiment-count">{experiments.length} total records</span>
                </div>
                <div className="bench-record-groups">
                  {RESEARCH_GROUPS.map((group, index) => {
                    const groupExperiments = experiments.filter((experiment) => researchGroup(experiment.family) === group);
                    return (
                      <section className={`bench-record-group bench-record-group-${group.toLowerCase()}`} key={group} aria-labelledby={`bench-group-${group.toLowerCase()}`} data-testid={`group-${group.toLowerCase()}`}>
                        <header>
                          <span>{String(index + 1).padStart(2, "0")}</span>
                          <h3 id={`bench-group-${group.toLowerCase()}`}>{group}</h3>
                          <small>{groupExperiments.length} {groupExperiments.length === 1 ? "record" : "records"}</small>
                        </header>
                        {groupExperiments.length > 0 ? (
                          <div className="bench-record-group-items">
                            {groupExperiments.map((experiment) => (
                              <article className="bench-record-experiment" key={experiment.id} data-testid={`row-experiment-${experiment.id}`}>
                                <div className="bench-record-experiment-top">
                                  <div>
                                    <span>Record {experiment.id}</span>
                                    <strong>{familyLabel(experiment.family)}</strong>
                                  </div>
                                  <span className={`bench-record-verdict ${outcomeTone(experiment.outcome)}`} data-testid={`status-outcome-${experiment.id}`}>
                                    {outcomeLabel(experiment.outcome)}
                                  </span>
                                </div>
                                <p className="bench-record-hypothesis" title={experiment.hypothesis}>{experiment.hypothesis || "No hypothesis was recorded."}</p>
                                <div className="bench-record-evidence">
                                  <div>
                                    <span>Pass bar</span>
                                    <strong>{formatPassBar(experiment.pass_bar)}</strong>
                                  </div>
                                  <div className="bench-record-result">
                                    <span>Result</span>
                                    <div>
                                      <span><b>{formatMetric(experiment.metrics?.sharpe, 3)}</b><small>Sharpe</small></span>
                                      <span><b>{formatPercent(experiment.metrics?.return_pct, 2)}</b><small>Return</small></span>
                                      <span><b>{formatDrawdown(experiment.metrics?.max_drawdown_pct)}</b><small>Max drawdown</small></span>
                                    </div>
                                  </div>
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
                            ))}
                          </div>
                        ) : (
                          <p className="bench-record-group-empty">No registered experiments in this snapshot.</p>
                        )}
                      </section>
                    );
                  })}
                </div>
                {experiments.length === 0 && (
                  <p className="bench-record-empty-note" data-testid="status-experiments-empty">The current catalog contains no experiment records.</p>
                )}
              </section>

              <section className="bench-record-panel bench-record-runs" aria-labelledby="bench-runs-title">
                <div className="bench-record-panel-heading bench-record-runs-heading">
                  <div>
                    <span className="bench-record-section-label">03 · Historical search space</span>
                    <h2 id="bench-runs-title">Exploration runs</h2>
                    <p>Recorded parameter trials and metrics. Filter by family or sort a column.</p>
                  </div>
                  <label className="bench-record-filter">
                    <span>Family</span>
                    <select data-testid="select-family-filter" value={familyFilter} onChange={(event) => setFamilyFilter(event.target.value)}>
                      <option value="all">All families</option>
                      {families.map((family) => <option key={family} value={family}>{familyLabel(family)}</option>)}
                    </select>
                  </label>
                </div>
                <div className="bench-record-table-meta">
                  <span data-testid="text-visible-run-count">{visibleRuns.length} of {runs.length} runs</span>
                  <span>Scroll this table to inspect more records</span>
                </div>
                <div className="bench-record-table-scroll" role="region" aria-label="Exploration run records" tabIndex={0}>
                  {visibleRuns.length > 0 ? (
                    <table className="bench-record-table">
                      <thead>
                        <tr>
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
                                <button type="button" className="bench-record-sort" data-testid={`sort-runs-${key}`} aria-label={`Sort by ${label.toLowerCase()}`} onClick={() => changeSort(key)}>
                                  {label}<SortIcon size={12} aria-hidden="true" />
                                </button>
                              </th>
                            );
                          })}
                          <th scope="col">Source</th>
                          <th scope="col">Parameters and window</th>
                        </tr>
                      </thead>
                      <tbody>
                        {visibleRuns.map((run) => (
                          <tr key={run.id} data-testid={`row-run-${run.id}`}>
                            <td className="bench-record-mono">
                              <button type="button" className="bench-record-run-link" onClick={() => setSelectedRunId(String(run.id))} aria-label={`Inspect exploration run ${run.id}`}>
                                #{run.id}
                              </button>
                            </td>
                            <td><span className="bench-record-family"><i style={{ backgroundColor: GROUP_COLORS[researchGroup(run.family)] }} />{familyLabel(run.family)}</span></td>
                            <td className="bench-record-mono">{formatMetric(run.sharpe, 3)}</td>
                            <td className="bench-record-mono">{formatPercent(run.return_pct, 2)}</td>
                            <td className="bench-record-mono">{formatDrawdown(run.max_drawdown)}</td>
                            <td className="bench-record-mono"><span className="bench-record-date"><CalendarClock size={12} />{formatDate(run.created_at)}</span></td>
                            <td className="bench-record-mono">{run.source || "Not recorded"}</td>
                            <td>
                              <details className="bench-record-run-details">
                                <summary>Inspect <ChevronDown size={13} /></summary>
                                <div>
                                  <section><span>Parameters</span><pre>{formatSummary(run.parameters_summary)}</pre></section>
                                  <section><span>Data window</span><pre>{formatSummary(run.data_window)}</pre></section>
                                </div>
                              </details>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <div className="bench-record-empty-runs" data-testid="status-runs-empty">
                      <strong>{runs.length === 0 ? "No exploration runs" : "No runs for this family"}</strong>
                      <span>{runs.length === 0 ? "The current catalog contains no exploration records." : "Choose another family to view recorded runs."}</span>
                    </div>
                  )}
                </div>
                <footer className="bench-record-table-foot">
                  <span><LockKeyhole size={13} /> Read-only historical records</span>
                  <span>Source: {catalog.source_label || catalog.source}</span>
                </footer>
              </section>

              <footer className="bench-record-page-foot">
                <span><ShieldCheck size={14} /> Research records do not represent live positions or execution.</span>
                <span>Snapshot as of {formatDate(catalog.snapshot_as_of)}</span>
              </footer>
            </>
          ) : null}
        </div>
      </section>
    </main>
  );
}