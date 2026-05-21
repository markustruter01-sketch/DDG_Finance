import type { CSSProperties } from "react";

interface DDGBadgeProps {
  style?: CSSProperties;
  size?: "sm" | "md";
}

export function DDGBadge({ style, size = "md" }: DDGBadgeProps) {
  const isSm = size === "sm";
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: isSm ? 4 : 6,
        background: "rgba(2,6,23,0.85)",
        border: "1px solid rgba(255,255,255,1)",
        borderLeft: "3px solid rgba(255,255,255,1)",
        borderRadius: 7,
        padding: isSm ? "3px 8px 3px 6px" : "5px 12px 5px 8px",
        backdropFilter: "blur(12px)",
        boxShadow: "0 0 20px rgba(251,146,60,0.08)",
        ...style,
      }}
    >
      <span style={{ color: "#ffffff", fontSize: isSm ? 11 : 13, lineHeight: 1, flexShrink: 0 }}>⚡</span>
      <span
        style={{
          fontFamily: "monospace",
          fontSize: isSm ? 8 : 10,
          letterSpacing: "0.08em",
          color: "rgba(255,255,255,0.65)",
          whiteSpace: "nowrap",
          lineHeight: 1,
        }}
      >
        POWERED BY{" "}
        <span style={{ color: "#ffffff", fontWeight: 700 }}>DIGITAL DYNAMICS</span>{" "}
        <span style={{ color: "#ffffff", fontWeight: 700 }}>GROUP</span>
      </span>
      <img
        src="/ddg-logo.png"
        alt="DDG"
        style={{
          height: isSm ? 12 : 15,
          width: isSm ? 12 : 15,
          objectFit: "contain",
          mixBlendMode: "screen",
          opacity: 0.88,
          flexShrink: 0,
          display: "block",
        }}
      />
    </div>
  );
}
