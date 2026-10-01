const COLORS: Record<string, string> = {
  purple: "#a855f7",
  cyan: "#06b6d4",
  orange: "#f97316",
};

export function getBotColors(colorName: string | undefined) {
  return { hex: COLORS[colorName ?? ""] ?? "#64748b" };
}