/** Night Glass motion for DDG Finance (DDG_Control docs/brand/night-glass.md, section 10).
 *  Finance is the calmest DDG product: things you touch may slide, numbers and money
 *  only ease in (no bounce), loaders loop only while waiting, and "reduce motion"
 *  turns every duration token into 1 ms (styles/night-glass/tokens.css), so all
 *  of this obeys it without extra code. Timings come from the --ng-dur-* tokens only. */
import { useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";

const css = (name: string) =>
  typeof window === "undefined" ? "" : getComputedStyle(document.documentElement).getPropertyValue(name).trim();
/** A duration token in ms ("base" → --ng-dur-base). The build's CSS minifier may
 *  rewrite 320ms as .32s, so both units are read. */
export const dur = (name: "instant" | "quick" | "base" | "slow" | "story") => {
  const v = css(`--ng-dur-${name}`);
  const n = parseFloat(v);
  if (!Number.isFinite(n)) return 1;
  return v.endsWith("ms") ? n : v.endsWith("s") ? n * 1000 : n;
};
/** How long a "done" tick stays before the control goes back to rest. */
const HOLD_MS = 1400;

/** Runs a Web Animation on the motion tokens. Browsers that reject a token's
 *  easing (linear() is newer) get plain "ease". */
export function play(el: Element, frames: Keyframe[], d: Parameters<typeof dur>[0], ease: "out" | "in" | "move" | "spring" | "elastic") {
  const opts: KeyframeAnimationOptions = { duration: dur(d), easing: css(`--ng-ease-${ease}`) || "ease" };
  try { return el.animate(frames, opts); } catch { return el.animate(frames, { ...opts, easing: "ease" }); }
}

// ── Sliding pill (Gooey Tab Bar / Leaf Tabs / Worm Dots) ─────────────────────
type Box = { x: number; y: number; w: number; h: number };
const remembered = new Map<string, Box>();   // the top bar remounts on every page; it remembers where the pill was

/** Moves the host's `.ng-pill` child under the element matching `selector`.
 *  When the choice changes, the pill stretches across the gap and lands. `key`
 *  is the current choice; `remember` keeps the position across remounts. */
export function useSlidingPill(host: RefObject<HTMLElement | null>, selector: string, key: unknown,
  opts: { remember?: string; fit?: (b: Box) => Box } = {}) {
  const last = useRef<Box | null>(opts.remember ? remembered.get(opts.remember) ?? null : null);
  useLayoutEffect(() => {
    const el = host.current;
    const pill = el?.querySelector<HTMLElement>(":scope > .ng-pill");
    if (!el || !pill) return;
    const place = (from: Box | null) => {
      const active = el.querySelector<HTMLElement>(selector);
      if (!active || !active.offsetWidth) { el.classList.remove("has-pill"); return; }
      const r = active.getBoundingClientRect(), h = el.getBoundingClientRect();
      let to: Box = { x: r.left - h.left - el.clientLeft, y: r.top - h.top - el.clientTop, w: r.width, h: r.height };
      if (opts.fit) to = opts.fit(to);
      pill.style.transform = `translate(${to.x}px, ${to.y}px)`;
      pill.style.width = `${to.w}px`;
      pill.style.height = `${to.h}px`;
      el.classList.add("has-pill");
      if (from && (Math.abs(from.x - to.x) > 1 || Math.abs(from.y - to.y) > 1)) {
        const l = Math.min(from.x, to.x), rr = Math.max(from.x + from.w, to.x + to.w), inset = Math.min(from.w, to.w) * 0.2;
        play(pill, [
          { transform: `translate(${from.x}px, ${from.y}px)`, width: `${from.w}px`, height: `${from.h}px` },
          { transform: `translate(${l + inset}px, ${(from.y + to.y) / 2}px)`, width: `${rr - l - 2 * inset}px`, offset: 0.5 },
          { transform: `translate(${to.x}px, ${to.y}px)`, width: `${to.w}px`, height: `${to.h}px` },
        ], "base", "move");
      }
      last.current = to;
      if (opts.remember) remembered.set(opts.remember, to);
    };
    place(last.current);
    const ro = new ResizeObserver(() => place(null));   // window or font changes: move without animating
    ro.observe(el);
    return () => ro.disconnect();
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
}

// ── Numbers ease in when they change (no bounce: money never bounces) ───────
/** Re-plays a short settle when `value` changes after the first render. */
export function Settle({ value }: { value: string | null | undefined }) {
  const first = useRef(value);
  const shown = value ?? "—";
  return <span key={shown} className={value !== first.current ? "ng-settle" : undefined}>{shown}</span>;
}

// ── Loaders: only while waiting ─────────────────────────────────────────────
/** Small loader for inside buttons and table cells (01 Bars Fade). */
export const Bars = () => <span className="ng-bars" aria-hidden="true"><i /><i /><i /></span>;

/** The standard loader with its words (36 Dot Revolve). */
export function Loading({ children }: { children: ReactNode }) {
  return (
    <span className="ng-loading" role="status">
      <svg className="ng-revolve" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r="6" fill="none" stroke="rgba(255,255,255,0.18)" strokeWidth="2" />
        <circle cx="8" cy="2" r="2" fill="#fff" />
      </svg>
      {children}
    </span>
  );
}

/** A tick that draws itself once, beside a "done" message (33 Checklist). */
export const DoneTick = () => (
  <svg className="ng-tick" width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
    <path d="m5 12.5 4.5 4.5L19 7.5" pathLength={1} fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

// ── Download (21 Download Ring) ─────────────────────────────────────────────
/** The button folds into a ring while the file is prepared, shows a tick when
 *  it is saved, then opens back out. Progress is unknown, so the ring turns
 *  rather than fills. `run` resolves true when the file was saved. */
export function DownloadButton({ run, icon, label, title, className = "" }: {
  run: () => Promise<boolean>; icon: ReactNode; label: string; title: string; className?: string;
}) {
  const ref = useRef<HTMLButtonElement>(null);
  const wide = useRef(0);
  const [state, setState] = useState<"idle" | "busy" | "done">("idle");
  const [said, setSaid] = useState("");
  useLayoutEffect(() => {
    const b = ref.current;
    if (!b || !wide.current) return;
    if (state !== "idle") { b.style.width = `${b.offsetHeight}px`; return; }
    b.style.width = `${wide.current}px`;                          // open back out, then let it size itself
    const t = window.setTimeout(() => { b.style.width = ""; }, dur("base"));
    return () => window.clearTimeout(t);
  }, [state]);
  const go = async () => {
    const b = ref.current;
    if (!b || state !== "idle") return;
    wide.current = b.offsetWidth;
    b.style.width = `${wide.current}px`;
    void b.offsetWidth;                                            // start the fold from the measured width
    setState("busy"); setSaid(`Preparing the ${label.toLowerCase()}`);
    const ok = await run();
    setSaid(ok ? `${label} downloaded` : `${label} not downloaded`);
    if (!ok) { setState("idle"); return; }
    setState("done");
    window.setTimeout(() => setState("idle"), HOLD_MS);
  };
  return (
    <button ref={ref} className={`btn ng-dl ${state} ${className}`} onClick={go} title={title}
      aria-label={state === "idle" ? undefined : said} aria-busy={state === "busy"}>
      <span className="ng-dl-label">{icon} <span className="btn-text">{label}</span></span>
      {state === "busy" && <svg className="ng-revolve ng-dl-ring" width="22" height="22" viewBox="0 0 22 22" aria-hidden="true">
        <circle cx="11" cy="11" r="9" fill="none" stroke="rgba(255,255,255,0.18)" strokeWidth="2.5" />
        <path d="M11 2a9 9 0 0 1 9 9" fill="none" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" /></svg>}
      {state === "done" && <span className="ng-dl-done"><DoneTick /></span>}
      <span className="ng-sr" aria-live="polite">{said}</span>
    </button>
  );
}

// ── Pager for side-scrolling cards (20 Worm Dots) ───────────────────────────
/** Dots under a row of cards that scrolls sideways (phones). Shows which card
 *  is in view; tapping a dot scrolls to that card. */
export function CardPager({ target, names, label }: { target: RefObject<HTMLElement | null>; names: string[]; label: string }) {
  const host = useRef<HTMLDivElement>(null);
  const [at, setAt] = useState(0);
  useLayoutEffect(() => {
    const el = target.current;
    if (!el) return;
    const onScroll = () => {
      const cards = el.children;
      const step = cards.length > 1 ? (cards[1] as HTMLElement).offsetLeft - (cards[0] as HTMLElement).offsetLeft : 0;
      if (step > 0) setAt(Math.max(0, Math.min(names.length - 1, Math.round(el.scrollLeft / step))));
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [target, names.length]);
  useSlidingPill(host, "[aria-current='true']", `${at}/${names.length}`, { fit: (b) => ({ x: b.x + b.w / 2 - 10, y: b.y + b.h / 2 - 4, w: 20, h: 8 }) });
  const show = (i: number) => {
    const el = target.current;
    const card = el?.children[i] as HTMLElement | undefined;
    if (!el || !card) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollTo({ left: card.offsetLeft - (el.children[0] as HTMLElement).offsetLeft, behavior: reduce ? "auto" : "smooth" });
  };
  if (names.length < 2) return null;
  return (
    <div ref={host} className="card-pager" role="group" aria-label={label}>
      <span className="ng-pill" aria-hidden="true" />
      {names.map((n, i) => (
        <button key={n} aria-label={`Show ${n}`} aria-current={i === at ? "true" : undefined} onClick={() => show(i)} />
      ))}
    </div>
  );
}
