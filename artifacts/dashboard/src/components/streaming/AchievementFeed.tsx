import { motion, AnimatePresence } from "framer-motion";
import type { Achievement } from "./useSimulatedFeed";

interface AchievementFeedProps {
  achievements: Achievement[];
}

export function AchievementFeed({ achievements }: AchievementFeedProps) {
  if (achievements.length === 0) return null;

  return (
    <div className="fixed top-4 right-4 z-40 flex flex-col gap-2 w-[340px] pointer-events-none">
      <AnimatePresence>
        {achievements.slice(0, 3).map((a) => (
          <motion.div
            key={a.id}
            initial={{ opacity: 0, x: 100, scale: 0.8 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: 100, scale: 0.8 }}
            transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] as const }}
            className="rounded-xl border bg-slate-900/95 backdrop-blur-xl p-3 flex items-start gap-3 shadow-2xl"
            style={{
              borderColor: `${a.color}40`,
              boxShadow: `0 4px 30px ${a.color}20, 0 0 0 1px ${a.color}15`,
            }}
          >
            <span className="text-2xl shrink-0 mt-0.5">{a.icon}</span>
            <div className="flex-1 min-w-0">
              <div className="text-[8px] uppercase tracking-widest font-bold mb-0.5" style={{ color: a.color }}>
                Achievement Unlocked
              </div>
              <div className="text-xs font-bold text-white leading-snug">{a.text}</div>
            </div>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
