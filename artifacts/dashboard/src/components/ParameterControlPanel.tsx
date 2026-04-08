import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Sliders, RotateCcw, Save, ChevronDown, ChevronUp,
  Activity, TrendingUp, DollarSign, Shield, Clock,
  Pause, Play, AlertTriangle, CheckCircle, Timer,
} from "lucide-react";
import {
  useAllParameters,
  useUpdateOracleParams,
  useUpdateNavigatorParams,
  useResetBotParams,
  usePauseBotParam,
  useParameterAudit,
  type BotParameterData,
  type ParameterAuditEntry,
  type AllParametersResponse,
} from "@/hooks/use-trading";

// ── Meta for each known parameter ──────────────────────────────────────────

const PARAM_META: Record<string, { label: string; desc: string; icon: React.ReactNode; fmt: (v: number) => string }> = {
  conviction_threshold: {
    label: "Conviction Threshold",
    desc: "Min Claude confidence to place a trade",
    icon: <Activity className="w-3 h-3" />,
    fmt: (v) => v.toFixed(2),
  },
  max_positions: {
    label: "Max Positions",
    desc: "Maximum concurrent equity positions",
    icon: <TrendingUp className="w-3 h-3" />,
    fmt: (v) => String(Math.round(v)),
  },
  cash_reserve_pct: {
    label: "Cash Reserve",
    desc: "Portfolio fraction kept as cash/SGOV",
    icon: <Shield className="w-3 h-3" />,
    fmt: (v) => `${(v * 100).toFixed(0)}%`,
  },
  position_size_usd: {
    label: "Position Size",
    desc: "Per-trade notional in USD for forex",
    icon: <DollarSign className="w-3 h-3" />,
    fmt: (v) => `$${v.toLocaleString()}`,
  },
};

// ── Expiry countdown ────────────────────────────────────────────────────────

function useCountdown(expiresAt: string | null | undefined) {
  const [secondsLeft, setSecondsLeft] = useState<number>(0);

  useEffect(() => {
    if (!expiresAt) { setSecondsLeft(0); return; }
    const update = () => {
      const diff = Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000);
      setSecondsLeft(Math.max(0, diff));
    };
    update();
    const id = setInterval(update, 1000);
    return () => clearInterval(id);
  }, [expiresAt]);

  return secondsLeft;
}

function ExpiryBadge({ expiresAt }: { expiresAt: string | null | undefined }) {
  const secs = useCountdown(expiresAt);
  if (!expiresAt || secs <= 0) return null;

  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  const label = h > 0 ? `${h}h ${m}m` : m > 0 ? `${m}m ${s}s` : `${s}s`;
  const urgent = secs < 3600;

  return (
    <div className={`flex items-center gap-1 text-[9px] font-mono px-1.5 py-0.5 rounded ${
      urgent ? "text-orange-400 bg-orange-950/40" : "text-slate-400 bg-slate-800/60"
    }`}>
      <Timer className="w-2.5 h-2.5" />
      {label}
    </div>
  );
}

// ── Delta indicator ─────────────────────────────────────────────────────────

function Delta({ cur, def, fmt }: { cur: number; def: number; fmt: (v: number) => string }) {
  const diff = cur - def;
  if (Math.abs(diff) < 1e-9) return null;
  const sign = diff > 0 ? "+" : "";
  return (
    <span className={`text-[9px] font-mono ${diff > 0 ? "text-emerald-400" : "text-red-400"}`}>
      {sign}{fmt ? fmt(cur + diff * 0) : diff > 0 ? `+${diff}` : `${diff}`}Δ
    </span>
  );
}

// ── Slider control ──────────────────────────────────────────────────────────

function SliderControl({
  paramName, value, defaultValue, min, max, step, onChange, disabled,
}: {
  paramName: string; value: number; defaultValue: number;
  min: number; max: number; step: number;
  onChange: (v: number) => void; disabled: boolean;
}) {
  const meta = PARAM_META[paramName];
  const pct = ((value - min) / (max - min)) * 100;
  const isChanged = Math.abs(value - defaultValue) > 1e-9;

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-slate-400">
          <span className="text-slate-500">{meta?.icon}</span>
          <span className="text-[11px] font-medium">{meta?.label ?? paramName}</span>
          {isChanged && (
            <span className="text-[9px] text-amber-400 bg-amber-950/40 px-1 rounded">modified</span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {isChanged && (
            <span className="text-[9px] text-slate-500 font-mono line-through">
              {meta?.fmt ? meta.fmt(defaultValue) : defaultValue}
            </span>
          )}
          <span className="text-[11px] font-mono font-bold text-cyan-300 bg-cyan-950/40 px-1.5 py-0.5 rounded">
            {meta?.fmt ? meta.fmt(value) : value}
          </span>
        </div>
      </div>
      {meta?.desc && <p className="text-[9px] text-slate-600 leading-tight">{meta.desc}</p>}
      <div className="relative h-1.5 bg-slate-700/60 rounded-full overflow-hidden">
        <div
          className="absolute inset-y-0 left-0 bg-gradient-to-r from-cyan-600 to-cyan-400 rounded-full transition-all"
          style={{ width: `${pct}%` }}
        />
        <input
          type="range" min={min} max={max} step={step} value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          disabled={disabled}
          className="absolute inset-0 w-full h-full opacity-0 cursor-pointer disabled:cursor-not-allowed"
        />
      </div>
      <div className="flex justify-between text-[8px] text-slate-700 font-mono">
        <span>{meta?.fmt ? meta.fmt(min) : min}</span>
        <span>{meta?.fmt ? meta.fmt(max) : max}</span>
      </div>
    </div>
  );
}

// ── Bot parameter card ──────────────────────────────────────────────────────

function BotOverrideCard({
  title, bot, color,
  data, secondsRemaining,
  onSave, onReset, onPause,
  isSaving, isResetting, isPausing,
}: {
  title: string;
  bot: "oracle" | "navigator";
  color: string;
  data: BotParameterData | undefined;
  secondsRemaining: number | null;
  onSave: (params: Record<string, number | boolean>, reasoning: string, ttl: number) => void;
  onReset: () => void;
  onPause: (paused: boolean) => void;
  isSaving: boolean; isResetting: boolean; isPausing: boolean;
}) {
  const [local, setLocal] = useState<Record<string, number>>({});
  const [reasoning, setReasoning] = useState("");
  const [ttlHours, setTtlHours] = useState(24);
  const [expanded, setExpanded] = useState(true);

  const current = (data?.current ?? {}) as Record<string, number | boolean>;
  const bounds = data?.bounds ?? {};
  const defaults = data?.defaults ?? {};
  const isPaused = Boolean(current["paused"]);
  const expiresAt = data?.override_expires_at;
  const hasActiveOverride = data?.has_active_override;

  const effective = { ...current, ...local };
  const hasChanges = Object.keys(local).some(
    (k) => Math.abs((local[k] ?? 0) - (Number(current[k]) ?? 0)) > 1e-9
  );

  const handleSave = () => {
    if (!hasChanges) return;
    onSave(local, reasoning || "Operator override", ttlHours);
    setLocal({});
    setReasoning("");
  };

  const handleReset = () => {
    setLocal({});
    onReset();
  };

  return (
    <div className="rounded-xl border overflow-hidden" style={{ borderColor: `${color}25` }}>
      <button
        className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-white/[0.02] transition-colors"
        onClick={() => setExpanded((e) => !e)}
      >
        <div className="flex items-center gap-2">
          <Sliders className="w-3.5 h-3.5" style={{ color }} />
          <span className="text-xs font-bold text-white">{title}</span>
          {isPaused && (
            <span className="text-[9px] px-1.5 py-0.5 rounded font-semibold bg-orange-950/60 text-orange-400 border border-orange-500/30">
              PAUSED
            </span>
          )}
          {hasActiveOverride && !isPaused && (
            <CheckCircle className="w-3 h-3 text-emerald-400" />
          )}
          {expiresAt && <ExpiryBadge expiresAt={expiresAt} />}
        </div>
        <div className="flex items-center gap-2">
          {expanded ? <ChevronUp className="w-3 h-3 text-slate-500" /> : <ChevronDown className="w-3 h-3 text-slate-500" />}
        </div>
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 space-y-3 border-t border-white/[0.04]">
              {!data ? (
                <p className="text-xs text-slate-500 pt-2">Loading...</p>
              ) : (
                <>
                  <div className="pt-2 space-y-3">
                    {Object.entries(bounds).map(([param, b]) => (
                      <SliderControl
                        key={param}
                        paramName={param}
                        value={local[param] ?? Number(current[param] ?? b.min)}
                        defaultValue={Number(defaults[param] ?? b.min)}
                        min={b.min} max={b.max} step={b.step}
                        onChange={(v) => setLocal((prev) => ({ ...prev, [param]: v }))}
                        disabled={isSaving || isResetting || isPaused}
                      />
                    ))}
                  </div>

                  {hasChanges && (
                    <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} className="space-y-2">
                      <input
                        type="text"
                        value={reasoning}
                        onChange={(e) => setReasoning(e.target.value)}
                        placeholder="Reason for change (optional)"
                        className="w-full text-[11px] bg-slate-800/60 border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-slate-200 placeholder-slate-600 focus:outline-none focus:border-cyan-500/40"
                      />
                      <div className="flex items-center gap-2">
                        <label className="text-[9px] text-slate-500 whitespace-nowrap">TTL (hours):</label>
                        <input
                          type="number" min={1} max={168} value={ttlHours}
                          onChange={(e) => setTtlHours(Math.max(1, Math.min(168, Number(e.target.value))))}
                          className="w-16 text-[11px] bg-slate-800/60 border border-white/[0.08] rounded px-2 py-1 text-slate-200 focus:outline-none focus:border-cyan-500/40"
                        />
                        <span className="text-[9px] text-slate-600">Auto-reverts after {ttlHours}h</span>
                      </div>
                    </motion.div>
                  )}

                  <div className="flex items-center gap-1.5">
                    <button
                      onClick={handleSave}
                      disabled={!hasChanges || isSaving || isResetting || isPaused}
                      className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-lg text-[11px] font-semibold transition-all disabled:opacity-40 disabled:cursor-not-allowed border"
                      style={{
                        backgroundColor: hasChanges && !isPaused ? `${color}15` : "transparent",
                        color: hasChanges && !isPaused ? color : "#475569",
                        borderColor: hasChanges && !isPaused ? `${color}40` : "#1e293b",
                      }}
                    >
                      <Save className="w-3 h-3" />
                      {isSaving ? "Saving..." : "Apply"}
                    </button>

                    <button
                      onClick={() => onPause(!isPaused)}
                      disabled={isPausing || isResetting}
                      className={`flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-semibold border transition-all disabled:opacity-40 ${
                        isPaused
                          ? "bg-emerald-950/40 border-emerald-500/40 text-emerald-400"
                          : "bg-orange-950/40 border-orange-500/40 text-orange-400"
                      }`}
                    >
                      {isPaused ? <Play className="w-3 h-3" /> : <Pause className="w-3 h-3" />}
                      {isPausing ? "..." : isPaused ? "Resume" : "Pause"}
                    </button>

                    <button
                      onClick={handleReset}
                      disabled={isSaving || isResetting}
                      title="Reset to factory defaults (clears expiry)"
                      className="flex items-center justify-center p-1.5 rounded-lg text-slate-500 border border-slate-700/60 hover:border-slate-600 hover:text-slate-300 transition-all disabled:opacity-40"
                    >
                      <RotateCcw className="w-3 h-3" />
                    </button>
                  </div>

                  {hasActiveOverride && expiresAt && (
                    <div className="flex items-center gap-1.5 text-[9px] text-slate-500 bg-slate-800/40 rounded-lg px-2 py-1.5">
                      <AlertTriangle className="w-2.5 h-2.5 text-amber-500" />
                      <span>Override active — auto-reverts to defaults at expiry</span>
                    </div>
                  )}

                  <div className="pt-1 space-y-0.5">
                    {Object.entries(defaults).map(([k, dv]) => (
                      <div key={k} className="flex justify-between text-[9px] text-slate-700">
                        <span>Default {PARAM_META[k]?.label ?? k}</span>
                        <span className="font-mono">{PARAM_META[k]?.fmt ? PARAM_META[k].fmt(Number(dv)) : dv}</span>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Audit row ───────────────────────────────────────────────────────────────

function AuditRow({ entry }: { entry: ParameterAuditEntry }) {
  const paramKey = entry.parameter_name || entry.param_name;
  const label = PARAM_META[paramKey]?.label ?? paramKey;
  const fmt = PARAM_META[paramKey]?.fmt;
  const oldV = entry.old_value_num !== null && entry.old_value_num !== undefined && fmt
    ? fmt(entry.old_value_num)
    : entry.old_value;
  const newV = entry.new_value_num !== null && entry.new_value_num !== undefined && fmt
    ? fmt(entry.new_value_num)
    : entry.new_value;
  const ts = new Date(entry.ts).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });

  return (
    <div className="flex items-start gap-2 py-1.5 border-b border-white/[0.03] last:border-0 text-[10px]">
      <Clock className="w-2.5 h-2.5 text-slate-700 mt-0.5 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1 flex-wrap">
          <span className="font-mono text-cyan-400">{entry.bot_id}</span>
          <span className="text-slate-600">·</span>
          <span className="text-slate-400">{label}</span>
          <span className="text-slate-600">·</span>
          <span className="font-mono text-red-400">{oldV}</span>
          <span className="text-slate-600">→</span>
          <span className="font-mono text-green-400">{newV}</span>
          {entry.source && (
            <span className="text-[8px] text-slate-700 bg-slate-800/60 px-1 rounded">{entry.source}</span>
          )}
        </div>
        {entry.reasoning && entry.reasoning !== "Reset to factory defaults" && (
          <p className="text-slate-600 mt-0.5 truncate">{entry.reasoning}</p>
        )}
        <div className="flex items-center gap-2 mt-0.5">
          <p className="text-slate-700">{ts}</p>
          {entry.expires_at && (
            <ExpiryBadge expiresAt={entry.expires_at} />
          )}
        </div>
      </div>
    </div>
  );
}

// ── Main panel ──────────────────────────────────────────────────────────────

export function ParameterControlPanel() {
  const { data: allParams } = useAllParameters();
  const { data: auditData } = useParameterAudit(30);

  const updateOracle = useUpdateOracleParams();
  const updateNavigator = useUpdateNavigatorParams();
  const resetOracle = useResetBotParams("oracle");
  const resetNavigator = useResetBotParams("navigator");
  const pauseOracle = usePauseBotParam("oracle");
  const pauseNavigator = usePauseBotParam("navigator");

  const [auditExpanded, setAuditExpanded] = useState(false);

  const oracleData = allParams?.oracle as BotParameterData | undefined;
  const navData = allParams?.navigator as BotParameterData | undefined;

  const handleOracleSave = (params: Record<string, number | boolean>, reasoning: string, ttl: number) => {
    updateOracle.mutate({ ...(params as Parameters<typeof updateOracle.mutate>[0]), reasoning, ttl_hours: ttl });
  };

  const handleNavigatorSave = (params: Record<string, number | boolean>, reasoning: string, ttl: number) => {
    updateNavigator.mutate({ ...(params as Parameters<typeof updateNavigator.mutate>[0]), reasoning, ttl_hours: ttl });
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 mb-1">
        <Sliders className="w-3.5 h-3.5 text-cyan-400" />
        <span className="text-xs font-bold text-slate-200">Parameter Control</span>
        <span className="text-[9px] text-slate-500 bg-slate-800/60 px-2 py-0.5 rounded-full">24h expiry</span>
      </div>

      <BotOverrideCard
        title="Oracle · Alpaca Equities"
        bot="oracle"
        color="#06b6d4"
        data={oracleData}
        secondsRemaining={allParams?.oracle?.seconds_remaining ?? null}
        onSave={handleOracleSave}
        onReset={() => resetOracle.mutate()}
        onPause={(paused) => pauseOracle.mutate({ paused, reasoning: `Operator ${paused ? "pause" : "resume"}` })}
        isSaving={updateOracle.isPending}
        isResetting={resetOracle.isPending}
        isPausing={pauseOracle.isPending}
      />

      <BotOverrideCard
        title="Navigator · Forex"
        bot="navigator"
        color="#8b5cf6"
        data={navData}
        secondsRemaining={allParams?.navigator?.seconds_remaining ?? null}
        onSave={handleNavigatorSave}
        onReset={() => resetNavigator.mutate()}
        onPause={(paused) => pauseNavigator.mutate({ paused, reasoning: `Operator ${paused ? "pause" : "resume"}` })}
        isSaving={updateNavigator.isPending}
        isResetting={resetNavigator.isPending}
        isPausing={pauseNavigator.isPending}
      />

      <div className="rounded-xl border border-white/[0.05] bg-slate-900/40 overflow-hidden">
        <button
          className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-white/[0.02] transition-colors"
          onClick={() => setAuditExpanded((e) => !e)}
        >
          <div className="flex items-center gap-2">
            <Clock className="w-3 h-3 text-slate-600" />
            <span className="text-[11px] font-semibold text-slate-400">Audit Log</span>
            {auditData && (
              <span className="text-[8px] font-mono bg-slate-800 text-slate-500 px-1.5 rounded">
                {auditData.count}
              </span>
            )}
          </div>
          {auditExpanded ? <ChevronUp className="w-3 h-3 text-slate-600" /> : <ChevronDown className="w-3 h-3 text-slate-600" />}
        </button>
        <AnimatePresence>
          {auditExpanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <div className="px-3 pb-3 border-t border-white/[0.04] max-h-56 overflow-y-auto">
                {!auditData || auditData.history.length === 0 ? (
                  <p className="text-[10px] text-slate-600 py-3">No parameter changes recorded yet.</p>
                ) : (
                  auditData.history.map((entry, i) => (
                    <AuditRow key={`${entry.ts}-${i}`} entry={entry} />
                  ))
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
