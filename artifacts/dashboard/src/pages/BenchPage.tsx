import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  BarChart3,
  Check,
  ChevronDown,
  CircleHelp,
  Database,
  FlaskConical,
  Gauge,
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

type BenchData = {
  meta: { source: string; generated: string };
  months: string[];
  universe: Record<string, string[]>;
  momentum: Record<string, Record<string, Record<string, number>>>;
  forward: Record<string, Record<string, number>>;
  vol: Record<string, Record<string, number>>;
  spy: Record<string, { ret: number; risk_on: boolean }>;
};

type Params = {
  universe: number;
  lookback: number;
  skip: number;
  positions: number;
  weighting: "equal" | "inverse_vol";
  rebalance: number;
  stop: number;
  slippage: number;
  deployment: number;
  regime: "none" | "spy_200sma" | "vol_scaled";
  volTarget: number;
};

type ResultPoint = {
  month: string;
  strategy: number;
  spy: number;
  drawdown: number;
  selected: number;
  riskOn: boolean;
};

type RunResult = {
  curve: ResultPoint[];
  sharpe: number;
  spySharpe: number;
  sortino: number;
  spySortino: number;
  totalReturn: number;
  spyReturn: number;
  cagr: number;
  spyCagr: number;
  maxDrawdown: number;
  spyDrawdown: number;
  volatility: number;
  hitRate: number;
  turnover: number;
  monthsCash: number;
  spyMonthsCash: number;
  years: number;
  score: number;
};

type SavedRun = { id: string; params: Params; result: RunResult };

const HOLDOUT_START = "2025-01";
const DEFAULT_PARAMS: Params = {
  universe: 200,
  lookback: 6,
  skip: 1,
  positions: 12,
  weighting: "inverse_vol",
  rebalance: 1,
  stop: 12,
  slippage: 8,
  deployment: 100,
  regime: "spy_200sma",
  volTarget: 14,
};

const nf = new Intl.NumberFormat("en-US");
const pct = (value: number, digits = 1) => `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
const shortMonth = (month: string) => {
  const [year, monthNumber] = month.split("-");
  return `${monthNumber}/${year.slice(2)}`;
};

function simulate(data: BenchData, params: Params, unlocked: boolean): RunResult {
  const months = data.months.filter((month) => unlocked || month < HOLDOUT_START);
  const curve: ResultPoint[] = [];
  let strategy = 100;
  let spy = 100;
  let peak = 100;
  let tradeCount = 0;
  let winningMonths = 0;
  const strategyReturns: number[] = [];
  const spyReturns: number[] = [];
  let holdings: string[] = [];
  let monthsCash = 0;

  months.forEach((month, index) => {
    const universe = data.universe[month] ?? [];
    const momentum = data.momentum[month] ?? {};
    const momentumKey = `${params.lookback}_${params.skip}`;
    const forward = data.forward[month] ?? {};
    const vol = data.vol[month] ?? {};
    const candidates = universe
      .slice(0, params.universe)
      .filter((ticker) => typeof momentum[ticker]?.[momentumKey] === "number" && typeof forward[ticker] === "number")
      .sort((a, b) => (momentum[b]?.[momentumKey] ?? 0) - (momentum[a]?.[momentumKey] ?? 0));
    const canTrade = index >= 0;
    const shouldRebalance = canTrade && (index === 0 || index % params.rebalance === 0);
    if (shouldRebalance) {
      holdings = candidates.slice(0, Math.min(params.positions, candidates.length));
      tradeCount += holdings.length;
    }

    const activeHoldings = holdings.filter((ticker) => typeof forward[ticker] === "number");
    const gross = activeHoldings.length
      ? activeHoldings.reduce((total, ticker) => {
          const raw = forward[ticker] ?? 0;
          const stopped = Math.max(raw, -params.stop / 100);
          const weight = params.weighting === "inverse_vol" ? 1 / Math.max(vol[ticker] ?? 0.25, 0.05) : 1;
          return total + stopped * weight;
        }, 0) / activeHoldings.reduce((total, ticker) => {
          const weight = params.weighting === "inverse_vol" ? 1 / Math.max(vol[ticker] ?? 0.25, 0.05) : 1;
          return total + weight;
        }, 0)
      : 0;
    const spyReturn = data.spy[month]?.ret ?? 0;
    const riskOn = data.spy[month]?.risk_on ?? true;
    let deployment = params.deployment / 100;
    if (params.regime === "spy_200sma" && !riskOn) deployment = 0;
    if (params.regime === "vol_scaled") deployment *= Math.min(1, params.volTarget / Math.max(8, Math.abs(spyReturn) * 100 * 1.8));
    const costs = shouldRebalance ? params.slippage / 10000 : 0;
    const net = canTrade ? gross * deployment - costs : 0;
    strategy *= 1 + net;
    spy *= 1 + spyReturn;
    strategyReturns.push(net);
    spyReturns.push(spyReturn);
    if (net > 0) winningMonths += 1;
    if (activeHoldings.length === 0 || deployment === 0) monthsCash += 1;
    peak = Math.max(peak, strategy);
    curve.push({
      month,
      strategy,
      spy,
      drawdown: ((strategy / peak) - 1) * 100,
      selected: activeHoldings.length,
      riskOn,
    });
  });

  const first = curve[0] ?? { strategy: 100, spy: 100 };
  const years = Math.max(1, curve.length / 12);
  const mean = (values: number[]) => values.reduce((total, value) => total + value, 0) / Math.max(1, values.length);
  const deviation = (values: number[]) => {
    const average = mean(values);
    return Math.sqrt(mean(values.map((value) => (value - average) ** 2)));
  };
  const annualizedSharpe = (values: number[]) => {
    const standardDeviation = deviation(values);
    return standardDeviation > 0 ? (mean(values) / standardDeviation) * Math.sqrt(12) : 0;
  };
  const annualizedSortino = (values: number[]) => {
    const downsideDeviation = Math.sqrt(mean(values.map((value) => Math.min(0, value) ** 2)));
    return downsideDeviation > 0 ? (mean(values) / downsideDeviation) * Math.sqrt(12) : 0;
  };
  const sharpe = annualizedSharpe(strategyReturns);
  const spySharpe = annualizedSharpe(spyReturns);
  const sortino = annualizedSortino(strategyReturns);
  const spySortino = annualizedSortino(spyReturns);
  const volatility = deviation(strategyReturns) * Math.sqrt(12) * 100;
  const maxDrawdown = curve.reduce((lowest, point) => Math.min(lowest, point.drawdown), 0);
  const spyDrawdown = curve.reduce((lowest, point) => Math.min(lowest, ((point.spy / Math.max(...curve.slice(0, curve.indexOf(point) + 1).map((item) => item.spy))) - 1) * 100), 0);
  const totalReturn = ((curve.at(-1)?.strategy ?? first.strategy) / first.strategy - 1) * 100;
  const spyReturn = ((curve.at(-1)?.spy ?? first.spy) / first.spy - 1) * 100;
  const cagr = (Math.pow((curve.at(-1)?.strategy ?? 100) / 100, 1 / years) - 1) * 100;
  const spyCagr = (Math.pow((curve.at(-1)?.spy ?? 100) / 100, 1 / years) - 1) * 100;
  const hitRate = (winningMonths / Math.max(1, strategyReturns.length)) * 100;
  const turnover = (tradeCount / Math.max(1, curve.length)) * 100;
  const score = Math.max(0, Math.min(100, 50 + sharpe * 16 + maxDrawdown * 0.7 - volatility * 0.2));
  return {
    curve,
    sharpe,
    spySharpe,
    sortino,
    spySortino,
    totalReturn,
    spyReturn,
    cagr,
    spyCagr,
    maxDrawdown,
    spyDrawdown,
    volatility,
    hitRate,
    turnover,
    monthsCash,
    spyMonthsCash: 0,
    years,
    score,
  };
}

function formatParams(params: Params) {
  return `${params.universe}U / ${params.lookback}L / ${params.skip}S / ${params.positions}N / ${params.weighting === "equal" ? "EQ" : "IV"} / ${params.rebalance}M`;
}

function SelectControl({
  label,
  value,
  options,
  onChange,
  testId,
  suffix,
}: {
  label: string;
  value: string | number;
  options: (string | number)[];
  onChange: (value: string) => void;
  testId: string;
  suffix?: string;
}) {
  return (
    <label className="bench-field">
      <span>{label}</span>
      <div className="bench-select-wrap">
        <select data-testid={`select-${testId}`} value={value} onChange={(event) => onChange(event.target.value)}>
          {options.map((option) => <option key={option} value={option}>{option}{suffix ?? ""}</option>)}
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
  return <div className="bench-empty-chart"><BarChart3 size={18} /><span>{message}</span></div>;
}

export default function BenchPage() {
  const [data, setData] = useState<BenchData | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [params, setParams] = useState<Params>(DEFAULT_PARAMS);
  const [holdoutUnlocked, setHoldoutUnlocked] = useState(false);
  const [compareRuns, setCompareRuns] = useState<SavedRun[]>([]);
  const [runLog, setRunLog] = useState<{ id: string; stamp: string; params: string; result: string }[]>([]);
  const [attemptSignatures, setAttemptSignatures] = useState<string[]>([]);
  const [activeRail, setActiveRail] = useState<"controls" | "compare">("controls");

  useEffect(() => {
    let mounted = true;
    fetch(`${import.meta.env.BASE_URL}strategy-bench.json`)
      .then((response) => {
        if (!response.ok) throw new Error("Unable to load bench asset");
        return response.json() as Promise<BenchData>;
      })
      .then((payload) => mounted && setData(payload))
      .catch(() => mounted && setLoadError(true));
    return () => { mounted = false; };
  }, []);

  const result = useMemo(() => data ? simulate(data, params, holdoutUnlocked) : null, [data, params, holdoutUnlocked]);
  const lastMonth = result?.curve.at(-1)?.month ?? "—";
  const signature = JSON.stringify(params) + holdoutUnlocked;
  const attemptCount = Math.max(1, attemptSignatures.length);
  const expectedNoiseSharpe = result
    ? Math.sqrt(2 * Math.log(Math.max(2, attemptCount))) / Math.sqrt(result.years)
    : 0;
  const noiseFloor = result
    ? Math.max(8, Math.min(92, 50 + (result.sharpe - expectedNoiseSharpe) * 22))
    : 0;

  useEffect(() => {
    if (!result || !data) return;
    setAttemptSignatures((previous) => previous.includes(signature) ? previous : [...previous, signature]);
    const stamp = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    setRunLog((previous) => [
      { id: `${Date.now()}`, stamp, params: formatParams(params), result: `${pct(result.cagr)} CAGR` },
      ...previous,
    ].slice(0, 8));
    // signature intentionally makes each control change an auditable local run.
  }, [signature]);

  const updateParam = <K extends keyof Params>(key: K, value: Params[K]) => {
    setParams((current) => ({ ...current, [key]: value }));
  };

  const resetParams = () => setParams(DEFAULT_PARAMS);
  const saveComparison = () => {
    if (!result) return;
    const saved: SavedRun = { id: `${Date.now()}`, params: { ...params }, result };
    setCompareRuns((current) => current.length >= 3 ? [...current.slice(1), saved] : [...current, saved]);
    setActiveRail("compare");
  };
  const removeComparison = (id: string) => setCompareRuns((current) => current.filter((run) => run.id !== id));

  if (loadError) {
    return (
      <div className="bench-fallback" data-testid="status-bench-error">
        <ShieldAlert size={28} />
        <h1>Research asset unavailable</h1>
        <p>strategy-bench.json could not be loaded from the development bundle.</p>
        <button data-testid="button-retry-bench" onClick={() => window.location.reload()}><RotateCcw size={15} /> Retry load</button>
      </div>
    );
  }
  if (!data || !result) {
    return (
      <div className="bench-fallback" data-testid="status-bench-loading">
        <div className="bench-loading-bar" />
        <span>Indexing synthetic monthly panel…</span>
      </div>
    );
  }

  const chartTicks = result.curve.filter((_, index) => index % 12 === 0).map((point) => point.month);
  return (
    <main className="bench-shell" data-testid="page-bench">
      <aside className="bench-rail">
        <div className="bench-rail-brand">
          <div className="bench-brand-mark"><FlaskConical size={18} /></div>
          <div><span className="bench-overline">QUANT TERMINAL</span><strong>Strategy Bench</strong></div>
        </div>
        <div className="bench-rail-rule" />
        <button className={`bench-rail-button ${activeRail === "controls" ? "active" : ""}`} data-testid="button-rail-controls" onClick={() => setActiveRail("controls")}>
          <SlidersHorizontal size={16} /><span>Parameters</span><kbd>⌘1</kbd>
        </button>
        <button className={`bench-rail-button ${activeRail === "compare" ? "active" : ""}`} data-testid="button-rail-compare" onClick={() => setActiveRail("compare")}>
          <GitCompareArrows size={16} /><span>Compare</span><b>{compareRuns.length}</b>
        </button>
        <div className="bench-rail-spacer" />
        <div className="bench-rail-note">
          <span className="bench-status-dot" />
          <div><strong>DEV RESEARCH</strong><span>NO ORDER PATHS</span></div>
        </div>
        <div className="bench-rail-meta">
          <span>ASSET</span><code>BENCH / v3.4</code>
          <span>GENERATED</span><code>{data.meta.generated.slice(0, 10)}</code>
        </div>
      </aside>

      <section className="bench-content">
        <header className="bench-topbar">
          <div className="bench-title-group">
            <div className="bench-breadcrumb"><Terminal size={13} /> /research / bench <span>•</span> bot_2_momentum</div>
            <h1>Momentum strategy bench</h1>
          </div>
          <div className="bench-top-actions">
            <span className="bench-readonly"><Database size={13} /> STATIC PANEL</span>
            <button className="bench-reset-button" data-testid="button-reset-parameters" onClick={resetParams}><RotateCcw size={13} /> Reset</button>
            <button className="bench-compare-button" data-testid="button-save-comparison" onClick={saveComparison}><GitCompareArrows size={14} /> Save run</button>
          </div>
        </header>

        <div className="bench-notice">
          <div><span className="notice-pip" /><strong>SYNTHETIC / DEVELOPMENT RESEARCH</strong><span>Monthly adjusted panel · no live prices · no execution access</span></div>
          <span className="notice-source" title={data.meta.source}><CircleHelp size={13} /> provenance</span>
        </div>

        {activeRail === "compare" ? (
          <section className="bench-compare-view" data-testid="panel-compare">
            <div className="bench-section-heading"><div><span className="bench-overline">RUN REGISTRY</span><h2>Compare parameter sets</h2></div><button className="bench-subtle-button" data-testid="button-back-controls" onClick={() => setActiveRail("controls")}><SlidersHorizontal size={14} /> Back to controls</button></div>
            {compareRuns.length === 0 ? (
              <div className="bench-compare-empty"><GitCompareArrows size={24} /><strong>No runs pinned yet</strong><span>Configure a set, then use “Save run” to pin it here. Keep two or three candidates in view while you search.</span></div>
            ) : (
              <div className="bench-compare-grid">
                {compareRuns.map((run, index) => (
                  <article className="bench-compare-card" key={run.id} data-testid={`card-comparison-${index}`}>
                    <div className="compare-card-top"><span>RUN {String(index + 1).padStart(2, "0")}</span><button data-testid={`button-remove-comparison-${index}`} onClick={() => removeComparison(run.id)}><X size={14} /></button></div>
                    <code>{formatParams(run.params)}</code>
                    <strong className={run.result.cagr >= 0 ? "positive" : "negative"}>{pct(run.result.cagr)} <small>CAGR</small></strong>
                    <div className="compare-mini-metrics"><span>MAX DD <b>{pct(run.result.maxDrawdown)}</b></span><span>VOL <b>{run.result.volatility.toFixed(1)}%</b></span><span>HIT <b>{run.result.hitRate.toFixed(0)}%</b></span></div>
                    <button className="compare-load" data-testid={`button-load-comparison-${index}`} onClick={() => { setParams(run.params); setActiveRail("controls"); }}>Load into bench <Play size={13} /></button>
                  </article>
                ))}
              </div>
            )}
            <div className="bench-compare-rule"><span>COMPARE MODE</span><i /> <span>{compareRuns.length}/3 slots occupied</span></div>
          </section>
        ) : (
          <>
            <section className="bench-controls-panel" data-testid="panel-research-controls">
              <div className="bench-panel-heading"><div><span className="bench-overline">CONTROL RAIL</span><h2>Research parameters</h2></div><span className="bench-recompute"><span /> Recomputes on change</span></div>
              <div className="bench-control-grid">
                <SelectControl label="Universe size" value={params.universe} options={[100, 200, 300, 500]} onChange={(value) => updateParam("universe", Number(value))} testId="universe" />
                <SelectControl label="Lookback" value={params.lookback} options={[3, 6, 9, 12]} onChange={(value) => updateParam("lookback", Number(value))} testId="lookback" suffix=" mo" />
                <SelectControl label="Skip" value={params.skip} options={[0, 1]} onChange={(value) => updateParam("skip", Number(value))} testId="skip" suffix=" mo" />
                <SelectControl label="Positions / top N" value={params.positions} options={[5, 8, 12, 20, 30]} onChange={(value) => updateParam("positions", Number(value))} testId="positions" />
                <SelectControl label="Weighting" value={params.weighting} options={["equal", "inverse_vol"]} onChange={(value) => updateParam("weighting", value as Params["weighting"])} testId="weighting" />
                <SelectControl label="Rebalance" value={params.rebalance} options={[1, 3, 6]} onChange={(value) => updateParam("rebalance", Number(value))} testId="rebalance" suffix=" mo" />
                <label className="bench-range-field"><span>Stop loss <b>{params.stop}%</b></span><input data-testid="input-stop" type="range" min="4" max="25" step="1" value={params.stop} onChange={(event) => updateParam("stop", Number(event.target.value))} /></label>
                <label className="bench-range-field"><span>Slippage <b>{params.slippage} bps</b></span><input data-testid="input-slippage" type="range" min="0" max="30" step="1" value={params.slippage} onChange={(event) => updateParam("slippage", Number(event.target.value))} /></label>
                <label className="bench-range-field"><span>Max deployment <b>{params.deployment}%</b></span><input data-testid="input-deployment" type="range" min="25" max="100" step="5" value={params.deployment} onChange={(event) => updateParam("deployment", Number(event.target.value))} /></label>
                <SelectControl label="Regime filter" value={params.regime} options={["none", "spy_200sma", "vol_scaled"]} onChange={(value) => updateParam("regime", value as Params["regime"])} testId="regime" />
                <label className="bench-range-field"><span>Vol target <b>{params.volTarget}%</b></span><input data-testid="input-vol-target" type="range" min="6" max="24" step="1" value={params.volTarget} onChange={(event) => updateParam("volTarget", Number(event.target.value))} /></label>
              </div>
              <div className="bench-control-footer">
                <div className="bench-config-string"><Settings2 size={13} /><code>{formatParams(params)}</code></div>
                <div className="bench-holdout">
                  <div><LockKeyhole size={14} /><span><strong>HOLDOUT 2025-01 →</strong><small>Locked until explicitly unlocked</small></span></div>
                  <button className={holdoutUnlocked ? "unlocked" : ""} data-testid="button-unlock-holdout" onClick={() => setHoldoutUnlocked((current) => !current)}>{holdoutUnlocked ? <><Check size={13} /> Unlocked for this session</> : <><LockKeyhole size={13} /> Unlock holdout</>}</button>
                </div>
              </div>
              {holdoutUnlocked && <div className="bench-unlock-ack" data-testid="status-holdout-unlocked"><Check size={14} /> Holdout included in this local exploration only. This does not grant production or trading access.</div>}
            </section>

            <section className="bench-result-head">
              <div><span className="bench-overline">RESULT SURFACE / {result.curve.length} MONTHS</span><h2>Strategy consequences</h2></div>
              <div className="bench-run-meta"><span>LAST PERIOD <b>{lastMonth}</b></span><span>ATTEMPTS <b data-testid="value-attempt-count">{nf.format(attemptCount)}</b></span><span className="run-ready"><span /> RUN COMPLETE</span></div>
            </section>

            <section className="bench-chart-grid">
              <article className="bench-panel bench-equity-panel">
                <div className="bench-chart-heading"><div><span className="bench-overline">EQUITY CURVE</span><h3>Growth of 100</h3></div><div className="chart-legend"><span className="legend-strategy" /> BOT 2 <span className="legend-spy" /> SPY</div></div>
                <div className="bench-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={result.curve} margin={{ top: 12, right: 12, left: -18, bottom: 0 }}><CartesianGrid stroke="rgba(145,160,173,.12)" vertical={false} /><XAxis dataKey="month" ticks={chartTicks} tickFormatter={shortMonth} tick={{ fill: "#71808b", fontSize: 10, fontFamily: "IBM Plex Mono" }} axisLine={false} tickLine={false} /><YAxis tick={{ fill: "#71808b", fontSize: 10, fontFamily: "IBM Plex Mono" }} axisLine={false} tickLine={false} tickFormatter={(value: number) => `${value}`} /><Tooltip contentStyle={{ background: "#111a20", border: "1px solid #33414a", borderRadius: 4, fontFamily: "IBM Plex Mono", fontSize: 11 }} labelStyle={{ color: "#aab8c0" }} /><Line type="monotone" dataKey="strategy" name="BOT 2" stroke="#e9ae57" strokeWidth={2} dot={false} /><Line type="monotone" dataKey="spy" name="SPY" stroke="#69808b" strokeWidth={1.5} dot={false} strokeDasharray="5 4" /></LineChart></ResponsiveContainer></div>
                <div className="chart-footer"><span>2019-02</span><span>{holdoutUnlocked ? "HOLDOUT INCLUDED" : "HOLDOUT LOCKED AT 2024-12"}</span><span>{lastMonth}</span></div>
              </article>
              <article className="bench-panel bench-drawdown-panel">
                <div className="bench-chart-heading"><div><span className="bench-overline">RISK PATH</span><h3>Drawdown</h3></div><span className="chart-stat negative" data-testid="value-max-drawdown">{pct(result.maxDrawdown)} max</span></div>
                <div className="bench-chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={result.curve} margin={{ top: 12, right: 10, left: -18, bottom: 0 }}><CartesianGrid stroke="rgba(145,160,173,.12)" vertical={false} /><XAxis dataKey="month" ticks={chartTicks} tickFormatter={shortMonth} tick={{ fill: "#71808b", fontSize: 10, fontFamily: "IBM Plex Mono" }} axisLine={false} tickLine={false} /><YAxis tick={{ fill: "#71808b", fontSize: 10, fontFamily: "IBM Plex Mono" }} axisLine={false} tickLine={false} tickFormatter={(value: number) => `${value}%`} /><ReferenceLine y={0} stroke="rgba(233,174,87,.24)" /><Tooltip contentStyle={{ background: "#111a20", border: "1px solid #33414a", borderRadius: 4, fontFamily: "IBM Plex Mono", fontSize: 11 }} /><Area type="monotone" dataKey="drawdown" name="Drawdown" stroke="#bc685d" fill="rgba(188,104,93,.18)" strokeWidth={1.5} /></AreaChart></ResponsiveContainer></div>
                <div className="chart-footer"><span>PEAK-TO-TROUGH</span><span>SPY REF {pct(result.spyDrawdown)}</span></div>
              </article>
            </section>

            <section className="bench-metric-strip" data-testid="panel-metrics">
              <Metric label="SHARPE" value={result.sharpe.toFixed(2)} compare={`SPY ${result.spySharpe.toFixed(2)}`} tone={result.sharpe >= result.spySharpe ? "positive" : "negative"} testId="sharpe" />
              <Metric label="SORTINO" value={result.sortino.toFixed(2)} compare={`SPY ${result.spySortino.toFixed(2)}`} tone={result.sortino >= result.spySortino ? "positive" : "negative"} testId="sortino" />
              <Metric label="TOTAL RETURN" value={pct(result.totalReturn)} compare={`SPY ${pct(result.spyReturn)}`} tone={result.totalReturn >= result.spyReturn ? "positive" : "negative"} testId="total-return" />
              <Metric label="MAX DRAWDOWN" value={pct(result.maxDrawdown)} compare={`SPY ${pct(result.spyDrawdown)}`} tone="negative" testId="drawdown" />
              <Metric label="MONTHS IN CASH" value={`${result.monthsCash}`} compare={`SPY ${result.spyMonthsCash}`} tone="neutral" testId="months-cash" />
              <Metric label="YEARS TESTED" value={result.years.toFixed(1)} compare={`SPY ${result.years.toFixed(1)}`} tone="neutral" testId="years-tested" />
            </section>

            <section className="bench-lower-grid">
              <article className="bench-panel noise-panel" data-testid="panel-noise-floor">
                <div className="bench-chart-heading"><div><span className="bench-overline">ROBUSTNESS PROXY</span><h3>Noise-floor gauge</h3></div><Gauge size={16} /></div>
                <div className="noise-gauge"><div className="noise-track"><div className="noise-fill" style={{ width: `${noiseFloor}%` }} /><span className="noise-marker" style={{ left: `${noiseFloor}%` }} /></div><div className="noise-scale"><span>weak</span><strong>{noiseFloor.toFixed(0)} / 100</strong><span>persistent</span></div></div>
                <p>Observed Sharpe compared with the expected best Sharpe from noise. Higher is not proof of out-of-sample edge.</p>
                <div className="noise-meta"><span><Activity size={13} /> {nf.format(attemptCount)} distinct parameter sets</span><span>SH {result.sharpe.toFixed(2)} / NOISE {expectedNoiseSharpe.toFixed(2)}</span></div>
              </article>
              <article className="bench-panel runlog-panel" data-testid="panel-run-log">
                <div className="bench-chart-heading"><div><span className="bench-overline">LOCAL AUDIT TRAIL</span><h3>Run log</h3></div><span className="runlog-count">{runLog.length} runs</span></div>
                <div className="bench-table-wrap"><table><thead><tr><th>TIME</th><th>CONFIG</th><th>OUTCOME</th></tr></thead><tbody>{runLog.map((entry, index) => <tr key={entry.id} data-testid={`row-run-log-${index}`}><td>{entry.stamp}</td><td><code>{entry.params}</code></td><td className={entry.result.startsWith("+") ? "positive" : ""}>{entry.result}</td></tr>)}</tbody></table></div>
              </article>
            </section>
          </>
        )}
        <footer className="bench-footer"><span>QUANT TERMINAL / DEVELOPMENT ONLY</span><span>Source: {data.meta.source.split(";")[0]}</span><span>Research controls are client-side and non-executable.</span></footer>
      </section>
    </main>
  );
}