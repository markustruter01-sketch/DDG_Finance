import { OrbVisualiser } from "@/components/streaming/OrbVisualiser";
import { useVault } from "@/hooks/use-trading";

export default function StreamingOrbScreen() {
  const { data: vault } = useVault();
  const totalVaulted = vault?.total_vaulted_usd ?? null;

  return (
    <div
      style={{
        height: "100%",
        width: "100%",
        background: "#020617",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "flex-end",
          gap: 8,
          padding: "6px 16px",
          borderBottom: "1px solid rgba(255,255,255,0.04)",
          background: "rgba(2,6,23,0.9)",
        }}
      >
        <span
          style={{
            fontSize: 9,
            fontFamily: "monospace",
            fontWeight: 700,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "rgba(251,191,36,0.5)",
          }}
        >
          VAULT
        </span>
        <span
          style={{
            fontSize: 13,
            fontFamily: "monospace",
            fontWeight: 900,
            color: "#fbbf24",
            textShadow: "0 0 12px rgba(251,191,36,0.4)",
          }}
        >
          {totalVaulted != null ? `$${Math.round(totalVaulted).toLocaleString()}` : "—"}
        </span>
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>
        <OrbVisualiser />
      </div>
    </div>
  );
}
