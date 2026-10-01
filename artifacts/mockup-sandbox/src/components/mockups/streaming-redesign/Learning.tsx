import { useState } from "react";
import {
  ArrowDownRight,
  ArrowUpRight,
  BookOpen,
  Check,
  CircleDot,
  Database,
  Fingerprint,
  LockKeyhole,
  Radio,
  ShieldCheck,
  Trees,
} from "lucide-react";
import { useFleetEquity } from "../streaming-current/_shared/mockData";

const notes = [
  {
    id: "totals",
    index: "01",
    title: "Fleet totals",
    eyebrow: "SOURCE OF RECORD",
    text: "This view reads fleet totals from /fleet/equity. Missing values stay unavailable instead of being reconstructed here.",
    icon: Database,
    detailTitle: "One reported total. No inferred components.",
    detail:
      "The fleet total is displayed from the equity endpoint response. This surface does not sum bot-level values, fill gaps, or substitute a cached estimate when a value is absent.",
    evidence: "GET  /fleet/equity",
    state: "Reported value only",
  },
  {
    id: "identity",
    index: "02",
    title: "Bot identity",
    eyebrow: "CANONICAL ATTRIBUTION",
    text: "Known bot IDs use canonical labels. Journal rows without a bot ID remain unattributed.",
    icon: Fingerprint,
    detailTitle: "Identity follows the canonical registry.",
    detail:
      "Known IDs resolve to their canonical labels across the workspace. A journal record with no bot ID is kept unattributed; it is never assigned to a likely strategy.",
    evidence: "bot_id  →  canonical label",
    state: "Unmatched stays unattributed",
  },
  {
    id: "boundary",
    index: "03",
    title: "Read-only view",
    eyebrow: "SCOPE BOUNDARY",
    text: "These notes summarize operational data. This page does not edit strategy or risk settings.",
    icon: ShieldCheck,
    detailTitle: "Context, not a control surface.",
    detail:
      "Learning explains how dashboard data is presented. Strategy parameters, risk limits, and execution behavior remain outside this page and are not changed here.",
    evidence: "OPERATING NOTES  /  READ ONLY",
    state: "No strategy controls",
  },
];

export function Learning() {
  const { data } = useFleetEquity();
  const total = data?.fleet_total;
  const [activeNote, setActiveNote] = useState(notes[0].id);
  const active = notes.find((note) => note.id === activeNote) ?? notes[0];
  const ActiveIcon = active.icon;

  return (
    <main className="learn-shell">
      <style>{`
        .learn-shell {
          --ink: #eff3e9;
          --muted: #b8c6bc;
          --soft: #8fa59a;
          --line: rgba(227, 240, 229, .15);
          --glass: rgba(11, 25, 23, .66);
          position: relative;
          isolation: isolate;
          width: 100%;
          min-height: 100dvh;
          overflow: hidden;
          color: var(--ink);
          background: #13241f;
          font-family: "DM Sans", "Segoe UI", sans-serif;
        }
        .learn-shell * { box-sizing: border-box; }
        .learn-backdrop, .learn-shade, .learn-grain {
          position: absolute;
          inset: 0;
          pointer-events: none;
        }
        .learn-backdrop {
          z-index: -3;
          background-image: url("/__mockup/images/streaming-forest-atmosphere.jpg");
          background-size: cover;
          background-position: center 56%;
          opacity: .5;
          filter: saturate(.68);
          transform: scale(1.025);
        }
        .learn-shade {
          z-index: -2;
          background:
            linear-gradient(90deg, rgba(8, 21, 19, .88) 0%, rgba(9, 23, 20, .72) 48%, rgba(9, 22, 19, .77) 100%),
            linear-gradient(180deg, rgba(9, 20, 18, .18), rgba(8, 18, 17, .84));
        }
        .learn-grain {
          z-index: -1;
          opacity: .16;
          background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.88' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.16'/%3E%3C/svg%3E");
        }
        .learn-frame {
          width: min(1280px, 100%);
          min-height: 800px;
          margin: 0 auto;
          padding: 24px 42px 28px;
        }
        .learn-topbar {
          height: 50px;
          display: flex;
          justify-content: space-between;
          align-items: center;
          border-bottom: 1px solid var(--line);
        }
        .learn-brand, .learn-status, .learn-kicker, .learn-note-meta,
        .learn-evidence-label, .learn-state, .learn-foot {
          display: flex;
          align-items: center;
        }
        .learn-brand { gap: 10px; color: #e7eee4; }
        .learn-mark {
          width: 28px; height: 28px; display: grid; place-items: center;
          border: 1px solid rgba(214, 235, 216, .31); border-radius: 9px;
          background: rgba(221, 244, 222, .08); color: #c4dfc8;
        }
        .learn-brand-name {
          font: 600 12px/1 "Space Mono", monospace;
          letter-spacing: .15em; text-transform: uppercase;
        }
        .learn-brand-sub {
          margin-left: 8px; color: #94a99d; font: 10px/1 "Space Mono", monospace;
          letter-spacing: .1em;
        }
        .learn-status {
          gap: 8px; padding: 7px 11px; border: 1px solid rgba(202, 228, 205, .18);
          border-radius: 99px; color: #c5d8ca; background: rgba(12, 25, 22, .48);
          font: 10px/1 "Space Mono", monospace; letter-spacing: .1em;
        }
        .learn-status-dot {
          width: 6px; height: 6px; border-radius: 50%; background: #aecab0;
          box-shadow: 0 0 0 3px rgba(174, 202, 176, .12);
        }
        .learn-hero {
          display: grid; grid-template-columns: 1fr 330px; align-items: end;
          gap: 40px; padding: 32px 0 24px;
        }
        .learn-kicker {
          gap: 9px; color: #b6cdb9; font: 10px/1.2 "Space Mono", monospace;
          letter-spacing: .18em; text-transform: uppercase;
        }
        .learn-kicker-line { width: 25px; height: 1px; background: #99b89e; }
        .learn-title {
          margin: 13px 0 0; color: #f2f4ea; font: 500 40px/.98 "DM Sans", sans-serif;
          letter-spacing: -.045em;
        }
        .learn-intro {
          max-width: 590px; margin: 12px 0 0; color: #c1ccc2;
          font-size: 13px; line-height: 1.65;
        }
        .learn-total {
          position: relative; overflow: hidden; min-height: 120px; padding: 17px 20px 16px;
          border: 1px solid rgba(218, 234, 218, .2); border-radius: 17px;
          background: linear-gradient(135deg, rgba(219, 237, 216, .13), rgba(17, 37, 31, .64));
          box-shadow: inset 0 1px rgba(255,255,255,.13), 0 14px 36px rgba(0,0,0,.16);
          backdrop-filter: blur(20px);
        }
        .learn-total::after {
          content: ""; position: absolute; width: 135px; height: 135px; right: -36px; top: -62px;
          border: 1px solid rgba(202, 226, 203, .13); border-radius: 50%;
          box-shadow: 0 0 0 15px rgba(202,226,203,.025), 0 0 0 31px rgba(202,226,203,.02);
        }
        .learn-total-label {
          color: #afc4b5; font: 10px/1.3 "Space Mono", monospace; letter-spacing: .14em;
        }
        .learn-total-value {
          position: relative; z-index: 1; margin-top: 8px; color: #f2f5e9;
          font: 500 32px/1 "DM Sans", sans-serif; letter-spacing: -.04em;
        }
        .learn-total-foot {
          margin-top: 10px; color: #a9b9ad; font: 9px/1.3 "Space Mono", monospace;
          letter-spacing: .035em;
        }
        .learn-content {
          display: grid; grid-template-columns: 362px minmax(0, 1fr);
          gap: 16px; min-height: 438px;
        }
        .learn-panel {
          border: 1px solid rgba(219, 235, 219, .16); border-radius: 18px;
          background: var(--glass); box-shadow: inset 0 1px rgba(255,255,255,.07), 0 18px 48px rgba(0,0,0,.15);
          backdrop-filter: blur(22px);
        }
        .learn-nav { padding: 17px 12px 12px; }
        .learn-section-label {
          margin: 0 8px 11px; color: #91a89a; font: 9px/1.2 "Space Mono", monospace;
          letter-spacing: .16em; text-transform: uppercase;
        }
        .learn-note {
          position: relative; width: 100%; display: grid; grid-template-columns: 36px 1fr 15px;
          gap: 10px; align-items: start; padding: 13px 10px; text-align: left;
          border: 1px solid transparent; border-radius: 12px; color: inherit;
          background: transparent; cursor: pointer; transition: background .18s ease, border-color .18s ease, transform .18s ease;
        }
        .learn-note + .learn-note { margin-top: 4px; }
        .learn-note:hover { background: rgba(216, 237, 219, .055); transform: translateX(2px); }
        .learn-note.selected {
          border-color: rgba(194, 222, 197, .17);
          background: linear-gradient(100deg, rgba(176, 207, 179, .13), rgba(176, 207, 179, .035));
        }
        .learn-note-num {
          width: 33px; height: 33px; display: grid; place-items: center;
          border: 1px solid rgba(212, 232, 215, .15); border-radius: 10px;
          color: #a9c2ad; font: 10px "Space Mono", monospace;
        }
        .learn-note.selected .learn-note-num { background: rgba(202, 228, 202, .1); color: #e3eee2; }
        .learn-note-meta { gap: 7px; color: #90a699; font: 8px/1.1 "Space Mono", monospace; letter-spacing: .11em; }
        .learn-note-title { margin-top: 5px; color: #e8eee5; font-size: 13px; font-weight: 600; }
        .learn-note-copy { margin-top: 5px; color: #aebdb2; font-size: 10.5px; line-height: 1.55; }
        .learn-note-arrow { margin-top: 9px; color: #91aa97; }
        .learn-main { padding: 22px 26px; display: flex; flex-direction: column; }
        .learn-detail-head {
          display: flex; align-items: flex-start; gap: 14px; padding-bottom: 20px;
          border-bottom: 1px solid var(--line);
        }
        .learn-detail-icon {
          flex: none; width: 42px; height: 42px; display: grid; place-items: center;
          border: 1px solid rgba(204, 227, 207, .22); border-radius: 13px;
          background: rgba(205, 232, 207, .09); color: #c9ddca;
        }
        .learn-detail-overline { color: #94aa9a; font: 9px/1.3 "Space Mono", monospace; letter-spacing: .16em; }
        .learn-detail-title { margin: 7px 0 0; color: #eff3e9; font-size: 19px; line-height: 1.2; font-weight: 500; letter-spacing: -.025em; }
        .learn-detail-copy { max-width: 680px; margin: 9px 0 0; color: #b8c6ba; font-size: 12px; line-height: 1.65; }
        .learn-evidence {
          display: grid; grid-template-columns: minmax(0, 1fr) 205px; gap: 14px;
          margin-top: 17px; padding: 15px 16px; border: 1px solid rgba(215, 235, 216, .13);
          border-radius: 13px; background: rgba(5, 18, 16, .34);
        }
        .learn-evidence-label { gap: 7px; color: #91a99a; font: 8px/1.4 "Space Mono", monospace; letter-spacing: .12em; }
        .learn-evidence-value { margin-top: 8px; color: #e0e9df; font: 11px/1.5 "Space Mono", monospace; }
        .learn-evidence-caption { margin-top: 5px; color: #8da397; font-size: 10px; line-height: 1.4; }
        .learn-state { gap: 7px; align-self: center; color: #bdcfbf; font-size: 10px; line-height: 1.4; }
        .learn-state-icon { width: 7px; height: 7px; flex: none; border-radius: 50%; background: #a5c3a8; }
        .learn-rule {
          display: flex; align-items: center; gap: 12px; margin-top: auto; padding-top: 18px;
          color: #a0b3a3; font-size: 10px; line-height: 1.4;
        }
        .learn-rule-line { width: 27px; height: 1px; background: rgba(188, 215, 191, .44); }
        .learn-foot {
          justify-content: space-between; gap: 20px; margin-top: 15px; padding: 0 2px;
          color: #9bb0a1; font: 9px/1.4 "Space Mono", monospace; letter-spacing: .025em;
        }
        .learn-foot-left { display: flex; align-items: center; gap: 8px; }
        .learn-foot-right { color: #7e9887; text-align: right; }
        @media (max-width: 850px) {
          .learn-frame { min-height: 100dvh; padding: 18px 20px 24px; }
          .learn-hero { grid-template-columns: 1fr; gap: 19px; padding: 27px 0 19px; }
          .learn-total { max-width: 360px; min-height: 110px; }
          .learn-content { grid-template-columns: 1fr; }
          .learn-nav { padding: 14px 10px; }
          .learn-note { grid-template-columns: 34px 1fr 15px; }
          .learn-main { min-height: 300px; }
          .learn-foot { align-items: flex-start; flex-direction: column; }
        }
        @media (prefers-reduced-motion: reduce) {
          .learn-note { transition: none; }
        }
      `}</style>
      <div className="learn-backdrop" aria-hidden="true" />
      <div className="learn-shade" aria-hidden="true" />
      <div className="learn-grain" aria-hidden="true" />

      <div className="learn-frame">
        <header className="learn-topbar">
          <div className="learn-brand">
            <span className="learn-mark"><Trees size={15} strokeWidth={1.7} /></span>
            <span className="learn-brand-name">STREAMING</span>
            <span className="learn-brand-sub">OPERATIONS / FIELD NOTES</span>
          </div>
          <div className="learn-status"><span className="learn-status-dot" />READ ONLY</div>
        </header>

        <section className="learn-hero">
          <div>
            <div className="learn-kicker"><span className="learn-kicker-line" />A CLEAR VIEW OF THE SYSTEM</div>
            <h1 className="learn-title">Current operating notes</h1>
            <p className="learn-intro">
              A read-only reference for how fleet metrics, bot identity, and attribution are presented across the workspace.
            </p>
          </div>
          <div className="learn-total" aria-label="Fleet total equity">
            <div className="learn-total-label">FLEET TOTAL / EQUITY</div>
            <div className="learn-total-value">
              {total?.equity != null ? `$${Math.round(total.equity).toLocaleString()}` : "—"}
            </div>
            <div className="learn-total-foot">SOURCE · /fleet/equity</div>
          </div>
        </section>

        <section className="learn-content" aria-label="Current operating notes">
          <nav className="learn-panel learn-nav" aria-label="Note topics">
            <div className="learn-section-label">REFERENCE / 03 NOTES</div>
            {notes.map((note) => {
              const Icon = note.icon;
              const selected = activeNote === note.id;
              return (
                <button
                  key={note.id}
                  className={`learn-note${selected ? " selected" : ""}`}
                  type="button"
                  onClick={() => setActiveNote(note.id)}
                  aria-current={selected ? "true" : undefined}
                >
                  <span className="learn-note-num">{note.index}</span>
                  <span>
                    <span className="learn-note-meta"><Icon size={11} />{note.eyebrow}</span>
                    <span className="learn-note-title" style={{ display: "block" }}>{note.title}</span>
                    <span className="learn-note-copy" style={{ display: "block" }}>{note.text}</span>
                  </span>
                  <span className="learn-note-arrow">
                    {selected ? <ArrowDownRight size={14} /> : <ArrowUpRight size={13} />}
                  </span>
                </button>
              );
            })}
          </nav>

          <article className="learn-panel learn-main" aria-live="polite">
            <div className="learn-detail-head">
              <span className="learn-detail-icon"><ActiveIcon size={19} strokeWidth={1.65} /></span>
              <div>
                <div className="learn-detail-overline">{active.index} / {active.eyebrow}</div>
                <h2 className="learn-detail-title">{active.detailTitle}</h2>
                <p className="learn-detail-copy">{active.detail}</p>
              </div>
            </div>

            <div className="learn-evidence">
              <div>
                <div className="learn-evidence-label"><Radio size={12} />EVIDENCE PATH</div>
                <div className="learn-evidence-value">{active.evidence}</div>
                <div className="learn-evidence-caption">The displayed figure above preserves the reported fleet equity value.</div>
              </div>
              <div className="learn-state">
                <span className="learn-state-icon" />
                <span>{active.state}</span>
              </div>
            </div>

            <div className="learn-rule">
              <span className="learn-rule-line" />
              <LockKeyhole size={13} strokeWidth={1.6} />
              <span>Notes explain the data boundary; they do not change it.</span>
            </div>
          </article>
        </section>

        <footer className="learn-foot">
          <div className="learn-foot-left"><BookOpen size={12} strokeWidth={1.5} />LEARNING / OPERATIONAL CONTEXT</div>
          <div className="learn-foot-right"><Check size={11} style={{ verticalAlign: "-2px", marginRight: 6 }} />Values are shown as reported; unavailable stays unavailable.</div>
        </footer>
      </div>
    </main>
  );
}