import { useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronDown, RefreshCw } from "lucide-react";
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
import { Shell, Status } from "@/components/Shell";

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
// Night Glass: no colour per research group; each group gets its own white glyph.
type Glyph = "dot" | "ring" | "square" | "triangle" | "cross" | "small";
const GROUP_GLYPH: Record<ResearchGroup, Glyph> = {
  Atlas: "dot", Momentum: "ring", Bullion: "square", Forex: "triangle", Fleet: "cross", Other: "small",
};

function GlyphMark({ glyph, cx, cy, size = 5.5 }: { glyph: Glyph | "diamond"; cx: number; cy: number; size?: number }) {
  const s = size;
  const white = "#FFFFFF";
  switch (glyph) {
    case "ring": return <circle cx={cx} cy={cy} r={s - 0.75} fill="none" stroke={white} strokeWidth={1.5} />;
    case "square": return <rect x={cx - s + 1} y={cy - s + 1} width={2 * s - 2} height={2 * s - 2} fill={white} fillOpacity={0.72} />;
    case "triangle": return <path d={`M${cx} ${cy - s}L${cx + s} ${cy + s - 1}L${cx - s} ${cy + s - 1}Z`} fill="none" stroke={white} strokeWidth={1.5} />;
    case "cross": return <path d={`M${cx - s} ${cy}H${cx + s}M${cx} ${cy - s}V${cy + s}`} stroke={white} strokeWidth={1.5} />;
    case "small": return <circle cx={cx} cy={cy} r={2.5} fill={white} fillOpacity={0.62} />;
    case "diamond": return <path d={`M${cx} ${cy - s - 1}L${cx + s + 1} ${cy}L${cx} ${cy + s + 1}L${cx - s - 1} ${cy}Z`} fill="none" stroke={white} strokeWidth={1.5} />;
    default: return <circle cx={cx} cy={cy} r={s - 1} fill={white} />;
  }
}

const GlyphIcon = ({ glyph }: { glyph: Glyph | "diamond" }) => (
  <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><GlyphMark glyph={glyph} cx={7} cy={7} size={5} /></svg>
);

function formatDate(value: string | undefined) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    ...(value.includes("T") ? { hour: "2-digit", minute: "2-digit", timeZone: "Australia/Brisbane" } : { timeZone: "UTC" }),
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

/** Status dot for an outcome: problem for a fail, a white dot for a pass, hollow otherwise. */
function outcomeTone(outcome: string): "ok" | "problem" | "none" {
  const normalized = outcome.toLowerCase();
  if (/fail|reject|negative|blocked|not.?pass/.test(normalized)) return "problem";
  if (/pass|verified|accept|success|ready/.test(normalized)) return "ok";
  return "none";
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
    <div className="chart-tip" role="status">
      <span className="label">Run {point.id} · {point.group}</span>
      <strong>{familyLabel(point.family)}</strong>
      <div className="tab">Sharpe {formatMetric(point.sharpe, 3)} · worst fall {formatDrawdown(point.run.max_drawdown)} · return {formatPercent(point.return_pct, 2)}</div>
      <div className="note">{point.source} · {formatDate(point.created_at)}</div>
    </div>
  );
}

function CatalogSkeleton() {
  return (
    <Shell>
      <main className="bench" data-testid="status-bench-loading" aria-busy="true">
        <div className="page-head"><h1 className="page-title">Strategy Bench</h1><span className="label">Research record · read-only</span></div>
        <section className="glass panel" data-testid="panel-bench-loading"><div className="empty">Reading the research catalog…</div></section>
      </main>
    </Shell>
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
    const props = rawProps as { cx?: number; cy?: number; payload?: ChartPoint };
    const point = props.payload;
    if (typeof props.cx !== "number" || typeof props.cy !== "number" || !point) return <g />;
    const selectPoint = () => setSelectedRunId(String(point.id));
    const selected = selectedRunId === String(point.id);
    return (
      <g
        role="button"
        tabIndex={0}
        aria-label={`Inspect run ${point.id}, ${familyLabel(point.family)}, Sharpe ${formatMetric(point.sharpe, 3)}, maximum drawdown ${formatDrawdown(point.run.max_drawdown)}`}
        aria-pressed={selected}
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
        {selected && <circle cx={props.cx} cy={props.cy} r={10} fill="none" stroke="#7CC9E8" strokeWidth={1.5} />}
        <GlyphMark glyph={GROUP_GLYPH[point.group]} cx={props.cx} cy={props.cy} />
      </g>
    );
  };

  const outcomeLabel = (outcome: string) => outcome
    .replace(/[_-]+/g, " ")
    .replace(/\b[a-z]/g, (letter) => letter.toUpperCase());

  const AXIS = "rgba(255,255,255,0.62)";

  return (
    <Shell>
      <main className="bench" data-testid="page-bench">
        <div className="page-head">
          <div>
            <span className="label">Research record{catalog ? ` · version ${catalog.schema_version}` : ""} · read-only</span>
            <h1 className="page-title">Strategy Bench</h1>
          </div>
          <span className="label">Cannot start research or place orders</span>
        </div>

        {error ? (
          <section className="glass panel" role="alert" data-testid="status-bench-error">
            <Status tone="problem" word="Research records are unavailable" />
            <p className="body" style={{ margin: 0 }}>The catalog could not be read. No research action was submitted.</p>
            <p className="note mono" style={{ margin: 0 }} data-testid="text-bench-error-detail">{error}</p>
            <div><button className="btn" data-testid="button-retry-bench" onClick={() => setAttempt((value) => value + 1)}>
              <RefreshCw size={15} aria-hidden="true" /> Retry catalog read
            </button></div>
          </section>
        ) : catalog ? (
          <>
            <div className="bench-intro">
              <section className="glass panel" aria-labelledby="bench-record-title">
                <h2 id="bench-record-title" className="heading" data-testid="text-bench-headline">{headline}</h2>
                <p className="body" style={{ margin: 0 }}>Historical hypotheses and outcomes for inspection. This page cannot start research or route an order.</p>
                <div className="bench-outcomes" aria-label="Experiment outcome counts">
                  {outcomeCounts.length > 0 ? outcomeCounts.map(([outcome, count]) => (
                    <Status key={outcome} tone={outcomeTone(outcome)} word={`${count} ${outcomeLabel(outcome)}`} />
                  )) : <Status tone="none" word="No outcomes recorded" />}
                </div>
              </section>
              <aside className="glass panel" aria-label="Catalog snapshot source">
                <h2 className="card-title">Snapshot source</h2>
                <dl className="facts">
                  <div><dt className="label">Source</dt><dd data-testid="text-bench-source">{catalog.source_label || catalog.source}</dd></div>
                  <div><dt className="label">As of</dt><dd data-testid="text-bench-as-of">{formatDate(catalog.snapshot_as_of)}</dd></div>
                  <div><dt className="label">Generated</dt><dd>{formatDate(catalog.generated_at)}</dd></div>
                </dl>
                {catalog.source_detail && <p className="note" style={{ margin: 0 }}>{catalog.source_detail}</p>}
              </aside>
            </div>

            <section className="glass panel" aria-labelledby="bench-chart-title">
              <div className="panel-head">
                <div>
                  <span className="label">01 · Risk and return</span>
                  <h2 id="bench-chart-title" className="heading">Sharpe vs worst fall</h2>
                  <p className="small" style={{ margin: 0 }}>Each mark is an exploration run with both chart numbers recorded.</p>
                </div>
                <span className="label" data-testid="text-plotted-run-count">{chartPoints.length} of {runs.length} runs plotted</span>
              </div>
              <div className="bench-chart-layout">
                <div className="bench-chart-col">
                  {chartPoints.length > 0 ? (
                    <div className="bench-chart" role="group" aria-label="Sharpe ratio against maximum drawdown. Select a point for run details.">
                      <ResponsiveContainer width="100%" height="100%">
                        <ScatterChart margin={{ top: 14, right: 20, bottom: 25, left: 6 }}>
                          <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical strokeDasharray="3 5" />
                          <XAxis type="number" dataKey="sharpe" name="Sharpe" tick={{ fill: AXIS, fontSize: 11 }} tickLine={false}
                            axisLine={{ stroke: "rgba(255,255,255,0.10)" }} tickFormatter={(value: number) => Number(value).toFixed(1)}
                            label={{ value: "Sharpe ratio", position: "insideBottom", offset: -13, fill: AXIS, fontSize: 11 }} />
                          <YAxis type="number" dataKey="drawdown" name="Maximum drawdown" reversed domain={[0, "auto"]} width={52}
                            tick={{ fill: AXIS, fontSize: 10 }} tickLine={false} axisLine={false}
                            tickFormatter={(value: number) => `−${Math.abs(value).toFixed(0)}%`} />
                          <Tooltip content={<RunTooltip />} cursor={{ stroke: "rgba(255,255,255,0.2)", strokeDasharray: "3 4" }} />
                          {chartGroups.map(({ group, points }) => (
                            <Scatter key={group} name={group} data={points} shape={renderPoint} isAnimationActive={false} />
                          ))}
                          {spyBenchmark && (
                            <Scatter name="SPY buy-and-hold" data={[spyBenchmark]} isAnimationActive={false}
                              shape={(p: unknown) => {
                                const q = p as { cx?: number; cy?: number };
                                return typeof q.cx === "number" && typeof q.cy === "number"
                                  ? <GlyphMark glyph="diamond" cx={q.cx} cy={q.cy} size={6} /> : <g />;
                              }} />
                          )}
                        </ScatterChart>
                      </ResponsiveContainer>
                    </div>
                  ) : (
                    <div className="empty" data-testid="status-no-plottable-runs">
                      No runs can be plotted. The catalog has no exploration runs with both Sharpe and worst-fall values.
                    </div>
                  )}
                  {chartGroups.length > 0 && (
                    <div className="key" aria-label="Chart groups">
                      {chartGroups.map(({ group }) => <span key={group}><GlyphIcon glyph={GROUP_GLYPH[group]} />{group}</span>)}
                      {spyBenchmark && <span><GlyphIcon glyph="diamond" />SPY buy-and-hold</span>}
                    </div>
                  )}
                </div>
                <aside className="bench-selection" aria-live="polite" aria-label="Selected exploration run">
                  {selectedRun ? (
                    <>
                      <span className="label">
                        {plottedRunIds.has(String(selectedRun.id)) ? "Selected run" : "Selected run · chart numbers incomplete"}
                      </span>
                      <strong className="card-title">{familyLabel(selectedRun.family)}</strong>
                      <span className="note mono">Record {selectedRun.id} · {selectedRun.source}</span>
                      <dl className="facts">
                        <div><dt className="label">Sharpe</dt><dd className="tab">{formatMetric(selectedRun.sharpe, 3)}</dd></div>
                        <div><dt className="label">Worst fall</dt><dd className="tab">{formatDrawdown(selectedRun.max_drawdown)}</dd></div>
                        <div><dt className="label">Return</dt><dd className="tab">{formatPercent(selectedRun.return_pct, 2)}</dd></div>
                      </dl>
                      <time className="note">{formatDate(selectedRun.created_at)}</time>
                    </>
                  ) : (
                    <p className="note" style={{ margin: 0 }}>Hover over or select a mark to see its recorded numbers.</p>
                  )}
                </aside>
              </div>
              <div className="note bench-notes">
                <span>{runs.length - chartPoints.length} {runs.length - chartPoints.length === 1 ? "run is" : "runs are"} missing one or both chart numbers; all remain in the table below.</span>
                <span>
                  {spyReference
                    ? spyBenchmark
                      ? "SPY buy-and-hold is marked as a reference point."
                      : "A SPY buy-and-hold record exists but lacks the numbers needed for a reference point."
                    : "No SPY buy-and-hold reference is recorded in this catalog."}
                </span>
              </div>
            </section>

            <section aria-labelledby="bench-experiments-title" className="bench-section">
              <div className="page-head">
                <div>
                  <span className="label">02 · Registered hypotheses</span>
                  <h2 id="bench-experiments-title" className="heading">Experiments by research family</h2>
                  <p className="small" style={{ margin: 0 }}>Declared pass bars and recorded outcomes. Parameters and data windows open on demand.</p>
                </div>
                <span className="label" data-testid="value-experiment-count">{experiments.length} total records</span>
              </div>
              <div className="bench-groups">
                {RESEARCH_GROUPS.map((group) => {
                  const groupExperiments = experiments.filter((experiment) => researchGroup(experiment.family) === group);
                  return (
                    <section className="glass panel" key={group} aria-labelledby={`bench-group-${group.toLowerCase()}`} data-testid={`group-${group.toLowerCase()}`}>
                      <div className="panel-head">
                        <h3 id={`bench-group-${group.toLowerCase()}`} className="card-title"><GlyphIcon glyph={GROUP_GLYPH[group]} /> {group}</h3>
                        <span className="label">{groupExperiments.length} {groupExperiments.length === 1 ? "record" : "records"}</span>
                      </div>
                      {groupExperiments.length > 0 ? (
                        <ul className="list">
                          {groupExperiments.map((experiment) => (
                            <li className="bench-experiment" key={experiment.id} data-testid={`row-experiment-${experiment.id}`}>
                              <div className="bench-experiment-top">
                                <div className="grow">
                                  <span className="label">Record {experiment.id}</span>
                                  <strong className="card-title">{familyLabel(experiment.family)}</strong>
                                </div>
                                <span data-testid={`status-outcome-${experiment.id}`}>
                                  <Status tone={outcomeTone(experiment.outcome)} word={outcomeLabel(experiment.outcome)} />
                                </span>
                              </div>
                              <p className="small" style={{ margin: 0 }} title={experiment.hypothesis}>{experiment.hypothesis || "No hypothesis was recorded."}</p>
                              <dl className="facts">
                                <div className="wide"><dt className="label">Pass bar</dt><dd className="small">{formatPassBar(experiment.pass_bar)}</dd></div>
                                <div><dt className="label">Sharpe</dt><dd className="tab">{formatMetric(experiment.metrics?.sharpe, 3)}</dd></div>
                                <div><dt className="label">Return</dt><dd className="tab">{formatPercent(experiment.metrics?.return_pct, 2)}</dd></div>
                                <div><dt className="label">Worst fall</dt><dd className="tab">{formatDrawdown(experiment.metrics?.max_drawdown_pct)}</dd></div>
                              </dl>
                              <details className="disclosure">
                                <summary>Parameters and data window <ChevronDown size={14} aria-hidden="true" /></summary>
                                <div>
                                  <span className="label">Parameters</span><pre>{formatSummary(experiment.parameters_summary)}</pre>
                                  <span className="label">Data window</span><pre>{formatSummary(experiment.data_window)}</pre>
                                  <p className="note">Recorded {formatDate(experiment.created_at)} · outcome is historical, not actionable.</p>
                                </div>
                              </details>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="note" style={{ margin: 0 }}>No registered experiments in this snapshot.</p>
                      )}
                    </section>
                  );
                })}
              </div>
              {experiments.length === 0 && (
                <p className="note" data-testid="status-experiments-empty">The current catalog contains no experiment records.</p>
              )}
            </section>

            <section className="glass panel" aria-labelledby="bench-runs-title">
              <div className="panel-head">
                <div>
                  <span className="label">03 · Historical search space</span>
                  <h2 id="bench-runs-title" className="heading">Exploration runs</h2>
                  <p className="small" style={{ margin: 0 }}>Recorded parameter trials and their numbers. Filter by family or sort a column.</p>
                </div>
                <label className="field">
                  <span className="label">Family</span>
                  <select className="input" data-testid="select-family-filter" value={familyFilter} onChange={(event) => setFamilyFilter(event.target.value)}>
                    <option value="all">All families</option>
                    {families.map((family) => <option key={family} value={family}>{familyLabel(family)}</option>)}
                  </select>
                </label>
              </div>
              <span className="label" data-testid="text-visible-run-count">{visibleRuns.length} of {runs.length} runs</span>
              <div className="table-scroll bench-table" role="region" aria-label="Exploration run records" tabIndex={0}>
                {visibleRuns.length > 0 ? (
                  <table className="ng">
                    <thead>
                      <tr>
                        <th scope="col">Record</th>
                        <th scope="col">Family</th>
                        {([
                          ["sharpe", "Sharpe"],
                          ["return_pct", "Return"],
                          ["max_drawdown", "Worst fall"],
                          ["created_at", "Recorded"],
                        ] as [SortKey, string][]).map(([key, label]) => {
                          const SortIcon = sortKey === key ? sortDirection === "asc" ? ArrowUp : ArrowDown : ArrowUpDown;
                          return (
                            <th scope="col" key={key} className={key === "created_at" ? undefined : "money"}>
                              <button type="button" className="sort" data-testid={`sort-runs-${key}`} aria-label={`Sort by ${label.toLowerCase()}`} onClick={() => changeSort(key)}>
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
                          <td className="mono">
                            <button type="button" className="sort" onClick={() => setSelectedRunId(String(run.id))} aria-label={`Inspect exploration run ${run.id}`}>
                              #{run.id}
                            </button>
                          </td>
                          <td><span className="status"><GlyphIcon glyph={GROUP_GLYPH[researchGroup(run.family)]} />{familyLabel(run.family)}</span></td>
                          <td className="money">{formatMetric(run.sharpe, 3)}</td>
                          <td className="money">{formatPercent(run.return_pct, 2)}</td>
                          <td className="money">{formatDrawdown(run.max_drawdown)}</td>
                          <td className="mono note">{formatDate(run.created_at)}</td>
                          <td className="mono note">{run.source || "Not recorded"}</td>
                          <td>
                            <details className="disclosure">
                              <summary>Inspect <ChevronDown size={13} aria-hidden="true" /></summary>
                              <div>
                                <span className="label">Parameters</span><pre>{formatSummary(run.parameters_summary)}</pre>
                                <span className="label">Data window</span><pre>{formatSummary(run.data_window)}</pre>
                              </div>
                            </details>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <div className="empty" data-testid="status-runs-empty">
                    {runs.length === 0 ? "No exploration runs. The current catalog contains no exploration records." : "No runs for this family. Choose another family."}
                  </div>
                )}
              </div>
              <div className="note bench-notes">
                <span>Read-only historical records</span>
                <span>Source: {catalog.source_label || catalog.source}</span>
              </div>
            </section>

            <p className="note bench-notes">
              <span>Research records do not represent live positions or execution.</span>
              <span>Snapshot as of {formatDate(catalog.snapshot_as_of)}</span>
            </p>
          </>
        ) : null}
      </main>
    </Shell>
  );
}
