import { useState, useEffect, useRef, useCallback } from "react";
import StreamingScreen from "@/pages/StreamingScreen";
import StreamingScreenV2 from "@/pages/StreamingScreenV2";

type SubPage = "a" | "b";

const STORAGE_KEY = "stream-prefs";

interface StreamPrefs {
  autoCycle: boolean;
  intervalSeconds: number;
}

function loadPrefs(): StreamPrefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return {
        autoCycle: typeof parsed.autoCycle === "boolean" ? parsed.autoCycle : false,
        intervalSeconds:
          typeof parsed.intervalSeconds === "number" &&
          parsed.intervalSeconds >= 5 &&
          parsed.intervalSeconds <= 60
            ? parsed.intervalSeconds
            : 10,
      };
    }
  } catch {}
  return { autoCycle: false, intervalSeconds: 10 };
}

function savePrefs(prefs: StreamPrefs) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  } catch {}
}

export default function StreamPage() {
  function getInitialSubPage(): SubPage {
    try {
      const params = new URLSearchParams(window.location.search);
      const sub = params.get("sub");
      if (sub === "b") return "b";
    } catch {}
    return "a";
  }

  const [active, setActive] = useState<SubPage>(getInitialSubPage);
  const prefs = useRef<StreamPrefs>(loadPrefs());
  const [autoCycle, setAutoCycle] = useState(prefs.current.autoCycle);
  const [intervalSeconds, setIntervalSeconds] = useState(prefs.current.intervalSeconds);
  const [progress, setProgress] = useState(0);

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const progressRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const progressStartRef = useRef<number>(0);

  const clearCycle = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    if (progressRef.current) {
      clearInterval(progressRef.current);
      progressRef.current = null;
    }
    setProgress(0);
  }, []);

  const startCycle = useCallback(
    (secs: number) => {
      clearCycle();
      progressStartRef.current = Date.now();

      progressRef.current = setInterval(() => {
        const elapsed = Date.now() - progressStartRef.current;
        const pct = Math.min((elapsed / (secs * 1000)) * 100, 100);
        setProgress(pct);
      }, 50);

      intervalRef.current = setInterval(() => {
        progressStartRef.current = Date.now();
        setProgress(0);
        setActive((prev) => (prev === "a" ? "b" : "a"));
      }, secs * 1000);
    },
    [clearCycle]
  );

  useEffect(() => {
    if (autoCycle) {
      startCycle(intervalSeconds);
    } else {
      clearCycle();
    }
    return clearCycle;
  }, [autoCycle, intervalSeconds, startCycle, clearCycle]);

  function handleToggleAutoCycle() {
    const next = !autoCycle;
    setAutoCycle(next);
    const updated = { autoCycle: next, intervalSeconds };
    prefs.current = updated;
    savePrefs(updated);
  }

  function handleIntervalChange(val: number) {
    const clamped = Math.max(5, Math.min(60, val));
    setIntervalSeconds(clamped);
    const updated = { autoCycle, intervalSeconds: clamped };
    prefs.current = updated;
    savePrefs(updated);
  }

  return (
    <div className="h-screen w-screen bg-slate-950 overflow-hidden flex flex-col">
      <div
        className="flex items-center shrink-0 z-20 relative"
        style={{
          background: "linear-gradient(90deg, rgba(2,6,23,0.97), rgba(15,23,42,0.95))",
          borderBottom: "1px solid rgba(255,255,255,0.06)",
          minHeight: 44,
        }}
      >
        <div className="flex items-center gap-1 px-4">
          <button
            onClick={() => setActive("a")}
            className="px-4 py-1.5 rounded-md text-xs font-bold uppercase tracking-wider transition-all"
            style={{
              background:
                active === "a"
                  ? "linear-gradient(135deg, rgba(99,102,241,0.3), rgba(139,92,246,0.2))"
                  : "transparent",
              color: active === "a" ? "#a5b4fc" : "rgba(148,163,184,0.5)",
              border: active === "a" ? "1px solid rgba(99,102,241,0.4)" : "1px solid transparent",
            }}
          >
            Live
          </button>
          <button
            onClick={() => setActive("b")}
            className="px-4 py-1.5 rounded-md text-xs font-bold uppercase tracking-wider transition-all"
            style={{
              background:
                active === "b"
                  ? "linear-gradient(135deg, rgba(34,211,238,0.2), rgba(168,85,247,0.15))"
                  : "transparent",
              color: active === "b" ? "#67e8f9" : "rgba(148,163,184,0.5)",
              border: active === "b" ? "1px solid rgba(34,211,238,0.3)" : "1px solid transparent",
            }}
          >
            Fleet
          </button>
        </div>

        <div className="ml-auto flex items-center gap-3 px-4">
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-widest font-bold" style={{ color: "rgba(148,163,184,0.4)" }}>
              Interval
            </span>
            <input
              type="number"
              min={5}
              max={60}
              value={intervalSeconds}
              onChange={(e) => handleIntervalChange(Number(e.target.value))}
              className="w-14 bg-slate-900 border rounded text-xs font-mono text-center text-white outline-none focus:ring-1"
              style={{ borderColor: "rgba(99,102,241,0.3)", padding: "2px 4px" }}
            />
            <span className="text-[10px] font-mono" style={{ color: "rgba(148,163,184,0.4)" }}>s</span>
          </div>

          <button
            onClick={handleToggleAutoCycle}
            className="flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-bold uppercase tracking-wider transition-all"
            style={{
              background: autoCycle
                ? "linear-gradient(135deg, rgba(34,197,94,0.25), rgba(16,185,129,0.15))"
                : "rgba(15,23,42,0.8)",
              color: autoCycle ? "#4ade80" : "rgba(148,163,184,0.5)",
              border: autoCycle ? "1px solid rgba(34,197,94,0.4)" : "1px solid rgba(255,255,255,0.08)",
            }}
          >
            <span
              className="inline-block w-1.5 h-1.5 rounded-full"
              style={{
                background: autoCycle ? "#22c55e" : "rgba(148,163,184,0.3)",
                boxShadow: autoCycle ? "0 0 6px #22c55e" : "none",
              }}
            />
            Auto-Cycle
          </button>
        </div>
      </div>

      {autoCycle && (
        <div className="shrink-0 h-0.5 relative" style={{ background: "rgba(255,255,255,0.05)" }}>
          <div
            className="absolute top-0 left-0 h-full transition-none"
            style={{
              width: `${progress}%`,
              background: "linear-gradient(90deg, #6366f1, #22d3ee)",
              boxShadow: "0 0 8px rgba(99,102,241,0.6)",
            }}
          />
        </div>
      )}

      <div className="flex-1 relative overflow-hidden">
        <div style={{ display: active === "a" ? "block" : "none", position: "absolute", inset: 0 }}>
          <StreamingScreen />
        </div>
        <div style={{ display: active === "b" ? "block" : "none", position: "absolute", inset: 0 }}>
          <StreamingScreenV2 />
        </div>
      </div>
    </div>
  );
}
