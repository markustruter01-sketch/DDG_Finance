import { motion } from "framer-motion";
import { useFleetParams, type BotParamBounds } from "@/hooks/use-trading";
import { Sliders, Anchor } from "lucide-react";

const PARAM_LABELS: Record<string, { label: string; short: string; format: (v: number) => string; aggressive: "high" | "low" }> = {
  ZSCORE_ENTRY: {
    label: "Z-Score Entry",
    short: "ZE",
    format: (v) => v.toFixed(2),
    aggressive: "low",
  },
  ZSCORE_EXIT: {
    label: "Z-Score Exit",
    short: "ZX",
    format: (v) => v.toFixed(2),
    aggressive: "low",
  },
  STOP_LOSS_PCT: {
    label: "Stop Loss",
    short: "SL",
    format: (v) => `${(v * 100).toFixed(1)}%`,
    aggressive: "high",
  },
  TRAIL_PCT: {
    label: "Trail %",
    short: "TR",
    format: (v) => `${(v * 100).toFixed(1)}%`,
    aggressive: "low",
  },
  MIN_NET_PROFIT_PCT: {
    label: "Min Profit",
    short: "MNP",
    format: (v) => `${(v * 100).toFixed(1)}%`,
    aggressive: "low",
  },
};

const PARAM_ORDER = ["ZSCORE_ENTRY", "ZSCORE_EXIT", "STOP_LOSS_PCT", "TRAIL_PCT", "MIN_NET_PROFIT_PCT"];

const BOT_LABELS: Record<string, { name: string; color: string; glow: string }> = {
  davy_jones: { name: "Davy Jones", color: "#f59e0b", glow: "shadow-amber-500/20" },
  blackbeard: { name: "Blackbeard", color: "#ef4444", glow: "shadow-red-500/20" },
  calypso: { name: "Calypso", color: "#8b5cf6", glow: "shadow-violet-500/20" },
};

function getAggressivenessColor(value: number, bounds: BotParamBounds, aggressive: "high" | "low"): string {
  const range = bounds.max - bounds.min;
  if (range === 0) return "#6b7280";
  const normalized = (value - bounds.min) / range;
  const aggressiveness = aggressive === "high" ? normalized : 1 - normalized;

  if (aggressiveness < 0.33) return "#22c55e";
  if (aggressiveness < 0.66) return "#f59e0b";
  return "#ef4444";
}

function ParamSlider({
  paramName,
  value,
  bounds,
}: {
  paramName: string;
  value: number;
  bounds: BotParamBounds;
}) {
  const config = PARAM_LABELS[paramName];
  if (!config) return null;

  const range = bounds.max - bounds.min;
  const pct = range > 0 ? ((value - bounds.min) / range) * 100 : 50;
  const clampedPct = Math.max(0, Math.min(100, pct));
  const fillColor = getAggressivenessColor(value, bounds, config.aggressive);

  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] font-mono text-slate-500 w-7 text-right flex-shrink-0">{config.short}</span>
      <div className="flex-1 relative h-4 group">
        <div className="absolute inset-0 rounded-full bg-white/[0.04] border border-white/[0.06] overflow-hidden">
          <motion.div
            className="absolute inset-y-0 left-0 rounded-full"
            style={{ backgroundColor: fillColor }}
            initial={false}
            animate={{ width: `${clampedPct}%`, opacity: 0.6 }}
            transition={{ type: "spring", stiffness: 120, damping: 20 }}
          />
        </div>
        <motion.div
          className="absolute top-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full border-2 border-white/80 z-10"
          style={{ backgroundColor: fillColor }}
          initial={false}
          animate={{ left: `calc(${clampedPct}% - 5px)` }}
          transition={{ type: "spring", stiffness: 120, damping: 20 }}
        />
        <div
          className="absolute top-0 left-0 h-full opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"
          style={{ width: "100%" }}
        >
          <span
            className="absolute -top-0.5 text-[8px] font-mono text-slate-600"
            style={{ left: 0 }}
          >
            {config.format(bounds.min)}
          </span>
          <span
            className="absolute -top-0.5 text-[8px] font-mono text-slate-600"
            style={{ right: 0 }}
          >
            {config.format(bounds.max)}
          </span>
        </div>
      </div>
      <motion.span
        className="text-[10px] font-mono font-semibold w-12 text-right flex-shrink-0"
        style={{ color: fillColor }}
        key={value}
        initial={{ opacity: 0.5, scale: 1.15 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.4 }}
      >
        {config.format(value)}
      </motion.span>
    </div>
  );
}

export function BotParameterSliders() {
  const { data, isLoading } = useFleetParams();

  if (isLoading) {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2 px-1">
          <Sliders className="w-3.5 h-3.5 text-slate-500" />
          <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">Bot Parameters</span>
        </div>
        {[0, 1, 2].map((i) => (
          <div key={i} className="rounded-xl border border-white/[0.04] bg-white/[0.02] p-3 animate-pulse">
            <div className="h-3 w-24 bg-white/5 rounded mb-3" />
            <div className="space-y-2">
              {[0, 1, 2, 3, 4].map((j) => (
                <div key={j} className="h-4 bg-white/[0.03] rounded-full" />
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (!data?.bots || Object.keys(data.bots).length === 0) return null;

  return (
    <div className="space-y-2.5">
      <div className="flex items-center gap-2 px-1">
        <Sliders className="w-3.5 h-3.5 text-indigo-400/70" />
        <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">Bot Parameters</span>
      </div>

      {Object.entries(data.bots).map(([botId, botData]) => {
        const label = BOT_LABELS[botId] || { name: botId, color: "#6b7280", glow: "" };

        return (
          <motion.div
            key={botId}
            className="rounded-xl border border-white/[0.06] bg-slate-900/50 p-3"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
          >
            <div className="flex items-center gap-2 mb-2.5">
              <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: label.color }} />
              <Anchor className="w-3 h-3 flex-shrink-0" style={{ color: label.color, opacity: 0.6 }} />
              <span className="text-[11px] font-bold text-white tracking-wide">{label.name}</span>
            </div>
            <div className="space-y-1.5">
              {PARAM_ORDER.map((paramName) => {
                const value = botData.current?.[paramName];
                const bounds = botData.bounds?.[paramName];
                if (value == null || !bounds) return null;
                return (
                  <ParamSlider
                    key={paramName}
                    paramName={paramName}
                    value={value}
                    bounds={bounds}
                  />
                );
              })}
            </div>
          </motion.div>
        );
      })}
    </div>
  );
}
