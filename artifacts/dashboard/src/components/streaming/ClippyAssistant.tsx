import { useState, useEffect } from "react";

type SubPage = "a" | "b" | "c" | "d" | "e";

const MESSAGES: Record<SubPage, string> = {
  a: "Our robots are making live trades right now! Watch the green numbers — that means we're winning! 🤖",
  b: "All 6 trading robots in one view! Each one is a market specialist working 24 hours a day! 💪",
  c: "Here are each robot's current open trades and strategy settings — like peeking at their game plan! 📋",
  d: "Mission control! Every green node means that system is running perfectly. Red means trouble! 🟢",
  e: "The ultimate command center! Every bot's P&L, all open trades, live news, and our AI brain — all in one place! 🚀",
};

interface ClippyAssistantProps {
  active: SubPage;
}

export function ClippyAssistant({ active }: ClippyAssistantProps) {
  const [displayed, setDisplayed] = useState<SubPage>(active);
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    setVisible(false);
    const t = setTimeout(() => {
      setDisplayed(active);
      setVisible(true);
    }, 250);
    return () => clearTimeout(t);
  }, [active]);

  const msg = MESSAGES[displayed];

  return (
    <>
      <style>{`
        @keyframes clippyWobble {
          0%   { transform: rotate(-3deg) translateY(0px); }
          25%  { transform: rotate(3deg)  translateY(-2px); }
          50%  { transform: rotate(-2deg) translateY(0px); }
          75%  { transform: rotate(2deg)  translateY(-1px); }
          100% { transform: rotate(-3deg) translateY(0px); }
        }
        @keyframes eyeBlink {
          0%, 92%, 100% { transform: scaleY(1); }
          94%, 98%      { transform: scaleY(0.05); }
        }
        @keyframes clippyFloat {
          0%, 100% { transform: translateY(0px); }
          50%      { transform: translateY(-5px); }
        }
      `}</style>

      <div
        style={{
          position: "fixed",
          bottom: 56,
          left: 16,
          zIndex: 9999,
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-start",
          gap: 10,
          pointerEvents: "none",
          userSelect: "none",
        }}
      >
        {/* Speech bubble */}
        <div
          style={{
            opacity: visible ? 1 : 0,
            transition: "opacity 0.25s ease",
            maxWidth: 264,
            background: "linear-gradient(135deg, rgba(15,23,42,0.97), rgba(30,41,59,0.95))",
            border: "1px solid rgba(99,102,241,0.35)",
            borderRadius: 14,
            padding: "12px 16px",
            boxShadow: "0 5px 28px rgba(0,0,0,0.6), 0 0 14px rgba(99,102,241,0.15)",
            position: "relative",
          }}
        >
          <p
            style={{
              margin: 0,
              fontSize: 13,
              lineHeight: 1.5,
              color: "rgba(226,232,240,0.92)",
              fontWeight: 600,
              fontFamily: "system-ui, sans-serif",
            }}
          >
            {msg}
          </p>
          {/* Bubble tail */}
          <div
            style={{
              position: "absolute",
              bottom: -10,
              left: 26,
              width: 0,
              height: 0,
              borderLeft: "10px solid transparent",
              borderRight: "5px solid transparent",
              borderTop: "10px solid rgba(99,102,241,0.35)",
            }}
          />
          <div
            style={{
              position: "absolute",
              bottom: -8,
              left: 28,
              width: 0,
              height: 0,
              borderLeft: "8px solid transparent",
              borderRight: "4px solid transparent",
              borderTop: "8px solid rgba(15,23,42,0.97)",
            }}
          />
        </div>

        {/* Clippy mascot SVG */}
        <div
          style={{
            marginLeft: 10,
            animation: "clippyFloat 3.5s ease-in-out infinite",
          }}
        >
          <svg
            width={65}
            height={86}
            viewBox="0 0 54 72"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            style={{ animation: "clippyWobble 5s ease-in-out infinite", filter: "drop-shadow(0 0 10px rgba(99,102,241,0.5))" }}
          >
            <path
              d="M27 4 C12 4, 6 12, 6 22 C6 32, 12 40, 22 40 L32 40 C38 40, 42 44, 42 50 C42 56, 38 62, 30 62 C22 62, 18 56, 18 50 L18 30"
              stroke="#818cf8"
              strokeWidth={5}
              strokeLinecap="round"
              fill="none"
            />
            <path
              d="M27 13 C19 13, 15 18, 15 24 C15 30, 19 33, 24 33 L32 33"
              stroke="#a5b4fc"
              strokeWidth={4}
              strokeLinecap="round"
              fill="none"
            />
            <path
              d="M27 4 C19 4, 11 9, 9 17"
              stroke="rgba(255,255,255,0.3)"
              strokeWidth={2}
              strokeLinecap="round"
              fill="none"
            />
            <ellipse cx="28" cy="24" rx="9" ry="10" fill="rgba(15,23,42,0.0)" />
            <g style={{ animation: "eyeBlink 5s ease-in-out infinite", transformOrigin: "28px 22px" }}>
              <circle cx="24" cy="22" r="2" fill="#e0e7ff" />
              <circle cx="32" cy="22" r="2" fill="#e0e7ff" />
              <circle cx="24.7" cy="22.7" r="1" fill="#312e81" />
              <circle cx="32.7" cy="22.7" r="1" fill="#312e81" />
              <circle cx="23.5" cy="21.5" r="0.5" fill="white" />
              <circle cx="31.5" cy="21.5" r="0.5" fill="white" />
            </g>
            <path
              d="M23 27 Q28 31 33 27"
              stroke="#e0e7ff"
              strokeWidth={1.5}
              strokeLinecap="round"
              fill="none"
            />
            <ellipse cx="21" cy="26" rx="2.5" ry="1.5" fill="rgba(251,113,133,0.4)" />
            <ellipse cx="35" cy="26" rx="2.5" ry="1.5" fill="rgba(251,113,133,0.4)" />
          </svg>
        </div>
      </div>
    </>
  );
}
