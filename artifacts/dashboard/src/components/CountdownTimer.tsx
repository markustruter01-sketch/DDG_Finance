import { useState, useEffect, useMemo } from 'react';
import { motion } from 'framer-motion';
import { Clock, Zap, AlertTriangle, CheckCircle2 } from 'lucide-react';

interface CountdownTimerProps {
  targetISO: string | null;
  label: string;
  sublabel?: string;
  activeLabel?: string;
  color?: string;
  icon?: React.ReactNode;
  isActive?: boolean;
}

type ParseResult = { hours: number; minutes: number; seconds: number; total: number } | 'expired' | 'invalid';

function parseTimeRemaining(targetISO: string): ParseResult {
  const target = new Date(targetISO).getTime();
  if (!Number.isFinite(target)) return 'invalid';
  const diff = target - Date.now();
  if (diff <= 0) return 'expired';

  const hours = Math.floor(diff / 3600000);
  const minutes = Math.floor((diff % 3600000) / 60000);
  const seconds = Math.floor((diff % 60000) / 1000);

  return { hours, minutes, seconds, total: diff };
}

function TimeBlock({ value, unit, color }: { value: number; unit: string; color: string }) {
  return (
    <div className="flex flex-col items-center">
      <div
        className="relative rounded-xl border px-4 py-2 min-w-[64px] text-center font-mono"
        style={{
          borderColor: `${color}33`,
          background: `linear-gradient(135deg, ${color}08, ${color}15)`,
          boxShadow: `0 0 20px ${color}10`,
        }}
      >
        <span className="text-3xl sm:text-4xl font-bold tracking-tight" style={{ color }}>
          {String(value).padStart(2, '0')}
        </span>
      </div>
      <span className="text-[10px] uppercase tracking-widest mt-1.5 text-slate-500 font-medium">{unit}</span>
    </div>
  );
}

export default function CountdownTimer({
  targetISO,
  label,
  sublabel,
  activeLabel,
  color = '#3b82f6',
  icon,
  isActive = false,
}: CountdownTimerProps) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const interval = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, []);

  const remaining = useMemo(() => {
    if (!targetISO) return null;
    return parseTimeRemaining(targetISO);
  }, [targetISO, now]);

  if (isActive) {
    return (
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        className="relative rounded-2xl border overflow-hidden"
        style={{
          borderColor: `${color}40`,
          background: `linear-gradient(135deg, ${color}08, ${color}03)`,
        }}
      >
        <div className="absolute inset-0 overflow-hidden">
          <div
            className="absolute top-0 right-0 w-48 h-48 rounded-full blur-3xl opacity-20 -translate-y-1/2 translate-x-1/4"
            style={{ background: color }}
          />
        </div>
        <div className="relative px-6 py-5 flex items-center gap-4">
          <div className="flex items-center justify-center w-12 h-12 rounded-xl" style={{ background: `${color}20` }}>
            <Zap className="w-6 h-6" style={{ color }} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4" style={{ color }} />
              <span className="text-sm font-bold uppercase tracking-wider" style={{ color }}>
                {activeLabel || 'Active Now'}
              </span>
            </div>
            <p className="text-slate-400 text-xs mt-0.5">{sublabel}</p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span
              className="relative flex h-3 w-3"
            >
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75" style={{ background: color }} />
              <span className="relative inline-flex rounded-full h-3 w-3" style={{ background: color }} />
            </span>
            <span className="text-xs font-mono uppercase tracking-wider" style={{ color }}>Live</span>
          </div>
        </div>
      </motion.div>
    );
  }

  if (!remaining || remaining === 'invalid') {
    return (
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative rounded-2xl border border-amber-500/20 bg-gradient-to-br from-amber-500/5 to-amber-500/[0.02] px-6 py-5"
      >
        <div className="flex items-center gap-3">
          <AlertTriangle className="w-5 h-5 text-amber-400" />
          <span className="text-sm text-amber-300 font-medium">{label} — Waiting for schedule data...</span>
        </div>
      </motion.div>
    );
  }

  if (remaining === 'expired') {
    return (
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative rounded-2xl border border-slate-500/20 bg-gradient-to-br from-slate-500/5 to-slate-500/[0.02] px-6 py-5"
      >
        <div className="flex items-center gap-3">
          <CheckCircle2 className="w-5 h-5 text-slate-400" />
          <span className="text-sm text-slate-300 font-medium">{label} — Awaiting next cycle refresh...</span>
        </div>
      </motion.div>
    );
  }

  const urgencyPct = Math.max(0, 1 - remaining.total / 3600000);

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="relative rounded-2xl border overflow-hidden"
      style={{
        borderColor: `${color}25`,
        background: `linear-gradient(135deg, rgba(15,23,42,0.9), rgba(15,23,42,0.95))`,
      }}
    >
      <div className="absolute inset-0 overflow-hidden">
        <div
          className="absolute top-0 left-0 w-64 h-64 rounded-full blur-3xl -translate-x-1/2 -translate-y-1/2"
          style={{ background: color, opacity: 0.06 + urgencyPct * 0.08 }}
        />
        <div
          className="absolute bottom-0 right-0 w-48 h-48 rounded-full blur-3xl translate-x-1/4 translate-y-1/4"
          style={{ background: color, opacity: 0.04 }}
        />
      </div>

      <div className="relative px-6 py-5">
        <div className="flex items-center gap-3 mb-4">
          <div className="flex items-center justify-center w-10 h-10 rounded-lg" style={{ background: `${color}15` }}>
            {icon || <Clock className="w-5 h-5" style={{ color }} />}
          </div>
          <div>
            <h3 className="text-sm font-bold uppercase tracking-wider" style={{ color }}>{label}</h3>
            {sublabel && <p className="text-[11px] text-slate-500 mt-0.5">{sublabel}</p>}
          </div>
        </div>

        <div className="flex items-center justify-center gap-3 sm:gap-5">
          <TimeBlock value={remaining.hours} unit="Hours" color={color} />
          <span className="text-2xl font-light mt-[-18px]" style={{ color: `${color}60` }}>:</span>
          <TimeBlock value={remaining.minutes} unit="Min" color={color} />
          <span className="text-2xl font-light mt-[-18px]" style={{ color: `${color}60` }}>:</span>
          <TimeBlock value={remaining.seconds} unit="Sec" color={color} />
        </div>

        <div className="mt-4 w-full h-1 rounded-full overflow-hidden" style={{ background: `${color}15` }}>
          <motion.div
            className="h-full rounded-full"
            style={{ background: `linear-gradient(90deg, ${color}60, ${color})`, width: `${urgencyPct * 100}%` }}
            animate={{ width: `${urgencyPct * 100}%` }}
            transition={{ duration: 1 }}
          />
        </div>
      </div>
    </motion.div>
  );
}
