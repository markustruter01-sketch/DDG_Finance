import { useMemo, useState } from "react";
import { ArrowUpRight, CircleDashed, Orbit, Radio, TrendingUp } from "lucide-react";
import { useFleetEquity, useLivePositions } from "@/hooks/use-portfolio";
import { useJournal } from "@/hooks/use-journal";
import { getAttributedBotIdentity } from "@/lib/bot-identity";

const RETIRED = new Set(["PSX", "MPC", "BAC", "FTNT", "ARM", "PANW"]);
const SATELLITE_SLOTS = [
  { x: "18%", y: "20%" },
  { x: "82%", y: "20%" },
  { x: "17%", y: "79%" },
  { x: "83%", y: "79%" },
];

function money(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value < 0 ? "−" : ""}$${Math.abs(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function signedMoney(value: number) {
  return `${value >= 0 ? "+" : "−"}$${Math.abs(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

export default function StreamingOrbScreen() {
  const fleet = useFleetEquity();
  const positions = useLivePositions();
  const journal = useJournal();
  const [selectedPositionKey, setSelectedPositionKey] = useState<string | null>(null);
  const open = useMemo(
    () => (positions.data?.positions ?? []).filter((position) => !RETIRED.has(position.symbol)),
    [positions.data?.positions],
  );
  const closed = useMemo(
    () => (journal.data?.trades ?? []).filter((trade) => trade.status !== "Active" && !RETIRED.has(trade.ticker)).slice(0, 8),
    [journal.data?.trades],
  );
  const total = fleet.data?.fleet_total;
  const selected = open.find((position, index) => `${position.bot_id ?? "unattributed"}-${position.symbol}-${index}` === selectedPositionKey) ?? open[0];
  const status = positions.isError
    ? "Position feed unavailable"
    : positions.isLoading && !positions.data
      ? "Loading position feed"
      : positions.data
        ? `${open.length} open positions reported`
        : "No position response";

  return (
    <div className="stream-screen stream-screen-orb orb-screen">
      <style>{`
        .orb-screen,.orb-screen *{box-sizing:border-box}
        .orb-screen{height:100%;min-height:720px;overflow:auto;position:relative;isolation:isolate;color:#edf2e9;background:#172522 url("/streaming-forest-atmosphere.jpg") center 55%/cover;font-family:"DM Sans","Avenir Next",ui-sans-serif,system-ui,sans-serif}
        .orb-screen:before{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;background:linear-gradient(90deg,rgba(7,17,16,.82),rgba(8,20,18,.58) 50%,rgba(7,17,16,.82)),linear-gradient(180deg,rgba(8,18,16,.52),rgba(8,18,16,.26) 47%,rgba(8,18,16,.82))}
        .orb-topbar{height:64px;padding:0 clamp(18px,4vw,52px);display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid rgba(229,239,225,.13);background:rgba(10,22,19,.45);backdrop-filter:blur(22px)}
        .orb-brand,.orb-feed-state,.orb-title-line,.orb-card-heading,.orb-trade-bot{display:flex;align-items:center}
        .orb-brand{gap:11px}.orb-mark{width:32px;height:32px;display:grid;place-items:center;border:1px solid rgba(193,231,202,.22);border-radius:10px;background:rgba(184,223,194,.09);color:#c9e6cb}
        .orb-brand-name{font-size:11px;font-weight:700;letter-spacing:.15em;text-transform:uppercase}.orb-brand-path{color:#94a397;font-size:11px}
        .orb-feed-state{gap:8px;color:#aebbaf;font-size:10px}.orb-feed-dot{width:6px;height:6px;border-radius:50%;background:#9fb39f}.orb-feed-state.is-error{color:#dfc38f}.orb-feed-state.is-error .orb-feed-dot{background:#dfc38f}.orb-feed-state.is-loading .orb-feed-dot{background:#8eb9a1}
        .orb-main{width:min(1160px,calc(100% - 42px));margin:0 auto;padding:24px 0 28px}
        .orb-title-row{display:flex;align-items:flex-end;justify-content:space-between;gap:20px}.orb-eyebrow{color:#b6d2b8;font-size:9px;font-weight:700;letter-spacing:.17em;text-transform:uppercase}
        .orb-title-line{gap:12px;margin-top:7px}.orb-title-line h1{margin:0;color:#f0f4ec;font-size:26px;font-weight:520;letter-spacing:-.05em}.orb-title-icon{color:#c0e0c3}
        .orb-subtitle{margin:7px 0 0;color:#aab8aa;font-size:11px;line-height:1.5}.orb-updated{color:#94a295;font-size:9px;text-align:right}
        .orb-stage{height:300px;position:relative;margin-top:13px;overflow:hidden;border:1px solid rgba(218,232,216,.12);border-radius:15px;background:linear-gradient(120deg,rgba(21,41,34,.43),rgba(9,21,19,.42));backdrop-filter:blur(10px)}
        .orb-stage:before{content:"";position:absolute;left:50%;top:49%;width:min(250px,46vw);aspect-ratio:1;transform:translate(-50%,-50%);border-radius:50%;background:radial-gradient(circle,rgba(167,218,178,.20),rgba(167,218,178,.06) 43%,transparent 70%);filter:blur(3px)}
        .orb-rings{position:absolute;left:50%;top:49%;width:216px;height:216px;transform:translate(-50%,-50%);border:1px solid rgba(190,226,194,.19);border-radius:50%;box-shadow:0 0 0 22px rgba(190,226,194,.025),0 0 0 48px rgba(190,226,194,.018),inset 0 0 32px rgba(190,226,194,.08);animation:orb-breathe 6s ease-in-out infinite}
        .orb-rings:before,.orb-rings:after{content:"";position:absolute;inset:17px;border:1px solid rgba(190,226,194,.19);border-radius:50%}.orb-rings:after{inset:34px;border-color:rgba(190,226,194,.25)}
        @keyframes orb-breathe{0%,100%{transform:translate(-50%,-50%) scale(.98);opacity:.78}50%{transform:translate(-50%,-50%) scale(1.035);opacity:1}}
        .orb-core{position:absolute;left:50%;top:49%;width:112px;height:112px;transform:translate(-50%,-50%);display:flex;flex-direction:column;align-items:center;justify-content:center;border:1px solid rgba(202,235,203,.4);border-radius:50%;background:radial-gradient(circle at 36% 25%,rgba(184,224,188,.2),rgba(22,43,35,.88) 72%);box-shadow:0 0 38px rgba(151,207,163,.15),inset 0 1px rgba(255,255,255,.12);text-align:center}
        .orb-core-label{color:#b4d1b5;font-size:8px;font-weight:700;letter-spacing:.13em}.orb-core-value{margin-top:8px;color:#eef4eb;font:500 18px "IBM Plex Mono",monospace;letter-spacing:-.06em}.orb-core-foot{margin-top:5px;color:#879989;font-size:8px}
        .orb-satellite{position:absolute;min-width:130px;padding:10px 12px;border:1px solid rgba(203,228,201,.15);border-radius:10px;background:rgba(9,23,19,.63);backdrop-filter:blur(12px);color:#dfe8dc;text-align:left;cursor:pointer;transition:border-color .2s,background .2s,transform .2s}
        .orb-satellite:hover,.orb-satellite.is-selected{transform:translateY(-2px);border-color:rgba(193,227,195,.48);background:rgba(20,41,32,.85)}
        .orb-satellite-head{display:flex;align-items:center;justify-content:space-between;gap:10px;color:#b8d4b8;font-size:9px;font-weight:600}.orb-satellite-symbol{margin-top:6px;color:#e8eee5;font:500 12px "IBM Plex Mono",monospace}.orb-satellite-pnl{margin-top:3px;color:#aab8ab;font:9px "IBM Plex Mono",monospace}
        .orb-panel-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:13px;margin-top:13px}
        .orb-panel{min-width:0;overflow:hidden;border:1px solid rgba(218,232,216,.13);border-radius:13px;background:linear-gradient(135deg,rgba(28,45,38,.78),rgba(12,24,21,.78));backdrop-filter:blur(20px);box-shadow:0 12px 32px rgba(2,12,10,.17)}
        .orb-card-heading{min-height:54px;padding:11px 15px;justify-content:space-between;border-bottom:1px solid rgba(218,232,216,.1)}
        .orb-card-title{display:flex;align-items:center;gap:8px;color:#e3ebe0;font-size:11px;font-weight:600}.orb-card-title svg{color:#beddbf}.orb-card-count{color:#92a293;font:9px "IBM Plex Mono",monospace}
        .orb-rows{padding:3px 15px 7px}.orb-row{min-height:43px;display:flex;align-items:center;justify-content:space-between;gap:10px;border-bottom:1px solid rgba(218,232,216,.07)}.orb-row:last-child{border-bottom:0}
        .orb-row-main{min-width:0;display:flex;flex-direction:column;gap:3px}.orb-symbol{color:#dce6da;font:500 10px "IBM Plex Mono",monospace}.orb-identity{overflow:hidden;color:#849486;font-size:8px;text-overflow:ellipsis;white-space:nowrap}
        .orb-row-value{text-align:right;color:#d6e5d4;font:10px "IBM Plex Mono",monospace}.orb-row-value.is-positive{color:#bfe2c2}.orb-row-value.is-negative{color:#e0a79f}.orb-row-sub{margin-top:3px;color:#879688;font-size:8px;text-align:right}
        .orb-empty{min-height:110px;padding:20px;display:flex;align-items:center;justify-content:center;gap:9px;color:#b6c1b3;font-size:10px;text-align:center}.orb-empty.is-unavailable{color:#dfc38f}.orb-empty svg{flex:0 0 auto}
        .orb-footnote{margin-top:13px;display:flex;align-items:center;justify-content:space-between;gap:10px;color:#879588;font-size:8px}.orb-footnote span:first-child{color:#adc4ae}
        @media(max-width:720px){.orb-screen{min-height:810px}.orb-main{width:calc(100% - 28px);padding-top:18px}.orb-stage{height:270px}.orb-satellite{min-width:100px;padding:8px}.orb-satellite-head{font-size:8px}.orb-satellite-symbol{font-size:10px}.orb-satellite-pnl{font-size:8px}.orb-panel-grid{grid-template-columns:1fr}.orb-title-line h1{font-size:22px}.orb-updated{max-width:110px}}
        @media(max-width:440px){.orb-stage{height:245px}.orb-rings{width:175px;height:175px}.orb-core{width:100px;height:100px}.orb-satellite{min-width:85px;max-width:112px}.orb-satellite:nth-of-type(4){display:none}.orb-satellite-head{font-size:7px}.orb-main{width:calc(100% - 20px)}}
        @media(prefers-reduced-motion:reduce){.orb-rings{animation:none}.orb-satellite{transition:none}}
      `}</style>
      <header className="orb-topbar">
        <div className="orb-brand">
          <span className="orb-mark"><Orbit size={16} /></span>
          <span className="orb-brand-name">Neural</span>
          <span className="orb-brand-path">/ ORB</span>
        </div>
        <div className={`orb-feed-state ${positions.isError ? "is-error" : positions.isLoading && !positions.data ? "is-loading" : ""}`} data-testid="orb-position-status" aria-live="polite">
          <span className="orb-feed-dot" /><span>{status}</span>
        </div>
      </header>

      <main className="orb-main">
        <div className="orb-title-row">
          <div>
            <div className="orb-eyebrow">ETF FLEET · LIVE POSITION VIEW</div>
            <div className="orb-title-line"><Orbit className="orb-title-icon" size={22} /><h1>Orbital fleet</h1></div>
            <p className="orb-subtitle">Positions and journal records shown as reported by dashboard services.</p>
          </div>
          <div className="orb-updated">
            <div>FLEET EQUITY</div>
            <div>{fleet.isError && total ? "Refresh failed · showing last response" : fleet.isLoading && !total ? "Loading…" : fleet.isError ? "Unavailable" : fleet.data?.generated_at ? new Date(fleet.data.generated_at).toLocaleTimeString() : "No response"}</div>
          </div>
        </div>

        <section className="orb-stage" aria-label="Fleet equity and reported position satellites">
          <div className="orb-rings" aria-hidden="true" />
          <div className="orb-core">
            <span className="orb-core-label">FLEET EQUITY</span>
            <span className="orb-core-value" data-testid="orb-fleet-equity">
              {fleet.isLoading && !total ? "Loading" : fleet.isError && !total ? "Unavailable" : total ? money(total.equity) : "—"}
            </span>
            <span className="orb-core-foot">{total ? `${total.positions} positions reported` : fleet.isError ? "Source unavailable" : "No value reported"}</span>
          </div>
          {positions.isLoading && !positions.data ? (
            <div className="orb-empty"><CircleDashed size={15} />Loading positions…</div>
          ) : positions.isError && !positions.data ? (
            <div className="orb-empty is-unavailable"><CircleDashed size={15} />Position feed unavailable</div>
          ) : positions.data && open.length === 0 ? (
            <div className="orb-empty"><Radio size={14} />No open positions reported</div>
          ) : open.slice(0, SATELLITE_SLOTS.length).map((position, index) => {
            const key = `${position.bot_id ?? "unattributed"}-${position.symbol}-${index}`;
            const identity = getAttributedBotIdentity(position.bot_id);
            return (
              <button
                type="button"
                key={key}
                className={`orb-satellite ${selected && selected.symbol === position.symbol && selected.bot_id === position.bot_id ? "is-selected" : ""}`}
                style={{ left: SATELLITE_SLOTS[index].x, top: SATELLITE_SLOTS[index].y, transform: "translate(-50%,-50%)" }}
                onClick={() => setSelectedPositionKey(key)}
                aria-pressed={selectedPositionKey === key}
                aria-label={`Select ${position.symbol}, ${identity.displayName}`}
                data-testid={`orb-position-${position.symbol}-${index}`}
              >
                <span className="orb-satellite-head"><span>{identity.icon} {identity.shortName}</span><span>{position.side}</span></span>
                <span className="orb-satellite-symbol">{position.symbol}</span>
                <span className={`orb-satellite-pnl ${position.unrealized_pl >= 0 ? "is-positive" : "is-negative"}`}>{signedMoney(position.unrealized_pl)}</span>
              </button>
            );
          })}
        </section>

        <div className="orb-panel-grid">
          <section className="orb-panel" aria-label="Open positions">
            <div className="orb-card-heading">
              <div className="orb-card-title"><Orbit size={14} />Open positions</div>
              <span className="orb-card-count">{positions.data ? `${open.length} reported` : "—"}</span>
            </div>
            {positions.isLoading && !positions.data ? (
              <div className="orb-empty"><CircleDashed size={15} />Loading positions…</div>
            ) : positions.isError && !positions.data ? (
              <div className="orb-empty is-unavailable"><CircleDashed size={15} />Position feed unavailable</div>
            ) : open.length === 0 ? (
              <div className="orb-empty"><Radio size={14} />No open positions reported</div>
            ) : (
              <div className="orb-rows">
                {open.map((position, index) => {
                  const identity = getAttributedBotIdentity(position.bot_id);
                  return (
                    <div className="orb-row" key={`${position.bot_id ?? "unattributed"}-${position.symbol}-${index}`}>
                      <div className="orb-row-main">
                        <span className="orb-symbol">{position.symbol} · {position.side}</span>
                        <span className="orb-identity">{identity.icon} {identity.displayName} · {position.qty} units</span>
                      </div>
                      <div>
                        <div className={`orb-row-value ${position.unrealized_pl >= 0 ? "is-positive" : "is-negative"}`}>{signedMoney(position.unrealized_pl)}</div>
                        <div className="orb-row-sub">unrealized P/L · {position.unrealized_plpc >= 0 ? "+" : ""}{(position.unrealized_plpc * 100).toFixed(2)}%</div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
            {positions.isError && positions.data && <div className="orb-footnote"><span>Refresh failed · showing last response</span></div>}
          </section>

          <section className="orb-panel" aria-label="Recent journal trades">
            <div className="orb-card-heading">
              <div className="orb-card-title"><TrendingUp size={14} />Recent closed trades</div>
              <span className="orb-card-count">{journal.data ? `${closed.length} shown` : "—"}</span>
            </div>
            {journal.isLoading && !journal.data ? (
              <div className="orb-empty"><CircleDashed size={15} />Loading journal…</div>
            ) : journal.isError && !journal.data ? (
              <div className="orb-empty is-unavailable"><CircleDashed size={15} />Journal unavailable</div>
            ) : closed.length === 0 ? (
              <div className="orb-empty"><Radio size={14} />No recent closed trades reported</div>
            ) : (
              <div className="orb-rows">
                {closed.map((trade) => {
                  const identity = getAttributedBotIdentity(trade.bot_id);
                  const pnl = trade.pnl_percentage;
                  return (
                    <div className="orb-row" key={trade.trade_id}>
                      <div className="orb-row-main">
                        <span className="orb-symbol">{trade.ticker} · {trade.status.replaceAll("_", " ")}</span>
                        <span className="orb-identity">{identity.icon} {identity.displayName} · {trade.date ? new Date(trade.date).toLocaleDateString() : "Date unavailable"}</span>
                      </div>
                      <div className={`orb-row-value ${pnl >= 0 ? "is-positive" : "is-negative"}`}>{Number.isFinite(pnl) ? `${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}%` : "—"}</div>
                    </div>
                  );
                })}
              </div>
            )}
            {journal.isError && journal.data && <div className="orb-footnote"><span>Refresh failed · showing last response</span></div>}
          </section>
        </div>
        <div className="orb-footnote">
          <span>{selected ? `Selected · ${selected.symbol} / ${getAttributedBotIdentity(selected.bot_id).displayName}` : "No position selected"}</span>
          <span>Only reported service data · no synthetic position records</span>
          <ArrowUpRight size={12} aria-hidden="true" />
        </div>
      </main>
    </div>
  );
}