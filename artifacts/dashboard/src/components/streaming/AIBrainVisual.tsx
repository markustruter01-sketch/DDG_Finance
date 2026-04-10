import { useState, useEffect, useMemo } from "react";

const W = 1000;
const H = 570;
const EDGE_DIST = 88;

type Hem = "L" | "R" | "B";
type Node = [number, number, Hem];

const NODES: Node[] = [
  // Left hemisphere — 51 nodes in brain-oval shape
  [200,155,"L"],[240,138,"L"],[282,132,"L"],[322,135,"L"],[362,150,"L"],[400,168,"L"],
  [162,195,"L"],[202,182,"L"],[242,172,"L"],[282,168,"L"],[326,170,"L"],[366,178,"L"],[406,188,"L"],[442,205,"L"],
  [138,238,"L"],[178,228,"L"],[218,218,"L"],[258,212,"L"],[302,210,"L"],[346,214,"L"],[386,222,"L"],[426,234,"L"],[460,250,"L"],
  [140,280,"L"],[180,272,"L"],[220,266,"L"],[262,262,"L"],[306,260,"L"],[350,264,"L"],[392,272,"L"],[432,284,"L"],[462,300,"L"],
  [150,322,"L"],[190,316,"L"],[232,311,"L"],[274,307,"L"],[318,305,"L"],[360,310,"L"],[400,320,"L"],[435,332,"L"],
  [168,362,"L"],[208,356,"L"],[250,352,"L"],[292,348,"L"],[336,350,"L"],[374,356,"L"],[407,368,"L"],
  [192,402,"L"],[232,398,"L"],[274,396,"L"],[314,396,"L"],[353,401,"L"],
  // Right hemisphere — mirror of left (51 nodes)
  [800,155,"R"],[760,138,"R"],[718,132,"R"],[678,135,"R"],[638,150,"R"],[600,168,"R"],
  [838,195,"R"],[798,182,"R"],[758,172,"R"],[718,168,"R"],[674,170,"R"],[634,178,"R"],[594,188,"R"],[558,205,"R"],
  [862,238,"R"],[822,228,"R"],[782,218,"R"],[742,212,"R"],[698,210,"R"],[654,214,"R"],[614,222,"R"],[574,234,"R"],[540,250,"R"],
  [860,280,"R"],[820,272,"R"],[780,266,"R"],[738,262,"R"],[694,260,"R"],[650,264,"R"],[608,272,"R"],[568,284,"R"],[538,300,"R"],
  [850,322,"R"],[810,316,"R"],[768,311,"R"],[726,307,"R"],[682,305,"R"],[640,310,"R"],[600,320,"R"],[565,332,"R"],
  [832,362,"R"],[792,356,"R"],[750,352,"R"],[708,348,"R"],[664,350,"R"],[626,356,"R"],[593,368,"R"],
  [808,402,"R"],[768,398,"R"],[726,396,"R"],[686,396,"R"],[647,401,"R"],
  // Bridge nodes — corpus callosum
  [475,243,"B"],[494,276,"B"],[506,276,"B"],[525,243,"B"],
  [486,314,"B"],[514,314,"B"],[500,205,"B"],
];

const STATUS_MESSAGES = [
  "AUDITING FLEET POSITIONS…",
  "CROSS-FLEET CORRELATION SCAN…",
  "REGIME DETECTION: SIDEWAYS MARKET…",
  "VPIN MICROSTRUCTURE CHECK PASSED…",
  "NEURAL PATTERN SYNC COMPLETE…",
  "PORTFOLIO RISK ASSESSMENT: NOMINAL…",
  "GEMINI ANALYZING MACRO INDICATORS…",
  "CLAUDE REVIEWING TRADE JOURNAL…",
  "SIGNAL VALIDATION IN PROGRESS…",
  "DRAWDOWN PROTECTION: ACTIVE…",
  "LEARNING MODEL — EPOCH 247…",
  "6 BOTS ACTIVE — ALL SYSTEMS NOMINAL…",
  "ORACLE: BULL REGIME EQUITY SCAN…",
  "CRYPTO REGIME: BEAR — SHORTS ENABLED…",
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

          <radialGradient id="bg-leftNeb" cx="30%" cy="46%" r="28%">
            <stop offset="0%" stopColor="#0e7490" stopOpacity="0.18" />
            <stop offset="100%" stopColor="#020617" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="bg-rightNeb" cx="70%" cy="46%" r="28%">
            <stop offset="0%" stopColor="#3b0764" stopOpacity="0.22" />
            <stop offset="100%" stopColor="#020617" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="bg-centerNeb" cx="50%" cy="46%" r="11%">
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
        <path d="M 462 274 Q 500 254 538 274" stroke="#fbbf24" strokeWidth={1.5} fill="none" opacity={0.4} strokeDasharray="3,4">
          <animate attributeName="opacity" values="0.2;0.55;0.2" dur="2.6s" repeatCount="indefinite" />
        </path>

        {/* GEMINI label — left hemisphere */}
        <text x={240} y={90} textAnchor="middle" fontFamily="'Courier New',monospace"
          fontSize={21} fontWeight="bold" fill="#22d3ee" letterSpacing="4" opacity={0.92}>
          ✦ GEMINI
        </text>
        <text x={240} y={107} textAnchor="middle" fontFamily="monospace"
          fontSize={9} fill="#22d3ee" opacity={0.48} letterSpacing="2">
          MARKET ANALYSIS ENGINE
        </text>
        <line x1={240} y1={114} x2={240} y2={147} stroke="#22d3ee" strokeWidth={0.8} strokeDasharray="2,3" opacity={0.28}>
          <animate attributeName="opacity" values="0.14;0.42;0.14" dur="2s" repeatCount="indefinite" />
        </line>

        {/* CLAUDE label — right hemisphere */}
        <text x={760} y={90} textAnchor="middle" fontFamily="'Courier New',monospace"
          fontSize={21} fontWeight="bold" fill="#a78bfa" letterSpacing="4" opacity={0.92}>
          ✦ CLAUDE
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
          GEMINI-3
        </text>
        <text x={912} y={491} textAnchor="end" fontFamily="'Courier New',monospace" fontSize={12} fill="#a78bfa" opacity={0.7} letterSpacing="2">
          CLAUDE-4
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
