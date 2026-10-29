import { useMemo, useState } from "react";
import {
  AlertTriangle, Archive, ArrowDown, ArrowUp, ArrowUpDown, BookOpen, ChevronRight,
  Database, FlaskConical, LockKeyhole, RefreshCw, Search, ShieldCheck,
} from "lucide-react";
import { MOCK_CATALOG } from "./_shared/BenchCatalogFixture";
import "./_group.css";
import "./StrategyCatalog.css";

type Run = (typeof MOCK_CATALOG.exploration_runs)[number];
type SortKey = "sharpe" | "return_pct" | "max_drawdown" | "created_at";
const color = "#456b5b";

function familyName(value: string) {
  return value.replace(/^bot(\d+)_/i, "Bot $1 · ").replace(/[_-]+/g, " ").replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}
function date(value: string) {
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : new Intl.DateTimeFormat("en", { year: "numeric", month: "short", day: "2-digit", ...(value.includes("T") ? { hour: "2-digit", minute: "2-digit", timeZone: "UTC", timeZoneName: "short" as const } : {}) }).format(d);
}
function metric(value: number | null | undefined, digits = 2) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—";
}
function percent(value: number | null | undefined) {
  return typeof value === "number" && Number.isFinite(value) ? `${value > 0 ? "+" : ""}${value.toFixed(2)}%` : "—";
}
function drawdown(value: number | null | undefined) {
  return typeof value === "number" && Number.isFinite(value) ? `−${Math.abs(value).toFixed(1)}%` : "—";
}
function summary(value: unknown) {
  if (value === null || value === undefined || value === "") return "Not recorded";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  try { return JSON.stringify(value, null, 2); } catch { return "Not recorded"; }
}

export default function StrategyCatalog() {
  const [preview, setPreview] = useState(false);
  const [retryState, setRetryState] = useState<"idle" | "loading" | "unavailable">("idle");
  const [familyFilter, setFamilyFilter] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("created_at");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const runs = MOCK_CATALOG.exploration_runs as Run[];
  const families = useMemo(() => [...new Set(runs.map((run) => run.family))].sort(), [runs]);
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return runs.filter((run) => (familyFilter === "all" || run.family === familyFilter)
      && (!needle || `${run.id} ${run.family} ${run.source} ${summary(run.parameters_summary)}`.toLowerCase().includes(needle)))
      .sort((a, b) => {
        const left = a[sortKey], right = b[sortKey];
        const diff = sortKey === "created_at" ? new Date(String(left)).getTime() - new Date(String(right)).getTime() : Number(left) - Number(right);
        return diff * (sortDirection === "asc" ? 1 : -1);
      });
  }, [familyFilter, query, runs, sortDirection, sortKey]);
  const selected = runs.find((run) => String(run.id) === selectedId) ?? null;
  function sort(key: SortKey) {
    if (sortKey === key) setSortDirection((direction) => direction === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDirection("desc"); }
  }
  function retry() {
    setRetryState("loading");
    window.setTimeout(() => setRetryState("unavailable"), 700);
  }

  return (
    <main className="bench-shell bench-catalog bench-record-page strategy-catalog-page" data-testid="page-bench-catalog">
      <aside className="bench-rail">
        <div className="bench-rail-brand"><div className="bench-brand-mark"><FlaskConical size={18} /></div><div><span className="bench-overline">RESEARCH LEDGER</span><strong>Strategy Bench</strong></div></div>
        <div className="bench-rail-rule" />
        <div className="archive-rail-nav" aria-label="Archive contents">
          <span className="archive-nav-label">COLLECTION</span>
          <div className="archive-nav-current"><Archive size={15} /><span>Historical runs</span><b>{runs.length}</b></div>
          <div className="archive-nav-note"><BookOpen size={14} /><span>Registered hypotheses</span><b>{MOCK_CATALOG.experiments.length}</b></div>
        </div>
        <div className="bench-rail-spacer" />
        <div className="bench-rail-note"><span className="bench-status-dot" /><div><strong>READ ONLY</strong><span>NO ORDER PATHS</span></div></div>
        <div className="bench-rail-meta"><span>Record set</span><code>{preview ? `Version ${MOCK_CATALOG.schema_version}` : "Unavailable"}</code><span>Execution</span><code>Separate system</code></div>
      </aside>
      <section className="bench-content">
        <header className="bench-topbar archive-topbar">
          <div className="bench-title-group"><div className="bench-breadcrumb"><BookOpen size={13} /> Research / Bench / Archive</div><h1>Strategy Bench</h1></div>
          <div className="archive-top-status"><span className="bench-readonly"><Database size={13} /> Historical research ledger</span><span className="archive-boundary"><LockKeyhole size={13} /> Read only · no order paths</span></div>
        </header>
        <div className={`archive-workspace${preview ? " is-preview" : " is-unavailable"}`}>
          {preview && <section className="archive-context">
            <div className="archive-context-mark"><Archive size={17} /></div>
            <div className="archive-context-copy"><span className="archive-kicker">CATALOG ACCESS</span><strong>Local sample snapshot</strong><p>Static sample records for layout review; not live data.</p></div>
            <span className="archive-static"><i /> STATIC / SAMPLE</span>
          </section>}
          {!preview ? (
            <section className="archive-unavailable" role="alert" data-testid="status-bench-error">
              <div className="archive-unavailable-top"><div className="archive-alert-icon"><AlertTriangle size={20} /></div><span className="archive-kicker">READ-ONLY SOURCE · GET</span><span className="archive-offline"><i />{retryState === "loading" ? "CHECKING" : "SOURCE OFFLINE"}</span></div>
              <div className="archive-alert-copy"><h2>Research records are unavailable</h2><p>{retryState === "loading" ? "Retrying local catalog check…" : retryState === "unavailable" ? "Catalog remains unavailable. The local preview is still available for layout review." : "The catalog could not be read. No research action was submitted."}</p><p className="archive-boundary-copy">This historical ledger is read-only. No research action or order was submitted.</p></div>
              <div className="archive-alert-actions"><button className="archive-retry" type="button" onClick={retry} disabled={retryState === "loading"} aria-live="polite"><RefreshCw size={14} className={retryState === "loading" ? "archive-spin" : ""} />{retryState === "loading" ? "Checking catalog…" : "Retry catalog read"}</button><button type="button" onClick={() => { setPreview(true); setSelectedId(String(runs[0]?.id ?? "")); }}>Inspect local sample <ChevronRight size={14} /></button></div>
            </section>
          ) : (
            <>
              <section className="archive-ledger-summary" aria-label="Snapshot summary">
                <div className="archive-summary-title"><span className="archive-kicker">COLLECTION INDEX</span><strong>Snapshot overview</strong><small>Version {MOCK_CATALOG.schema_version} · as of {date(MOCK_CATALOG.snapshot_as_of)}</small></div>
                <div><b>{MOCK_CATALOG.experiments.length}</b><span>Hypotheses</span></div><div><b>1</b><span>Pass</span></div><div><b>1</b><span>Fail</span></div><div><b>{runs.length}</b><span>Exploration runs</span></div>
                <div className="archive-provenance"><Database size={13} /><span>{MOCK_CATALOG.source_label}</span></div>
              </section>
              <section className="archive-browser" aria-label="Historical archive">
                <div className="archive-browser-head">
                  <div><span className="archive-kicker">01 / RECORD INDEX</span><h2>Exploration runs</h2><p>Browse historical trials by family, metric or recorded date.</p></div>
                  <div className="archive-controls">
                    <label className="archive-search"><Search size={14} /><span className="sr-only">Search archive</span><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find a record…" /></label>
                    <label className="archive-family"><span>Family</span><select aria-label="Filter runs by family" value={familyFilter} onChange={(e) => setFamilyFilter(e.target.value)}><option value="all">All families</option>{families.map((family) => <option key={family} value={family}>{familyName(family)}</option>)}</select></label>
                  </div>
                </div>
                <div className="archive-browser-body">
                  <div className="archive-list-wrap" role="region" aria-label="Historical run records" tabIndex={0}>
                    <div className="archive-list-meta"><span>{visible.length} / {runs.length} RECORDS</span><span>SELECT TO INSPECT</span></div>
                    <table className="archive-list"><thead><tr><th>RECORD</th><th>FAMILY</th>{([["sharpe","SHARPE"],["return_pct","RETURN"],["max_drawdown","DRAWDOWN"],["created_at","RECORDED"]] as [SortKey,string][]).map(([key,label]) => { const Icon = key === sortKey ? sortDirection === "asc" ? ArrowUp : ArrowDown : ArrowUpDown; return <th key={key}><button type="button" aria-label={`Sort by ${label.toLowerCase()}`} aria-sort={sortKey === key ? sortDirection === "asc" ? "ascending" : "descending" : "none"} onClick={() => sort(key)}>{label}<Icon size={11} /></button></th> })}</tr></thead>
                      <tbody>{visible.map((run) => <tr key={run.id} className={String(run.id) === selectedId ? "is-selected" : ""} onClick={() => setSelectedId(String(run.id))}>
                        <td><button className="archive-record-id" type="button" onClick={(e) => { e.stopPropagation(); setSelectedId(String(run.id)); }} aria-pressed={String(run.id) === selectedId}>#{run.id}</button></td><td><span className="archive-family-dot" style={{ background: color }} />{familyName(run.family)}</td><td>{metric(run.sharpe,3)}</td><td>{percent(run.return_pct)}</td><td>{drawdown(run.max_drawdown)}</td><td>{date(run.created_at)}</td>
                      </tr>)}</tbody></table>
                    {!visible.length && <div className="archive-empty"><strong>No records match</strong><span>Adjust the family or search term.</span></div>}
                  </div>
                  <aside className="archive-record-panel" aria-live="polite" aria-label="Selected historical record">
                    {selected ? <>
                      <div className="archive-detail-head"><span className="archive-kicker">SELECTED RECORD</span><span className="archive-detail-id">#{selected.id}</span></div>
                      <h3>{familyName(selected.family)}</h3><p className="archive-detail-date">{date(selected.created_at)}</p>
                      <div className="archive-detail-metrics"><div><span>SHARPE</span><b>{metric(selected.sharpe,3)}</b></div><div><span>RETURN</span><b>{percent(selected.return_pct)}</b></div><div><span>MAX DRAWDOWN</span><b>{drawdown(selected.max_drawdown)}</b></div></div>
                      <div className="archive-detail-source"><span>SOURCE</span><b>{selected.source}</b></div>
                      <details className="archive-detail-disclosure"><summary>Parameters and data window <ChevronRight size={13} /></summary><div><span>Parameters</span><pre>{summary(selected.parameters_summary)}</pre><span>Data window</span><pre>{summary(selected.data_window)}</pre></div></details>
                      <div className="archive-readonly-note"><ShieldCheck size={14} /><span>Historical record only.<br />Not an instruction or live position.</span></div>
                    </> : <p className="archive-select-prompt">Select a row to inspect its recorded metrics and source details.</p>}
                  </aside>
                </div>
                <footer className="archive-browser-foot"><span><LockKeyhole size={12} /> No execution controls in this archive</span><span>Parameters and windows are recorded as supplied</span></footer>
              </section>
              <section className="archive-hypotheses" aria-label="Registered hypotheses">
                <div><span className="archive-kicker">02 / RELATED REGISTER</span><strong>Registered hypotheses</strong><small>Declared pass bars and recorded outcomes</small></div>
                {MOCK_CATALOG.experiments.map((item) => <article key={item.id}><b>#{item.id}</b><span>{familyName(item.family)}</span><em className={item.outcome === "PASS" ? "is-pass" : "is-fail"}>{item.outcome}</em></article>)}
              </section>
            </>
          )}
          <footer className="archive-page-foot"><span><ShieldCheck size={13} /> Read-only historical research · never an order path</span><span>{preview ? "Static sample data — not live" : "Catalog source unavailable"} <button type="button" onClick={() => { setPreview(!preview); setRetryState("idle"); setSelectedId(null); }}>{preview ? "Return to unavailable state" : "View local sample preview"}</button></span></footer>
        </div>
      </section>
    </main>
  );
}
