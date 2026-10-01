import { useEffect, useState } from "react";
import { Activity, AudioLines, BrainCircuit, CircleDot, Waves } from "lucide-react";
import { AIBrainVisual } from "../streaming-current/_shared/AIBrainVisual";

const contextLabels = ["FLEET OVERVIEW", "SIGNAL ANALYSIS", "TRADE REVIEW"];

export function Live() {
  const [contextIndex, setContextIndex] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setContextIndex((current) => (current + 1) % contextLabels.length);
    }, 3000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <main className="live-ops">
      <style>{`
        .live-ops {
          --ink: #eef4ed;
          --muted: rgba(222, 233, 222, .63);
          --line: rgba(222, 241, 225, .17);
          --glass: rgba(14, 31, 28, .58);
          position: relative;
          isolation: isolate;
          width: 100%;
          height: 100%;
          min-height: 100dvh;
          box-sizing: border-box;
          overflow: hidden;
          padding: 25px 38px 22px;
          color: var(--ink);
          font-family: 'DM Sans', 'Avenir Next', sans-serif;
          background: #10211d url('/__mockup/images/streaming-forest-atmosphere.jpg') center 46% / cover no-repeat;
        }
        .live-ops *, .live-ops *::before, .live-ops *::after { box-sizing: border-box; }
        .live-ops::before {
          content: '';
          position: absolute;
          inset: 0;
          z-index: -1;
          background:
            linear-gradient(105deg, rgba(5, 20, 18, .84) 0%, rgba(7, 22, 20, .55) 47%, rgba(8, 18, 17, .72) 100%),
            linear-gradient(180deg, rgba(8, 20, 18, .38), rgba(6, 17, 16, .73));
        }
        .live-ops::after {
          content: '';
          position: absolute;
          inset: 0;
          pointer-events: none;
          opacity: .18;
          z-index: 5;
          background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.84' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.18'/%3E%3C/svg%3E");
          mix-blend-mode: soft-light;
        }
        .live-topbar {
          height: 54px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          position: relative;
          z-index: 2;
          margin-bottom: 13px;
        }
        .live-brand {
          display: flex;
          align-items: center;
          gap: 13px;
        }
        .live-mark {
          display: grid;
          place-items: center;
          width: 40px;
          height: 40px;
          color: #c8e0bd;
          border: 1px solid rgba(203, 228, 197, .28);
          border-radius: 13px;
          background: rgba(22, 44, 37, .62);
          box-shadow: inset 0 1px 0 rgba(255,255,255,.12), 0 8px 24px rgba(1,10,8,.18);
          backdrop-filter: blur(18px);
        }
        .live-eyebrow {
          color: rgba(208, 225, 208, .58);
          font-family: 'Space Mono', monospace;
          font-size: 9px;
          letter-spacing: .2em;
          line-height: 1.5;
        }
        .live-title {
          margin: 1px 0 0;
          color: #f0f4eb;
          font-size: 19px;
          font-weight: 550;
          letter-spacing: -.035em;
          line-height: 1.12;
        }
        .live-state {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 10px 14px;
          border: 1px solid rgba(197, 234, 199, .21);
          border-radius: 999px;
          color: #e0ebdd;
          background: rgba(12, 30, 26, .58);
          box-shadow: inset 0 1px 0 rgba(255,255,255,.1);
          backdrop-filter: blur(20px);
          font-family: 'Space Mono', monospace;
          font-size: 10px;
          letter-spacing: .13em;
        }
        .live-dot {
          width: 7px;
          height: 7px;
          border-radius: 50%;
          background: #b7e4a9;
          box-shadow: 0 0 0 4px rgba(183, 228, 169, .12), 0 0 15px rgba(183, 228, 169, .62);
          animation: live-breathe 2.4s ease-in-out infinite;
        }
        .live-stage {
          position: relative;
          z-index: 1;
          height: calc(100% - 54px - 13px - 43px - 15px);
          min-height: 450px;
          overflow: hidden;
          border: 1px solid rgba(226, 241, 224, .2);
          border-radius: 24px;
          background: linear-gradient(145deg, rgba(21, 42, 37, .39), rgba(7, 20, 19, .55));
          box-shadow:
            inset 0 1px 0 rgba(255,255,255,.13),
            0 24px 80px rgba(1, 9, 8, .24);
          backdrop-filter: blur(18px) saturate(.86);
        }
        .live-stage::before {
          content: '';
          position: absolute;
          inset: 0;
          pointer-events: none;
          z-index: 1;
          background:
            radial-gradient(ellipse at 50% 44%, rgba(23, 44, 40, .03), rgba(4, 16, 15, .18) 70%),
            linear-gradient(180deg, rgba(11, 25, 23, .27), transparent 25%, transparent 72%, rgba(4, 16, 15, .4));
        }
        .live-stage-head {
          position: absolute;
          top: 19px;
          left: 23px;
          right: 23px;
          z-index: 3;
          display: flex;
          justify-content: space-between;
          align-items: center;
          pointer-events: none;
        }
        .stage-caption {
          display: flex;
          align-items: center;
          gap: 9px;
          color: rgba(227, 237, 223, .78);
          font-family: 'Space Mono', monospace;
          font-size: 9px;
          letter-spacing: .17em;
        }
        .stage-caption svg { color: #c6d9b7; }
        .stage-mode {
          color: rgba(229, 237, 225, .5);
          font-family: 'Space Mono', monospace;
          font-size: 9px;
          letter-spacing: .14em;
        }
        .brain-layer {
          position: absolute;
          inset: 0;
          z-index: 0;
          overflow: hidden;
          opacity: .88;
          mix-blend-mode: screen;
        }
        .brain-layer > div {
          width: 100%;
          height: 100%;
          background: transparent !important;
        }
        .brain-layer svg { display: block; }
        .live-context {
          position: absolute;
          z-index: 3;
          left: 50%;
          bottom: 21px;
          transform: translateX(-50%);
          display: flex;
          align-items: center;
          gap: 12px;
          min-width: 270px;
          justify-content: center;
          padding: 10px 18px;
          border: 1px solid rgba(218, 237, 215, .19);
          border-radius: 999px;
          color: #dcebd9;
          background: rgba(10, 25, 22, .76);
          box-shadow: inset 0 1px 0 rgba(255,255,255,.1), 0 8px 22px rgba(0,0,0,.17);
          backdrop-filter: blur(20px);
          font: 10px 'Space Mono', monospace;
          letter-spacing: .17em;
          transition: opacity .35s ease;
          white-space: nowrap;
        }
        .live-context svg { color: #bfdcae; }
        .live-footer {
          position: relative;
          z-index: 2;
          height: 43px;
          display: flex;
          justify-content: space-between;
          align-items: flex-end;
          padding-top: 14px;
        }
        .live-legend {
          display: flex;
          align-items: center;
          gap: 24px;
          color: var(--muted);
          font-family: 'Space Mono', monospace;
          font-size: 9px;
          letter-spacing: .12em;
        }
        .live-legend span {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .legend-line {
          width: 16px;
          height: 1px;
          background: rgba(197, 222, 188, .72);
        }
        .legend-line.violet { background: rgba(190, 177, 235, .78); }
        .live-credit {
          padding: 7px 10px 7px 11px;
          color: rgba(223, 234, 221, .69);
          border: 1px solid rgba(224, 239, 220, .15);
          border-left: 2px solid #b2d69e;
          border-radius: 8px;
          background: rgba(8, 23, 20, .54);
          backdrop-filter: blur(14px);
          font: 9px 'Space Mono', monospace;
          letter-spacing: .08em;
        }
        .live-credit strong { color: #edf3e9; font-weight: 600; }
        @keyframes live-breathe {
          0%, 100% { opacity: .78; transform: scale(.9); }
          50% { opacity: 1; transform: scale(1.08); }
        }
        @media (max-width: 760px) {
          .live-ops { min-height: 100dvh; padding: 20px 16px; overflow: auto; }
          .live-title { font-size: 16px; }
          .live-stage { height: calc(100dvh - 158px); min-height: 490px; border-radius: 18px; }
          .live-stage-head { top: 15px; left: 14px; right: 14px; }
          .stage-mode { display: none; }
          .live-context { bottom: 15px; min-width: 0; }
          .live-footer { height: auto; gap: 12px; align-items: flex-start; flex-direction: column; }
          .live-legend { gap: 12px; flex-wrap: wrap; }
        }
      `}</style>

      <header className="live-topbar">
        <div className="live-brand">
          <div className="live-mark"><BrainCircuit size={19} strokeWidth={1.45} /></div>
          <div>
            <div className="live-eyebrow">DIGITAL DYNAMICS GROUP&nbsp; / &nbsp;STREAMING</div>
            <h1 className="live-title">Live operations</h1>
          </div>
        </div>
        <div className="live-state" aria-label="Live stream active">
          <span className="live-dot" />
          STREAM ACTIVE
          <Activity size={13} strokeWidth={1.7} />
        </div>
      </header>

      <section className="live-stage" aria-label="Animated AI neural signal">
        <div className="brain-layer"><AIBrainVisual /></div>
        <div className="live-stage-head">
          <div className="stage-caption"><Waves size={14} /> ALWAYS-ON AI OPERATIONS</div>
          <div className="stage-mode">NEURAL SIGNAL&nbsp; / &nbsp;LIVE VIEW</div>
        </div>
        <div className="live-context" aria-live="polite">
          <CircleDot size={13} strokeWidth={1.6} />
          <span>{contextLabels[contextIndex]}</span>
          <AudioLines size={14} strokeWidth={1.5} />
        </div>
      </section>

      <footer className="live-footer">
        <div className="live-legend" aria-label="Neural signal context">
          <span><i className="legend-line" /> SIGNAL ANALYSIS</span>
          <span><i className="legend-line violet" /> TRADE REVIEW</span>
        </div>
        <div className="live-credit">POWERED BY&nbsp; <strong>DIGITAL DYNAMICS</strong>&nbsp; GROUP</div>
      </footer>
    </main>
  );
}