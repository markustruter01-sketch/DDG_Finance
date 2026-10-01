import { AIBrainVisual } from "./_shared/AIBrainVisual";
import { DDGBadge } from "./_shared/DDGBadge";

export default function StreamingScreen() {
  return (
    <div
      className="stream-screen stream-screen-live"
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
      <div style={{ flex: 1, minHeight: 0 }}>
        <AIBrainVisual />
      </div>
      <DDGBadge style={{ position: "absolute", bottom: 10, left: 10, zIndex: 50 }} />
    </div>
  );
}
