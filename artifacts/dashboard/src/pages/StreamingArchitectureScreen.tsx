import { useState, useRef, useEffect, useCallback, useMemo, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { X, ChevronRight } from "lucide-react";
import { NODES, EDGES, FLOWS, COLUMN_LABELS, COLUMN_COLORS, type ArchNode, type ArchEdge, type ArchFlow } from "@/data/architectureData";
import { formatBotLabel, useBotIdentity } from "@/lib/bot-identity";

const NODE_W = 152;
const NODE_H = 56;
const NODE_GAP = 10;
const COL_HEADER_H = 34;
const SVG_PADDING_X = 18;
const SVG_PADDING_TOP = 14;
const COL_COUNT = 5;
const NATURAL_W = 1040;
const COLUMN_TEXT_COLORS = ["#eaf0f4", "#eaf0f4", "#eaf0f4", "#eaf0f4", "#eaf0f4"] as const;

function getColX(col: number): number {
  const usable = NATURAL_W - SVG_PADDING_X * 2;
  const spacing = usable / COL_COUNT;
  return SVG_PADDING_X + spacing * col + spacing / 2;
}

function getNodeY(row: number): number {
  return SVG_PADDING_TOP + COL_HEADER_H + row * (NODE_H + NODE_GAP) + NODE_H / 2;
}

function svgHeight(): number {
  const maxRow = Math.max(...NODES.map((n) => n.row));
  return SVG_PADDING_TOP + COL_HEADER_H + (maxRow + 1) * (NODE_H + NODE_GAP) + 18;
}

function nodeCenter(node: ArchNode): { x: number; y: number } {
  return { x: getColX(node.col), y: getNodeY(node.row) };
}

function EdgePath({
  edge,
  nodes,
  highlighted,
  dimmed,
}: {
  edge: ArchEdge;
  nodes: ArchNode[];
  highlighted: boolean;
  dimmed: boolean;
}) {
  const src = nodes.find((n) => n.id === edge.from);
  const tgt = nodes.find((n) => n.id === edge.to);
  if (!src || !tgt) return null;

  const s = nodeCenter(src);
  const t = nodeCenter(tgt);

  const sameCol = src.col === tgt.col;
  let sx = s.x + NODE_W / 2;
  let sy = s.y;
  let tx = t.x - NODE_W / 2;
  let ty = t.y;

  // For cross-col edges going right→right, start from right edge → right edge
  // For backward edges (right to left columns), use bottom/top routing
  const goingRight = tgt.col > src.col;
  const goingLeft = tgt.col < src.col;
  const colDiff = Math.abs(tgt.col - src.col);

  let d = "";

  if (sameCol) {
    // vertical within same column
    sx = s.x;
    sy = s.y + NODE_H / 2;
    tx = t.x;
    ty = t.y - NODE_H / 2;
    const midY = (sy + ty) / 2;
    d = `M ${sx} ${sy} C ${sx} ${midY} ${tx} ${midY} ${tx} ${ty}`;
  } else if (goingRight) {
    // left edge of source → right edge of target going rightward
    sx = s.x + NODE_W / 2;
    sy = s.y;
    tx = t.x - NODE_W / 2;
    ty = t.y;
    const cp = Math.max(40, colDiff * 30);
    d = `M ${sx} ${sy} C ${sx + cp} ${sy} ${tx - cp} ${ty} ${tx} ${ty}`;
  } else if (goingLeft) {
    // going leftward (e.g. db_trades → api_claude_review, llm → api)
    sx = s.x - NODE_W / 2;
    sy = s.y;
    tx = t.x + NODE_W / 2;
    ty = t.y;
    const cp = Math.max(40, colDiff * 30);
    d = `M ${sx} ${sy} C ${sx - cp} ${sy} ${tx + cp} ${ty} ${tx} ${ty}`;
  }

  const opacity = dimmed ? 0.08 : highlighted ? 1 : 0.22;
  const strokeW = highlighted ? 2 : 1;
  const color = highlighted
    ? (src.color !== "#22d3ee" ? src.color : tgt.color)
    : "#94a3b8";
  const markerId = `arrow-${edge.id}`;

  return (
    <g style={{ transition: "opacity 0.25s" }} opacity={opacity}>
      <defs>
        <marker id={markerId} markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
          <path d="M0,0 L6,3 L0,6 Z" fill={color} opacity={highlighted ? 1 : 0.5} />
        </marker>
      </defs>
      {highlighted && (
        <path d={d} fill="none" stroke={color} strokeWidth={6} opacity={0.15} strokeLinecap="round" />
      )}
      <path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth={strokeW}
        strokeLinecap="round"
        markerEnd={`url(#${markerId})`}
        strokeDasharray={highlighted ? "none" : "4 4"}
      />
    </g>
  );
}

function ArchNodeBox({
  node,
  highlighted,
  dimmed,
  selected,
  onClick,
  onKeyDown,
}: {
  node: ArchNode;
  highlighted: boolean;
  dimmed: boolean;
  selected: boolean;
  onClick: () => void;
  onKeyDown: (event: ReactKeyboardEvent<SVGGElement>) => void;
}) {
  const { x, y } = nodeCenter(node);
  const nx = x - NODE_W / 2;
  const ny = y - NODE_H / 2;
  const colColor = COLUMN_COLORS[node.col];
  const nodeColor = node.color;

  const opacity = dimmed ? 0.15 : 1;
  const borderColor = selected
    ? nodeColor
    : highlighted
    ? nodeColor
    : "rgba(227,240,228,0.2)";
  const bgColor = selected
    ? "rgba(255,255,255,.18)"
    : highlighted
    ? "rgba(255,255,255,.11)"
    : "rgba(18,27,36,.62)";
  const glowFilter = (highlighted || selected)
    ? "drop-shadow(0 0 5px rgba(255,255,255,.24))"
    : "none";

  return (
    <g
      role="button"
      tabIndex={0}
      data-testid={`architecture-node-${node.id}`}
      aria-label={`Inspect ${node.label}`}
      style={{ cursor: "pointer", opacity, transition: "opacity 0.25s", filter: glowFilter }}
      onClick={onClick}
      onKeyDown={onKeyDown}
    >
      <rect
        x={nx}
        y={ny}
        width={NODE_W}
        height={NODE_H}
        rx={7}
        fill={bgColor}
        stroke={borderColor}
        strokeWidth={selected ? 1.8 : highlighted ? 1.4 : 1}
        style={{ transition: "all 0.2s" }}
      />
      {/* top-left corner accent */}
      <path
        d={`M ${nx + 10} ${ny} L ${nx} ${ny} L ${nx} ${ny + 10}`}
        fill="none"
        stroke={highlighted || selected ? nodeColor : colColor}
        strokeWidth={1.5}
        opacity={highlighted || selected ? 0.9 : 0.35}
      />
      {/* status dot */}
      <circle
        cx={nx + NODE_W - 10}
        cy={ny + 10}
        r={3}
        fill={highlighted || selected ? nodeColor : "rgba(215,232,218,.66)"}
      />
      {/* label via foreignObject */}
      <foreignObject x={nx + 8} y={ny + 6} width={NODE_W - 16} height={NODE_H - 12}>
        <div
          style={{
            fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            height: "100%",
            gap: 2,
          }}
        >
          <div
            style={{
              fontSize: 10,
              fontWeight: 700,
              color: highlighted || selected ? nodeColor : "#f1f3eb",
              letterSpacing: "0.04em",
              lineHeight: 1.2,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {node.label}
          </div>
          <div
            style={{
              fontSize: 8,
              color: "rgba(221,232,216,.62)",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
              letterSpacing: "0.02em",
            }}
          >
            {node.subtitle}
          </div>
        </div>
      </foreignObject>
    </g>
  );
}

function ColumnHeaders() {
  return (
    <>
      {([0, 1, 2, 3, 4] as const).map((col) => {
        const cx = getColX(col);
        const textColor = COLUMN_TEXT_COLORS[col];
        return (
          <g key={col}>
            <rect
              x={cx - NODE_W / 2}
              y={SVG_PADDING_TOP}
              width={NODE_W}
              height={COL_HEADER_H - 6}
              rx={5}
              fill="rgba(255,255,255,.07)"
              stroke="rgba(255,255,255,.2)"
              strokeWidth={1}
            />
            <text
              x={cx}
              y={SVG_PADDING_TOP + (COL_HEADER_H - 6) / 2 + 4}
              textAnchor="middle"
              style={{
                fontSize: 8,
                fontFamily: "'JetBrains Mono', monospace",
                fontWeight: 700,
                fill: textColor,
                letterSpacing: "0.18em",
              }}
            >
              {COLUMN_LABELS[col]}
            </text>
          </g>
        );
      })}
    </>
  );
}

function NodePopover({ node, onClose }: { node: ArchNode; onClose: () => void }) {
  const { x, y } = nodeCenter(node);
  const popW = 220;
  const popH = 90;
  let px = x + NODE_W / 2 + 8;
  let py = y - popH / 2;
  if (px + popW > NATURAL_W - 10) px = x - NODE_W / 2 - popW - 8;
  if (py < 4) py = 4;

  return (
    <foreignObject x={px} y={py} width={popW} height={popH + 20}>
      <div
        style={{
          background: "rgba(18,27,36,.92)",
          border: `1px solid ${node.color}55`,
          borderRadius: 8,
          padding: "10px 12px",
          boxShadow: "0 12px 30px rgba(0,0,0,.28), inset 0 1px rgba(255,255,255,.12)",
          backdropFilter: "blur(18px)",
          WebkitBackdropFilter: "blur(18px)",
          fontFamily: "'JetBrains Mono', monospace",
          position: "relative",
        }}
      >
        <button
          onClick={onClose}
          aria-label="Close node details"
          style={{
            position: "absolute",
            top: 6,
            right: 6,
            background: "none",
            border: "none",
            cursor: "pointer",
            color: "rgba(223,233,220,.58)",
            padding: 0,
            lineHeight: 1,
          }}
        >
          <X size={10} />
        </button>
        <div style={{ fontSize: 10, fontWeight: 700, color: node.color, marginBottom: 4 }}>
          {node.label}
        </div>
        <div style={{ fontSize: 8, color: "rgba(223,233,220,.7)", lineHeight: 1.5 }}>
          {node.description}
        </div>
      </div>
    </foreignObject>
  );
}

function FlowsSidebar({
  flows,
  activeFlow,
  onSelect,
  onClear,
}: {
  flows: ArchFlow[];
  activeFlow: ArchFlow | null;
  onSelect: (flow: ArchFlow) => void;
  onClear: () => void;
}) {
  return (
    <div
      className="stream-screen stream-screen-architecture"
      data-testid="architecture-flow-sidebar"
      style={{
        width: 264,
        flexShrink: 0,
        background: "linear-gradient(145deg,rgba(20,39,34,.88),rgba(12,27,24,.92))",
        borderLeft: "1px solid rgba(223,237,221,.16)",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "12px 14px 8px",
          borderBottom: "1px solid rgba(255,255,255,0.06)",
          flexShrink: 0,
        }}
      >
        <div
          style={{
            fontSize: 8,
            fontFamily: "'JetBrains Mono', monospace",
            fontWeight: 700,
            letterSpacing: "0.22em",
            color: "rgba(148,163,184,0.5)",
            textTransform: "uppercase",
            marginBottom: 2,
          }}
        >
          Flows
        </div>
        <div style={{ fontSize: 10, color: "rgba(148,163,184,0.35)", fontFamily: "monospace" }}>
          Click a flow to highlight the path
        </div>
      </div>

      {/* Flow list */}
      <div style={{ flex: 1, overflowY: "auto", padding: "6px 0" }}>
        {flows.map((flow) => {
          const isActive = activeFlow?.id === flow.id;
          return (
            <button
              key={flow.id}
              data-testid={`architecture-flow-${flow.id}`}
              aria-pressed={isActive}
              onClick={() => onSelect(flow)}
              style={{
                width: "100%",
                textAlign: "left",
                padding: "8px 14px",
                 background: isActive ? "rgba(255,255,255,0.11)" : "transparent",
                border: "none",
                 borderLeft: isActive ? "2px solid rgba(255,255,255,.62)" : "2px solid transparent",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: 8,
                transition: "all 0.15s",
              }}
            >
                <ChevronRight
                size={10}
                  style={{ color: isActive ? "#d9e4c4" : "rgba(223,233,220,0.38)", flexShrink: 0 }}
              />
              <div>
                <div
                  style={{
                    fontSize: 10,
                    fontWeight: 700,
                    fontFamily: "'JetBrains Mono', monospace",
                    color: isActive ? "#e6e9d7" : "rgba(226,235,223,0.7)",
                    marginBottom: 2,
                  }}
                >
                  {flow.label}
                </div>
                <div
                  style={{
                    fontSize: 8,
                    color: "rgba(148,163,184,0.4)",
                    fontFamily: "monospace",
                    lineHeight: 1.4,
                  }}
                >
                  {flow.description.slice(0, 60)}…
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {/* Active flow steps */}
      {activeFlow && (
        <div
          style={{
            borderTop: "1px solid rgba(255,255,255,0.07)",
            background: "rgba(8,16,40,0.8)",
            flexShrink: 0,
            maxHeight: 260,
            overflow: "hidden",
            display: "flex",
            flexDirection: "column",
          }}
        >
          <div
            style={{
              padding: "8px 14px 6px",
              borderBottom: "1px solid rgba(255,255,255,0.05)",
              flexShrink: 0,
            }}
          >
            <div
              style={{
                fontSize: 8,
                fontFamily: "'JetBrains Mono', monospace",
                fontWeight: 700,
                letterSpacing: "0.2em",
                color: "rgba(148,163,184,0.45)",
                textTransform: "uppercase",
              }}
            >
              Steps
            </div>
          </div>
          <div style={{ overflowY: "auto", padding: "6px 0 8px" }}>
            {activeFlow.steps.map((step, i) => (
              <div
                key={i}
                style={{
                  display: "flex",
                  gap: 8,
                  padding: "5px 14px",
                  alignItems: "flex-start",
                }}
              >
                <div
                  style={{
                    flexShrink: 0,
                    width: 16,
                    height: 16,
                    borderRadius: "50%",
                    background: "rgba(99,102,241,0.2)",
                    border: "1px solid rgba(99,102,241,0.4)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 8,
                    fontWeight: 700,
                    color: "#a5b4fc",
                    fontFamily: "monospace",
                    marginTop: 1,
                  }}
                >
                  {i + 1}
                </div>
                <div
                  style={{
                    fontSize: 8,
                    color: "rgba(148,163,184,0.7)",
                    fontFamily: "monospace",
                    lineHeight: 1.5,
                  }}
                >
                  {step}
                </div>
              </div>
            ))}
          </div>
          <div style={{ padding: "6px 14px 10px", flexShrink: 0 }}>
            <button
              onClick={onClear}
              style={{
                fontSize: 8,
                fontFamily: "'JetBrains Mono', monospace",
                fontWeight: 700,
                letterSpacing: "0.12em",
                color: "rgba(148,163,184,0.4)",
                background: "transparent",
                border: "1px solid rgba(255,255,255,0.08)",
                borderRadius: 4,
                padding: "4px 10px",
                cursor: "pointer",
                textTransform: "uppercase",
                width: "100%",
              }}
            >
              Clear selection
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function DotGrid({ width, height }: { width: number; height: number }) {
  const spacing = 24;
  const cols = Math.floor(width / spacing);
  const rows = Math.floor(height / spacing);
  const dots = [];
  for (let r = 0; r <= rows; r++) {
    for (let c = 0; c <= cols; c++) {
      dots.push(
        <circle
          key={`${r}-${c}`}
          cx={c * spacing}
          cy={r * spacing}
          r={0.8}
          fill="rgba(148,163,184,0.08)"
        />
      );
    }
  }
  return <g>{dots}</g>;
}

export default function StreamingArchitectureScreen() {
  const [activeFlow, setActiveFlow] = useState<ArchFlow | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const { getBotIdentity } = useBotIdentity();
  const nodes = useMemo(() => NODES.map((node) => {
    if (!node.botId) return node;
    const identity = getBotIdentity(node.botId);
    return {
      ...node,
      label: formatBotLabel(identity),
      subtitle: identity.subtitle || node.subtitle,
    };
  }), [getBotIdentity]);

  const selectedNode = nodes.find((n) => n.id === selectedNodeId) ?? null;

  const highlightedNodeIds = activeFlow ? new Set(activeFlow.nodeIds) : null;
  const highlightedEdgeIds = activeFlow ? new Set(activeFlow.edgeIds) : null;

  const handleNodeClick = useCallback(
    (nodeId: string) => {
      if (activeFlow) return;
      setSelectedNodeId((prev) => (prev === nodeId ? null : nodeId));
    },
    [activeFlow]
  );

  const handleFlowSelect = useCallback((flow: ArchFlow) => {
    setActiveFlow((prev) => (prev?.id === flow.id ? null : flow));
    setSelectedNodeId(null);
  }, []);

  const handleClear = useCallback(() => {
    setActiveFlow(null);
    setSelectedNodeId(null);
  }, []);

  const svgH = svgHeight();

  return (
    <div
      className="stream-screen stream-screen-architecture"
      data-testid="architecture-screen"
      style={{
        height: "100%",
        width: "100%",
        display: "flex",
        flexDirection: "column",
        background: "transparent",
        overflow: "hidden",
        fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      }}
    >
      <style>{`
        .stream-screen-architecture[data-testid="architecture-screen"] { isolation:isolate; color:#f1f1e9; }
        .stream-screen-architecture[data-testid="architecture-screen"] { background:transparent !important; color:#f1f1e9 !important; }
        .stream-screen-architecture[data-testid="architecture-screen"] [style*="rgba(148,163,184"],.stream-screen-architecture[data-testid="architecture-screen"] [style*="rgba(148, 163, 184"],.stream-screen-architecture[data-testid="architecture-screen"] [class*="text-slate-"] { color:rgba(245,248,251,.88) !important; text-shadow:0 1px 3px rgba(0,0,0,.3) !important; }
        .stream-screen-architecture[data-testid="architecture-screen"] > div:first-of-type { background:rgba(18,27,36,.42) !important; border-bottom-color:rgba(255,255,255,.18) !important; }
        .stream-screen-architecture[data-testid="architecture-screen"] > div:nth-of-type(2) > div:first-child { background:radial-gradient(ellipse at 50% 40%,rgba(255,255,255,.055),transparent 68%); }
        .stream-screen-architecture[data-testid="architecture-screen"] > div:nth-of-type(3) { background:rgba(18,27,36,.46) !important; border-top-color:rgba(255,255,255,.18) !important; }
        .stream-screen-architecture[data-testid="architecture-flow-sidebar"] { background:rgba(18,27,36,.46) !important; color:#e4ebdd !important; backdrop-filter:blur(18px); }
        .stream-screen-architecture[data-testid="architecture-flow-sidebar"] [style*="rgba(148,163,184"],.stream-screen-architecture[data-testid="architecture-flow-sidebar"] [style*="rgba(148, 163, 184"] { color:rgba(245,248,251,.88) !important; text-shadow:0 1px 3px rgba(0,0,0,.3) !important; }
        .stream-screen-architecture[data-testid="architecture-flow-sidebar"] button:hover { background:rgba(233,242,225,.07) !important; }
      `}</style>
      {/* Page title — fixed strip */}
      <div
        style={{
          flexShrink: 0,
          padding: "9px 16px 7px",
          background: "linear-gradient(90deg, rgba(16,34,29,.9), rgba(18,34,28,.82))",
          borderBottom: "1px solid rgba(227,239,223,0.16)",
          display: "flex",
          alignItems: "baseline",
          gap: 10,
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 700, color: "#f4f2e8", letterSpacing: "0.04em" }}>
          System Architecture & Flows
        </span>
        <span style={{ fontSize: 9, color: "rgba(148,163,184,0.35)", letterSpacing: "0.08em" }}>
          {NODES.length} components · {EDGES.length} connections · {FLOWS.length} flows
        </span>
        {activeFlow && (
          <span
            style={{
              fontSize: 9,
              fontWeight: 700,
              color: "#f4f7fa",
              background: "rgba(255,255,255,.11)",
              border: "1px solid rgba(255,255,255,.24)",
              borderRadius: 4,
              padding: "2px 8px",
              marginLeft: 4,
            }}
          >
            {activeFlow.label}
          </span>
        )}
      </div>

      {/* Middle row: canvas + sidebar */}
      <div style={{ flex: 1, display: "flex", minHeight: 0, overflow: "hidden" }}>
        {/* SVG canvas — fills all available space, diagram scales to fit */}
        <div
          style={{ flex: 1, minWidth: 0, overflow: "hidden", position: "relative" }}
          onClick={(e) => { if (e.target === e.currentTarget) handleClear(); }}
        >
          <svg
            viewBox={`0 0 ${NATURAL_W} ${svgH}`}
            preserveAspectRatio="xMidYMid meet"
            style={{ display: "block", width: "100%", height: "100%" }}
          >
            <DotGrid width={NATURAL_W} height={svgH} />
            <ColumnHeaders />

            {EDGES.map((edge) => {
              const highlighted = highlightedEdgeIds ? highlightedEdgeIds.has(edge.id) : false;
              const dimmed = highlightedEdgeIds ? !highlighted : false;
              return (
                <EdgePath
                  key={edge.id}
                  edge={edge}
                  nodes={nodes}
                  highlighted={highlighted}
                  dimmed={dimmed}
                />
              );
            })}

            {nodes.map((node) => {
              const highlighted = highlightedNodeIds ? highlightedNodeIds.has(node.id) : false;
              const dimmed = highlightedNodeIds ? !highlighted : false;
              const selected = selectedNodeId === node.id;
              return (
                <ArchNodeBox
                  key={node.id}
                  node={node}
                  highlighted={highlighted}
                  dimmed={dimmed}
                  selected={selected}
                   onClick={() => handleNodeClick(node.id)}
                   onKeyDown={(event) => {
                     if (event.key === "Enter" || event.key === " ") {
                       event.preventDefault();
                       handleNodeClick(node.id);
                     }
                   }}
                />
              );
            })}

            {selectedNode && !activeFlow && (
              <NodePopover node={selectedNode} onClose={() => setSelectedNodeId(null)} />
            )}
          </svg>
        </div>

        <FlowsSidebar
          flows={FLOWS}
          activeFlow={activeFlow}
          onSelect={handleFlowSelect}
          onClear={handleClear}
        />
      </div>

      {/* Legend — fixed strip at bottom */}
      <div
        style={{
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
          gap: 16,
          padding: "5px 16px",
          background: "rgba(16,31,29,0.84)",
          borderTop: "1px solid rgba(225,236,218,0.14)",
          flexWrap: "wrap",
        }}
      >
        {([0, 1, 2, 3, 4] as const).map((col) => (
          <div key={col} style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <div
              style={{
                width: 8, height: 8, borderRadius: 2,
                background: "rgba(255,255,255,.14)",
                border: "1px solid rgba(255,255,255,.42)",
              }}
            />
            <span style={{ fontSize: 8, color: COLUMN_TEXT_COLORS[col], fontWeight: 700, letterSpacing: "0.12em" }}>
              {COLUMN_LABELS[col]}
            </span>
          </div>
        ))}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 5 }}>
          <div style={{ width: 18, height: 1, background: "rgba(148,163,184,0.3)", borderTop: "1px dashed rgba(148,163,184,0.3)" }} />
          <span style={{ fontSize: 8, color: "rgba(148,163,184,0.4)" }}>data flow</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
          <div style={{ width: 18, height: 1.5, background: "rgba(255,255,255,.72)" }} />
          <span style={{ fontSize: 8, color: "rgba(148,163,184,0.4)" }}>selected flow</span>
        </div>
        <span style={{ fontSize: 8, color: "rgba(148,163,184,0.3)" }}>
          Click node for details · Click flow to highlight path
        </span>
      </div>
    </div>
  );
}
