/**
 * FleetSparkline — life-of-platform equity curve.
 * Shows fleet total equity since inception as a glowing Recharts AreaChart.
 * Data is written nightly by the scheduler; empty until the first snapshot.
 */
import { useMemo } from "react";
import {
  AreaChart, Area, ResponsiveContainer, Tooltip, YAxis,
} from "recharts";
import { useQuery } from "@tanstack/react-query";
import axios from "axios";

const BASE = (import.meta.env.VITE_API_BASE_URL as string) || "/trading-api";
const api  = axios.create({ baseURL: BASE });

interface HistoryPoint { date: string; total_equity: number }
interface HistoryResponse { history: HistoryPoint[] }

function useFleetHistory() {
  return useQuery<HistoryResponse>({
    queryKey: ["fleet-equity-history"],
    queryFn:  async () => (await api.get("/fleet/equity-history")).data,
    staleTime: 300_000,
    refetchInterval: 600_000,
    retry: 1,
  });
}

function fmtK(v: number) {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1_000)     return `$${(v / 1_000).toFixed(1)}k`;
  return `$${v.toFixed(0)}`;
}

// Minimal custom tooltip
function SparkTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload as HistoryPoint;
  return (
    <div style={{
      background: "rgba(6,10,22,0.95)", border: "1px solid rgba(34,211,238,0.18)",
      borderRadius: 6, padding: "4px 8px", fontSize: 10, fontFamily: "monospace",
      color: "#94a3b8",
    }}>
      <div style={{ color: "#22d3ee", fontWeight: 700 }}>{fmtK(d.total_equity)}</div>
      <div>{d.date}</div>
    </div>
  );
}

export default function FleetSparkline() {
  const { data, isLoading } = useFleetHistory();
  const history = data?.history ?? [];

  // Compute all-time % change relative to first data point
  const { pctChange, positive } = useMemo(() => {
    if (history.length < 2) return { pctChange: null, positive: true };
    const first = history[0].total_equity;
    const last  = history[history.length - 1].total_equity;
    const pct   = ((last - first) / first) * 100;
    return { pctChange: pct, positive: pct >= 0 };
  }, [history]);

  const lineColor   = positive ? "#22d3ee" : "#f87171";
  const fillStart   = positive ? "rgba(34,211,238,0.15)" : "rgba(248,113,113,0.10)";
  const fillEnd     = "rgba(0,0,0,0)";

  // Min/max for y-axis domain with 5% padding
  const values = history.map(h => h.total_equity);
  const minVal = values.length ? Math.min(...values) : 0;
  const maxVal = values.length ? Math.max(...values) : 1;
  const pad    = (maxVal - minVal) * 0.08 || 1000;

  const latest = history.length ? history[history.length - 1].total_equity : null;

  return (
    <div style={{
      marginTop: 8,
      borderRadius: 12,
      background: "rgba(6,10,22,0.6)",
      border: "1px solid rgba(34,211,238,0.08)",
      padding: "12px 14px 8px",
    }}>
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: 8, letterSpacing: "0.2em", color: "#334155", fontFamily: "monospace", textTransform: "uppercase" }}>
          FLEET EQUITY · SINCE INCEPTION
        </span>
        {latest != null && (
          <span style={{ fontSize: 11, fontFamily: "monospace", fontWeight: 700, color: "#22d3ee" }}>
            {fmtK(latest)}
          </span>
        )}
        {pctChange != null && (
          <span style={{
            fontSize: 9, fontFamily: "monospace",
            color: positive ? "#4ade80" : "#f87171",
          }}>
            {positive ? "+" : ""}{pctChange.toFixed(2)}% all-time
          </span>
        )}
        {history.length === 0 && !isLoading && (
          <span style={{ fontSize: 9, fontFamily: "monospace", color: "#334155" }}>
            no history yet — first snapshot tonight
          </span>
        )}
      </div>

      {/* Sparkline */}
      {history.length > 0 ? (
        <div style={{ height: 52, marginLeft: -4 }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={history} margin={{ top: 2, right: 4, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="sparkFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"   stopColor={lineColor} stopOpacity={0.18} />
                  <stop offset="100%" stopColor={lineColor} stopOpacity={0} />
                </linearGradient>
                <filter id="sparkGlow">
                  <feGaussianBlur stdDeviation="1.5" result="blur" />
                  <feMerge>
                    <feMergeNode in="blur" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
              </defs>
              <YAxis domain={[minVal - pad, maxVal + pad]} hide />
              <Tooltip content={<SparkTooltip />} />
              <Area
                type="monotone"
                dataKey="total_equity"
                stroke={lineColor}
                strokeWidth={1.5}
                fill="url(#sparkFill)"
                dot={false}
                activeDot={{ r: 3, fill: lineColor, strokeWidth: 0 }}
                filter="url(#sparkGlow)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div style={{ height: 52, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{
            width: "80%", height: 1,
            background: "linear-gradient(to right, transparent, rgba(34,211,238,0.12), transparent)",
          }} />
        </div>
      )}
    </div>
  );
}
