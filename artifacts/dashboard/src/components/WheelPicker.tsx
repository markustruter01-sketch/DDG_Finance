/** A scroll wheel for picking a whole number from a fixed range (Night Glass M22).
 *  Swipe or scroll it; the value under the centre band is the choice. Keyboard:
 *  arrows ±1 step, Page Up/Down ±10 steps, Home/End for the ends. Replaces a typed
 *  number box, which could not be emptied (Markus, 25 Nov 2026: the 0 would not go).
 *  Keyboard follows the spin-button pattern: Arrow Up = one step more. */
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";

const ROW = 40;           // px; matches --wheel-row in night-glass.css
const SETTLE_MS = 120;    // how long the wheel must be still before its value counts

export function WheelPicker({ value, onChange, min = 0, max = 100, step = 1, unit = "", labelledBy }: {
  value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number; unit?: string; labelledBy: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const settle = useRef(0);
  const count = Math.floor((max - min) / step) + 1;
  const clamp = (v: number) => Math.max(min, Math.min(max, v));
  const at = (i: number) => min + Math.max(0, Math.min(count - 1, i)) * step;
  const [shown, setShown] = useState(clamp(value));

  // Sit on the value: on the first render and whenever it changes from outside.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const top = Math.round((clamp(value) - min) / step) * ROW;
    if (Math.abs(el.scrollTop - top) > 1) el.scrollTop = top;
    setShown(clamp(value));
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => window.clearTimeout(settle.current), []);

  const onScroll = () => {
    const el = ref.current;
    if (!el) return;
    const v = at(Math.round(el.scrollTop / ROW));
    setShown(v);
    window.clearTimeout(settle.current);
    settle.current = window.setTimeout(() => onChange(v), SETTLE_MS);
  };
  const go = (v: number) => {
    const el = ref.current;
    if (!el) return;
    const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollTo({ top: Math.round((clamp(v) - min) / step) * ROW, behavior: smooth ? "smooth" : "auto" });
  };
  const onKey = (e: KeyboardEvent) => {
    const jump: Record<string, number> = { ArrowUp: step, ArrowDown: -step, PageUp: 10 * step, PageDown: -10 * step };   // spin button: up = more
    let v: number | null = null;
    if (e.key in jump) v = shown + jump[e.key];
    if (e.key === "Home") v = min;
    if (e.key === "End") v = max;
    if (v == null) return;
    e.preventDefault();
    onChange(clamp(v));       // the layout effect moves the wheel
  };

  return (
    <div className="wheel">
      <span className="wheel-band" aria-hidden="true" />
      <div ref={ref} className="wheel-scroll" tabIndex={0} role="spinbutton" aria-labelledby={labelledBy}
        aria-valuemin={min} aria-valuemax={max} aria-valuenow={shown} aria-valuetext={`${shown}${unit}`}
        onScroll={onScroll} onKeyDown={onKey}>
        {Array.from({ length: count }, (_, i) => at(i)).map((v) => (
          <div key={v} className={`wheel-row${v === shown ? " on" : ""}`} onClick={() => go(v)}>{v}{unit}</div>
        ))}
      </div>
    </div>
  );
}
