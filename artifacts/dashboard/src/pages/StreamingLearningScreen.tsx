import { useState } from "react";
import { ArrowUpRight, HelpCircle, Leaf } from "lucide-react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useFleetEquity } from "@/hooks/use-portfolio";

const NOTE_ITEMS = [
  {
    id: "portfolio-principle",
    label: "Portfolio principle",
    category: "CAPITAL ALLOCATION",
    text: "Diversification across distinct strategies can reduce portfolio-level dependence on any single signal.",
    detail: "The fleet allocation view reports current capital and strategy-level exposure.",
    source: "PORTFOLIO / FLEET EQUITY",
  },
  {
    id: "risk-principle",
    label: "Risk principle",
    category: "RISK MANAGEMENT",
    text: "Position sizing should account for both conviction and the risk budget available to the strategy.",
    detail: "Current live positions expose the recorded conviction and position sizing fields.",
    source: "POSITIONS / LIVE",
  },
  {
    id: "review-principle",
    label: "Review principle",
    category: "PERFORMANCE REVIEW",
    text: "Reviewing closed trades alongside their recorded thesis helps keep strategy decisions auditable.",
    detail: "The journal stores the trade result and the original thesis where supplied.",
    source: "JOURNAL / TRADES",
  },
  {
    id: "audit-principle",
    label: "Audit principle",
    category: "QUANTITATIVE CHECKS",
    text: "Risk metrics should be compared with their stated definitions before they are interpreted.",
    detail: "The math audit endpoint reports its own checks and outcomes; this view does not recompute them.",
    source: "ADMIN / MATH AUDIT",
  },
];

export default function StreamingLearningScreen() {
  const [selectedNote, setSelectedNote] = useState("portfolio-principle");
  const equity = useFleetEquity();
  const activeNote = NOTE_ITEMS.find((item) => item.id === selectedNote) ?? NOTE_ITEMS[0];
  const total = equity.data?.fleet_total;
  const updatedAt = equity.data?.generated_at ? new Date(equity.data.generated_at) : null;
  const updatedLabel = updatedAt && !Number.isNaN(updatedAt.getTime())
    ? updatedAt.toLocaleTimeString()
    : null;

  return (
    <div className="stream-screen stream-screen-learning learn-shell">
      <style>{`
        .learn-shell,.learn-shell *{box-sizing:border-box}
        .learn-shell{height:100%;min-height:620px;position:relative;isolation:isolate;overflow:auto;color:#edf2e9;background:transparent;font-family:"DM Sans","Avenir Next",ui-sans-serif,system-ui,sans-serif;letter-spacing:-.01em}
        .learn-shell:before{display:none}
        .learn-header{height:64px;padding:0 clamp(20px,4vw,58px);display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid rgba(229,239,225,.12);background:rgba(10,22,19,.48);backdrop-filter:blur(22px)}
        .learn-brand,.learn-header-meta,.learn-total-label,.learn-total-foot{display:flex;align-items:center}
        .learn-brand{gap:12px}.learn-brand-mark{width:32px;height:32px;display:grid;place-items:center;border:1px solid rgba(193,231,202,.28);border-radius:10px;background:rgba(184,223,194,.10);color:#c8e8cc;font:600 13px "Geist Mono",monospace}
        .learn-brand-name{font-size:11px;font-weight:700;letter-spacing:.17em;text-transform:uppercase}.learn-brand-divider{color:#718274}.learn-brand-section{color:#b4c5b4;font-size:11px}
        .learn-header-meta{gap:9px;color:#aab7aa;font-size:10px}.learn-live-dot,.learn-total-mark{width:7px;height:7px;border-radius:50%;background:#a9ddb7;box-shadow:0 0 12px rgba(169,221,183,.55)}.learn-live-dot.is-error{background:#dfaa86;box-shadow:0 0 10px rgba(223,170,134,.4)}.learn-live-dot.is-loading{background:#a8bbac;box-shadow:none}.learn-meta-divider{height:16px;width:1px;margin:0 7px;background:rgba(218,232,216,.18)}
        .learn-main{width:min(1020px,calc(100% - 48px));min-height:calc(100% - 112px);margin:0 auto;padding:clamp(28px,5vh,58px) 0 30px;display:flex;flex-direction:column;justify-content:center}
        .learn-intro{max-width:640px;margin-bottom:30px}.learn-kicker,.learn-section-kicker{color:#b3d0b4;font-size:9px;font-weight:700;letter-spacing:.18em;text-transform:uppercase}.learn-kicker span{margin-right:9px;color:#d6e8d4}
        .learn-intro h1{margin:11px 0 9px;color:#f1f4ec;font:500 clamp(29px,4vw,42px)/1.05 "DM Sans",sans-serif;letter-spacing:-.055em}.learn-intro p{max-width:560px;margin:0;color:#b1beb1;font-size:12px;line-height:1.65}
        .learn-board,.learn-total{border:1px solid rgba(218,232,216,.14);background:linear-gradient(135deg,rgba(31,48,41,.78),rgba(14,27,24,.77));backdrop-filter:blur(22px) saturate(115%);box-shadow:0 16px 42px rgba(2,12,10,.22),inset 0 1px rgba(245,255,244,.06)}
        .learn-board{overflow:hidden;border-radius:15px}.learn-board-heading{min-height:66px;padding:14px 20px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid rgba(218,232,216,.10)}
        .learn-board-heading h2{margin:4px 0 0;color:#e8eee4;font-size:14px;font-weight:600}.learn-board-count{padding:6px 9px;border:1px solid rgba(183,219,187,.13);border-radius:7px;color:#a7b8a7;font:9px "Geist Mono",monospace;letter-spacing:.06em}
        .learn-board-content{display:grid;grid-template-columns:minmax(230px,.8fr) minmax(0,1.5fr);min-height:250px}
        .learn-notes{padding:11px;border-right:1px solid rgba(218,232,216,.10);display:flex;flex-direction:column;gap:5px}
        .learn-note{width:100%;min-height:50px;padding:8px 10px;display:flex;align-items:center;gap:11px;border:1px solid transparent;border-radius:9px;background:transparent;color:inherit;text-align:left;cursor:pointer;transition:.2s}
        .learn-note:hover,.learn-note.is-selected{border-color:rgba(195,223,194,.2);background:rgba(195,223,194,.075)}.learn-note-index{color:#829787;font:10px "Geist Mono",monospace}
        .learn-note-copy{min-width:0;flex:1;display:flex;flex-direction:column;gap:3px}.learn-note-label{color:#dce5da;font-size:11px;font-weight:600}.learn-note-category{color:#8fa091;font-size:8px;letter-spacing:.1em}
        .learn-note-indicator{width:6px;height:6px;border-radius:50%;background:transparent}.learn-note.is-selected .learn-note-indicator{background:#b5debd;box-shadow:0 0 10px rgba(181,222,189,.6)}
        .learn-detail{padding:24px 26px;display:flex;flex-direction:column}.learn-detail-top,.learn-detail-foot{display:flex;justify-content:space-between;gap:14px}
        .learn-detail-category{color:#b6d9bb;font-size:9px;font-weight:700;letter-spacing:.12em}.learn-detail-index{color:#819183;font:8px "Geist Mono",monospace}
        .learn-detail h2{margin:17px 0 8px;color:#edf3e9;font-size:19px;font-weight:550;letter-spacing:-.035em}.learn-detail-copy{max-width:520px;margin:0;color:#bdc9bc;font-size:13px;line-height:1.7}
        .learn-detail-foot{margin-top:auto;padding-top:23px;color:#829184;font-size:8px;letter-spacing:.11em}.learn-detail-foot span:last-child{color:#adc2ae;font-family:"Geist Mono",monospace}
        .learn-detail-caption{margin:8px 0 0;color:#89998d;font-size:10px;line-height:1.5}
        .learn-total{position:relative;min-height:126px;margin-top:13px;padding:18px 22px;border-radius:14px;display:grid;grid-template-columns:1fr auto;align-items:center}
        .learn-total-label{gap:9px;color:#becabe;font-size:10px;letter-spacing:.035em}.learn-total-mark{width:6px;height:6px}.learn-total-value{grid-column:1;font:500 31px/1 "Geist Mono",monospace;color:#e0eddd;letter-spacing:-.075em}
        .learn-total-foot{grid-column:1;gap:12px;margin-top:6px;color:#849486;font-size:8px;letter-spacing:.04em}.learn-total-foot span:first-child{color:#a6c7ab}
        .learn-total-info{grid-column:2;grid-row:1/4;width:36px;height:36px;display:grid;place-items:center;border:1px solid rgba(218,232,216,.14);border-radius:10px;background:rgba(226,239,223,.05);color:#b7d4ba;cursor:pointer}
        .learn-total-info:hover{background:rgba(226,239,223,.11);color:#e1f0df}.learn-source-state{color:#d8c18e}
        .learn-footer{min-height:48px;padding:8px clamp(20px,4vw,58px);display:flex;align-items:center;justify-content:space-between;gap:10px;border-top:1px solid rgba(218,232,216,.1);color:#8f9e92;font-size:8px;letter-spacing:.09em;background:rgba(10,22,19,.38)}
        .learn-footer span:first-child{color:#b3d0b4;font-weight:700}
        @media(max-width:680px){.learn-shell{min-height:700px}.learn-main{width:calc(100% - 28px);padding:24px 0}.learn-board-content{grid-template-columns:1fr}.learn-notes{border-right:0;border-bottom:1px solid rgba(218,232,216,.1);display:grid;grid-template-columns:1fr 1fr}.learn-note{padding:7px}.learn-note-category{font-size:7px}.learn-detail{min-height:200px;padding:19px}.learn-total{padding:16px}.learn-footer{align-items:flex-start;flex-direction:column;justify-content:center}.learn-header-meta{font-size:9px}}
        @media(prefers-reduced-motion:reduce){.learn-note,.learn-total-info{transition:none}}
      `}</style>
      <header className="learn-header">
        <div className="learn-brand">
          <span className="learn-brand-mark"><Leaf size={15} /></span>
          <span className="learn-brand-name">Neural</span>
          <span className="learn-brand-divider">/</span>
          <span className="learn-brand-section">Learning</span>
        </div>
        <div className="learn-header-meta" data-testid="learning-source-status" aria-live="polite">
          <span className={`learn-live-dot ${equity.isError ? "is-error" : equity.isLoading ? "is-loading" : ""}`} />
          <span>{equity.isLoading ? "Loading fleet equity" : equity.isError ? "Equity source unavailable" : "Reference notes"}</span>
          <span className="learn-meta-divider" />
          <span>/fleet/equity</span>
        </div>
      </header>
      <main className="learn-main">
        <section className="learn-intro">
          <div className="learn-kicker"><span>01</span> SYSTEM KNOWLEDGE</div>
          <h1>Learning, made visible.</h1>
          <p>A quiet view of the principles behind the fleet — with current equity reported separately from explanatory context.</p>
        </section>
        <section className="learn-board" aria-label="Learning principles">
          <div className="learn-board-heading">
            <div><span className="learn-section-kicker">REFERENCE NOTES</span><h2>Portfolio context</h2></div>
            <span className="learn-board-count">04 NOTES</span>
          </div>
          <div className="learn-board-content">
            <nav className="learn-notes" aria-label="Select a learning note">
              {NOTE_ITEMS.map((note, index) => (
                <button
                  type="button"
                  key={note.id}
                  onClick={() => setSelectedNote(note.id)}
                  className={`learn-note ${selectedNote === note.id ? "is-selected" : ""}`}
                  aria-current={selectedNote === note.id ? "true" : undefined}
                  data-testid={`learning-note-${note.id}`}
                >
                  <span className="learn-note-index">0{index + 1}</span>
                  <span className="learn-note-copy"><span className="learn-note-label">{note.label}</span><span className="learn-note-category">{note.category}</span></span>
                  <span className="learn-note-indicator" />
                </button>
              ))}
            </nav>
            <article className="learn-detail" aria-live="polite">
              <div className="learn-detail-top"><span className="learn-detail-category">{activeNote.category}</span><span className="learn-detail-index">{activeNote.id.toUpperCase()}</span></div>
              <h2>{activeNote.label}</h2>
              <p className="learn-detail-copy">{activeNote.text}</p>
              <div className="learn-detail-foot"><span>DATA REFERENCE</span><span>{activeNote.source}</span></div>
              <p className="learn-detail-caption">{activeNote.detail}</p>
            </article>
          </div>
        </section>
        <section className="learn-total" aria-label="Current reported fleet equity">
          <div className="learn-total-label"><span className="learn-total-mark" /><span>Reported fleet equity</span></div>
          <div className="learn-total-value" data-testid="learning-fleet-equity" aria-live="polite">
            {equity.isLoading && !total ? "Loading…" : equity.isError && !total ? "Unavailable" : total ? `$${Math.round(total.equity).toLocaleString()}` : "—"}
          </div>
          <div className="learn-total-foot">
            <span>FLEET EQUITY API</span>
            <span className={equity.isError ? "learn-source-state" : ""}>
              {equity.isError && total
                ? "Refresh failed · showing last response"
                : equity.isError
                  ? "Source unavailable"
                  : total
                    ? `${total.positions} positions${updatedLabel ? ` · updated ${updatedLabel}` : ""}`
                    : equity.isLoading
                      ? "Awaiting source response"
                      : "No equity value reported"}
            </span>
          </div>
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <button type="button" className="learn-total-info" aria-label="About the reported equity value" data-testid="learning-equity-info">
                  <HelpCircle size={16} /><span className="sr-only">About the reported equity value</span>
                </button>
              </TooltipTrigger>
              <TooltipContent><p>Reported by the fleet equity endpoint. This page does not infer missing values.</p></TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </section>
      </main>
      <footer className="learn-footer"><span>KNOWLEDGE IS CONTEXT</span><span>Values are reported by their source endpoints.</span><ArrowUpRight size={12} aria-hidden="true" /></footer>
    </div>
  );
}