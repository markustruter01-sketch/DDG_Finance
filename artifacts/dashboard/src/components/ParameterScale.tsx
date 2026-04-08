interface ParameterScaleProps {
  label: string;
  min: number;
  max: number;
  current: number;
  previous?: number;
  format?: (v: number) => string;
  color?: string;
}

function defaultFormat(v: number): string {
  if (Math.abs(v) < 1 && v !== 0) return `${(v * 100).toFixed(1)}%`;
  return v.toFixed(2);
}

export function ParameterScale({
  label,
  min,
  max,
  current,
  previous,
  format = defaultFormat,
  color = "#6b7280",
}: ParameterScaleProps) {
  const range = max - min;
  const toPercent = (v: number) =>
    range > 0 ? Math.max(0, Math.min(100, ((v - min) / range) * 100)) : 50;

  const currentPct = toPercent(current);
  const previousPct = previous != null ? toPercent(previous) : null;

  return (
    <div>
      <div className="flex justify-between items-center mb-1">
        <span className="text-[10px] text-slate-400 font-mono">{label}</span>
        <span className="text-[10px] font-mono text-white">{format(current)}</span>
      </div>
      <div className="relative h-2 rounded-full bg-slate-800/80">
        {previousPct != null && (
          <div
            className="absolute top-1/2 -translate-y-1/2 w-0.5 h-3 rounded-full"
            style={{
              left: `${previousPct}%`,
              background: color,
              opacity: 0.3,
            }}
          />
        )}
        <div
          className="absolute top-1/2 -translate-y-1/2 w-1 h-4 rounded-full"
          style={{
            left: `${currentPct}%`,
            background: color,
            opacity: 1,
            transform: `translateX(-50%) translateY(-50%)`,
            boxShadow: `0 0 4px ${color}80`,
          }}
        />
      </div>
      <div className="flex justify-between mt-0.5">
        <span className="text-[9px] text-slate-700 font-mono">{format(min)}</span>
        <span className="text-[9px] text-slate-700 font-mono">{format(max)}</span>
      </div>
    </div>
  );
}
