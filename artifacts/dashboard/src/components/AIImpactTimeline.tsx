import { useState, useMemo } from "react";
import { useAIImpactTimeline, type AIIntervention } from "@/hooks/use-trading";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui";
import { formatCurrency } from "@/lib/utils";
import { Brain, TrendingUp, TrendingDown, Minus, ChevronDown, ChevronUp, AlertTriangle, Shield, ShieldAlert, Ban, Zap } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";

const VERDICT_COLORS: Record<string, string> = {
  CLEAN: "#4ade80",
  CAUTION: "#fb923c",
  HOLD: "#ef4444",
};

const VERDICT_ICONS: Record<string, React.ReactNode> = {
  CLEAN: <Shield className="h-3.5 w-3.5" />,
  CAUTION: <AlertTriangle className="h-3.5 w-3.5" />,
  HOLD: <ShieldAlert className="h-3.5 w-3.5" />,
};

function ImpactBadge({ impact }: { impact?: string }) {
  if (impact === "helped") return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/20 text-emerald-400"><TrendingUp className="h-3 w-3" />HELPED</span>;
  if (impact === "hurt") return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-red-500/20 text-red-400"><TrendingDown className="h-3 w-3" />HURT</span>;
  return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-zinc-500/20 text-zinc-400"><Minus className="h-3 w-3" />NEUTRAL</span>;
}

function InterventionDetail({ intervention }: { intervention: AIIntervention }) {
  const [expanded, setExpanded] = useState(false);
  const ts = new Date(intervention.ts);
  const verdict = intervention.overall_verdict || "CLEAN";
  const verdictColor = VERDICT_COLORS[verdict] || "#a78bfa";
  const paramChanges = intervention.param_changes || [];
  const vetoed = intervention.vetoed_tickers || [];

  return (
    <div className="border border-zinc-800 rounded-lg bg-zinc-900/50 overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-zinc-800/50 transition-colors text-left"
      >
        <div className="flex items-center gap-1.5" style={{ color: verdictColor }}>
          {VERDICT_ICONS[verdict]}
          <span className="text-[10px] font-bold uppercase">{verdict}</span>
        </div>
        <span className="text-[11px] text-zinc-400 font-mono">
          {ts.toLocaleDateString()} {ts.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </span>
        <div className="flex items-center gap-2 ml-auto">
          {paramChanges.length > 0 && (
            <span className="text-[10px] text-violet-400 font-mono">{paramChanges.length} param change{paramChanges.length > 1 ? 's' : ''}</span>
          )}
          {vetoed.length > 0 && (
            <span className="inline-flex items-center gap-1 text-[10px] text-amber-400"><Ban className="h-3 w-3" />{vetoed.length} vetoed</span>
          )}
          <ImpactBadge impact={intervention.impact} />
          {expanded ? <ChevronUp className="h-3.5 w-3.5 text-zinc-500" /> : <ChevronDown className="h-3.5 w-3.5 text-zinc-500" />}
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
            <div className="px-3 pb-3 space-y-3 border-t border-zinc-800">
              {intervention.critique_summary && (
                <div className="mt-2">
                  <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1">Fleet Assessment</div>
                  <p className="text-[12px] text-zinc-300 leading-relaxed">{intervention.critique_summary}</p>
                </div>
              )}

              {intervention.critique_flags?.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {intervention.critique_flags.map((flag, i) => (
                    <span key={i} className="text-[10px] px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">
                      {flag}
                    </span>
                  ))}
                </div>
              )}

              {paramChanges.length > 0 && (
                <div>
                  <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1.5">Parameter Changes</div>
                  <div className="space-y-2">
                    {paramChanges.map((pc, i) => (
                      <div key={i} className="rounded bg-zinc-950 border border-zinc-800 p-2">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-[11px] font-bold text-violet-400 uppercase">{pc.bot_id?.replace(/_/g, ' ')}</span>
                        </div>
                        <div className="flex flex-wrap gap-2 mb-1">
                          {pc.ZSCORE_ENTRY !== undefined && <ParamPill label="Z-Entry" value={pc.ZSCORE_ENTRY} />}
                          {pc.ZSCORE_EXIT !== undefined && <ParamPill label="Z-Exit" value={pc.ZSCORE_EXIT} />}
                          {pc.STOP_LOSS_PCT !== undefined && <ParamPill label="Stop Loss" value={`${(pc.STOP_LOSS_PCT * 100).toFixed(1)}%`} />}
                          {pc.TRAIL_PCT !== undefined && <ParamPill label="Trail" value={`${(pc.TRAIL_PCT * 100).toFixed(1)}%`} />}
                          {pc.MIN_NET_PROFIT_PCT !== undefined && <ParamPill label="Min Profit" value={`${(pc.MIN_NET_PROFIT_PCT * 100).toFixed(2)}%`} />}
                        </div>
                        <p className="text-[11px] text-zinc-400 leading-relaxed">{pc.reasoning}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {vetoed.length > 0 && (
                <div>
                  <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1">Vetoed Tickers</div>
                  <div className="flex flex-wrap gap-1.5">
                    {vetoed.map((t, i) => (
                      <span key={i} className="text-[10px] px-2 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/20 font-mono font-bold">{t}</span>
                    ))}
                  </div>
                </div>
              )}

              <div className="grid grid-cols-2 gap-2">
                <PerfCard label="24h Before" data={intervention.performance_before} />
                <PerfCard label="24h After" data={intervention.performance_after} />
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function ParamPill({ label, value }: { label: string; value: string | number }) {
  return (
    <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-300 border border-violet-500/20 font-mono">
      {label}: <span className="font-bold text-white">{value}</span>
    </span>
  );
}

function PerfCard({ label, data }: { label: string; data: { trades: number; wins: number; win_rate: number | null; net_pnl: number } | null }) {
  if (!data || data.trades === 0) {
    return (
      <div className="rounded bg-zinc-950 border border-zinc-800 p-2">
        <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1">{label}</div>
        <div className="text-[11px] text-zinc-600">No trades</div>
      </div>
    );
  }
  const pnlColor = data.net_pnl >= 0 ? "text-emerald-400" : "text-red-400";
  return (
    <div className="rounded bg-zinc-950 border border-zinc-800 p-2">
      <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1">{label}</div>
      <div className="flex items-baseline gap-2">
        <span className={`text-[13px] font-bold font-mono ${pnlColor}`}>{formatCurrency(data.net_pnl)}</span>
        <span className="text-[10px] text-zinc-400">{data.trades} trades</span>
      </div>
      <div className="text-[10px] text-zinc-400">
        {data.wins}W / {data.trades - data.wins}L
        {data.win_rate != null && <span className="ml-1">({data.win_rate}%)</span>}
      </div>
    </div>
  );
}

function ImpactChart({ data }: { data: ReturnType<typeof useAIImpactTimeline>["data"] }) {
  if (!data) return null;

  const chartData = useMemo(() => {
    return data.equity_curve.map((pt) => ({
      ts: new Date(pt.ts).getTime(),
      total: pt.total_equity,
      kraken: pt.kraken_equity,
      alpaca: pt.alpaca_equity,
    }));
  }, [data.equity_curve]);

  const interventionLines = useMemo(() => {
    return data.interventions.map((iv) => ({
      ts: new Date(iv.ts).getTime(),
      verdict: iv.overall_verdict,
      impact: iv.impact,
      paramCount: (iv.param_changes || []).length,
    }));
  }, [data.interventions]);

  if (chartData.length === 0) return null;

  const minEquity = Math.min(...chartData.map(d => d.total)) * 0.998;
  const maxEquity = Math.max(...chartData.map(d => d.total)) * 1.002;

  return (
    <div className="h-[280px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={chartData} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
          <defs>
            <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#a78bfa" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#a78bfa" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
          <XAxis
            dataKey="ts"
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={(v) => {
              const d = new Date(v);
              return `${d.getMonth() + 1}/${d.getDate()}`;
            }}
            tick={{ fill: "#71717a", fontSize: 10 }}
            stroke="#27272a"
          />
          <YAxis
            domain={[minEquity, maxEquity]}
            tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
            tick={{ fill: "#71717a", fontSize: 10 }}
            stroke="#27272a"
            width={55}
          />
          <Tooltip
            contentStyle={{ backgroundColor: "#18181b", border: "1px solid #3f3f46", borderRadius: "8px", fontSize: "11px" }}
            labelFormatter={(v) => new Date(v).toLocaleString()}
            formatter={(value: number) => [formatCurrency(value), ""]}
          />
          <Area
            type="monotone"
            dataKey="total"
            stroke="#a78bfa"
            strokeWidth={2}
            fill="url(#equityGradient)"
            name="Total Equity"
            dot={false}
          />
          {interventionLines.map((iv, i) => (
            <ReferenceLine
              key={i}
              x={iv.ts}
              stroke={iv.impact === "helped" ? "#4ade80" : iv.impact === "hurt" ? "#ef4444" : "#fb923c"}
              strokeDasharray="4 4"
              strokeWidth={1.5}
              strokeOpacity={0.7}
            />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function AIImpactTimeline() {
  const { data, isLoading, isError } = useAIImpactTimeline();
  const [showAll, setShowAll] = useState(false);

  if (isLoading) {
    return (
      <Card className="border-violet-500/20 bg-gradient-to-br from-violet-950/10 to-zinc-950">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Brain className="h-4 w-4 text-violet-400" />
            <span>AI Impact Timeline</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="animate-pulse space-y-3">
            <div className="h-[200px] bg-zinc-800/50 rounded" />
            <div className="h-8 bg-zinc-800/50 rounded w-1/2" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (isError || !data) {
    return (
      <Card className="border-violet-500/20 bg-gradient-to-br from-violet-950/10 to-zinc-950">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Brain className="h-4 w-4 text-violet-400" />
            <span>AI Impact Timeline</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-zinc-500">Unable to load AI impact data</p>
        </CardContent>
      </Card>
    );
  }

  const { summary, interventions } = data;
  const displayedInterventions = showAll ? interventions : interventions.slice(-8);

  return (
    <Card className="border-violet-500/20 bg-gradient-to-br from-violet-950/10 to-zinc-950">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Brain className="h-4 w-4 text-violet-400" />
            <span>AI Impact Timeline</span>
            <span className="text-[10px] text-zinc-500 font-normal ml-1">Claude Fleet Commander Interventions</span>
          </CardTitle>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <SummaryCard label="Total Interventions" value={summary.total_interventions} icon={<Zap className="h-4 w-4 text-violet-400" />} color="text-violet-400" />
          <SummaryCard label="Helped" value={summary.helped} icon={<TrendingUp className="h-4 w-4 text-emerald-400" />} color="text-emerald-400" />
          <SummaryCard label="Hurt" value={summary.hurt} icon={<TrendingDown className="h-4 w-4 text-red-400" />} color="text-red-400" />
          <SummaryCard label="Neutral / No Data" value={summary.neutral} icon={<Minus className="h-4 w-4 text-zinc-400" />} color="text-zinc-400" />
        </div>

        <div>
          <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-2">Equity Curve with AI Intervention Markers</div>
          <div className="flex items-center gap-4 mb-1 text-[10px] text-zinc-500">
            <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-emerald-400 inline-block" style={{ borderTop: "2px dashed #4ade80" }} /> Helped</span>
            <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-red-400 inline-block" style={{ borderTop: "2px dashed #ef4444" }} /> Hurt</span>
            <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-amber-400 inline-block" style={{ borderTop: "2px dashed #fb923c" }} /> Neutral</span>
            <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-violet-400 inline-block" /> Equity</span>
          </div>
          <ImpactChart data={data} />
        </div>

        <div>
          <div className="flex items-center justify-between mb-2">
            <div className="text-[10px] text-zinc-500 uppercase tracking-wider">
              Intervention Log {!showAll && interventions.length > 8 && `(showing last 8 of ${interventions.length})`}
            </div>
            {interventions.length > 8 && (
              <button
                onClick={() => setShowAll(!showAll)}
                className="text-[10px] text-violet-400 hover:text-violet-300 transition-colors"
              >
                {showAll ? "Show Recent" : "Show All"}
              </button>
            )}
          </div>
          <div className="space-y-1.5 max-h-[400px] overflow-y-auto">
            {[...displayedInterventions].reverse().map((iv) => (
              <InterventionDetail key={iv.id} intervention={iv} />
            ))}
            {interventions.length === 0 && (
              <div className="text-center py-6 text-zinc-500 text-sm">No AI interventions recorded yet</div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function SummaryCard({ label, value, icon, color }: { label: string; value: number; icon: React.ReactNode; color: string }) {
  return (
    <div className="rounded-lg bg-zinc-900/60 border border-zinc-800 p-2.5 flex items-center gap-2.5">
      {icon}
      <div>
        <div className={`text-lg font-bold font-mono ${color}`}>{value}</div>
        <div className="text-[10px] text-zinc-500 uppercase tracking-wider">{label}</div>
      </div>
    </div>
  );
}
