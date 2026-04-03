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
    <div className="fixed bottom-16 right-4 z-40 flex flex-col-reverse gap-2 w-[290px] pointer-events-none">
      <AnimatePresence>
        {visible.map((a) => (
          <motion.div
            key={a.id}
            initial={{ opacity: 0, x: 100, scale: 0.8 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: 100, scale: 0.8 }}
            transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] as const }}
            className="rounded-xl border bg-slate-900/95 backdrop-blur-xl p-2.5 flex items-start gap-2.5 shadow-2xl"
            style={{
              borderColor: `${a.color}40`,
              boxShadow: `0 4px 24px ${a.color}20, 0 0 0 1px ${a.color}15`,
            }}
          >
            <span className="text-xl shrink-0 mt-0.5">{a.icon}</span>
            <div className="flex-1 min-w-0">
              <div className="text-[7px] uppercase tracking-widest font-bold mb-0.5" style={{ color: a.color }}>
                Achievement Unlocked
              </div>
              <div className="text-[10px] font-bold text-white leading-snug">{a.text}</div>
            </div>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
