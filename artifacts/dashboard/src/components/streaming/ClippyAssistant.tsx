import { useState, useEffect, useRef } from "react";

type SubPage = "a" | "b" | "c" | "d" | "e" | "f" | "g" | "h";

interface PageConfig {
  message: string;
  color: string;
  glowColor: string;
  floatDur: string;
  wobbleDur: string;
  eyeColor: string;
  pupilColor: string;
  blinkDur: string;
}

const PAGE_CONFIG: Record<SubPage, PageConfig> = {
  a: {
    message: "Our robots are making live trades right now! Watch the green numbers — that means we're winning! 🤖",
    color: "#818cf8",
    glowColor: "rgba(99,102,241,0.5)",
    floatDur: "3.5s",
    wobbleDur: "5s",
    eyeColor: "#e0e7ff",
    pupilColor: "#312e81",
    blinkDur: "5s",
  },
  b: {
    message: "This is the Synaptic Math Audit Engine — it checks every trade calculation for accuracy. A 100% pass rate means our math is bulletproof! 🧮",
    color: "#22d3ee",
    glowColor: "rgba(34,211,238,0.5)",
    floatDur: "4s",
    wobbleDur: "6s",
    eyeColor: "#cffafe",
    pupilColor: "#0e7490",
    blinkDur: "4.5s",
  },
  c: {
    message: "Bot Fleet Leaderboard — every trading robot ranked by all-time P&L. The top bot earns the crown! 👑",
    color: "#34d399",
    glowColor: "rgba(52,211,153,0.5)",
    floatDur: "3s",
    wobbleDur: "4.5s",
    eyeColor: "#d1fae5",
    pupilColor: "#065f46",
    blinkDur: "4s",
  },
  d: {
    message: "Mission control! Every green node means that system is running perfectly. Red means trouble — but auto-heal kicks in immediately! 🟢",
    color: "#fbbf24",
    glowColor: "rgba(251,191,36,0.5)",
    floatDur: "2.2s",
    wobbleDur: "3.5s",
    eyeColor: "#fef9c3",
    pupilColor: "#78350f",
    blinkDur: "3s",
  },
  e: {
    message: "The Learning Journal tracks every symbol pair our algorithms study. Hurst exponents below 0.45 mean it's safe to mean-revert! 🧠",
    color: "#6ee7b7",
    glowColor: "rgba(110,231,183,0.5)",
    floatDur: "4.5s",
    wobbleDur: "7s",
    eyeColor: "#ecfdf5",
    pupilColor: "#064e3b",
    blinkDur: "6s",
  },
  f: {
    message: "The Orb is alive! Every glow, pulse and tendril is live trading activity. Each orbiting ring is one of your bots — watch the flares when trades close! ✨",
    color: "#c084fc",
    glowColor: "rgba(192,132,252,0.55)",
    floatDur: "5s",
    wobbleDur: "8s",
    eyeColor: "#f3e8ff",
    pupilColor: "#4c1d95",
    blinkDur: "7s",
  },
  g: {
    message: "Raw performance! Sharpe, Sortino, max drawdown, Calmar — every number that tells you if the system is ACTUALLY working. Green ratios mean the math is on our side! 📊",
    color: "#fb923c",
    glowColor: "rgba(251,146,60,0.5)",
    floatDur: "3.2s",
    wobbleDur: "4.8s",
    eyeColor: "#ffedd5",
    pupilColor: "#431407",
    blinkDur: "5s",
  },
  h: {
    message: "System Architecture map! Every component, database table, and external service laid out visually. Click a Flow on the right to highlight exactly how data moves through the platform. 🗺️",
    color: "#a5b4fc",
    glowColor: "rgba(99,102,241,0.5)",
    floatDur: "4s",
    wobbleDur: "6s",
    eyeColor: "#e0e7ff",
    pupilColor: "#7c2d12",
    blinkDur: "4.2s",
  },
};

const AUTO_HIDE_MS = 12_000;

interface ClippyAssistantProps {
  active: SubPage;
}

export function ClippyAssistant({ active }: ClippyAssistantProps) {
  const [displayed, setDisplayed] = useState<SubPage>(active);
  const [visible, setVisible] = useState(true);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (hideTimer.current) clearTimeout(hideTimer.current);

    setVisible(false);
    const showTimer = setTimeout(() => {
      setDisplayed(active);
      setVisible(true);

      hideTimer.current = setTimeout(() => {
        setVisible(false);
      }, AUTO_HIDE_MS);
    }, 250);

    return () => {
      clearTimeout(showTimer);
      if (hideTimer.current) clearTimeout(hideTimer.current);
    };
  }, [active]);

  const cfg = PAGE_CONFIG[displayed];

  const animId = `clippy-${displayed}`;

  return (
    <>
      <style>{`
        @keyframes ${animId}-wobble {
          0%   { transform: rotate(-3deg) translateY(0px); }
          25%  { transform: rotate(3deg)  translateY(-2px); }
          50%  { transform: rotate(-2deg) translateY(0px); }
          75%  { transform: rotate(2deg)  translateY(-1px); }
          100% { transform: rotate(-3deg) translateY(0px); }
        }
        @keyframes ${animId}-blink {
          0%, 90%, 100% { transform: scaleY(1); }
          92%, 97%      { transform: scaleY(0.04); }
        }
        @keyframes ${animId}-float {
          0%, 100% { transform: translateY(0px); }
          50%      { transform: translateY(-6px); }
        }
        @keyframes ${animId}-bubble-in {
          0%   { opacity: 0; transform: scale(0.85) translateY(6px); }
          100% { opacity: 1; transform: scale(1) translateY(0px); }
        }
        @keyframes ${animId}-heartbeat {
          0%, 100% { filter: drop-shadow(0 0 8px ${cfg.glowColor}); }
          50%       { filter: drop-shadow(0 0 20px ${cfg.glowColor}) drop-shadow(0 0 8px ${cfg.color}); }
        }
      `}</style>

      <div
        style={{
          position: "fixed",
          bottom: 56,
          right: 16,
          zIndex: 9999,
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-end",
          gap: 12,
          pointerEvents: "none",
          userSelect: "none",
          opacity: visible ? 1 : 0,
          transition: "opacity 0.35s ease",
        }}
      >
        {/* Speech bubble */}
        <div
          style={{
            maxWidth: 340,
            background: "linear-gradient(135deg, rgba(15,23,42,0.97), rgba(30,41,59,0.95))",
            border: `1px solid ${cfg.color}55`,
            borderRadius: 18,
            padding: "14px 20px",
            boxShadow: `0 5px 28px rgba(0,0,0,0.65), 0 0 18px ${cfg.glowColor}30`,
            position: "relative",
            animation: visible ? `${animId}-bubble-in 0.35s ease both` : "none",
          }}
        >
          {/* Page accent line */}
          <div style={{
            position: "absolute",
            top: 0,
            left: 18,
            right: 18,
            height: 2,
            borderRadius: "0 0 4px 4px",
            background: `linear-gradient(90deg, transparent, ${cfg.color}, transparent)`,
            opacity: 0.7,
          }} />
          <p
            style={{
              margin: 0,
              fontSize: 16,
              lineHeight: 1.55,
              color: "rgba(226,232,240,0.93)",
              fontWeight: 600,
              fontFamily: "system-ui, sans-serif",
            }}
          >
            {cfg.message}
          </p>
          {/* Tail border */}
          <div style={{
            position: "absolute",
            bottom: -13,
            right: 34,
            width: 0,
            height: 0,
            borderLeft: "7px solid transparent",
            borderRight: "13px solid transparent",
            borderTop: `13px solid ${cfg.color}55`,
          }} />
          {/* Tail fill */}
          <div style={{
            position: "absolute",
            bottom: -10,
            right: 37,
            width: 0,
            height: 0,
            borderLeft: "5px solid transparent",
            borderRight: "10px solid transparent",
            borderTop: "10px solid rgba(15,23,42,0.97)",
          }} />
        </div>

        {/* Clippy mascot SVG */}
        <div
          style={{
            marginRight: 14,
            animation: `${animId}-float ${cfg.floatDur} ease-in-out infinite, ${animId}-heartbeat 3s ease-in-out infinite`,
          }}
        >
          <svg
            width={88}
            height={116}
            viewBox="0 0 54 72"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            style={{
              animation: `${animId}-wobble ${cfg.wobbleDur} ease-in-out infinite`,
            }}
          >
            {/* Body — outer glow ring */}
            <path
              d="M27 4 C12 4, 6 12, 6 22 C6 32, 12 40, 22 40 L32 40 C38 40, 42 44, 42 50 C42 56, 38 62, 30 62 C22 62, 18 56, 18 50 L18 30"
              stroke={cfg.color}
              strokeWidth={6}
              strokeLinecap="round"
              fill="none"
              opacity={0.18}
            />
            {/* Body — main */}
            <path
              d="M27 4 C12 4, 6 12, 6 22 C6 32, 12 40, 22 40 L32 40 C38 40, 42 44, 42 50 C42 56, 38 62, 30 62 C22 62, 18 56, 18 50 L18 30"
              stroke={cfg.color}
              strokeWidth={5}
              strokeLinecap="round"
              fill="none"
            />
            {/* Inner loop */}
            <path
              d="M27 13 C19 13, 15 18, 15 24 C15 30, 19 33, 24 33 L32 33"
              stroke={cfg.color}
              strokeWidth={4}
              strokeLinecap="round"
              fill="none"
              opacity={0.75}
            />
            {/* Highlight */}
            <path
              d="M27 4 C19 4, 11 9, 9 17"
              stroke="rgba(255,255,255,0.28)"
              strokeWidth={2}
              strokeLinecap="round"
              fill="none"
            />
            {/* Face area */}
            <ellipse cx="28" cy="24" rx="9" ry="10" fill="rgba(15,23,42,0.0)" />
            {/* Eyes */}
            <g style={{ animation: `${animId}-blink ${cfg.blinkDur} ease-in-out infinite`, transformOrigin: "28px 22px" }}>
              <circle cx="24" cy="22" r="2.2" fill={cfg.eyeColor} />
              <circle cx="32" cy="22" r="2.2" fill={cfg.eyeColor} />
              <circle cx="24.7" cy="22.7" r="1.1" fill={cfg.pupilColor} />
              <circle cx="32.7" cy="22.7" r="1.1" fill={cfg.pupilColor} />
              <circle cx="23.5" cy="21.3" r="0.55" fill="white" opacity={0.9} />
              <circle cx="31.5" cy="21.3" r="0.55" fill="white" opacity={0.9} />
            </g>
            {/* Smile */}
            <path
              d="M23 27 Q28 31.5 33 27"
              stroke={cfg.eyeColor}
              strokeWidth={1.6}
              strokeLinecap="round"
              fill="none"
            />
            {/* Cheeks */}
            <ellipse cx="21" cy="26.5" rx="2.5" ry="1.5" fill="rgba(251,113,133,0.35)" />
            <ellipse cx="35" cy="26.5" rx="2.5" ry="1.5" fill="rgba(251,113,133,0.35)" />
          </svg>
        </div>
      </div>
    </>
  );
}
