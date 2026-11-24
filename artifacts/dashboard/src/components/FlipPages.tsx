import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useSlidingPill } from "@/components/Motion";

/**
 * Two screens on one sheet. Scrolling past the end of either screen turns the
 * sheet over (like lifting an A4 page and flipping it) to the other one, so
 * scrolling on keeps flipping between them: down at the bottom turns forward,
 * up at the top turns back. Also: PageDown/PageUp, a swipe, or FlipButtons. On small or short screens (where
 * Home scrolls normally) the two screens simply stack, with no animation.
 */
export const FLIP_QUERY = "(min-width: 1101px) and (min-height: 701px)"; // = Home's one-screen layout
const FLIP_MS = 1200;          // matches the CSS: 600ms out, then 600ms in from 560ms
const REDUCED_MS = 320;
const WHEEL_MIN = 12;          // ignore tiny trackpad noise

function useMedia(query: string): boolean {
  const [match, setMatch] = useState(() => typeof window !== "undefined" && window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setMatch(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [query]);
  return match;
}

export function FlipPages({ pages, side, onSide }: {
  pages: [ReactNode, ReactNode]; side: 0 | 1; onSide: (s: 0 | 1) => void;
}) {
  const flipMode = useMedia(FLIP_QUERY);
  const reduced = useMedia("(prefers-reduced-motion: reduce)");
  const [anim, setAnim] = useState<"down" | "up" | null>(null);
  const shown = useRef(side);
  const nextDir = useRef<"down" | "up" | null>(null);  // set by scroll/swipe/keys; buttons go by page order
  const refs = [useRef<HTMLDivElement>(null), useRef<HTMLDivElement>(null)];

  // Animate whenever the side changes (wheel, keys, swipe or the top-bar buttons).
  // Layout effect: the animation classes land before the first paint of the new side.
  useLayoutEffect(() => {
    if (side === shown.current) return;
    const dir = nextDir.current ?? (side > shown.current ? "down" : "up");
    nextDir.current = null;
    shown.current = side;
    if (!flipMode) {
      refs[side].current?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
      return;
    }
    refs[side].current?.scrollTo({ top: 0 });
    setAnim(dir);
    const t = window.setTimeout(() => setAnim(null), reduced ? REDUCED_MS : FLIP_MS);
    return () => window.clearTimeout(t);
  }, [side, flipMode, reduced]); // eslint-disable-line react-hooks/exhaustive-deps

  // Turn to the other screen, in the direction of the scroll.
  const turn = useCallback((dir: "down" | "up") => {
    if (anim) return;
    nextDir.current = dir;
    onSide(side === 0 ? 1 : 0);
  }, [anim, side, onSide]);

  useEffect(() => {
    if (!flipMode) return;
    const page = () => refs[side].current;
    const atBottom = (el: HTMLElement) => el.scrollTop + el.clientHeight >= el.scrollHeight - 2;
    const onWheel = (e: WheelEvent) => {
      const el = page();
      if (!el || Math.abs(e.deltaY) < WHEEL_MIN) return;
      if (e.deltaY > 0 && atBottom(el)) turn("down");
      else if (e.deltaY < 0 && el.scrollTop <= 0) turn("up");
    };
    let startY: number | null = null;
    const onStart = (e: TouchEvent) => { startY = e.touches[0]?.clientY ?? null; };
    const onEnd = (e: TouchEvent) => {
      const el = page();
      const endY = e.changedTouches[0]?.clientY;
      if (!el || startY === null || endY === undefined) return;
      const dy = startY - endY;
      if (dy > 60 && atBottom(el)) turn("down");
      else if (dy < -60 && el.scrollTop <= 0) turn("up");
      startY = null;
    };
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      if (e.key === "PageDown") turn("down");
      if (e.key === "PageUp") turn("up");
    };
    window.addEventListener("wheel", onWheel, { passive: true });
    window.addEventListener("touchstart", onStart, { passive: true });
    window.addEventListener("touchend", onEnd, { passive: true });
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("wheel", onWheel);
      window.removeEventListener("touchstart", onStart);
      window.removeEventListener("touchend", onEnd);
      window.removeEventListener("keydown", onKey);
    };
  }, [flipMode, side, turn]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className={`flip-stage${flipMode ? " on" : ""}${anim ? ` flipping-${anim}` : ""}${reduced ? " reduced" : ""}`}>
      {pages.map((content, i) => {
        const current = i === side;
        const cls = !flipMode ? "" : current ? (anim ? " is-current flip-in" : " is-current") : anim ? " flip-out" : " is-away";
        return (
          <div key={i} ref={refs[i]} className={`flip-page${cls}`} aria-hidden={flipMode && !current ? true : undefined}>
            {content}
          </div>
        );
      })}
    </div>
  );
}

/** Overview / Detail switch for the top bar. */
export function FlipButtons({ side, onSide, labels }: {
  side: 0 | 1; onSide: (s: 0 | 1) => void; labels: [string, string];
}) {
  const host = useRef<HTMLDivElement>(null);
  useSlidingPill(host, "[aria-selected='true']", side);
  return (
    <div ref={host} className="seg glass" role="tablist" aria-label="Page">
      <span className="ng-pill" aria-hidden="true" />
      {labels.map((l, i) => (
        <button key={l} role="tab" aria-selected={side === i} className={side === i ? "on" : ""}
          onClick={() => onSide(i as 0 | 1)}>{l}</button>
      ))}
    </div>
  );
}
