import { useEconomicCalendar } from "@/hooks/use-trading";
import { cn } from "@/lib/utils";
import { Card, CardHeader, CardTitle, CardContent, Badge } from "@/components/ui";
import { AlertOctagon, Lock } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

export function BlackoutBanner() {
  const { data } = useEconomicCalendar();

  if (!data?.blackout?.active) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, height: 0 }}
        animate={{ opacity: 1, height: "auto" }}
        exit={{ opacity: 0, height: 0 }}
        className="w-full"
      >
        <div className="flex items-center gap-3 px-5 py-3 rounded-xl border border-red-500/30 bg-red-500/10 text-red-400">
          <motion.div animate={{ scale: [1, 1.2, 1] }} transition={{ duration: 1.5, repeat: Infinity }}>
            <Lock className="h-4 w-4" />
          </motion.div>
          <div className="flex-1">
            <span className="text-xs font-bold uppercase tracking-wide">BLACKOUT ACTIVE</span>
            <span className="text-[11px] ml-2 text-red-400/80">{data.blackout.event} — {data.blackout.event_time_et} ET</span>
          </div>
          <Badge variant="danger" className="text-[9px] px-1.5 py-0">TRADING PAUSED</Badge>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}

export function EconomicCalendarPanel() {
  const { data, isLoading } = useEconomicCalendar();

  return (
    <Card className="border-white/5">
      <CardHeader className="bg-slate-900/50 border-b border-white/5 py-4">
        <CardTitle className="flex items-center gap-2 text-sm">
          <AlertOctagon className="h-4 w-4 text-amber-400" /> Economic Calendar
          {data?.blackout?.active && (
            <Badge variant="danger" className="text-[9px] px-1.5 py-0 ml-1 animate-pulse">BLACKOUT</Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-5">
        {isLoading ? (
          <div className="text-xs text-muted-foreground italic">Loading calendar...</div>
        ) : !data?.upcoming_events?.length ? (
          <div className="text-xs text-muted-foreground italic">No upcoming high-impact events</div>
        ) : (
          <div className="space-y-2">
            {data.upcoming_events.slice(0, 6).map((ev, i) => (
              <div
                key={i}
                className={cn(
                  "flex items-center justify-between px-3 py-2 rounded-lg border text-xs",
                  ev.days_away === 0
                    ? "border-red-500/20 bg-red-500/5 text-red-400"
                    : ev.days_away <= 2
                    ? "border-amber-500/20 bg-amber-500/5 text-amber-400"
                    : "border-white/5 bg-slate-900/50 text-muted-foreground"
                )}
              >
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-white">{ev.name}</span>
                </div>
                <div className="flex items-center gap-3 text-[10px]">
                  <span>{ev.date} {ev.time_et} ET</span>
                  <Badge
                    variant={ev.days_away === 0 ? "danger" : ev.days_away <= 2 ? "warning" : "outline"}
                    className="text-[9px] px-1.5 py-0"
                  >
                    {ev.days_away === 0 ? "TODAY" : `${ev.days_away}d`}
                  </Badge>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
