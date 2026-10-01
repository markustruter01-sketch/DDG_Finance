import { useMemo, useState } from "react";
import { Activity, ArrowDownRight, ArrowUpRight, Clock3, Orbit, Radio } from "lucide-react";
import { useFleetEquity, useJournal, useLivePositions } from "../streaming-current/_shared/mockData";
import { getBotIdentity } from "../streaming-current/_shared/identity";

const RETIRED = new Set(["PSX", "MPC", "BAC", "FTNT", "ARM", "PANW"]);
const SATELLITE_SLOTS = [
  { top: "15%", left: "8%" },
  { top: "12%", right: "8%" },
  { bottom: "13%", left: "7%" },
  { bottom: "10%", right: "7%" },
];

function money(value: number, signed = false) {
  const rounded = Math.round(value);
  const amount = `$${Math.abs(rounded).toLocaleString()}`;
  if (rounded < 0) return `−${amount}`;
  return `${signed ? "+" : ""}${amount}`;
}

function timeLabel(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-US", { hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
}

export function Orb() {
  const fleet = useFleetEquity();
  const positions = useLivePositions();
  const journal = useJournal();
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const open = useMemo(
    () => (positions.data?.positions ?? []).filter((position) => !RETIRED.has(position.symbol)),
    [positions.data],
  );
  const closed = useMemo(
    () => (journal.data?.trades ?? []).filter((trade) => !RETIRED.has(trade.ticker)).slice(0, 8),
    [journal.data],
  );
  const selected = open.find((position) => `${position.bot_id ?? "unknown"}-${position.symbol}` === selectedKey) ?? open[0];
  const total = fleet.data?.fleet_total;
  const hasPositionData = Array.isArray(positions.data?.positions);

  return (
    <div className="orb-redesign relative h-full min-h-[800px] w-full overflow-hidden bg-[#101a18] text-[#f2f4e9]">
      <div className="orb-backdrop absolute inset-0" aria-hidden="true" />
      <div className="orb-shade absolute inset-0" aria-hidden="true" />
      <div className="orb-grain absolute inset-0" aria-hidden="true" />

      <div className="relative z-10 mx-auto flex h-full min-h-[800px] w-full max-w-[1600px] flex-col px-7 py-5">
        <header className="flex h-12 shrink-0 items-center justify-between border-b border-white/[0.13] pb-3">
          <div className="flex items-center gap-3">
            <div className="grid h-8 w-8 place-items-center rounded-xl border border-[#c4d4aa]/30 bg-[#c4d4aa]/10 text-[#d6e3be]">
              <Orbit size={17} strokeWidth={1.5} />
            </div>
            <div className="flex items-baseline gap-2">
              <span className="font-['DM_Sans'] text-[13px] font-semibold tracking-[0.16em] text-[#eff4e7]">FIELD / ORB</span>
              <span className="text-[10px] tracking-[0.13em] text-[#b5c2ae]/55">STREAMING WORKSPACE</span>
            </div>
          </div>
          <div className="flex items-center gap-2 rounded-full border border-[#d2d9c6]/15 bg-[#1d2924]/55 px-3 py-1.5 text-[10px] tracking-[0.12em] text-[#d0d7c8]/80 backdrop-blur-xl">
            <span className="h-1.5 w-1.5 rounded-full bg-[#c5a876]" />
            SANDBOX FIXTURE
            <span className="ml-1 border-l border-white/15 pl-2 text-[#aab6a5]/60">NOT CONNECTED</span>
          </div>
        </header>

        <main className="flex min-h-0 flex-1 flex-col">
          <section className="flex shrink-0 items-end justify-between pb-5 pt-5">
            <div>
              <div className="mb-1.5 flex items-center gap-2 text-[10px] font-medium tracking-[0.2em] text-[#c9d9ae]/70">
                <span className="h-px w-5 bg-[#c9d9ae]/55" />
                FLEET OBSERVATORY
              </div>
              <h1 className="font-['DM_Sans'] text-[31px] font-medium leading-none tracking-[-0.045em] text-[#f2f3e9]">ORB</h1>
              <p className="mt-2 text-[12px] text-[#c2cabc]/68">Capital, positions, and closed trades at a glance.</p>
            </div>
            <div className="mb-1 flex items-center gap-2 text-[10px] tracking-[0.11em] text-[#c7d0c2]/70">
              <Clock3 size={13} strokeWidth={1.5} />
              FIXTURE VALUES · SOURCE-SHAPED SAMPLE
            </div>
          </section>

          <section className="grid min-h-0 flex-1 grid-cols-[minmax(0,1.62fr)_minmax(390px,1fr)] gap-4 pb-1">
            <section className="orb-glass relative flex min-h-0 flex-col overflow-hidden rounded-[26px] border border-white/[0.14] px-5 pb-4 pt-4 shadow-[0_24px_90px_rgba(4,11,9,.32)]">
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-[9px] font-medium tracking-[0.2em] text-[#d1d8c4]/60">EQUITY FIELD</p>
                  <h2 className="mt-1 font-['DM_Sans'] text-[15px] font-medium tracking-[-0.02em] text-[#f0f2e9]">Fleet at a glance</h2>
                </div>
                <div className="flex items-center gap-2 rounded-full border border-white/[0.12] bg-[#17221e]/55 px-2.5 py-1.5 text-[9px] tracking-[0.11em] text-[#d5dccb]/70">
                  <Activity size={12} strokeWidth={1.6} />
                  {hasPositionData ? `${open.length} OPEN POSITIONS` : "POSITIONS UNAVAILABLE"}
                </div>
              </div>

              <div className="orb-field relative mt-2 min-h-[430px] flex-1">
                <div className="orb-ring orb-ring-outer" aria-hidden="true" />
                <div className="orb-ring orb-ring-inner" aria-hidden="true" />
                <div className="orb-ring orb-ring-core" aria-hidden="true" />
                <div className="orb-center">
                  <div className="orb-center-halo" aria-hidden="true" />
                  <div className="relative z-10 text-center">
                    <div className="mx-auto mb-3 grid h-8 w-8 place-items-center rounded-full border border-[#dce6c4]/25 bg-[#dce6c4]/[0.08] text-[#d5e3bd]/85">
                      <Orbit size={16} strokeWidth={1.35} />
                    </div>
                    <div className="text-[9px] font-medium tracking-[0.22em] text-[#c4d4af]/68">FLEET EQUITY</div>
                    <div className="mt-2 font-['DM_Sans'] text-[32px] font-medium leading-none tracking-[-0.055em] text-[#f5f3e8]">
                      {total?.equity != null ? money(total.equity) : "—"}
                    </div>
                    {total ? (
                      <div className={`mt-3 inline-flex items-center gap-1.5 rounded-full border border-white/[0.12] bg-[#101c19]/50 px-2.5 py-1 text-[10px] ${total.pnl >= 0 ? "text-[#c1d8aa]" : "text-[#e3a39a]"}`}>
                        {total.pnl >= 0 ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
                        <span>{money(total.pnl, true)}</span>
                        <span className="text-white/35">·</span>
                        <span>{total.pnl >= 0 ? "+" : ""}{total.pnl_pct.toFixed(2)}%</span>
                      </div>
                    ) : (
                      <div className="mt-3 text-[10px] text-[#c4ccc0]/50">Equity unavailable</div>
                    )}
                  </div>
                </div>

                {open.map((position, index) => {
                  const key = `${position.bot_id ?? "unknown"}-${position.symbol}`;
                  const identity = getBotIdentity(position.bot_id ?? "");
                  const slot = SATELLITE_SLOTS[index % SATELLITE_SLOTS.length];
                  const isSelected = selected?.symbol === position.symbol && selected?.bot_id === position.bot_id;
                  return (
                    <button
                      key={key}
                      type="button"
                      style={slot}
                      onClick={() => setSelectedKey(key)}
                      aria-pressed={isSelected}
                      className={`orb-satellite absolute z-20 w-[174px] rounded-[14px] border px-3 py-2.5 text-left backdrop-blur-2xl transition duration-200 hover:-translate-y-0.5 ${isSelected ? "border-[#d4e0b9]/40 bg-[#28392e]/85 shadow-[0_10px_34px_rgba(5,12,9,.3)]" : "border-white/[0.13] bg-[#17221e]/75 hover:border-white/25"}`}
                    >
                      <span className="flex items-center justify-between gap-2">
                        <span className="font-['DM_Sans'] text-[14px] font-semibold tracking-[0.06em] text-[#edf0e5]">{position.symbol}</span>
                        <span className={`font-['DM_Sans'] text-[12px] font-medium ${position.unrealized_pl >= 0 ? "text-[#c4dba8]" : "text-[#e4a198]"}`}>
                          {money(position.unrealized_pl, true)}
                        </span>
                      </span>
                      <span className="mt-1 block truncate text-[9px] tracking-[0.08em] text-[#b7c3b3]/65">{identity.shortName.toUpperCase()}</span>
                    </button>
                  );
                })}

                {!hasPositionData && (
                  <div className="absolute bottom-6 left-1/2 z-30 -translate-x-1/2 rounded-full border border-white/10 bg-[#111b17]/80 px-4 py-2 text-[11px] text-[#d0d7c8]/70 backdrop-blur-xl">
                    Position data unavailable
                  </div>
                )}
                {hasPositionData && open.length === 0 && (
                  <div className="absolute bottom-6 left-1/2 z-30 -translate-x-1/2 rounded-full border border-white/10 bg-[#111b17]/80 px-4 py-2 text-[11px] text-[#d0d7c8]/70 backdrop-blur-xl">
                    No open positions
                  </div>
                )}
              </div>

              <div className="flex shrink-0 items-center justify-between border-t border-white/[0.11] pt-3 text-[9px] tracking-[0.12em] text-[#bdc8b7]/55">
                <span>POSITION PL · SOURCE VALUES ROUNDED TO WHOLE USD</span>
                <span className="flex items-center gap-1.5"><span className="h-1 w-1 rounded-full bg-[#c5a876]/85" />CLICK A NODE TO FOCUS</span>
              </div>
            </section>

            <aside className="flex min-h-0 flex-col gap-4">
              <section className="orb-glass min-h-0 flex-[1.02] overflow-hidden rounded-[23px] border border-white/[0.14] px-4 pb-3 pt-4 shadow-[0_18px_65px_rgba(4,11,9,.24)]">
                <div className="mb-2 flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <div className="grid h-7 w-7 place-items-center rounded-[10px] border border-[#ceddb7]/15 bg-[#ceddb7]/[0.08] text-[#cfddba]/80">
                      <Radio size={14} strokeWidth={1.5} />
                    </div>
                    <div>
                      <h2 className="font-['DM_Sans'] text-[13px] font-medium text-[#f0f2e9]">Open positions</h2>
                      <p className="mt-0.5 text-[9px] tracking-[0.09em] text-[#b7c2b3]/55">CURRENT UNREALIZED P&L</p>
                    </div>
                  </div>
                  <span className="rounded-full border border-white/[0.12] bg-[#17231e]/55 px-2 py-1 text-[9px] text-[#c7d3bd]/72">
                    {hasPositionData ? String(open.length).padStart(2, "0") : "—"}
                  </span>
                </div>
                <div className="space-y-1">
                  {!hasPositionData ? (
                    <div className="flex h-[148px] items-center justify-center rounded-xl border border-dashed border-white/[0.12] text-[11px] text-[#c0c9bd]/55">Position data unavailable</div>
                  ) : open.length === 0 ? (
                    <div className="flex h-[148px] items-center justify-center rounded-xl border border-dashed border-white/[0.12] text-[11px] text-[#c0c9bd]/55">No open positions</div>
                  ) : open.map((position) => {
                    const key = `${position.bot_id ?? "unknown"}-${position.symbol}`;
                    const identity = getBotIdentity(position.bot_id ?? "");
                    const isSelected = selected?.symbol === position.symbol && selected?.bot_id === position.bot_id;
                    return (
                      <button
                        key={key}
                        type="button"
                        onClick={() => setSelectedKey(key)}
                        aria-pressed={isSelected}
                        className={`flex w-full items-center justify-between rounded-xl border px-3 py-2 text-left transition duration-200 ${isSelected ? "border-[#d4dfbe]/25 bg-[#d4dfbe]/[0.08]" : "border-transparent bg-[#101b17]/30 hover:border-white/[0.11] hover:bg-white/[0.04]"}`}
                      >
                        <span className="flex min-w-0 items-center gap-3">
                          <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${position.unrealized_pl >= 0 ? "bg-[#bbd398]" : "bg-[#de8f85]"}`} />
                          <span className="min-w-0">
                            <span className="block font-['DM_Sans'] text-[12px] font-semibold tracking-[0.04em] text-[#edf0e4]">{position.symbol}</span>
                            <span className="mt-0.5 block truncate text-[9px] tracking-[0.07em] text-[#b6c1b0]/60">{identity.shortName.toUpperCase()}</span>
                          </span>
                        </span>
                        <span className={`font-['DM_Sans'] text-[12px] font-medium tabular-nums ${position.unrealized_pl >= 0 ? "text-[#c4dba8]" : "text-[#e4a198]"}`}>
                          {money(position.unrealized_pl, true)}
                        </span>
                      </button>
                    );
                  })}
                </div>
                {selected && (
                  <div className="mt-2 flex items-center justify-between border-t border-white/[0.1] pt-2 text-[9px] text-[#b7c2b3]/55">
                    <span>FOCUSED · {getBotIdentity(selected.bot_id ?? "").displayName.toUpperCase()}</span>
                    <span className="tabular-nums">{selected.symbol} / UNREALIZED</span>
                  </div>
                )}
              </section>

              <section className="orb-glass min-h-0 flex-[1] overflow-hidden rounded-[23px] border border-white/[0.14] px-4 pb-3 pt-4 shadow-[0_18px_65px_rgba(4,11,9,.24)]">
                <div className="mb-2 flex items-center justify-between">
                  <div>
                    <h2 className="font-['DM_Sans'] text-[13px] font-medium text-[#f0f2e9]">Recent closed trades</h2>
                    <p className="mt-0.5 text-[9px] tracking-[0.09em] text-[#b7c2b3]/55">JOURNAL · NEWEST FIRST</p>
                  </div>
                  <span className="rounded-full border border-white/[0.12] bg-[#17231e]/55 px-2 py-1 text-[9px] text-[#c7d3bd]/72">
                    {journal.isError ? "ERR" : journal.isLoading ? "…" : journal.data ? String(closed.length).padStart(2, "0") : "—"}
                  </span>
                </div>
                {journal.isLoading ? (
                  <div className="space-y-2 pt-1" aria-label="Loading recent trades">
                    {[0, 1, 2, 3].map((item) => <div key={item} className="h-8 animate-pulse rounded-lg bg-white/[0.06]" />)}
                  </div>
                ) : journal.isError ? (
                  <div className="flex h-[164px] items-center justify-center rounded-xl border border-dashed border-[#d68b7e]/20 text-[11px] text-[#e2a59c]/75">Journal unavailable</div>
                ) : !journal.data ? (
                  <div className="flex h-[164px] items-center justify-center rounded-xl border border-dashed border-white/[0.12] text-[11px] text-[#c0c9bd]/55">Journal data unavailable</div>
                ) : closed.length ? (
                  <>
                    <div className="grid grid-cols-[1fr_68px_80px] border-b border-white/[0.1] px-2 pb-1.5 text-[8px] tracking-[0.13em] text-[#aeb8a8]/50">
                      <span>INSTRUMENT</span><span>TIME</span><span className="text-right">RETURN</span>
                    </div>
                    <div className="divide-y divide-white/[0.07]">
                      {closed.map((trade) => {
                        const identity = getBotIdentity(trade.bot_id);
                        const pnl = trade.pnl_percentage;
                        const positive = pnl != null && pnl >= 0;
                        return (
                          <div key={trade.trade_id} className="grid grid-cols-[1fr_68px_80px] items-center px-2 py-[7px]">
                            <div className="min-w-0">
                              <span className="font-['DM_Sans'] text-[11px] font-semibold tracking-[0.03em] text-[#e7ebdf]">{trade.ticker}</span>
                              <span className="ml-2 truncate text-[8px] tracking-[0.04em] text-[#aeb9a8]/50">{identity.shortName.toUpperCase()}</span>
                            </div>
                            <span className="font-mono text-[9px] tabular-nums text-[#b8c2b2]/60">{timeLabel(trade.date)}</span>
                            <span className={`text-right font-mono text-[10px] tabular-nums ${pnl == null ? "text-[#b8c2b2]/45" : positive ? "text-[#c4dba8]" : "text-[#e4a198]"}`}>
                              {pnl == null ? "—" : `${pnl.toFixed(2)}%`}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </>
                ) : (
                  <div className="flex h-[164px] items-center justify-center rounded-xl border border-dashed border-white/[0.12] text-[11px] text-[#c0c9bd]/55">No recent closed ETF trades</div>
                )}
              </section>
            </aside>
          </section>
        </main>
      </div>

      <style>{`
        .orb-redesign {
          font-family: "DM Sans", "Segoe UI", sans-serif;
          isolation: isolate;
        }
        .orb-backdrop {
          z-index: -3;
          background-image: url("/__mockup/images/streaming-forest-atmosphere.jpg");
          background-size: cover;
          background-position: center 49%;
          filter: saturate(.56) brightness(.62);
          transform: scale(1.025);
        }
        .orb-shade {
          z-index: -2;
          background:
            linear-gradient(90deg, rgba(9, 20, 17, .82) 0%, rgba(12, 23, 20, .65) 52%, rgba(7, 16, 14, .82) 100%),
            linear-gradient(180deg, rgba(13, 22, 19, .36), rgba(8, 17, 15, .78));
        }
        .orb-grain {
          z-index: -1;
          pointer-events: none;
          opacity: .11;
          background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.88' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.22'/%3E%3C/svg%3E");
          mix-blend-mode: soft-light;
        }
        .orb-glass {
          background:
            linear-gradient(145deg, rgba(40, 55, 47, .66), rgba(18, 29, 25, .72) 56%, rgba(19, 27, 24, .65));
          backdrop-filter: blur(24px) saturate(118%);
          -webkit-backdrop-filter: blur(24px) saturate(118%);
        }
        .orb-field {
          overflow: hidden;
        }
        .orb-ring {
          position: absolute;
          left: 50%;
          top: 51%;
          border: 1px solid rgba(216, 229, 200, .12);
          border-radius: 50%;
          transform: translate(-50%, -50%);
          pointer-events: none;
        }
        .orb-ring-outer {
          width: min(88%, 475px);
          aspect-ratio: 1;
          border-style: dashed;
          border-color: rgba(210, 224, 192, .12);
          animation: orb-drift 72s linear infinite;
        }
        .orb-ring-inner {
          width: min(69%, 365px);
          aspect-ratio: 1;
          border-color: rgba(222, 231, 207, .14);
          box-shadow: 0 0 42px rgba(195, 213, 173, .035), inset 0 0 42px rgba(195, 213, 173, .025);
        }
        .orb-ring-core {
          width: min(48%, 255px);
          aspect-ratio: 1;
          border-color: rgba(226, 233, 214, .19);
          box-shadow: 0 0 0 16px rgba(208, 224, 190, .018), 0 0 0 34px rgba(208, 224, 190, .014);
        }
        .orb-center {
          position: absolute;
          z-index: 10;
          top: 51%;
          left: 50%;
          display: grid;
          width: min(42%, 230px);
          aspect-ratio: 1;
          place-items: center;
          border: 1px solid rgba(230, 236, 215, .29);
          border-radius: 50%;
          background:
            radial-gradient(circle at 36% 25%, rgba(193, 213, 171, .23), transparent 38%),
            radial-gradient(circle at 58% 76%, rgba(149, 176, 151, .12), transparent 42%),
            linear-gradient(145deg, rgba(60, 79, 65, .88), rgba(22, 35, 30, .88) 66%);
          box-shadow: inset 0 1px 0 rgba(255, 255, 255, .16), 0 20px 60px rgba(0, 0, 0, .25), 0 0 85px rgba(200, 219, 178, .09);
          transform: translate(-50%, -50%);
          backdrop-filter: blur(18px);
        }
        .orb-center-halo {
          position: absolute;
          inset: 11px;
          border: 1px solid rgba(237, 239, 218, .1);
          border-radius: 50%;
          background: linear-gradient(125deg, rgba(255,255,255,.035), transparent 55%);
          pointer-events: none;
        }
        @keyframes orb-drift { to { transform: translate(-50%, -50%) rotate(360deg); } }
        @media (max-width: 900px) {
          .orb-redesign { min-height: 100dvh; }
          .orb-redesign > div.relative { min-height: 100dvh; padding-left: 16px; padding-right: 16px; }
          .orb-redesign main > section:last-child {
            grid-template-columns: minmax(0, 1fr);
            overflow-y: auto;
          }
          .orb-redesign .orb-field { min-height: 430px; }
        }
        @media (prefers-reduced-motion: reduce) {
          .orb-ring-outer { animation: none; }
        }
      `}</style>
    </div>
  );
}