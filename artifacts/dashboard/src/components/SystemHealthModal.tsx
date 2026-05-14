import { useState, useEffect, useMemo, useCallback } from "react";
import { X, Activity, Wifi, Server, Shield, Database, Anchor, AlertTriangle, CheckCircle2, XCircle, Info, Zap, RotateCcw, Clock, Brain, Globe, Target, Bell } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { cn } from "@/lib/utils";

const API_PREFIX = import.meta.env.VITE_API_PREFIX ?? "/trading-api";
const api = {
  get: async (path: string) => {
    const res = await fetch(`${API_PREFIX}${path}`);
    if (!res.ok) throw new Error(`${res.status}`);
    return { data: await res.json() };
  },
  post: async (path: string, body?: unknown) => {
    const res = await fetch(`${API_PREFIX}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) throw new Error(`${res.status}`);
    return { data: await res.json() };
  },
};

type Level = "green" | "yellow" | "red";

interface NodeHealth {
  label: string;
  level: Level;
  latency_ms: number | null;
  data_age_s: number | null;
  detail: string;
}

interface HealthData {
  timestamp: number;
  nodes: Record<string, NodeHealth>;
}

interface HealEntry {
  ts: number;
  component: string;
  action: string;
  result: string;
  success: boolean;
  triggered_by: string;
  heal_type?: string;
  state_changed?: boolean;
}

interface Overrides {
  [key: string]: Partial<NodeHealth>;
}

const LEVEL_COLORS: Record<Level, { fill: string; stroke: string; glow: string; wire: string; text: string; bg: string; border: string }> = {
  green: {
    fill: "rgba(34,197,94,0.08)",
    stroke: "rgba(34,197,94,0.6)",
    glow: "rgba(34,197,94,0.4)",
    wire: "#22c55e",
    text: "text-green-400",
    bg: "bg-green-500/10",
    border: "border-green-500/20",
  },
  yellow: {
    fill: "rgba(234,179,8,0.08)",
    stroke: "rgba(234,179,8,0.6)",
    glow: "rgba(234,179,8,0.4)",
    wire: "#eab308",
    text: "text-yellow-400",
    bg: "bg-yellow-500/10",
    border: "border-yellow-500/20",
  },
  red: {
    fill: "rgba(239,68,68,0.08)",
    stroke: "rgba(239,68,68,0.6)",
    glow: "rgba(239,68,68,0.4)",
    wire: "#ef4444",
    text: "text-red-400",
    bg: "bg-red-500/10",
    border: "border-red-500/25",
  },
};

const NODE_POSITIONS: Record<string, { x: number; y: number; icon: typeof Server }> = {
  platform_core:  { x: 400, y: 80,  icon: Server },
  equity_manager: { x: 140, y: 230, icon: Shield },
  alpaca_api:     { x: 140, y: 400, icon: Wifi },
  kraken_api:     { x: 400, y: 230, icon: Anchor },
  options_bot:    { x: 660, y: 230, icon: Target },
  forex_bot:      { x: 660, y: 400, icon: Globe },
  data_pipeline:  { x: 400, y: 400, icon: Database },
  rag_engine:     { x: 140, y: 530, icon: Brain },
  alert_system:   { x: 660, y: 530, icon: Bell },
};
const NODE_W = 170;
const NODE_H = 86;

type WireSpec = { from: string; to: string; bend?: "h-first" | "v-first" };

const WIRES: WireSpec[] = [
  { from: "platform_core",  to: "equity_manager", bend: "v-first" },
  { from: "platform_core",  to: "kraken_api",     bend: "v-first" },
  { from: "platform_core",  to: "options_bot",    bend: "v-first" },
  { from: "equity_manager", to: "alpaca_api",     bend: "v-first" },
  { from: "kraken_api",     to: "data_pipeline",  bend: "v-first" },
  { from: "options_bot",    to: "forex_bot",      bend: "v-first" },
  { from: "data_pipeline",  to: "rag_engine",     bend: "h-first" },
  { from: "data_pipeline",  to: "forex_bot",      bend: "h-first" },
  { from: "data_pipeline",  to: "alert_system",   bend: "h-first" },
  { from: "rag_engine",     to: "alpaca_api",     bend: "v-first" },
];

const COMPONENT_LABELS: Record<string, string> = {
  platform_core: "Platform Core",
  data_pipeline: "Data Pipeline",
  kraken_api: "Kraken Bot",
  alpaca_api: "Alpaca API",
  equity_manager: "Equity Manager",
  rag_engine: "RAG Learning Engine",
  options_bot: "Options Engine",
  forex_bot: "Forex Gump",
  alert_system: "Alert System",
  kraken_davy_jones: "SPY/QQQ Trend",
  kraken_blackbeard: "Jerome",
  kraken_poseidon: "Poseidon",
  kraken_kraken_current: "Kraken Current",
};

function buildExplanation(key: string, node: NodeHealth): string {
  const { level, latency_ms, data_age_s, detail } = node;

  if (level === "green") return "All checks passing.";

  if (latency_ms != null && latency_ms > 1000)
    return `Round-trip to ${node.label.split("(")[0].trim()} took ${latency_ms}ms — well above the 1,000ms critical threshold. Check network or API availability.`;
  if (latency_ms != null && latency_ms > 200)
    return `Latency is ${latency_ms}ms — above the 200ms optimal threshold. The API is reachable but responding slowly.`;

  if (data_age_s != null && data_age_s > 600)
    return `Feed data is ${data_age_s.toFixed(0)}s old — critical threshold is 600s. The data pipeline may be stalled or the bot has stopped writing updates.`;
  if (data_age_s != null && data_age_s > 60)
    return `Feed data is ${data_age_s.toFixed(0)}s old — past the 60s freshness threshold. Normal if a cycle just completed; watch if it continues rising.`;

  if (key === "equity_manager") {
    if (level === "red") return `A single position exceeds 15% of total equity — the hard risk limit. The enforcer should trigger a rebalance. Detail: ${detail}`;
    if (level === "yellow") return `A single position is approaching the 15% limit (currently 12–15%). No breach yet, but worth monitoring. Detail: ${detail}`;
  }

  if (key === "platform_core") {
    if (detail.includes("0/8 jobs") || detail.includes("0 jobs")) return "The APScheduler crashed or lost all 8 registered jobs. Restart the trading API server to recover.";
    if (detail.includes("analysis_failed") && level === "yellow") return `analysis_failed off market hours — expected (Alpaca/yfinance unavailable). Clears when market opens. Detail: ${detail}`;
    if (detail.includes("error") || detail.includes("failed")) return `The last analysis cycle ended in an error state. Check server logs for the root cause. Detail: ${detail}`;
    if (detail.includes("never_run")) return "No analysis cycle has run yet since the server started. This clears automatically once the first cycle fires.";
  }

  if (key === "data_pipeline") {
    if (detail.includes("No data cached")) return "No market data feeds have been cached yet. This resolves after the first analysis cycle runs (scheduler must be enabled and market must be in session or crypto cycle must fire).";
    return `Only some data feeds are cached. Detail: ${detail}`;
  }

  if (key === "kraken_api") {
    if (detail.includes("Bot not started")) return "The Kraken bot process hasn't written a status file yet. Start the 'SPY/QQQ Trend' bot workflow to resolve.";
    if (detail.includes("paused")) return "The Kraken bot is paused — either manually via the dashboard toggle or by the circuit breaker (>3% drop / 30min). Resume from the toolbar.";
    if (detail.includes("503") || detail.includes("timeout")) return "The Kraken exchange API returned a server error. This is usually transient — the bot will retry on the next cycle.";
    if (data_age_s != null && data_age_s > 1800) return `Kraken status file is ${data_age_s.toFixed(0)}s old (threshold 1800s / 30 min). The Replit workflow may have been paused — check if the bot is still running.`;
    if (data_age_s != null && data_age_s > 600) return `Kraken status file is ${data_age_s.toFixed(0)}s old (warning threshold 600s). Bot is cycling but slower than expected.`;
  }

  if (key === "alpaca_api") {
    if (detail.includes("429")) return "Alpaca rate limit hit. The platform made too many API calls in a short window. This resolves automatically within a minute.";
    if (detail.includes("401") || detail.includes("403")) return "Alpaca authentication failed. Verify ALPACA_API_KEY and ALPACA_SECRET_KEY are set correctly in Secrets.";
    if (detail.includes("404")) return "Alpaca returned 404 — the requested resource (account, order, position) was not found. May indicate a stale reference.";
    if (detail.includes("503") || detail.includes("timeout")) return "Alpaca API is unreachable or timing out. Could be a temporary outage — check status.alpaca.markets.";
  }

  if (key === "rag_engine") {
    if (level === "red") return `The RAG learning engine cannot reach the PostgreSQL database. Phase 3 contextual retrieval and Phase 4 rule injection are disabled — the LLM is running without historical memory. Check DATABASE_URL and DB connectivity. Detail: ${detail}`;
    if (level === "yellow") return "The RAG engine is online but no post-mortem lessons exist yet (fresh database). This is expected on first run. Lessons accumulate after the first losing trade is closed and the evening post-mortem cycle runs.";
  }

  if (key === "forex_bot") {
    if (level === "red") return `The Navigator forex engine is offline or encountered an error. Check trading-api logs. Detail: ${detail}`;
    if (level === "yellow") return detail.includes("Paused") ? "The forex engine is paused — either manually from the dashboard or by the system. Resume via the FOREX tab." : "The forex engine is loading or has not completed its first cycle yet.";
  }

  if (key === "alert_system") {
    if (level === "yellow") return "No notification channels configured. Set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID or DISCORD_WEBHOOK_URL in Secrets to receive profitable trade alerts.";
  }

  return detail || "Status flagged — check the server logs for more detail.";
}

function GlowingWire({ x1, y1, x2, y2, bend, level, id }: { x1: number; y1: number; x2: number; y2: number; bend: "h-first" | "v-first"; level: Level; id: string }) {
  const colors = LEVEL_COLORS[level];
  const mx = bend === "h-first" ? x2 : x1;
  const my = bend === "h-first" ? y1 : y2;
  const pathD = `M ${x1} ${y1} L ${mx} ${my} L ${x2} ${y2}`;
  const seg1 = Math.abs(bend === "h-first" ? x2 - x1 : y2 - y1);
  const seg2 = Math.abs(bend === "h-first" ? y2 - y1 : x2 - x1);
  const totalLen = seg1 + seg2;
  const dur  = level === "red" ? "0.7s" : level === "yellow" ? "1.6s" : "2.8s";
  const dur2 = level === "red" ? "0.9s" : level === "yellow" ? "2.2s" : "4s";

  const kf1 = totalLen > 0 ? seg1 / totalLen : 0.5;

  return (
    <g>
      <path d={pathD} fill="none" stroke={colors.wire} strokeWidth={8} opacity={0.06} />
      <path d={pathD} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth={1} />
      <path d={pathD} fill="none" stroke={colors.wire} strokeWidth={1.5} opacity={0.3} />
      <path
        d={pathD} fill="none"
        stroke={colors.wire} strokeWidth={3} opacity={0.95}
        strokeDasharray={`12 ${totalLen}`} strokeLinecap="round"
      >
        <animate attributeName="stroke-dashoffset" from={totalLen + 12} to={-(totalLen)} dur={dur} repeatCount="indefinite" />
      </path>
      <path
        d={pathD} fill="none"
        stroke={colors.wire} strokeWidth={2} opacity={0.5}
        strokeDasharray={`6 ${totalLen}`} strokeLinecap="round"
      >
        <animate attributeName="stroke-dashoffset" from={totalLen + 6} to={-(totalLen)} dur={dur2} repeatCount="indefinite" />
      </path>
      <circle cx={x1} cy={y1} r={level === "red" ? 5 : 4} fill={colors.wire} opacity={0.95}>
        <animate attributeName="cx" values={`${x1};${mx};${x2}`} keyTimes={`0;${kf1.toFixed(3)};1`} dur={dur} repeatCount="indefinite" />
        <animate attributeName="cy" values={`${y1};${my};${y2}`} keyTimes={`0;${kf1.toFixed(3)};1`} dur={dur} repeatCount="indefinite" />
        <animate attributeName="opacity" values="0;0.95;0.95;0" keyTimes="0;0.1;0.9;1" dur={dur} repeatCount="indefinite" />
      </circle>
      <circle cx={x1} cy={y1} r={3} fill={colors.wire} opacity={0.6}>
        <animate attributeName="cx" values={`${x1};${mx};${x2}`} keyTimes={`0;${kf1.toFixed(3)};1`} dur={dur2} begin={`${parseFloat(dur2) * 0.45}s`} repeatCount="indefinite" />
        <animate attributeName="cy" values={`${y1};${my};${y2}`} keyTimes={`0;${kf1.toFixed(3)};1`} dur={dur2} begin={`${parseFloat(dur2) * 0.45}s`} repeatCount="indefinite" />
        <animate attributeName="opacity" values="0;0.6;0.6;0" keyTimes="0;0.1;0.9;1" dur={dur2} begin={`${parseFloat(dur2) * 0.45}s`} repeatCount="indefinite" />
      </circle>
    </g>
  );
}

function ArchitectureNode({
  nodeKey,
  health,
  selected,
  onClick,
}: {
  nodeKey: string;
  health: NodeHealth;
  selected: boolean;
  onClick: () => void;
}) {
  const pos = NODE_POSITIONS[nodeKey];
  if (!pos) return null;
  const colors = LEVEL_COLORS[health.level];
  const Icon = pos.icon;
  const W = NODE_W;
  const H = NODE_H;
  const cs = 14; // corner-bracket size

  const metric = health.latency_ms != null
    ? `${health.latency_ms}ms`
    : health.data_age_s != null
    ? `${health.data_age_s.toFixed(0)}s`
    : "—";

  return (
    <g onClick={onClick} className="cursor-pointer">
      {/* Outer pulsing halo for non-green nodes */}
      {health.level !== "green" && (
        <ellipse cx={pos.x} cy={pos.y} rx={W / 2 + 16} ry={H / 2 + 14}
          fill="none" stroke={colors.wire} strokeWidth={1}>
          <animate attributeName="rx" values={`${W/2+10};${W/2+22};${W/2+10}`} dur={health.level === "red" ? "1s" : "2.5s"} repeatCount="indefinite" />
          <animate attributeName="ry" values={`${H/2+8};${H/2+18};${H/2+8}`} dur={health.level === "red" ? "1s" : "2.5s"} repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.5;0;0.5" dur={health.level === "red" ? "1s" : "2.5s"} repeatCount="indefinite" />
        </ellipse>
      )}

      {/* Main node body */}
      <rect x={pos.x - W/2} y={pos.y - H/2} width={W} height={H} rx={8}
        fill={colors.fill} stroke={colors.stroke} strokeWidth={selected ? 2 : 1.2} />

      {/* Selected glow overlay */}
      {selected && (
        <rect x={pos.x - W/2} y={pos.y - H/2} width={W} height={H} rx={8}
          fill={colors.wire} opacity={0.06} />
      )}

      {/* Critical flash */}
      {health.level === "red" && (
        <rect x={pos.x - W/2} y={pos.y - H/2} width={W} height={H} rx={8}
          fill="none" stroke={colors.stroke} strokeWidth={2.5}>
          <animate attributeName="opacity" values="1;0.15;1" dur="0.9s" repeatCount="indefinite" />
        </rect>
      )}

      {/* Corner brackets — top-left */}
      <path d={`M ${pos.x-W/2} ${pos.y-H/2+cs} L ${pos.x-W/2} ${pos.y-H/2} L ${pos.x-W/2+cs} ${pos.y-H/2}`}
        fill="none" stroke={colors.wire} strokeWidth={2} opacity={0.9} />
      {/* top-right */}
      <path d={`M ${pos.x+W/2-cs} ${pos.y-H/2} L ${pos.x+W/2} ${pos.y-H/2} L ${pos.x+W/2} ${pos.y-H/2+cs}`}
        fill="none" stroke={colors.wire} strokeWidth={2} opacity={0.9} />
      {/* bottom-left */}
      <path d={`M ${pos.x-W/2} ${pos.y+H/2-cs} L ${pos.x-W/2} ${pos.y+H/2} L ${pos.x-W/2+cs} ${pos.y+H/2}`}
        fill="none" stroke={colors.wire} strokeWidth={2} opacity={0.9} />
      {/* bottom-right */}
      <path d={`M ${pos.x+W/2-cs} ${pos.y+H/2} L ${pos.x+W/2} ${pos.y+H/2} L ${pos.x+W/2} ${pos.y+H/2-cs}`}
        fill="none" stroke={colors.wire} strokeWidth={2} opacity={0.9} />

      {/* Status indicator dot — top right inside corner */}
      <circle cx={pos.x + W/2 - 11} cy={pos.y - H/2 + 11} r={4} fill={colors.wire} opacity={0.95} />
      {health.level !== "green" && (
        <circle cx={pos.x + W/2 - 11} cy={pos.y - H/2 + 11} r={4} fill="none" stroke={colors.wire} strokeWidth={1.5}>
          <animate attributeName="r" values="4;9;4" dur={health.level === "red" ? "0.8s" : "2s"} repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.9;0;0.9" dur={health.level === "red" ? "0.8s" : "2s"} repeatCount="indefinite" />
        </circle>
      )}

      {/* Center separator line */}
      <line x1={pos.x - W/2 + 10} y1={pos.y - 4} x2={pos.x + W/2 - 10} y2={pos.y - 4}
        stroke={colors.wire} strokeWidth={0.5} opacity={0.25} />

      {/* Content */}
      <foreignObject x={pos.x - W/2} y={pos.y - H/2} width={W} height={H}>
        <div className="w-full h-full flex flex-col items-center justify-center px-3 gap-1" style={{ fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
          {/* Icon in circle */}
          <div className="flex items-center justify-center h-6 w-6 rounded-full" style={{ background: colors.fill, border: `1px solid ${colors.stroke}` }}>
            <Icon style={{ height: 12, width: 12, color: colors.wire }} />
          </div>
          {/* Label */}
          <div className="text-center leading-tight font-bold tracking-wide uppercase"
            style={{ fontSize: 9, color: colors.wire, textShadow: `0 0 8px ${colors.wire}` }}>
            {health.label.split("(")[0].trim()}
          </div>
          {/* Metric */}
          <div className="font-mono text-center" style={{ fontSize: 8, color: "rgba(148,163,184,0.6)" }}>
            {metric}
          </div>
        </div>
      </foreignObject>
    </g>
  );
}

/* ── Active Alerts Digest + Fix Buttons ─────────────────────────────────── */
function AlertsDigest({
  nodes,
  onFix,
  fixingComponent,
  onHealAll,
  healAllLoading,
  lastHealResults,
}: {
  nodes: Record<string, NodeHealth>;
  onFix: (component: string) => void;
  fixingComponent: string | null;
  onHealAll: () => void;
  healAllLoading: boolean;
  lastHealResults: Record<string, { success: boolean; result: string }>;
}) {
  const alerts = useMemo(() => {
    return Object.entries(nodes)
      .filter(([, n]) => n.level !== "green")
      .sort(([, a], [, b]) => (a.level === "red" ? -1 : b.level === "red" ? 1 : 0));
  }, [nodes]);

  const [expanded, setExpanded] = useState<string | null>(null);
  const criticalCount = alerts.filter(([, n]) => n.level === "red").length;
  const degradedCount = alerts.filter(([, n]) => n.level === "yellow").length;

  if (alerts.length === 0) {
    return (
      <div className="flex items-center gap-2.5 px-5 py-3 border-t border-white/5 bg-green-500/5">
        <CheckCircle2 className="h-4 w-4 text-green-400 shrink-0" />
        <span className="text-[11px] font-mono text-green-400">All systems nominal — no active alerts.</span>
      </div>
    );
  }

  return (
    <div className="border-t border-white/8 bg-slate-950/80 shrink-0">
      {/* digest header with Heal All button */}
      <div className="flex items-center gap-2 px-5 py-2 border-b border-white/5">
        <AlertTriangle className="h-3.5 w-3.5 text-yellow-400 shrink-0" />
        <span className="text-[9px] font-mono uppercase tracking-widest text-muted-foreground/60 font-semibold">
          Active Alerts
        </span>
        <span className="ml-1 text-[9px] font-mono text-muted-foreground/40">
          {criticalCount > 0 && <span className="text-red-400">{criticalCount} critical</span>}
          {criticalCount > 0 && degradedCount > 0 && <span className="text-muted-foreground/40"> · </span>}
          {degradedCount > 0 && <span className="text-yellow-400">{degradedCount} degraded</span>}
        </span>
        <button
          onClick={onHealAll}
          disabled={healAllLoading}
          className={cn(
            "ml-auto flex items-center gap-1.5 px-3 py-1 rounded-lg text-[9px] font-mono font-semibold transition-all border",
            healAllLoading
              ? "border-violet-500/30 text-violet-400/60 bg-violet-500/5 cursor-not-allowed"
              : "border-violet-500/40 text-violet-400 bg-violet-500/10 hover:bg-violet-500/20 hover:border-violet-400/60"
          )}
        >
          <Zap className={cn("h-3 w-3", healAllLoading && "animate-pulse")} />
          {healAllLoading ? "Healing…" : "⚡ Heal All"}
        </button>
      </div>

      {/* alert rows */}
      <div className="max-h-52 overflow-y-auto divide-y divide-white/[0.04]">
        {alerts.map(([key, node]) => {
          const colors = LEVEL_COLORS[node.level];
          const explanation = buildExplanation(key, node);
          const isOpen = expanded === key;
          const Icon = node.level === "red" ? XCircle : AlertTriangle;
          const isFixing = fixingComponent === key;
          const healResult = lastHealResults[key];

          return (
            <div key={key} className={cn("transition-colors", isOpen && "bg-white/[0.02]")}>
              <div className="flex items-start gap-3 px-5 py-2.5">
                {/* level icon */}
                <button
                  onClick={() => setExpanded(isOpen ? null : key)}
                  className="flex-1 text-left flex items-start gap-3 min-w-0"
                >
                  <Icon
                    className={cn("h-3.5 w-3.5 mt-0.5 shrink-0", colors.text, node.level === "red" && "animate-pulse")}
                  />

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={cn("text-[10px] font-semibold font-mono", colors.text)}>
                        {node.label.split("(")[0].trim()}
                      </span>
                      <span className={cn("text-[8px] font-mono px-1.5 py-0.5 rounded border uppercase tracking-wider", colors.bg, colors.text, colors.border)}>
                        {node.level === "green" ? "OK" : node.level === "yellow" ? "DEGRADED" : "CRITICAL"}
                      </span>
                      {node.latency_ms != null && (
                        <span className="text-[8px] font-mono text-muted-foreground/50">{node.latency_ms}ms</span>
                      )}
                      {node.data_age_s != null && node.latency_ms == null && (
                        <span className="text-[8px] font-mono text-muted-foreground/50">{node.data_age_s.toFixed(0)}s old</span>
                      )}
                      {/* heal result badge */}
                      {healResult && (
                        <span className={cn(
                          "text-[8px] font-mono px-1.5 py-0.5 rounded-full border flex items-center gap-1",
                          healResult.success
                            ? "text-green-400 bg-green-500/10 border-green-500/20"
                            : "text-red-400 bg-red-500/10 border-red-500/20"
                        )}>
                          {healResult.success ? "✓ healed" : "✗ failed"}
                        </span>
                      )}
                    </div>
                    <div className="text-[9px] text-muted-foreground/60 font-mono mt-0.5 truncate">{node.detail}</div>

                    {/* expanded explanation + heal result */}
                    {isOpen && (
                      <div className="mt-2 space-y-1.5">
                        <div className={cn("text-[10px] leading-relaxed rounded-lg px-3 py-2 border", colors.bg, colors.border, colors.text)}>
                          <div className="flex gap-1.5">
                            <Info className="h-3 w-3 mt-0.5 shrink-0 opacity-70" />
                            <span>{explanation}</span>
                          </div>
                        </div>
                        {healResult && (
                          <div className={cn(
                            "text-[9px] font-mono rounded-lg px-3 py-1.5 border leading-relaxed",
                            healResult.success
                              ? "bg-green-500/5 border-green-500/20 text-green-400/80"
                              : "bg-red-500/5 border-red-500/20 text-red-400/80"
                          )}>
                            <span className="font-semibold">{healResult.success ? "✓ Healed: " : "✗ Failed: "}</span>
                            {healResult.result}
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  <span className="text-[8px] text-muted-foreground/30 hover:text-muted-foreground/60 transition-colors mt-0.5 font-mono shrink-0">
                    {isOpen ? "▲" : "▼"}
                  </span>
                </button>

                {/* Fix button */}
                <button
                  onClick={() => onFix(key)}
                  disabled={isFixing || healAllLoading}
                  className={cn(
                    "shrink-0 flex items-center gap-1 px-2 py-1 rounded-md text-[9px] font-mono font-semibold transition-all border mt-0.5",
                    isFixing
                      ? "border-cyan-500/30 text-cyan-400/60 bg-cyan-500/5 cursor-not-allowed"
                      : healResult?.success
                      ? "border-green-500/30 text-green-400 bg-green-500/5 hover:bg-green-500/10"
                      : "border-cyan-500/30 text-cyan-400 bg-cyan-500/5 hover:bg-cyan-500/15 hover:border-cyan-400/50"
                  )}
                >
                  {isFixing ? (
                    <><RotateCcw className="h-2.5 w-2.5 animate-spin" /> fixing…</>
                  ) : healResult?.success ? (
                    <><CheckCircle2 className="h-2.5 w-2.5" /> fixed</>
                  ) : (
                    <>Fix →</>
                  )}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Remediation Log Panel ───────────────────────────────────────────────── */
const HEAL_TYPE_STYLES: Record<string, string> = {
  HEALED: "text-green-400 border-green-500/30 bg-green-500/10",
  LOGGED: "text-blue-400 border-blue-500/30 bg-blue-500/10",
  FAILED: "text-red-400 border-red-500/30 bg-red-500/10",
};

function RemediationLog({ log }: { log: HealEntry[] }) {
  if (log.length === 0) return null;

  return (
    <div className="border-t border-white/5 bg-slate-950/60 shrink-0">
      <div className="flex items-center gap-2 px-5 py-1.5 border-b border-white/5">
        <Clock className="h-3 w-3 text-muted-foreground/40" />
        <span className="text-[9px] font-mono uppercase tracking-widest text-muted-foreground/40 font-semibold">Heal Log</span>
        <span className="text-[8px] font-mono text-muted-foreground/30 ml-auto">{log.length} entr{log.length === 1 ? "y" : "ies"}</span>
      </div>
      <div className="max-h-28 overflow-y-auto divide-y divide-white/[0.03]">
        {log.map((entry, i) => {
          const label = COMPONENT_LABELS[entry.component] ?? entry.component;
          const byLabel = entry.triggered_by === "auto_heal" ? "auto" : entry.triggered_by === "heal_all" ? "heal-all" : "manual";
          const timeStr = new Date(entry.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
          const healType = entry.heal_type ?? (entry.success ? "HEALED" : "FAILED");
          const healTypeStyle = HEAL_TYPE_STYLES[healType] ?? "text-slate-400 border-white/10 bg-white/5";
          return (
            <div key={i} className="flex items-center gap-2 px-5 py-1.5 flex-wrap">
              <span className="text-[8px] font-mono text-muted-foreground/50 shrink-0 w-16">{timeStr}</span>
              <span className={cn("text-[7px] font-mono font-bold shrink-0 px-1.5 py-px rounded border uppercase tracking-wider", healTypeStyle)}>
                {healType}
              </span>
              <span className={cn("text-[7px] font-mono shrink-0 px-1 py-px rounded border",
                entry.triggered_by === "auto_heal"
                  ? "text-violet-400 border-violet-500/20 bg-violet-500/5"
                  : "text-cyan-400/60 border-cyan-500/15 bg-cyan-500/5"
              )}>
                {byLabel}
              </span>
              <span className="text-[8px] font-mono text-white/60 shrink-0">{label}</span>
              <span className="text-[8px] font-mono text-muted-foreground/40 truncate flex-1">{entry.result}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Test Control Panel ─────────────────────────────────────────────────── */
function TestControlPanel({
  overrides,
  setOverrides,
  resetOverrides,
}: {
  overrides: Overrides;
  setOverrides: React.Dispatch<React.SetStateAction<Overrides>>;
  resetOverrides: () => void;
}) {
  const [showPanel, setShowPanel] = useState(false);

  const updateNode = (key: string, field: string, value: any) => {
    setOverrides((prev) => ({
      ...prev,
      [key]: { ...(prev[key] || {}), [field]: value },
    }));
  };

  const forceLevel = (key: string, level: Level) => {
    setOverrides((prev) => ({
      ...prev,
      [key]: { ...(prev[key] || {}), level },
    }));
  };

  const applyScenario = (name: string) => {
    const scenarios: Record<string, Overrides> = {
      "all-green": {},
      "http-404": {
        alpaca_api: { level: "red", detail: "HTTP 404 Not Found", latency_ms: 0 },
      },
      "http-500": {
        platform_core: { level: "red", detail: "HTTP 500 Internal Server Error" },
        alpaca_api: { level: "red", detail: "HTTP 500 Server Error", latency_ms: 0 },
      },
      "rate-limit": {
        alpaca_api: { level: "yellow", detail: "HTTP 429 Rate Limited", latency_ms: 350 },
        kraken_api: { level: "yellow", detail: "Rate limit warning (3/min)", latency_ms: 450 },
      },
      "high-latency": {
        alpaca_api: { level: "yellow", latency_ms: 500, detail: "Latency 500ms > 200ms threshold" },
        kraken_api: { level: "yellow", latency_ms: 800, detail: "Latency 800ms > 200ms threshold" },
        data_pipeline: { level: "yellow", data_age_s: 120, detail: "Data 120s old > 60s threshold" },
      },
      "stale-data": {
        data_pipeline: { level: "red", data_age_s: 700, detail: "Data 700s old > 600s CRITICAL" },
        kraken_api: { level: "red", data_age_s: 2100, detail: "Status 2100s old > 1800s CRITICAL" },
      },
      "alloc-breach": {
        equity_manager: { level: "red", detail: "BREACH: single position 18.4% > 15.00% limit" },
      },
      "total-failure": {
        platform_core: { level: "red", detail: "Scheduler crashed — 0/10 jobs" },
        alpaca_api: { level: "red", latency_ms: 5000, detail: "Connection timeout (5000ms)" },
        kraken_api: { level: "red", detail: "HTTP 503 Service Unavailable" },
        data_pipeline: { level: "red", data_age_s: 900, detail: "All feeds stale > 600s" },
        equity_manager: { level: "red", detail: "Cannot validate — API unreachable" },
        rag_engine: { level: "red", detail: "DB error: connection refused" },
        options_bot: { level: "red", detail: "Options engine crashed — no heartbeat" },
        forex_bot: { level: "red", detail: "Forex engine unreachable — import error" },
        alert_system: { level: "red", detail: "Alert dispatch failed — queue overflow" },
      },
    };
    if (name === "all-green") {
      resetOverrides();
    } else {
      setOverrides(scenarios[name] ?? {});
    }
  };

  if (!showPanel) {
    return (
      <button
        onClick={() => setShowPanel(true)}
        className="absolute bottom-4 right-4 px-3 py-1.5 text-[10px] font-mono bg-slate-800 border border-white/10 rounded-lg text-muted-foreground hover:text-white hover:border-white/20 transition-colors"
      >
        Test Controls
      </button>
    );
  }

  return (
    <div className="absolute bottom-4 right-4 w-80 bg-slate-900/95 border border-white/10 rounded-xl p-3 backdrop-blur-lg max-h-[70vh] overflow-y-auto">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground font-semibold">Test Controls</span>
        <div className="flex gap-2">
          <button
            onClick={resetOverrides}
            className="text-[9px] font-mono px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 hover:bg-blue-500/20"
          >
            Reset
          </button>
          <button onClick={() => setShowPanel(false)} className="text-muted-foreground hover:text-white">
            <X className="h-3 w-3" />
          </button>
        </div>
      </div>

      <div className="mb-3 pb-3 border-b border-white/5">
        <div className="text-[8px] font-mono text-muted-foreground/50 uppercase tracking-wider mb-1.5">Scenario Presets</div>
        <div className="grid grid-cols-2 gap-1">
          {[
            { id: "all-green", label: "All Optimal", color: "text-green-400 bg-green-500/10 border-green-500/20" },
            { id: "http-404", label: "Simulate 404", color: "text-red-400 bg-red-500/10 border-red-500/20" },
            { id: "http-500", label: "Simulate 500", color: "text-red-400 bg-red-500/10 border-red-500/20" },
            { id: "rate-limit", label: "Rate Limited", color: "text-yellow-400 bg-yellow-500/10 border-yellow-500/20" },
            { id: "high-latency", label: "High Latency", color: "text-yellow-400 bg-yellow-500/10 border-yellow-500/20" },
            { id: "stale-data", label: "Stale Data", color: "text-red-400 bg-red-500/10 border-red-500/20" },
            { id: "alloc-breach", label: "Alloc >15%", color: "text-red-400 bg-red-500/10 border-red-500/20" },
            { id: "total-failure", label: "Total Failure", color: "text-red-400 bg-red-500/10 border-red-500/20" },
          ].map((s) => (
            <button
              key={s.id}
              onClick={() => applyScenario(s.id)}
              className={cn("text-[8px] font-mono py-1 px-2 rounded border transition-colors hover:opacity-80", s.color)}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      <div className="text-[8px] font-mono text-muted-foreground/50 uppercase tracking-wider mb-1.5">Per-Node Overrides</div>
      <div className="space-y-3">
        {Object.entries(NODE_POSITIONS).map(([key]) => (
          <div key={key} className="space-y-1">
            <div className="text-[9px] font-mono text-white/60">{key.replace(/_/g, " ")}</div>
            <div className="flex gap-1">
              {(["green", "yellow", "red"] as Level[]).map((lvl) => (
                <button
                  key={lvl}
                  onClick={() => forceLevel(key, lvl)}
                  className={cn(
                    "flex-1 text-[8px] font-mono py-1 rounded border transition-colors",
                    overrides[key]?.level === lvl
                      ? `${LEVEL_COLORS[lvl].bg} ${LEVEL_COLORS[lvl].text} border-current`
                      : "bg-transparent text-muted-foreground/40 border-white/5 hover:border-white/15"
                  )}
                >
                  {lvl}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[8px] text-muted-foreground/40 w-10">Lat:</span>
              <input
                type="range" min={0} max={2000} step={50} defaultValue={0}
                onChange={(e) => updateNode(key, "latency_ms", parseInt(e.target.value))}
                className="flex-1 h-1 accent-cyan-500 cursor-pointer"
              />
              <span className="text-[8px] font-mono text-muted-foreground w-12 text-right">
                {overrides[key]?.latency_ms ?? 0}ms
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[8px] text-muted-foreground/40 w-10">Age:</span>
              <input
                type="range" min={0} max={600} step={10} defaultValue={0}
                onChange={(e) => updateNode(key, "data_age_s", parseInt(e.target.value))}
                className="flex-1 h-1 accent-cyan-500 cursor-pointer"
              />
              <span className="text-[8px] font-mono text-muted-foreground w-12 text-right">
                {overrides[key]?.data_age_s ?? 0}s
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Main Modal ─────────────────────────────────────────────────────────── */
export function SystemHealthModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery<HealthData>({
    queryKey: ["/system/health-architecture"],
    queryFn: async () => (await api.get("/system/health-architecture")).data,
    refetchInterval: 10_000,
    retry: false,
  });

  const { data: logData } = useQuery({
    queryKey: ["/system/remediate/log"],
    queryFn: async () => (await api.get("/system/remediate/log")).data,
    refetchInterval: 5_000,
    retry: false,
  });

  const [overrides, setOverrides] = useState<Overrides>({});
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [fixingComponent, setFixingComponent] = useState<string | null>(null);
  const [healAllLoading, setHealAllLoading] = useState(false);
  const [lastHealResults, setLastHealResults] = useState<Record<string, { success: boolean; result: string }>>({});
  const resetOverrides = useCallback(() => setOverrides({}), []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const mergedNodes = useMemo(() => {
    if (!data?.nodes) return null;
    const merged: Record<string, NodeHealth> = {};
    for (const [key, node] of Object.entries(data.nodes)) {
      const ov = overrides[key];
      merged[key] = ov ? { ...node, ...ov } : node;
    }
    return merged;
  }, [data, overrides]);

  const overallLevel: Level = useMemo(() => {
    if (!mergedNodes) return "yellow";
    const levels = Object.values(mergedNodes).map((n) => n.level);
    if (levels.includes("red")) return "red";
    if (levels.includes("yellow")) return "yellow";
    return "green";
  }, [mergedNodes]);

  const overallColors = LEVEL_COLORS[overallLevel];
  const hasOverrides = Object.keys(overrides).length > 0;
  const selectedHealth = selectedNode && mergedNodes ? mergedNodes[selectedNode] : null;

  const handleFix = useCallback(async (component: string) => {
    setFixingComponent(component);
    try {
      const res = await api.post(`/system/remediate/${component}`);
      const result = res.data as { success: boolean; result: string };
      setLastHealResults(prev => ({ ...prev, [component]: { success: result.success, result: result.result } }));
      queryClient.invalidateQueries({ queryKey: ["/system/remediate/log"] });
      queryClient.invalidateQueries({ queryKey: ["/system/health-architecture"] });
    } catch (err) {
      setLastHealResults(prev => ({ ...prev, [component]: { success: false, result: `Request failed: ${err}` } }));
    } finally {
      setFixingComponent(null);
    }
  }, [queryClient]);

  const handleHealAll = useCallback(async () => {
    setHealAllLoading(true);
    try {
      const res = await api.post("/system/remediate/all");
      const result = res.data as { success: boolean; results: Array<{ component: string; success: boolean; result: string }> };
      const newResults: Record<string, { success: boolean; result: string }> = {};
      for (const r of result.results) {
        newResults[r.component] = { success: r.success, result: r.result };
      }
      setLastHealResults(prev => ({ ...prev, ...newResults }));
      queryClient.invalidateQueries({ queryKey: ["/system/remediate/log"] });
      queryClient.invalidateQueries({ queryKey: ["/system/health-architecture"] });
    } catch (err) {
      console.error("Heal all failed:", err);
    } finally {
      setHealAllLoading(false);
    }
  }, [queryClient]);

  const healLog: HealEntry[] = logData?.log ?? [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm" onClick={onClose}>
      <div
        className="relative w-[92vw] h-[92vh] max-w-5xl rounded-2xl shadow-2xl flex flex-col overflow-hidden"
        style={{
          background: "radial-gradient(ellipse at 30% 0%, rgba(8,18,38,1) 0%, rgba(2,6,18,1) 100%)",
          border: `1px solid ${overallColors.stroke}`,
          boxShadow: `0 0 80px ${overallColors.glow}, 0 0 0 1px rgba(255,255,255,0.04) inset`,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* ── Header ── */}
        <div className="flex items-center justify-between px-5 py-3 shrink-0"
          style={{ borderBottom: `1px solid ${overallColors.stroke}30`, background: `${overallColors.wire}06` }}>
          <div className="flex items-center gap-3">
            {/* Animated radar icon */}
            <div className="relative h-8 w-8 flex items-center justify-center shrink-0">
              <div className="absolute inset-0 rounded-full animate-ping opacity-20"
                style={{ background: overallColors.wire }} />
              <Activity className={cn("h-4 w-4 relative z-10", overallColors.text)} />
            </div>
            <div>
              <div className="text-[11px] font-mono uppercase tracking-[0.25em]"
                style={{ color: overallColors.wire, textShadow: `0 0 10px ${overallColors.wire}` }}>
                SYS / HEALTH / ARCHITECTURE
              </div>
              <div className="flex items-center gap-2 mt-0.5">
                <span className={cn("h-1.5 w-1.5 rounded-full", {
                  "bg-green-400": overallLevel === "green",
                  "bg-yellow-400 animate-pulse": overallLevel === "yellow",
                  "bg-red-400 animate-pulse": overallLevel === "red",
                })} />
                <span className="text-[9px] font-mono text-muted-foreground/50 uppercase tracking-widest">
                  {overallLevel === "green" ? "All systems nominal" : overallLevel === "yellow" ? "Degraded — self-heal active" : "Critical — auto-remediating"}
                </span>
              </div>
            </div>
            {hasOverrides && (
              <span className="text-[8px] font-mono px-2 py-0.5 rounded bg-orange-500/15 text-orange-400 border border-orange-500/20 uppercase tracking-widest">
                Test Mode
              </span>
            )}
            {overallLevel !== "green" && (
              <span className="text-[8px] font-mono px-2 py-0.5 rounded flex items-center gap-1 uppercase tracking-widest"
                style={{ background: `${overallColors.wire}12`, color: overallColors.wire, border: `1px solid ${overallColors.wire}30` }}>
                <Zap className="h-2.5 w-2.5" />
                self-heal active
              </span>
            )}
          </div>
          <button onClick={onClose}
            className="p-2 rounded-lg text-muted-foreground hover:text-white transition-colors"
            style={{ border: "1px solid rgba(255,255,255,0.08)" }}>
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* ── Body (diagram) ── */}
        <div className="flex-1 relative overflow-hidden min-h-0">
          {isLoading || !mergedNodes ? (
            <div className="flex items-center justify-center h-full gap-3">
              <div className="h-2 w-2 rounded-full bg-green-400 animate-bounce" style={{ animationDelay: "0ms" }} />
              <div className="h-2 w-2 rounded-full bg-green-400 animate-bounce" style={{ animationDelay: "150ms" }} />
              <div className="h-2 w-2 rounded-full bg-green-400 animate-bounce" style={{ animationDelay: "300ms" }} />
              <span className="text-muted-foreground text-xs font-mono ml-1">Scanning subsystems…</span>
            </div>
          ) : (
            <>
              {/* Legend — top-left */}
              <div className="absolute top-3 left-5 flex items-center gap-4 z-10">
                {(["green", "yellow", "red"] as Level[]).map((lvl) => (
                  <div key={lvl} className="flex items-center gap-1.5">
                    <span className={cn("h-2 w-2 rounded-full", {
                      "bg-green-400": lvl === "green",
                      "bg-yellow-400": lvl === "yellow",
                      "bg-red-400": lvl === "red",
                    })} style={{ boxShadow: `0 0 6px ${LEVEL_COLORS[lvl].wire}` }} />
                    <span className="text-[8px] font-mono uppercase tracking-widest"
                      style={{ color: LEVEL_COLORS[lvl].wire, opacity: 0.7 }}>
                      {lvl === "green" ? "Optimal" : lvl === "yellow" ? "Degraded" : "Critical"}
                    </span>
                  </div>
                ))}
              </div>

              {/* SVG Diagram */}
              <svg viewBox="0 0 800 620" className="w-full h-full" preserveAspectRatio="xMidYMid meet">
                <defs>
                  {/* Dot grid */}
                  <pattern id="dots" x="0" y="0" width="30" height="30" patternUnits="userSpaceOnUse">
                    <circle cx="1" cy="1" r="1" fill="rgba(255,255,255,0.05)" />
                  </pattern>
                  {/* Radial mask so grid fades at edges */}
                  <radialGradient id="gridFade" cx="50%" cy="50%" r="55%">
                    <stop offset="0%" stopColor="white" stopOpacity="1" />
                    <stop offset="100%" stopColor="white" stopOpacity="0" />
                  </radialGradient>
                  <mask id="gridMask">
                    <rect width="800" height="620" fill="url(#gridFade)" />
                  </mask>
                </defs>

                {/* Grid background */}
                <rect width="800" height="620" fill="url(#dots)" mask="url(#gridMask)" />

                {/* Horizontal scan line */}
                <line x1="0" y1="0" x2="800" y2="0" stroke={overallColors.wire} strokeWidth="1.5" opacity="0.12">
                  <animate attributeName="y1" values="0;620;0" dur="5s" repeatCount="indefinite" />
                  <animate attributeName="y2" values="0;620;0" dur="5s" repeatCount="indefinite" />
                </line>

                {/* Wires (drawn first, under nodes) */}
                {WIRES.map((wire, i) => {
                  const fromPos = NODE_POSITIONS[wire.from];
                  const toPos = NODE_POSITIONS[wire.to];
                  const fromNode = mergedNodes[wire.from];
                  const toNode = mergedNodes[wire.to];
                  if (!fromPos || !toPos) return null;
                  const fromLevel = fromNode?.level ?? "green";
                  const toLevel = toNode?.level ?? "green";
                  const worstLevel: Level =
                    fromLevel === "red" || toLevel === "red" ? "red"
                    : fromLevel === "yellow" || toLevel === "yellow" ? "yellow"
                    : "green";
                  return (
                    <GlowingWire key={i}
                      x1={fromPos.x} y1={fromPos.y}
                      x2={toPos.x}   y2={toPos.y}
                      bend={wire.bend ?? "v-first"}
                      level={worstLevel} id={`wire-${i}`} />
                  );
                })}

                {/* Nodes */}
                {Object.entries(mergedNodes).map(([key, health]) => (
                  <ArchitectureNode key={key} nodeKey={key} health={health}
                    selected={selectedNode === key}
                    onClick={() => setSelectedNode(selectedNode === key ? null : key)} />
                ))}
              </svg>

              {/* Per-bot Kraken Fleet Panel */}
              {(() => {
                const perBotNodes = Object.entries(mergedNodes).filter(
                  ([k]) => k.startsWith("kraken_") && k !== "kraken_api"
                );
                if (perBotNodes.length === 0) return null;
                const BOT_DISPLAY: Record<string, string> = {
                  kraken_davy_jones: "SPY/QQQ Trend",
                  kraken_blackbeard: "Jerome",
                  kraken_poseidon: "Poseidon",
                  kraken_kraken_current: "Kraken Current",
                };
                return (
                  <div className="absolute top-3 right-5 z-10 flex flex-col gap-1.5"
                    style={{ minWidth: 140 }}>
                    <div className="text-[8px] font-mono uppercase tracking-widest text-muted-foreground/40 mb-0.5">
                      Bot Fleet
                    </div>
                    {perBotNodes.map(([key, node]) => {
                      const colors = LEVEL_COLORS[node.level];
                      const botLabel = BOT_DISPLAY[key] ?? key.replace("kraken_", "").replace(/_/g, " ");
                      const kickPending = (node as NodeHealth & { kick_pending?: boolean }).kick_pending;
                      return (
                        <div key={key} className="flex items-center gap-2 px-2 py-1 rounded-lg backdrop-blur-sm"
                          style={{
                            background: colors.fill,
                            border: `1px solid ${colors.stroke}`,
                          }}>
                          <span className="h-1.5 w-1.5 rounded-full shrink-0"
                            style={{ background: colors.wire, boxShadow: `0 0 5px ${colors.wire}` }} />
                          <span className="text-[8px] font-mono font-semibold flex-1 capitalize"
                            style={{ color: colors.wire }}>
                            {botLabel}
                          </span>
                          {kickPending && (
                            <span className="text-[7px] font-mono px-1 py-px rounded border text-orange-400 border-orange-500/30 bg-orange-500/10">
                              KICK
                            </span>
                          )}
                          <span className="text-[7px] font-mono uppercase"
                            style={{ color: colors.wire, opacity: 0.7 }}>
                            {node.level === "green" ? "OK" : node.level === "yellow" ? "WARN" : "ERR"}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                );
              })()}

              {/* Selected Node Detail Panel */}
              {selectedHealth && (
                <div className="absolute bottom-3 left-4 max-w-[260px] rounded-xl p-3 backdrop-blur-lg"
                  style={{
                    background: "rgba(4,10,24,0.95)",
                    border: `1px solid ${LEVEL_COLORS[selectedHealth.level].stroke}`,
                    boxShadow: `0 0 20px ${LEVEL_COLORS[selectedHealth.level].glow}`,
                  }}>
                  {/* Corner accent */}
                  <div className="absolute top-0 left-0 w-3 h-3 border-t-2 border-l-2 rounded-tl-xl"
                    style={{ borderColor: LEVEL_COLORS[selectedHealth.level].wire }} />
                  <div className="absolute bottom-0 right-0 w-3 h-3 border-b-2 border-r-2 rounded-br-xl"
                    style={{ borderColor: LEVEL_COLORS[selectedHealth.level].wire }} />
                  <div className="text-[10px] font-bold font-mono uppercase tracking-wider mb-1"
                    style={{ color: LEVEL_COLORS[selectedHealth.level].wire }}>
                    {selectedHealth.label}
                  </div>
                  <div className="text-[9px] font-mono text-slate-400/80">{selectedHealth.detail}</div>
                  {selectedHealth.level !== "green" && (
                    <div className="text-[9px] mt-2 leading-relaxed font-mono"
                      style={{ color: LEVEL_COLORS[selectedHealth.level].wire, opacity: 0.85 }}>
                      {buildExplanation(selectedNode!, selectedHealth)}
                    </div>
                  )}
                </div>
              )}

              <TestControlPanel overrides={overrides} setOverrides={setOverrides} resetOverrides={resetOverrides} />
            </>
          )}
        </div>

        {/* ── Alerts + Fix Buttons ── */}
        {mergedNodes && (
          <AlertsDigest
            nodes={mergedNodes}
            onFix={handleFix}
            fixingComponent={fixingComponent}
            onHealAll={handleHealAll}
            healAllLoading={healAllLoading}
            lastHealResults={lastHealResults}
          />
        )}

        {/* ── Remediation Log ── */}
        <RemediationLog log={healLog} />
      </div>
    </div>
  );
}
