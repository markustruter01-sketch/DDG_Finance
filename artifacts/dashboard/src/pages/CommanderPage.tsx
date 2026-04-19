import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import ReactMarkdown from "react-markdown";
import {
  Send, Shield, Swords, Target, RotateCcw, Pause, Zap,
  Bot, User, Loader2, Check, X, ChevronDown, ChevronUp, AlertTriangle, ArrowRight, Info,
  ScanSearch, Copy, ClipboardCheck, Brain, Play, CheckCircle2, XCircle, Clock,
} from "lucide-react";
import { useFleetParams, useClaudeAuditStages, useTriggerClaudeStage, type AuditStageInfo, type BotParamBounds, type BotParamData } from "@/hooks/use-trading";

const BASE = import.meta.env.VITE_API_BASE_URL || "/trading-api";


interface ChatMessage {
  id: string;
  ts: string;
  role: "user" | "assistant";
  content: string;
  source: string;
  metadata: Record<string, unknown>;
}

interface Recommendation {
  bot_id: string;
  params: Record<string, number>;
  reasoning: string;
}

const QUICK_ACTIONS = [
  { id: "conservative", label: "Conservative", icon: Shield, color: "#3b82f6", desc: "Tighten entries & stops" },
  { id: "aggressive", label: "Aggressive", icon: Swords, color: "#ef4444", desc: "Loosen entries & stops" },
  { id: "tighten_stops", label: "Tighten Stops", icon: Target, color: "#f59e0b", desc: "Lower stop-loss levels" },
  { id: "best_params", label: "Best Params", icon: Zap, color: "#10b981", desc: "Copy winning bot's params" },
  { id: "pause_losing", label: "Pause Losers", icon: Pause, color: "#8b5cf6", desc: "Pause bots with negative PnL" },
  { id: "reset_defaults", label: "Reset Defaults", icon: RotateCcw, color: "#6b7280", desc: "Step toward factory params" },
];

function parseAuditFindings(text: string): { number: number; category: string; title: string; prompt: string }[] {
  const findings: { number: number; category: string; title: string; prompt: string }[] = [];
  const findingRegex = /\*{1,2}#(\d+)\s*[—–\-]\s*\[([^\]]+)\]\s*([^\n*]+?)\*{0,2}\s*\n/g;
  let match;
  while ((match = findingRegex.exec(text)) !== null) {
    const num = parseInt(match[1], 10);
    const category = match[2].trim();
    const title = match[3].replace(/\*+/g, "").trim();
    const afterHeader = text.slice(match.index + match[0].length);
    const promptMatch = afterHeader.match(/^[\s\n]*>\s*"([\s\S]*?)"\s*(?:\n|$)/);
    let prompt = "";
    if (promptMatch) {
      prompt = promptMatch[1].replace(/\s+/g, " ").trim();
    } else {
      const promptFallback = afterHeader.match(/^[\s\n]*>\s*([\s\S]*?)(?:\n\n|$)/);
      if (promptFallback) {
        prompt = promptFallback[1].replace(/^["']|["']$/g, "").replace(/\s+/g, " ").trim();
      }
    }
    findings.push({ number: num, category, title, prompt });
  }
  return findings;
}

function AuditFindingCard({ finding }: { finding: { number: number; category: string; title: string; prompt: string } }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    if (!finding.prompt) return;
    navigator.clipboard.writeText(finding.prompt).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const categoryColors: Record<string, string> = {
    Security: "text-red-400 bg-red-500/10 border-red-500/30",
    Performance: "text-amber-400 bg-amber-500/10 border-amber-500/30",
    Bug: "text-orange-400 bg-orange-500/10 border-orange-500/30",
    Architecture: "text-blue-400 bg-blue-500/10 border-blue-500/30",
    "Error Handling": "text-purple-400 bg-purple-500/10 border-purple-500/30",
    "Code Quality": "text-slate-400 bg-slate-500/10 border-slate-500/30",
    Testing: "text-teal-400 bg-teal-500/10 border-teal-500/30",
  };

  const catStyle = categoryColors[finding.category] || "text-slate-400 bg-slate-500/10 border-slate-500/30";

  return (
    <div className="rounded-lg border border-white/[0.07] bg-slate-900/60 p-3 mb-2">
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[10px] font-mono text-slate-500">#{finding.number}</span>
          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded border ${catStyle}`}>
            {finding.category}
          </span>
          <span className="text-xs text-slate-200 font-medium">{finding.title}</span>
        </div>
      </div>
      {finding.prompt && (
        <div className="mt-1.5 rounded-md bg-slate-800/60 border border-white/[0.05] p-2.5 flex items-start gap-2">
          <p className="flex-1 text-[11px] text-slate-300 font-mono leading-relaxed">{finding.prompt}</p>
          <button
            onClick={handleCopy}
            title="Copy Replit prompt"
            className="flex-shrink-0 flex items-center gap-1 px-2 py-1 rounded bg-indigo-600/30 border border-indigo-500/40 text-indigo-300 hover:bg-indigo-600/50 transition-all text-[10px] font-semibold"
          >
            {copied ? <ClipboardCheck className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
            {copied ? "Copied!" : "Copy"}
          </button>
        </div>
      )}
    </div>
  );
}

function formatParamName(name: string): string {
  return name.replace(/_/g, " ").replace(/PCT/g, "%").replace(/MIN NET PROFIT/g, "Min Profit");
}

function formatParamValue(name: string, val: number): string {
  return val.toFixed(name.includes("PCT") ? 3 : 2);
}

function ParamChangeCard({ botId, params, currentParams, bounds }: {
  botId: string;
  params: Record<string, number>;
  currentParams?: Record<string, number>;
  bounds?: Record<string, BotParamBounds>;
}) {
  return (
    <div className="rounded-lg border border-white/[0.08] bg-slate-900/60 p-2.5 mb-1.5">
      <div className="text-xs font-bold text-amber-300 mb-1.5 font-mono">{botId}</div>
      <div className="space-y-1">
        {Object.entries(params).map(([pname, target]) => {
          const current = currentParams?.[pname];
          const b = bounds?.[pname];
          return (
            <div key={pname} className="flex items-center gap-2 text-[11px]">
              <span className="text-slate-400 font-mono w-28 flex-shrink-0">{formatParamName(pname)}</span>
              {current != null ? (
                <>
                  <span className="font-mono text-slate-300">{formatParamValue(pname, current)}</span>
                  <ArrowRight className="w-3 h-3 text-amber-400 flex-shrink-0" />
                  <span className="font-mono text-white font-bold">{formatParamValue(pname, target)}</span>
                </>
              ) : (
                <span className="font-mono text-white font-bold">{formatParamValue(pname, target)}</span>
              )}
              {b && (
                <span className="text-slate-600 text-[9px] ml-auto">[{formatParamValue(pname, b.min)}-{formatParamValue(pname, b.max)}]</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function MessageBubble({ msg, onApprove, onDecline, isApproving, currentBotParams, botBounds }: {
  msg: ChatMessage;
  onApprove?: (id: string) => void;
  onDecline?: (id: string) => void;
  isApproving?: boolean;
  currentBotParams?: Record<string, Record<string, number>>;
  botBounds?: Record<string, Record<string, BotParamBounds>>;
}) {
  const isUser = msg.role === "user";
  const meta = msg.metadata || {};
  const hasRecs = meta.status === "pending_approval" && Array.isArray(meta.pending_recommendations);
  const wasApproved = meta.status === "approved";
  const wasDeclined = meta.status === "declined";
  const isAudit = Boolean(meta.audit);
  const auditFindings = isAudit ? parseAuditFindings(msg.content) : [];

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={`flex ${isUser ? "justify-end" : "justify-start"} mb-3`}
    >
      <div className={`flex gap-2.5 ${isAudit ? "max-w-[96%] w-full" : "max-w-[85%]"} ${isUser ? "flex-row-reverse" : ""}`}>
        <div className={`flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center mt-0.5 ${
          isUser ? "bg-blue-500/20 border border-blue-500/30" : isAudit ? "bg-indigo-500/20 border border-indigo-500/30" : "bg-emerald-500/20 border border-emerald-500/30"
        }`}>
          {isUser ? <User className="w-3.5 h-3.5 text-blue-400" /> : isAudit ? <ScanSearch className="w-3.5 h-3.5 text-indigo-400" /> : <Bot className="w-3.5 h-3.5 text-emerald-400" />}
        </div>
        <div className={isAudit ? "flex-1 min-w-0" : ""}>
          <div className={`rounded-xl px-3.5 py-2.5 text-sm leading-relaxed ${
            isUser
              ? "bg-blue-600/20 border border-blue-500/20 text-blue-100"
              : isAudit
              ? "bg-indigo-950/60 border border-indigo-500/20 text-slate-200"
              : "bg-slate-800/80 border border-white/[0.06] text-slate-200"
          }`}>
            {isUser ? (
              <div className="whitespace-pre-wrap">{msg.content}</div>
            ) : isAudit ? (
              <div>
                <div className="flex items-center gap-2 mb-3 pb-2 border-b border-indigo-500/20">
                  <ScanSearch className="w-4 h-4 text-indigo-400" />
                  <span className="text-xs font-bold text-indigo-300 uppercase tracking-wider">Code Audit Results</span>
                  {(meta.file_count as number) > 0 && (
                    <span className="text-[10px] text-slate-500 ml-auto">{meta.file_count as number} files scanned</span>
                  )}
                </div>
                <div className="prose prose-invert prose-sm max-w-none [&_p]:mb-2 [&_p]:leading-relaxed [&_strong]:text-white mb-3">
                  <ReactMarkdown>{
                    (() => {
                      const firstFinding = msg.content.search(/\*{1,2}#\d+\s*[—–\-]/);
                      return firstFinding > 0 ? msg.content.slice(0, firstFinding).trim() : msg.content.split("\n")[0];
                    })()
                  }</ReactMarkdown>
                </div>
                {auditFindings.length > 0 && (
                  <div>
                    {auditFindings.map(f => (
                      <AuditFindingCard key={f.number} finding={f} />
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div className="prose prose-invert prose-sm max-w-none [&_p]:mb-1.5 [&_p]:leading-relaxed [&_strong]:text-white [&_code]:bg-slate-700/50 [&_code]:px-1 [&_code]:rounded [&_code]:text-emerald-300 [&_ul]:mb-1.5 [&_ol]:mb-1.5 [&_li]:mb-0.5 [&_pre]:bg-slate-900 [&_pre]:rounded-lg [&_pre]:p-2 [&_pre]:text-xs [&_h1]:text-base [&_h2]:text-sm [&_h3]:text-xs">
                <ReactMarkdown>{msg.content}</ReactMarkdown>
              </div>
            )}
          </div>

          {hasRecs && !wasApproved && !wasDeclined && (
            <div className="mt-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
              <div className="flex items-center gap-2 mb-2">
                <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
                <span className="text-xs font-semibold text-amber-400 uppercase tracking-wider">Pending Approval</span>
              </div>
              <div className="mb-2">
                {(meta.pending_recommendations as Recommendation[]).map((rec, i) => (
                  <ParamChangeCard
                    key={i}
                    botId={rec.bot_id}
                    params={rec.params || {}}
                    currentParams={currentBotParams?.[rec.bot_id]}
                    bounds={botBounds?.[rec.bot_id]}
                  />
                ))}
              </div>
              <div className="flex items-start gap-2 mb-3 p-2 rounded-md bg-slate-900/40 border border-white/[0.04]">
                <Info className="w-3.5 h-3.5 text-slate-400 mt-0.5 flex-shrink-0" />
                <span className="text-[10px] text-slate-400 leading-relaxed">
                  Changes are limited to max 1 step per parameter per approval cycle. Multiple approvals may be needed to reach target values.
                </span>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => onApprove?.(msg.id)}
                  disabled={isApproving}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600/30 border border-emerald-500/40 text-emerald-300 text-xs font-semibold hover:bg-emerald-600/50 transition-all disabled:opacity-50"
                >
                  {isApproving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                  Accept
                </button>
                <button
                  onClick={() => onDecline?.(msg.id)}
                  disabled={isApproving}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-600/30 border border-red-500/40 text-red-300 text-xs font-semibold hover:bg-red-600/50 transition-all disabled:opacity-50"
                >
                  <X className="w-3 h-3" /> Decline
                </button>
              </div>
            </div>
          )}

          {wasApproved && (
            <div className="mt-1.5 flex items-center gap-1.5 text-xs text-emerald-400">
              <Check className="w-3 h-3" /> Approved & applied
            </div>
          )}
          {wasDeclined && (
            <div className="mt-1.5 flex items-center gap-1.5 text-xs text-slate-500">
              <X className="w-3 h-3" /> Declined
            </div>
          )}

          <div className="text-[10px] text-slate-600 mt-1 px-1">
            {new Date(msg.ts).toLocaleTimeString()}
          </div>
        </div>
      </div>
    </motion.div>
  );
}

function ParamsPanel() {
  const { data } = useFleetParams();

  if (!data?.bots) return null;

  const botLabels: Record<string, { name: string; color: string }> = {
    davy_jones: { name: "Davy Jones", color: "#f59e0b" },
    blackbeard: { name: "Blackbeard", color: "#ef4444" },
    calypso: { name: "Calypso", color: "#8b5cf6" },
  };

  return (
    <div className="space-y-3">
      <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider px-1">Live Parameters</h3>
      {Object.entries(data.bots).map(([botId, botData]: [string, BotParamData]) => {
        const label = botLabels[botId] || { name: botId, color: "#6b7280" };
        const current = botData.current || {};
        const defaults = botData.defaults || {};
        const bounds = botData.bounds || {};

        return (
          <div key={botId} className="rounded-xl border border-white/[0.06] bg-slate-900/60 p-3">
            <div className="flex items-center gap-2 mb-2.5">
              <div className="w-2 h-2 rounded-full" style={{ background: label.color }} />
              <span className="text-xs font-bold text-white">{label.name}</span>
            </div>
            <div className="space-y-2">
              {Object.entries(bounds).map(([param, b]: [string, BotParamBounds]) => {
                const val = current[param];
                const def = defaults[param];
                if (val == null) return null;
                const pct = ((val - b.min) / (b.max - b.min)) * 100;
                const atDefault = def != null && Math.abs(val - def) < b.step * 0.5;

                return (
                  <div key={param}>
                    <div className="flex justify-between items-center mb-0.5">
                      <span className="text-[10px] text-slate-400 font-mono">{formatParamName(param)}</span>
                      <span className="text-[10px] font-mono text-white">
                        {formatParamValue(param, val)}
                        {!atDefault && def != null && (
                          <span className="text-slate-600 ml-1">(def: {formatParamValue(param, def)})</span>
                        )}
                      </span>
                    </div>
                    <div className="h-1 rounded-full bg-slate-800 overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{
                          width: `${Math.max(2, Math.min(100, pct))}%`,
                          background: `linear-gradient(90deg, ${label.color}80, ${label.color})`,
                        }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

const STAGE_SHORT: Record<string, string> = {
  s1_analysis:       "Analysis",
  s2_core_execution: "Core/Exec",
  s3_routes:         "Routes",
  s4_infrastructure: "Infra",
  s5_dashboard_logic:"Dash Logic",
  s6_components_a:   "UI A–M",
  s7_components_b:   "UI N–Z",
  s8_synthesis:      "Synthesis",
};

const STAGE_VERDICT_STYLE: Record<string, { dot: string; label: string; badge: string }> = {
  PASS:            { dot: "bg-emerald-400", label: "text-emerald-400", badge: "bg-emerald-500/15 border-emerald-500/30 text-emerald-300" },
  NEEDS_ATTENTION: { dot: "bg-amber-400",   label: "text-amber-400",   badge: "bg-amber-500/15 border-amber-500/30 text-amber-300" },
  CRITICAL:        { dot: "bg-red-400",     label: "text-red-400",     badge: "bg-red-500/15 border-red-500/30 text-red-300" },
  HEALTHY:         { dot: "bg-emerald-400", label: "text-emerald-400", badge: "bg-emerald-500/15 border-emerald-500/30 text-emerald-300" },
  DEGRADED:        { dot: "bg-amber-400",   label: "text-amber-400",   badge: "bg-amber-500/15 border-amber-500/30 text-amber-300" },
  failed:          { dot: "bg-red-500",     label: "text-red-400",     badge: "bg-red-500/15 border-red-500/30 text-red-400" },
};

function formatCooldown(s: number) {
  if (s <= 0) return "Ready";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
  if (h > 0) return `${h}h ${m}m cooldown`;
  if (m > 0) return `${m}m ${sec}s cooldown`;
  return `${sec}s cooldown`;
}

function ClaudeAuditPanel() {
  const { data: stagesData, refetch } = useClaudeAuditStages();
  const triggerMutation = useTriggerClaudeStage();
  const [selectedId, setSelectedId] = useState<string>("s1_analysis");
  const [expanded, setExpanded] = useState(true);
  const [, setTick] = useState(0);

  useEffect(() => {
    const iv = setInterval(() => setTick(t => t + 1), 4000);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    if (triggerMutation.isSuccess) { setTimeout(() => refetch(), 2000); }
  }, [triggerMutation.isSuccess, refetch]);

  const stages: AuditStageInfo[] = stagesData?.stages || [];
  const anyRunning = stages.some(s => s.run_state.in_progress);
  const selected = stages.find(s => s.id === selectedId);

  return (
    <div className="border-b border-white/[0.06] bg-[#0a0e1a]">
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-white/[0.02] transition-colors"
      >
        <div className="flex items-center gap-2">
          <Brain className="w-3.5 h-3.5 text-violet-400" />
          <span className="text-xs font-bold text-violet-300 uppercase tracking-wider">Claude Deep Audit</span>
          <span className="text-[10px] text-slate-500">8-stage · claude-3-5-sonnet · full codebase</span>
          {anyRunning && (
            <span className="flex items-center gap-1 text-[10px] text-violet-300 bg-violet-500/15 border border-violet-500/30 rounded-full px-2 py-0.5">
              <Loader2 className="w-2.5 h-2.5 animate-spin" /> Running
            </span>
          )}
        </div>
        {expanded ? <ChevronUp className="w-3.5 h-3.5 text-slate-500" /> : <ChevronDown className="w-3.5 h-3.5 text-slate-500" />}
      </button>

      {expanded && (
        <div className="px-4 pb-3">
          {stages.length === 0 ? (
            <div className="text-xs text-slate-500 py-2">Loading stages…</div>
          ) : (
            <>
              <div className="flex flex-wrap gap-1.5 mb-3">
                {stages.map((stage, i) => {
                  const verdict = stage.last_result?.stage_verdict || (stage.last_result?.status === "failed" ? "failed" : null);
                  const vstyle = verdict ? (STAGE_VERDICT_STYLE[verdict] || null) : null;
                  const isSelected = stage.id === selectedId;
                  const isRunning = stage.run_state.in_progress;
                  return (
                    <button
                      key={stage.id}
                      onClick={() => setSelectedId(stage.id)}
                      className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-[11px] font-medium transition-all ${
                        isSelected
                          ? "bg-violet-600/25 border-violet-500/50 text-violet-200"
                          : "bg-white/[0.04] border-white/[0.08] text-slate-400 hover:text-white hover:border-white/20"
                      }`}
                    >
                      <span className="text-slate-600 font-mono text-[9px]">{i + 1}</span>
                      <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                        isRunning ? "bg-violet-400 animate-pulse" :
                        vstyle ? vstyle.dot : "bg-white/15"
                      }`} />
                      {STAGE_SHORT[stage.id] || stage.id}
                    </button>
                  );
                })}
              </div>

              {selected && (
                <div className="rounded-xl border border-white/[0.08] bg-slate-900/60 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap mb-1">
                        <span className="text-xs font-bold text-white">{selected.name}</span>
                        {(() => {
                          const verdict = selected.last_result?.stage_verdict || (selected.last_result?.status === "failed" ? "failed" : null);
                          const vstyle = verdict ? (STAGE_VERDICT_STYLE[verdict] || null) : null;
                          return verdict && vstyle ? (
                            <span className={`text-[10px] px-2 py-0.5 rounded border font-semibold ${vstyle.badge}`}>{verdict}</span>
                          ) : null;
                        })()}
                        {selected.run_state.in_progress && (
                          <span className="text-[10px] px-2 py-0.5 rounded border bg-violet-500/15 border-violet-500/30 text-violet-300 flex items-center gap-1">
                            <Loader2 className="w-2.5 h-2.5 animate-spin" /> Running…
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-slate-400 leading-relaxed">{selected.description}</p>
                      {selected.last_result?.summary && (
                        <p className="text-[11px] text-slate-300 mt-1.5 pt-1.5 border-t border-white/[0.05] leading-relaxed">
                          {selected.last_result.summary}
                        </p>
                      )}
                      {selected.last_result?.key_risks && selected.last_result.key_risks.length > 0 && (
                        <div className="mt-2 space-y-0.5">
                          {selected.last_result.key_risks.slice(0, 3).map((r, i) => (
                            <div key={i} className="flex items-start gap-1.5 text-[11px] text-amber-300/80">
                              <AlertTriangle className="w-2.5 h-2.5 mt-0.5 flex-shrink-0" />
                              <span>{r}</span>
                            </div>
                          ))}
                        </div>
                      )}
                      {selected.last_result?.completed_at && (
                        <div className="flex items-center gap-1 mt-1.5 text-[10px] text-slate-600">
                          <Clock className="w-2.5 h-2.5" />
                          {new Date(selected.last_result.completed_at).toLocaleString()}
                        </div>
                      )}
                      {selected.run_state.error && (
                        <p className="text-[11px] text-red-400 mt-1.5 flex items-center gap-1">
                          <XCircle className="w-3 h-3" /> {selected.run_state.error}
                        </p>
                      )}
                    </div>
                    <div className="flex-shrink-0">
                      {selected.run_state.in_progress || anyRunning ? (
                        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-violet-500/10 border border-violet-500/20 text-violet-400 text-xs">
                          <Loader2 className="w-3 h-3 animate-spin" />
                          {selected.run_state.in_progress ? "Running" : "Busy"}
                        </div>
                      ) : selected.cooldown_remaining_seconds > 0 ? (
                        <div className="text-[10px] text-slate-500 text-right">
                          <Clock className="w-3 h-3 inline mr-1" />
                          {formatCooldown(selected.cooldown_remaining_seconds)}
                        </div>
                      ) : (
                        <button
                          onClick={() => triggerMutation.mutate(selected.id)}
                          disabled={triggerMutation.isPending}
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-violet-600/30 border border-violet-500/40 text-violet-300 text-xs font-semibold hover:bg-violet-600/50 transition-all disabled:opacity-50"
                        >
                          <Play className="w-3 h-3" />
                          Run Stage {stages.findIndex(s => s.id === selected.id) + 1}
                        </button>
                      )}
                    </div>
                  </div>

                  {selected.last_result && !selected.run_state.in_progress && (
                    <div className="mt-2 pt-2 border-t border-white/[0.05] flex gap-3 text-[10px] text-slate-500">
                      {(selected.last_result.critical_issues?.length ?? 0) > 0 && (
                        <span className="text-red-400">● {selected.last_result.critical_issues!.length} critical</span>
                      )}
                      {(selected.last_result.high_issues?.length ?? 0) > 0 && (
                        <span className="text-orange-400">● {selected.last_result.high_issues!.length} high</span>
                      )}
                      {(selected.last_result.medium_issues?.length ?? 0) > 0 && (
                        <span className="text-amber-400">● {selected.last_result.medium_issues!.length} medium</span>
                      )}
                      {(selected.last_result.positive_notes?.length ?? 0) > 0 && (
                        <span className="text-emerald-400">
                          <CheckCircle2 className="w-2.5 h-2.5 inline mr-0.5" />
                          {selected.last_result.positive_notes!.length} positive
                        </span>
                      )}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default function CommanderPage() {
  const [input, setInput] = useState("");
  const [showParams, setShowParams] = useState(true);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const { data: historyData, isLoading: historyLoading } = useQuery({
    queryKey: ["fleet-chat-history"],
    queryFn: async () => {
      const r = await fetch(`${BASE}/fleet-commander/chat/history?limit=100`);
      if (!r.ok) throw new Error(`Chat history fetch failed: ${r.status}`);
      return r.json();
    },
    refetchInterval: 10_000,
  });

  const { data: paramsData } = useFleetParams();

  const currentBotParams: Record<string, Record<string, number>> = {};
  const botBounds: Record<string, Record<string, BotParamBounds>> = {};
  if (paramsData?.bots) {
    for (const [botId, botData] of Object.entries(paramsData.bots) as [string, BotParamData][]) {
      if (botData.current) {
        currentBotParams[botId] = botData.current;
      }
      if (botData.bounds) {
        botBounds[botId] = botData.bounds;
      }
    }
  }

  const messages: ChatMessage[] = historyData?.messages || [];

  const scrollToBottom = useCallback(() => {
    setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: "smooth" }), 100);
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages.length, scrollToBottom]);

  const chatMutation = useMutation({
    mutationFn: async (body: { message?: string; quick_action?: string }) => {
      const resp = await fetch(`${BASE}/fleet-commander/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!resp.ok) throw new Error(await resp.text());
      return resp.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["fleet-chat-history"] });
      queryClient.invalidateQueries({ queryKey: ["fleet-params"] });
      scrollToBottom();
    },
  });

  const approveMutation = useMutation({
    mutationFn: async ({ messageId, approved }: { messageId: string; approved: boolean }) => {
      const resp = await fetch(`${BASE}/fleet-commander/chat/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message_id: messageId, approved }),
      });
      if (!resp.ok) throw new Error(await resp.text());
      return resp.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["fleet-chat-history"] });
      queryClient.invalidateQueries({ queryKey: ["fleet-params"] });
    },
  });

  const handleSend = () => {
    const msg = input.trim();
    if (!msg || chatMutation.isPending) return;
    setInput("");
    chatMutation.mutate({ message: msg });
  };

  const handleQuickAction = (actionId: string) => {
    if (chatMutation.isPending) return;
    chatMutation.mutate({ quick_action: actionId });
  };

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col">
      <header className="sticky top-0 z-40 border-b border-white/[0.06] bg-slate-950/95 backdrop-blur-xl px-4 py-3">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-xl bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center">
              <Bot className="w-4 h-4 text-emerald-400" />
            </div>
            <div>
              <h1 className="text-sm font-bold text-white leading-none">Fleet Commander</h1>
              <p className="text-[10px] text-slate-500">Gemini chat · Claude deep audit</p>
            </div>
          </div>
          <button
            onClick={() => setShowParams(p => !p)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-white border border-white/[0.06] hover:border-white/[0.12] transition-all"
          >
            <ChevronDown className={`w-3 h-3 transition-transform ${showParams ? "rotate-180" : ""}`} />
            Params
          </button>
        </div>
      </header>

      <div className="flex-1 flex max-w-6xl mx-auto w-full">
        <div className="flex-1 flex flex-col min-w-0">
          <div className="px-4 py-3 border-b border-white/[0.04]">
            <div className="flex flex-wrap gap-2">
              {QUICK_ACTIONS.map(action => {
                const Icon = action.icon;
                return (
                  <button
                    key={action.id}
                    onClick={() => handleQuickAction(action.id)}
                    disabled={chatMutation.isPending}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium border border-white/[0.08] bg-slate-900/60 hover:bg-slate-800/80 transition-all disabled:opacity-40 group"
                  >
                    <Icon className="w-3.5 h-3.5 transition-colors" style={{ color: action.color }} />
                    <span className="text-slate-300 group-hover:text-white transition-colors">{action.label}</span>
                  </button>
                );
              })}
            </div>
          </div>

          <ClaudeAuditPanel />

          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-1">
            {historyLoading && (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="w-5 h-5 text-slate-500 animate-spin" />
              </div>
            )}

            {!historyLoading && messages.length === 0 && (
              <div className="flex flex-col items-center justify-center py-16 text-center">
                <div className="w-14 h-14 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center mb-4">
                  <Bot className="w-7 h-7 text-emerald-400" />
                </div>
                <h2 className="text-lg font-bold text-white mb-1">Fleet Commander</h2>
                <p className="text-sm text-slate-500 max-w-sm">
                  Chat with Gemini to manage your trading fleet. Use quick actions above or type a command below.
                </p>
              </div>
            )}

            <AnimatePresence>
              {messages.map(msg => (
                <MessageBubble
                  key={msg.id}
                  msg={msg}
                  onApprove={(id) => approveMutation.mutate({ messageId: id, approved: true })}
                  onDecline={(id) => approveMutation.mutate({ messageId: id, approved: false })}
                  isApproving={approveMutation.isPending}
                  currentBotParams={currentBotParams}
                  botBounds={botBounds}
                />
              ))}
            </AnimatePresence>

            {chatMutation.isPending && (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex justify-start mb-3">
                <div className="flex gap-2.5">
                  <div className="w-7 h-7 rounded-lg bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center">
                    <Bot className="w-3.5 h-3.5 text-emerald-400" />
                  </div>
                  <div className="rounded-xl px-3.5 py-2.5 bg-slate-800/80 border border-white/[0.06]">
                    <div className="flex items-center gap-2">
                      <Loader2 className="w-3.5 h-3.5 text-emerald-400 animate-spin" />
                      <span className="text-sm text-slate-400">Analyzing fleet data...</span>
                    </div>
                  </div>
                </div>
              </motion.div>
            )}

            <div ref={chatEndRef} />
          </div>

          <div className="sticky bottom-0 border-t border-white/[0.06] bg-slate-950/95 backdrop-blur-xl px-4 py-3">
            <div className="flex gap-2">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
                placeholder="Ask Fleet Commander..."
                disabled={chatMutation.isPending}
                className="flex-1 bg-slate-900/80 border border-white/[0.08] rounded-xl px-4 py-2.5 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-emerald-500/40 transition-colors disabled:opacity-50"
              />
              <button
                onClick={handleSend}
                disabled={!input.trim() || chatMutation.isPending}
                className="flex items-center justify-center w-10 h-10 rounded-xl bg-emerald-600/30 border border-emerald-500/40 text-emerald-300 hover:bg-emerald-600/50 transition-all disabled:opacity-30"
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>

        {showParams && (
          <motion.aside
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: 300, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            className="border-l border-white/[0.06] overflow-y-auto p-4 hidden lg:block"
          >
            <ParamsPanel />
          </motion.aside>
        )}
      </div>
    </div>
  );
}
