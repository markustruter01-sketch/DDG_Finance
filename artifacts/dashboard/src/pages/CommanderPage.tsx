import { useState, useRef, useEffect, useCallback } from "react";
import { useLocation } from "wouter";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft, Send, Shield, Swords, Target, RotateCcw, Pause, Zap,
  Bot, User, Loader2, Check, X, ChevronDown, AlertTriangle,
} from "lucide-react";

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

function formatParamName(name: string): string {
  return name.replace(/_/g, " ").replace(/PCT/g, "%").replace(/MIN NET PROFIT/g, "Min Profit");
}

function MessageBubble({ msg, onApprove, onDecline, isApproving }: {
  msg: ChatMessage;
  onApprove?: (id: string) => void;
  onDecline?: (id: string) => void;
  isApproving?: boolean;
}) {
  const isUser = msg.role === "user";
  const meta = msg.metadata || {};
  const hasRecs = meta.status === "pending_approval" && Array.isArray(meta.pending_recommendations);
  const wasApproved = meta.status === "approved";
  const wasDeclined = meta.status === "declined";

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={`flex ${isUser ? "justify-end" : "justify-start"} mb-3`}
    >
      <div className={`flex gap-2.5 max-w-[85%] ${isUser ? "flex-row-reverse" : ""}`}>
        <div className={`flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center mt-0.5 ${
          isUser ? "bg-blue-500/20 border border-blue-500/30" : "bg-emerald-500/20 border border-emerald-500/30"
        }`}>
          {isUser ? <User className="w-3.5 h-3.5 text-blue-400" /> : <Bot className="w-3.5 h-3.5 text-emerald-400" />}
        </div>
        <div>
          <div className={`rounded-xl px-3.5 py-2.5 text-sm leading-relaxed ${
            isUser
              ? "bg-blue-600/20 border border-blue-500/20 text-blue-100"
              : "bg-slate-800/80 border border-white/[0.06] text-slate-200"
          }`}>
            <div className="whitespace-pre-wrap">{msg.content}</div>
          </div>

          {hasRecs && !wasApproved && !wasDeclined && (
            <div className="mt-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
              <div className="flex items-center gap-2 mb-2">
                <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
                <span className="text-xs font-semibold text-amber-400 uppercase tracking-wider">Pending Approval</span>
              </div>
              <div className="space-y-1.5 mb-3">
                {(meta.pending_recommendations as Recommendation[]).map((rec, i) => (
                  <div key={i} className="text-xs text-slate-300">
                    <span className="font-mono text-amber-300">{rec.bot_id}</span>
                    {": "}
                    {Object.entries(rec.params || {}).map(([k, v]) => (
                      <span key={k} className="font-mono text-white ml-1">{k}={typeof v === 'number' ? v.toFixed(4) : v}</span>
                    ))}
                  </div>
                ))}
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
  const { data } = useQuery({
    queryKey: ["fleet-params"],
    queryFn: async () => {
      const r = await fetch(`${BASE}/fleet-commander/params`);
      if (!r.ok) throw new Error(`Params fetch failed: ${r.status}`);
      return r.json();
    },
    refetchInterval: 30_000,
  });

  if (!data?.bots) return null;

  const botLabels: Record<string, { name: string; color: string }> = {
    davy_jones: { name: "Davy Jones", color: "#f59e0b" },
    blackbeard: { name: "Blackbeard", color: "#ef4444" },
    calypso: { name: "Calypso", color: "#8b5cf6" },
  };

  return (
    <div className="space-y-3">
      <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider px-1">Live Parameters</h3>
      {Object.entries(data.bots).map(([botId, botData]: [string, any]) => {
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
              {Object.entries(bounds).map(([param, b]: [string, any]) => {
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
                        {val.toFixed(param.includes("PCT") ? 3 : 2)}
                        {!atDefault && def != null && (
                          <span className="text-slate-600 ml-1">(def: {def.toFixed(param.includes("PCT") ? 3 : 2)})</span>
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

export default function CommanderPage() {
  const [, navigate] = useLocation();
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
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate("/")}
              className="flex items-center gap-1.5 text-slate-400 hover:text-white transition-colors text-sm"
            >
              <ArrowLeft className="w-4 h-4" /> Dashboard
            </button>
            <div className="w-px h-5 bg-white/10" />
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-xl bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center">
                <Bot className="w-4 h-4 text-emerald-400" />
              </div>
              <div>
                <h1 className="text-sm font-bold text-white leading-none">Fleet Commander</h1>
                <p className="text-[10px] text-slate-500">Gemini-powered fleet control</p>
              </div>
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
