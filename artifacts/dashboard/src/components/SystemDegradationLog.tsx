import { useState } from "react";
import { useDegradationLog, useDegradationReport, type DegradationEvent } from "@/hooks/use-trading";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui";
import { AlertTriangle, AlertCircle, ShieldAlert, Copy, Check, ChevronDown, ChevronUp, Bug, Clock, CheckCircle2 } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useToast } from "@/hooks/use-toast";

const SEV_CONFIG: Record<string, { color: string; bg: string; border: string; icon: React.ReactNode }> = {
  critical: { color: "text-red-400", bg: "bg-red-500/10", border: "border-red-500/20", icon: <ShieldAlert className="h-3 w-3" /> },
  error:    { color: "text-amber-400", bg: "bg-amber-500/10", border: "border-amber-500/20", icon: <AlertCircle className="h-3 w-3" /> },
  warning:  { color: "text-yellow-400", bg: "bg-yellow-500/10", border: "border-yellow-500/20", icon: <AlertTriangle className="h-3 w-3" /> },
};

function timeAgo(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  const secs = Math.floor(diff / 1000);
  if (secs < 120) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 120) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}h ago`;
}

function EventRow({ event }: { event: DegradationEvent }) {
  const [expanded, setExpanded] = useState(false);
  const sev = SEV_CONFIG[event.severity] || SEV_CONFIG.warning;
  const isOpen = !event.resolved_at;

  return (
    <div className={`border rounded-lg overflow-hidden ${sev.border} ${isOpen ? sev.bg : "bg-zinc-900/30"}`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-zinc-800/30 transition-colors text-left"
      >
        <span className={sev.color}>{sev.icon}</span>
        <span className={`text-[10px] font-bold uppercase ${sev.color}`}>{event.severity}</span>
        <span className="text-[11px] text-zinc-300 font-mono truncate flex-1">{event.component}/{event.error_type}</span>
        <span className="flex items-center gap-1.5 ml-auto shrink-0">
          {isOpen ? (
            <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-red-500/20 text-red-400 font-bold">OPEN</span>
          ) : (
            <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 font-bold flex items-center gap-0.5">
              <CheckCircle2 className="h-2.5 w-2.5" />RESOLVED
            </span>
          )}
          <span className="text-[10px] text-zinc-500 font-mono">{timeAgo(event.ts)}</span>
          {expanded ? <ChevronUp className="h-3 w-3 text-zinc-500" /> : <ChevronDown className="h-3 w-3 text-zinc-500" />}
        </span>
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
            <div className="px-3 pb-3 space-y-2 border-t border-zinc-800">
              <div className="mt-2">
                <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-0.5">Message</div>
                <p className="text-[12px] text-zinc-300 leading-relaxed">{event.message}</p>
              </div>
              {event.detail && (
                <div>
                  <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-0.5">Detail / Traceback</div>
                  <pre className="text-[10px] text-zinc-400 bg-zinc-950 rounded p-2 overflow-x-auto max-h-[200px] overflow-y-auto font-mono whitespace-pre-wrap break-words border border-zinc-800">
                    {event.detail}
                  </pre>
                </div>
              )}
              <div className="flex gap-4 text-[10px] text-zinc-500">
                <span className="flex items-center gap-1"><Clock className="h-3 w-3" /> {new Date(event.ts).toLocaleString()}</span>
                {event.resolved_at && (
                  <span className="flex items-center gap-1"><CheckCircle2 className="h-3 w-3 text-emerald-500" /> Resolved {timeAgo(event.resolved_at)}</span>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function SystemDegradationLog() {
  const { data, isLoading, isError } = useDegradationLog(48);
  const reportMutation = useDegradationReport(48);
  const [copied, setCopied] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const { toast } = useToast();

  const handleCopyReport = async () => {
    try {
      const report = await reportMutation.mutateAsync();
      try {
        await navigator.clipboard.writeText(report);
      } catch {
        const ta = document.createElement("textarea");
        ta.value = report;
        ta.style.cssText = "position:fixed;left:-9999px;top:-9999px";
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      setCopied(true);
      toast({ title: "Bug Report Copied", description: "Full diagnostic report copied to clipboard. Paste it to the AI for analysis." });
      setTimeout(() => setCopied(false), 3000);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      toast({ variant: "destructive", title: "Report Failed", description: `Could not generate bug report: ${msg.slice(0, 80)}` });
    }
  };

  if (isLoading) {
    return (
      <Card className="border-red-500/20 bg-gradient-to-br from-red-950/10 to-zinc-950">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Bug className="h-4 w-4 text-red-400" />
            <span>System Health Log</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="animate-pulse space-y-2">
            <div className="h-8 bg-zinc-800/50 rounded w-full" />
            <div className="h-8 bg-zinc-800/50 rounded w-3/4" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (isError || !data) {
    return (
      <Card className="border-red-500/20 bg-gradient-to-br from-red-950/10 to-zinc-950">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Bug className="h-4 w-4 text-red-400" />
            <span>System Health Log</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-zinc-500">Unable to load degradation data</p>
        </CardContent>
      </Card>
    );
  }

  const { events, stats } = data;
  const openEvents = events.filter(e => !e.resolved_at);
  const resolvedEvents = events.filter(e => e.resolved_at);
  const displayEvents = showAll ? events : events.slice(0, 10);

  const critCount = Object.values(stats).reduce((sum, s) => sum + (s.critical || 0), 0);
  const errCount = Object.values(stats).reduce((sum, s) => sum + (s.error || 0), 0);
  const warnCount = Object.values(stats).reduce((sum, s) => sum + (s.warning || 0), 0);

  return (
    <Card className="border-red-500/20 bg-gradient-to-br from-red-950/10 to-zinc-950">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Bug className="h-4 w-4 text-red-400" />
            <span>System Health Log</span>
            <span className="text-[10px] text-zinc-500 font-normal ml-1">Last 48h · Auto-tracked failures</span>
          </CardTitle>
          <button
            onClick={handleCopyReport}
            disabled={reportMutation.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11px] font-bold border transition-colors bg-red-500/10 border-red-500/30 text-red-400 hover:bg-red-500/20 disabled:opacity-50"
          >
            {reportMutation.isPending ? (
              <span className="animate-spin">⟳</span>
            ) : copied ? (
              <Check className="h-3.5 w-3.5 text-emerald-400" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
            {reportMutation.isPending ? "Generating..." : copied ? "Copied!" : "Copy Bug Report"}
          </button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <StatCard label="Open Issues" value={openEvents.length} color={openEvents.length > 0 ? "text-red-400" : "text-emerald-400"} icon={<AlertCircle className="h-4 w-4" />} />
          <StatCard label="Critical" value={critCount} color={critCount > 0 ? "text-red-400" : "text-zinc-500"} icon={<ShieldAlert className="h-4 w-4" />} />
          <StatCard label="Errors" value={errCount} color={errCount > 0 ? "text-amber-400" : "text-zinc-500"} icon={<AlertTriangle className="h-4 w-4" />} />
          <StatCard label="Resolved" value={resolvedEvents.length} color="text-emerald-400" icon={<CheckCircle2 className="h-4 w-4" />} />
        </div>

        {Object.keys(stats).length > 0 && (
          <div>
            <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1.5">Components Affected</div>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(stats).map(([comp, sevMap]) => {
                const worst = sevMap.critical ? "critical" : sevMap.error ? "error" : "warning";
                const cfg = SEV_CONFIG[worst];
                const total = (sevMap.critical || 0) + (sevMap.error || 0) + (sevMap.warning || 0);
                return (
                  <span key={comp} className={`inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded ${cfg.bg} ${cfg.color} border ${cfg.border} font-mono`}>
                    {cfg.icon} {comp} <span className="font-bold">×{total}</span>
                  </span>
                );
              })}
            </div>
          </div>
        )}

        <div>
          <div className="flex items-center justify-between mb-1.5">
            <div className="text-[10px] text-zinc-500 uppercase tracking-wider">
              Event Timeline {!showAll && events.length > 10 && `(showing ${displayEvents.length} of ${events.length})`}
            </div>
            {events.length > 10 && (
              <button onClick={() => setShowAll(!showAll)} className="text-[10px] text-red-400 hover:text-red-300 transition-colors">
                {showAll ? "Show Recent" : "Show All"}
              </button>
            )}
          </div>
          <div className="space-y-1 max-h-[350px] overflow-y-auto">
            {displayEvents.map((ev) => (
              <EventRow key={ev.id} event={ev} />
            ))}
            {events.length === 0 && (
              <div className="text-center py-6 text-zinc-500 text-sm flex flex-col items-center gap-1">
                <CheckCircle2 className="h-5 w-5 text-emerald-500" />
                No system failures in the last 48 hours
              </div>
            )}
          </div>
        </div>

        <div className="text-[10px] text-zinc-600 border-t border-zinc-800 pt-2">
          Click "Copy Bug Report" to get a full diagnostic with tracebacks, auto-heal logs, and live health snapshot — paste it to the AI for analysis.
        </div>
      </CardContent>
    </Card>
  );
}

function StatCard({ label, value, color, icon }: { label: string; value: number; color: string; icon: React.ReactNode }) {
  return (
    <div className="rounded-lg bg-zinc-900/60 border border-zinc-800 p-2.5 flex items-center gap-2.5">
      <span className={color}>{icon}</span>
      <div>
        <div className={`text-lg font-bold font-mono ${color}`}>{value}</div>
        <div className="text-[10px] text-zinc-500 uppercase tracking-wider">{label}</div>
      </div>
    </div>
  );
}
