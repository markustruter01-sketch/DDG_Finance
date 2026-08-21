import { useState, useEffect, useRef, useCallback } from "react";
import StreamingScreen from "@/pages/StreamingScreen";
import SynapticAuditScreen from "@/pages/SynapticAuditScreen";
import StreamingBotsScreen from "@/pages/StreamingBotsScreen";
import StreamingHealthScreen from "@/pages/StreamingHealthScreen";
import StreamingPerformanceScreen from "@/pages/StreamingPerformanceScreen";
import StreamingArchitectureScreen from "@/pages/StreamingArchitectureScreen";
import { ClippyAssistant } from "@/components/streaming/ClippyAssistant";
import { StreamHeaderBar } from "@/components/streaming/StreamHeaderBar";

type SubPage = "a" | "b" | "c" | "d" | "g" | "h";

const SUB_PAGES: SubPage[] = ["a", "b", "c", "d", "g", "h"];

function nextPage(current: SubPage): SubPage {
  const idx = SUB_PAGES.indexOf(current);
  return SUB_PAGES[(idx + 1) % SUB_PAGES.length];
}

const STORAGE_KEY = "stream-prefs-v2";

interface StreamPrefs {
  autoCycle: boolean;
  intervalSeconds: number;
}

function parseUrlParams(): { autoCycle: boolean | null; intervalSeconds: number | null; subPage: SubPage | null } {
  try {
    const params = new URLSearchParams(window.location.search);
    const autoParam = params.get("auto");
    const intervalParam = params.get("interval");
    const subParam = params.get("sub");

    const autoCycle = autoParam === "1" ? true : autoParam === "0" ? false : null;

    let intervalSeconds: number | null = null;
    if (intervalParam !== null) {
      const parsed = parseInt(intervalParam, 10);
      if (!isNaN(parsed)) {
        intervalSeconds = Math.max(5, Math.min(120, parsed));
      }
    }

    let subPage: SubPage | null = null;
    if (subParam === "b" || subParam === "c" || subParam === "d" || subParam === "g" || subParam === "h") subPage = subParam;
    else if (subParam === "a") subPage = "a";

    return { autoCycle, intervalSeconds, subPage };
  } catch {
    return { autoCycle: null, intervalSeconds: null, subPage: null };
  }
}

function loadPrefs(): StreamPrefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return {
        autoCycle: typeof parsed.autoCycle === "boolean" ? parsed.autoCycle : true,
        intervalSeconds:
          typeof parsed.intervalSeconds === "number" &&
          parsed.intervalSeconds >= 5 &&
          parsed.intervalSeconds <= 120
            ? parsed.intervalSeconds
            : 15,
      };
    }
  } catch {}
  return { autoCycle: false, intervalSeconds: 15 };
}

function savePrefs(prefs: StreamPrefs) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  } catch {}
}

export default function StreamPage() {
  const urlParams = useRef(parseUrlParams());
  const urlControlled = urlParams.current.autoCycle !== null || urlParams.current.intervalSeconds !== null;

  function getInitialSubPage(): SubPage {
    if (urlParams.current.subPage) return urlParams.current.subPage;
    return "a";
  }

  const stored = useRef<StreamPrefs>(loadPrefs());

  function getInitialAutoCycle(): boolean {
    if (urlParams.current.autoCycle !== null) return urlParams.current.autoCycle;
    return false;
  }

  function getInitialInterval(): number {
    if (urlParams.current.intervalSeconds !== null) return urlParams.current.intervalSeconds;
    return stored.current.intervalSeconds;
  }

  const [active, setActive] = useState<SubPage>(getInitialSubPage);
  const [autoCycle, setAutoCycle] = useState<boolean>(getInitialAutoCycle);
  const [intervalSeconds, setIntervalSeconds] = useState<number>(getInitialInterval);
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
        setActive((prev) => nextPage(prev));
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
    if (!urlControlled) {
      savePrefs({ autoCycle: next, intervalSeconds });
    }
  }

  function handleIntervalChange(val: number) {
    const clamped = Math.max(5, Math.min(120, val));
    setIntervalSeconds(clamped);
    if (!urlControlled) {
      savePrefs({ autoCycle, intervalSeconds: clamped });
    }
  }

  const tabs: { id: SubPage; label: string; activeGrad: string; activeColor: string; activeBorder: string; progressGrad: string; progressGlow: string }[] = [
    {
      id: "a",
      label: "Live",
      activeGrad: "linear-gradient(135deg, rgba(99,102,241,0.3), rgba(139,92,246,0.2))",
      activeColor: "#a5b4fc",
      activeBorder: "rgba(99,102,241,0.4)",
      progressGrad: "linear-gradient(90deg, #6366f1, #a78bfa)",
      progressGlow: "rgba(99,102,241,0.6)",
    },
    {
      id: "b",
      label: "Math",
      activeGrad: "linear-gradient(135deg, rgba(34,211,238,0.2), rgba(168,85,247,0.15))",
      activeColor: "#67e8f9",
      activeBorder: "rgba(34,211,238,0.3)",
      progressGrad: "linear-gradient(90deg, #22d3ee, #a855f7)",
      progressGlow: "rgba(34,211,238,0.6)",
    },
    {
      id: "c",
      label: "Bots",
      activeGrad: "linear-gradient(135deg, rgba(16,185,129,0.25), rgba(34,211,238,0.12))",
      activeColor: "#34d399",
      activeBorder: "rgba(16,185,129,0.4)",
      progressGrad: "linear-gradient(90deg, #10b981, #22d3ee)",
      progressGlow: "rgba(16,185,129,0.6)",
    },
    {
      id: "d",
      label: "Health",
      activeGrad: "linear-gradient(135deg, rgba(239,68,68,0.25), rgba(245,158,11,0.15))",
      activeColor: "#fca5a5",
      activeBorder: "rgba(239,68,68,0.4)",
      progressGrad: "linear-gradient(90deg, #ef4444, #f59e0b)",
      progressGlow: "rgba(239,68,68,0.6)",
    },
    {
      id: "g",
      label: "Performance",
      activeGrad: "linear-gradient(135deg, rgba(251,146,60,0.28), rgba(250,204,21,0.15))",
      activeColor: "#fdba74",
      activeBorder: "rgba(251,146,60,0.45)",
      progressGrad: "linear-gradient(90deg, #f97316, #facc15)",
      progressGlow: "rgba(251,146,60,0.65)",
    },
    {
      id: "h",
      label: "Architecture",
      activeGrad: "linear-gradient(135deg, rgba(99,102,241,0.28), rgba(34,211,238,0.15))",
      activeColor: "#a5b4fc",
      activeBorder: "rgba(99,102,241,0.4)",
      progressGrad: "linear-gradient(90deg, #6366f1, #22d3ee)",
      progressGlow: "rgba(99,102,241,0.6)",
    },
  ];

  const activeTab = tabs.find((t) => t.id === active)!;

  return (
    <div style={{ height: "100vh", width: "100vw", overflow: "hidden", display: "flex", flexDirection: "column" }}>
      <StreamHeaderBar />
      <div
        className="flex items-center shrink-0 z-20 relative"
        style={{
          background: "#000000",
          borderBottom: "1px solid rgba(255,255,255,0.06)",
          minHeight: 44,
        }}
      >
        <div className="flex items-center gap-1 px-4">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActive(tab.id)}
              className="px-4 py-1.5 rounded-md text-xs font-bold uppercase tracking-wider transition-all"
              style={{
                background: active === tab.id ? tab.activeGrad : "transparent",
                color: active === tab.id ? tab.activeColor : "rgba(255,255,255,0.8)",
                border: active === tab.id ? `1px solid ${tab.activeBorder}` : "1px solid transparent",
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Page indicator dots */}
        <div className="flex items-center gap-1 ml-2">
          {tabs.map((tab) => (
            <span
              key={tab.id}
              className="w-1 h-1 rounded-full transition-all"
              style={{
                background: active === tab.id ? tab.activeColor : "rgba(148,163,184,0.2)",
                boxShadow: active === tab.id ? `0 0 4px ${tab.activeColor}` : "none",
              }}
            />
          ))}
        </div>

        <div className="ml-auto flex items-center gap-3 px-4">
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-widest font-bold" style={{ color: "rgba(148,163,184,0.4)" }}>
              Interval
            </span>
            <input
              type="number"
              min={5}
              max={120}
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
              background: activeTab.progressGrad,
              boxShadow: `0 0 8px ${activeTab.progressGlow}`,
            }}
          />
        </div>
      )}

      <div className="flex-1 relative overflow-hidden">
        <div style={{ display: active === "a" ? "block" : "none", position: "absolute", inset: 0 }}>
          <StreamingScreen />
        </div>
        <div style={{ display: active === "b" ? "block" : "none", position: "absolute", inset: 0 }}>
          <SynapticAuditScreen />
        </div>
        <div style={{ display: active === "c" ? "block" : "none", position: "absolute", inset: 0 }}>
          <StreamingBotsScreen />
        </div>
        <div style={{ display: active === "d" ? "block" : "none", position: "absolute", inset: 0 }}>
          <StreamingHealthScreen />
        </div>
        <div style={{ display: active === "g" ? "block" : "none", position: "absolute", inset: 0 }}>
          <StreamingPerformanceScreen />
        </div>
        <div style={{ display: active === "h" ? "block" : "none", position: "absolute", inset: 0 }}>
          <StreamingArchitectureScreen />
        </div>
      </div>

      <ClippyAssistant active={active} />
    </div>
  );
}
