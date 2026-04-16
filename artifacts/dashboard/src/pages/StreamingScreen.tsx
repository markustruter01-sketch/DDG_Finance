import { GlobalHUD } from "@/components/streaming/GlobalHUD";
import { AIBrainVisual } from "@/components/streaming/AIBrainVisual";
import { DDGBadge } from "@/components/DDGBadge";

export default function StreamingScreen() {
  return (
    <div
      style={{
        height: "100%",
        width: "100%",
        background: "#020617",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        position: "relative",
      }}
    >
      <GlobalHUD />
      <div style={{ flex: 1, minHeight: 0 }}>
        <AIBrainVisual />
      </div>
      <DDGBadge style={{ position: "absolute", bottom: 10, left: 10, zIndex: 50 }} />
    </div>
  );
}
