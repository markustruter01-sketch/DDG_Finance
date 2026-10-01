import { useState, useEffect, useMemo } from "react";
import { Activity, Server, Shield, Database, Anchor, AlertTriangle, CheckCircle2, XCircle, Clock, Brain, Globe, Target, Bell, Wifi, Zap } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { DDGBadge } from "@/components/DDGBadge";
import { api } from "@/hooks/use-trading-client";
import { getAttributedBotIdentity } from "@/lib/bot-identity";

type Level = "green" | "yellow" | "red" | "unknown";

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
  status?: "healthy" | "degraded" | "unknown";
  nodes: Record<string, NodeHealth>;
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
  unknown: {
    fill: "rgba(148,163,184,0.08)",
    stroke: "rgba(148,163,184,0.55)",
    glow: "rgba(148,163,184,0.35)",
    wire: "#94a3b8",
    text: "text-slate-300",
    bg: "bg-slate-500/10",
    border: "border-slate-400/25",
  },
};

const NODE_POSITIONS: Record<string, { x: number; y: number; icon: typeof Server }> = {
  platform_core:  { x: 400, y: 80,  icon: Server },
  bot_oracle:     { x: 140, y: 230, icon: Target },
  bot_spy_qqq_trend: { x: 400, y: 230, icon: Target },
  bot_jerome_macro:  { x: 660, y: 230, icon: Target },
  alpaca_api:     { x: 140, y: 400, icon: Wifi },
  data_pipeline:  { x: 400, y: 400, icon: Database },
  alert_system:   { x: 660, y: 400, icon: Bell },
  degradation_events: { x: 400, y: 530, icon: AlertTriangle },
  equity_manager: { x: 140, y: 530, icon: Shield },
  analysis_layer: { x: 660, y: 530, icon: Brain },
};

const NODE_W = 170;
const NODE_H = 86;

type WireSpec = { from: string; to: string; bend?: "h-first" | "v-first" };

const WIRES: WireSpec[] = [
  { from: "platform_core",  to: "bot_oracle",     bend: "v-first" },
  { from: "platform_core",  to: "bot_spy_qqq_trend", bend: "v-first" },
  { from: "platform_core",  to: "bot_jerome_macro",  bend: "v-first" },
  { from: "bot_oracle",     to: "alpaca_api",     bend: "v-first" },
  { from: "bot_spy_qqq_trend", to: "data_pipeline", bend: "v-first" },
  { from: "bot_jerome_macro",  to: "alert_system",  bend: "v-first" },
  { from: "data_pipeline",  to: "equity_manager", bend: "h-first" },
  { from: "data_pipeline",  to: "analysis_layer", bend: "h-first" },
  { from: "data_pipeline",  to: "alert_system",   bend: "h-first" },
  { from: "equity_manager", to: "alpaca_api",     bend: "v-first" },
];

const COMPONENT_LABELS: Record<string, string> = {
  platform_core: "Platform Core",
  data_pipeline: "Data Pipeline",
  bot_oracle: getAttributedBotIdentity("oracle").displayName,
  bot_spy_qqq_trend: getAttributedBotIdentity("spy_qqq_trend").displayName,
  bot_jerome_macro: getAttributedBotIdentity("jerome_macro").displayName,
  degradation_events: "Degradation Events",
  alpaca_api: "Alpaca API",
  equity_manager: "Equity Manager",
  analysis_layer: "Analysis Layer",
  alert_system: "Alert System",
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
    <g data-testid={`health-node-${nodeKey}`} aria-label={`${health.label}: ${health.level}`}>
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
  const perBotNodes = Object.entries(nodes).filter(([k]) => ["bot_oracle", "bot_spy_qqq_trend", "bot_jerome_macro"].includes(k));
  if (perBotNodes.length === 0) return null;

  return (
    <div style={{ borderTop: "1px solid rgba(255,255,255,0.05)", background: "rgba(2,6,23,0.92)" }}>
      <div className="flex items-center gap-2 px-5 py-1.5" style={{ borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
        <Anchor className="h-2.5 w-2.5" style={{ color: "rgba(148,163,184,0.35)" }} />
        <span className="text-[7px] font-mono uppercase tracking-widest font-semibold" style={{ color: "rgba(148,163,184,0.35)" }}>
          Active Alpaca ETF Fleet
        </span>
        <span className="ml-auto text-[7px] font-mono" style={{ color: "rgba(148,163,184,0.2)" }}>
          {perBotNodes.filter(([, n]) => n.level === "green").length}/{perBotNodes.length} healthy
        </span>
      </div>
      <div className="flex items-center gap-2 px-5 py-2 flex-wrap">
        {perBotNodes.map(([key, node]) => {
          const colors = LEVEL_COLORS[node.level];
          const botLabel = COMPONENT_LABELS[key] ?? key;
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
                {node.level === "green" ? "OK" : node.level === "yellow" ? "WARN" : node.level === "red" ? "ERR" : "UNKNOWN"}
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
  const unknownCount = alerts.filter(([, n]) => n.level === "unknown").length;
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
          {(criticalCount > 0 || degradedCount > 0) && unknownCount > 0 && <span style={{ color: "rgba(148,163,184,0.4)" }}> · </span>}
          {unknownCount > 0 && <span className="text-slate-300">{unknownCount} unknown</span>}
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
                {node.level === "yellow" ? "DEGRADED" : node.level === "red" ? "CRITICAL" : "UNKNOWN"}
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
              +{hiddenCount} more alert{hiddenCount !== 1 ? "s" : ""}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Full Alert Panel (right column) ─────────────────────────────────────── */
function AlertPanel({ nodes }: { nodes: Record<string, NodeHealth> }) {
  const [filter, setFilter] = useState<"all" | "red" | "yellow" | "unknown">("all");
  const alerts = useMemo(() => {
    return Object.entries(nodes)
      .filter(([, n]) => n.level !== "green")
      .sort(([, a], [, b]) => {
        const rank = (l: Level) => l === "red" ? 0 : l === "yellow" ? 1 : l === "unknown" ? 2 : 3;
        return rank(a.level) - rank(b.level);
      });
  }, [nodes]);

  const criticalCount = alerts.filter(([, n]) => n.level === "red").length;
  const degradedCount = alerts.filter(([, n]) => n.level === "yellow").length;
  const unknownCount = alerts.filter(([, n]) => n.level === "unknown").length;
  const visibleAlerts = filter === "all" ? alerts : alerts.filter(([, node]) => node.level === filter);

  return (
    <div className="flex flex-col flex-1" data-testid="health-alert-content">
      {/* Panel header */}
      <div className="flex items-center gap-2 px-4 py-2.5 shrink-0"
        style={{ borderBottom: "1px solid rgba(255,255,255,0.06)", background: "rgba(2,6,23,0.8)" }}>
        <AlertTriangle className="h-3.5 w-3.5 text-yellow-400 shrink-0" />
        <span className="text-[9px] font-mono uppercase tracking-widest font-semibold"
          style={{ color: "rgba(148,163,184,0.7)" }}>Active Alerts</span>
        <span className="ml-1 text-[9px] font-mono">
          {criticalCount > 0 && <span className="text-red-400">{criticalCount} critical</span>}
          {criticalCount > 0 && degradedCount > 0 && <span style={{ color: "rgba(148,163,184,0.4)" }}> · </span>}
          {degradedCount > 0 && <span className="text-yellow-400">{degradedCount} degraded</span>}
          {(criticalCount > 0 || degradedCount > 0) && unknownCount > 0 && <span style={{ color: "rgba(148,163,184,0.4)" }}> · </span>}
          {unknownCount > 0 && <span className="text-slate-300">{unknownCount} unknown</span>}
          {alerts.length === 0 && <span className="text-green-400">none</span>}
        </span>
        <span className="ml-auto text-[8px] font-mono" style={{ color: "rgba(148,163,184,0.2)" }}>
          {alerts.length} total
        </span>
      </div>
      <div className="flex items-center gap-1 px-3 py-2" role="group" aria-label="Filter health alerts">
        {(["all", "red", "yellow", "unknown"] as const).map((level) => (
          <button
            key={level}
            type="button"
            data-testid={`health-alert-filter-${level}`}
            aria-pressed={filter === level}
            onClick={() => setFilter(level)}
            className="rounded-md border px-2 py-1 font-mono text-[8px] uppercase tracking-wider"
            style={{
              borderColor: filter === level ? "rgba(205,216,178,.32)" : "rgba(225,238,219,.1)",
              color: filter === level ? "#e6e9d7" : "rgba(220,230,216,.55)",
              background: filter === level ? "rgba(204,214,175,.12)" : "transparent",
            }}
          >
            {level === "red" ? "Critical" : level === "yellow" ? "Degraded" : level}
          </button>
        ))}
      </div>

      {visibleAlerts.length === 0 ? (
        <div className="flex flex-1 items-center justify-center gap-2.5 px-5 py-6"
          style={{ background: alerts.length === 0 ? "rgba(34,197,94,0.04)" : "transparent" }}>
          {alerts.length === 0 && filter === "all" && <CheckCircle2 className="h-4 w-4 text-green-400 shrink-0" />}
          <span className="text-[11px] font-mono" style={{ color: alerts.length === 0 && filter === "all" ? "#4ade80" : "rgba(220,230,216,.55)" }}>
            {alerts.length === 0 && filter === "all" ? "All reported systems nominal" : "No alerts match this filter"}
          </span>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto">
          {visibleAlerts.map(([key, node]) => {
            const colors = LEVEL_COLORS[node.level];
            const Icon = node.level === "red" ? XCircle : AlertTriangle;
            return (
              <div key={key} data-testid={`health-alert-${key}`} className="flex flex-col gap-1 px-4 py-3"
                style={{ borderBottom: "1px solid rgba(255,255,255,0.04)", background: node.level === "red" ? "rgba(239,68,68,0.04)" : "transparent" }}>
                {/* Top row: icon + label + badge */}
                <div className="flex items-center gap-2.5 flex-wrap">
                  <Icon className={`h-3.5 w-3.5 shrink-0 ${colors.text} ${node.level === "red" ? "animate-pulse" : ""}`} />
                  <span className={`text-[11px] font-semibold font-mono ${colors.text}`}>
                    {node.label.split("(")[0].trim()}
                  </span>
                  <span className={`text-[8px] font-mono px-1.5 py-0.5 rounded border uppercase tracking-wider ${colors.bg} ${colors.text} ${colors.border}`}>
                    {node.level === "yellow" ? "DEGRADED" : node.level === "red" ? "CRITICAL" : "UNKNOWN"}
                  </span>
                  {node.kick_pending && (
                    <span className="text-[7px] font-mono px-1.5 py-0.5 rounded border"
                      style={{ color: "#fb923c", borderColor: "rgba(251,146,60,0.3)", background: "rgba(251,146,60,0.1)" }}>
                      KICK PENDING
                    </span>
                  )}
                  {node.latency_ms != null && (
                    <span className="text-[8px] font-mono ml-auto shrink-0" style={{ color: "rgba(148,163,184,0.5)" }}>
                      {node.latency_ms}ms
                    </span>
                  )}
                  {node.data_age_s != null && node.latency_ms == null && (
                    <span className="text-[8px] font-mono ml-auto shrink-0" style={{ color: "rgba(148,163,184,0.5)" }}>
                      {node.data_age_s.toFixed(0)}s old
                    </span>
                  )}
                </div>
                {/* Detail row */}
                <div className="text-[9px] font-mono pl-6 leading-relaxed"
                  style={{ color: "rgba(148,163,184,0.5)" }}>
                  {node.detail}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ── Main Screen ──────────────────────────────────────────────────────────── */
export default function StreamingHealthScreen() {
  const { data, isLoading, isError } = useQuery<HealthData>({
    queryKey: ["/system/health-architecture"],
    queryFn: async () => (await api.get("/system/health-architecture")).data,
    refetchInterval: 10_000,
    retry: false,
  });

  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const nodes = useMemo(() => {
    if (!data?.nodes) return null;
    return Object.fromEntries(
      Object.keys(NODE_POSITIONS).map((key) => [
        key,
        data.nodes[key] ?? {
          label: COMPONENT_LABELS[key] ?? key,
          level: "unknown" as const,
          latency_ms: null,
          data_age_s: null,
          detail: "No subsystem record was returned in the latest report.",
        },
      ]),
    ) as Record<string, NodeHealth>;
  }, [data?.nodes]);
  const reportAge = data ? Math.max(0, Math.floor((now.getTime() - data.timestamp) / 1000)) : null;
  const reportStale = Boolean(reportAge != null && reportAge > 60) || (isError && Boolean(data));

  const overallLevel: Level = useMemo(() => {
    if (!nodes || !data) return "unknown";
    const levels = Object.values(nodes).map((n) => n.level);
    if (data?.status === "unknown") return "unknown";
    if (levels.includes("red")) return "red";
    if (data?.status === "degraded" || levels.includes("yellow")) return "yellow";
    if (levels.includes("unknown")) return "unknown";
    return "green";
  }, [nodes, data]);

  const overallColors = LEVEL_COLORS[overallLevel];

  const alertCount = nodes ? Object.values(nodes).filter(n => n.level !== "green").length : 0;
  const nodeCounts = nodes
    ? Object.values(nodes).reduce(
      (counts, node) => ({ ...counts, [node.level]: counts[node.level] + 1 }),
      { green: 0, yellow: 0, red: 0, unknown: 0 },
    )
    : null;
  const freshestAge = nodes
    ? Object.values(nodes).map((node) => node.data_age_s).filter((age): age is number => age != null).sort((a, b) => a - b)[0]
    : null;

  return (
    <div
      className="stream-screen stream-screen-health h-full w-full flex flex-col relative"
      data-testid="health-screen"
      style={{ background: "linear-gradient(180deg, rgba(10,22,20,.72), rgba(8,20,17,.94)), url('/streaming-forest-atmosphere.jpg') center 53% / cover, #14241f" }}
    >
      <style>{`
        .stream-screen-health[data-testid="health-screen"] { isolation:isolate; color:#eff3eb !important; background:linear-gradient(180deg,rgba(10,22,20,.72),rgba(8,20,17,.94)),url('/streaming-forest-atmosphere.jpg') center 53% / cover,#14241f !important; font-family:"DM Sans","Avenir Next",system-ui,sans-serif; }
        .stream-screen-health[data-testid="health-screen"] [style*="rgba(148,163,184"],.stream-screen-health[data-testid="health-screen"] [style*="rgba(148, 163, 184"],.stream-screen-health[data-testid="health-screen"] [style*="#94a3b8"],.stream-screen-health[data-testid="health-screen"] [style*="#e2e8f0"],.stream-screen-health[data-testid="health-screen"] [class*="text-slate-"] { color:rgba(223,233,220,.72) !important; text-shadow:none !important; }
        .stream-screen-health[data-testid="health-screen"] [style*="rgba(2,6,23"] { background:rgba(11,25,22,.8) !important; border-color:rgba(229,240,226,.16) !important; }
        .stream-screen-health[data-testid="health-screen"] [class*="text-green-"],.stream-screen-health[data-testid="health-screen"] [class*="text-emerald-"] { color:#a9d8ad !important; }
        .stream-screen-health[data-testid="health-screen"] [class*="text-red-"],.stream-screen-health[data-testid="health-screen"] [class*="text-rose-"] { color:#ee9a8c !important; }
        .stream-screen-health[data-testid="health-screen"] [class*="text-yellow-"],.stream-screen-health[data-testid="health-screen"] [class*="text-amber-"] { color:#e2c47d !important; }
        .stream-screen-health [data-testid="health-topology-and-alerts"] { gap:12px; padding:12px 20px 18px; }
        .stream-screen-health [data-testid="health-topology-and-alerts"] > div { border:1px solid rgba(229,240,226,.16); border-radius:14px; background:linear-gradient(135deg,rgba(20,38,31,.78),rgba(11,25,22,.77)) !important; box-shadow:inset 0 1px rgba(255,255,255,.06),0 14px 36px rgba(3,11,8,.2); backdrop-filter:blur(17px); }
        .stream-screen-health [data-testid="health-topology-and-alerts"] > div:first-child { border-right:1px solid rgba(229,240,226,.16) !important; }
        .stream-screen-health [data-testid="health-topology-and-alerts"] > div:last-child { background:rgba(11,25,22,.69) !important; }
        .stream-screen-health svg { color-scheme:dark; }
        @media(max-width:850px) { .stream-screen-health [data-testid="health-topology-and-alerts"] { padding:8px; gap:8px; } }
      `}</style>
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
              overallLevel === "red" ? "bg-red-400 animate-pulse" :
              "bg-slate-300 animate-pulse"
            }`} />
            <span className="text-[10px] font-mono uppercase tracking-[0.22em]"
              style={{ color: overallColors.wire, textShadow: `0 0 8px ${overallColors.wire}` }}>
              SYS / HEALTH
            </span>
            <span className="text-[9px] font-mono uppercase tracking-widest" style={{ color: "rgba(148,163,184,0.4)" }}>
              — {reportStale ? "Stale report · refresh failed or timestamp aged" : overallLevel === "green" ? "All reported systems nominal" : overallLevel === "yellow" ? "Degraded · review required" : overallLevel === "red" ? "Critical · review required" : "Unknown · health data unavailable"}
            </span>
          </div>

        </div>
        <div className="text-right">
            <div className="text-[8px] font-mono" style={{ color: "rgba(148,163,184,0.3)" }}>
              {reportAge == null ? "NO REPORT" : `${reportAge}s since report`}
            </div>
            {(isError || reportStale) && <div data-testid="health-stale-warning" className="text-[8px] font-mono text-amber-300">{isError ? "Refresh failed" : "Report is stale"}</div>}
            {alertCount > 0 && (
              <div className="text-[8px] font-mono text-yellow-400">{alertCount} alert{alertCount !== 1 ? "s" : ""}</div>
            )}
          </div>
      </div>

      <section data-testid="health-summary" className="flex shrink-0 items-center gap-5 px-5 py-2.5" style={{
        margin: "10px 20px 0",
        border: "1px solid rgba(234,243,229,.17)",
        borderRadius: 12,
        background: "linear-gradient(115deg,rgba(16,34,29,.84),rgba(18,39,32,.68))",
        boxShadow: "inset 0 1px rgba(255,255,255,.05),0 10px 28px rgba(4,12,9,.16)",
        backdropFilter: "blur(18px)",
      }}>
        <div className="min-w-28">
          <div className="text-[8px] font-mono uppercase tracking-widest text-slate-400">Overall health</div>
          <div className="mt-1 text-xs font-semibold uppercase" style={{ color: overallColors.wire }}>{nodes ? overallLevel : "unavailable"}</div>
        </div>
        {(["green", "yellow", "red", "unknown"] as const).map((level) => (
          <div key={level} className="min-w-12 border-l border-white/10 pl-4">
            <div className="text-sm font-mono font-semibold" style={{ color: LEVEL_COLORS[level].wire }}>{nodeCounts ? nodeCounts[level] : "—"}</div>
            <div className="mt-1 text-[8px] font-mono uppercase tracking-wider text-slate-400">{level}</div>
          </div>
        ))}
        <div className="ml-auto border-l border-white/10 pl-4">
          <div className="text-sm font-mono font-semibold text-slate-100">{freshestAge == null ? "—" : `${freshestAge.toFixed(0)}s`}</div>
          <div className="mt-1 text-[8px] font-mono uppercase tracking-wider text-slate-400">Freshest data age</div>
        </div>
      </section>

      {/* ── 50/50 body ── */}
      <div data-testid="health-topology-and-alerts" className="flex-1 flex min-h-0 overflow-hidden">

        {/* LEFT — diagram + fleet strip */}
        <div data-testid="health-topology" className="flex flex-col w-1/2 min-h-0 border-r" style={{ borderColor: "rgba(255,255,255,0.05)" }}>
          <div className="flex-1 relative overflow-hidden min-h-0">
            {isLoading ? (
              <div className="flex items-center justify-center h-full gap-3">
                <div className="h-2 w-2 rounded-full bg-cyan-700 animate-bounce" style={{ animationDelay: "0ms" }} />
                <div className="h-2 w-2 rounded-full bg-cyan-700 animate-bounce" style={{ animationDelay: "150ms" }} />
                <div className="h-2 w-2 rounded-full bg-cyan-700 animate-bounce" style={{ animationDelay: "300ms" }} />
                <span className="text-xs font-mono ml-1" style={{ color: "rgba(148,163,184,0.5)" }}>Scanning subsystems…</span>
              </div>
            ) : !nodes ? (
              <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
                <span className="text-[10px] font-mono font-bold uppercase tracking-[0.18em] text-amber-800">
                  Health data unavailable
                </span>
                <p className="max-w-sm text-xs leading-5 text-slate-600">
                  The service did not return a subsystem report. Health remains unknown until a report is available.
                </p>
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
                  const fromLevel = fromNode?.level ?? "unknown";
                  const toLevel = toNode?.level ?? "unknown";
                  const worstLevel: Level =
                    fromLevel === "red" || toLevel === "red" ? "red"
                    : fromLevel === "yellow" || toLevel === "yellow" ? "yellow"
                    : fromLevel === "unknown" || toLevel === "unknown" ? "unknown"
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
          {nodes && <PerBotFleetStrip nodes={nodes} />}
        </div>

        {/* RIGHT — full alert list */}
        <div data-testid="health-alert-panel" className="flex flex-col w-1/2 min-h-0 overflow-y-auto" style={{ background: "rgba(2,6,23,0.6)" }}>
          {nodes ? (
            <AlertPanel nodes={nodes} />
          ) : (
            <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-2 p-6 text-center">
              <span className="font-mono text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">
                {isLoading ? "Awaiting health report" : "Alert details unavailable"}
              </span>
              <p className="max-w-xs text-xs leading-5 text-slate-600">
                {isLoading
                  ? "Subsystem checks will appear when the service responds."
                  : "A missing report is not a healthy result; alert checks cannot be evaluated."}
              </p>
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
