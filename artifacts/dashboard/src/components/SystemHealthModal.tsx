import { useState, useEffect, useMemo, useCallback } from "react";
import { X, Activity, Wifi, Server, Shield, Database, Anchor, AlertTriangle, CheckCircle2, XCircle, Info } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";

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
}

interface HealthData {
  timestamp: number;
  nodes: Record<string, NodeHealth>;
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
  platform_core: { x: 400, y: 160, icon: Server },
  equity_manager: { x: 180, y: 310, icon: Shield },
  alpaca_api: { x: 100, y: 460, icon: Wifi },
  kraken_api: { x: 620, y: 310, icon: Anchor },
  data_pipeline: { x: 540, y: 460, icon: Database },
};

const WIRES: [string, string][] = [
  ["platform_core", "equity_manager"],
  ["platform_core", "kraken_api"],
  ["platform_core", "data_pipeline"],
  ["equity_manager", "alpaca_api"],
  ["data_pipeline", "kraken_api"],
];

function buildExplanation(key: string, node: NodeHealth): string {
  const { level, latency_ms, data_age_s, detail } = node;

  if (level === "green") return "All checks passing.";

  if (latency_ms != null && latency_ms > 1000)
    return `Round-trip to ${node.label.split("(")[0].trim()} took ${latency_ms}ms — well above the 1,000ms critical threshold. Check network or API availability.`;
  if (latency_ms != null && latency_ms > 200)
    return `Latency is ${latency_ms}ms — above the 200ms optimal threshold. The API is reachable but responding slowly.`;

  if (data_age_s != null && data_age_s > 300)
    return `Feed data is ${data_age_s.toFixed(0)}s old — critical threshold is 300s. The data pipeline may be stalled or the bot has stopped writing updates.`;
  if (data_age_s != null && data_age_s > 60)
    return `Feed data is ${data_age_s.toFixed(0)}s old — past the 60s freshness threshold. Normal if a cycle just completed; watch if it continues rising.`;

  if (key === "equity_manager") {
    if (level === "red") return `A single position exceeds 15% of total equity — the hard risk limit. The enforcer should trigger a rebalance. Detail: ${detail}`;
    if (level === "yellow") return `A single position is approaching the 15% limit (currently 12–15%). No breach yet, but worth monitoring. Detail: ${detail}`;
  }

  if (key === "platform_core") {
    if (detail.includes("0 jobs")) return "The APScheduler crashed or lost all registered jobs. Restart the trading API server to recover.";
    if (detail.includes("error") || detail.includes("failed")) return `The last analysis cycle ended in an error state. Check server logs for the root cause. Detail: ${detail}`;
    if (detail.includes("never_run")) return "No analysis cycle has run yet since the server started. This clears automatically once the first cycle fires.";
  }

  if (key === "data_pipeline") {
    if (detail.includes("No data cached")) return "No market data feeds have been cached yet. This resolves after the first analysis cycle runs (scheduler must be enabled and market must be in session or crypto cycle must fire).";
    return `Only some data feeds are cached. Detail: ${detail}`;
  }

  if (key === "kraken_api") {
    if (detail.includes("Bot not started")) return "The Kraken bot process hasn't written a status file yet. Start the 'Davy Jones' Portfolio' workflow to resolve.";
    if (detail.includes("paused")) return "The Kraken bot is paused — either manually via the dashboard toggle or by the circuit breaker (>10% price drop). Resume from the toolbar.";
    if (detail.includes("503") || detail.includes("timeout")) return "The Kraken exchange API returned a server error. This is usually transient — the bot will retry on the next cycle.";
  }

  if (key === "alpaca_api") {
    if (detail.includes("429")) return "Alpaca rate limit hit. The platform made too many API calls in a short window. This resolves automatically within a minute.";
    if (detail.includes("401") || detail.includes("403")) return "Alpaca authentication failed. Verify ALPACA_API_KEY and ALPACA_SECRET_KEY are set correctly in Secrets.";
    if (detail.includes("404")) return "Alpaca returned 404 — the requested resource (account, order, position) was not found. May indicate a stale reference.";
    if (detail.includes("503") || detail.includes("timeout")) return "Alpaca API is unreachable or timing out. Could be a temporary outage — check status.alpaca.markets.";
  }

  return detail || "Status flagged — check the server logs for more detail.";
}

function GlowingWire({ x1, y1, x2, y2, level, id }: { x1: number; y1: number; x2: number; y2: number; level: Level; id: string }) {
  const colors = LEVEL_COLORS[level];
  const length = Math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2);

  return (
    <g>
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="rgba(255,255,255,0.04)" strokeWidth={2} />
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={colors.wire} strokeWidth={1.5} opacity={0.3} />
      <line
        x1={x1} y1={y1} x2={x2} y2={y2}
        stroke={colors.wire}
        strokeWidth={3}
        opacity={0.6}
        strokeDasharray={`8 ${length - 8}`}
        strokeLinecap="round"
      >
        <animate
          attributeName="stroke-dashoffset"
          from={length}
          to={0}
          dur={level === "red" ? "0.8s" : level === "yellow" ? "2s" : "3s"}
          repeatCount="indefinite"
        />
      </line>
      {level === "red" && (
        <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={colors.wire} strokeWidth={4} opacity={0.3}>
          <animate attributeName="opacity" values="0.3;0.8;0.3" dur="0.6s" repeatCount="indefinite" />
        </line>
      )}
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
  const W = 160;
  const H = 80;

  return (
    <g
      onClick={onClick}
      className="cursor-pointer"
      style={{ filter: `drop-shadow(0 0 ${selected ? "12px" : "6px"} ${colors.glow})` }}
    >
      <rect
        x={pos.x - W / 2}
        y={pos.y - H / 2}
        width={W}
        height={H}
        rx={12}
        fill={colors.fill}
        stroke={colors.stroke}
        strokeWidth={selected ? 2 : 1.2}
      />
      {health.level === "red" && (
        <rect
          x={pos.x - W / 2}
          y={pos.y - H / 2}
          width={W}
          height={H}
          rx={12}
          fill="none"
          stroke={colors.stroke}
          strokeWidth={2}
        >
          <animate attributeName="opacity" values="1;0.3;1" dur="1s" repeatCount="indefinite" />
        </rect>
      )}
      <foreignObject x={pos.x - W / 2} y={pos.y - H / 2} width={W} height={H}>
        <div className="w-full h-full flex flex-col items-center justify-center px-2">
          <Icon className={cn("h-4 w-4 mb-1", colors.text)} />
          <div className={cn("text-[10px] font-semibold text-center leading-tight", colors.text)}>
            {health.label.split("(")[0].trim()}
          </div>
          <div className="text-[8px] text-muted-foreground/60 font-mono mt-0.5 text-center truncate max-w-full">
            {health.latency_ms != null
              ? `${health.latency_ms}ms`
              : health.data_age_s != null
              ? `${health.data_age_s.toFixed(0)}s ago`
              : "—"}
          </div>
        </div>
      </foreignObject>
    </g>
  );
}

/* ── Active Alerts Digest ───────────────────────────────────────────────── */
function AlertsDigest({ nodes }: { nodes: Record<string, NodeHealth> }) {
  const alerts = useMemo(() => {
    return Object.entries(nodes)
      .filter(([, n]) => n.level !== "green")
      .sort(([, a], [, b]) => (a.level === "red" ? -1 : b.level === "red" ? 1 : 0));
  }, [nodes]);

  const [expanded, setExpanded] = useState<string | null>(null);

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
      {/* digest header */}
      <div className="flex items-center gap-2 px-5 py-2 border-b border-white/5">
        <AlertTriangle className="h-3.5 w-3.5 text-yellow-400 shrink-0" />
        <span className="text-[9px] font-mono uppercase tracking-widest text-muted-foreground/60 font-semibold">
          Active Alerts
        </span>
        <span className="ml-auto text-[9px] font-mono text-muted-foreground/40">
          {alerts.filter(([, n]) => n.level === "red").length} critical · {alerts.filter(([, n]) => n.level === "yellow").length} degraded
        </span>
      </div>

      {/* alert rows */}
      <div className="max-h-48 overflow-y-auto divide-y divide-white/[0.04]">
        {alerts.map(([key, node]) => {
          const colors = LEVEL_COLORS[node.level];
          const explanation = buildExplanation(key, node);
          const isOpen = expanded === key;
          const Icon = node.level === "red" ? XCircle : AlertTriangle;

          return (
            <button
              key={key}
              onClick={() => setExpanded(isOpen ? null : key)}
              className={cn(
                "w-full text-left px-5 py-2.5 transition-colors hover:bg-white/[0.03] group",
                isOpen && "bg-white/[0.03]"
              )}
            >
              <div className="flex items-start gap-3">
                {/* level icon */}
                <Icon
                  className={cn("h-3.5 w-3.5 mt-0.5 shrink-0", colors.text, node.level === "red" && "animate-pulse")}
                />

                {/* left: label + short detail */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={cn("text-[10px] font-semibold font-mono", colors.text)}>
                      {node.label.split("(")[0].trim()}
                    </span>
                    <span
                      className={cn(
                        "text-[8px] font-mono px-1.5 py-0.5 rounded border uppercase tracking-wider",
                        colors.bg, colors.text, colors.border
                      )}
                    >
                      {node.level === "green" ? "OK" : node.level === "yellow" ? "DEGRADED" : "CRITICAL"}
                    </span>
                    {node.latency_ms != null && (
                      <span className="text-[8px] font-mono text-muted-foreground/50">{node.latency_ms}ms</span>
                    )}
                    {node.data_age_s != null && node.latency_ms == null && (
                      <span className="text-[8px] font-mono text-muted-foreground/50">{node.data_age_s.toFixed(0)}s old</span>
                    )}
                  </div>

                  {/* short detail line always visible */}
                  <div className="text-[9px] text-muted-foreground/60 font-mono mt-0.5 truncate">{node.detail}</div>

                  {/* expanded plain-English explanation */}
                  {isOpen && (
                    <div
                      className={cn(
                        "mt-2 text-[10px] leading-relaxed rounded-lg px-3 py-2 border",
                        colors.bg, colors.border,
                        colors.text
                      )}
                    >
                      <div className="flex gap-1.5">
                        <Info className="h-3 w-3 mt-0.5 shrink-0 opacity-70" />
                        <span>{explanation}</span>
                      </div>
                    </div>
                  )}
                </div>

                {/* chevron */}
                <span className="text-[8px] text-muted-foreground/30 group-hover:text-muted-foreground/60 transition-colors mt-0.5 font-mono">
                  {isOpen ? "▲" : "▼"}
                </span>
              </div>
            </button>
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
        data_pipeline: { level: "red", data_age_s: 450, detail: "Data 450s old > 300s CRITICAL" },
        kraken_api: { level: "red", data_age_s: 360, detail: "Status 360s old > 300s CRITICAL" },
      },
      "alloc-breach": {
        equity_manager: { level: "red", detail: "BREACH: single position 18.4% > 15.00% limit" },
      },
      "total-failure": {
        platform_core: { level: "red", detail: "Scheduler crashed — 0 jobs" },
        alpaca_api: { level: "red", latency_ms: 5000, detail: "Connection timeout (5000ms)" },
        kraken_api: { level: "red", detail: "HTTP 503 Service Unavailable" },
        data_pipeline: { level: "red", data_age_s: 600, detail: "All feeds stale > 300s" },
        equity_manager: { level: "red", detail: "Cannot validate — API unreachable" },
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

      {/* Scenario Presets */}
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

      {/* Per-Node Overrides */}
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
                type="range"
                min={0}
                max={2000}
                step={50}
                defaultValue={0}
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
                type="range"
                min={0}
                max={600}
                step={10}
                defaultValue={0}
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
  const { data, isLoading } = useQuery<HealthData>({
    queryKey: ["/system/health-architecture"],
    queryFn: async () => (await api.get("/system/health-architecture")).data,
    refetchInterval: 10_000,
    retry: false,
  });

  const [overrides, setOverrides] = useState<Overrides>({});
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm" onClick={onClose}>
      <div
        className="relative w-[90vw] h-[85vh] max-w-5xl bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 border border-white/10 rounded-2xl shadow-2xl flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* ── Header ── */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10 shrink-0">
          <div className="flex items-center gap-3">
            <div className="relative">
              <Activity className={cn("h-5 w-5", overallColors.text)} />
              <span
                className={cn("absolute -top-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-slate-900", {
                  "bg-green-400": overallLevel === "green",
                  "bg-yellow-400 animate-pulse": overallLevel === "yellow",
                  "bg-red-400 animate-pulse": overallLevel === "red",
                })}
              />
            </div>
            <h3 className="text-lg font-bold text-white">System Health Architecture</h3>
            {hasOverrides && (
              <span className="text-[9px] font-mono px-2 py-0.5 rounded bg-orange-500/15 text-orange-400 border border-orange-500/20 uppercase">
                Test Mode
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg text-muted-foreground hover:text-white hover:bg-white/10 transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* ── Body (diagram) ── */}
        <div className="flex-1 relative overflow-hidden min-h-0">
          {isLoading || !mergedNodes ? (
            <div className="flex items-center justify-center h-full">
              <div className="text-muted-foreground text-sm font-mono animate-pulse">Scanning subsystems...</div>
            </div>
          ) : (
            <>
              {/* Legend */}
              <div className="absolute top-4 left-6 flex items-center gap-4 z-10">
                {(["green", "yellow", "red"] as Level[]).map((lvl) => (
                  <div key={lvl} className="flex items-center gap-1.5">
                    <span
                      className={cn("h-2.5 w-2.5 rounded-full", {
                        "bg-green-400": lvl === "green",
                        "bg-yellow-400": lvl === "yellow",
                        "bg-red-400": lvl === "red",
                      })}
                    />
                    <span className="text-[9px] font-mono text-muted-foreground/60 uppercase">
                      {lvl === "green" ? "Optimal" : lvl === "yellow" ? "Degraded" : "Critical"}
                    </span>
                  </div>
                ))}
              </div>

              {/* SVG Diagram */}
              <svg viewBox="0 0 800 560" className="w-full h-full" preserveAspectRatio="xMidYMid meet">
                <defs>
                  {(["green", "yellow", "red"] as Level[]).map((lvl) => (
                    <filter key={lvl} id={`glow-${lvl}`} x="-50%" y="-50%" width="200%" height="200%">
                      <feGaussianBlur stdDeviation="4" result="blur" />
                      <feFlood floodColor={LEVEL_COLORS[lvl].glow} />
                      <feComposite in2="blur" operator="in" />
                      <feMerge>
                        <feMergeNode />
                        <feMergeNode in="SourceGraphic" />
                      </feMerge>
                    </filter>
                  ))}
                </defs>

                {/* Wires */}
                {WIRES.map(([from, to], i) => {
                  const fromPos = NODE_POSITIONS[from];
                  const toPos = NODE_POSITIONS[to];
                  const fromNode = mergedNodes[from];
                  const toNode = mergedNodes[to];
                  if (!fromPos || !toPos || !fromNode || !toNode) return null;
                  const worstLevel: Level =
                    fromNode.level === "red" || toNode.level === "red"
                      ? "red"
                      : fromNode.level === "yellow" || toNode.level === "yellow"
                      ? "yellow"
                      : "green";
                  return (
                    <GlowingWire
                      key={i}
                      x1={fromPos.x}
                      y1={fromPos.y}
                      x2={toPos.x}
                      y2={toPos.y}
                      level={worstLevel}
                      id={`wire-${i}`}
                    />
                  );
                })}

                {/* Nodes */}
                {Object.entries(mergedNodes).map(([key, health]) => (
                  <ArchitectureNode
                    key={key}
                    nodeKey={key}
                    health={health}
                    selected={selectedNode === key}
                    onClick={() => setSelectedNode(selectedNode === key ? null : key)}
                  />
                ))}
              </svg>

              {/* Selected node hover detail */}
              {selectedHealth && (
                <div className="absolute top-4 right-4 w-64 bg-slate-900/95 border border-white/10 rounded-xl p-4 backdrop-blur-lg z-10">
                  <div className="flex items-center gap-2 mb-3">
                    <span
                      className={cn("h-2.5 w-2.5 rounded-full", {
                        "bg-green-400": selectedHealth.level === "green",
                        "bg-yellow-400 animate-pulse": selectedHealth.level === "yellow",
                        "bg-red-400 animate-pulse": selectedHealth.level === "red",
                      })}
                    />
                    <span className="text-xs font-semibold text-white">{selectedHealth.label}</span>
                    <button
                      onClick={() => setSelectedNode(null)}
                      className="ml-auto text-muted-foreground/40 hover:text-white"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                  <div className="space-y-2">
                    <div className="flex justify-between text-[10px]">
                      <span className="text-muted-foreground">Status</span>
                      <span className={LEVEL_COLORS[selectedHealth.level].text}>
                        {selectedHealth.level === "green" ? "Optimal" : selectedHealth.level === "yellow" ? "Degraded" : "CRITICAL"}
                      </span>
                    </div>
                    {selectedHealth.latency_ms != null && (
                      <div className="flex justify-between text-[10px]">
                        <span className="text-muted-foreground">Latency</span>
                        <span className="text-white font-mono">{selectedHealth.latency_ms}ms</span>
                      </div>
                    )}
                    {selectedHealth.data_age_s != null && (
                      <div className="flex justify-between text-[10px]">
                        <span className="text-muted-foreground">Data Age</span>
                        <span className="text-white font-mono">{selectedHealth.data_age_s.toFixed(0)}s</span>
                      </div>
                    )}
                    <div className="pt-1 border-t border-white/5">
                      <div className="text-[9px] text-muted-foreground/60 font-mono">{selectedHealth.detail}</div>
                    </div>
                  </div>
                </div>
              )}

              {/* Threshold reference — bottom left */}
              <div className="absolute bottom-4 left-6 z-10">
                <div className="text-[8px] font-mono text-muted-foreground/25 space-y-0.5">
                  <div>GREEN: latency &lt;200ms · data &lt;60s old · allocation ≤15%</div>
                  <div>YELLOW: latency 200–1000ms · data 60–300s old · rate limited</div>
                  <div>RED: latency &gt;1000ms · HTTP 4xx/5xx · data &gt;300s · alloc &gt;15%</div>
                </div>
              </div>

              {/* Test control panel */}
              <TestControlPanel overrides={overrides} setOverrides={setOverrides} resetOverrides={resetOverrides} />
            </>
          )}
        </div>

        {/* ── Active Alerts Digest — pinned bottom ── */}
        {mergedNodes && <AlertsDigest nodes={mergedNodes} />}
      </div>
    </div>
  );
}
