import { OrbVisualiser } from "@/components/streaming/OrbVisualiser";
import { MiniSynapticWidget } from "@/components/streaming/MiniSynapticWidget";

export default function StreamingOrbScreen() {
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
      <div style={{ flex: 1, minHeight: 0 }}>
        <OrbVisualiser />
      </div>
      <MiniSynapticWidget />
    </div>
  );
}
