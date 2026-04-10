import { motion } from "framer-motion";

export function GlobalHUD() {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "14px 28px",
        flexShrink: 0,
        gap: 28,
        background: "linear-gradient(90deg, rgba(10,16,35,0.99), rgba(22,32,55,0.97))",
        borderBottom: "1px solid rgba(99,102,241,0.25)",
      }}
    >
      {/* Welcome text */}
      <div style={{ flexShrink: 1, minWidth: 0 }}>
        {/* Line 1 */}
        <p style={{ margin: "0 0 5px 0", lineHeight: 1.4, fontFamily: "system-ui, sans-serif" }}>
          <span style={{ color: "#e2e8f0", fontWeight: 800, fontSize: 17 }}>Welcome!</span>
          <span style={{ color: "rgba(203,213,225,0.9)", fontWeight: 500, fontSize: 15.5 }}>
            {" "}Experience our six fully automated AI trading algorithms —{" "}
          </span>
          <span style={{ color: "#facc15", fontWeight: 700, fontSize: 15.5 }}>Stocks</span>
          <span style={{ color: "rgba(203,213,225,0.9)", fontSize: 15.5 }}>, </span>
          <span style={{ color: "#22d3ee", fontWeight: 700, fontSize: 15.5 }}>Crypto</span>
          <span style={{ color: "rgba(203,213,225,0.9)", fontSize: 15.5 }}>, </span>
          <span style={{ color: "#a78bfa", fontWeight: 700, fontSize: 15.5 }}>FOREX</span>
          <span style={{ color: "rgba(203,213,225,0.9)", fontSize: 15.5 }}> &amp; </span>
          <span style={{ color: "#fb923c", fontWeight: 700, fontSize: 15.5 }}>Futures</span>
          <span style={{ color: "rgba(203,213,225,0.9)", fontSize: 15.5 }}>.</span>
        </p>
        {/* Line 2 */}
        <p style={{ margin: 0, lineHeight: 1.4, fontFamily: "system-ui, sans-serif" }}>
          <span style={{ color: "#f1f5f9", fontWeight: 700, fontSize: 15 }}>
            Want to build your own for just{" "}
          </span>
          <span style={{ color: "#4ade80", fontWeight: 800, fontSize: 16 }}>$49</span>
          <span style={{ color: "#f1f5f9", fontWeight: 700, fontSize: 15 }}>? No experience required — reach out at{" "}</span>
          <a
            href="mailto:info@digitaldynamics-group.com"
            style={{ color: "#22d3ee", fontWeight: 700, fontSize: 15, textDecoration: "none" }}
          >
            info@digitaldynamics-group.com
          </a>
          <span style={{ color: "rgba(148,163,184,0.85)", fontWeight: 400, fontSize: 14 }}>
            {" "}— We built the entire system from scratch with AI in 1 day, 5 days total with parameter adjustments.
          </span>
        </p>
      </div>

      {/* Branding badge */}
      <motion.div
        style={{
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "10px 20px",
          borderRadius: 10,
          border: "1px solid rgba(99,102,241,0.35)",
          background: "linear-gradient(135deg, rgba(99,102,241,0.18), rgba(139,92,246,0.10))",
          whiteSpace: "nowrap",
        }}
        animate={{
          boxShadow: [
            "0 0 8px rgba(99,102,241,0.1)",
            "0 0 22px rgba(99,102,241,0.35)",
            "0 0 8px rgba(99,102,241,0.1)",
          ],
        }}
        transition={{ duration: 3, repeat: Infinity }}
      >
        <span style={{ fontSize: 18 }}>⚡</span>
        <span
          style={{
            fontFamily: "system-ui, sans-serif",
            fontSize: 13,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "rgba(203,213,225,0.8)",
          }}
        >
          Powered by{" "}
          <motion.span
            style={{ color: "#ffffff" }}
            animate={{ textShadow: ["0 0 8px rgba(255,255,255,0.2)", "0 0 20px rgba(255,255,255,0.55)", "0 0 8px rgba(255,255,255,0.2)"] }}
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
