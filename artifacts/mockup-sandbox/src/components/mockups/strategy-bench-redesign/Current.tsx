import { useEffect, useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  BarChart3,
  BookOpen,
  CalendarClock,
  Database,
  FlaskConical,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import "./_group.css";

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

type View = "experiments" | "runs";
type SortKey = "sharpe" | "return_pct" | "max_drawdown" | "created_at";

// Local catalog fixture for the sandbox; no backend or network request is used.
const CATALOG_FIXTURE: Catalog = {
  schema_version: 1,
  generated_at: "2026-10-05T00:45:45.754501Z",
  snapshot_as_of: "2026-10-05T00:45:45.754501Z",
  source: "helium_research_database_snapshot",
  source_label: "Helium research database · read-only export",
  row_counts: { experiments: 2, exploration_runs: 3 },
  experiments: [
    {
      id: 17,
      family: "bot2_momentum_fullmarket",
      hypothesis: "12-1 cross-sectional momentum, top 20 equal weight, monthly rebalance, on a full-market mechanically screened US equity universe produces positive risk-adjusted returns.",
      parameters_summary: "allocation=equal_weight; cash_model=one shared cash balance; max_deployment=1.0; momentum=12-1; rebalance=monthly first-trading-day; top_n=20; universe_size=500",
      pass_bar: { pooled_sharpe_min: 0.6, pooled_max_drawdown_max: 0.4 },
      data_window: { backtest_start: "2019-02-01", backtest_end: "2026-07-31", warmup_start: "2018-01-01" },
      metrics: { sharpe: 1.799, return_pct: 96.23, max_drawdown_pct: 18.3 },
      outcome: "PASS",
      created_at: "2026-08-29T01:59:27.614437Z",
    },
    {
      id: 19,
      family: "bot2_momentum_rank500_regime",
      hypothesis: "Adding a market regime filter to rank-500 12-1 momentum reduces the momentum-crash drawdown without destroying the return.",
      parameters_summary: "allocation=equal_weight; idle_capital=cash; market_regime=SPY prior 200-session SMA; top_n=20; universe_size=500",
      pass_bar: { sharpe_min: 0.6, max_drawdown_max: 0.4 },
      data_window: { backtest_start: "2019-02-01", backtest_end: "2026-07-31", warmup_start: "2018-01-01" },
      metrics: { sharpe: 0.887, return_pct: 209.2, max_drawdown_pct: 33.79 },
      outcome: "FAIL",
      created_at: "2026-08-29T03:45:41.438825Z",
    },
  ],
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
      parameters_summary: "allocation=equal_weight; catastrophe_stop=0.2; idle_capital=cash; max_deployment=1.0; momentum=12-1; random_control_iterations=1000; random_control_seed=2712026; rebalance=monthly first-trading-day; screening=4 fields; slippage_each_leg_bps=10.0; top_n=20; universe_rule=top 500 by trailing 60-session median dollar volume; universe_size=500",
      data_window: { backtest_start: "2019-02-01", backtest_end: "2026-07-31", warmup_start: "2018-01-01" },
      sharpe: 0.7016876886753177,
      return_pct: 3.218342604572803,
      max_drawdown: 72.01566486898376,
      source: "bench_gate",
      created_at: "2026-08-31T00:03:17.861893Z",
    },
  ],
};

function formatDate(value: string | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    ...(value.includes("T") ? { hour: "2-digit", minute: "2-digit", timeZoneName: "short" } : {}),
  }).format(date);
}

function formatMetric(value: number | null | undefined, digits = 2) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—";
}

function formatSummary(value: unknown) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return "—";
  }
}

function SummaryValue({ value }: { value: unknown }) {
  const summary = formatSummary(value);
  if (summary.length <= 150) return <span>{summary}</span>;
  return (
    <details className="bench-summary-details">
      <summary>
        <span>{summary.slice(0, 110).trimEnd()}…</span>
        <small>Expand</small>
      </summary>
      <pre>{summary}</pre>
    </details>
  );
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
  if (/fail|reject|negative|blocked|not.?pass/.test(normalized)) return "is-negative";
  if (/pass|verified|accept|success|ready/.test(normalized)) return "";
  return "is-neutral";
}

function CatalogSkeleton() {
  return (
    <main className="bench-shell bench-catalog" data-testid="status-bench-loading" aria-busy="true">
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
          <div className="bench-title-group"><div className="bench-breadcrumb"><BookOpen size={13} /> /research / bench</div><h1>Strategy Bench</h1></div>
          <span className="bench-readonly"><Database size={13} /> CATALOG</span>
        </header>
        <div className="bench-ledger-body">
          <div className="bench-ledger-panel bench-ledger-loading" data-testid="panel-bench-loading">
            <div className="bench-skeleton" aria-label="Loading research catalog">
              <div className="bench-skeleton-line" /><div className="bench-skeleton-line" /><div className="bench-skeleton-line" />
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}

export function Current() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>("experiments");
  const [familyFilter, setFamilyFilter] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("created_at");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    Promise.resolve(CATALOG_FIXTURE).then((payload) => {
      if (!controller.signal.aborted) setCatalog(payload);
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
  const families = useMemo(
    () => [...new Set(runs.map((run) => run.family))].sort((a, b) => a.localeCompare(b)),
    [runs],
  );
  const visibleRuns = useMemo(() => {
    const filtered = familyFilter === "all" ? runs : runs.filter((run) => run.family === familyFilter);
    return [...filtered].sort((a, b) => {
      const left = a[sortKey];
      const right = b[sortKey];
      if (sortKey !== "created_at" && (left == null || right == null)) {
        if (left == null && right != null) return 1;
        if (left != null && right == null) return -1;
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
      setSortDirection(key === "created_at" ? "desc" : "desc");
    }
  }

  if (loading && !catalog) return <CatalogSkeleton />;

  return (
    <main className="bench-shell bench-catalog" data-testid="page-bench">
      <aside className="bench-rail">
        <div className="bench-rail-brand">
          <div className="bench-brand-mark"><FlaskConical size={18} /></div>
          <div><span className="bench-overline">RESEARCH LEDGER</span><strong>Strategy Bench</strong></div>
        </div>
        <div className="bench-rail-rule" />
        <div className="bench-rail-spacer" />
        <div className="bench-rail-note"><span className="bench-status-dot" /><div><strong>READ ONLY</strong><span>NO ORDER PATHS</span></div></div>
        <div className="bench-rail-meta"><span>RECORD SET</span><code>{catalog ? `v${catalog.schema_version}` : "unavailable"}</code><span>LIVE EXECUTION</span><code>SEPARATE SYSTEM</code></div>
      </aside>

      <section className="bench-content">
        <header className="bench-topbar">
          <div className="bench-title-group">
            <div className="bench-breadcrumb"><BookOpen size={13} /> /research / bench <span>·</span> catalog</div>
            <h1>Strategy Bench</h1>
          </div>
          <span className="bench-readonly"><Database size={13} /> RESEARCH RECORDS</span>
        </header>

        <div className="bench-ledger-body">
          <section className="bench-ledger-context" aria-label="Research execution boundary">
            <div className="bench-ledger-context-main">
              <div className="bench-safety-mark"><LockKeyhole size={15} /></div>
              <div><strong>RESEARCH ONLY · READ-ONLY CATALOG</strong><p>Recorded experiments and exploration runs. No controls here can trigger backtests, workshops, sweeps, or live execution.</p></div>
            </div>
            <span><ShieldCheck size={12} /> EXECUTION ISOLATED</span>
          </section>

          {error ? (
            <section className="bench-ledger-panel bench-ledger-error" role="alert" data-testid="status-bench-error">
              <TriangleAlert size={24} />
              <strong>Research catalog unavailable</strong>
              <p>The catalog could not be read. No research action was submitted.</p>
              <p className="bench-error-detail" data-testid="text-bench-error-detail">{error}</p>
              <button className="bench-retry" data-testid="button-retry-bench" onClick={() => setAttempt((value) => value + 1)}>
                <RefreshCw size={13} /> Retry catalog read
              </button>
            </section>
          ) : catalog ? (
            <>
              <section className="bench-catalog-summary" aria-label="Catalog provenance and record counts">
                <div className="bench-summary-cell">
                  <span>DATA SOURCE</span><strong data-testid="text-bench-source">{catalog.source_label || catalog.source}</strong>
                  {catalog.source_detail && <small>{catalog.source_detail}</small>}
                </div>
                <div className="bench-summary-cell">
                  <span>SNAPSHOT AS OF</span><strong data-testid="text-bench-as-of">{formatDate(catalog.snapshot_as_of)}</strong>
                  <small>Generated {formatDate(catalog.generated_at)}</small>
                </div>
                <div className="bench-summary-cell">
                  <span>REGISTERED EXPERIMENTS</span><strong className="bench-summary-count" data-testid="value-experiment-count">{catalog.row_counts.experiments}</strong>
                  <small>Read-only records</small>
                </div>
                <div className="bench-summary-cell">
                  <span>EXPLORATION RUNS</span><strong className="bench-summary-count" data-testid="value-run-count">{catalog.row_counts.exploration_runs}</strong>
                  <small>Historical outcomes</small>
                </div>
              </section>

              <section className="bench-ledger-panel" aria-labelledby="bench-ledger-title">
                <div className="bench-ledger-heading">
                  <div>
                    <span className="bench-overline">CATALOG / VERSION {catalog.schema_version}</span>
                    <h2 id="bench-ledger-title">{view === "experiments" ? "Registered experiments" : "Exploration runs"}</h2>
                    <p>{view === "experiments" ? "Hypotheses, declared pass bars, and recorded outcomes." : "Observed metrics from recorded parameter explorations."}</p>
                  </div>
                  <div className="bench-view-switch" role="tablist" aria-label="Research record type">
                    <button type="button" role="tab" aria-selected={view === "experiments"} className={view === "experiments" ? "active" : ""} data-testid="tab-experiments" onClick={() => setView("experiments")}>
                      <BookOpen size={13} /> Experiments <b>{catalog.row_counts.experiments}</b>
                    </button>
                    <button type="button" role="tab" aria-selected={view === "runs"} className={view === "runs" ? "active" : ""} data-testid="tab-runs" onClick={() => setView("runs")}>
                      <BarChart3 size={13} /> Exploration <b>{catalog.row_counts.exploration_runs}</b>
                    </button>
                  </div>
                </div>

                {view === "experiments" ? (
                  <>
                    <div className="bench-table-toolbar"><span>{experiments.length} REGISTERED RECORD{experiments.length === 1 ? "" : "S"}</span><span>OUTCOME STATUS IS RECORDED, NOT ACTIONABLE</span></div>
                    {experiments.length === 0 ? (
                      <div className="bench-ledger-empty" data-testid="status-experiments-empty"><BookOpen size={22} /><strong>No registered experiments</strong><p>The current catalog contains no experiment records.</p></div>
                    ) : (
                      <div className="bench-table-wrap">
                        <table className="bench-table bench-experiments-table">
                          <thead><tr><th>RECORD</th><th>FAMILY</th><th>HYPOTHESIS</th><th>PARAMETERS</th><th>PASS BAR</th><th>SHARPE</th><th>RETURN</th><th>MAX DD</th><th>DATA WINDOW</th><th>OUTCOME</th></tr></thead>
                          <tbody>
                            {experiments.map((experiment) => (
                              <tr key={experiment.id} data-testid={`row-experiment-${experiment.id}`}>
                                <td className="cell-id">{experiment.id}<span className="bench-family-sub">{formatDate(experiment.created_at)}</span></td>
                                <td><span className="bench-family">{experiment.family}</span></td>
                                <td className="bench-wrap-cell"><SummaryValue value={experiment.hypothesis} /></td>
                                <td className="bench-wrap-cell"><SummaryValue value={experiment.parameters_summary} /></td>
                                <td className="bench-wrap-cell"><SummaryValue value={experiment.pass_bar} /></td>
                                <td className="bench-mono-cell">{formatMetric(experiment.metrics?.sharpe)}</td>
                                <td className="bench-mono-cell">{formatPercent(experiment.metrics?.return_pct)}</td>
                                <td className="bench-mono-cell">{formatDrawdown(experiment.metrics?.max_drawdown_pct)}</td>
                                <td className="bench-wrap-cell"><SummaryValue value={experiment.data_window} /></td>
                                <td><span className={`bench-outcome ${outcomeTone(experiment.outcome)}`} data-testid={`status-outcome-${experiment.id}`}>{experiment.outcome}</span></td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </>
                ) : (
                  <>
                    <div className="bench-table-toolbar">
                      <span>{visibleRuns.length} OF {runs.length} EXPLORATION RUN{runs.length === 1 ? "" : "S"}</span>
                      <label className="bench-filter"><span>FAMILY</span>
                        <select data-testid="select-family-filter" value={familyFilter} onChange={(event) => setFamilyFilter(event.target.value)}>
                          <option value="all">All families</option>
                          {families.map((family) => <option key={family} value={family}>{family}</option>)}
                        </select>
                      </label>
                    </div>
                    {runs.length === 0 || visibleRuns.length === 0 ? (
                      <div className="bench-ledger-empty" data-testid="status-runs-empty"><BarChart3 size={22} /><strong>{runs.length === 0 ? "No exploration runs" : "No runs for this family"}</strong><p>{runs.length === 0 ? "The current catalog contains no exploration records." : "Choose another family filter to view recorded runs."}</p></div>
                    ) : (
                      <div className="bench-table-wrap">
                        <table className="bench-table bench-runs-table">
                          <thead><tr>
                            <th>RECORD</th><th>FAMILY</th><th>PARAMETERS</th><th>DATA WINDOW</th>
                            {(["sharpe", "return_pct", "max_drawdown", "created_at"] as SortKey[]).map((key) => {
                              const label = key === "sharpe" ? "SHARPE" : key === "return_pct" ? "RETURN" : key === "max_drawdown" ? "MAX DD" : "CREATED";
                              const Icon = sortKey === key ? sortDirection === "asc" ? ArrowUp : ArrowDown : ArrowUpDown;
                              return <th key={key}><button className="bench-sort" type="button" data-testid={`sort-runs-${key}`} aria-label={`Sort by ${label.toLowerCase()}`} onClick={() => changeSort(key)}>{label}<Icon size={11} /></button></th>;
                            })}
                            <th>SOURCE</th>
                          </tr></thead>
                          <tbody>
                            {visibleRuns.map((run) => (
                              <tr key={run.id} data-testid={`row-run-${run.id}`}>
                                <td className="cell-id">{run.id}</td>
                                <td><span className="bench-family">{run.family}</span></td>
                                <td className="bench-wrap-cell"><SummaryValue value={run.parameters_summary} /></td>
                                <td className="bench-wrap-cell"><SummaryValue value={run.data_window} /></td>
                                <td className="bench-mono-cell">{formatMetric(run.sharpe)}</td>
                                <td className="bench-mono-cell">{formatPercent(run.return_pct)}</td>
                                <td className="bench-mono-cell">{formatDrawdown(run.max_drawdown)}</td>
                                <td className="bench-mono-cell"><span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}><CalendarClock size={11} />{formatDate(run.created_at)}</span></td>
                                <td className="bench-mono-cell">{run.source}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </>
                )}
                <footer className="bench-ledger-foot">
                  <span><strong>READ ONLY</strong> · No research jobs can be started from this page</span>
                  <span>AS OF {formatDate(catalog.snapshot_as_of)}</span>
                </footer>
              </section>
            </>
          ) : null}
        </div>
      </section>
    </main>
  );
}