import { useState, useEffect } from "react";
import { useFleetCommanderStatus, useFleetCommanderHistory, useTriggerFleetCommander, useClaudeAuditStages, useClaudeStageResult, useTriggerClaudeStage, type AuditStageInfo } from "@/hooks/use-trading";
import { Shield, Play, Clock, AlertTriangle, CheckCircle2, XCircle, Zap, Bot, ChevronDown, ChevronUp, Brain, Cpu, FileText, ListChecks, AlertCircle, TrendingUp } from "lucide-react";
import { BotParameterSliders } from "./BotParameterSliders";

const verdictConfig: Record<string, { color: string; bg: string; icon: typeof CheckCircle2 }> = {
  CLEAN: { color: "text-emerald-400", bg: "bg-emerald-500/10", icon: CheckCircle2 },
  CAUTION: { color: "text-amber-400", bg: "bg-amber-500/10", icon: AlertTriangle },
  HOLD: { color: "text-red-400", bg: "bg-red-500/10", icon: XCircle },
};

const claudeVerdictConfig: Record<string, { color: string; bg: string; icon: typeof CheckCircle2; label: string }> = {
  HEALTHY: { color: "text-emerald-400", bg: "bg-emerald-500/10", icon: CheckCircle2, label: "Healthy" },
  DEGRADED: { color: "text-amber-400", bg: "bg-amber-500/10", icon: AlertTriangle, label: "Degraded" },
  CRITICAL: { color: "text-red-400", bg: "bg-red-500/10", icon: XCircle, label: "Critical" },
};

const claudeBotVerdictConfig: Record<string, { color: string; bg: string }> = {
  GOOD: { color: "text-emerald-400", bg: "bg-emerald-500/10" },
  WARNING: { color: "text-amber-400", bg: "bg-amber-500/10" },
  CRITICAL: { color: "text-red-400", bg: "bg-red-500/10" },
};

const claudeSeverityConfig: Record<string, { color: string; bg: string }> = {
  CRITICAL: { color: "text-red-400", bg: "bg-red-500/15" },
  HIGH: { color: "text-orange-400", bg: "bg-orange-500/15" },
  MEDIUM: { color: "text-amber-400", bg: "bg-amber-500/15" },
  LOW: { color: "text-blue-400", bg: "bg-blue-500/15" },
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

function formatCooldown(seconds: number): string {
  if (seconds <= 0) return "Ready";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function CollapsibleSection({ title, icon: Icon, children, defaultOpen = false, badge }: {
  title: string;
  icon: typeof CheckCircle2;
  children: React.ReactNode;
  defaultOpen?: boolean;
  badge?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-lg border border-white/5 overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-3 py-2.5 bg-white/3 hover:bg-white/5 transition-colors text-left"
      >
        <div className="flex items-center gap-2">
          <Icon className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-xs font-medium text-white">{title}</span>
          {badge && (
            <span className="px-1.5 py-0.5 rounded-full bg-white/10 text-xs text-muted-foreground">{badge}</span>
          )}
        </div>
        {open ? <ChevronUp className="w-3 h-3 text-muted-foreground" /> : <ChevronDown className="w-3 h-3 text-muted-foreground" />}
      </button>
      {open && <div className="p-3">{children}</div>}
    </div>
  );
}

const stageVerdictCfg: Record<string, { color: string; bg: string; dot: string; label: string }> = {
  PASS:            { color: "text-emerald-400", bg: "bg-emerald-500/10", dot: "bg-emerald-400", label: "Pass" },
  NEEDS_ATTENTION: { color: "text-amber-400",   bg: "bg-amber-500/10",   dot: "bg-amber-400",   label: "Attention" },
  CRITICAL:        { color: "text-red-400",      bg: "bg-red-500/10",     dot: "bg-red-400",     label: "Critical" },
  HEALTHY:         { color: "text-emerald-400",  bg: "bg-emerald-500/10", dot: "bg-emerald-400", label: "Healthy" },
  DEGRADED:        { color: "text-amber-400",    bg: "bg-amber-500/10",   dot: "bg-amber-400",   label: "Degraded" },
  failed:          { color: "text-red-400",      bg: "bg-red-500/10",     dot: "bg-red-500",     label: "Failed" },
};

function StageDot({ stage }: { stage: AuditStageInfo }) {
  const isRunning = stage.run_state.in_progress;
  const verdict = stage.last_result?.stage_verdict || (stage.last_result?.status === "failed" ? "failed" : null);
  const cfg = verdict ? (stageVerdictCfg[verdict] || null) : null;
  return (
    <div
      className={`w-2 h-2 rounded-full flex-shrink-0 ${
        isRunning ? "bg-violet-400 animate-pulse" :
        cfg ? cfg.dot :
        stage.last_result ? "bg-muted-foreground/40" : "bg-white/10"
      }`}
    />
  );
}

function StageIssueList({ title, icon: Icon, issues, severity }: {
  title: string;
  icon: typeof CheckCircle2;
  issues: { file: string; function?: string; issue: string; recommendation: string }[];
  severity: string;
}) {
  const sev = claudeSeverityConfig[severity] || claudeSeverityConfig.LOW;
  return (
    <CollapsibleSection title={title} icon={Icon} badge={String(issues.length)}>
      <div className="space-y-2 max-h-72 overflow-y-auto">
        {issues.map((iss, i) => (
          <div key={i} className={`rounded-lg p-2.5 ${sev.bg}`}>
            <div className="flex items-center gap-1.5 mb-1 flex-wrap">
              <span className={`text-[10px] font-bold ${sev.color}`}>{severity}</span>
              <span className="text-[10px] font-mono text-white/70">{iss.file}</span>
              {iss.function && <span className="text-[10px] text-muted-foreground">· {iss.function}</span>}
            </div>
            <p className="text-xs text-white/90">{iss.issue}</p>
            {iss.recommendation && (
              <p className="text-[11px] text-muted-foreground mt-1 pt-1 border-t border-white/5">
                Fix: {iss.recommendation}
              </p>
            )}
          </div>
        ))}
      </div>
    </CollapsibleSection>
  );
}

function ClaudeReviewSection() {
  const { data: stagesData } = useClaudeAuditStages();
  const [selectedId, setSelectedId] = useState("s1_analysis");
  const [, setTick] = useState(0);
  const { data: fullResult } = useClaudeStageResult(selectedId);
  const triggerMutation = useTriggerClaudeStage();

  const stages = stagesData?.stages ?? [];
  const selected = stages.find(s => s.id === selectedId);

  useEffect(() => {
    const t = setInterval(() => setTick(n => n + 1), 1000);
    return () => clearInterval(t);
  }, []);

  const isRunning = selected?.run_state.in_progress ?? false;
  const anyRunning = stages.some(s => s.run_state.in_progress);

  const nextAvailable = selected?.cooldown.next_available;
  const secondsRemaining = nextAvailable
    ? Math.max(0, Math.floor((new Date(nextAvailable).getTime() - Date.now()) / 1000))
    : 0;
  const isLocked = secondsRemaining > 0 && !isRunning;
  const cooldownDisplay = secondsRemaining > 0 ? formatCooldown(secondsRemaining) : "Ready";

  const hasResult = !!fullResult && fullResult.status === "ok";
  const verdict = fullResult?.stage_verdict ?? fullResult?.system_health_verdict;
  const vCfg = verdict ? (stageVerdictCfg[verdict] || null) : null;

  return (
    <div className="rounded-xl border border-violet-500/20 bg-violet-500/5 overflow-hidden mt-4">
      {/* Header */}
      <div className="px-6 py-4 border-b border-violet-500/10 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-violet-500/15">
            <Brain className="w-5 h-5 text-violet-400" />
          </div>
          <div>
            <h3 className="font-semibold text-white">Claude Deep Audit</h3>
            <p className="text-xs text-muted-foreground">8-stage manual audit · claude-3-5-sonnet · complete coverage</p>
          </div>
        </div>
      </div>

      <div className="p-5 space-y-4">
        {/* Stage overview strip */}
        <div className="grid grid-cols-4 gap-1.5">
          {stages.map(stage => {
            const sv = stage.last_result?.stage_verdict ?? (stage.last_result?.status === "failed" ? "failed" : null);
            const scfg = sv ? (stageVerdictCfg[sv] || null) : null;
            const running = stage.run_state.in_progress;
            return (
              <button
                key={stage.id}
                onClick={() => setSelectedId(stage.id)}
                className={`flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-left transition-colors text-[10px] border ${
                  selectedId === stage.id
                    ? "border-violet-500/50 bg-violet-500/15 text-white"
                    : "border-white/5 bg-white/3 hover:bg-white/5 text-muted-foreground"
                }`}
              >
                <StageDot stage={stage} />
                <span className="truncate leading-tight">
                  {stage.order}. {stage.name.replace(/^Stage \d+: /, "")}
                </span>
                {scfg && !running && (
                  <span className={`ml-auto text-[9px] font-bold ${scfg.color} flex-shrink-0`}>
                    {scfg.label.slice(0, 4).toUpperCase()}
                  </span>
                )}
                {running && <span className="ml-auto text-[9px] text-violet-400 flex-shrink-0">RUN</span>}
              </button>
            );
          })}
        </div>

        {/* Selected stage detail */}
        {selected && (
          <div className="rounded-lg border border-white/8 bg-white/3 overflow-hidden">
            {/* Stage header row */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
              <div className="flex-1 min-w-0 mr-3">
                <p className="text-sm font-medium text-white">{selected.name}</p>
                <p className="text-[11px] text-muted-foreground mt-0.5 leading-relaxed">{selected.description}</p>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                {anyRunning && !isRunning && (
                  <span className="text-[10px] text-muted-foreground">Another stage running…</span>
                )}
                {fullResult?.total_tokens && (
                  <div className="flex items-center gap-1 px-2 py-1 rounded bg-white/5 text-[10px] text-muted-foreground">
                    <Zap className="w-2.5 h-2.5 text-violet-400" />
                    {((fullResult.total_tokens) / 1000).toFixed(0)}k tok
                    {fullResult.estimated_cost_usd != null && ` · $${fullResult.estimated_cost_usd.toFixed(3)}`}
                  </div>
                )}
                <button
                  onClick={() => triggerMutation.mutate(selected.id)}
                  disabled={isRunning || isLocked || anyRunning || triggerMutation.isPending}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-50 ${
                    isLocked
                      ? "bg-white/5 text-muted-foreground cursor-not-allowed"
                      : "bg-violet-500/20 hover:bg-violet-500/30 text-violet-300"
                  }`}
                >
                  <Play className="w-3 h-3" />
                  {isRunning ? "Running…" : isLocked ? `Cooldown: ${cooldownDisplay}` : "Run Audit"}
                </button>
              </div>
            </div>

            <div className="p-4 space-y-3">
              {/* Running indicator */}
              {isRunning && (
                <div className="flex items-center gap-3 py-2.5 px-3 rounded-lg bg-violet-500/10 border border-violet-500/20">
                  <div className="w-2 h-2 rounded-full bg-violet-400 animate-pulse" />
                  <div>
                    <p className="text-xs text-white font-medium">Audit in progress…</p>
                    <p className="text-[11px] text-muted-foreground mt-0.5">
                      Started {selected.run_state.started_at ? timeAgo(selected.run_state.started_at) : ""}
                    </p>
                  </div>
                </div>
              )}

              {/* Error */}
              {selected.run_state.error && !isRunning && (
                <div className="flex items-start gap-2 py-2.5 px-3 rounded-lg bg-red-500/10 border border-red-500/20">
                  <XCircle className="w-3.5 h-3.5 text-red-400 mt-0.5 flex-shrink-0" />
                  <div>
                    <p className="text-xs text-red-400 font-medium">Last run failed</p>
                    <p className="text-[11px] text-muted-foreground mt-0.5">{selected.run_state.error}</p>
                  </div>
                </div>
              )}

              {/* Not run yet */}
              {!hasResult && !isRunning && !selected.run_state.error && (
                <div className="text-center py-5 text-muted-foreground">
                  <Brain className="w-8 h-8 mx-auto mb-2 opacity-20" />
                  <p className="text-xs">{selected.name} hasn't run yet</p>
                  <p className="text-[11px] mt-1 opacity-60">
                    {selected.is_synthesis
                      ? "Run all code stages first, then trigger this to produce the master verdict."
                      : "Press 'Run Audit' to start. A 23-hour cooldown applies after each run."}
                  </p>
                </div>
              )}

              {/* Result for code stages (1-7) */}
              {hasResult && fullResult && !selected.is_synthesis && (
                <div className="space-y-3">
                  {/* Verdict + meta */}
                  <div className="flex items-center gap-3 flex-wrap">
                    {vCfg && (
                      <div className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg ${vCfg.bg}`}>
                        <div className={`w-2 h-2 rounded-full ${vCfg.dot}`} />
                        <span className={`text-xs font-bold ${vCfg.color}`}>{vCfg.label.toUpperCase()}</span>
                      </div>
                    )}
                    <p className="text-[11px] text-muted-foreground flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {timeAgo(fullResult.generated_at)} · {fullResult.elapsed_seconds}s
                    </p>
                    <div className="flex gap-2 text-[10px]">
                      {(fullResult.critical_issues?.length ?? 0) > 0 && (
                        <span className="px-1.5 py-0.5 rounded bg-red-500/15 text-red-400 font-medium">
                          {fullResult.critical_issues!.length} critical
                        </span>
                      )}
                      {(fullResult.high_issues?.length ?? 0) > 0 && (
                        <span className="px-1.5 py-0.5 rounded bg-orange-500/15 text-orange-400 font-medium">
                          {fullResult.high_issues!.length} high
                        </span>
                      )}
                      {(fullResult.medium_issues?.length ?? 0) > 0 && (
                        <span className="px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 font-medium">
                          {fullResult.medium_issues!.length} medium
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Summary */}
                  {fullResult.summary && (
                    <p className="text-xs text-muted-foreground leading-relaxed border-l-2 border-violet-500/30 pl-3">
                      {fullResult.summary}
                    </p>
                  )}

                  {/* Issues */}
                  {(fullResult.critical_issues?.length ?? 0) > 0 && (
                    <StageIssueList
                      title="Critical Issues"
                      icon={XCircle}
                      issues={fullResult.critical_issues!}
                      severity="CRITICAL"
                    />
                  )}
                  {(fullResult.high_issues?.length ?? 0) > 0 && (
                    <StageIssueList
                      title="High Issues"
                      icon={AlertTriangle}
                      issues={fullResult.high_issues!}
                      severity="HIGH"
                    />
                  )}
                  {(fullResult.medium_issues?.length ?? 0) > 0 && (
                    <StageIssueList
                      title="Medium Issues"
                      icon={AlertCircle}
                      issues={fullResult.medium_issues!}
                      severity="MEDIUM"
                    />
                  )}

                  {/* Parameter concerns */}
                  {(fullResult.parameter_concerns?.length ?? 0) > 0 && (
                    <CollapsibleSection title="Parameter Concerns" icon={TrendingUp} badge={String(fullResult.parameter_concerns!.length)}>
                      <div className="space-y-2">
                        {fullResult.parameter_concerns!.map((p, i) => (
                          <div key={i} className="rounded-lg p-2.5 bg-white/5">
                            <p className="text-[10px] font-mono text-white/60 mb-0.5">{p.file}</p>
                            <p className="text-xs text-white/90">{p.issue}</p>
                            {p.recommendation && (
                              <p className="text-[11px] text-muted-foreground mt-1">Fix: {p.recommendation}</p>
                            )}
                          </div>
                        ))}
                      </div>
                    </CollapsibleSection>
                  )}

                  {/* Key risks */}
                  {(fullResult.key_risks?.length ?? 0) > 0 && (
                    <CollapsibleSection title="Key Risks" icon={AlertTriangle} badge={String(fullResult.key_risks!.length)}>
                      <ul className="space-y-1.5">
                        {fullResult.key_risks!.map((r, i) => (
                          <li key={i} className="flex items-start gap-2 text-xs text-amber-300/80">
                            <AlertTriangle className="w-3 h-3 mt-0.5 flex-shrink-0" />
                            {r}
                          </li>
                        ))}
                      </ul>
                    </CollapsibleSection>
                  )}

                  {/* Positive notes */}
                  {(fullResult.positive_notes?.length ?? 0) > 0 && (
                    <CollapsibleSection title="Positive Notes" icon={CheckCircle2} badge={String(fullResult.positive_notes!.length)}>
                      <ul className="space-y-1.5">
                        {fullResult.positive_notes!.map((n, i) => (
                          <li key={i} className="flex items-start gap-2 text-xs text-emerald-300/80">
                            <CheckCircle2 className="w-3 h-3 mt-0.5 flex-shrink-0" />
                            {n}
                          </li>
                        ))}
                      </ul>
                    </CollapsibleSection>
                  )}
                </div>
              )}

              {/* Result for synthesis stage (8) */}
              {hasResult && fullResult && selected.is_synthesis && (
                <div className="space-y-3">
                  <div className="flex items-center gap-3 flex-wrap">
                    {vCfg && (
                      <div className={`flex items-center gap-2 px-3 py-2 rounded-lg ${vCfg.bg}`}>
                        <div className={`w-2 h-2 rounded-full ${vCfg.dot}`} />
                        <span className={`text-sm font-bold ${vCfg.color}`}>{vCfg.label}</span>
                      </div>
                    )}
                    <p className="text-[11px] text-muted-foreground flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {timeAgo(fullResult.generated_at)} · {fullResult.elapsed_seconds}s
                    </p>
                  </div>

                  {fullResult.health_summary && (
                    <p className="text-xs text-muted-foreground leading-relaxed border-l-2 border-violet-500/30 pl-3">
                      {fullResult.health_summary}
                    </p>
                  )}

                  {fullResult.per_bot_assessment && fullResult.per_bot_assessment.length > 0 && (
                    <CollapsibleSection title="Per-Bot Assessment" icon={Bot} defaultOpen badge={String(fullResult.per_bot_assessment.length)}>
                      <div className="space-y-2">
                        {fullResult.per_bot_assessment.map((bot) => {
                          const bvc = claudeBotVerdictConfig[bot.verdict] || claudeBotVerdictConfig.GOOD;
                          return (
                            <div key={bot.bot_id} className={`rounded-lg p-3 ${bvc.bg}`}>
                              <div className="flex items-center justify-between mb-1">
                                <span className="text-xs font-medium text-white">{botNames[bot.bot_id] || bot.bot_id}</span>
                                <span className={`text-xs font-bold ${bvc.color}`}>{bot.verdict}</span>
                              </div>
                              <div className="space-y-0.5 text-[11px] text-muted-foreground">
                                {bot.win_rate_assessment && <p><span className="text-white/50">Win rate:</span> {bot.win_rate_assessment}</p>}
                                {bot.pnl_assessment && <p><span className="text-white/50">P&L:</span> {bot.pnl_assessment}</p>}
                                {bot.flags?.map((f, i) => (
                                  <p key={i} className="flex items-start gap-1 text-amber-400/80">
                                    <AlertTriangle className="w-3 h-3 mt-0.5 flex-shrink-0" /> {f}
                                  </p>
                                ))}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </CollapsibleSection>
                  )}

                  {fullResult.code_issues && fullResult.code_issues.length > 0 && (
                    <CollapsibleSection title="Code Issues" icon={AlertCircle} badge={String(fullResult.code_issues.length)}>
                      <div className="space-y-2 max-h-72 overflow-y-auto">
                        {fullResult.code_issues.map((issue, i) => {
                          const sev = claudeSeverityConfig[issue.severity] || claudeSeverityConfig.LOW;
                          return (
                            <div key={i} className={`rounded-lg p-2.5 ${sev.bg}`}>
                              <div className="flex items-center gap-1.5 mb-1 flex-wrap">
                                <span className={`text-[10px] font-bold ${sev.color}`}>{issue.severity}</span>
                                <span className="text-[10px] font-mono text-white/70">{issue.file}</span>
                                {issue.function && <span className="text-[10px] text-muted-foreground">· {issue.function}</span>}
                              </div>
                              <p className="text-xs text-white/90">{issue.issue}</p>
                              {issue.recommendation && (
                                <p className="text-[11px] text-muted-foreground mt-1 pt-1 border-t border-white/5">
                                  Fix: {issue.recommendation}
                                </p>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </CollapsibleSection>
                  )}

                  {fullResult.action_items && fullResult.action_items.length > 0 && (
                    <CollapsibleSection title="Action Items" icon={ListChecks} defaultOpen badge={String(fullResult.action_items.length)}>
                      <div className="space-y-2">
                        {fullResult.action_items.map((item, i) => (
                          <div key={i} className="flex items-start gap-3 p-2.5 rounded-lg bg-white/5">
                            <span className="text-xs font-bold text-violet-400 w-5 text-center flex-shrink-0">{item.priority}</span>
                            <div className="flex-1 min-w-0">
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/10 text-muted-foreground">{item.category}</span>
                              <p className="text-xs text-white mt-1">{item.action}</p>
                              {item.impact && <p className="text-[11px] text-muted-foreground mt-0.5">{item.impact}</p>}
                            </div>
                          </div>
                        ))}
                      </div>
                    </CollapsibleSection>
                  )}

                  {fullResult.parameter_recommendations && fullResult.parameter_recommendations.length > 0 && (
                    <CollapsibleSection title="Parameter Recommendations" icon={TrendingUp} badge={String(fullResult.parameter_recommendations.length)}>
                      <div className="space-y-2">
                        {fullResult.parameter_recommendations.map((rec, i) => (
                          <div key={i} className="p-2.5 rounded-lg bg-white/5">
                            <div className="flex items-center gap-2 mb-1 flex-wrap">
                              <span className="text-xs font-medium text-white">{botNames[rec.bot_id] || rec.bot_id}</span>
                              <span className="text-xs font-mono text-violet-300">{rec.parameter}</span>
                              <span className="text-xs text-muted-foreground">{rec.current_value} → {rec.recommended_value}</span>
                            </div>
                            <p className="text-[11px] text-muted-foreground">{rec.reasoning}</p>
                          </div>
                        ))}
                      </div>
                    </CollapsibleSection>
                  )}

                  {fullResult.cross_bot_risks && fullResult.cross_bot_risks.length > 0 && (
                    <CollapsibleSection title="Cross-Bot Risks" icon={AlertTriangle} badge={String(fullResult.cross_bot_risks.length)}>
                      <ul className="space-y-1.5">
                        {fullResult.cross_bot_risks.map((r, i) => (
                          <li key={i} className="flex items-start gap-2 text-xs text-amber-300/80">
                            <AlertTriangle className="w-3 h-3 mt-0.5 flex-shrink-0" /> {r}
                          </li>
                        ))}
                      </ul>
                    </CollapsibleSection>
                  )}

                  {fullResult.stage_key_findings && Object.keys(fullResult.stage_key_findings).length > 0 && (
                    <CollapsibleSection title="Stage Key Findings" icon={FileText} badge={String(Object.keys(fullResult.stage_key_findings).length)}>
                      <div className="space-y-2">
                        {Object.entries(fullResult.stage_key_findings).map(([stageName, findings]) => (
                          <div key={stageName}>
                            <p className="text-[10px] font-medium text-violet-400 mb-1">{stageName}</p>
                            <ul className="space-y-0.5">
                              {findings.map((f, i) => (
                                <li key={i} className="text-[11px] text-muted-foreground flex items-start gap-1.5">
                                  <span className="text-white/30 flex-shrink-0">·</span>{f}
                                </li>
                              ))}
                            </ul>
                          </div>
                        ))}
                      </div>
                    </CollapsibleSection>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
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
    <div className="space-y-0">
      <div className="rounded-xl border border-white/5 bg-card overflow-hidden">
        <div className="px-6 py-4 border-b border-white/5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-indigo-500/10">
              <Shield className="w-5 h-5 text-indigo-400" />
            </div>
            <div>
              <h3 className="font-semibold text-white">Fleet Commander</h3>
              <p className="text-xs text-muted-foreground">Gemini AI audits all 8 bots, 6x daily</p>
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
            <div className="space-y-5">
              <div className="text-center py-4 text-muted-foreground">
                <Shield className="w-10 h-10 mx-auto mb-3 opacity-30" />
                <p className="text-sm">Fleet Commander hasn't run yet</p>
                <p className="text-xs mt-1">Click "Run Now" to trigger the first audit, or it will start automatically on schedule</p>
              </div>
              <BotParameterSliders />
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

              <BotParameterSliders />

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

      <ClaudeReviewSection />
    </div>
  );
}
