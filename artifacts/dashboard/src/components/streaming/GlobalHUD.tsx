import { motion } from "framer-motion";

export function GlobalHUD() {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 24px",
        height: 62,
        flexShrink: 0,
        gap: 24,
        background: "linear-gradient(90deg, rgba(15,23,42,0.98), rgba(30,41,59,0.96))",
        borderBottom: "1px solid rgba(99,102,241,0.18)",
      }}
    >
      {/* Welcome text */}
      <p
        style={{
          margin: 0,
          fontSize: 13.5,
          lineHeight: 1.55,
          color: "rgba(203,213,225,0.88)",
          fontWeight: 500,
          fontFamily: "system-ui, sans-serif",
          flexShrink: 1,
          minWidth: 0,
        }}
      >
        <span style={{ color: "#ddd6fe", fontWeight: 800, fontSize: 14.5 }}>Welcome!</span>
        {" "}Experience our six fully automated AI trading algorithms —{" "}
        <span style={{ color: "#facc15", fontWeight: 700 }}>Stocks</span>,{" "}
        <span style={{ color: "#22d3ee", fontWeight: 700 }}>Crypto</span>,{" "}
        <span style={{ color: "#a78bfa", fontWeight: 700 }}>FOREX</span> &amp;{" "}
        <span style={{ color: "#fb923c", fontWeight: 700 }}>Futures</span>.{" "}
        Want to build your own? No experience required — reach out to us at{" "}
        <a
          href="mailto:info@digitaldynamics-group.com"
          style={{ color: "#22d3ee", fontWeight: 700, textDecoration: "none" }}
        >
          info@digitaldynamics-group.com
        </a>
        {" "}— We built the entire system from scratch with AI systems in 1 day, 5 days total with parameter adjustments.
      </p>

      {/* Branding badge */}
      <motion.div
        style={{
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "8px 18px",
          borderRadius: 10,
          border: "1px solid rgba(99,102,241,0.3)",
          background: "linear-gradient(135deg, rgba(99,102,241,0.15), rgba(139,92,246,0.08))",
          whiteSpace: "nowrap",
        }}
        animate={{
          boxShadow: [
            "0 0 8px rgba(99,102,241,0.1)",
            "0 0 20px rgba(99,102,241,0.3)",
            "0 0 8px rgba(99,102,241,0.1)",
          ],
        }}
        transition={{ duration: 3, repeat: Infinity }}
      >
        <span style={{ fontSize: 16 }}>⚡</span>
        <span
          style={{
            fontFamily: "system-ui, sans-serif",
            fontSize: 12,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "rgba(203,213,225,0.75)",
          }}
        >
          Powered by{" "}
          <motion.span
            style={{ color: "#ffffff" }}
            animate={{ textShadow: ["0 0 8px rgba(255,255,255,0.2)", "0 0 18px rgba(255,255,255,0.5)", "0 0 8px rgba(255,255,255,0.2)"] }}
            transition={{ duration: 3, repeat: Infinity }}
          >
            DIGITAL DYNAMICS
          </motion.span>{" "}
          <span style={{ color: "#22d3ee" }}>Group</span>
        </span>
      </motion.div>
    </div>
  );
}
