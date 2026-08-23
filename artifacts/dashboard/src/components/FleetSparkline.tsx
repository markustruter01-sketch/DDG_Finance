/**
 * FleetSparkline — life-of-platform equity curve.
 * Shows fleet total equity since inception as a glowing Recharts AreaChart.
 * Data is written nightly by the scheduler; empty until the first snapshot.
 */
import { useMemo } from "react";
import {
  AreaChart, Area, ResponsiveContainer, Tooltip, YAxis, CartesianGrid,
} from "recharts";
import { useQuery } from "@tanstack/react-query";
import axios from "axios";

const BASE = (import.meta.env.VITE_API_BASE_URL as string) || "/trading-api";
const api  = axios.create({ baseURL: BASE });

interface HistoryPoint { date: string; total_equity: number }
interface HistoryResponse { history: HistoryPoint[] }
interface FleetEquityResponse { fleet_total?: { starting?: number | null } }

function useFleetHistory() {
  return useQuery<HistoryResponse>({
    queryKey: ["fleet-equity-history"],
    queryFn:  async () => (await api.get("/fleet/equity-history")).data,
    staleTime: 300_000,
    refetchInterval: 600_000,
    retry: 1,
  });
}

function useFleetStartingCapital() {
  return useQuery<FleetEquityResponse>({
    queryKey: ["fleet-equity"],
    queryFn: async () => (await api.get("/fleet/equity")).data,
    staleTime: 10_000,
    refetchInterval: 15_000,
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
      background: "rgba(15,23,42,0.78)",
      border: "1px solid rgba(34,211,238,0.30)",
      borderRadius: 10,
      padding: "7px 10px",
      fontSize: 10,
      fontFamily: "monospace",
      color: "rgba(255,255,255,0.70)",
      backdropFilter: "blur(18px)",
      WebkitBackdropFilter: "blur(18px)",
      boxShadow: "0 12px 30px rgba(15,23,42,0.20)",
    }}>
      <div style={{ color: "#22d3ee", fontWeight: 700 }}>{fmtK(d.total_equity)}</div>
      <div>{d.date}</div>
    </div>
  );
}

export default function FleetSparkline() {
  const { data, isLoading } = useFleetHistory();
  const { data: fleet } = useFleetStartingCapital();
  const history = data?.history ?? [];
  const startingCapital = fleet?.fleet_total?.starting;

  // Compute all-time % change against canonical fleet starting capital.
  const { pctChange, positive } = useMemo(() => {
    if (startingCapital == null || startingCapital <= 0 || history.length === 0) {
      return { pctChange: null, positive: true };
    }
    const last = history[history.length - 1].total_equity;
    const pct = ((last - startingCapital) / startingCapital) * 100;
    return { pctChange: pct, positive: pct >= 0 };
  }, [history, startingCapital]);

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
      marginTop: 10,
      borderRadius: 18,
      background: "linear-gradient(135deg, rgba(255,255,255,0.16), rgba(148,163,184,0.08))",
      border: "1px solid rgba(255,255,255,0.24)",
      padding: "14px 14px 11px",
      backdropFilter: "blur(18px) saturate(125%)",
      WebkitBackdropFilter: "blur(18px) saturate(125%)",
      boxShadow: "0 16px 34px rgba(15,23,42,0.14), inset 0 1px 0 rgba(255,255,255,0.20)",
      overflow: "hidden",
    }}>
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
        <span style={{ fontSize: 8, letterSpacing: "0.2em", color: "rgba(15,23,42,0.68)", fontFamily: "monospace", textTransform: "uppercase", fontWeight: 700 }}>
          FLEET EQUITY · SINCE INCEPTION
        </span>
        {latest != null && (
          <span style={{ fontSize: 12, fontFamily: "monospace", fontWeight: 800, color: "#0891b2", textShadow: "0 1px 10px rgba(34,211,238,0.24)" }}>
            {fmtK(latest)}
          </span>
        )}
        {pctChange != null && (
          <span style={{
            fontSize: 9, fontFamily: "monospace",
            color: positive ? "#15803d" : "#b91c1c",
          }}>
            {positive ? "+" : ""}{pctChange.toFixed(2)}% all-time
          </span>
        )}
        {history.length === 0 && !isLoading && (
          <span style={{ fontSize: 9, fontFamily: "monospace", color: "rgba(15,23,42,0.60)" }}>
            no history yet · first snapshot pending
          </span>
        )}
      </div>

      {/* Sparkline */}
      {history.length > 0 ? (
        <div style={{ height: 112, margin: "0 -4px" }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={history} margin={{ top: 6, right: 4, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="sparkFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"   stopColor={lineColor} stopOpacity={0.28} />
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
              <CartesianGrid vertical={false} stroke="rgba(15,23,42,0.10)" strokeDasharray="3 5" />
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
        <div style={{
          height: 112,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          borderRadius: 12,
          background: "linear-gradient(135deg, rgba(15,23,42,0.10), rgba(255,255,255,0.05))",
          border: "1px solid rgba(15,23,42,0.10)",
        }}>
          <div style={{
            width: "76%",
            height: 1,
            background: "linear-gradient(to right, transparent, rgba(8,145,178,0.52), transparent)",
            boxShadow: "0 0 16px rgba(34,211,238,0.35)",
          }} />
        </div>
      )}
    </div>
  );
}
