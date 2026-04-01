import { useState } from "react";
import { useFleetCommanderStatus, useFleetCommanderHistory, useTriggerFleetCommander } from "@/hooks/use-trading";
import { Shield, Play, Clock, AlertTriangle, CheckCircle2, XCircle, Zap, Bot, ChevronDown, ChevronUp } from "lucide-react";

const verdictConfig: Record<string, { color: string; bg: string; icon: typeof CheckCircle2 }> = {
  CLEAN: { color: "text-emerald-400", bg: "bg-emerald-500/10", icon: CheckCircle2 },
  CAUTION: { color: "text-amber-400", bg: "bg-amber-500/10", icon: AlertTriangle },
  HOLD: { color: "text-red-400", bg: "bg-red-500/10", icon: XCircle },
};

const botNames: Record<string, string> = {
  oracle: "Oracle #1",
  davy_jones: "Davy Jones #2",
  blackbeard: "Blackbeard #3",
  calypso: "Calypso #4",
  apex_predator: "Apex #5",
  navigator: "Navigator #6",
};

function formatTime(iso: string | undefined) {
  if (!iso) return "Never";
  try {
    return new Date(iso).toLocaleString("en-US", {
      month: "short", day: "numeric",
      hour: "numeric", minute: "2-digit",
      hour12: true, timeZoneName: "short",
    });
  } catch { return iso; }
}

function timeAgo(iso: string | undefined) {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ${mins % 60}m ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function FleetCommanderPanel() {
  const { data: status, isLoading } = useFleetCommanderStatus();
  const { data: historyData } = useFleetCommanderHistory();
  const triggerMutation = useTriggerFleetCommander();
  const [showHistory, setShowHistory] = useState(false);
  const [showSchedule, setShowSchedule] = useState(false);

  if (isLoading) {
    return (
      <div className="rounded-xl border border-white/5 bg-card p-6 animate-pulse">
        <div className="h-6 w-48 bg-white/10 rounded mb-4" />
        <div className="h-20 bg-white/5 rounded" />
      </div>
    );
  }

  const notRun = !status || status.status === "not_run";
  const verdict = status?.overall_verdict || "CLEAN";
  const vc = verdictConfig[verdict] || verdictConfig.CLEAN;
  const VerdictIcon = vc.icon;
  const tokenToday = status?.token_usage_today;
  const history = historyData?.history || [];
  const paramAdj = status?.kraken_param_adjustments || [];
  const vetoedTickers = status?.vetoed_tickers || [];
  const flags = status?.critique_flags || [];
  const schedule = status?.scheduled_runs || [];

  return (
    <div className="rounded-xl border border-white/5 bg-card overflow-hidden">
      <div className="px-6 py-4 border-b border-white/5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-indigo-500/10">
            <Shield className="w-5 h-5 text-indigo-400" />
          </div>
          <div>
            <h3 className="font-semibold text-white">Fleet Commander</h3>
            <p className="text-xs text-muted-foreground">Gemini AI audits all 6 bots, 6x daily</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {tokenToday && tokenToday.call_count > 0 && (
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-white/5 text-xs text-muted-foreground">
              <Zap className="w-3 h-3 text-amber-400" />
              <span>{(tokenToday.total_tokens / 1000).toFixed(1)}k tokens</span>
              <span className="text-white/30">|</span>
              <span>{tokenToday.call_count} calls today</span>
            </div>
          )}
          <button
            onClick={() => triggerMutation.mutate()}
            disabled={triggerMutation.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-500/20 hover:bg-indigo-500/30 text-indigo-300 text-xs font-medium transition-colors disabled:opacity-50"
          >
            <Play className="w-3 h-3" />
            {triggerMutation.isPending ? "Running..." : "Run Now"}
          </button>
        </div>
      </div>

      <div className="p-6">
        {notRun ? (
          <div className="text-center py-8 text-muted-foreground">
            <Shield className="w-10 h-10 mx-auto mb-3 opacity-30" />
            <p className="text-sm">Fleet Commander hasn't run yet</p>
            <p className="text-xs mt-1">Click "Run Now" to trigger the first audit, or it will start automatically on schedule</p>
          </div>
        ) : (
          <div className="space-y-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className={`p-2 rounded-lg ${vc.bg}`}>
                  <VerdictIcon className={`w-5 h-5 ${vc.color}`} />
                </div>
                <div>
                  <span className={`text-lg font-bold ${vc.color}`}>{verdict}</span>
                  <p className="text-xs text-muted-foreground flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    {timeAgo(status?.generated_at)} · {status?.elapsed_seconds}s
                  </p>
                </div>
              </div>
              {vetoedTickers.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {vetoedTickers.map(t => (
                    <span key={t} className="px-2 py-0.5 rounded bg-red-500/15 text-red-400 text-xs font-mono">{t}</span>
                  ))}
                </div>
              )}
            </div>

            {status?.critique_summary && (
              <p className="text-sm text-muted-foreground leading-relaxed border-l-2 border-indigo-500/30 pl-3">
                {status.critique_summary}
              </p>
            )}

            {status?.bot_verdicts && Object.keys(status.bot_verdicts).length > 0 && (
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
                {Object.entries(status.bot_verdicts).map(([botId, bv]) => {
                  const bvc = verdictConfig[bv] || verdictConfig.CLEAN;
                  const BotVIcon = bvc.icon;
                  return (
                    <div key={botId} className={`flex items-center gap-2 px-3 py-2 rounded-lg ${bvc.bg}`}>
                      <BotVIcon className={`w-3.5 h-3.5 ${bvc.color}`} />
                      <div>
                        <p className="text-xs font-medium text-white">{botNames[botId] || botId}</p>
                        <p className={`text-[10px] ${bvc.color}`}>{bv}</p>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {paramAdj.length > 0 && (
              <div>
                <h4 className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wider">Parameter Adjustments</h4>
                <div className="space-y-2">
                  {paramAdj.map((adj, i) => (
                    <div key={i} className="rounded-lg bg-white/5 p-3">
                      <div className="flex items-center gap-2 mb-1.5">
                        <Bot className="w-3.5 h-3.5 text-indigo-400" />
                        <span className="text-sm font-medium text-white">{botNames[adj.bot_id] || adj.bot_id}</span>
                      </div>
                      <div className="flex flex-wrap gap-2 mb-1.5">
                        {adj.ZSCORE_ENTRY != null && (
                          <span className="text-xs px-2 py-0.5 rounded bg-blue-500/10 text-blue-300 font-mono">ZE: {adj.ZSCORE_ENTRY.toFixed(2)}</span>
                        )}
                        {adj.ZSCORE_EXIT != null && (
                          <span className="text-xs px-2 py-0.5 rounded bg-blue-500/10 text-blue-300 font-mono">ZX: {adj.ZSCORE_EXIT.toFixed(2)}</span>
                        )}
                        {adj.STOP_LOSS_PCT != null && (
                          <span className="text-xs px-2 py-0.5 rounded bg-red-500/10 text-red-300 font-mono">SL: {(adj.STOP_LOSS_PCT * 100).toFixed(1)}%</span>
                        )}
                        {adj.TRAIL_PCT != null && (
                          <span className="text-xs px-2 py-0.5 rounded bg-amber-500/10 text-amber-300 font-mono">TR: {(adj.TRAIL_PCT * 100).toFixed(1)}%</span>
                        )}
                        {adj.MIN_NET_PROFIT_PCT != null && (
                          <span className="text-xs px-2 py-0.5 rounded bg-green-500/10 text-green-300 font-mono">MNP: {(adj.MIN_NET_PROFIT_PCT * 100).toFixed(1)}%</span>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground">{adj.reasoning}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {flags.length > 0 && (
              <div>
                <h4 className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wider">Critique Flags</h4>
                <ul className="space-y-1">
                  {flags.map((f, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs text-amber-300/80">
                      <AlertTriangle className="w-3 h-3 mt-0.5 flex-shrink-0" />
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="flex gap-2 pt-2 border-t border-white/5">
              <button
                onClick={() => setShowSchedule(!showSchedule)}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-white transition-colors"
              >
                <Clock className="w-3 h-3" />
                Schedule ({schedule.length} runs)
                {showSchedule ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
              </button>
              <button
                onClick={() => setShowHistory(!showHistory)}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-white transition-colors"
              >
                History ({history.length})
                {showHistory ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
              </button>
            </div>

            {showSchedule && schedule.length > 0 && (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {schedule.map(s => (
                  <div key={s.id} className="px-3 py-2 rounded-lg bg-white/5 text-xs">
                    <p className="text-white font-medium">{s.name.replace("Fleet Commander (", "").replace(")", "").replace(" ET", "")}</p>
                    <p className="text-muted-foreground mt-0.5">{s.next_run ? formatTime(s.next_run) : "—"}</p>
                  </div>
                ))}
              </div>
            )}

            {showHistory && history.length > 0 && (
              <div className="space-y-1.5 max-h-48 overflow-y-auto">
                {[...history].reverse().map((h, i) => {
                  const hvc = verdictConfig[h.overall_verdict] || verdictConfig.CLEAN;
                  return (
                    <div key={i} className="flex items-center justify-between px-3 py-1.5 rounded bg-white/5 text-xs">
                      <div className="flex items-center gap-2">
                        <span className={`font-medium ${hvc.color}`}>{h.overall_verdict}</span>
                        <span className="text-muted-foreground">{timeAgo(h.generated_at)}</span>
                      </div>
                      <div className="flex items-center gap-3 text-muted-foreground">
                        {h.kraken_param_adjustments?.length > 0 && (
                          <span>{h.kraken_param_adjustments.length} param changes</span>
                        )}
                        {h.token_usage?.totalTokenCount && (
                          <span>{(h.token_usage.totalTokenCount / 1000).toFixed(1)}k tok</span>
                        )}
                        <span>{h.elapsed_seconds}s</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
