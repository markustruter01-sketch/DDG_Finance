import { useCorrelation } from "@/hooks/use-trading";
import { cn } from "@/lib/utils";
import { Card, CardHeader, CardTitle, CardContent, Badge } from "@/components/ui";
import { Activity, AlertTriangle } from "lucide-react";

function corrColor(val: number): string {
  if (val >= 0.85) return "bg-red-500/80 text-white";
  if (val >= 0.6) return "bg-orange-500/60 text-white";
  if (val >= 0.3) return "bg-yellow-500/30 text-white";
  if (val >= -0.3) return "bg-slate-700/50 text-muted-foreground";
  if (val >= -0.6) return "bg-blue-500/30 text-white";
  return "bg-blue-500/60 text-white";
}

export function CorrelationMatrix() {
  const { data, isLoading } = useCorrelation();

  if (isLoading) {
    return (
      <Card className="border-white/5">
        <CardHeader className="bg-slate-900/50 border-b border-white/5 py-4">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Activity className="h-4 w-4 text-primary" /> Portfolio Correlation
          </CardTitle>
        </CardHeader>
        <CardContent className="p-5">
          <div className="text-xs text-muted-foreground italic">Loading correlation data...</div>
        </CardContent>
      </Card>
    );
  }

  if (!data || data.error || !data.tickers?.length) {
    return (
      <Card className="border-white/5">
        <CardHeader className="bg-slate-900/50 border-b border-white/5 py-4">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Activity className="h-4 w-4 text-primary" /> Portfolio Correlation
          </CardTitle>
        </CardHeader>
        <CardContent className="p-5">
          <div className="text-xs text-muted-foreground italic">{data?.error || "No correlation data available"}</div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-white/5">
      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-4">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Activity className="h-4 w-4 text-primary" /> Portfolio Correlation
          {data.warnings.length > 0 && (
            <Badge variant="danger" className="text-[9px] px-1.5 py-0 ml-1">
              {data.warnings.length} HIGH
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-5">
        <div className="overflow-x-auto">
          <table className="w-full text-[11px] font-mono">
            <thead>
              <tr>
                <th className="px-2 py-1 text-left text-muted-foreground" />
                {data.tickers.map((t) => (
                  <th key={t} className="px-2 py-1 text-center text-muted-foreground font-normal truncate max-w-[60px]">{t}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.tickers.map((row) => (
                <tr key={row}>
                  <td className="px-2 py-1 text-muted-foreground font-normal truncate max-w-[60px]">{row}</td>
                  {data.tickers.map((col) => {
                    const val = data.matrix[row]?.[col] ?? 0;
                    const isDiag = row === col;
                    return (
                      <td
                        key={col}
                        className={cn(
                          "px-2 py-1 text-center rounded-sm",
                          isDiag ? "bg-primary/20 text-primary font-bold" : corrColor(val)
                        )}
                        title={`${row} / ${col}: ${val.toFixed(3)}`}
                      >
                        {isDiag ? "1.00" : val.toFixed(2)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {data.warnings.length > 0 && (
          <div className="mt-3 space-y-1">
            {data.warnings.map((w, i) => (
              <div key={i} className="flex items-center gap-2 text-[10px] text-orange-400 bg-orange-500/10 rounded-lg px-3 py-1.5 border border-orange-500/20">
                <AlertTriangle className="h-3 w-3 shrink-0" />
                <span>{w.pair.join(" / ")} — r={w.correlation.toFixed(3)} — {w.risk}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
