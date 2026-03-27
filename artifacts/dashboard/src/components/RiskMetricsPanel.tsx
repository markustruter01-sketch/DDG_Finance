import { useRiskMetrics } from "@/hooks/use-trading";
import { cn } from "@/lib/utils";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui";
import { Shield } from "lucide-react";

function metricColor(label: string, val: number | null): string {
  if (val == null) return "text-muted-foreground";
  if (label === "Sharpe" || label === "Sortino" || label === "Calmar") {
    if (val >= 2) return "text-emerald-400";
    if (val >= 1) return "text-green-400";
    if (val >= 0) return "text-amber-400";
    return "text-red-400";
  }
  if (label === "Max DD") {
    if (val <= 5) return "text-green-400";
    if (val <= 10) return "text-amber-400";
    return "text-red-400";
  }
  if (label === "Volatility") {
    if (val <= 10) return "text-green-400";
    if (val <= 20) return "text-amber-400";
    return "text-red-400";
  }
  if (label === "Annual Ret") {
    return val >= 0 ? "text-green-400" : "text-red-400";
  }
  return "text-white";
}

export function RiskMetricsPanel() {
  const { data, isLoading } = useRiskMetrics();

  const metrics = [
    { label: "Sharpe", value: data?.sharpe_ratio, fmt: (v: number) => v.toFixed(2), suffix: "" },
    { label: "Sortino", value: data?.sortino_ratio, fmt: (v: number) => v.toFixed(2), suffix: "" },
    { label: "Max DD", value: data?.max_drawdown_pct, fmt: (v: number) => `-${v.toFixed(2)}`, suffix: "%" },
    { label: "Calmar", value: data?.calmar_ratio, fmt: (v: number) => v.toFixed(2), suffix: "" },
    { label: "Volatility", value: data?.volatility_annual_pct, fmt: (v: number) => v.toFixed(1), suffix: "%" },
    { label: "Annual Ret", value: data?.annualised_return_pct, fmt: (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(1)}`, suffix: "%" },
  ];

  return (
    <Card className="border-white/5">
      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-4">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Shield className="h-4 w-4 text-cyan-400" /> Risk Metrics
          {data?.period_days != null && (
            <span className="text-[10px] text-muted-foreground ml-auto font-normal">{data.period_days}d window · {data.data_points} pts</span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-5">
        {isLoading ? (
          <div className="text-xs text-muted-foreground italic">Loading risk metrics...</div>
        ) : (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {metrics.map((m) => (
                <div key={m.label} className="bg-slate-900/70 rounded-xl p-3 border border-white/5">
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1">{m.label}</div>
                  <div className={cn("text-xl font-mono font-bold", metricColor(m.label, m.value ?? null))}>
                    {m.value != null ? `${m.fmt(m.value)}${m.suffix}` : "—"}
                  </div>
                </div>
              ))}
            </div>
            {data?.message && (
              <div className="mt-3 text-[10px] text-muted-foreground/60 italic border-t border-white/5 pt-2">
                {data.message}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
