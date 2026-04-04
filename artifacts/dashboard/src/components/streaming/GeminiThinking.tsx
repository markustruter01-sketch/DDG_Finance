import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useFleetCommanderStatus, useFleetCommanderHistory } from "@/hooks/use-trading";

export function GeminiThinking() {
  const [displayIdx, setDisplayIdx] = useState(0);
  const [key, setKey] = useState(0);
  const { data: auditStatus } = useFleetCommanderStatus();
  const { data: historyData } = useFleetCommanderHistory();

  const entries: { title: string; body: string }[] = [];

  if (auditStatus?.overall_verdict) {
    entries.push({
      title: "Latest Fleet Audit",
      body: auditStatus.overall_verdict,
    });
  }

  if (auditStatus?.recommendations && Array.isArray(auditStatus.recommendations)) {
    for (const rec of auditStatus.recommendations.slice(0, 3)) {
      const text = typeof rec === "string" ? rec : rec?.text ?? rec?.recommendation ?? JSON.stringify(rec);
      entries.push({ title: "Recommendation", body: text });
    }
  }

  if (historyData?.history && Array.isArray(historyData.history)) {
    for (const audit of historyData.history.slice(0, 5)) {
      if (audit?.overall_verdict) {
        entries.push({
          title: `Audit — ${audit.generated_at ? new Date(audit.generated_at).toLocaleTimeString() : ""}`,
          body: audit.overall_verdict,
        });
      }
    }
  }

  const hasData = entries.length > 0;

  useEffect(() => {
    if (entries.length <= 1) return;
    const interval = setInterval(() => {
      setDisplayIdx((i) => (i + 1) % entries.length);
      setKey((k) => k + 1);
    }, 15000);
    return () => clearInterval(interval);
  }, [entries.length]);

  const current = hasData
    ? entries[displayIdx % entries.length]
    : { title: "Awaiting Data", body: "Fleet Commander has not run an audit yet. Audits run automatically at scheduled intervals." };

  return (
    <div className="rounded-lg border border-violet-500/20 bg-violet-950/20 p-4 relative overflow-hidden flex-1 flex flex-col min-h-0">
      <div className="flex items-center gap-2 mb-1 shrink-0">
        <span className="text-lg">🧠</span>
        <div className="flex flex-col">
          <span
            className="text-[15px] uppercase tracking-wider font-black text-white"
            style={{ textShadow: "0 0 20px rgba(167,139,250,0.6), 0 0 40px rgba(139,92,246,0.3)" }}
          >
            Gemini Fleet Commander
          </span>
          <span className="text-[8px] uppercase tracking-widest font-bold -mt-0.5" style={{ color: "rgba(167,139,250,0.5)" }}>AI Orchestrator · Quant Brain</span>
        </div>
        {hasData ? (
          <motion.div
            className="ml-auto flex gap-0.5"
            animate={{ opacity: [0.3, 1, 0.3] }}
            transition={{ duration: 1.2, repeat: Infinity }}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-violet-400" />
            <span className="h-1.5 w-1.5 rounded-full bg-violet-400" />
            <span className="h-1.5 w-1.5 rounded-full bg-violet-400" />
          </motion.div>
        ) : (
          <span className="ml-auto text-[9px] font-mono" style={{ color: "rgba(167,139,250,0.3)" }}>no data yet</span>
        )}
      </div>
      <div className="flex-1 overflow-hidden min-h-0">
        <AnimatePresence mode="wait">
          <motion.div
            key={key}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.5 }}
            className="flex flex-col gap-2 h-full"
          >
            <div className="text-[16px] font-mono font-bold" style={{ color: "rgba(196,181,253,0.9)" }}>{current.title}</div>
            <div className="text-[15px] font-mono leading-[1.55] flex-1 overflow-hidden" style={{ color: "rgba(255,255,255,0.8)" }}>
              {current.body}
            </div>
          </motion.div>
        </AnimatePresence>
      </div>
      {auditStatus?.generated_at && (
        <div className="text-[9px] mt-2 font-mono shrink-0" style={{ color: "rgba(167,139,250,0.3)" }}>
          Last audit: {new Date(auditStatus.generated_at).toLocaleTimeString()}
        </div>
      )}
    </div>
  );
}
