/** Page frame for every DDG Finance screen (Night Glass v5): the full landscape
 *  photo on Home, "dusk" everywhere else, and one top bar with the logo lockup,
 *  the pill navigation, live status (a dot plus a word) and Brisbane time. */
import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation } from "wouter";
import { useFleetData } from "@/hooks/useFleetData";

const NAV = [
  { path: "/", label: "Home" },
  { path: "/league", label: "League" },
  { path: "/me", label: "Me vs bots" },
  { path: "/forex", label: "Forex" },
  { path: "/bench", label: "Research" },
  { path: "/controls", label: "Controls" },
];

const brisbane = (d: Date | string | number, opts: Intl.DateTimeFormatOptions) =>
  new Intl.DateTimeFormat("en-AU", { timeZone: "Australia/Brisbane", ...opts }).format(new Date(d));

export const bneTime = (iso?: string | null) =>
  iso ? brisbane(iso, { hour: "numeric", minute: "2-digit" }) : null;

export function Status({ tone, word }: { tone: "ok" | "late" | "problem" | "none"; word: string }) {
  return <span className="status"><span className={`dot ${tone === "ok" ? "" : tone}`} aria-hidden="true" />{word}</span>;
}

function Clock() {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(t);
  }, []);
  return (
    <span className="pill glass tab" title="Brisbane time (AEST, UTC+10)">
      <span className="clock-date">{brisbane(now, { weekday: "short", day: "numeric", month: "short" })},</span>
      {brisbane(now, { hour: "numeric", minute: "2-digit" })} · Brisbane
    </span>
  );
}

function TopBar({ actions }: { actions?: ReactNode }) {
  const [location] = useLocation();
  const { mktOpen, killTripped, killSwitchArmed, lastCycle, runnerStatus, runnerStatusError } = useFleetData();
  const verdict = runnerStatusError ? null : runnerStatus?.verdict ?? null;
  const runner = verdict === "ALIVE" ? { tone: "ok" as const, word: "Bots running" }
    : verdict === "STALE" ? { tone: "problem" as const, word: "Bots stale" }
      : verdict === "ABSENT" ? { tone: "problem" as const, word: "Bots stopped" }
        : { tone: "none" as const, word: "Bots: no data" };
  const kill = killTripped == null ? { tone: "none" as const, word: "Kill switch: no data" }
    : killTripped ? { tone: "problem" as const, word: "Kill switch tripped" }
      : killSwitchArmed ? { tone: "ok" as const, word: "Kill switch armed" }
        : { tone: "late" as const, word: "Kill switch report-only" };
  const active = (p: string) => (p === "/" ? location === "/" || location === "" : location.startsWith(p));
  return (
    <header className="topbar">
      <Link href="/" className="brand glass" aria-label="DDG Finance home">
        <img src={`${import.meta.env.BASE_URL}ddg-mark-white-256.png`} alt="" />
        <b>DDG</b><i aria-hidden="true" /><span>Finance</span>
      </Link>
      <nav className="nav glass" aria-label="Main">
        {NAV.map((n) => (
          <Link key={n.path} href={n.path} aria-current={active(n.path) ? "page" : undefined}>{n.label}</Link>
        ))}
        <a href={`${import.meta.env.BASE_URL}paper.html`} target="_blank" rel="noopener" title="The research paper: why three accounts, what the evidence is, how 2027 is judged">Paper</a>
      </nav>
      <div className="statuses glass" aria-label="Platform status">
        <span className="label">Paper accounts</span>
        <Status tone={runner.tone} word={runner.word} />
        <Status tone={kill.tone} word={kill.word} />
        <Status tone={mktOpen ? "ok" : "none"} word={mktOpen ? "US market open" : "US market closed"} />
        <span className="small tab synced">Synced {bneTime(lastCycle) ?? "—"}</span>
      </div>
      <span className="spacer" />
      {actions}
      <Clock />
    </header>
  );
}

// Phone (760 px and narrower, approved design 20 Nov, Apple HIG tab bar): the top
// pill navigation is hidden and these tabs sit at the bottom; "More" opens a
// sheet with the rest. Labels under icons, 44 pt targets, safe-area padding.
const TABS = [NAV[0], NAV[1], { ...NAV[2], label: "Me" }, NAV[3]];
const MORE = [...NAV.slice(4)];

function TabBar() {
  const [location] = useLocation();
  const [open, setOpen] = useState(false);
  const active = (p: string) => (p === "/" ? location === "/" || location === "" : location.startsWith(p));
  const moreActive = MORE.some((n) => active(n.path));
  return (<>
    {open && (
      <div className="sheet-backdrop" onClick={() => setOpen(false)}>
        <nav className="sheet glass" aria-label="More pages" onClick={(e) => e.stopPropagation()}>
          {MORE.map((n) => <Link key={n.path} href={n.path} onClick={() => setOpen(false)} aria-current={active(n.path) ? "page" : undefined}>{n.label}</Link>)}
          <a href={`${import.meta.env.BASE_URL}paper.html`} target="_blank" rel="noopener">Paper</a>
          <button className="btn" onClick={() => setOpen(false)}>Close</button>
        </nav>
      </div>
    )}
    <nav className="tabbar glass" aria-label="Main">
      {TABS.map((n) => <Link key={n.path} href={n.path} aria-current={active(n.path) ? "page" : undefined}>{n.label}</Link>)}
      <button aria-expanded={open} aria-current={moreActive ? "page" : undefined} onClick={() => setOpen((v) => !v)}>More</button>
    </nav>
  </>);
}

export function Shell({ home = false, fit = false, actions, children }: {
  home?: boolean; fit?: boolean; actions?: ReactNode; children: ReactNode;
}) {
  return (
    <div className={`ng-page ${home ? "photo" : "dusk"} ${fit ? "fit" : ""}`}>
      <div className="ng-wrap">
        <TopBar actions={actions} />
        {children}
      </div>
      <TabBar />
    </div>
  );
}
