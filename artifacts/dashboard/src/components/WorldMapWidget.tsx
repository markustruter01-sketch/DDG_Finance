/**
 * WorldMapWidget — stylized SVG world map with pulsing regions.
 *
 * Each region glows only when that bot holds real (non-SGOV) strategy positions.
 * Bot → region mapping:
 *   spy_qqq_trend → North America
 *   oracle        → Asia-Pacific (Korea, Taiwan, Japan, India, SE-Asia)
 *   jerome_macro  → EM/Commodities (S. America + Africa + Middle East)
 *
 * Data source: GET /fleet/region-status  (server, no client math)
 * Pulse is CSS-only (opacity cycle), no heavy animation.
 */
import { useQuery } from "@tanstack/react-query";
import axios from "axios";

const BASE = (import.meta.env.VITE_API_BASE_URL as string) || "/trading-api";
const api  = axios.create({ baseURL: BASE });

interface RegionStatus {
  oracle:        boolean;
  spy_qqq_trend: boolean;
  jerome_macro:  boolean;
}

function useRegionStatus() {
  return useQuery<RegionStatus>({
    queryKey: ["fleet-region-status"],
    queryFn:  async () => (await api.get("/fleet/region-status")).data,
    staleTime: 30_000,
    refetchInterval: 60_000,
    retry: 1,
  });
}

const PULSE_CSS = `
@keyframes region-pulse {
  0%   { opacity: 0.85; filter: drop-shadow(0 0 3px currentColor); }
  50%  { opacity: 0.40; filter: drop-shadow(0 0 1px currentColor); }
  100% { opacity: 0.85; filter: drop-shadow(0 0 3px currentColor); }
}
@keyframes region-pulse-em {
  0%   { opacity: 0.75; filter: drop-shadow(0 0 2px currentColor); }
  50%  { opacity: 0.35; filter: drop-shadow(0 0 1px currentColor); }
  100% { opacity: 0.75; filter: drop-shadow(0 0 2px currentColor); }
}
`;

// Continent SVG paths in a 280×132 viewBox (simplified Mercator-like outlines)
// Each path key maps to which bot activates it.
const PATHS = {
  // ── North America ──────────────────────────────────────────────────────────
  northAmerica: {
    d: "M 14,18 L 28,12 L 52,10 L 68,14 L 78,24 L 82,38 L 76,58 L 65,72 L 50,78 L 36,72 L 24,58 L 18,40 L 14,28 Z",
    bot: "spy_qqq_trend" as const,
    color: "#fbbf24",
  },
  // ── Central America / Caribbean ────────────────────────────────────────────
  centralAmerica: {
    d: "M 54,78 L 65,74 L 70,82 L 62,86 L 52,84 Z",
    bot: "spy_qqq_trend" as const,
    color: "#fbbf24",
  },

  // ── South America  (jerome EM) ─────────────────────────────────────────────
  southAmerica: {
    d: "M 50,88 L 72,84 L 80,96 L 78,114 L 66,126 L 52,120 L 44,104 L 46,92 Z",
    bot: "jerome_macro" as const,
    color: "#f87171",
  },

  // ── Europe ─────────────────────────────────────────────────────────────────
  europe: {
    d: "M 110,24 L 130,20 L 138,30 L 134,44 L 116,46 L 108,36 Z",
    bot: "jerome_macro" as const,
    color: "#f87171",
  },

  // ── Africa  (jerome EM — commodity-rich) ───────────────────────────────────
  africa: {
    d: "M 112,48 L 146,44 L 152,60 L 148,90 L 134,108 L 114,104 L 106,82 L 108,58 Z",
    bot: "jerome_macro" as const,
    color: "#f87171",
  },

  // ── Middle East  (jerome EM — energy ETFs) ─────────────────────────────────
  middleEast: {
    d: "M 146,46 L 168,42 L 174,56 L 160,64 L 146,60 Z",
    bot: "jerome_macro" as const,
    color: "#f87171",
  },

  // ── Central / South Asia ───────────────────────────────────────────────────
  southAsia: {
    d: "M 170,50 L 196,46 L 200,64 L 185,72 L 168,66 Z",
    bot: "oracle" as const,
    color: "#a78bfa",
  },

  // ── East Asia / Asia-Pacific (oracle) ──────────────────────────────────────
  eastAsia: {
    d: "M 196,20 L 232,16 L 244,30 L 238,50 L 218,60 L 198,64 L 182,56 L 176,40 L 192,26 Z",
    bot: "oracle" as const,
    color: "#a78bfa",
  },

  // ── SE Asia ────────────────────────────────────────────────────────────────
  seAsia: {
    d: "M 200,66 L 224,62 L 230,76 L 214,84 L 198,78 Z",
    bot: "oracle" as const,
    color: "#a78bfa",
  },

  // ── Japan / Korean peninsula (small island/peninsula) ──────────────────────
  japan: {
    d: "M 236,26 L 246,22 L 250,34 L 243,40 L 234,36 Z",
    bot: "oracle" as const,
    color: "#a78bfa",
  },

  // ── Australia ──────────────────────────────────────────────────────────────
  australia: {
    d: "M 208,90 L 248,86 L 254,102 L 246,114 L 214,116 L 204,104 Z",
    bot: "oracle" as const,
    color: "#a78bfa",
  },
} as const;

type BotKey = "spy_qqq_trend" | "oracle" | "jerome_macro";

const BOT_LABELS: Record<BotKey, string> = {
  spy_qqq_trend: "US CORE",
  oracle:        "ASIA-PAC",
  jerome_macro:  "EM/COMMOD",
};

const BOT_COLORS: Record<BotKey, string> = {
  spy_qqq_trend: "#fbbf24",
  oracle:        "#a78bfa",
  jerome_macro:  "#f87171",
};

export default function WorldMapWidget() {
  const { data } = useRegionStatus();
  const status: RegionStatus = data ?? { oracle: false, spy_qqq_trend: false, jerome_macro: false };

  return (
    <div style={{
      marginTop: 6,
      borderRadius: 12,
      background: "rgba(6,10,22,0.6)",
      border: "1px solid rgba(34,211,238,0.08)",
      padding: "10px 14px 8px",
      overflow: "hidden",
    }}>
      <style>{PULSE_CSS}</style>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
        <span style={{ fontSize: 8, letterSpacing: "0.2em", color: "#334155", fontFamily: "monospace", textTransform: "uppercase" }}>
          CAPITAL DEPLOYMENT MAP
        </span>
        <div style={{ display: "flex", gap: 8 }}>
          {(["spy_qqq_trend", "oracle", "jerome_macro"] as BotKey[]).map(bot => (
            <div key={bot} style={{ display: "flex", alignItems: "center", gap: 3 }}>
              <div style={{
                width: 5, height: 5, borderRadius: "50%",
                background: status[bot] ? BOT_COLORS[bot] : "#1e293b",
                boxShadow: status[bot] ? `0 0 6px ${BOT_COLORS[bot]}` : "none",
                transition: "all 0.5s",
              }} />
              <span style={{
                fontSize: 7, fontFamily: "monospace", letterSpacing: "0.12em",
                color: status[bot] ? BOT_COLORS[bot] : "#334155",
                transition: "color 0.5s",
              }}>
                {BOT_LABELS[bot]}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Map */}
      <svg
        viewBox="0 0 270 132"
        style={{ width: "100%", height: "auto", display: "block" }}
        role="img"
        aria-label="World map showing deployed capital regions"
      >
        {/* Ocean background */}
        <rect width="270" height="132" fill="rgba(2,6,15,0.6)" rx="6" />

        {/* Grid lines (subtle latitude/longitude) */}
        {[33, 66, 99].map(x => (
          <line key={`vl${x}`} x1={x} y1={0} x2={x} y2={132} stroke="rgba(255,255,255,0.03)" />
        ))}
        {[44, 88].map(y => (
          <line key={`hl${y}`} x1={0} y1={y} x2={270} y2={y} stroke="rgba(255,255,255,0.03)" />
        ))}

        {/* Continent paths */}
        {Object.entries(PATHS).map(([key, { d, bot, color }]) => {
          const active = status[bot];
          return (
            <path
              key={key}
              d={d}
              fill={active ? color : "#1e293b"}
              stroke={active ? color : "#0f172a"}
              strokeWidth={active ? 0.5 : 0.3}
              style={{
                opacity:   active ? 0.85 : 0.35,
                animation: active ? `region-pulse 2.8s ease-in-out infinite` : "none",
                color,
                transition: "fill 0.8s, stroke 0.8s, opacity 0.8s",
              }}
            />
          );
        })}

        {/* "IN MARKET" labels for active regions */}
        {status.spy_qqq_trend && (
          <text x="48" y="47" textAnchor="middle" fontSize="5" fill="#fbbf24" fontFamily="monospace" opacity="0.8">
            IN MARKET
          </text>
        )}
        {status.oracle && (
          <text x="216" y="42" textAnchor="middle" fontSize="5" fill="#a78bfa" fontFamily="monospace" opacity="0.8">
            IN MARKET
          </text>
        )}
        {status.jerome_macro && (
          <text x="130" y="76" textAnchor="middle" fontSize="5" fill="#f87171" fontFamily="monospace" opacity="0.8">
            IN MARKET
          </text>
        )}
      </svg>
    </div>
  );
}
