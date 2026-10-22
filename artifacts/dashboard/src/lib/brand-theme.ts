import { useCallback, useEffect, useState } from "react";

/** Day (light, default) or night ops (dark). Same layout; tokens swap. */
export type Mode = "light" | "dark";

const KEY = "ddg-mode";

function read(): Mode {
  try {
    return localStorage.getItem(KEY) === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

/** Chart colours: SVG presentation attributes cannot read CSS variables, so
 *  the brand series colours (guide p7, "color.chart.1 → 4") live here too. */
export const CHART = {
  light: {
    series: ["#007A99", "#0B1F2A", "#3E5A69", "#187A4B"],
    text: "#3E5A69",
    hairline: "rgba(11,31,42,0.10)",
    ok: "#187A4B",
    bad: "#C21A30",
  },
  dark: {
    series: ["#00E5FF", "#7CC9E8", "#F7FBFF", "#4FD99A"],
    text: "#F7FBFF",
    hairline: "rgba(124,201,232,0.14)",
    ok: "#4FD99A",
    bad: "#FF5C6E",
  },
} as const;

// Both modes now sit on darkened photography with white type, so both use
// the night-ops chart colours (light-mode navy series would not read).
export function useMode() {
  const [mode, setMode] = useState<Mode>(read);
  useEffect(() => {
    document.documentElement.dataset.theme = mode;
    try {
      localStorage.setItem(KEY, mode);
    } catch {
      /* private window: mode simply is not remembered */
    }
  }, [mode]);
  const toggle = useCallback(() => setMode((m) => (m === "light" ? "dark" : "light")), []);
  return { mode, setMode, toggle, chart: CHART.dark };
}
