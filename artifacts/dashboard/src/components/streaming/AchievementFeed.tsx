import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import type { Achievement } from "./useRealCelebrations";
import { playAchievement } from "./sounds";

interface AchievementFeedProps {
  achievements: Achievement[];
}

export function AchievementFeed({ achievements }: AchievementFeedProps) {
  const [visible, setVisible] = useState<Achievement[]>([]);

  useEffect(() => {
    if (achievements.length === 0) return;
    const latest = achievements[0];
    setVisible((prev) => {
      if (prev.some((a) => a.id === latest.id)) return prev;
      return [latest, ...prev].slice(0, 3);
    });

    playAchievement();

    const timer = setTimeout(() => {
      setVisible((prev) => prev.filter((a) => a.id !== latest.id));
    }, 3000);

    return () => clearTimeout(timer);
  }, [achievements]);

  if (visible.length === 0) return null;

  return (
    <div className="fixed bottom-20 right-6 z-40 flex flex-col-reverse gap-3 w-[450px] pointer-events-none">
      <AnimatePresence>
        {visible.map((a) => (
          <motion.div
            key={a.id}
            initial={{ opacity: 0, x: 100, scale: 0.8 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: 100, scale: 0.8 }}
            transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] as const }}
            className="rounded-2xl border bg-slate-900/95 backdrop-blur-xl p-4 flex items-start gap-4 shadow-2xl"
            style={{
              borderColor: `${a.color}40`,
              boxShadow: `0 6px 40px ${a.color}25, 0 0 0 1px ${a.color}15`,
            }}
          >
            <span className="text-3xl shrink-0 mt-0.5">{a.icon}</span>
            <div className="flex-1 min-w-0">
              <div className="text-[11px] uppercase tracking-widest font-bold mb-1" style={{ color: a.color }}>
                Achievement Unlocked
              </div>
              <div className="text-[15px] font-bold text-white leading-snug">{a.text}</div>
            </div>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
