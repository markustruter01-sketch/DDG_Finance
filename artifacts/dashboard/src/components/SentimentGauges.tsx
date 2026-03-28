import { useSentiment } from "@/hooks/use-trading";
import { cn } from "@/lib/utils";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui";
import { Flame } from "lucide-react";

function gaugeColor(value: number | null): string {
  if (value == null) return "text-muted-foreground";
  if (value <= 20) return "text-red-500";
  if (value <= 40) return "text-orange-400";
  if (value <= 60) return "text-yellow-400";
  if (value <= 80) return "text-green-400";
  return "text-emerald-400";
}

function gaugeBg(value: number | null): string {
  if (value == null) return "bg-slate-700";
  if (value <= 20) return "bg-red-500/30";
  if (value <= 40) return "bg-orange-500/30";
  if (value <= 60) return "bg-yellow-500/30";
  if (value <= 80) return "bg-green-500/30";
  return "bg-emerald-500/30";
}

function GaugeRing({ value, label, sublabel }: { value: number | null; label: string; sublabel: string }) {
  const pct = value ?? 0;
  const circumference = 2 * Math.PI * 40;
  const strokeDashoffset = circumference - (pct / 100) * circumference;

  return (
    <div className="flex flex-col items-center gap-1.5 md:gap-2">
      <div className="relative w-16 h-16 md:w-24 md:h-24">
        <svg className="w-16 h-16 md:w-24 md:h-24 -rotate-90" viewBox="0 0 100 100">
          <circle cx="50" cy="50" r="40" fill="none" stroke="currentColor" strokeWidth="6" className="text-slate-800" />
          <circle
            cx="50" cy="50" r="40" fill="none"
            strokeWidth="6"
            strokeLinecap="round"
            className={cn(gaugeColor(value))}
            style={{
              strokeDasharray: circumference,
              strokeDashoffset: value != null ? strokeDashoffset : circumference,
              transition: "stroke-dashoffset 1s ease-out",
              stroke: "currentColor",
            }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className={cn("text-sm md:text-xl font-mono font-bold", gaugeColor(value))}>
            {value != null ? value : "—"}
          </span>
        </div>
      </div>
      <div className="text-center">
        <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
        <div className={cn("text-xs font-semibold mt-0.5", gaugeColor(value))}>{sublabel}</div>
      </div>
    </div>
  );
}

export function SentimentGauges() {
  const { data, isLoading } = useSentiment();

  return (
    <Card className="border-white/5">
      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-4">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Flame className="h-4 w-4 text-orange-400" /> Fear &amp; Greed
        </CardTitle>
      </CardHeader>
      <CardContent className="p-5">
        {isLoading ? (
          <div className="text-xs text-muted-foreground italic">Loading sentiment...</div>
        ) : (
          <div className="flex justify-around items-start gap-4">
            <GaugeRing
              value={data?.crypto_fear_greed?.value ?? null}
              label="Crypto"
              sublabel={data?.crypto_fear_greed?.label ?? "N/A"}
            />
            <GaugeRing
              value={data?.market_fear_greed?.value ?? null}
              label="Market"
              sublabel={data?.market_fear_greed?.label ?? "N/A"}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
