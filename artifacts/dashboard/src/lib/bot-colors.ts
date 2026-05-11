/**
 * Maps registry color names to Tailwind utility classes.
 * Used by all bot card components for consistent theming.
 */
export interface BotColorClasses {
  border: string;
  glow: string;
  text: string;
  bg: string;
  hex: string;
}

const COLOR_MAP: Record<string, BotColorClasses> = {
  purple: { border: "border-purple-500", glow: "shadow-purple-500/50", text: "text-purple-400", bg: "bg-purple-500/10", hex: "#a855f7" },
  amber:  { border: "border-amber-500",  glow: "shadow-amber-500/50",  text: "text-amber-400",  bg: "bg-amber-500/10",  hex: "#f59e0b" },
  red:    { border: "border-red-500",    glow: "shadow-red-500/50",    text: "text-red-400",    bg: "bg-red-500/10",    hex: "#ef4444" },
  cyan:   { border: "border-cyan-500",   glow: "shadow-cyan-500/50",   text: "text-cyan-400",   bg: "bg-cyan-500/10",   hex: "#06b6d4" },
  green:  { border: "border-green-500",  glow: "shadow-green-500/50",  text: "text-green-400",  bg: "bg-green-500/10",  hex: "#10b981" },
  indigo: { border: "border-indigo-500", glow: "shadow-indigo-500/50", text: "text-indigo-400", bg: "bg-indigo-500/10", hex: "#6366f1" },
  blue:   { border: "border-blue-500",   glow: "shadow-blue-500/50",   text: "text-blue-400",   bg: "bg-blue-500/10",   hex: "#3b82f6" },
  teal:   { border: "border-teal-500",   glow: "shadow-teal-500/50",   text: "text-teal-400",   bg: "bg-teal-500/10",   hex: "#14b8a6" },
  slate:  { border: "border-slate-500",  glow: "shadow-slate-500/50",  text: "text-slate-400",  bg: "bg-slate-500/10",  hex: "#64748b" },
};

const DEFAULT: BotColorClasses = COLOR_MAP.slate;

export function getBotColors(colorName: string | undefined): BotColorClasses {
  if (!colorName) return DEFAULT;
  return COLOR_MAP[colorName] ?? DEFAULT;
}
