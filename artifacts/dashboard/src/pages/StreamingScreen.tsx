import { AIBrainVisual } from "@/components/streaming/AIBrainVisual";
import { useFleetData } from "@/hooks/useFleetData";

export default function StreamingScreen() {
  const { runnerStatus, runnerStatusError } = useFleetData();
  const runnerTone = runnerStatus?.verdict === "ALIVE"
    ? "alive"
    : runnerStatus?.verdict === "STALE"
      ? "stale"
      : runnerStatus?.verdict === "ABSENT"
        ? "absent"
        : "unknown";
  const runnerLabel = runnerStatusError && runnerStatus
    ? "Runner refresh failed"
    : runnerStatusError
      ? "Runner status unavailable"
    : runnerStatus?.verdict === "ALIVE"
      ? "Runner alive"
      : runnerStatus?.verdict === "STALE"
        ? "Runner stale"
        : runnerStatus?.verdict === "ABSENT"
          ? "Runner absent"
          : "Checking runner";
  const lastBeat = runnerStatus?.last_beat_at ? new Date(runnerStatus.last_beat_at) : null;
  const lastBeatLabel = lastBeat && !Number.isNaN(lastBeat.getTime())
    ? lastBeat.toLocaleTimeString()
    : null;

  return (
    <div
      className="stream-screen stream-screen-live"
      style={{
        height: "100%",
        width: "100%",
        overflow: "hidden",
        position: "relative",
      }}
    >
      <style>{`
        .live-stream,.live-stream *{box-sizing:border-box}
        .live-stream{height:100%;min-height:580px;overflow:hidden;position:relative;isolation:isolate;color:#edf2e9;background:#172522 url("/streaming-forest-atmosphere.jpg") center 52%/cover;font-family:"DM Sans","Avenir Next",ui-sans-serif,system-ui,sans-serif}
        .live-stream:before{content:"";position:absolute;inset:0;z-index:1;pointer-events:none;background:linear-gradient(90deg,rgba(7,18,17,.7),rgba(9,20,18,.46) 50%,rgba(7,18,17,.72)),linear-gradient(180deg,rgba(8,18,16,.48),rgba(8,18,16,.05) 40%,rgba(8,18,16,.78))}
        .live-stream .live-brain{position:absolute;inset:0;z-index:0;opacity:.82}
        .live-topbar{position:absolute;z-index:3;top:0;left:0;right:0;min-height:66px;padding:0 clamp(18px,4vw,48px);display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid rgba(229,239,225,.13);background:rgba(10,22,19,.48);backdrop-filter:blur(20px)}
        .live-brand{display:flex;align-items:center;gap:12px}.live-brand-mark{width:32px;height:32px;display:grid;place-items:center;border:1px solid rgba(193,231,202,.24);border-radius:10px;color:#c4e6c7;background:rgba(184,223,194,.1)}
        .live-brand-name{color:#edf3e9;font-size:11px;font-weight:650;letter-spacing:.14em;text-transform:uppercase}.live-brand-section{color:#aab7aa;font-size:11px}
        .live-source-state{display:flex;align-items:center;gap:9px;color:#b9c6b9;font-size:10px;letter-spacing:.045em}
        .live-source-dot{width:7px;height:7px;flex:0 0 auto;border-radius:50%;background:#91a297}.live-source-state.alive .live-source-dot{background:#a9ddb7;box-shadow:0 0 13px rgba(169,221,183,.65)}.live-source-state.stale .live-source-dot{background:#e3bf7d}.live-source-state.absent .live-source-dot{background:#db9690}.live-source-state.unknown .live-source-dot{background:#91a297}
        .live-center{position:absolute;z-index:2;inset:66px 0 70px;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;padding:0 20px 28px;text-align:center;pointer-events:none}
        .live-kicker{color:#c1d9c0;font-size:9px;font-weight:700;letter-spacing:.22em;text-transform:uppercase;text-shadow:0 1px 8px #10211d}
        .live-center h1{margin:9px 0 6px;color:#f1f4ec;font-size:clamp(22px,3vw,32px);font-weight:500;letter-spacing:-.045em;text-shadow:0 2px 14px rgba(0,0,0,.45)}
        .live-center p{max-width:500px;margin:0;color:#b7c4b7;font-size:11px;line-height:1.6}
        .live-footer{position:absolute;z-index:3;left:0;right:0;bottom:0;min-height:54px;padding:11px clamp(18px,4vw,48px);display:flex;align-items:center;justify-content:space-between;gap:14px;border-top:1px solid rgba(229,239,225,.12);background:rgba(10,22,19,.58);backdrop-filter:blur(18px);color:#94a395;font-size:9px}
        .live-footer-label{color:#bed9c0;font-weight:650;letter-spacing:.12em;text-transform:uppercase}.live-footer-detail{text-align:right}
        @media(max-width:580px){.live-topbar{padding:0 14px}.live-brand-section{display:none}.live-source-state{font-size:9px}.live-center{padding-bottom:20px}.live-footer{align-items:flex-start;flex-direction:column;gap:5px}.live-footer-detail{text-align:left}}
      `}</style>
      <div className="live-stream" data-testid="live-stream-screen">
        <div className="live-brain" aria-hidden="true"><AIBrainVisual /></div>
        <header className="live-topbar">
          <div className="live-brand">
            <span className="live-brand-mark">N</span>
            <span className="live-brand-name">Neural</span>
            <span className="live-brand-section">/ Live visualization</span>
          </div>
          <div className={`live-source-state ${runnerTone} ${runnerStatusError ? "has-error" : ""}`} data-testid="live-runner-status" aria-live="polite">
            <span className="live-source-dot" />
            <span>{runnerLabel}</span>
          </div>
        </header>
        <main className="live-center">
          <div className="live-kicker">Illustrative neural network</div>
          <h1>A view of the system in motion.</h1>
          <p>The animated network is visual artwork, not market telemetry. Operational runner state is reported separately above.</p>
        </main>
        <footer className="live-footer">
          <span className="live-footer-label">Runner status · /runner/status</span>
          <span className="live-footer-detail" data-testid="live-runner-updated">
            {runnerStatusError && runnerStatus
              ? `Refresh failed · last response ${runnerStatus.verdict}${lastBeatLabel ? ` · last beat ${lastBeatLabel}` : ""}`
              : runnerStatusError
                ? "Could not retrieve runner status"
              : runnerStatus
                ? `${runnerStatus.verdict}${lastBeatLabel ? ` · last beat ${lastBeatLabel}` : ""}`
                : "Waiting for runner status"}
          </span>
        </footer>
      </div>
    </div>
  );
}
