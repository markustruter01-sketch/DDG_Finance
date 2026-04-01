import { useState, useEffect } from "react";
import { Card, CardHeader, CardTitle, CardContent, Button } from "./ui";
import { useAlertStatus, useUpdateAlertConfig, useTestAlert, useFlushAlerts } from "@/hooks/use-trading";
import { Bell, Send, Loader2, CheckCircle2, AlertTriangle, MessageSquare } from "lucide-react";
import { useToast } from "@/hooks/use-toast";

const INTERVAL_OPTIONS = [
  { value: 5, label: "5 min" },
  { value: 15, label: "15 min" },
  { value: 30, label: "30 min" },
  { value: 60, label: "1 hr" },
  { value: 120, label: "2 hr" },
  { value: 360, label: "6 hr" },
  { value: 720, label: "12 hr" },
  { value: 1440, label: "24 hr" },
];

export function AlertSettingsPanel() {
  const { toast } = useToast();
  const { data: status, isLoading } = useAlertStatus();
  const updateConfig = useUpdateAlertConfig();
  const testAlert = useTestAlert();
  const flushAlerts = useFlushAlerts();

  const [interval, setInterval_] = useState(60);
  const [enabled, setEnabled] = useState(true);
  const [minPnl, setMinPnl] = useState(0);

  useEffect(() => {
    if (status?.config) {
      setInterval_(status.config.interval_minutes);
      setEnabled(status.config.enabled);
      setMinPnl(status.config.min_pnl_usd ?? 0);
    }
  }, [status?.config]);

  const tgOk = status?.telegram_configured ?? false;
  const dcOk = status?.discord_configured ?? false;
  const queueSize = status?.queue_size ?? 0;

  const handleSave = async () => {
    try {
      await updateConfig.mutateAsync({ interval_minutes: interval, enabled, min_pnl_usd: minPnl });
      toast({ title: "Alert config saved", description: `Interval: ${interval}min · Min P&L: $${minPnl}` });
    } catch (err: any) {
      toast({ variant: "destructive", title: "Save failed", description: err.message });
    }
  };

  const handleTest = async () => {
    try {
      const res = await testAlert.mutateAsync();
      toast({ title: "Test alert sent", description: res?.detail || "Check your Telegram/Discord" });
    } catch (err: any) {
      toast({ variant: "destructive", title: "Test failed", description: err?.response?.data?.detail || err.message });
    }
  };

  const handleFlush = async () => {
    try {
      const res = await flushAlerts.mutateAsync();
      toast({ title: "Queue flushed", description: res?.detail || `${queueSize} alerts dispatched` });
    } catch (err: any) {
      toast({ variant: "destructive", title: "Flush failed", description: err.message });
    }
  };

  if (isLoading) {
    return (
      <Card className="border-white/5 bg-slate-900/60">
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-white/5 bg-slate-900/60">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm flex items-center gap-2">
          <Bell className="h-4 w-4 text-amber-400" />
          Trade Alert Notifications
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <div className={`w-2 h-2 rounded-full ${tgOk ? "bg-green-400" : "bg-red-400/50"}`} />
            <span className="text-[10px] font-mono text-muted-foreground">Telegram</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className={`w-2 h-2 rounded-full ${dcOk ? "bg-green-400" : "bg-red-400/50"}`} />
            <span className="text-[10px] font-mono text-muted-foreground">Discord</span>
          </div>
          {queueSize > 0 && (
            <span className="ml-auto text-[10px] font-mono text-amber-400">
              {queueSize} queued
            </span>
          )}
        </div>

        {!tgOk && !dcOk && (
          <div className="rounded-lg bg-amber-500/5 border border-amber-500/10 px-3 py-2">
            <p className="text-[10px] text-amber-400/80 font-mono leading-relaxed">
              No channels configured. Add TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID or DISCORD_WEBHOOK_URL in Secrets.
            </p>
          </div>
        )}

        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-mono text-muted-foreground">Alerts Enabled</span>
            <button
              onClick={() => {
                setEnabled(!enabled);
                updateConfig.mutate({ enabled: !enabled });
              }}
              className={`relative w-9 h-5 rounded-full transition-colors ${enabled ? "bg-green-500/40" : "bg-slate-700"}`}
            >
              <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${enabled ? "left-[18px]" : "left-0.5"}`} />
            </button>
          </div>

          <div>
            <label className="text-[10px] font-mono text-muted-foreground/70 uppercase tracking-wider block mb-1.5">
              Digest Frequency
            </label>
            <div className="grid grid-cols-4 gap-1">
              {INTERVAL_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setInterval_(opt.value)}
                  className={`text-[9px] font-mono py-1.5 rounded border transition-colors ${
                    interval === opt.value
                      ? "bg-primary/20 text-primary border-primary/30"
                      : "bg-slate-800/50 text-muted-foreground border-white/5 hover:border-white/10"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-[10px] font-mono text-muted-foreground/70 uppercase tracking-wider block mb-1.5">
              Min P&L (USD)
            </label>
            <input
              type="number"
              value={minPnl}
              onChange={(e) => setMinPnl(Number(e.target.value))}
              className="w-full text-xs font-mono bg-slate-800/50 border border-white/5 rounded px-2.5 py-1.5 text-white focus:outline-none focus:border-primary/40"
              placeholder="0"
              min={0}
              step={1}
            />
          </div>
        </div>

        <div className="flex gap-2 pt-1">
          <Button
            onClick={handleSave}
            disabled={updateConfig.isPending}
            className="flex-1 text-[10px] h-7"
          >
            {updateConfig.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : "Save"}
          </Button>
          <Button
            onClick={handleTest}
            disabled={testAlert.isPending || (!tgOk && !dcOk)}
            variant="outline"
            className="text-[10px] h-7 px-3"
          >
            {testAlert.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <><Send className="h-3 w-3 mr-1" />Test</>}
          </Button>
          {queueSize > 0 && (
            <Button
              onClick={handleFlush}
              disabled={flushAlerts.isPending}
              variant="outline"
              className="text-[10px] h-7 px-3"
            >
              {flushAlerts.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : "Flush"}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
