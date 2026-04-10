import { GlobalHUD } from "@/components/streaming/GlobalHUD";
import { AIBrainVisual } from "@/components/streaming/AIBrainVisual";

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
      }}
    >
      <GlobalHUD />
      <div style={{ flex: 1, minHeight: 0 }}>
        <AIBrainVisual />
      </div>
    </div>
  );
}
