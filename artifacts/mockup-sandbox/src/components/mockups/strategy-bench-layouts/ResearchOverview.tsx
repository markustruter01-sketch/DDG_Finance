import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  BookOpen,
  Check,
  ChevronDown,
  Database,
  FlaskConical,
  LockKeyhole,
  RefreshCw,
} from "lucide-react";
import { MOCK_CATALOG } from "./_shared/BenchCatalogFixture";
import "./_group.css";
import "./BenchRecord.css";
import "./CalmEvidenceDesk.css";

type Catalog = typeof MOCK_CATALOG;
type Run = Catalog["exploration_runs"][number];
type SortKey = "sharpe" | "return_pct" | "max_drawdown" | "created_at";

function familyLabel(family: string) {
  return family.replace(/^bot(\d+)_/i, "Bot $1 · ").replace(/[_-]+/g, " ")
    .replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}

function dateLabel(value?: string) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    ...(value.includes("T") ? { hour: "2-digit", minute: "2-digit", timeZone: "UTC", timeZoneName: "short" as const } : {}),
  }).format(date);
}

function metric(value: number | null | undefined, digits = 2) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—";
}

function percent(value: number | null | undefined, digits = 1) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

function drawdown(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "−" : ""}${Math.abs(value).toFixed(1)}%`;
}

function summary(value: unknown) {
  if (value === null || value === undefined || value === "") return "Not recorded";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  try { return JSON.stringify(value, null, 2); } catch { return "Not recorded"; }
}

function passBar(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return summary(value);
  const entries = Object.entries(value as Record<string, unknown>);
  if (!entries.length) return "Not recorded";
  return entries.map(([key, threshold]) => {
    const operator = key.endsWith("_min") ? "≥" : key.endsWith("_max") ? "≤" : "=";
    return `${key.replace(/_(min|max)$/, "").replace(/_/g, " ")} ${operator} ${summary(threshold)}`;
  }).join(" · ");
}

function outcomeClass(outcome: string) {
  if (/fail|reject|negative|blocked|not.?pass/i.test(outcome)) return "is-fail";
  if (/pass|verified|accept|success|ready/i.test(outcome)) return "is-pass";
  return "is-neutral";
}

export default function ResearchOverview() {
  const experiments = MOCK_CATALOG.experiments;
  const runs = MOCK_CATALOG.exploration_runs;
  const [showSample, setShowSample] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [retryMessage, setRetryMessage] = useState("");
  const [selectedExperimentId, setSelectedExperimentId] = useState<string | number>(experiments[0].id);
  const [selectedRunId, setSelectedRunId] = useState<string | number>(runs[0].id);
  const [familyFilter, setFamilyFilter] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("created_at");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");

  useEffect(() => {
    if (!retrying) return undefined;
    const timer = window.setTimeout(() => {
      setRetrying(false);
      setRetryMessage("Read attempt finished. Catalog remains unavailable in this local preview.");
    }, 700);
    return () => window.clearTimeout(timer);
  }, [retrying]);

  useEffect(() => {
    document.body.classList.add("calm-evidence-active");
    document.documentElement.classList.add("calm-evidence-active");
    const root = document.getElementById("root");
    root?.classList.add("calm-evidence-active");
    return () => {
      document.body.classList.remove("calm-evidence-active");
      document.documentElement.classList.remove("calm-evidence-active");
      root?.classList.remove("calm-evidence-active");
    };
  }, []);

  const selectedExperiment = experiments.find((item) => String(item.id) === String(selectedExperimentId)) ?? experiments[0];
  const families = useMemo(() => [...new Set(runs.map((run) => run.family))].sort((a, b) => a.localeCompare(b)), [runs]);
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
  }, [familyFilter, sortDirection, sortKey, runs]);
  const selectedRun = runs.find((run) => String(run.id) === String(selectedRunId)) ?? null;

  function changeSort(key: SortKey) {
    if (sortKey === key) setSortDirection((current) => current === "asc" ? "desc" : "asc");
    else {
      setSortKey(key);
      setSortDirection("desc");
    }
  }

  if (!showSample) {
    return (
      <main className="bench-shell bench-catalog bench-record-page research-overview calm-evidence" data-testid="page-bench">
        <aside className="bench-rail" aria-label="Strategy Bench identity and safety status">
          <div className="bench-rail-brand">
            <div className="bench-brand-mark"><FlaskConical size={18} /></div>
            <div><span className="bench-overline">RESEARCH LEDGER</span><strong>Strategy Bench</strong></div>
          </div>
          <div className="bench-rail-rule" />
          <div className="calm-rail-context"><span className="calm-rail-index">01</span><span>Evidence<br />overview</span></div>
          <div className="bench-rail-spacer" />
          <div className="bench-rail-note"><span className="bench-status-dot" /><div><strong>READ ONLY</strong><span>NO ORDER PATHS</span></div></div>
          <div className="bench-rail-meta"><span>Execution</span><code>Separate system</code><span>Record type</span><code>Historical only</code></div>
        </aside>
        <section className="bench-content">
          <header className="bench-topbar calm-topbar">
            <div className="bench-title-group">
              <div className="bench-breadcrumb"><BookOpen size={13} /> Research / Bench <span>/</span> Ledger</div>
              <h1>Strategy Bench</h1>
            </div>
            <div className="calm-header-meta">
              <span className="bench-readonly"><Database size={13} /> Read-only research ledger</span>
              <span className="calm-safety"><LockKeyhole size={12} /> No execution controls</span>
            </div>
          </header>
          <div className="bench-ledger-body bench-record-body calm-body">
            <div className="calm-sourcebar is-unavailable" role="status" aria-live="polite">
              <div className="calm-source-status">
                <AlertCircle size={16} />
                <div>
                  <strong>Catalog unavailable</strong>
                  <span>{retrying ? "Retrying catalog read locally…" : retryMessage || "Research records could not be read. No research action was submitted."}</span>
                </div>
              </div>
              <div className="calm-source-actions">
                <button type="button" className="calm-retry" onClick={() => { setRetryMessage(""); setRetrying(true); }} disabled={retrying}>
                  <RefreshCw size={13} className={retrying ? "is-spinning" : ""} /> {retrying ? "Checking…" : "Retry read"}
                </button>
                <button type="button" className="calm-preview-toggle" onClick={() => setShowSample(true)}>Preview local sample</button>
              </div>
            </div>
            <section className="calm-unavailable-layout" aria-label="Unavailable research catalog">
              <div className="calm-error-record" role="alert">
                <div className="calm-error-mark"><AlertCircle size={18} /></div>
                <div className="calm-error-copy">
                  <span className="calm-eyebrow">RESEARCH CATALOG · STATUS</span>
                  <h2>{retrying ? "Checking the catalog…" : "Historical records are unavailable"}</h2>
                  <p>{retrying
                    ? "This preview is simulating a read attempt. No request is being sent."
                    : "The catalog could not be read. No research action was submitted, and no order path is available here."}</p>
                  <div className="calm-error-reference"><span>Catalog source</span><code>Research catalog · read-only GET</code></div>
                  <div className="calm-error-reference"><span>Execution boundary</span><code>Separate system · no order path</code></div>
                </div>
                <div className="calm-error-action">
                  <span>To inspect the layout with records</span>
                  <button type="button" className="calm-preview-toggle" onClick={() => setShowSample(true)}>Open static sample preview</button>
                </div>
              </div>
              <aside className="calm-unavailable-note">
                <span className="calm-eyebrow">READING GUIDE</span>
                <strong>One ledger. Two record types.</strong>
                <p>Registered hypotheses preserve the declared test and pass bar. Exploration runs preserve individual historical trials.</p>
                <div className="calm-guide-line"><i />Hypotheses and recorded outcomes</div>
                <div className="calm-guide-line"><i />Run-level metrics and provenance</div>
                <div className="calm-guide-line"><i />Nothing here starts a backtest or places an order</div>
              </aside>
            </section>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="bench-shell bench-catalog bench-record-page research-overview calm-evidence" data-testid="page-bench">
      <aside className="bench-rail" aria-label="Strategy Bench identity and safety status">
        <div className="bench-rail-brand">
          <div className="bench-brand-mark"><FlaskConical size={18} /></div>
          <div><span className="bench-overline">RESEARCH LEDGER</span><strong>Strategy Bench</strong></div>
        </div>
        <div className="bench-rail-rule" />
        <div className="calm-rail-context"><span className="calm-rail-index">01</span><span>Evidence<br />overview</span></div>
        <div className="bench-rail-spacer" />
        <div className="bench-rail-note"><span className="bench-status-dot" /><div><strong>READ ONLY</strong><span>NO ORDER PATHS</span></div></div>
        <div className="bench-rail-meta"><span>Execution</span><code>Separate system</code><span>Record type</span><code>Historical only</code></div>
      </aside>

      <section className="bench-content">
        <header className="bench-topbar calm-topbar">
          <div className="bench-title-group">
            <div className="bench-breadcrumb"><BookOpen size={13} /> Research / Bench <span>/</span> Ledger</div>
            <h1>Strategy Bench</h1>
          </div>
          <div className="calm-header-meta">
            <span className="bench-readonly"><Database size={13} /> Read-only research ledger</span>
            <span className="calm-safety"><LockKeyhole size={12} /> No execution controls</span>
          </div>
        </header>

        <div className="bench-ledger-body bench-record-body calm-body">
          <div className={`calm-sourcebar${showSample ? " is-sample" : " is-unavailable"}`} role="status" aria-live="polite">
            <div className="calm-source-status">
              {showSample ? <Check size={16} /> : <AlertCircle size={16} />}
              <div>
                <strong>{showSample ? "Local sample preview" : "Catalog unavailable"}</strong>
                <span>{showSample
                  ? "Static fixture · sample records only · not live data"
                  : retrying ? "Retrying catalog read locally…" : retryMessage || "Research records could not be read. No research action was submitted."}</span>
              </div>
            </div>
            <div className="calm-source-actions">
              {!showSample && (
                <button type="button" className="calm-retry" onClick={() => { setRetryMessage(""); setRetrying(true); }} disabled={retrying}>
                  <RefreshCw size={13} className={retrying ? "is-spinning" : ""} /> {retrying ? "Checking…" : "Retry read"}
                </button>
              )}
              <button type="button" className="calm-preview-toggle" aria-pressed={showSample} onClick={() => {
                setShowSample((active) => !active);
                setRetryMessage("");
              }}>
                {showSample ? "Return to unavailable state" : "Preview local sample"}
              </button>
            </div>
          </div>

          {showSample ? (
            <>
              <section className="calm-ledger-intro" aria-label="Static sample catalog summary">
                <div>
                  <span className="calm-eyebrow">RECORD SET · VERSION {MOCK_CATALOG.schema_version}</span>
                  <h2>Two hypotheses. Three historical trials.</h2>
                  <p>Evidence for inspection, not a launch surface. Recorded outcomes do not imply future performance.</p>
                </div>
                <div className="calm-intro-stats">
                  <div><strong>{experiments.length}</strong><span>Hypotheses</span></div>
                  <div><strong>{experiments.filter((item) => item.outcome === "PASS").length}</strong><span>Pass</span></div>
                  <div><strong>{runs.length}</strong><span>Exploration runs</span></div>
                </div>
              </section>

              <div className="calm-workspace">
                <section className="calm-hypothesis-index" aria-labelledby="calm-hypothesis-heading">
                  <div className="calm-panel-heading">
                    <div><span className="calm-eyebrow">01 · REGISTERED HYPOTHESES</span><h2 id="calm-hypothesis-heading">Evidence index</h2></div>
                    <span className="calm-count">{experiments.length} records</span>
                  </div>
                  <div className="calm-hypothesis-list" role="list" aria-label="Select a hypothesis">
                    {experiments.map((item) => {
                      const active = String(selectedExperiment.id) === String(item.id);
                      return (
                        <button type="button" role="listitem" key={item.id} className={`calm-hypothesis-choice${active ? " is-active" : ""}`}
                          aria-pressed={active} onClick={() => setSelectedExperimentId(item.id)}>
                          <span className="calm-record-number">RECORD {item.id}</span>
                          <span className="calm-choice-title">{familyLabel(item.family)}</span>
                          <span className={`calm-verdict ${outcomeClass(item.outcome)}`}>{item.outcome}</span>
                        </button>
                      );
                    })}
                  </div>
                  <div className="calm-index-foot"><Database size={12} /> Helium research database · read-only export</div>
                </section>

                <article className="calm-primary-record" aria-labelledby="calm-primary-heading">
                  <header className="calm-record-heading">
                    <div><span className="calm-eyebrow">PRIMARY RECORD · {selectedExperiment.id}</span><h2 id="calm-primary-heading">{familyLabel(selectedExperiment.family)}</h2></div>
                    <span className={`calm-verdict ${outcomeClass(selectedExperiment.outcome)}`}>{selectedExperiment.outcome}</span>
                  </header>
                  <div className="calm-record-content">
                    <section className="calm-hypothesis-copy">
                      <span className="calm-field-label">Hypothesis</span>
                      <p>{selectedExperiment.hypothesis}</p>
                    </section>
                    <div className="calm-evidence-grid">
                      <section className="calm-passbar"><span className="calm-field-label">Declared pass bar</span><strong>{passBar(selectedExperiment.pass_bar)}</strong></section>
                      <section className="calm-metrics" aria-label="Recorded outcome metrics">
                        <span className="calm-field-label">Recorded result</span>
                        <div>
                          <span><b>{metric(selectedExperiment.metrics.sharpe, 3)}</b><small>Sharpe</small></span>
                          <span><b>{percent(selectedExperiment.metrics.return_pct, 2)}</b><small>Return</small></span>
                          <span><b>{drawdown(selectedExperiment.metrics.max_drawdown_pct)}</b><small>Max drawdown</small></span>
                        </div>
                      </section>
                    </div>
                    <details className="calm-details">
                      <summary>Parameters and data window <ChevronDown size={14} /></summary>
                      <div className="calm-detail-columns">
                        <section><span>Parameters</span><pre>{summary(selectedExperiment.parameters_summary)}</pre></section>
                        <section><span>Data window</span><pre>{summary(selectedExperiment.data_window)}</pre></section>
                      </div>
                    </details>
                    <div className="calm-record-foot"><span>Recorded {dateLabel(selectedExperiment.created_at)}</span><span>Historical outcome · not actionable</span></div>
                  </div>
                </article>

                <section className="calm-run-ledger" aria-labelledby="calm-run-heading">
                  <div className="calm-panel-heading calm-run-heading">
                    <div><span className="calm-eyebrow">02 · HISTORICAL SEARCH SPACE</span><h2 id="calm-run-heading">Exploration runs</h2></div>
                    <label className="calm-family-filter"><span>Family</span>
                      <select aria-label="Filter exploration runs by family" value={familyFilter} onChange={(event) => setFamilyFilter(event.target.value)}>
                        <option value="all">All families</option>
                        {families.map((family) => <option value={family} key={family}>{familyLabel(family)}</option>)}
                      </select>
                    </label>
                  </div>
                  <div className="calm-sortbar" role="group" aria-label="Sort exploration runs">
                    <span>{visibleRuns.length} of {runs.length} records</span>
                    {([
                      ["created_at", "Date"], ["sharpe", "Sharpe"], ["return_pct", "Return"], ["max_drawdown", "Drawdown"],
                    ] as [SortKey, string][]).map(([key, label]) => {
                      const Icon = sortKey === key ? sortDirection === "asc" ? ArrowUp : ArrowDown : ArrowUpDown;
                      return <button type="button" key={key} className={sortKey === key ? "is-active" : ""}
                        aria-label={`Sort by ${label}`} aria-pressed={sortKey === key} onClick={() => changeSort(key)}>{label}<Icon size={11} /></button>;
                    })}
                  </div>
                  <div className="calm-run-list" role="list" aria-label="Historical exploration run records" tabIndex={0}>
                    {visibleRuns.length ? visibleRuns.map((run) => {
                      const active = String(run.id) === String(selectedRunId);
                      return (
                        <button type="button" role="listitem" key={run.id} className={`calm-run-row${active ? " is-selected" : ""}`}
                          aria-pressed={active} onClick={() => setSelectedRunId(run.id)}>
                          <span className="calm-run-row-top"><b>#{run.id}</b><time dateTime={run.created_at}>{dateLabel(run.created_at)}</time></span>
                          <span className="calm-run-family">{familyLabel(run.family)}</span>
                          <span className="calm-run-values"><span>Sharpe <b>{metric(run.sharpe, 3)}</b></span><span>Return <b>{percent(run.return_pct, 2)}</b></span></span>
                        </button>
                      );
                    }) : <div className="calm-run-empty">No runs match this family.</div>}
                  </div>
                  <div className="calm-run-detail" aria-live="polite">
                    {selectedRun ? (
                      <>
                        <span className="calm-field-label">Selected run · #{selectedRun.id}</span>
                        <strong>{familyLabel(selectedRun.family)}</strong>
                        <dl><div><dt>Max drawdown</dt><dd>{drawdown(selectedRun.max_drawdown)}</dd></div><div><dt>Source</dt><dd>{selectedRun.source}</dd></div></dl>
                        <details className="calm-details calm-run-details">
                          <summary>Parameters and window <ChevronDown size={13} /></summary>
                          <div className="calm-detail-columns">
                            <section><span>Parameters</span><pre>{summary(selectedRun.parameters_summary)}</pre></section>
                            <section><span>Data window</span><pre>{summary(selectedRun.data_window)}</pre></section>
                          </div>
                        </details>
                      </>
                    ) : <p>Select a run to inspect its recorded metrics.</p>}
                  </div>
                </section>
              </div>
              <footer className="calm-footer">
                <span><LockKeyhole size={12} /> Read-only research ledger · no order paths</span>
                <span>Static sample records · {MOCK_CATALOG.row_counts.experiments} hypotheses · {MOCK_CATALOG.row_counts.exploration_runs} runs</span>
              </footer>
            </>
          ) : (
            <section className="calm-unavailable-layout" aria-label="Unavailable research catalog">
              <div className="calm-error-record" role="alert">
                <div className="calm-error-mark"><AlertCircle size={18} /></div>
                <div className="calm-error-copy">
                  <span className="calm-eyebrow">RESEARCH CATALOG · STATUS</span>
                  <h2>{retrying ? "Checking the catalog…" : "Historical records are unavailable"}</h2>
                  <p>{retrying
                    ? "This preview is simulating a read attempt. No request is being sent."
                    : "The catalog could not be read. No research action was submitted, and no order path is available here."}</p>
                  <div className="calm-error-reference"><span>Catalog source</span><code>Research catalog · read-only GET</code></div>
                  <div className="calm-error-reference"><span>Execution boundary</span><code>Separate system · no order path</code></div>
                </div>
                <div className="calm-error-action">
                  <span>To inspect the layout with records</span>
                  <button type="button" className="calm-preview-toggle" onClick={() => setShowSample(true)}>Open static sample preview</button>
                </div>
              </div>
              <aside className="calm-unavailable-note">
                <span className="calm-eyebrow">READING GUIDE</span>
                <strong>One ledger. Two record types.</strong>
                <p>Registered hypotheses preserve the declared test and pass bar. Exploration runs preserve individual historical trials.</p>
                <div className="calm-guide-line"><i />Hypotheses and recorded outcomes</div>
                <div className="calm-guide-line"><i />Run-level metrics and provenance</div>
                <div className="calm-guide-line"><i />Nothing here starts a backtest or places an order</div>
              </aside>
            </section>
          )}
        </div>
      </section>
    </main>
  );
}
