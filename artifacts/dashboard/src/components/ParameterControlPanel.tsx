import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Sliders, RotateCcw, Save, ChevronDown, ChevronUp,
  Activity, TrendingUp, DollarSign, Shield, Clock,
} from "lucide-react";
import {
  useOracleParams,
  useNavigatorParams,
  useParameterAudit,
  useUpdateOracleParams,
  useUpdateNavigatorParams,
  useResetBotParams,
  type BotParameterData,
  type ParameterAuditEntry,
} from "@/hooks/use-trading";

const PARAM_LABELS: Record<string, { label: string; desc: string; icon: React.ReactNode; fmt: (v: number) => string }> = {
  conviction_threshold: {
    label: "Conviction Threshold",
    desc: "Min LLM confidence to place a trade (lower = more trades)",
    icon: <Activity className="w-3.5 h-3.5" />,
    fmt: (v) => v.toFixed(2),
  },
  max_positions: {
    label: "Max Positions",
    desc: "Maximum concurrent equity positions",
    icon: <TrendingUp className="w-3.5 h-3.5" />,
    fmt: (v) => String(Math.round(v)),
  },
  cash_reserve_pct: {
    label: "Cash Reserve",
    desc: "Fraction of portfolio kept as cash/SGOV",
    icon: <Shield className="w-3.5 h-3.5" />,
    fmt: (v) => `${(v * 100).toFixed(0)}%`,
  },
  position_size_usd: {
    label: "Position Size",
    desc: "Per-trade notional in USD for forex",
    icon: <DollarSign className="w-3.5 h-3.5" />,
    fmt: (v) => `$${v.toLocaleString()}`,
  },
};

function SliderControl({
  paramName,
  value,
  min,
  max,
  step,
  onChange,
  disabled,
}: {
  paramName: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  disabled: boolean;
}) {
  const meta = PARAM_LABELS[paramName];
  const pct = ((value - min) / (max - min)) * 100;

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-slate-300">
          <span className="text-slate-500">{meta?.icon}</span>
          <span className="text-xs font-medium">{meta?.label ?? paramName}</span>
        </div>
        <span className="text-xs font-mono font-bold text-cyan-300 bg-cyan-950/40 px-1.5 py-0.5 rounded">
          {meta?.fmt ? meta.fmt(value) : value}
        </span>
      </div>
      {meta?.desc && (
        <p className="text-[10px] text-slate-500 leading-tight">{meta.desc}</p>
      )}
      <div className="relative h-2 bg-slate-700/60 rounded-full overflow-hidden">
        <div
          className="absolute inset-y-0 left-0 bg-gradient-to-r from-cyan-600 to-cyan-400 rounded-full transition-all"
          style={{ width: `${pct}%` }}
        />
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          disabled={disabled}
          className="absolute inset-0 w-full h-full opacity-0 cursor-pointer disabled:cursor-not-allowed"
        />
      </div>
      <div className="flex justify-between text-[9px] text-slate-600 font-mono">
        <span>{meta?.fmt ? meta.fmt(min) : min}</span>
        <span>{meta?.fmt ? meta.fmt(max) : max}</span>
      </div>
    </div>
  );
}

function BotParamCard({
  title,
  bot,
  color,
  data,
  onSave,
  onReset,
  isSaving,
  isResetting,
}: {
  title: string;
  bot: "oracle" | "navigator";
  color: string;
  data: BotParameterData | undefined;
  onSave: (params: Record<string, number>, reasoning: string) => void;
  onReset: () => void;
  isSaving: boolean;
  isResetting: boolean;
}) {
  const [local, setLocal] = useState<Record<string, number>>({});
  const [reasoning, setReasoning] = useState("");
  const [expanded, setExpanded] = useState(true);

  const current = data?.current ?? {};
  const bounds = data?.bounds ?? {};
  const defaults = data?.defaults ?? {};

  const effective = { ...current, ...local };
  const hasChanges = Object.keys(local).some((k) => Math.abs((local[k] ?? 0) - (current[k] ?? 0)) > 1e-9);

  const handleSlider = (param: string, val: number) => {
    setLocal((prev) => ({ ...prev, [param]: val }));
  };

  const handleSave = () => {
    if (!hasChanges) return;
    onSave(local, reasoning || "Operator override");
    setLocal({});
    setReasoning("");
  };

  const handleReset = () => {
    setLocal({});
    onReset();
  };

  return (
    <div className={`rounded-xl border bg-slate-900/60 overflow-hidden`} style={{ borderColor: `${color}30` }}>
      <button
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/[0.02] transition-colors"
        onClick={() => setExpanded((e) => !e)}
      >
        <div className="flex items-center gap-2">
          <Sliders className="w-4 h-4" style={{ color }} />
          <span className="text-sm font-bold text-white">{title}</span>
          <span
            className="text-[10px] font-mono px-1.5 py-0.5 rounded"
            style={{ color, backgroundColor: `${color}20` }}
          >
            {bot.toUpperCase()}
          </span>
        </div>
        {expanded ? (
          <ChevronUp className="w-3.5 h-3.5 text-slate-500" />
        ) : (
          <ChevronDown className="w-3.5 h-3.5 text-slate-500" />
        )}
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
            <div className="px-4 pb-4 space-y-4 border-t border-white/[0.05]">
              {!data ? (
                <p className="text-xs text-slate-500 pt-3">Loading parameters...</p>
              ) : (
                <>
                  <div className="pt-3 space-y-4">
                    {Object.entries(bounds).map(([param, b]) => (
                      <SliderControl
                        key={param}
                        paramName={param}
                        value={effective[param] ?? current[param] ?? b.min}
                        min={b.min}
                        max={b.max}
                        step={b.step}
                        onChange={(v) => handleSlider(param, v)}
                        disabled={isSaving || isResetting}
                      />
                    ))}
                  </div>

                  {hasChanges && (
                    <motion.div
                      initial={{ opacity: 0, y: -4 }}
                      animate={{ opacity: 1, y: 0 }}
                      className="space-y-2"
                    >
                      <input
                        type="text"
                        value={reasoning}
                        onChange={(e) => setReasoning(e.target.value)}
                        placeholder="Reason for change (optional)"
                        className="w-full text-xs bg-slate-800/60 border border-white/[0.08] rounded-lg px-3 py-2 text-slate-200 placeholder-slate-600 focus:outline-none focus:border-cyan-500/50"
                      />
                    </motion.div>
                  )}

                  <div className="flex items-center gap-2 pt-1">
                    <button
                      onClick={handleSave}
                      disabled={!hasChanges || isSaving || isResetting}
                      className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-semibold transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                      style={{
                        backgroundColor: hasChanges ? `${color}22` : "transparent",
                        color: hasChanges ? color : "#64748b",
                        borderWidth: 1,
                        borderColor: hasChanges ? `${color}50` : "#1e293b",
                      }}
                    >
                      <Save className="w-3 h-3" />
                      {isSaving ? "Saving..." : "Apply Changes"}
                    </button>
                    <button
                      onClick={handleReset}
                      disabled={isSaving || isResetting}
                      className="flex items-center justify-center gap-1 px-3 py-2 rounded-lg text-xs text-slate-400 border border-slate-700/60 hover:border-slate-600 hover:text-slate-300 transition-all disabled:opacity-40"
                      title="Reset to factory defaults"
                    >
                      <RotateCcw className="w-3 h-3" />
                      {isResetting ? "Resetting..." : "Reset"}
                    </button>
                  </div>

                  <div className="text-[10px] text-slate-600 space-y-0.5">
                    {Object.entries(defaults).map(([k, dv]) => (
                      <div key={k} className="flex justify-between">
                        <span>Default {PARAM_LABELS[k]?.label ?? k}</span>
                        <span className="font-mono">{PARAM_LABELS[k]?.fmt ? PARAM_LABELS[k].fmt(dv) : dv}</span>
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

function AuditRow({ entry }: { entry: ParameterAuditEntry }) {
  const label = PARAM_LABELS[entry.param_name]?.label ?? entry.param_name;
  const fmt = PARAM_LABELS[entry.param_name]?.fmt;
  const oldV = fmt ? fmt(Number(entry.old_value)) : entry.old_value;
  const newV = fmt ? fmt(Number(entry.new_value)) : entry.new_value;
  const ts = new Date(entry.ts).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

  return (
    <div className="flex items-start gap-3 py-2 border-b border-white/[0.04] last:border-0 text-[11px]">
      <Clock className="w-3 h-3 text-slate-600 mt-0.5 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="font-mono text-cyan-400">{entry.bot_id}</span>
          <span className="text-slate-500">·</span>
          <span className="text-slate-300">{label}</span>
          <span className="text-slate-500">·</span>
          <span className="font-mono text-red-400">{oldV}</span>
          <span className="text-slate-500">→</span>
          <span className="font-mono text-green-400">{newV}</span>
        </div>
        {entry.reasoning && (
          <p className="text-slate-500 mt-0.5 truncate">{entry.reasoning}</p>
        )}
        <p className="text-slate-700 mt-0.5">{ts} · {entry.source}</p>
      </div>
    </div>
  );
}

export function ParameterControlPanel() {
  const { data: oracleData } = useOracleParams();
  const { data: navData } = useNavigatorParams();
  const { data: auditData } = useParameterAudit(20);

  const updateOracle = useUpdateOracleParams();
  const updateNavigator = useUpdateNavigatorParams();
  const resetOracle = useResetBotParams("oracle");
  const resetNavigator = useResetBotParams("navigator");

  const [auditExpanded, setAuditExpanded] = useState(false);

  const handleOracleSave = (params: Record<string, number>, reasoning: string) => {
    updateOracle.mutate({ ...params, reasoning } as Parameters<typeof updateOracle.mutate>[0]);
  };

  const handleNavigatorSave = (params: Record<string, number>, reasoning: string) => {
    updateNavigator.mutate({ ...params, reasoning } as Parameters<typeof updateNavigator.mutate>[0]);
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 mb-1">
        <Sliders className="w-4 h-4 text-cyan-400" />
        <span className="text-sm font-bold text-slate-200">Parameter Control</span>
        <span className="text-[10px] text-slate-500 bg-slate-800/60 px-2 py-0.5 rounded-full">Oracle & Navigator</span>
      </div>

      <BotParamCard
        title="Oracle Bot — Alpaca Equities"
        bot="oracle"
        color="#06b6d4"
        data={oracleData}
        onSave={handleOracleSave}
        onReset={() => resetOracle.mutate()}
        isSaving={updateOracle.isPending}
        isResetting={resetOracle.isPending}
      />

      <BotParamCard
        title="Navigator Bot — Forex"
        bot="navigator"
        color="#8b5cf6"
        data={navData}
        onSave={handleNavigatorSave}
        onReset={() => resetNavigator.mutate()}
        isSaving={updateNavigator.isPending}
        isResetting={resetNavigator.isPending}
      />

      <div className="rounded-xl border border-white/[0.06] bg-slate-900/40 overflow-hidden">
        <button
          className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/[0.02] transition-colors"
          onClick={() => setAuditExpanded((e) => !e)}
        >
          <div className="flex items-center gap-2">
            <Clock className="w-3.5 h-3.5 text-slate-500" />
            <span className="text-xs font-semibold text-slate-300">Parameter Audit Log</span>
            {auditData && (
              <span className="text-[9px] font-mono bg-slate-800 text-slate-400 px-1.5 rounded">
                {auditData.count}
              </span>
            )}
          </div>
          {auditExpanded ? (
            <ChevronUp className="w-3.5 h-3.5 text-slate-500" />
          ) : (
            <ChevronDown className="w-3.5 h-3.5 text-slate-500" />
          )}
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
              <div className="px-4 pb-3 border-t border-white/[0.05] max-h-64 overflow-y-auto">
                {!auditData || auditData.history.length === 0 ? (
                  <p className="text-xs text-slate-600 py-3">No parameter changes recorded yet.</p>
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
