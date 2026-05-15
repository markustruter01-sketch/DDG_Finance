import { useState, useEffect, useMemo } from "react";
import { Activity, Server, Shield, Database, Anchor, AlertTriangle, CheckCircle2, XCircle, Clock, Brain, Globe, Target, Bell, Wifi, Zap } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { DDGBadge } from "@/components/DDGBadge";

const API_PREFIX = import.meta.env.VITE_API_PREFIX ?? "/trading-api";
const api = {
  get: async (path: string) => {
    const res = await fetch(`${API_PREFIX}${path}`);
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
  kick_pending?: boolean;
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

const BOT_DISPLAY: Record<string, string> = {
  kraken_davy_jones: "SPY/QQQ Trend",
  kraken_blackbeard: "Jerome",
  kraken_poseidon: "Poseidon",
  kraken_kraken_current: "Kraken Current",
};

const HEAL_TYPE_STYLES: Record<string, string> = {
  HEALED: "text-green-400 border-green-500/30 bg-green-500/10",
  LOGGED: "text-blue-400 border-blue-500/30 bg-blue-500/10",
  FAILED: "text-red-400 border-red-500/30 bg-red-500/10",
};

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
      <path d={pathD} fill="none" stroke={colors.wire} strokeWidth={3} opacity={0.95}
        strokeDasharray={`12 ${totalLen}`} strokeLinecap="round">
        <animate attributeName="stroke-dashoffset" from={totalLen + 12} to={-(totalLen)} dur={dur} repeatCount="indefinite" />
      </path>
      <path d={pathD} fill="none" stroke={colors.wire} strokeWidth={2} opacity={0.5}
        strokeDasharray={`6 ${totalLen}`} strokeLinecap="round">
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

function ArchitectureNode({ nodeKey, health }: { nodeKey: string; health: NodeHealth }) {
  const pos = NODE_POSITIONS[nodeKey];
  if (!pos) return null;
  const colors = LEVEL_COLORS[health.level];
  const Icon = pos.icon;
  const W = NODE_W;
  const H = NODE_H;
  const cs = 14;

  const metric = health.latency_ms != null
    ? `${health.latency_ms}ms`
    : health.data_age_s != null
    ? `${health.data_age_s.toFixed(0)}s`
    : "—";

  return (
    <g>
      {health.level !== "green" && (
        <ellipse cx={pos.x} cy={pos.y} rx={W / 2 + 16} ry={H / 2 + 14}
          fill="none" stroke={colors.wire} strokeWidth={1}>
          <animate attributeName="rx" values={`${W/2+10};${W/2+22};${W/2+10}`} dur={health.level === "red" ? "1s" : "2.5s"} repeatCount="indefinite" />
          <animate attributeName="ry" values={`${H/2+8};${H/2+18};${H/2+8}`} dur={health.level === "red" ? "1s" : "2.5s"} repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.5;0;0.5" dur={health.level === "red" ? "1s" : "2.5s"} repeatCount="indefinite" />
        </ellipse>
      )}
      <rect x={pos.x - W/2} y={pos.y - H/2} width={W} height={H} rx={8}
        fill={colors.fill} stroke={colors.stroke} strokeWidth={1.2} />
      {health.level === "red" && (
        <rect x={pos.x - W/2} y={pos.y - H/2} width={W} height={H} rx={8}
          fill="none" stroke={colors.stroke} strokeWidth={2.5}>
          <animate attributeName="opacity" values="1;0.15;1" dur="0.9s" repeatCount="indefinite" />
        </rect>
      )}
      <path d={`M ${pos.x-W/2} ${pos.y-H/2+cs} L ${pos.x-W/2} ${pos.y-H/2} L ${pos.x-W/2+cs} ${pos.y-H/2}`}
        fill="none" stroke={colors.wire} strokeWidth={2} opacity={0.9} />
      <path d={`M ${pos.x+W/2-cs} ${pos.y-H/2} L ${pos.x+W/2} ${pos.y-H/2} L ${pos.x+W/2} ${pos.y-H/2+cs}`}
        fill="none" stroke={colors.wire} strokeWidth={2} opacity={0.9} />
      <path d={`M ${pos.x-W/2} ${pos.y+H/2-cs} L ${pos.x-W/2} ${pos.y+H/2} L ${pos.x-W/2+cs} ${pos.y+H/2}`}
        fill="none" stroke={colors.wire} strokeWidth={2} opacity={0.9} />
      <path d={`M ${pos.x+W/2-cs} ${pos.y+H/2} L ${pos.x+W/2} ${pos.y+H/2} L ${pos.x+W/2} ${pos.y+H/2-cs}`}
        fill="none" stroke={colors.wire} strokeWidth={2} opacity={0.9} />
      <circle cx={pos.x + W/2 - 11} cy={pos.y - H/2 + 11} r={4} fill={colors.wire} opacity={0.95} />
      {health.level !== "green" && (
        <circle cx={pos.x + W/2 - 11} cy={pos.y - H/2 + 11} r={4} fill="none" stroke={colors.wire} strokeWidth={1.5}>
          <animate attributeName="r" values="4;9;4" dur={health.level === "red" ? "0.8s" : "2s"} repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.9;0;0.9" dur={health.level === "red" ? "0.8s" : "2s"} repeatCount="indefinite" />
        </circle>
      )}
      <line x1={pos.x - W/2 + 10} y1={pos.y - 4} x2={pos.x + W/2 - 10} y2={pos.y - 4}
        stroke={colors.wire} strokeWidth={0.5} opacity={0.25} />
      <foreignObject x={pos.x - W/2} y={pos.y - H/2} width={W} height={H}>
        <div className="w-full h-full flex flex-col items-center justify-center px-3 gap-1" style={{ fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
          <div className="flex items-center justify-center h-6 w-6 rounded-full" style={{ background: colors.fill, border: `1px solid ${colors.stroke}` }}>
            <Icon style={{ height: 12, width: 12, color: colors.wire }} />
          </div>
          <div className="text-center leading-tight font-bold tracking-wide uppercase"
            style={{ fontSize: 9, color: colors.wire, textShadow: `0 0 8px ${colors.wire}` }}>
            {health.label.split("(")[0].trim()}
          </div>
          <div className="font-mono text-center" style={{ fontSize: 8, color: "rgba(148,163,184,0.6)" }}>
            {metric}
          </div>
        </div>
      </foreignObject>
    </g>
  );
}

/* ── Per-Bot Fleet Strip ──────────────────────────────────────────────────── */
function PerBotFleetStrip({ nodes }: { nodes: Record<string, NodeHealth> }) {
  const perBotNodes = Object.entries(nodes).filter(
    ([k]) => k.startsWith("kraken_") && k !== "kraken_api"
  );
  if (perBotNodes.length === 0) return null;

  return (
    <div style={{ borderTop: "1px solid rgba(255,255,255,0.05)", background: "rgba(2,6,23,0.92)" }}>
      <div className="flex items-center gap-2 px-5 py-1.5" style={{ borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
        <Anchor className="h-2.5 w-2.5" style={{ color: "rgba(148,163,184,0.35)" }} />
        <span className="text-[7px] font-mono uppercase tracking-widest font-semibold" style={{ color: "rgba(148,163,184,0.35)" }}>
          Kraken Bot Fleet
        </span>
        <span className="ml-auto text-[7px] font-mono" style={{ color: "rgba(148,163,184,0.2)" }}>
          {perBotNodes.filter(([, n]) => n.level === "green").length}/{perBotNodes.length} healthy
        </span>
      </div>
      <div className="flex items-center gap-2 px-5 py-2 flex-wrap">
        {perBotNodes.map(([key, node]) => {
          const colors = LEVEL_COLORS[node.level];
          const botLabel = BOT_DISPLAY[key] ?? key.replace("kraken_", "").replace(/_/g, " ");
          return (
            <div key={key} className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg"
              style={{
                background: colors.fill,
                border: `1px solid ${colors.stroke}`,
              }}>
              <span className="h-1.5 w-1.5 rounded-full shrink-0"
                style={{ background: colors.wire, boxShadow: `0 0 4px ${colors.wire}` }} />
              <span className="text-[8px] font-mono font-semibold capitalize"
                style={{ color: colors.wire }}>
                {botLabel}
              </span>
              {node.kick_pending && (
                <span className="text-[6px] font-mono px-1 py-px rounded border ml-0.5"
                  style={{ color: "#fb923c", borderColor: "rgba(251,146,60,0.3)", background: "rgba(251,146,60,0.1)" }}>
                  KICK
                </span>
              )}
              <span className="text-[7px] font-mono uppercase ml-0.5"
                style={{ color: colors.wire, opacity: 0.7 }}>
                {node.level === "green" ? "OK" : node.level === "yellow" ? "WARN" : "ERR"}
              </span>
              {node.data_age_s != null && (
                <span className="text-[7px] font-mono"
                  style={{ color: "rgba(148,163,184,0.4)" }}>
                  {node.data_age_s.toFixed(0)}s
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Alert Digest ─────────────────────────────────────────────────────────── */
function StreamingAlertDigest({ nodes }: { nodes: Record<string, NodeHealth> }) {
  const alerts = useMemo(() => {
    return Object.entries(nodes)
      .filter(([, n]) => n.level !== "green")
      .sort(([, a], [, b]) => (a.level === "red" ? -1 : b.level === "red" ? 1 : 0));
  }, [nodes]);

  const criticalCount = alerts.filter(([, n]) => n.level === "red").length;
  const degradedCount = alerts.filter(([, n]) => n.level === "yellow").length;
  const hiddenCount = Math.max(0, alerts.length - 3);
  const visibleAlerts = alerts.slice(0, 3);

  if (alerts.length === 0) {
    return (
      <div className="flex items-center gap-2.5 px-5 py-2.5" style={{ borderTop: "1px solid rgba(255,255,255,0.05)", background: "rgba(34,197,94,0.04)" }}>
        <CheckCircle2 className="h-3.5 w-3.5 text-green-400 shrink-0" />
        <span className="text-[10px] font-mono text-green-400">All systems nominal — no active alerts.</span>
        <span className="ml-auto text-[8px] font-mono" style={{ color: "rgba(148,163,184,0.3)" }}>READ-ONLY · STREAMING VIEW</span>
      </div>
    );
  }

  return (
    <div style={{ borderTop: "1px solid rgba(255,255,255,0.06)", background: "rgba(2,6,23,0.95)" }}>
      <div className="flex items-center gap-2 px-5 py-2" style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
        <AlertTriangle className="h-3 w-3 text-yellow-400 shrink-0" />
        <span className="text-[8px] font-mono uppercase tracking-widest font-semibold" style={{ color: "rgba(148,163,184,0.6)" }}>
          Active Alerts
        </span>
        <span className="ml-1 text-[8px] font-mono">
          {criticalCount > 0 && <span className="text-red-400">{criticalCount} critical</span>}
          {criticalCount > 0 && degradedCount > 0 && <span style={{ color: "rgba(148,163,184,0.4)" }}> · </span>}
          {degradedCount > 0 && <span className="text-yellow-400">{degradedCount} degraded</span>}
        </span>
        <span className="ml-auto text-[8px] font-mono" style={{ color: "rgba(148,163,184,0.25)" }}>READ-ONLY · STREAMING VIEW</span>
      </div>
      <div className="divide-y" style={{ divideColor: "rgba(255,255,255,0.03)" } as React.CSSProperties}>
        {visibleAlerts.map(([key, node]) => {
          const colors = LEVEL_COLORS[node.level];
          const Icon = node.level === "red" ? XCircle : AlertTriangle;
          return (
            <div key={key} className="flex items-center gap-3 px-5 py-2">
              <Icon className={`h-3 w-3 shrink-0 ${colors.text} ${node.level === "red" ? "animate-pulse" : ""}`} />
              <span className={`text-[10px] font-semibold font-mono ${colors.text}`}>
                {node.label.split("(")[0].trim()}
              </span>
              <span className={`text-[8px] font-mono px-1.5 py-0.5 rounded border uppercase tracking-wider ${colors.bg} ${colors.text} ${colors.border}`}>
                {node.level === "yellow" ? "DEGRADED" : "CRITICAL"}
              </span>
              {node.kick_pending && (
                <span className="text-[7px] font-mono px-1.5 py-0.5 rounded border"
                  style={{ color: "#fb923c", borderColor: "rgba(251,146,60,0.3)", background: "rgba(251,146,60,0.1)" }}>
                  KICK PENDING
                </span>
              )}
              {node.latency_ms != null && (
                <span className="text-[8px] font-mono" style={{ color: "rgba(148,163,184,0.5)" }}>{node.latency_ms}ms</span>
              )}
              {node.data_age_s != null && node.latency_ms == null && (
                <span className="text-[8px] font-mono" style={{ color: "rgba(148,163,184,0.5)" }}>{node.data_age_s.toFixed(0)}s old</span>
              )}
              <span className="text-[8px] font-mono truncate flex-1" style={{ color: "rgba(148,163,184,0.45)" }}>{node.detail}</span>
            </div>
          );
        })}
        {hiddenCount > 0 && (
          <div className="flex items-center gap-2 px-5 py-1.5">
            <AlertTriangle className="h-2.5 w-2.5 text-yellow-500/60 shrink-0" />
            <span className="text-[8px] font-mono" style={{ color: "rgba(148,163,184,0.4)" }}>
              +{hiddenCount} more alert{hiddenCount !== 1 ? "s" : ""} — check remediate log for details
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Heal Log ─────────────────────────────────────────────────────────────── */
function StreamingHealLog({ log }: { log: HealEntry[] }) {
  if (log.length === 0) return null;
  const recent = log.slice(0, 4);

  return (
    <div style={{ borderTop: "1px solid rgba(255,255,255,0.04)", background: "rgba(2,6,23,0.9)" }}>
      <div className="flex items-center gap-2 px-5 py-1" style={{ borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
        <Clock className="h-2.5 w-2.5" style={{ color: "rgba(148,163,184,0.35)" }} />
        <span className="text-[7px] font-mono uppercase tracking-widest font-semibold" style={{ color: "rgba(148,163,184,0.35)" }}>Heal Log</span>
        <span className="ml-auto text-[7px] font-mono" style={{ color: "rgba(148,163,184,0.2)" }}>{log.length} entries</span>
      </div>
      <div className="divide-y" style={{ divideColor: "rgba(255,255,255,0.03)" } as React.CSSProperties}>
        {recent.map((entry, i) => {
          const label = COMPONENT_LABELS[entry.component] ?? entry.component;
          const byLabel = entry.triggered_by === "auto_heal" ? "auto" : entry.triggered_by === "heal_all" ? "heal-all" : "manual";
          const timeStr = new Date(entry.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
          const healType = entry.heal_type ?? (entry.success ? "HEALED" : "FAILED");
          const healTypeStyle = HEAL_TYPE_STYLES[healType] ?? "text-slate-400 border-white/10 bg-white/5";
          return (
            <div key={i} className="flex items-center gap-2 px-5 py-1 flex-wrap">
              <span className="text-[8px] font-mono shrink-0 w-16" style={{ color: "rgba(148,163,184,0.5)" }}>{timeStr}</span>
              <span className={`text-[7px] font-mono font-bold shrink-0 px-1.5 py-px rounded border uppercase tracking-wider ${healTypeStyle}`}>
                {healType}
              </span>
              <span className={`text-[7px] font-mono shrink-0 px-1 py-px rounded border ${
                entry.triggered_by === "auto_heal"
                  ? "text-violet-400 border-violet-500/20 bg-violet-500/5"
                  : "text-cyan-400/60 border-cyan-500/15 bg-cyan-500/5"
              }`}>{byLabel}</span>
              <span className="text-[8px] font-mono shrink-0" style={{ color: "rgba(255,255,255,0.6)" }}>{label}</span>
              <span className="text-[8px] font-mono truncate flex-1" style={{ color: "rgba(148,163,184,0.4)" }}>{entry.result}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Main Screen ──────────────────────────────────────────────────────────── */
export default function StreamingHealthScreen() {
  const { data, isLoading } = useQuery<HealthData>({
    queryKey: ["/system/health-architecture"],
    queryFn: async () => (await api.get("/system/health-architecture")).data,
    refetchInterval: 10_000,
    retry: false,
  });

  const { data: logData } = useQuery({
    queryKey: ["/system/remediate/log"],
    queryFn: async () => (await api.get("/system/remediate/log")).data,
    refetchInterval: 10_000,
    retry: false,
  });

  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const nodes = data?.nodes ?? null;

  const overallLevel: Level = useMemo(() => {
    if (!nodes) return "yellow";
    const levels = Object.values(nodes).map((n) => n.level);
    if (levels.includes("red")) return "red";
    if (levels.includes("yellow")) return "yellow";
    return "green";
  }, [nodes]);

  const overallColors = LEVEL_COLORS[overallLevel];
  const healLog: HealEntry[] = (logData as { log?: HealEntry[] } | undefined)?.log ?? [];

  const alertCount = nodes ? Object.values(nodes).filter(n => n.level !== "green").length : 0;

  return (
    <div
      className="h-full w-full flex flex-col relative"
      style={{ background: "radial-gradient(ellipse at 30% 0%, rgba(8,18,38,1) 0%, rgba(2,6,18,1) 100%)" }}
    >
      <DDGBadge style={{ position: "absolute", bottom: 10, left: 10, zIndex: 50 }} />
      {/* Health status strip */}
      <div
        className="shrink-0 flex items-center justify-between px-5 py-2"
        style={{
          borderBottom: `1px solid ${overallColors.stroke}30`,
          background: `${overallColors.wire}06`,
          minHeight: 36,
        }}
      >
        <div className="flex items-center gap-3">
          <div className="relative h-6 w-6 flex items-center justify-center shrink-0">
            <div className="absolute inset-0 rounded-full animate-ping opacity-20" style={{ background: overallColors.wire }} />
            <Activity className={`h-3.5 w-3.5 relative z-10 ${overallColors.text}`} />
          </div>
          <div className="flex items-center gap-2">
            <span className={`h-1.5 w-1.5 rounded-full ${
              overallLevel === "green" ? "bg-green-400" :
              overallLevel === "yellow" ? "bg-yellow-400 animate-pulse" :
              "bg-red-400 animate-pulse"
            }`} />
            <span className="text-[10px] font-mono uppercase tracking-[0.22em]"
              style={{ color: overallColors.wire, textShadow: `0 0 8px ${overallColors.wire}` }}>
              SYS / HEALTH
            </span>
            <span className="text-[9px] font-mono uppercase tracking-widest" style={{ color: "rgba(148,163,184,0.4)" }}>
              — {overallLevel === "green" ? "All systems nominal" : overallLevel === "yellow" ? "Degraded · self-heal active" : "Critical · auto-remediating"}
            </span>
          </div>
          {overallLevel !== "green" && (
            <span className="text-[8px] font-mono px-2 py-0.5 rounded flex items-center gap-1 uppercase tracking-widest"
              style={{ background: `${overallColors.wire}12`, color: overallColors.wire, border: `1px solid ${overallColors.wire}30` }}>
              <Zap className="h-2.5 w-2.5" />
              self-heal active
            </span>
          )}
        </div>
        <div className="text-right">
            <div className="text-[8px] font-mono" style={{ color: "rgba(148,163,184,0.3)" }}>
              {now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
            </div>
            {alertCount > 0 && (
              <div className="text-[8px] font-mono text-yellow-400">{alertCount} alert{alertCount !== 1 ? "s" : ""}</div>
            )}
          </div>
      </div>

      {/* SVG Diagram */}
      <div className="flex-1 relative overflow-hidden min-h-0">
        {isLoading || !nodes ? (
          <div className="flex items-center justify-center h-full gap-3">
            <div className="h-2 w-2 rounded-full bg-green-400 animate-bounce" style={{ animationDelay: "0ms" }} />
            <div className="h-2 w-2 rounded-full bg-green-400 animate-bounce" style={{ animationDelay: "150ms" }} />
            <div className="h-2 w-2 rounded-full bg-green-400 animate-bounce" style={{ animationDelay: "300ms" }} />
            <span className="text-xs font-mono ml-1" style={{ color: "rgba(148,163,184,0.5)" }}>Scanning subsystems…</span>
          </div>
        ) : (
          <svg viewBox="0 0 800 620" className="w-full h-full" preserveAspectRatio="xMidYMid meet">
            <defs>
              <pattern id="hs-dots" x="0" y="0" width="30" height="30" patternUnits="userSpaceOnUse">
                <circle cx="1" cy="1" r="1" fill="rgba(255,255,255,0.05)" />
              </pattern>
              <radialGradient id="hs-gridFade" cx="50%" cy="50%" r="55%">
                <stop offset="0%" stopColor="white" stopOpacity="1" />
                <stop offset="100%" stopColor="white" stopOpacity="0" />
              </radialGradient>
              <mask id="hs-gridMask">
                <rect width="800" height="620" fill="url(#hs-gridFade)" />
              </mask>
            </defs>

            <rect width="800" height="620" fill="url(#hs-dots)" mask="url(#hs-gridMask)" />

            <line x1="0" y1="0" x2="800" y2="0" stroke={overallColors.wire} strokeWidth="1.5" opacity="0.12">
              <animate attributeName="y1" values="0;620;0" dur="5s" repeatCount="indefinite" />
              <animate attributeName="y2" values="0;620;0" dur="5s" repeatCount="indefinite" />
            </line>

            {WIRES.map((wire, i) => {
              const fromPos = NODE_POSITIONS[wire.from];
              const toPos = NODE_POSITIONS[wire.to];
              const fromNode = nodes[wire.from];
              const toNode = nodes[wire.to];
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
                  level={worstLevel} id={`hs-wire-${i}`} />
              );
            })}

            {Object.entries(nodes).map(([key, health]) => (
              <ArchitectureNode key={key} nodeKey={key} health={health} />
            ))}
          </svg>
        )}
      </div>

      {/* Per-bot fleet strip */}
      {nodes && <PerBotFleetStrip nodes={nodes} />}

      {/* Alert digest */}
      {nodes && <StreamingAlertDigest nodes={nodes} />}

      {/* Heal log */}
      <StreamingHealLog log={healLog} />
    </div>
  );
}
