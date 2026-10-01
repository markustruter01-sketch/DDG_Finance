import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bell,
  Brain,
  Check,
  ChevronRight,
  CircleDot,
  Clock3,
  Database,
  Radio,
  Server,
  ShieldCheck,
  Target,
  Wifi,
  X,
} from "lucide-react";
import { mockHealthData } from "../streaming-current/_shared/mockData";

type Level = "green" | "yellow" | "red" | "unknown";
type NodeHealth = {
  label: string;
  level: Level;
  latency_ms: number | null;
  data_age_s: number | null;
  detail: string;
  kick_pending?: boolean;
};
type NodeMap = Record<string, NodeHealth>;

const LEVEL: Record<Level, { label: string; color: string; tint: string; border: string }> = {
  green: {
    label: "Healthy",
    color: "#a6dfbc",
    tint: "rgba(109, 178, 137, .13)",
    border: "rgba(145, 213, 167, .36)",
  },
  yellow: {
    label: "Degraded",
    color: "#f0c979",
    tint: "rgba(202, 151, 59, .14)",
    border: "rgba(230, 185, 96, .4)",
  },
  red: {
    label: "Critical",
    color: "#ef9e98",
    tint: "rgba(197, 89, 79, .16)",
    border: "rgba(237, 132, 122, .44)",
  },
  unknown: {
    label: "Unknown",
    color: "#c2c9c4",
    tint: "rgba(189, 199, 191, .11)",
    border: "rgba(201, 211, 202, .3)",
  },
};

const ICONS = {
  platform_core: Server,
  bot_oracle: Target,
  bot_spy_qqq_trend: Target,
  bot_jerome_macro: Target,
  alpaca_api: Wifi,
  data_pipeline: Database,
  alert_system: Bell,
  degradation_events: AlertTriangle,
  equity_manager: ShieldCheck,
  analysis_layer: Brain,
} as const;

const POSITIONS: Record<string, { x: number; y: number }> = {
  platform_core: { x: 430, y: 44 },
  bot_oracle: { x: 145, y: 144 },
  bot_spy_qqq_trend: { x: 430, y: 144 },
  bot_jerome_macro: { x: 715, y: 144 },
  alpaca_api: { x: 145, y: 244 },
  data_pipeline: { x: 430, y: 244 },
  alert_system: { x: 715, y: 244 },
  equity_manager: { x: 145, y: 344 },
  degradation_events: { x: 430, y: 344 },
  analysis_layer: { x: 715, y: 344 },
};

const WIRES = [
  ["platform_core", "bot_oracle"],
  ["platform_core", "bot_spy_qqq_trend"],
  ["platform_core", "bot_jerome_macro"],
  ["bot_oracle", "alpaca_api"],
  ["bot_spy_qqq_trend", "data_pipeline"],
  ["bot_jerome_macro", "alert_system"],
  ["data_pipeline", "equity_manager"],
  ["data_pipeline", "analysis_layer"],
  ["data_pipeline", "alert_system"],
  ["equity_manager", "alpaca_api"],
] as const;

const LABELS: Record<string, string> = {
  platform_core: "Platform Core",
  bot_oracle: "Oracle",
  bot_spy_qqq_trend: "SPY / QQQ Trend",
  bot_jerome_macro: "Jerome Macro",
  alpaca_api: "Alpaca API",
  data_pipeline: "Data Pipeline",
  alert_system: "Alert System",
  degradation_events: "Degradation Events",
  equity_manager: "Equity Manager",
  analysis_layer: "Analysis Layer",
};

const formatMetric = (node: NodeHealth) => {
  if (node.latency_ms != null) return `${node.latency_ms} ms`;
  if (node.data_age_s != null) return `${node.data_age_s.toFixed(0)} s data age`;
  return "No telemetry";
};

function connectorPath(fromKey: string, toKey: string) {
  const from = POSITIONS[fromKey];
  const to = POSITIONS[toKey];
  const boxW = 215;
  const boxH = 68;
  if (from.y === to.y) {
    const direction = to.x > from.x ? 1 : -1;
    return `M ${from.x + direction * boxW / 2} ${from.y} L ${to.x - direction * boxW / 2} ${to.y}`;
  }
  const down = to.y > from.y;
  const startY = from.y + (down ? boxH / 2 : -boxH / 2);
  const endY = to.y + (down ? -boxH / 2 : boxH / 2);
  const midY = (startY + endY) / 2;
  return `M ${from.x} ${startY} L ${from.x} ${midY} L ${to.x} ${midY} L ${to.x} ${endY}`;
}

function statusText(level: Level) {
  return level === "green" ? "NOMINAL" : level === "yellow" ? "DEGRADED" : level === "red" ? "CRITICAL" : "UNKNOWN";
}

function Topology({ nodes, selected, onSelect }: { nodes: NodeMap; selected: string | null; onSelect: (key: string) => void }) {
  return (
    <svg className="health-topology" viewBox="0 0 860 390" role="img" aria-label="System health topology">
      <defs>
        <pattern id="health-grid" width="26" height="26" patternUnits="userSpaceOnUse">
          <circle cx="1" cy="1" r="1" fill="rgba(231,239,224,.18)" />
        </pattern>
        <linearGradient id="health-wire" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="rgba(213,229,210,.27)" />
          <stop offset="1" stopColor="rgba(213,229,210,.09)" />
        </linearGradient>
      </defs>
      <rect width="860" height="390" fill="url(#health-grid)" opacity=".42" />
      {WIRES.map(([from, to]) => {
        const sourceLevel = nodes[from]?.level ?? "green";
        const targetLevel = nodes[to]?.level ?? "green";
        const wireLevel: Level =
          sourceLevel === "red" || targetLevel === "red"
            ? "red"
            : sourceLevel === "yellow" || targetLevel === "yellow"
              ? "yellow"
              : "green";
        return (
          <g key={`${from}-${to}`}>
            <path d={connectorPath(from, to)} fill="none" stroke="rgba(229,239,221,.12)" strokeWidth="4" />
            <path d={connectorPath(from, to)} fill="none" stroke={LEVEL[wireLevel].color} strokeOpacity=".58" strokeWidth="1.35" />
            <circle r="2.2" fill={LEVEL[wireLevel].color} opacity=".95">
              <animateMotion
                path={connectorPath(from, to)}
                dur={wireLevel === "yellow" ? "3.2s" : "5.4s"}
                repeatCount="indefinite"
              />
            </circle>
          </g>
        );
      })}
      {Object.entries(nodes).map(([key, node]) => {
        const position = POSITIONS[key];
        if (!position) return null;
        const Icon = ICONS[key as keyof typeof ICONS] ?? CircleDot;
        const palette = LEVEL[node.level];
        const isSelected = selected === key;
        return (
          <g
            key={key}
            className="health-node"
            transform={`translate(${position.x - 107.5} ${position.y - 34})`}
            onClick={() => onSelect(key)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onSelect(key);
              }
            }}
            role="button"
            tabIndex={0}
            aria-label={`${node.label}, ${LEVEL[node.level].label}. ${formatMetric(node)}`}
            aria-pressed={isSelected}
          >
            <rect
              className="health-node-plate"
              width="215"
              height="68"
              rx="12"
              fill={isSelected ? "rgba(24, 42, 34, .94)" : "rgba(16, 30, 25, .86)"}
              stroke={isSelected ? palette.color : palette.border}
              strokeWidth={isSelected ? 1.7 : 1}
            />
            <path d="M 12 12 V 6 Q 12 4 14 4 H 31" fill="none" stroke={palette.color} strokeWidth="2" opacity=".86" />
            <foreignObject x="0" y="0" width="215" height="68">
              <div className="health-node-content" xmlns="http://www.w3.org/1999/xhtml">
                <div className="health-node-icon" style={{ color: palette.color, background: palette.tint, borderColor: palette.border }}>
                  <Icon size={15} strokeWidth={1.8} />
                </div>
                <div className="health-node-copy">
                  <div className="health-node-label">{node.label || LABELS[key] || key}</div>
                  <div className="health-node-meta">
                    <span style={{ color: palette.color }}>{statusText(node.level)}</span>
                    <span className="health-separator">/</span>
                    <span>{formatMetric(node)}</span>
                  </div>
                </div>
                <span className="health-node-dot" style={{ background: palette.color, boxShadow: `0 0 12px ${palette.color}70` }} />
              </div>
            </foreignObject>
          </g>
        );
      })}
    </svg>
  );
}

export function Health() {
  const data = mockHealthData;
  const isLoading = false;
  const hasError = false;
  const nodes = data?.nodes as NodeMap | undefined;
  const [now, setNow] = useState(() => new Date());
  const [selectedKey, setSelectedKey] = useState<string | null>("bot_jerome_macro");
  const [filter, setFilter] = useState<"all" | Level>("all");

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const overallLevel: Level = useMemo(() => {
    if (!nodes) return "unknown";
    const levels = Object.values(nodes).map((node) => node.level);
    if (data?.status === "unknown") return "unknown";
    if (levels.includes("red")) return "red";
    if (data?.status === "degraded" || levels.includes("yellow")) return "yellow";
    if (levels.includes("unknown")) return "unknown";
    return "green";
  }, [nodes, data?.status]);

  const entries = useMemo(() => Object.entries(nodes ?? {}), [nodes]);
  const counts = useMemo(() => ({
    green: entries.filter(([, node]) => node.level === "green").length,
    yellow: entries.filter(([, node]) => node.level === "yellow").length,
    red: entries.filter(([, node]) => node.level === "red").length,
    unknown: entries.filter(([, node]) => node.level === "unknown").length,
  }), [entries]);
  const alerts = useMemo(
    () => entries
      .filter(([, node]) => node.level !== "green")
      .sort(([, left], [, right]) => {
        const rank = (level: Level) => level === "red" ? 0 : level === "yellow" ? 1 : level === "unknown" ? 2 : 3;
        return rank(left.level) - rank(right.level);
      }),
    [entries],
  );
  const visibleAlerts = filter === "all" ? alerts : alerts.filter(([, node]) => node.level === filter);
  const selectedNode = selectedKey ? nodes?.[selectedKey] : undefined;
  const freshestAge = entries
    .map(([, node]) => node.data_age_s)
    .filter((age): age is number => age != null)
    .sort((a, b) => a - b)[0];
  const apiNode = nodes?.alpaca_api;
  const reportAge = Math.max(0, Math.floor((now.getTime() - data.timestamp) / 1000));

  return (
    <main className="health-page">
      <style>{`
        .health-page {
          --ink: #eff3eb;
          --muted: rgba(224, 233, 221, .68);
          --quiet: rgba(215, 226, 211, .45);
          --glass: rgba(12, 26, 22, .75);
          --line: rgba(224, 238, 222, .14);
          position: relative;
          isolation: isolate;
          box-sizing: border-box;
          width: 100%;
          height: 100%;
          min-height: 740px;
          overflow: hidden;
          padding: 0 28px 16px;
          color: var(--ink);
          font-family: "DM Sans", "Avenir Next", system-ui, sans-serif;
          background: #14241f;
        }
        .health-page *, .health-page *::before, .health-page *::after { box-sizing: border-box; }
        .health-scene {
          position: absolute;
          z-index: -2;
          inset: 0;
          background-image: url("/__mockup/images/streaming-forest-atmosphere.jpg");
          background-size: cover;
          background-position: center 53%;
          filter: saturate(.65);
          transform: scale(1.015);
        }
        .health-page::before {
          content: "";
          position: absolute;
          z-index: -1;
          inset: 0;
          background:
            linear-gradient(180deg, rgba(10, 22, 20, .69) 0%, rgba(8, 20, 17, .86) 38%, rgba(8, 20, 17, .94) 100%),
            linear-gradient(90deg, rgba(11, 30, 26, .3), rgba(11, 26, 23, .56));
          pointer-events: none;
        }
        .health-page::after {
          content: "";
          position: fixed;
          z-index: -1;
          pointer-events: none;
          inset: 0;
          opacity: .14;
          background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.8' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.16'/%3E%3C/svg%3E");
        }
        .health-topbar {
          height: 55px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          border-bottom: 1px solid rgba(233, 241, 229, .16);
        }
        .health-brand, .health-brand-mark, .health-top-meta, .health-statusline, .health-titleline,
        .health-panel-heading, .health-legend, .health-alert-heading, .health-alert-meta,
        .health-inspector-head, .health-footer, .health-summary, .health-summary-label {
          display: flex;
          align-items: center;
        }
        .health-brand { gap: 11px; min-width: 245px; }
        .health-brand-mark {
          width: 27px; height: 27px; justify-content: center;
          border: 1px solid rgba(200, 222, 200, .44);
          border-radius: 8px;
          background: rgba(214, 231, 207, .08);
          color: #cde0c9;
        }
        .health-brand-name { font-size: 12px; font-weight: 700; letter-spacing: .13em; }
        .health-brand-sub { margin-top: 2px; color: var(--quiet); font: 9px/1.1 ui-monospace, SFMono-Regular, monospace; letter-spacing: .12em; }
        .health-nav { display: flex; align-items: center; gap: 5px; height: 100%; }
        .health-nav-item {
          height: 100%; padding: 0 15px; display: flex; align-items: center;
          border-bottom: 2px solid transparent; color: rgba(223, 231, 220, .49);
          font-size: 10px; font-weight: 650; letter-spacing: .11em; text-transform: uppercase;
        }
        .health-nav-item.active { color: #e3eddf; border-bottom-color: #aac9ae; }
        .health-top-meta { gap: 9px; justify-content: flex-end; min-width: 255px; }
        .health-top-pill {
          display: inline-flex; align-items: center; gap: 7px; padding: 6px 9px;
          border: 1px solid rgba(224, 237, 222, .15); border-radius: 999px;
          color: rgba(231, 239, 228, .76); background: rgba(11, 26, 22, .42);
          font: 9px ui-monospace, SFMono-Regular, monospace; letter-spacing: .08em; white-space: nowrap;
        }
        .health-top-pill .pulse {
          width: 6px; height: 6px; border-radius: 50%; background: #a6dfbc;
          box-shadow: 0 0 9px rgba(166, 223, 188, .66);
        }
        .health-clock { color: rgba(230, 237, 225, .65); font: 10px ui-monospace, SFMono-Regular, monospace; min-width: 66px; text-align: right; }
        .health-intro {
          min-height: 89px; display: flex; align-items: center; justify-content: space-between;
          padding: 11px 0 12px;
        }
        .health-kicker {
          display: flex; align-items: center; gap: 7px; margin-bottom: 4px;
          color: rgba(202, 220, 199, .68); font: 9px ui-monospace, SFMono-Regular, monospace;
          letter-spacing: .16em; text-transform: uppercase;
        }
        .health-kicker-dot { height: 4px; width: 4px; border-radius: 50%; background: #c5d7c0; opacity: .8; }
        .health-titleline { gap: 13px; }
        .health-title { margin: 0; font-size: 27px; line-height: 1; font-weight: 550; letter-spacing: -.04em; }
        .health-title-description { margin-top: 6px; color: rgba(223, 231, 218, .59); font-size: 11px; }
        .health-state-pill {
          display: flex; align-items: center; gap: 8px; height: 30px; padding: 0 11px;
          border-radius: 7px; border: 1px solid ${LEVEL[overallLevel].border};
          background: ${LEVEL[overallLevel].tint}; color: ${LEVEL[overallLevel].color};
          font: 9px ui-monospace, SFMono-Regular, monospace; letter-spacing: .11em;
        }
        .health-state-pill svg { opacity: .85; }
        .health-summary {
          height: 76px; padding: 0 17px; margin-bottom: 13px;
          border-radius: 13px; border: 1px solid rgba(234, 243, 229, .18);
          background: linear-gradient(115deg, rgba(16, 34, 29, .84), rgba(18, 39, 32, .68));
          box-shadow: inset 0 1px rgba(255,255,255,.06), 0 12px 35px rgba(4, 12, 9, .17);
          backdrop-filter: blur(18px);
        }
        .health-summary-overall { display: flex; align-items: center; gap: 12px; width: 224px; }
        .health-summary-symbol {
          width: 38px; height: 38px; border-radius: 10px; display: grid; place-items: center;
          color: ${LEVEL[overallLevel].color}; background: ${LEVEL[overallLevel].tint};
          border: 1px solid ${LEVEL[overallLevel].border};
        }
        .health-summary-label { gap: 7px; color: rgba(230, 238, 226, .64); font-size: 9px; letter-spacing: .1em; text-transform: uppercase; }
        .health-summary-state { margin-top: 3px; color: ${LEVEL[overallLevel].color}; font-size: 14px; font-weight: 650; }
        .health-summary-divider { width: 1px; height: 39px; background: rgba(230, 239, 227, .14); }
        .health-stat { min-width: 122px; padding: 0 17px; }
        .health-stat-value { display: flex; align-items: center; gap: 7px; font: 19px/1.1 ui-monospace, SFMono-Regular, monospace; letter-spacing: -.05em; }
        .health-stat-name { margin-top: 5px; color: rgba(226, 235, 221, .48); font: 8px ui-monospace, SFMono-Regular, monospace; letter-spacing: .1em; text-transform: uppercase; }
        .health-stat-dot { width: 7px; height: 7px; border-radius: 50%; }
        .health-summary-spacer { flex: 1; }
        .health-freshness {
          display: flex; align-items: center; gap: 10px; padding-left: 17px;
          border-left: 1px solid rgba(230, 239, 227, .14);
        }
        .health-freshness-icon { color: #bed7c0; }
        .health-fresh-value { color: #edf2e7; font: 16px ui-monospace, SFMono-Regular, monospace; }
        .health-fresh-label { margin-top: 4px; color: rgba(226, 235, 221, .48); font: 8px ui-monospace, SFMono-Regular, monospace; letter-spacing: .08em; text-transform: uppercase; }
        .health-main { height: calc(100% - 55px - 89px - 76px - 13px - 36px - 16px); min-height: 440px; display: grid; grid-template-columns: minmax(0, 1.84fr) minmax(340px, .96fr); gap: 13px; }
        .health-glass {
          min-width: 0; min-height: 0; border-radius: 14px;
          border: 1px solid rgba(229, 240, 226, .19);
          background: linear-gradient(135deg, rgba(20, 38, 31, .78), rgba(11, 25, 22, .77));
          box-shadow: inset 0 1px 0 rgba(255,255,255,.07), 0 18px 46px rgba(3, 11, 8, .2);
          backdrop-filter: blur(19px);
        }
        .health-topology-panel { display: flex; flex-direction: column; overflow: hidden; }
        .health-panel-heading { height: 48px; flex: 0 0 48px; justify-content: space-between; padding: 0 17px; border-bottom: 1px solid rgba(228, 238, 223, .12); }
        .health-panel-title-group { display: flex; align-items: center; gap: 9px; }
        .health-panel-title-icon { width: 25px; height: 25px; display: grid; place-items: center; color: #c4d7bf; border: 1px solid rgba(205, 224, 199, .2); border-radius: 7px; background: rgba(210, 230, 204, .07); }
        .health-panel-title { color: #e8eee4; font-size: 10px; font-weight: 680; letter-spacing: .12em; text-transform: uppercase; }
        .health-panel-subtitle { margin-top: 3px; color: rgba(220, 232, 214, .45); font: 8px ui-monospace, SFMono-Regular, monospace; letter-spacing: .04em; }
        .health-legend { gap: 13px; }
        .health-legend-item { display: flex; align-items: center; gap: 5px; color: rgba(224, 233, 220, .6); font: 8px ui-monospace, SFMono-Regular, monospace; text-transform: uppercase; }
        .health-legend-dot { width: 6px; height: 6px; border-radius: 50%; }
        .health-topology-wrap { height: 390px; min-height: 320px; flex: 1 1 auto; padding: 0 12px; display: flex; align-items: center; }
        .health-topology { width: 100%; height: 100%; overflow: visible; }
        .health-node { cursor: pointer; outline: none; }
        .health-node:focus .health-node-plate { stroke: #e4eeda; stroke-width: 2; }
        .health-node:hover .health-node-plate { fill: rgba(37, 59, 46, .94); }
        .health-node-content { width: 215px; height: 68px; display: flex; align-items: center; gap: 10px; padding: 0 12px; color: #e7eee3; font-family: "DM Sans", "Avenir Next", system-ui, sans-serif; }
        .health-node-icon { height: 31px; width: 31px; flex: 0 0 31px; border-radius: 9px; border: 1px solid; display: grid; place-items: center; }
        .health-node-copy { min-width: 0; flex: 1; }
        .health-node-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; font-weight: 650; letter-spacing: -.01em; }
        .health-node-meta { display: flex; align-items: center; gap: 6px; margin-top: 5px; color: rgba(220, 231, 217, .57); font: 8px ui-monospace, SFMono-Regular, monospace; white-space: nowrap; }
        .health-separator { color: rgba(216, 229, 212, .3); }
        .health-node-dot { width: 6px; height: 6px; flex: 0 0 6px; border-radius: 50%; }
        .health-topology-foot { height: 47px; flex: 0 0 47px; display: flex; align-items: center; justify-content: space-between; padding: 0 17px; border-top: 1px solid rgba(228, 238, 223, .12); color: rgba(223, 232, 219, .53); font: 8px ui-monospace, SFMono-Regular, monospace; letter-spacing: .05em; }
        .health-topology-foot-left { display: flex; align-items: center; gap: 7px; }
        .health-topology-foot-left svg { color: #bdcfb8; }
        .health-topology-foot-right { color: rgba(218, 229, 212, .36); }
        .health-side-panel { display: flex; flex-direction: column; overflow: hidden; }
        .health-alert-top { height: 50px; flex: 0 0 50px; padding: 0 16px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid rgba(228, 238, 223, .12); }
        .health-alert-title { display: flex; align-items: center; gap: 8px; font-size: 10px; font-weight: 680; letter-spacing: .12em; text-transform: uppercase; }
        .health-alert-title svg { color: #edcc87; }
        .health-alert-total { color: rgba(224, 234, 220, .48); font: 9px ui-monospace, SFMono-Regular, monospace; }
        .health-filter-row { display: flex; align-items: center; gap: 5px; padding: 10px 13px 8px; }
        .health-filter {
          border: 1px solid transparent; border-radius: 6px; padding: 5px 7px; cursor: pointer;
          color: rgba(220, 230, 216, .51); background: transparent;
          font: 8px ui-monospace, SFMono-Regular, monospace; transition: color .18s ease, background .18s ease, border-color .18s ease;
        }
        .health-filter:hover { color: #eef3e8; }
        .health-filter.active { color: #e7efe2; border-color: rgba(219, 235, 214, .2); background: rgba(212, 231, 205, .09); }
        .health-alert-list { min-height: 0; overflow: auto; flex: 1 1 auto; padding: 0 10px 6px; }
        .health-alert-card {
          padding: 10px 10px 9px; margin-bottom: 6px; cursor: pointer; border-radius: 9px;
          border: 1px solid rgba(229, 239, 225, .1); background: rgba(226, 237, 221, .035);
          transition: background .16s ease, border-color .16s ease, transform .16s ease;
        }
        .health-alert-card:hover { transform: translateY(-1px); background: rgba(226, 237, 221, .065); border-color: rgba(229, 239, 225, .2); }
        .health-alert-card.selected { border-color: rgba(230, 204, 145, .34); background: rgba(187, 146, 71, .075); }
        .health-alert-heading { gap: 7px; }
        .health-alert-name { color: #e9eee4; font-size: 10px; font-weight: 650; }
        .health-alert-badge { margin-left: auto; padding: 3px 5px; border-radius: 4px; border: 1px solid; font: 7px ui-monospace, SFMono-Regular, monospace; letter-spacing: .08em; }
        .health-alert-detail { margin: 6px 0 0 20px; color: rgba(219, 230, 216, .54); font-size: 9px; line-height: 1.42; }
        .health-alert-meta { gap: 9px; margin: 7px 0 0 20px; color: rgba(222, 232, 218, .42); font: 8px ui-monospace, SFMono-Regular, monospace; }
        .health-alert-meta svg { opacity: .72; }
        .health-kick { color: #e6aa77; }
        .health-empty { margin: auto; text-align: center; padding: 20px; color: rgba(219, 232, 215, .58); font-size: 10px; }
        .health-inspector { flex: 0 0 112px; padding: 12px 15px 10px; border-top: 1px solid rgba(228, 238, 223, .13); background: rgba(9, 20, 17, .26); }
        .health-inspector-head { justify-content: space-between; gap: 8px; }
        .health-inspector-title { color: rgba(225, 235, 220, .48); font: 8px ui-monospace, SFMono-Regular, monospace; letter-spacing: .13em; text-transform: uppercase; }
        .health-inspector-state { display: flex; align-items: center; gap: 5px; font: 8px ui-monospace, SFMono-Regular, monospace; letter-spacing: .06em; }
        .health-inspector-name { margin-top: 7px; color: #eff3e9; font-size: 12px; font-weight: 650; }
        .health-inspector-detail { display: -webkit-box; overflow: hidden; -webkit-line-clamp: 2; -webkit-box-orient: vertical; margin-top: 4px; color: rgba(218, 230, 215, .58); font-size: 9px; line-height: 1.35; }
        .health-footer { height: 36px; justify-content: space-between; color: rgba(216, 229, 211, .4); font: 8px ui-monospace, SFMono-Regular, monospace; letter-spacing: .07em; }
        .health-footer-left { display: flex; align-items: center; gap: 7px; }
        .health-readonly { display: inline-flex; align-items: center; gap: 5px; color: rgba(224, 235, 219, .6); }
        .health-no-report { height: 100%; min-height: 370px; display: flex; flex-direction: column; justify-content: center; align-items: center; padding: 30px; text-align: center; }
        .health-no-report-icon { display: grid; place-items: center; width: 42px; height: 42px; margin-bottom: 12px; border-radius: 12px; color: ${LEVEL.unknown.color}; background: ${LEVEL.unknown.tint}; border: 1px solid ${LEVEL.unknown.border}; }
        .health-no-report-title { color: ${LEVEL.unknown.color}; font: 10px ui-monospace, SFMono-Regular, monospace; letter-spacing: .14em; text-transform: uppercase; }
        .health-no-report-copy { max-width: 350px; margin-top: 7px; color: rgba(226, 234, 222, .57); font-size: 11px; line-height: 1.5; }
        @media (max-width: 1050px) {
          .health-page { padding: 0 18px 14px; min-height: 900px; height: auto; overflow: auto; }
          .health-main { height: auto; min-height: 0; grid-template-columns: 1fr; }
          .health-topology-panel { min-height: 470px; }
          .health-side-panel { min-height: 455px; }
          .health-summary-overall { width: 190px; }
          .health-stat { min-width: 98px; padding: 0 10px; }
        }
        @media (max-width: 720px) {
          .health-page { padding: 0 13px 14px; }
          .health-nav { display: none; }
          .health-brand { min-width: 0; }
          .health-top-meta { min-width: 0; }
          .health-top-pill { font-size: 0; padding: 8px; }
          .health-top-pill svg { width: 14px; height: 14px; }
          .health-intro { align-items: flex-start; }
          .health-title { font-size: 24px; }
          .health-summary { height: auto; min-height: 76px; flex-wrap: wrap; gap: 10px 0; padding: 12px; }
          .health-summary-overall { width: 100%; }
          .health-summary-divider { display: none; }
          .health-stat { min-width: 25%; padding: 0 7px; }
          .health-stat:first-of-type { padding-left: 0; }
          .health-summary-spacer { display: none; }
          .health-freshness { border-left: 1px solid rgba(230,239,227,.14); }
          .health-panel-heading { padding: 0 12px; }
          .health-legend { gap: 7px; }
          .health-legend-item { font-size: 7px; }
          .health-topology-wrap { height: 350px; padding: 0 2px; }
          .health-topology { min-width: 620px; }
          .health-topology-panel { overflow: auto; }
          .health-main { overflow: visible; }
        }
      `}</style>
      <div className="health-scene" aria-hidden="true" />

      <header className="health-topbar">
        <div className="health-brand">
          <div className="health-brand-mark"><Activity size={15} strokeWidth={1.7} /></div>
          <div>
            <div className="health-brand-name">ALGOEDGE</div>
            <div className="health-brand-sub">STREAMING OPERATIONS</div>
          </div>
        </div>
        <nav className="health-nav" aria-label="Streaming sections">
          <span className="health-nav-item">Overview</span>
          <span className="health-nav-item">Bots</span>
          <span className="health-nav-item">Events</span>
          <span className="health-nav-item active">Health</span>
        </nav>
        <div className="health-top-meta">
          <span className="health-top-pill"><span className="pulse" /> STREAMING VIEW</span>
          <span className="health-top-pill"><ShieldCheck size={11} /> READ ONLY</span>
          <time className="health-clock">{now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>
        </div>
      </header>

      <section className="health-intro">
        <div>
          <div className="health-kicker"><span className="health-kicker-dot" /> SYSTEM TELEMETRY <ChevronRight size={10} /> HEALTH</div>
          <div className="health-titleline">
            <h1 className="health-title">Health</h1>
            <div className="health-state-pill"><CircleDot size={11} /> {LEVEL[overallLevel].label.toUpperCase()} · {alerts.length} ACTIVE</div>
          </div>
          <div className="health-title-description">Service state, heartbeat freshness, and the paths between them.</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div className="health-kicker" style={{ justifyContent: "flex-end" }}>LATEST HEALTH REPORT</div>
          <div style={{ color: "#e4ece0", font: "11px ui-monospace, SFMono-Regular, monospace" }}>
            {reportAge < 2 ? "Just received" : `${reportAge}s ago`}
          </div>
        </div>
      </section>

      <section className="health-summary" aria-label="Health summary">
        <div className="health-summary-overall">
          <div className="health-summary-symbol"><Activity size={19} strokeWidth={1.7} /></div>
          <div>
            <div className="health-summary-label">Fleet health <span>·</span> report</div>
            <div className="health-summary-state">{overallLevel === "green" ? "All systems nominal" : overallLevel === "yellow" ? "Degraded · monitor" : overallLevel === "red" ? "Critical · investigate" : "Unknown · unavailable"}</div>
          </div>
        </div>
        <div className="health-summary-divider" />
        <div className="health-stat">
          <div className="health-stat-value" style={{ color: LEVEL.green.color }}><span className="health-stat-dot" style={{ background: LEVEL.green.color }} />{counts.green}</div>
          <div className="health-stat-name">Healthy</div>
        </div>
        <div className="health-stat">
          <div className="health-stat-value" style={{ color: LEVEL.yellow.color }}><span className="health-stat-dot" style={{ background: LEVEL.yellow.color }} />{counts.yellow + counts.red}</div>
          <div className="health-stat-name">Degraded / critical</div>
        </div>
        <div className="health-stat">
          <div className="health-stat-value" style={{ color: LEVEL.unknown.color }}><span className="health-stat-dot" style={{ background: LEVEL.unknown.color }} />{counts.unknown}</div>
          <div className="health-stat-name">Unknown</div>
        </div>
        <div className="health-summary-spacer" />
        <div className="health-freshness">
          <Clock3 className="health-freshness-icon" size={16} />
          <div>
            <div className="health-fresh-value">{freshestAge != null ? `${freshestAge.toFixed(0)}s` : "—"}</div>
            <div className="health-fresh-label">Freshest heartbeat</div>
          </div>
        </div>
      </section>

      <section className="health-main">
        <article className="health-glass health-topology-panel">
          <div className="health-panel-heading">
            <div className="health-panel-title-group">
              <div className="health-panel-title-icon"><Radio size={13} /></div>
              <div>
                <div className="health-panel-title">System topology</div>
                <div className="health-panel-subtitle">10 monitored subsystems · select a node for evidence</div>
              </div>
            </div>
            <div className="health-legend" aria-label="Status legend">
              {(["green", "yellow", "unknown"] as Level[]).map((level) => (
                <div className="health-legend-item" key={level}>
                  <span className="health-legend-dot" style={{ background: LEVEL[level].color }} />
                  {level === "green" ? "Healthy" : LEVEL[level].label}
                </div>
              ))}
            </div>
          </div>
          <div className="health-topology-wrap">
            {isLoading ? (
              <div className="health-no-report">
                <div className="health-no-report-icon"><Activity size={18} /></div>
                <div className="health-no-report-title">Scanning subsystems</div>
                <p className="health-no-report-copy">Waiting for the service health report.</p>
              </div>
            ) : hasError ? (
              <div className="health-no-report">
                <div className="health-no-report-icon"><X size={18} /></div>
                <div className="health-no-report-title">Health report failed</div>
                <p className="health-no-report-copy">The service returned an error. No subsystem state is inferred from a failed report.</p>
              </div>
            ) : !nodes ? (
              <div className="health-no-report">
                <div className="health-no-report-icon"><CircleDot size={18} /></div>
                <div className="health-no-report-title">Health data unavailable</div>
                <p className="health-no-report-copy">No subsystem report was returned. Health remains unknown until evidence is available.</p>
              </div>
            ) : (
              <Topology nodes={nodes} selected={selectedKey} onSelect={setSelectedKey} />
            )}
          </div>
          <div className="health-topology-foot">
            <div className="health-topology-foot-left"><Database size={11} /> CONNECTIVITY · {apiNode?.level === "green" ? "ALPACA API REACHABLE" : apiNode ? statusText(apiNode.level) : "UNKNOWN"}{apiNode?.latency_ms != null ? ` / ${apiNode.latency_ms} ms` : ""}</div>
            <div className="health-topology-foot-right">PATH STATE · WORST UPSTREAM HEALTH</div>
          </div>
        </article>

        <aside className="health-glass health-side-panel">
          <div className="health-alert-top">
            <div className="health-alert-title"><AlertTriangle size={14} /> Active alerts</div>
            <div className="health-alert-total">{alerts.length} component checks</div>
          </div>
          <div className="health-filter-row" aria-label="Filter alerts">
            {([
              ["all", `All ${alerts.length}`],
              ["red", `Critical ${counts.red}`],
              ["yellow", `Degraded ${counts.yellow}`],
              ["unknown", `Unknown ${counts.unknown}`],
            ] as const).map(([level, label]) => (
              <button
                className={`health-filter ${filter === level ? "active" : ""}`}
                key={level}
                type="button"
                onClick={() => setFilter(level)}
                aria-pressed={filter === level}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="health-alert-list">
            {visibleAlerts.length === 0 ? (
              <div className="health-empty">
                {filter === "all" ? (
                  <><Check size={14} style={{ verticalAlign: "middle", marginRight: 5, color: LEVEL.green.color }} /> All monitored checks are nominal.</>
                ) : `No ${filter === "red" ? "critical" : filter} checks in this report.`}
              </div>
            ) : visibleAlerts.map(([key, node]) => {
              const palette = LEVEL[node.level];
              const AlertIcon = node.level === "red" ? X : AlertTriangle;
              return (
                <button
                  key={key}
                  type="button"
                  className={`health-alert-card ${selectedKey === key ? "selected" : ""}`}
                  onClick={() => setSelectedKey(key)}
                  aria-label={`Inspect ${node.label}: ${palette.label}`}
                >
                  <div className="health-alert-heading">
                    <AlertIcon size={13} style={{ color: palette.color, flex: "0 0 auto" }} />
                    <span className="health-alert-name">{node.label}</span>
                    <span className="health-alert-badge" style={{ color: palette.color, borderColor: palette.border, background: palette.tint }}>
                      {node.level === "yellow" ? "DEGRADED" : node.level === "red" ? "CRITICAL" : "UNKNOWN"}
                    </span>
                  </div>
                  <div className="health-alert-detail">{node.detail}</div>
                  <div className="health-alert-meta">
                    {node.latency_ms != null && <span>{node.latency_ms} ms</span>}
                    {node.data_age_s != null && node.latency_ms == null && <span>{node.data_age_s.toFixed(0)} s old</span>}
                    {node.kick_pending && <span className="health-kick">KICK PENDING</span>}
                    {node.latency_ms == null && node.data_age_s == null && <span>Telemetry absent</span>}
                  </div>
                </button>
              );
            })}
          </div>
          <div className="health-inspector" aria-live="polite">
            <div className="health-inspector-head">
              <span className="health-inspector-title">Selected subsystem evidence</span>
              {selectedNode && (
                <span className="health-inspector-state" style={{ color: LEVEL[selectedNode.level].color }}>
                  <span className="health-legend-dot" style={{ background: LEVEL[selectedNode.level].color }} />
                  {statusText(selectedNode.level)}
                </span>
              )}
            </div>
            {selectedNode ? (
              <>
                <div className="health-inspector-name">{selectedNode.label}</div>
                <div className="health-inspector-detail">{selectedNode.detail} {formatMetric(selectedNode)}.</div>
              </>
            ) : (
              <>
                <div className="health-inspector-name">No subsystem selected</div>
                <div className="health-inspector-detail">Choose a topology node to inspect its latest status evidence.</div>
              </>
            )}
          </div>
        </aside>
      </section>

      <footer className="health-footer">
        <div className="health-footer-left">
          <span className="health-readonly"><ShieldCheck size={11} /> READ-ONLY MONITOR</span>
          <span>·</span>
          <span>NO CONTROL ACTIONS AVAILABLE</span>
        </div>
        <div>REPORT AGE {reportAge}s <span style={{ margin: "0 7px", opacity: .35 }}>·</span> LOCAL FIXTURE</div>
      </footer>
    </main>
  );
}