import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  BarChart3,
  Check,
  ChevronDown,
  CircleHelp,
  Database,
  FlaskConical,
  GitCompareArrows,
  LockKeyhole,
  Play,
  RotateCcw,
  Settings2,
  ShieldAlert,
  SlidersHorizontal,
  Terminal,
  X,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type Engine = "momentum" | "regime";
type Params = { universe_size: number; engine: Engine };
type CurvePoint = {
  date: string;
  growth_of_100: number;
  drawdown_pct: number;
  positions: number;
  mode?: string;
  regime?: string;
};
type BenchResponse = {
  status: "verified";
  run_id: number;
  spec_hash: string;
  strategy_family: string;
  parameters: Record<string, unknown>;
  data_window: {
    warmup_start: string;
    backtest_start: string;
    backtest_end: string;
    price_table: string;
    price_sources: string[];
  };
  metrics: {
    return_pct: number;
    max_drawdown_pct: number;
    sharpe: number;
    sortino: number;
    trades: number;
    turnover: number;
    mean_deployment: number;
    max_deployment: number;
    days_cash: number;
  };
  curve: CurvePoint[];
  provenance: {
    database: { database: string; host: string; port: number | string };
    price_table: string;
    price_sources: string[];
    data_feed: string;
    screener: string;
    engine: string;
    dashboard_json_used: boolean;
  };
};

type SavedRun = { id: string; params: Params; result: BenchResponse };

const HOLDOUT_START = "2025-01-01";
const HOLDOUT_END = "2026-07-31";
const DEFAULT_PARAMS: Params = { universe_size: 500, engine: "momentum" };
const BASE_URL = `${import.meta.env.BASE_URL}trading-api/`;
const API_HEADERS = {
  "Content-Type": "application/json",
};

const nf = new Intl.NumberFormat("en-US");
const pct = (value: number, digits = 1) =>
  `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
const ddPct = (value: number) => pct(-Math.abs(value));
const shortDate = (value: string) => {
  const [year, month] = value.split("-");
  return `${month}/${year.slice(2)}`;
};

function formatParams(params: Params) {
  return `${params.engine === "regime" ? "REGIME" : "MOMENTUM"} / ${params.universe_size}U / 20N / EQ / 12-1`;
}

function SelectControl({
  label,
  value,
  options,
  onChange,
  testId,
}: {
  label: string;
  value: string | number;
  options: { value: string | number; label: string }[];
  onChange: (value: string) => void;
  testId: string;
}) {
  return (
    <label className="bench-field">
      <span>{label}</span>
      <div className="bench-select-wrap">
        <select
          data-testid={`select-${testId}`}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        >
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <ChevronDown size={13} />
      </div>
    </label>
  );
}

function Metric({
  label,
  value,
  compare,
  tone = "neutral",
  testId,
}: {
  label: string;
  value: string;
  compare?: string;
  tone?: "positive" | "negative" | "neutral";
  testId: string;
}) {
  return (
    <div className="bench-metric" data-testid={`metric-${testId}`}>
      <span className="bench-metric-label">{label}</span>
      <strong className={`bench-metric-value ${tone}`}>{value}</strong>
      {compare && <span className="bench-metric-compare">{compare}</span>}
    </div>
  );
}

function EmptyChart({ message }: { message: string }) {
  return (
    <div className="bench-empty-chart">
      <BarChart3 size={18} />
      <span>{message}</span>
    </div>
  );
}

function BenchLoadingShell() {
  return (
    <main className="bench-shell bench-shell-loading" data-testid="status-bench-loading">
      <aside className="bench-rail">
        <div className="bench-rail-brand">
          <div className="bench-brand-mark">
            <FlaskConical size={18} />
          </div>
          <div>
            <span className="bench-overline">QUANT TERMINAL</span>
            <strong>Strategy Bench</strong>
          </div>
        </div>
        <div className="bench-rail-rule" />
        <div className="bench-rail-button active">
          <SlidersHorizontal size={16} />
          <span>Parameters</span>
        </div>
        <div className="bench-rail-button">
          <GitCompareArrows size={16} />
          <span>Compare</span>
          <b>0</b>
        </div>
        <div className="bench-rail-spacer" />
        <div className="bench-rail-note">
          <span className="bench-status-dot" />
          <div>
            <strong>DEV RESEARCH</strong>
            <span>NO ORDER PATHS</span>
          </div>
        </div>
        <div className="bench-rail-meta">
          <span>ENGINE RUN</span>
          <code>pending</code>
          <span>DATABASE</span>
          <code>heliumdb</code>
        </div>
      </aside>
      <section className="bench-content">
        <header className="bench-topbar">
          <div className="bench-title-group">
            <div className="bench-breadcrumb">
              <Terminal size={13} /> /research / bench <span>•</span> bot_2_momentum
            </div>
            <h1>Momentum strategy bench</h1>
          </div>
          <span className="bench-readonly">
            <Database size={13} /> VERIFIED ENGINE
          </span>
        </header>
        <div className="bench-notice">
          <div>
            <span className="notice-pip" />
            <strong>VERIFIED / DEVELOPMENT RESEARCH</strong>
            <span>Helium price panel · no live prices · no execution access</span>
          </div>
        </div>
        <section className="bench-loading-panel">
          <div className="bench-loading-icon"><FlaskConical size={24} /></div>
          <span className="bench-overline">SERVER RUN IN PROGRESS</span>
          <h2>Running verified Helium engine…</h2>
          <p>
            The controls are ready. The canonical simulation is loading the
            development price panel; no live orders or production data are used.
          </p>
          <div className="bench-loading-bar" />
        </section>
        <footer className="bench-footer">
          <span>QUANT TERMINAL / DEVELOPMENT ONLY</span>
          <span>Waiting for server provenance.</span>
          <span>Publishing remains manual.</span>
        </footer>
      </section>
    </main>
  );
}

export default function BenchPage() {
  const [params, setParams] = useState<Params>(DEFAULT_PARAMS);
  const [holdoutUnlocked, setHoldoutUnlocked] = useState(false);
  const [result, setResult] = useState<BenchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [compareRuns, setCompareRuns] = useState<SavedRun[]>([]);
  const [runLog, setRunLog] = useState<
    { id: string; stamp: string; params: string; result: string }[]
  >([]);
  const [attemptSignatures, setAttemptSignatures] = useState<string[]>([]);
  const [activeRail, setActiveRail] = useState<"controls" | "compare">(
    "controls",
  );

  const backtestEnd = holdoutUnlocked ? HOLDOUT_END : "2024-12-31";
  const requestKey = JSON.stringify({ params, backtestEnd });

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetch(`${BASE_URL}research/strategy-bench/run`, {
      method: "POST",
      headers: API_HEADERS,
      body: JSON.stringify({
        strategy_family:
          params.engine === "regime"
            ? "bot2_momentum_rank500_regime"
            : "bot2_momentum_rank500",
        parameters: { universe_size: params.universe_size },
        data_window: {
          warmup_start: "2018-01-01",
          backtest_start: "2019-02-01",
          backtest_end: backtestEnd,
        },
      }),
      signal: controller.signal,
    })
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) {
          const detail = payload?.detail;
          throw new Error(
            typeof detail === "string"
              ? detail
              : detail?.message ?? "Strategy Bench run was not verified",
          );
        }
        return payload as BenchResponse;
      })
      .then((payload) => {
        setResult(payload);
        setAttemptSignatures((previous) =>
          previous.includes(requestKey)
            ? previous
            : [...previous, requestKey],
        );
        setRunLog((previous) => [
          {
            id: `${payload.run_id}`,
            stamp: new Date().toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
            }),
            params: formatParams(params),
            result: `${pct(payload.metrics.return_pct)} RETURN · #${payload.run_id}`,
          },
          ...previous,
        ].slice(0, 8));
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setResult(null);
          setError(caught instanceof Error ? caught.message : "Unknown Bench error");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [backtestEnd, params, requestKey]);

  const years = result
    ? Math.max(1, result.curve.length / 252)
    : 1;
  const expectedNoiseSharpe = result
    ? Math.sqrt(2 * Math.log(Math.max(2, attemptSignatures.length))) /
      Math.sqrt(years)
    : 0;
  const noiseFloor = result
    ? Math.max(
        8,
        Math.min(92, 50 + (result.metrics.sharpe - expectedNoiseSharpe) * 22),
      )
    : 0;
  const chartTicks = useMemo(
    () =>
      result?.curve
        .filter((_, index) => index % 21 === 0)
        .map((point) => point.date) ?? [],
    [result],
  );
  const lastDate = result?.curve.at(-1)?.date ?? "—";

  const updateParam = <K extends keyof Params>(key: K, value: Params[K]) => {
    setParams((current) => ({ ...current, [key]: value }));
  };
  const resetParams = () => {
    setParams(DEFAULT_PARAMS);
    setHoldoutUnlocked(false);
  };
  const saveComparison = () => {
    if (!result) return;
    const saved: SavedRun = {
      id: `${result.run_id}`,
      params: { ...params },
      result,
    };
    setCompareRuns((current) =>
      current.length >= 3
        ? [...current.slice(1), saved]
        : [...current, saved],
    );
    setActiveRail("compare");
  };

  if (loading && !result) {
    return <BenchLoadingShell />;
  }

  if (error || !result) {
    return (
      <div className="bench-fallback bench-unverified" data-testid="status-bench-error">
        <ShieldAlert size={28} />
        <strong>UNVERIFIED — NO PROVENANCE</strong>
        <h1>Strategy Bench result unavailable</h1>
        <p>{error ?? "The development engine returned no result."}</p>
        <button
          data-testid="button-retry-bench"
          onClick={() => setParams((current) => ({ ...current }))}
        >
          <RotateCcw size={15} /> Retry run
        </button>
      </div>
    );
  }

  return (
    <main className="bench-shell" data-testid="page-bench">
      <aside className="bench-rail">
        <div className="bench-rail-brand">
          <div className="bench-brand-mark">
            <FlaskConical size={18} />
          </div>
          <div>
            <span className="bench-overline">QUANT TERMINAL</span>
            <strong>Strategy Bench</strong>
          </div>
        </div>
        <div className="bench-rail-rule" />
        <button
          className={`bench-rail-button ${activeRail === "controls" ? "active" : ""}`}
          data-testid="button-rail-controls"
          onClick={() => setActiveRail("controls")}
        >
          <SlidersHorizontal size={16} />
          <span>Parameters</span>
          <kbd>⌘1</kbd>
        </button>
        <button
          className={`bench-rail-button ${activeRail === "compare" ? "active" : ""}`}
          data-testid="button-rail-compare"
          onClick={() => setActiveRail("compare")}
        >
          <GitCompareArrows size={16} />
          <span>Compare</span>
          <b>{compareRuns.length}</b>
        </button>
        <div className="bench-rail-spacer" />
        <div className="bench-rail-note">
          <span className="bench-status-dot" />
          <div>
            <strong>DEV RESEARCH</strong>
            <span>NO ORDER PATHS</span>
          </div>
        </div>
        <div className="bench-rail-meta">
          <span>ENGINE RUN</span>
          <code>#{result.run_id}</code>
          <span>DATABASE</span>
          <code>{result.provenance.database.database}</code>
        </div>
      </aside>

      <section className="bench-content">
        <header className="bench-topbar">
          <div className="bench-title-group">
            <div className="bench-breadcrumb">
              <Terminal size={13} /> /research / bench <span>•</span>{" "}
              bot_2_momentum
            </div>
            <h1>Momentum strategy bench</h1>
          </div>
          <div className="bench-top-actions">
            <span className="bench-readonly">
              <Database size={13} /> VERIFIED ENGINE
            </span>
            <button
              className="bench-reset-button"
              data-testid="button-reset-parameters"
              onClick={resetParams}
            >
              <RotateCcw size={13} /> Reset
            </button>
            <button
              className="bench-compare-button"
              data-testid="button-save-comparison"
              onClick={saveComparison}
            >
              <GitCompareArrows size={14} /> Save run
            </button>
          </div>
        </header>

        <div className="bench-notice">
          <div>
            <span className="notice-pip" />
            <strong>VERIFIED / DEVELOPMENT RESEARCH</strong>
            <span>
              Helium price panel · no live prices · no execution access
            </span>
          </div>
          <span
            className="notice-source"
            title={`${result.provenance.database.host}:${result.provenance.database.port} · ${result.provenance.price_table} · ${result.provenance.screener}`}
          >
            <CircleHelp size={13} /> provenance
          </span>
        </div>

        {activeRail === "compare" ? (
          <section className="bench-compare-view" data-testid="panel-compare">
            <div className="bench-section-heading">
              <div>
                <span className="bench-overline">EXPLORATION RUNS</span>
                <h2>Compare parameter sets</h2>
              </div>
              <button
                className="bench-subtle-button"
                data-testid="button-back-controls"
                onClick={() => setActiveRail("controls")}
              >
                <SlidersHorizontal size={14} /> Back to controls
              </button>
            </div>
            {compareRuns.length === 0 ? (
              <div className="bench-compare-empty">
                <GitCompareArrows size={24} />
                <strong>No runs pinned yet</strong>
                <span>
                  Configure a set, then use “Save run” to pin it here. Every
                  saved card points to a server exploration run.
                </span>
              </div>
            ) : (
              <div className="bench-compare-grid">
                {compareRuns.map((run, index) => (
                  <article
                    className="bench-compare-card"
                    key={run.id}
                    data-testid={`card-comparison-${index}`}
                  >
                    <div className="compare-card-top">
                      <span>RUN #{run.result.run_id}</span>
                      <button
                        data-testid={`button-remove-comparison-${index}`}
                        onClick={() =>
                          setCompareRuns((current) =>
                            current.filter((item) => item.id !== run.id),
                          )
                        }
                      >
                        <X size={14} />
                      </button>
                    </div>
                    <code>{formatParams(run.params)}</code>
                    <strong
                      className={
                        run.result.metrics.return_pct >= 0
                          ? "positive"
                          : "negative"
                      }
                    >
                      {pct(run.result.metrics.return_pct)}{" "}
                      <small>RETURN</small>
                    </strong>
                    <div className="compare-mini-metrics">
                      <span>
                        SHARPE <b>{run.result.metrics.sharpe.toFixed(2)}</b>
                      </span>
                      <span>
                        MAX DD{" "}
                        <b>{ddPct(run.result.metrics.max_drawdown_pct)}</b>
                      </span>
                      <span>
                        TRADES <b>{run.result.metrics.trades}</b>
                      </span>
                    </div>
                    <button
                      className="compare-load"
                      data-testid={`button-load-comparison-${index}`}
                      onClick={() => {
                        setParams(run.params);
                        setActiveRail("controls");
                      }}
                    >
                      Load into bench <Play size={13} />
                    </button>
                  </article>
                ))}
              </div>
            )}
            <div className="bench-compare-rule">
              <span>SERVER RUN REGISTRY</span>
              <i />
              <span>{compareRuns.length}/3 slots occupied</span>
            </div>
          </section>
        ) : (
          <>
            <section
              className="bench-controls-panel"
              data-testid="panel-research-controls"
            >
              <div className="bench-panel-heading">
                <div>
                  <span className="bench-overline">CONTROL RAIL</span>
                  <h2>Research parameters</h2>
                </div>
                <span className="bench-recompute">
                  <span /> Runs verified engine on change
                </span>
              </div>
              <div className="bench-control-grid">
                <SelectControl
                  label="Universe size"
                  value={params.universe_size}
                  options={[100, 200, 300, 500].map((value) => ({
                    value,
                    label: `${value} eligible symbols`,
                  }))}
                  onChange={(value) =>
                    updateParam("universe_size", Number(value))
                  }
                  testId="universe"
                />
                <SelectControl
                  label="Verified engine"
                  value={params.engine}
                  options={[
                    { value: "momentum", label: "12-1 momentum" },
                    { value: "regime", label: "Momentum + SPY regime" },
                  ]}
                  onChange={(value) =>
                    updateParam("engine", value as Engine)
                  }
                  testId="engine"
                />
                <label className="bench-field">
                  <span>Warmup start</span>
                  <div className="bench-readonly-field">2018-01-01</div>
                </label>
                <label className="bench-field">
                  <span>Backtest start</span>
                  <div className="bench-readonly-field">2019-02-01</div>
                </label>
                <label className="bench-field">
                  <span>Slippage / stop</span>
                  <div className="bench-readonly-field">10 bps / 20%</div>
                </label>
                <label className="bench-field">
                  <span>Allocation</span>
                  <div className="bench-readonly-field">Equal weight / top 20</div>
                </label>
              </div>
              <div className="bench-control-footer">
                <div className="bench-config-string">
                  <Settings2 size={13} />
                  <code>{formatParams(params)}</code>
                </div>
                <div className="bench-holdout">
                  <div>
                    <LockKeyhole size={14} />
                    <span>
                      <strong>HOLDOUT 2025-01 → 2026-07</strong>
                      <small>Locked until explicitly unlocked</small>
                    </span>
                  </div>
                  <button
                    className={holdoutUnlocked ? "unlocked" : ""}
                    data-testid="button-unlock-holdout"
                    onClick={() => setHoldoutUnlocked((current) => !current)}
                  >
                    {holdoutUnlocked ? (
                      <>
                        <Check size={13} /> Unlocked for this session
                      </>
                    ) : (
                      <>
                        <LockKeyhole size={13} /> Unlock holdout
                      </>
                    )}
                  </button>
                </div>
              </div>
              {holdoutUnlocked && (
                <div className="bench-unlock-ack" data-testid="status-holdout-unlocked">
                  <Check size={14} /> Holdout included in this local
                  exploration only. This does not grant production or trading
                  access.
                </div>
              )}
            </section>

            <section className="bench-result-head">
              <div>
                <span className="bench-overline">
                  RESULT SURFACE / {result.curve.length} SESSIONS
                </span>
                <h2>Verified strategy consequences</h2>
              </div>
              <div className="bench-run-meta">
                <span>
                  LAST PERIOD <b>{lastDate}</b>
                </span>
                <span>
                  RUN <b>#{result.run_id}</b>
                </span>
                <span className="run-ready">
                  <span /> {loading ? "RUNNING" : "RUN VERIFIED"}
                </span>
              </div>
            </section>

            <section className="bench-chart-grid">
              <article className="bench-panel bench-equity-panel">
                <div className="bench-chart-heading">
                  <div>
                    <span className="bench-overline">EQUITY CURVE</span>
                    <h3>Growth of 100</h3>
                  </div>
                  <div className="chart-legend">
                    <span className="legend-strategy" /> VERIFIED ENGINE
                  </div>
                </div>
                <div className="bench-chart">
                  {result.curve.length === 0 ? (
                    <EmptyChart message="No curve returned" />
                  ) : (
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart
                        data={result.curve}
                        margin={{ top: 12, right: 12, left: -18, bottom: 0 }}
                      >
                        <CartesianGrid
                          stroke="rgba(145,160,173,.12)"
                          vertical={false}
                        />
                        <XAxis
                          dataKey="date"
                          ticks={chartTicks}
                          tickFormatter={shortDate}
                          tick={{ fill: "#71808b", fontSize: 10, fontFamily: "IBM Plex Mono" }}
                          axisLine={false}
                          tickLine={false}
                        />
                        <YAxis
                          tick={{ fill: "#71808b", fontSize: 10, fontFamily: "IBM Plex Mono" }}
                          axisLine={false}
                          tickLine={false}
                          tickFormatter={(value: number) => `${value}`}
                        />
                        <Tooltip
                          contentStyle={{ background: "#111a20", border: "1px solid #33414a", borderRadius: 4, fontFamily: "IBM Plex Mono", fontSize: 11 }}
                        />
                        <Line
                          type="monotone"
                          dataKey="growth_of_100"
                          name="VERIFIED ENGINE"
                          stroke="#e9ae57"
                          strokeWidth={2}
                          dot={false}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  )}
                </div>
                <div className="chart-footer">
                  <span>{result.data_window.backtest_start}</span>
                  <span>
                    {holdoutUnlocked ? "HOLDOUT INCLUDED" : "HOLDOUT LOCKED"}
                  </span>
                  <span>{lastDate}</span>
                </div>
              </article>
              <article className="bench-panel bench-drawdown-panel">
                <div className="bench-chart-heading">
                  <div>
                    <span className="bench-overline">RISK PATH</span>
                    <h3>Drawdown</h3>
                  </div>
                  <span className="chart-stat negative" data-testid="value-max-drawdown">
                    {ddPct(result.metrics.max_drawdown_pct)} max
                  </span>
                </div>
                <div className="bench-chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart
                      data={result.curve}
                      margin={{ top: 12, right: 10, left: -18, bottom: 0 }}
                    >
                      <CartesianGrid
                        stroke="rgba(145,160,173,.12)"
                        vertical={false}
                      />
                      <XAxis
                        dataKey="date"
                        ticks={chartTicks}
                        tickFormatter={shortDate}
                        tick={{ fill: "#71808b", fontSize: 10, fontFamily: "IBM Plex Mono" }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <YAxis
                        tick={{ fill: "#71808b", fontSize: 10, fontFamily: "IBM Plex Mono" }}
                        axisLine={false}
                        tickLine={false}
                        tickFormatter={(value: number) => `${value}%`}
                      />
                      <ReferenceLine y={0} stroke="rgba(233,174,87,.24)" />
                      <Tooltip
                        contentStyle={{ background: "#111a20", border: "1px solid #33414a", borderRadius: 4, fontFamily: "IBM Plex Mono", fontSize: 11 }}
                      />
                      <Area
                        type="monotone"
                        dataKey="drawdown_pct"
                        name="Drawdown"
                        stroke="#bc685d"
                        fill="rgba(188,104,93,.18)"
                        strokeWidth={1.5}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
                <div className="chart-footer">
                  <span>PEAK-TO-TROUGH</span>
                  <span>{result.metrics.days_cash} CASH SESSIONS</span>
                </div>
              </article>
            </section>

            <section className="bench-metric-strip" data-testid="panel-metrics">
              <Metric
                label="SHARPE"
                value={result.metrics.sharpe.toFixed(2)}
                tone={result.metrics.sharpe >= 0 ? "positive" : "negative"}
                testId="sharpe"
              />
              <Metric
                label="SORTINO"
                value={result.metrics.sortino.toFixed(2)}
                tone={result.metrics.sortino >= 0 ? "positive" : "negative"}
                testId="sortino"
              />
              <Metric
                label="TOTAL RETURN"
                value={pct(result.metrics.return_pct)}
                tone={result.metrics.return_pct >= 0 ? "positive" : "negative"}
                testId="total-return"
              />
              <Metric
                label="MAX DRAWDOWN"
                value={ddPct(result.metrics.max_drawdown_pct)}
                tone="negative"
                testId="drawdown"
              />
              <Metric
                label="TRADES"
                value={nf.format(result.metrics.trades)}
                compare={`TURNOVER ${pct(result.metrics.turnover * 100)}`}
                tone="neutral"
                testId="trades"
              />
              <Metric
                label="MEAN DEPLOYMENT"
                value={pct(result.metrics.mean_deployment * 100)}
                compare={`MAX ${pct(result.metrics.max_deployment * 100)}`}
                tone="neutral"
                testId="deployment"
              />
            </section>

            <section className="bench-lower-grid">
              <article className="bench-panel noise-panel" data-testid="panel-noise-floor">
                <div className="bench-chart-heading">
                  <div>
                    <span className="bench-overline">ROBUSTNESS PROXY</span>
                    <h3>Noise-floor gauge</h3>
                  </div>
                  <Activity size={16} />
                </div>
                <div className="noise-gauge">
                  <div className="noise-track">
                    <div className="noise-fill" style={{ width: `${noiseFloor}%` }} />
                    <span className="noise-marker" style={{ left: `${noiseFloor}%` }} />
                  </div>
                  <div className="noise-scale">
                    <span>weak</span>
                    <strong>{noiseFloor.toFixed(0)} / 100</strong>
                    <span>persistent</span>
                  </div>
                </div>
                <p>
                  Descriptive only: observed Sharpe compared with the expected
                  best Sharpe from the server run count. Higher is not proof of
                  out-of-sample edge.
                </p>
                <div className="noise-meta">
                  <span>
                    <Activity size={13} /> {nf.format(attemptSignatures.length)}{" "}
                    server runs
                  </span>
                  <span>
                    SH {result.metrics.sharpe.toFixed(2)} / NOISE{" "}
                    {expectedNoiseSharpe.toFixed(2)}
                  </span>
                </div>
              </article>
              <article className="bench-panel runlog-panel" data-testid="panel-run-log">
                <div className="bench-chart-heading">
                  <div>
                    <span className="bench-overline">EXPLORATION RUN LOG</span>
                    <h3>Run log</h3>
                  </div>
                  <span className="runlog-count">{runLog.length} runs</span>
                </div>
                <div className="bench-table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>TIME</th>
                        <th>CONFIG</th>
                        <th>OUTCOME</th>
                      </tr>
                    </thead>
                    <tbody>
                      {runLog.map((entry, index) => (
                        <tr key={entry.id} data-testid={`row-run-log-${index}`}>
                          <td>{entry.stamp}</td>
                          <td>
                            <code>{entry.params}</code>
                          </td>
                          <td className="positive">{entry.result}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </article>
            </section>
          </>
        )}
        <footer className="bench-footer">
          <span>QUANT TERMINAL / DEVELOPMENT ONLY</span>
          <span>
            Source: {result.provenance.price_table} · run #{result.run_id}
          </span>
          <span>Server verified · publishing remains manual.</span>
        </footer>
      </section>
    </main>
  );
}