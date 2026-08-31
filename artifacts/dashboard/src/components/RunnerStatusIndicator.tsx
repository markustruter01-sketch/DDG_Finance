import { Activity, CircleAlert, CircleDashed, CircleStop } from "lucide-react";
import type { RunnerStatusResponse } from "@/hooks/useFleetData";

type RunnerStatusIndicatorProps = {
  status?: RunnerStatusResponse;
  isError?: boolean;
  variant?: "mobile" | "observatory" | "summary";
};

function formatAge(seconds: number | null | undefined) {
  if (seconds == null || !Number.isFinite(seconds)) return "age unavailable";
  if (seconds < 60) return `${Math.floor(seconds)}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

function formatTimestamp(timestamp: string | null | undefined) {
  if (!timestamp) return "last seen unavailable";
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime())
    ? "last seen unavailable"
    : `last seen ${date.toISOString().replace("T", " ").replace(".000Z", " UTC")}`;
}

export default function RunnerStatusIndicator({
  status,
  isError = false,
  variant = "mobile",
}: RunnerStatusIndicatorProps) {
  const verdict = isError ? "UNKNOWN" : status?.verdict ?? "UNKNOWN";
  const isSummary = variant === "summary";
  const config = {
    ALIVE: {
      label: "RUNNER ALIVE",
      detail: `${formatAge(status?.age_seconds)} · durable beat`,
      color: "#16a34a",
      background: "rgba(34,197,94,0.10)",
      border: "rgba(34,197,94,0.34)",
      Icon: Activity,
    },
    STALE: {
      label: "RUNNER STOPPED",
      detail: formatTimestamp(status?.last_beat_at),
      color: "#dc2626",
      background: "rgba(220,38,38,0.10)",
      border: "rgba(220,38,38,0.34)",
      Icon: CircleStop,
    },
    ABSENT: {
      label: "RUNNER NEVER SEEN",
      detail: "no durable heartbeat row exists",
      color: "#d97706",
      background: "rgba(217,119,6,0.10)",
      border: "rgba(217,119,6,0.34)",
      Icon: CircleDashed,
    },
    UNKNOWN: {
      label: "RUNNER UNKNOWN",
      detail: "heartbeat endpoint unavailable",
      color: "#64748b",
      background: "rgba(100,116,139,0.12)",
      border: "rgba(100,116,139,0.34)",
      Icon: CircleAlert,
    },
  }[verdict];
  const Icon = config.Icon;

  return (
    <section
      aria-label="Runner status"
      data-testid="runner-status-indicator"
      data-runner-verdict={verdict}
      className={
        variant === "observatory"
          ? "obs-runner-status"
          : isSummary
            ? "summary-runner-status"
            : "runner-status-indicator"
      }
      style={{
        display: "flex",
        alignItems: isSummary ? "flex-start" : "center",
        gap: isSummary ? 8 : 10,
        padding: isSummary
          ? 0
          : variant === "observatory"
            ? "12px 15px"
            : "10px 13px",
        color: config.color,
        background: isSummary ? "transparent" : config.background,
        border: isSummary ? 0 : `1px solid ${config.border}`,
        borderRadius: isSummary ? 0 : variant === "observatory" ? 12 : 10,
        backdropFilter: isSummary ? "none" : "blur(10px)",
        WebkitBackdropFilter: isSummary ? "none" : "blur(10px)",
      }}
    >
      <Icon
        size={variant === "observatory" ? 18 : 16}
        aria-hidden="true"
        className="runner-status-icon"
      />
      <div style={{ minWidth: 0 }}>
        <div
          className="runner-status-label"
          style={{
            fontSize: variant === "observatory" ? 11 : 10,
            fontWeight: 900,
            letterSpacing: "0.14em",
          }}
        >
          {config.label}
        </div>
        <div
          className="runner-status-detail"
          style={{
            marginTop: 3,
            color:
              variant === "observatory"
                ? "var(--muted, #98b5b1)"
                : "rgba(15,23,42,0.72)",
            fontSize: 10,
            letterSpacing: "0.04em",
          }}
        >
          {config.detail}
        </div>
      </div>
      {status?.threshold_seconds != null && verdict !== "UNKNOWN" && (
        <span
          className="runner-status-threshold"
          style={{
            marginLeft: "auto",
            color:
              variant === "observatory"
                ? "var(--dim, #789694)"
                : "rgba(15,23,42,0.56)",
            fontSize: 9,
            whiteSpace: "nowrap",
          }}
        >
          threshold {formatAge(status.threshold_seconds).replace(" ago", "")}
        </span>
      )}
    </section>
  );
}