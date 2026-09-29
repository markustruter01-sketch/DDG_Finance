import { useState, useEffect, useMemo } from "react";

const W = 1000;
const H = 570;
const EDGE_DIST = 88;

type Hem = "L" | "R" | "B";
type Node = [number, number, Hem];

const NODES: Node[] = [
  // ── Left hemisphere — brain silhouette ──────────────────────
  // top dome — narrow
  [248,128,"L"],[290,122,"L"],[332,122,"L"],[373,130,"L"],[410,145,"L"],
  // upper — widening outward
  [190,162,"L"],[232,155,"L"],[275,150,"L"],[318,150,"L"],[360,156,"L"],[398,168,"L"],[432,184,"L"],
  // upper-mid
  [152,196,"L"],[192,188,"L"],[234,182,"L"],[277,179,"L"],[320,180,"L"],[361,187,"L"],[398,200,"L"],[432,217,"L"],
  // mid — widening to broadest point
  [118,232,"L"],[159,224,"L"],[202,218,"L"],[245,215,"L"],[288,215,"L"],[330,219,"L"],[369,230,"L"],[404,246,"L"],[437,265,"L"],
  // widest — parietal region
  [100,270,"L"],[141,262,"L"],[184,256,"L"],[227,253,"L"],[270,252,"L"],[313,256,"L"],[352,267,"L"],[386,283,"L"],[418,303,"L"],
  // lower-mid — outer edge pulls slightly inward (Sylvian region)
  [108,312,"L"],[148,305,"L"],[190,301,"L"],[233,299,"L"],[276,300,"L"],[317,305,"L"],[356,316,"L"],[390,334,"L"],
  // temporal lobe — narrowing
  [136,350,"L"],[176,344,"L"],[218,341,"L"],[260,340,"L"],[300,343,"L"],[338,354,"L"],[370,368,"L"],
  // temporal mid
  [168,382,"L"],[208,379,"L"],[248,378,"L"],[287,381,"L"],[322,390,"L"],
  // temporal lower
  [198,412,"L"],[236,411,"L"],[273,413,"L"],[307,421,"L"],
  // temporal tip
  [228,440,"L"],[260,443,"L"],[290,445,"L"],

  // ── Right hemisphere — mirror at x=500 ──────────────────────
  // top dome
  [752,128,"R"],[710,122,"R"],[668,122,"R"],[627,130,"R"],[590,145,"R"],
  // upper
  [810,162,"R"],[768,155,"R"],[725,150,"R"],[682,150,"R"],[640,156,"R"],[602,168,"R"],[568,184,"R"],
  // upper-mid
  [848,196,"R"],[808,188,"R"],[766,182,"R"],[723,179,"R"],[680,180,"R"],[639,187,"R"],[602,200,"R"],[568,217,"R"],
  // mid
  [882,232,"R"],[841,224,"R"],[798,218,"R"],[755,215,"R"],[712,215,"R"],[670,219,"R"],[631,230,"R"],[596,246,"R"],[563,265,"R"],
  // widest
  [900,270,"R"],[859,262,"R"],[816,256,"R"],[773,253,"R"],[730,252,"R"],[687,256,"R"],[648,267,"R"],[614,283,"R"],[582,303,"R"],
  // lower-mid
  [892,312,"R"],[852,305,"R"],[810,301,"R"],[767,299,"R"],[724,300,"R"],[683,305,"R"],[644,316,"R"],[610,334,"R"],
  // temporal upper
  [864,350,"R"],[824,344,"R"],[782,341,"R"],[740,340,"R"],[700,343,"R"],[662,354,"R"],[630,368,"R"],
  // temporal mid
  [832,382,"R"],[792,379,"R"],[752,378,"R"],[713,381,"R"],[678,390,"R"],
  // temporal lower
  [802,412,"R"],[764,411,"R"],[727,413,"R"],[693,421,"R"],
  // temporal tip
  [772,440,"R"],[740,443,"R"],[710,445,"R"],

  // ── Bridge — corpus callosum ─────────────────────────────────
  [475,243,"B"],[494,276,"B"],[506,276,"B"],[525,243,"B"],
  [486,314,"B"],[514,314,"B"],[500,205,"B"],
];

const STATUS_MESSAGES = [
  "FLEET OVERVIEW",
  "REGISTRY SNAPSHOT",
  "MARKET CONTEXT",
  "AUDIT RESULTS",
  "PERFORMANCE METRICS",
  "RISK METRICS",
  "SIGNAL ANALYSIS",
  "TRADE REVIEW",
  "POSITION STATUS",
  "DRAWDOWN METRICS",
  "LEARNING NOTES",
  "DATA AVAILABILITY",
  "CANONICAL BOT IDENTITY",
  "ETF FLEET MONITORING",
];

function nodeDist(a: Node, b: Node) {
  const dx = a[0] - b[0], dy = a[1] - b[1];
  return Math.sqrt(dx * dx + dy * dy);
}

function nodeColor(n: Node, idx: number): string {
  if (n[2] === "B") return "#fbbf24";
  if (n[2] === "L") return idx % 5 === 0 ? "#6d28d9" : "#22d3ee";
  return idx % 5 === 0 ? "#6d28d9" : "#a78bfa";
}

function edgeStroke(a: Node, b: Node): string {
  if (a[2] === "B" || b[2] === "B") return "rgba(251,191,36,0.18)";
  if (a[2] === "L" && b[2] === "L") return "rgba(34,211,238,0.11)";
  if (a[2] === "R" && b[2] === "R") return "rgba(167,139,250,0.11)";
  return "rgba(139,92,246,0.14)";
}

export function AIBrainVisual() {
  const [statusIdx, setStatusIdx] = useState(0);
  const [statusVisible, setStatusVisible] = useState(true);

  useEffect(() => {
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    const intervalId = setInterval(() => {
      setStatusVisible(false);
      timeoutId = setTimeout(() => {
        setStatusIdx(i => (i + 1) % STATUS_MESSAGES.length);
        setStatusVisible(true);
        timeoutId = null;
      }, 420);
    }, 3000);
    return () => {
      clearInterval(intervalId);
      if (timeoutId !== null) clearTimeout(timeoutId);
    };
  }, []);

  const edges = useMemo(() => {
    const result: [number, number][] = [];
    for (let i = 0; i < NODES.length; i++) {
      for (let j = i + 1; j < NODES.length; j++) {
        if (nodeDist(NODES[i], NODES[j]) < EDGE_DIST) result.push([i, j]);
      }
    }
    return result;
  }, []);

  const pulseEdges = useMemo(() => {
    if (!edges.length) return [];
    const cross = edges.filter(([i, j]) => {
      const hi = NODES[i][2], hj = NODES[j][2];
      return hi !== hj || hi === "B" || hj === "B";
    });
    const left = edges.filter(([i, j]) => NODES[i][2] === "L" && NODES[j][2] === "L");
    const right = edges.filter(([i, j]) => NODES[i][2] === "R" && NODES[j][2] === "R");
    const pick = <T,>(arr: T[], n: number) => {
      const step = Math.max(1, Math.floor(arr.length / n));
      return Array.from({ length: Math.min(n, arr.length) }, (_, k) => arr[(k * step) % arr.length]);
    };
    return [...pick(left, 7), ...pick(right, 7), ...pick(cross, 8)];
  }, [edges]);

  return (
    <div style={{ width: "100%", height: "100%", background: "#020617", overflow: "hidden", position: "relative" }}>
      <svg
        width="100%"
        height="100%"
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="xMidYMid meet"
        style={{ display: "block" }}
      >
        <defs>
          <filter id="bg-nodeGlow" x="-100%" y="-100%" width="300%" height="300%">
            <feGaussianBlur stdDeviation="2.5" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <filter id="bg-strongGlow" x="-150%" y="-150%" width="400%" height="400%">
            <feGaussianBlur stdDeviation="5" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <filter id="bg-scan" x="-5%" y="-300%" width="110%" height="700%">
            <feGaussianBlur stdDeviation="1" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>

          <radialGradient id="bg-leftNeb" cx="28%" cy="50%" r="30%">
            <stop offset="0%" stopColor="#0e7490" stopOpacity="0.18" />
            <stop offset="100%" stopColor="#020617" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="bg-rightNeb" cx="72%" cy="50%" r="30%">
            <stop offset="0%" stopColor="#3b0764" stopOpacity="0.22" />
            <stop offset="100%" stopColor="#020617" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="bg-centerNeb" cx="50%" cy="50%" r="11%">
            <stop offset="0%" stopColor="#5b21b6" stopOpacity="0.22" />
            <stop offset="100%" stopColor="#020617" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="bg-scanLine" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#22d3ee" stopOpacity="0" />
            <stop offset="50%" stopColor="#22d3ee" stopOpacity="1" />
            <stop offset="100%" stopColor="#22d3ee" stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Atmosphere */}
        <rect width={W} height={H} fill="url(#bg-leftNeb)" />
        <rect width={W} height={H} fill="url(#bg-rightNeb)" />
        <rect width={W} height={H} fill="url(#bg-centerNeb)" />

        {/* Scan line sweep */}
        <rect x={0} y={-14} width={W} height={14} fill="url(#bg-scanLine)" opacity={0.055} filter="url(#bg-scan)">
          <animate attributeName="y" values="-14;584" dur="5.5s" repeatCount="indefinite" calcMode="linear" />
        </rect>

        {/* Neural connections */}
        {edges.map(([i, j], ei) => {
          const a = NODES[i], b = NODES[j];
          const base = (a[2] === "B" || b[2] === "B") ? 0.38 : 0.13;
          const dur = 1.9 + (ei * 31 % 23) * 0.14;
          const beg = ((ei * 17) % 38) * 0.09;
          return (
            <line key={`e${ei}`} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]}
              stroke={edgeStroke(a, b)} strokeWidth={0.75} opacity={base}>
              <animate attributeName="opacity"
                values={`${base};${Math.min(base * 2.8, 0.65)};${base}`}
                dur={`${dur}s`} begin={`${beg}s`} repeatCount="indefinite" />
            </line>
          );
        })}

        {/* Signal pulses traveling along edges */}
        {pulseEdges.map(([i, j], pi) => {
          const a = NODES[i], b = NODES[j];
          const dur = 2.1 + (pi * 23 % 32) * 0.11;
          const delay = ((pi * 41) % 46) * 0.1;
          const hi = NODES[i][2], hj = NODES[j][2];
          const color = (hi === "B" || hj === "B") ? "#fbbf24"
            : (hi === "L" && hj === "L") ? "#22d3ee"
            : (hi === "R" && hj === "R") ? "#a78bfa"
            : "#f8fafc";
          return (
            <circle key={`p${pi}`} r={pi % 4 === 0 ? 3.2 : 2.2} fill={color} opacity={0.88} filter="url(#bg-nodeGlow)">
              <animateMotion
                path={`M ${a[0]} ${a[1]} L ${b[0]} ${b[1]}`}
                dur={`${dur}s`} repeatCount="indefinite" begin={`${delay}s`}
              />
            </circle>
          );
        })}

        {/* Node halos */}
        {NODES.map((n, ni) => {
          const color = nodeColor(n, ni);
          const r = n[2] === "B" ? 5.5 : ni % 7 === 0 ? 4.5 : 3.2;
          const dur = 1.6 + (ni * 37 % 22) * 0.12;
          const beg = ((ni * 19) % 30) * 0.08;
          return (
            <circle key={`h${ni}`} cx={n[0]} cy={n[1]} r={r} fill="none" stroke={color} strokeWidth={0.7}>
              <animate attributeName="r" values={`${r+1};${r+8};${r+1}`} dur={`${dur}s`} begin={`${beg}s`} repeatCount="indefinite" />
              <animate attributeName="opacity" values="0.05;0.22;0.05" dur={`${dur}s`} begin={`${beg}s`} repeatCount="indefinite" />
            </circle>
          );
        })}

        {/* Node cores */}
        {NODES.map((n, ni) => {
          const color = nodeColor(n, ni);
          const r = n[2] === "B" ? 5.5 : ni % 7 === 0 ? 4.5 : 3.2;
          const hot = n[2] === "B" || ni % 7 === 0 || ni % 11 === 0;
          return (
            <circle key={`n${ni}`} cx={n[0]} cy={n[1]} r={r} fill={color}
              filter={hot ? "url(#bg-strongGlow)" : "url(#bg-nodeGlow)"} />
          );
        })}

        {/* Central orb — the core AI mind */}
        <circle cx={500} cy={273} r={14} fill="#7c3aed" filter="url(#bg-strongGlow)" opacity={0.92}>
          <animate attributeName="r" values="11;18;11" dur="3.2s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.72;1;0.72" dur="3.2s" repeatCount="indefinite" />
        </circle>
        <circle cx={500} cy={273} r={28} fill="none" stroke="#8b5cf6" strokeWidth={1.2} opacity={0.22}>
          <animate attributeName="r" values="22;38;22" dur="3.2s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.08;0.32;0.08" dur="3.2s" repeatCount="indefinite" />
        </circle>
        <circle cx={500} cy={273} r={50} fill="none" stroke="#6d28d9" strokeWidth={0.6} opacity={0.1}>
          <animate attributeName="r" values="42;62;42" dur="4.8s" begin="0.6s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.04;0.18;0.04" dur="4.8s" begin="0.6s" repeatCount="indefinite" />
        </circle>

        {/* Orbiting electrons around central orb */}
        {[0, 1, 2].map(i => (
          <g key={`orbit${i}`} transform="translate(500, 273)">
            <g>
              <animateTransform
                attributeName="transform"
                type="rotate"
                values={`${i * 120};${i * 120 + 360}`}
                dur="5s"
                repeatCount="indefinite"
              />
              <circle cx={40} cy={0} r={2.5} fill={i === 0 ? "#22d3ee" : i === 1 ? "#a78bfa" : "#fbbf24"}
                filter="url(#bg-nodeGlow)" opacity={0.72} />
            </g>
          </g>
        ))}

        {/* Corpus callosum bridge arc */}
        <path d="M 437 272 Q 500 250 563 272" stroke="#fbbf24" strokeWidth={1.5} fill="none" opacity={0.4} strokeDasharray="3,4">
          <animate attributeName="opacity" values="0.2;0.55;0.2" dur="2.6s" repeatCount="indefinite" />
        </path>

        {/* Analysis label — left hemisphere */}
        <text x={240} y={90} textAnchor="middle" fontFamily="'Courier New',monospace"
          fontSize={21} fontWeight="bold" fill="#22d3ee" letterSpacing="4" opacity={0.92}>
          SIGNAL ANALYSIS
        </text>
        <text x={240} y={107} textAnchor="middle" fontFamily="monospace"
          fontSize={9} fill="#22d3ee" opacity={0.48} letterSpacing="2">
          MARKET ANALYSIS ENGINE
        </text>
        <line x1={240} y1={114} x2={240} y2={147} stroke="#22d3ee" strokeWidth={0.8} strokeDasharray="2,3" opacity={0.28}>
          <animate attributeName="opacity" values="0.14;0.42;0.14" dur="2s" repeatCount="indefinite" />
        </line>

        {/* Review label — right hemisphere */}
        <text x={760} y={90} textAnchor="middle" fontFamily="'Courier New',monospace"
          fontSize={21} fontWeight="bold" fill="#a78bfa" letterSpacing="4" opacity={0.92}>
          TRADE REVIEW
        </text>
        <text x={760} y={107} textAnchor="middle" fontFamily="monospace"
          fontSize={9} fill="#a78bfa" opacity={0.48} letterSpacing="2">
          TRADE JOURNAL AUDITOR
        </text>
        <line x1={760} y1={114} x2={760} y2={147} stroke="#a78bfa" strokeWidth={0.8} strokeDasharray="2,3" opacity={0.28}>
          <animate attributeName="opacity" values="0.14;0.42;0.14" dur="2.4s" repeatCount="indefinite" />
        </line>

        {/* Status strip */}
        <line x1={60} y1={462} x2={940} y2={462} stroke="rgba(99,102,241,0.25)" strokeWidth={1} />
        <rect x={60} y={463} width={880} height={44} fill="rgba(2,6,23,0.55)" />

        <text x={88} y={491} fontFamily="'Courier New',monospace" fontSize={12} fill="#22d3ee" opacity={0.7} letterSpacing="2">
          ANALYSIS
        </text>
        <text x={912} y={491} textAnchor="end" fontFamily="'Courier New',monospace" fontSize={12} fill="#a78bfa" opacity={0.7} letterSpacing="2">
          REVIEW
        </text>
        <text
          x={500} y={491}
          textAnchor="middle"
          fontFamily="'Courier New',monospace"
          fontSize={14}
          fill="#cbd5e1"
          letterSpacing="4"
          style={{ opacity: statusVisible ? 1 : 0, transition: "opacity 0.42s ease" }}
        >
          {STATUS_MESSAGES[statusIdx]}
        </text>

        {/* Corner decorators */}
        <text x={68} y={504} fontFamily="monospace" fontSize={9} fill="rgba(34,211,238,0.35)" letterSpacing="1">
          [{new Date().toISOString().slice(0,10)}]
        </text>
        <text x={932} y={504} textAnchor="end" fontFamily="monospace" fontSize={9} fill="rgba(167,139,250,0.35)" letterSpacing="1">
          DIGITAL DYNAMICS v2.0
        </text>
      </svg>
    </div>
  );
}
