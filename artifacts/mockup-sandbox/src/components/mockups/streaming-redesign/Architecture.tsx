import { useCallback, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import {
  Activity,
  ArrowDownRight,
  ArrowRight,
  Boxes,
  ChevronRight,
  CircleDot,
  Database,
  GitBranch,
  Layers3,
  Network,
  Radio,
  Route,
  X,
} from "lucide-react";
import {
  COLUMN_COLORS,
  COLUMN_LABELS,
  EDGES,
  FLOWS,
  NODES,
  type ArchEdge,
  type ArchFlow,
  type ArchNode,
} from "../streaming-current/_shared/architectureData";

const MAP_W = 1080;
const NODE_W = 158;
const NODE_H = 58;
const NODE_GAP = 10;
const TOP = 20;
const HEADER_H = 38;
const PAD_X = 18;
const COL_COUNT = 5;
const COL_INK = ["#ffd2ae", "#b7eef1", "#d4c3ff", "#b9f0cf", "#ffe1a4"];

function getColX(col: number) {
  const step = (MAP_W - PAD_X * 2) / COL_COUNT;
  return PAD_X + step * col + step / 2;
}

function getNodeY(row: number) {
  return TOP + HEADER_H + row * (NODE_H + NODE_GAP) + NODE_H / 2;
}

function mapHeight() {
  return TOP + HEADER_H + (Math.max(...NODES.map((node) => node.row)) + 1) * (NODE_H + NODE_GAP) + 18;
}

function center(node: ArchNode) {
  return { x: getColX(node.col), y: getNodeY(node.row) };
}

function EdgePath({
  edge,
  highlighted,
  dimmed,
}: {
  edge: ArchEdge;
  highlighted: boolean;
  dimmed: boolean;
}) {
  const from = NODES.find((node) => node.id === edge.from);
  const to = NODES.find((node) => node.id === edge.to);
  if (!from || !to) return null;

  const a = center(from);
  const b = center(to);
  const sameCol = from.col === to.col;
  const goesRight = to.col > from.col;
  const colDiff = Math.abs(to.col - from.col);
  let sx = a.x + NODE_W / 2;
  let sy = a.y;
  let tx = b.x - NODE_W / 2;
  let ty = b.y;
  let path = "";

  if (sameCol) {
    sx = a.x;
    sy = a.y + NODE_H / 2;
    tx = b.x;
    ty = b.y - NODE_H / 2;
    const mid = (sy + ty) / 2;
    path = `M ${sx} ${sy} C ${sx} ${mid} ${tx} ${mid} ${tx} ${ty}`;
  } else if (goesRight) {
    const cp = Math.max(40, colDiff * 30);
    path = `M ${sx} ${sy} C ${sx + cp} ${sy} ${tx - cp} ${ty} ${tx} ${ty}`;
  } else {
    sx = a.x - NODE_W / 2;
    tx = b.x + NODE_W / 2;
    const cp = Math.max(40, colDiff * 30);
    path = `M ${sx} ${sy} C ${sx - cp} ${sy} ${tx + cp} ${ty} ${tx} ${ty}`;
  }

  const fromColor = from.color !== "#22d3ee" ? from.color : to.color;
  const stroke = highlighted ? fromColor : "rgba(222,235,226,.54)";
  const marker = `arch-arrow-${edge.id}`;
  return (
    <g opacity={dimmed ? 0.075 : highlighted ? 1 : 0.58} style={{ transition: "opacity .22s ease" }}>
      <defs>
        <marker id={marker} markerWidth="7" markerHeight="7" refX="5.8" refY="3.5" orient="auto">
          <path d="M0,0 L7,3.5 L0,7 Z" fill={stroke} />
        </marker>
      </defs>
      {highlighted && <path d={path} fill="none" stroke={stroke} strokeWidth="8" opacity=".12" strokeLinecap="round" />}
      <path
        d={path}
        fill="none"
        stroke={stroke}
        strokeWidth={highlighted ? 2 : 1.2}
        strokeLinecap="round"
        strokeDasharray={highlighted ? undefined : "3 5"}
        markerEnd={`url(#${marker})`}
      />
    </g>
  );
}

function ArchitectureNode({
  node,
  selected,
  highlighted,
  dimmed,
  onClick,
  onKeyDown,
}: {
  node: ArchNode;
  selected: boolean;
  highlighted: boolean;
  dimmed: boolean;
  onClick: () => void;
  onKeyDown: (event: ReactKeyboardEvent<SVGGElement>) => void;
}) {
  const { x, y } = center(node);
  const left = x - NODE_W / 2;
  const top = y - NODE_H / 2;
  const emphasis = selected || highlighted;
  return (
    <g
      role="button"
      tabIndex={0}
      aria-label={`Inspect ${node.label}`}
      aria-pressed={selected}
      onClick={onClick}
      onKeyDown={onKeyDown}
      style={{
        cursor: "pointer",
        opacity: dimmed ? 0.19 : 1,
        transition: "opacity .22s ease",
        outline: "none",
      }}
    >
      <rect
        x={left}
        y={top}
        width={NODE_W}
        height={NODE_H}
        rx={9}
        fill={emphasis ? `${node.color}25` : "rgba(13,29,27,.82)"}
        stroke={emphasis ? node.color : "rgba(227,240,228,.2)"}
        strokeWidth={selected ? 2 : highlighted ? 1.6 : 1}
      />
      <path
        d={`M${left + 12} ${top} H${left + NODE_W - 12}`}
        stroke={emphasis ? node.color : COLUMN_COLORS[node.col]}
        strokeWidth={2}
        opacity={emphasis ? 0.95 : 0.52}
      />
      <circle cx={left + NODE_W - 13} cy={top + 14} r={3.4} fill={emphasis ? node.color : "rgba(215,232,218,.66)"} />
      <foreignObject x={left + 11} y={top + 7} width={NODE_W - 27} height={NODE_H - 12}>
        <div className="arch-node-copy">
          <div className="arch-node-label" style={{ color: emphasis ? node.color : "#f1f3eb" }}>{node.label}</div>
          <div className="arch-node-sub">{node.subtitle}</div>
        </div>
      </foreignObject>
    </g>
  );
}

function ColumnHeaders() {
  return (
    <>
      {([0, 1, 2, 3, 4] as const).map((col) => {
        const x = getColX(col);
        return (
          <g key={col}>
            <rect
              x={x - NODE_W / 2}
              y={TOP}
              width={NODE_W}
              height={HEADER_H - 7}
              rx={6}
              fill={`${COLUMN_COLORS[col]}18`}
              stroke={`${COLUMN_COLORS[col]}55`}
            />
            <text
              x={x}
              y={TOP + (HEADER_H - 7) / 2 + 3}
              textAnchor="middle"
              fill={COL_INK[col]}
              style={{ fontSize: 9, fontFamily: "ui-monospace, monospace", fontWeight: 700, letterSpacing: ".16em" }}
            >
              {COLUMN_LABELS[col]}
            </text>
          </g>
        );
      })}
    </>
  );
}

function DotField({ width, height }: { width: number; height: number }) {
  const marks = [];
  for (let y = 12; y < height; y += 25) {
    for (let x = 10; x < width; x += 25) {
      marks.push(<circle key={`${x}:${y}`} cx={x} cy={y} r=".8" fill="rgba(220,235,222,.16)" />);
    }
  }
  return <g aria-hidden="true">{marks}</g>;
}

function Sidebar({
  activeFlow,
  selectedNode,
  onSelectFlow,
  onClear,
  onCloseNode,
}: {
  activeFlow: ArchFlow | null;
  selectedNode: ArchNode | null;
  onSelectFlow: (flow: ArchFlow) => void;
  onClear: () => void;
  onCloseNode: () => void;
}) {
  return (
    <aside className="arch-side glass-panel">
      <div className="arch-side-head">
        <div>
          <div className="arch-kicker">{activeFlow ? "ROUTE INSPECTOR" : selectedNode ? "COMPONENT RECORD" : "FLOW CATALOG"}</div>
          <div className="arch-side-title">{activeFlow ? "Selected route" : selectedNode ? "Node details" : "Operational flows"}</div>
        </div>
        {(activeFlow || selectedNode) && (
          <button className="arch-icon-btn" onClick={onClear} aria-label="Clear current selection" title="Clear selection">
            <X size={15} />
          </button>
        )}
      </div>

      {selectedNode && !activeFlow ? (
        <div className="arch-node-detail">
          <div className="arch-detail-chip" style={{ color: selectedNode.color, borderColor: `${selectedNode.color}66` }}>
            <CircleDot size={12} /> {COLUMN_LABELS[selectedNode.col]}
          </div>
          <h2>{selectedNode.label}</h2>
          <div className="arch-node-subtitle">{selectedNode.subtitle}</div>
          <p>{selectedNode.description}</p>
          <div className="arch-detail-meta">
            <span>COMPONENT ID</span>
            <code>{selectedNode.id}</code>
          </div>
          <button className="arch-clear-btn" onClick={onCloseNode}>Close component record <X size={13} /></button>
          <div className="arch-detail-note">
            <Activity size={14} />
            <span>Topology reference only. Runtime availability is not reported by this map.</span>
          </div>
        </div>
      ) : (
        <>
          <div className="arch-flow-guidance">
            <Route size={14} />
            <span>Select a flow to trace its route across the architecture map.</span>
          </div>
          <div className="arch-flow-list">
            {FLOWS.map((flow, index) => {
              const isActive = activeFlow?.id === flow.id;
              return (
                <button
                  key={flow.id}
                  className={`arch-flow-item ${isActive ? "is-active" : ""}`}
                  onClick={() => onSelectFlow(flow)}
                  aria-pressed={isActive}
                >
                  <span className="arch-flow-index">0{index + 1}</span>
                  <span className="arch-flow-main">
                    <span className="arch-flow-name">{flow.label}</span>
                    <span className="arch-flow-desc">{flow.description}</span>
                  </span>
                  <ChevronRight size={15} className="arch-flow-chevron" />
                </button>
              );
            })}
          </div>
          {activeFlow ? (
            <div className="arch-step-box">
              <div className="arch-step-heading"><GitBranch size={14} /> Route sequence</div>
              {activeFlow.steps.map((step, index) => (
                <div className="arch-step" key={`${activeFlow.id}-${index}`}>
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <p>{step}</p>
                </div>
              ))}
              <button className="arch-clear-btn" onClick={onClear}>Clear route <X size={13} /></button>
            </div>
          ) : (
            <div className="arch-side-empty">
              <div className="arch-empty-mark"><Network size={18} /></div>
              <strong>Read the system left to right</strong>
              <span>Choose a flow above, or select any component in the map to inspect its source description.</span>
            </div>
          )}
        </>
      )}
      <div className="arch-side-foot">
        <span className="arch-live-pin" /> SOURCE MAP
        <span className="arch-foot-sep">/</span>
        {NODES.length} components
      </div>
    </aside>
  );
}

export function Architecture() {
  const [activeFlow, setActiveFlow] = useState<ArchFlow | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const selectedNode = NODES.find((node) => node.id === selectedNodeId) ?? null;
  const highlightedNodeIds = activeFlow ? new Set(activeFlow.nodeIds) : null;
  const highlightedEdgeIds = activeFlow ? new Set(activeFlow.edgeIds) : null;

  const selectNode = useCallback((nodeId: string) => {
    if (activeFlow) return;
    setSelectedNodeId((current) => current === nodeId ? null : nodeId);
  }, [activeFlow]);

  const selectFlow = useCallback((flow: ArchFlow) => {
    setActiveFlow((current) => current?.id === flow.id ? null : flow);
    setSelectedNodeId(null);
  }, []);

  const clear = useCallback(() => {
    setActiveFlow(null);
    setSelectedNodeId(null);
  }, []);

  const svgH = mapHeight();
  return (
    <main className="arch-page">
      <div className="arch-photo" aria-hidden="true" />
      <div className="arch-wash" aria-hidden="true" />
      <div className="arch-grain" aria-hidden="true" />

      <div className="arch-shell">
        <header className="arch-header">
          <div className="arch-brand">
            <div className="arch-brand-mark"><Boxes size={20} strokeWidth={1.7} /></div>
            <div>
              <div className="arch-eyebrow">STREAMING PLATFORM <span>·</span> SYSTEM MAP</div>
              <h1>Architecture <span>&amp; flows</span></h1>
            </div>
          </div>
          <div className="arch-header-meta">
            <div className="arch-map-stamp"><span className="arch-stamp-dot" /> SOURCE TOPOLOGY</div>
            <div className="arch-counts">
              <span><b>{NODES.length}</b> components</span>
              <i />
              <span><b>{EDGES.length}</b> connections</span>
              <i />
              <span><b>{FLOWS.length}</b> defined flows</span>
            </div>
          </div>
        </header>

        <section className="arch-workspace">
          <div className="arch-map-panel glass-panel">
            <div className="arch-map-topline">
              <div className="arch-map-title">
                <span className="arch-map-icon"><Layers3 size={15} /></span>
                <div>
                  <strong>Platform topology</strong>
                  <span>Component boundaries and directional data paths</span>
                </div>
              </div>
              <div className="arch-map-hint"><span>01</span> SELECT A NODE <ArrowRight size={12} /> INSPECT</div>
            </div>
            <div
              className="arch-svg-wrap"
              onClick={(event) => { if (event.target === event.currentTarget) clear(); }}
            >
              <svg
                viewBox={`0 0 ${MAP_W} ${svgH}`}
                preserveAspectRatio="xMidYMid meet"
                role="img"
                aria-label="Platform architecture map showing components and directional connections"
              >
                <DotField width={MAP_W} height={svgH} />
                <ColumnHeaders />
                {EDGES.map((edge) => {
                  const highlighted = highlightedEdgeIds?.has(edge.id) ?? false;
                  return <EdgePath key={edge.id} edge={edge} highlighted={highlighted} dimmed={!!highlightedEdgeIds && !highlighted} />;
                })}
                {NODES.map((node) => {
                  const highlighted = highlightedNodeIds?.has(node.id) ?? false;
                  return (
                    <ArchitectureNode
                      key={node.id}
                      node={node}
                      selected={selectedNodeId === node.id}
                      highlighted={highlighted}
                      dimmed={!!highlightedNodeIds && !highlighted}
                      onClick={() => selectNode(node.id)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          selectNode(node.id);
                        }
                      }}
                    />
                  );
                })}
              </svg>
            </div>
            <div className="arch-map-foot">
              <span><Radio size={13} /> Left-to-right system boundary</span>
              {activeFlow ? (
                <span className="arch-active-route"><Route size={13} /> Tracing: {activeFlow.label}</span>
              ) : (
                <span><ArrowDownRight size={13} /> Analysis models are not trading engines</span>
              )}
            </div>
          </div>

          <Sidebar
            activeFlow={activeFlow}
            selectedNode={selectedNode}
            onSelectFlow={selectFlow}
            onClear={clear}
            onCloseNode={() => setSelectedNodeId(null)}
          />
        </section>

        <footer className="arch-legend glass-panel">
          <div className="arch-legend-title"><Database size={13} /> SYSTEM LAYERS</div>
          {([0, 1, 2, 3, 4] as const).map((col) => (
            <div className="arch-legend-item" key={col}>
              <span style={{ background: COLUMN_COLORS[col], boxShadow: `0 0 10px ${COLUMN_COLORS[col]}66` }} />
              {COLUMN_LABELS[col]}
            </div>
          ))}
          <div className="arch-legend-key"><span className="arch-dash-key" /> Data flow</div>
          <div className="arch-legend-key"><span className="arch-solid-key" /> Selected route</div>
          <div className="arch-legend-end">Click empty map space to reset</div>
        </footer>
      </div>

      <style>{`
        .arch-page {
          --ink: #f1f1e9; --muted: rgba(226,235,223,.63); --quiet: rgba(220,231,218,.42);
          position: relative; width: 100%; height: 100%; min-height: 720px; overflow: hidden;
          color: var(--ink); font-family: "Avenir Next", Avenir, "Segoe UI", sans-serif;
          background: #10221d; isolation: isolate;
        }
        .arch-photo,.arch-wash,.arch-grain { position:absolute; inset:0; pointer-events:none; }
        .arch-photo { z-index:-3; background: url("/__mockup/images/streaming-forest-atmosphere.jpg") center 49%/cover no-repeat; filter: saturate(.55) contrast(.84); transform:scale(1.015); }
        .arch-wash { z-index:-2; background: linear-gradient(105deg,rgba(8,24,22,.84) 0%,rgba(9,26,24,.76) 48%,rgba(12,25,21,.84) 100%),linear-gradient(180deg,rgba(18,34,28,.08),rgba(8,20,19,.72)); }
        .arch-grain { z-index:-1; opacity:.09; background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.8' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.23'/%3E%3C/svg%3E"); }
        .arch-shell { box-sizing:border-box; height:100%; min-height:720px; padding:24px 30px 19px; display:flex; flex-direction:column; gap:18px; }
        .arch-header { height:79px; flex:none; display:flex; align-items:center; justify-content:space-between; padding:0 2px 14px; border-bottom:1px solid rgba(227,239,223,.2); }
        .arch-brand { display:flex; gap:14px; align-items:center; }
        .arch-brand-mark { width:42px; height:42px; border-radius:13px; display:grid; place-items:center; color:#d4e6d0; border:1px solid rgba(219,237,213,.33); background:linear-gradient(145deg,rgba(229,242,220,.18),rgba(219,228,206,.035)); box-shadow:inset 0 1px rgba(255,255,255,.18),0 8px 24px rgba(0,0,0,.14); }
        .arch-eyebrow,.arch-kicker { color:rgba(223,236,218,.55); font:700 9px/1.2 ui-monospace,SFMono-Regular,monospace; letter-spacing:.19em; }
        .arch-eyebrow span { color:#bdc9a2; padding:0 5px; }
        .arch-brand h1 { margin:6px 0 0; font-size:24px; font-weight:580; letter-spacing:-.035em; line-height:1; color:#f4f2e8; }
        .arch-brand h1 span { color:rgba(238,239,220,.62); font-weight:400; }
        .arch-header-meta { display:flex; flex-direction:column; align-items:flex-end; gap:10px; }
        .arch-map-stamp { font:700 9px ui-monospace,monospace; letter-spacing:.13em; color:#dce9d3; display:flex; gap:8px; align-items:center; }
        .arch-stamp-dot,.arch-live-pin { width:6px; height:6px; border-radius:50%; display:inline-block; background:#b8d19e; box-shadow:0 0 9px rgba(190,221,157,.6); }
        .arch-counts { color:var(--muted); display:flex; gap:12px; align-items:center; font:10px ui-monospace,monospace; }
        .arch-counts b { color:#f4f1e7; font-size:11px; font-weight:700; }
        .arch-counts i { width:1px; height:12px; background:rgba(230,238,222,.23); }
        .glass-panel { background:linear-gradient(145deg,rgba(20,39,34,.79),rgba(16,31,29,.71)); border:1px solid rgba(223,237,221,.18); box-shadow:0 16px 45px rgba(0,0,0,.2),inset 0 1px rgba(255,255,255,.11); backdrop-filter:blur(17px) saturate(110%); -webkit-backdrop-filter:blur(17px) saturate(110%); }
        .arch-workspace { display:flex; flex:1; min-height:0; gap:14px; }
        .arch-map-panel { min-width:0; flex:1; display:flex; flex-direction:column; border-radius:17px; overflow:hidden; }
        .arch-map-topline { flex:none; min-height:61px; box-sizing:border-box; display:flex; align-items:center; justify-content:space-between; padding:11px 17px 10px; border-bottom:1px solid rgba(230,240,225,.13); background:linear-gradient(90deg,rgba(233,241,221,.055),transparent 55%); }
        .arch-map-title { display:flex; align-items:center; gap:11px; }
        .arch-map-icon { width:30px; height:30px; border:1px solid rgba(210,227,204,.22); background:rgba(218,233,210,.08); border-radius:9px; display:grid; place-items:center; color:#d0dec5; }
        .arch-map-title strong { display:block; font-size:12px; font-weight:650; letter-spacing:.01em; }
        .arch-map-title span:not(.arch-map-icon) { display:block; margin-top:3px; font-size:10px; color:var(--quiet); }
        .arch-map-hint { display:flex; align-items:center; gap:7px; color:rgba(224,235,219,.51); font:700 8px ui-monospace,monospace; letter-spacing:.11em; }
        .arch-map-hint span { color:#d2ddb9; border:1px solid rgba(218,233,208,.28); border-radius:4px; padding:3px 5px; }
        .arch-map-hint svg { color:rgba(210,226,202,.52); }
        .arch-svg-wrap { flex:1; min-height:0; position:relative; padding:3px 8px; overflow:hidden; }
        .arch-svg-wrap:before { content:""; position:absolute; inset:0; pointer-events:none; background:radial-gradient(ellipse at 50% 45%,rgba(173,193,142,.065),transparent 65%); }
        .arch-svg-wrap svg { display:block; width:100%; height:100%; position:relative; }
        .arch-node-copy { box-sizing:border-box; display:flex; height:100%; flex-direction:column; justify-content:center; gap:3px; overflow:hidden; }
        .arch-node-label { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font:700 10px/1.2 ui-monospace,SFMono-Regular,monospace; letter-spacing:.015em; }
        .arch-node-sub { color:rgba(221,232,216,.6); font:9px/1.2 ui-monospace,SFMono-Regular,monospace; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .arch-map-foot { flex:none; min-height:34px; padding:0 15px; box-sizing:border-box; border-top:1px solid rgba(230,240,225,.12); display:flex; align-items:center; justify-content:space-between; color:rgba(224,235,219,.51); font:9px ui-monospace,monospace; }
        .arch-map-foot span { display:flex; align-items:center; gap:7px; }
        .arch-map-foot svg { color:#bdd0ae; }
        .arch-map-foot .arch-active-route { color:#e3ebd1; }
        .arch-side { width:292px; flex:none; box-sizing:border-box; border-radius:17px; display:flex; flex-direction:column; min-height:0; overflow:hidden; }
        .arch-side-head { padding:17px 16px 13px; border-bottom:1px solid rgba(227,239,223,.13); display:flex; align-items:center; justify-content:space-between; }
        .arch-kicker { font-size:8px; letter-spacing:.17em; }
        .arch-side-title { margin-top:6px; font-size:16px; font-weight:560; letter-spacing:-.02em; }
        .arch-icon-btn { display:grid; place-items:center; color:#d8e3d0; border:1px solid rgba(226,238,220,.18); background:rgba(237,244,228,.07); width:29px; height:29px; border-radius:8px; cursor:pointer; }
        .arch-icon-btn:hover,.arch-clear-btn:hover { background:rgba(221,237,213,.14); }
        .arch-flow-guidance { display:flex; gap:9px; padding:12px 15px; align-items:flex-start; color:rgba(222,233,217,.61); font-size:10px; line-height:1.45; border-bottom:1px solid rgba(227,239,223,.1); }
        .arch-flow-guidance svg { flex:none; margin-top:1px; color:#c3d5b0; }
        .arch-flow-list { padding:6px 8px 7px; display:grid; gap:4px; }
        .arch-flow-item { width:100%; display:flex; align-items:flex-start; gap:10px; padding:11px 9px; text-align:left; cursor:pointer; border:1px solid transparent; border-radius:10px; background:transparent; color:inherit; transition:background .18s,border-color .18s; }
        .arch-flow-item:hover { background:rgba(233,242,225,.06); }
        .arch-flow-item.is-active { background:linear-gradient(100deg,rgba(205,222,174,.13),rgba(205,222,174,.045)); border-color:rgba(210,228,184,.24); }
        .arch-flow-index { color:rgba(215,228,209,.42); font:700 9px ui-monospace,monospace; padding-top:2px; }
        .arch-flow-main { min-width:0; flex:1; }
        .arch-flow-name { display:block; color:#eff0e5; font-size:11px; line-height:1.35; font-weight:650; }
        .arch-flow-desc { display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; margin-top:5px; color:rgba(221,233,216,.56); font-size:9px; line-height:1.45; }
        .arch-flow-chevron { flex:none; margin-top:2px; color:rgba(222,235,219,.45); }
        .arch-flow-item.is-active .arch-flow-chevron { color:#dce7c6; }
        .arch-side-empty { margin:auto 17px; padding:18px 10px 22px; display:flex; flex-direction:column; align-items:flex-start; gap:8px; border-top:1px solid rgba(224,237,219,.1); color:rgba(229,237,224,.57); }
        .arch-empty-mark { width:34px; height:34px; border:1px solid rgba(218,233,210,.17); background:rgba(230,240,220,.07); border-radius:10px; display:grid; place-items:center; color:#d2dfc4; margin-bottom:3px; }
        .arch-side-empty strong { color:#e9ebdf; font-size:11px; font-weight:600; }
        .arch-side-empty span { font-size:9px; line-height:1.55; }
        .arch-step-box { border-top:1px solid rgba(224,237,219,.14); padding:12px 14px 14px; overflow:auto; }
        .arch-step-heading { display:flex; align-items:center; gap:7px; color:#e6ebd8; font:700 9px ui-monospace,monospace; letter-spacing:.1em; text-transform:uppercase; margin-bottom:8px; }
        .arch-step-heading svg { color:#c7d6b4; }
        .arch-step { display:flex; gap:9px; align-items:flex-start; padding:6px 0; }
        .arch-step > span { flex:none; font:700 8px ui-monospace,monospace; color:#c6d3af; border:1px solid rgba(205,220,183,.25); border-radius:5px; padding:3px 4px; }
        .arch-step p { margin:1px 0 0; font-size:9px; color:rgba(228,235,223,.7); line-height:1.45; }
        .arch-node-detail { padding:15px 16px; overflow:auto; }
        .arch-detail-chip { display:inline-flex; gap:6px; align-items:center; border:1px solid; border-radius:6px; padding:5px 7px; font:700 8px ui-monospace,monospace; letter-spacing:.1em; }
        .arch-node-detail h2 { margin:15px 0 5px; color:#f0f0e6; font-size:19px; font-weight:580; letter-spacing:-.035em; line-height:1.2; }
        .arch-node-subtitle { color:rgba(224,235,218,.6); font:9px ui-monospace,monospace; }
        .arch-node-detail p { margin:17px 0 20px; color:rgba(230,237,223,.78); font-size:11px; line-height:1.62; }
        .arch-detail-meta { border-top:1px solid rgba(225,236,218,.13); border-bottom:1px solid rgba(225,236,218,.13); padding:11px 0; display:flex; flex-direction:column; gap:6px; }
        .arch-detail-meta span { color:rgba(220,232,215,.45); font:700 8px ui-monospace,monospace; letter-spacing:.13em; }
        .arch-detail-meta code { color:#dce8d0; font:10px ui-monospace,monospace; }
        .arch-clear-btn { width:100%; margin-top:12px; padding:8px 9px; display:flex; align-items:center; justify-content:space-between; color:rgba(228,237,222,.68); background:rgba(228,239,218,.045); border:1px solid rgba(222,235,217,.14); border-radius:7px; font-size:9px; cursor:pointer; }
        .arch-detail-note { display:flex; gap:8px; margin-top:15px; color:rgba(222,231,217,.49); font-size:9px; line-height:1.5; }
        .arch-detail-note svg { flex:none; color:#c7d6b6; }
        .arch-side-foot { margin-top:auto; flex:none; padding:11px 15px; border-top:1px solid rgba(225,236,218,.13); color:rgba(224,235,219,.5); font:8px ui-monospace,monospace; letter-spacing:.08em; display:flex; align-items:center; gap:7px; }
        .arch-side-foot .arch-live-pin { width:5px; height:5px; }
        .arch-foot-sep { color:rgba(226,237,218,.25); }
        .arch-legend { min-height:45px; flex:none; border-radius:12px; padding:0 15px; display:flex; align-items:center; gap:21px; }
        .arch-legend-title { color:rgba(222,233,217,.58); display:flex; align-items:center; gap:7px; font:700 8px ui-monospace,monospace; letter-spacing:.13em; margin-right:2px; }
        .arch-legend-title svg { color:#d4e0c7; }
        .arch-legend-item { display:flex; align-items:center; gap:7px; color:rgba(230,237,223,.72); font:700 8px ui-monospace,monospace; letter-spacing:.08em; }
        .arch-legend-item > span { width:7px; height:7px; border-radius:2px; }
        .arch-legend-key { display:flex; align-items:center; gap:7px; color:rgba(226,235,220,.49); font:9px ui-monospace,monospace; }
        .arch-dash-key { width:19px; height:1px; border-top:1px dashed rgba(219,234,215,.67); }
        .arch-solid-key { width:19px; height:2px; background:#d2dfba; }
        .arch-legend-end { margin-left:auto; color:rgba(224,235,219,.43); font:9px ui-monospace,monospace; }
        @media (max-width:900px) {
          .arch-page,.arch-shell { min-height:760px; height:100%; }
          .arch-shell { padding:18px 16px 14px; gap:12px; }
          .arch-header { height:auto; min-height:74px; }
          .arch-workspace { flex-direction:column; overflow:auto; }
          .arch-map-panel { min-height:510px; }
          .arch-side { width:auto; min-height:340px; }
          .arch-svg-wrap { min-height:420px; overflow:auto; }
          .arch-svg-wrap svg { min-width:850px; }
          .arch-legend { gap:12px; flex-wrap:wrap; padding:9px 12px; }
          .arch-legend-end { display:none; }
        }
        @media (prefers-reduced-motion: reduce) {
          .arch-page *, .arch-page *:before, .arch-page *:after { transition:none !important; }
        }
      `}</style>
    </main>
  );
}