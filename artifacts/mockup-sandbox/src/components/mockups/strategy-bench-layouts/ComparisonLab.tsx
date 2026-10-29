import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  BookOpen,
  CalendarClock,
  Check,
  ChevronDown,
  Database,
  FlaskConical,
  LockKeyhole,
  RefreshCw,
  X,
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
import "./ComparisonLabWorkspace.css";

type Run = (typeof MOCK_CATALOG.exploration_runs)[number];
type SortKey = "sharpe" | "return_pct" | "max_drawdown" | "created_at";
type Group = "Atlas" | "Momentum" | "Bullion" | "Forex" | "Fleet" | "Other";
type Point = Run & { drawdown: number; group: Group };
type Availability = "unavailable" | "loading" | "resolved";

const GROUPS: Group[] = ["Atlas", "Momentum", "Bullion", "Forex", "Fleet", "Other"];
const COLORS: Record<Group, string> = {
  Atlas: "#9a654f",
  Momentum: "#466b5c",
  Bullion: "#92773f",
  Forex: "#74698a",
  Fleet: "#497d77",
  Other: "#68715f",
};

function groupFor(family: string): Group {
  const value = family.toLowerCase();
  if (value.includes("atlas")) return "Atlas";
  if (value.includes("momentum")) return "Momentum";
  if (value.includes("bullion") || value.includes("gold") || value.includes("silver")) return "Bullion";
  if (/\bforex\b|\bfx\b|foreign[_ -]?exchange|currency|oanda/.test(value)) return "Forex";
  if (value.includes("fleet")) return "Fleet";
  return "Other";
}

function familyLabel(family: string) {
  return family.replace(/^bot(\d+)_/i, "Bot $1 · ").replace(/[_-]+/g, " ")
    .replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}

function formatDate(value?: string) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en", {
    year: "numeric", month: "short", day: "2-digit",
    ...(value.includes("T") ? { hour: "2-digit", minute: "2-digit", timeZone: "UTC", timeZoneName: "short" as const } : {}),
  }).format(date);
}

function metric(value: number | null | undefined, digits = 2) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—";
}

function percent(value: number | null | undefined) {
  return typeof value === "number" && Number.isFinite(value)
    ? `${value > 0 ? "+" : ""}${value.toFixed(2)}%`
    : "—";
}

function drawdown(value: number | null | undefined) {
  return typeof value === "number" && Number.isFinite(value) ? `−${Math.abs(value).toFixed(1)}%` : "—";
}

function summary(value: unknown) {
  if (value === null || value === undefined || value === "") return "Not recorded";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  try { return JSON.stringify(value, null, 2); } catch { return "Not recorded"; }
}

function ChartTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload?: Point }> }) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  return (
    <div className="bench-record-tooltip" role="status">
      <strong>{familyLabel(point.family)}</strong>
      <span>Run {point.id} · {point.group}</span>
      <dl>
        <div><dt>Sharpe</dt><dd>{metric(point.sharpe, 3)}</dd></div>
        <div><dt>Maximum drawdown</dt><dd>{drawdown(point.max_drawdown)}</dd></div>
        <div><dt>Return</dt><dd>{percent(point.return_pct)}</dd></div>
      </dl>
      <small>{point.source} · {formatDate(point.created_at)}</small>
    </div>
  );
}

export default function ComparisonLab() {
  const [preview, setPreview] = useState(false);
  const [availability, setAvailability] = useState<Availability>("unavailable");
  const [retryCount, setRetryCount] = useState(0);
  const [family, setFamily] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("created_at");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  const runs = preview ? MOCK_CATALOG.exploration_runs : [];
  const families = useMemo(() => [...new Set(runs.map((run) => run.family))].sort((a, b) => a.localeCompare(b)), [runs]);
  const points = useMemo<Point[]>(() => runs.flatMap((run) => (
    typeof run.sharpe === "number" && Number.isFinite(run.sharpe)
      && typeof run.max_drawdown === "number" && Number.isFinite(run.max_drawdown)
      ? [{ ...run, drawdown: Math.abs(run.max_drawdown), group: groupFor(run.family) }]
      : []
  )), [runs]);
  const visibleRuns = useMemo(() => {
    const filtered = family === "all" ? runs : runs.filter((run) => run.family === family);
    return [...filtered].sort((a, b) => {
      const left = a[sortKey];
      const right = b[sortKey];
      if (sortKey === "created_at") {
        return (new Date(String(left)).getTime() - new Date(String(right)).getTime()) * (sortDirection === "asc" ? 1 : -1);
      }
      const leftNumber = typeof left === "number" && Number.isFinite(left) ? left : null;
      const rightNumber = typeof right === "number" && Number.isFinite(right) ? right : null;
      if (leftNumber === null) return rightNumber === null ? 0 : 1;
      if (rightNumber === null) return -1;
      return (leftNumber - rightNumber) * (sortDirection === "asc" ? 1 : -1);
    });
  }, [family, runs, sortDirection, sortKey]);
  const selectedRun = runs.find((run) => String(run.id) === selectedId) ?? runs[0] ?? null;
  const plotted = points.filter((point) => family === "all" || point.family === family);
  const chartGroups = GROUPS.map((group) => ({ group, data: plotted.filter((point) => point.group === group) }))
    .filter(({ data }) => data.length > 0);

  function changeSort(key: SortKey) {
    if (sortKey === key) setSortDirection((direction) => direction === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDirection("desc"); }
  }

  function retryLocal() {
    if (availability === "loading") return;
    setAvailability("loading");
    setRetryCount((count) => count + 1);
    window.setTimeout(() => setAvailability("unavailable"), 850);
  }

  function selectRun(run: Run, inspect = false) {
    setSelectedId(String(run.id));
    setDetailOpen(inspect);
  }

  const renderPoint = (raw: unknown) => {
    const props = raw as { cx?: number; cy?: number; fill?: string; payload?: Point };
    const point = props.payload;
    if (typeof props.cx !== "number" || typeof props.cy !== "number" || !point) return <g />;
    const choose = () => selectRun(point);
    return (
      <g
        className="cl-plot-point"
        role="button"
        tabIndex={0}
        aria-label={`Inspect historical run ${point.id}, ${familyLabel(point.family)}, Sharpe ${metric(point.sharpe, 3)}, maximum drawdown ${drawdown(point.max_drawdown)}`}
        aria-pressed={selectedRun?.id === point.id}
        onClick={(event) => { event.stopPropagation(); choose(); }}
        onFocus={choose}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") { event.preventDefault(); choose(); }
        }}
      >
        <circle cx={props.cx} cy={props.cy} r={13} fill="transparent" />
        <circle cx={props.cx} cy={props.cy} r={5.5} fill={props.fill ?? COLORS[point.group]} stroke="#f8f8ef" strokeWidth={2} />
      </g>
    );
  };

  return (
    <main className="bench-shell bench-catalog bench-record-page comparison-lab" data-testid="page-bench-comparison">
      <aside className="bench-rail">
        <div className="bench-rail-brand">
          <div className="bench-brand-mark"><FlaskConical size={18} /></div>
          <div><span className="bench-overline">RESEARCH LEDGER</span><strong>Strategy Bench</strong></div>
        </div>
        <div className="bench-rail-rule" />
        <div className="bench-rail-spacer" />
        <div className="bench-rail-note"><span className="bench-status-dot" /><div><strong>READ ONLY</strong><span>NO ORDER PATHS</span></div></div>
        <div className="bench-rail-meta"><span>Record set</span><code>{preview ? `Version ${MOCK_CATALOG.schema_version}` : "Unavailable"}</code><span>Execution</span><code>Separate system</code></div>
      </aside>

      <section className="bench-content">
        <header className="bench-topbar">
          <div className="cl-masthead-brand">
            <div className="bench-brand-mark" aria-hidden="true"><FlaskConical size={16} /></div>
            <div className="cl-title-copy">
              <div className="bench-breadcrumb"><BookOpen size={12} /> Research / Bench</div>
              <h1>Strategy Bench</h1>
            </div>
          </div>
          <div className="cl-head-actions">
            <span className="bench-readonly"><Database size={13} /> Read-only catalog</span>
            <span className="cl-static-indicator"><i /> Static sample fixture</span>
          </div>
        </header>

        <div className="bench-ledger-body bench-record-body cl-body">
          <section className="cl-workspace-heading" aria-labelledby="cl-workspace-title">
            <div className="cl-heading-copy">
              <span className="cl-kicker"><BookOpen size={12} /> Comparison workspace · Historical ledger</span>
              <h2 id="cl-workspace-title">Recorded runs, side by side.</h2>
            </div>
            <div className="cl-heading-tools">
              <span className={`cl-mode-pill${preview ? "" : " is-unavailable"}`} role="status">
                <i />{preview ? "Sample preview" : availability === "loading" ? "Checking catalog" : "Catalog unavailable"}
              </span>
              <button
                type="button"
                className={`cl-preview-toggle${preview ? " is-active" : ""}`}
                aria-pressed={preview}
                onClick={() => { setPreview((value) => !value); setSelectedId(null); setDetailOpen(false); }}
              >
                {preview ? <Check size={13} /> : <Database size={13} />}
                {preview ? "Exit sample preview" : "Preview sample records"}
              </button>
            </div>
          </section>

          {!preview ? (
            <section className={`cl-unavailable-screen${availability === "loading" ? " is-loading" : ""}`} role={availability === "loading" ? "status" : "alert"} aria-live="polite">
              <div className="cl-unavailable-rule"><span>Catalog status</span><i /></div>
              <div className="cl-unavailable-content">
                <div className="cl-status-icon">{availability === "loading" ? <RefreshCw className="is-spinning" size={19} /> : <AlertTriangle size={19} />}</div>
                <span className="cl-section-tag">Historical record access</span>
                <h3>{availability === "loading" ? "Checking catalog availability" : "Research catalog is unavailable"}</h3>
                <p>
                  {availability === "loading"
                    ? "Local status check in progress. No request is being sent."
                    : "No catalog read completed. Historical research is unchanged; no research action or order was submitted."}
                </p>
                <div className="cl-unavailable-provenance">
                  <span>Expected source</span>
                  <code>helium_research_database_snapshot</code>
                  <span>Recovery</span>
                  <b>Retry the local status check, or inspect the clearly labeled sample fixture.</b>
                </div>
                <div className="cl-unavailable-actions">
                  <button type="button" className="cl-retry-button" onClick={retryLocal} disabled={availability === "loading"}>
                    <RefreshCw className={availability === "loading" ? "is-spinning" : ""} size={13} />
                    {availability === "loading" ? "Checking…" : "Retry catalog"}
                  </button>
                  <span className="cl-retry-note">
                    {availability === "loading" ? "Please wait…" : retryCount ? `Local retry ${retryCount} · last result unavailable` : "Read only · retry stays local"}
                  </span>
                </div>
              </div>
              <div className="cl-unavailable-bottom">
                <span><LockKeyhole size={11} /> No execution controls · no order paths</span>
                <span>Preview data is static and not live</span>
              </div>
            </section>
          ) : (
          <section className="cl-main-grid" aria-label="Historical run comparison">
            <section className="cl-chart-card" aria-labelledby="cl-chart-title">
              <header className="cl-card-heading">
                <div>
                  <span className="cl-section-tag">01 · Risk / return map</span>
                  <h3 id="cl-chart-title">Sharpe vs maximum drawdown</h3>
                  <p>One point per run with both recorded chart metrics.</p>
                </div>
                <span className="cl-chart-count">{plotted.length} / {runs.length} plotted</span>
              </header>
              <div className="cl-chart-main">
                <div className="cl-plot-column">
                  {plotted.length ? (
                    <>
                      <div className="cl-plot" role="group" aria-label="Sharpe ratio against maximum drawdown; select a point to inspect its recorded run.">
                        <ResponsiveContainer width="100%" height="100%">
                          <ScatterChart margin={{ top: 14, right: 15, bottom: 22, left: 2 }}>
                            <CartesianGrid stroke="rgba(55,78,69,.17)" vertical strokeDasharray="3 5" />
                            <XAxis type="number" dataKey="sharpe" name="Sharpe" tick={{ fill: "#65766c", fontSize: 9 }} tickLine={false} axisLine={{ stroke: "rgba(53,75,66,.4)" }} tickFormatter={(value: number) => Number(value).toFixed(1)} />
                            <YAxis type="number" dataKey="drawdown" name="Maximum drawdown" reversed domain={[0, "auto"]} width={45} tick={{ fill: "#65766c", fontSize: 9 }} tickLine={false} axisLine={false} tickFormatter={(value: number) => `−${Math.abs(value).toFixed(0)}%`} />
                            <Tooltip content={<ChartTooltip />} cursor={{ stroke: "rgba(50,83,66,.4)", strokeDasharray: "3 4" }} />
                            {chartGroups.map(({ group, data }) => <Scatter key={group} name={group} data={data} fill={COLORS[group]} shape={renderPoint} isAnimationActive={false} />)}
                          </ScatterChart>
                        </ResponsiveContainer>
                      </div>
                      <div className="cl-legend" aria-label="Research family chart key">
                        {chartGroups.map(({ group }) => <span key={group}><i style={{ background: COLORS[group] }} />{group}</span>)}
                      </div>
                    </>
                  ) : (
                    <div className="cl-no-chart">
                      <Database size={19} />
                      <strong>{preview ? "No plotted records" : "Comparison plot is waiting"}</strong>
                      <span>{preview ? "The local fixture has no runs with both Sharpe and maximum drawdown values." : "The catalog has not supplied a readable record set. Use the sample preview to inspect the comparison workspace."}</span>
                    </div>
                  )}
                </div>
                <aside className="cl-selected-panel" aria-live="polite" aria-label="Selected exploration run">
                  {selectedRun ? (
                    <>
                      <span className="cl-selected-label">Selected historical record</span>
                      <h4>{familyLabel(selectedRun.family)}</h4>
                      <span className="cl-selected-id">Run {selectedRun.id} · {selectedRun.source || "Not recorded"}</span>
                      <dl>
                        <div><dt>Sharpe</dt><dd>{metric(selectedRun.sharpe, 3)}</dd></div>
                        <div><dt>Max drawdown</dt><dd>{drawdown(selectedRun.max_drawdown)}</dd></div>
                        <div><dt>Return</dt><dd>{percent(selectedRun.return_pct)}</dd></div>
                      </dl>
                      <time>{formatDate(selectedRun.created_at)}</time>
                    </>
                  ) : <p className="cl-selected-empty">Select a plotted point or run record to view its historical metrics.</p>}
                </aside>
              </div>
              <footer className="cl-chart-foot">
                <span>{runs.length - points.length} {runs.length - points.length === 1 ? "run is" : "runs are"} missing one or both chart metrics.</span>
                <span>{preview ? "Static sample records · not live data" : "No catalog data loaded · no live data implied"}</span>
              </footer>
            </section>

            <section className="cl-record-card" aria-labelledby="cl-records-title">
              <header className="cl-card-heading">
                <div><span className="cl-section-tag">02 · Inspection ledger</span><h3 id="cl-records-title">Exploration runs</h3></div>
                <span className="cl-chart-count">READ ONLY</span>
              </header>
              <div className="cl-record-toolbar">
                <div className="cl-filter-line">
                  <label htmlFor="cl-family-filter">Research family</label>
                  <select id="cl-family-filter" className="cl-family-select" value={family} onChange={(event) => setFamily(event.target.value)} disabled={!preview}>
                    <option value="all">All families</option>
                    {families.map((item) => <option key={item} value={item}>{familyLabel(item)}</option>)}
                  </select>
                </div>
                <div className="cl-view-tools" role="group" aria-label="Sort historical runs">
                  <span>Sort</span>
                  {([
                    ["sharpe", "Sharpe"], ["return_pct", "Return"], ["max_drawdown", "Drawdown"], ["created_at", "Date"],
                  ] as [SortKey, string][]).map(([key, label]) => {
                    const SortIcon = sortKey === key ? sortDirection === "asc" ? ArrowUp : ArrowDown : ArrowUpDown;
                    return (
                      <button type="button" className={`cl-sort-button${sortKey === key ? " is-active" : ""}`} key={key}
                        aria-label={`Sort by ${label.toLowerCase()}`} aria-pressed={sortKey === key} disabled={!preview}
                        onClick={() => changeSort(key)}>
                        {label}<SortIcon size={10} aria-hidden="true" />
                      </button>
                    );
                  })}
                </div>
              </div>
              <div className="cl-run-count">{preview ? `${visibleRuns.length} of ${runs.length} historical runs · select to inspect` : "No records loaded · sample preview is local"}</div>
              <div className="cl-run-list" role="region" aria-label="Historical exploration run records" tabIndex={0}>
                {visibleRuns.length ? visibleRuns.map((run) => {
                  const selected = selectedRun?.id === run.id;
                  return (
                    <article className={`cl-run-row${selected ? " is-selected" : ""}`} key={run.id}>
                      <button className="cl-run-select" type="button" onClick={() => selectRun(run)}
                        aria-pressed={selected} aria-label={`Select historical run ${run.id}, ${familyLabel(run.family)}`}>
                        <span className="cl-row-main">
                          <span className="cl-row-id"><i style={{ background: COLORS[groupFor(run.family)] }} /><b>#{run.id}</b><span>{familyLabel(run.family)}</span></span>
                          <time className="cl-row-date" dateTime={run.created_at}><CalendarClock size={10} /> {formatDate(run.created_at)}</time>
                        </span>
                        <span className="cl-row-metrics">
                          <span>Sharpe<b>{metric(run.sharpe, 3)}</b></span>
                          <span>Return<b>{percent(run.return_pct)}</b></span>
                          <span>Max DD<b>{drawdown(run.max_drawdown)}</b></span>
                        </span>
                        <span className="cl-row-bottom"><span>Source · {run.source || "Not recorded"}</span><span>{selected ? "Selected" : "View record"}</span></span>
                      </button>
                      <details className="cl-run-details">
                        <summary className="cl-run-summary"><span>Parameters &amp; data window</span><ChevronDown size={12} /></summary>
                        <div>
                          <section><span>Parameters</span><pre>{summary(run.parameters_summary)}</pre></section>
                          <section><span>Data window</span><pre>{summary(run.data_window)}</pre></section>
                          <button type="button" onClick={() => selectRun(run, true)}>Open record context</button>
                        </div>
                      </details>
                    </article>
                  );
                }) : (
                  <div className="cl-run-empty">
                    {preview ? <><strong>{runs.length ? "No runs match this family" : "No exploration runs recorded"}</strong><span>Choose another family or inspect the catalog source.</span></> : <><strong>Catalog unavailable</strong><span>Try the local sample preview to inspect recorded values.</span></>}
                  </div>
                )}
              </div>
            </section>
          </section>
          )}

          {preview && <footer className="cl-workspace-foot">
            <span><LockKeyhole size={11} /> Read-only historical research · no execution or order paths</span>
            <span className="cl-static-foot"><Database size={11} /> {preview ? `Static sample fixture · ${MOCK_CATALOG.row_counts.exploration_runs} runs · as of ${formatDate(MOCK_CATALOG.snapshot_as_of)}` : "Catalog snapshot unavailable · sample fixture remains separate"}</span>
          </footer>}
        </div>
      </section>

      {detailOpen && selectedRun && (
        <aside className="cl-detail-drawer" role="dialog" aria-modal="false" aria-labelledby="cl-detail-heading">
          <div className="cl-detail-title">
            <div><span className="cl-section-tag">Recorded run · {selectedRun.id}</span><h3 id="cl-detail-heading">{familyLabel(selectedRun.family)}</h3></div>
            <button type="button" aria-label="Close record context" onClick={() => setDetailOpen(false)}><X size={15} /></button>
          </div>
          <p className="cl-detail-meta">{selectedRun.source} · Recorded {formatDate(selectedRun.created_at)}</p>
          <div className="cl-detail-metrics">
            <span>Sharpe<b>{metric(selectedRun.sharpe, 3)}</b></span>
            <span>Return<b>{percent(selectedRun.return_pct)}</b></span>
            <span>Max drawdown<b>{drawdown(selectedRun.max_drawdown)}</b></span>
          </div>
          <div className="cl-detail-sections">
            <section><span>Parameters</span><pre>{summary(selectedRun.parameters_summary)}</pre></section>
            <section><span>Data window</span><pre>{summary(selectedRun.data_window)}</pre></section>
          </div>
        </aside>
      )}
    </main>
  );
}
