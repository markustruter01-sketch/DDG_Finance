import type { CSSProperties } from "react";

export function DDGBadge({ style, size = "md" }: { style?: CSSProperties; size?: "sm" | "md" }) {
  const isSm = size === "sm";
  return (
    <div style={{
      display: "inline-flex", alignItems: "center", gap: isSm ? 4 : 6,
      background: "rgba(2,6,23,0.85)", border: "1px solid rgba(251,146,60,0.2)",
      borderLeft: "3px solid #f97316", borderRadius: 7,
      padding: isSm ? "3px 8px 3px 6px" : "5px 12px 5px 8px",
      backdropFilter: "blur(12px)", boxShadow: "0 0 20px rgba(251,146,60,0.08)", ...style,
    }}>
      <span style={{ color: "#f97316", fontSize: isSm ? 11 : 13, lineHeight: 1 }}>⚡</span>
      <span style={{ fontFamily: "monospace", fontSize: isSm ? 8 : 10, letterSpacing: "0.08em", color: "rgba(148,163,184,0.65)", whiteSpace: "nowrap" }}>
        POWERED BY <strong style={{ color: "rgba(241,245,249,0.9)" }}>DIGITAL DYNAMICS</strong> <strong style={{ color: "#22d3ee" }}>GROUP</strong>
      </span>
      <img src="/__mockup/images/ddg-logo.png" alt="DDG" style={{ height: isSm ? 12 : 15, width: isSm ? 12 : 15, objectFit: "contain", mixBlendMode: "screen", opacity: 0.88 }} />
    </div>
  );
}