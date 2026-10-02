import { useFleetData } from "@/hooks/useFleetData";
import { AnimatedStyle, BotLine, DesignNav, FleetTotals, useBotRows, PositionChips } from "./DesignShared";

export default function Design2Terminal() {
  const data = useFleetData();
  const rows = useBotRows(data);
  return (
    <main className="min-h-screen overflow-hidden bg-[#090909] font-mono text-[#f5f5f5]">
      <AnimatedStyle>{`
        @keyframes d2scan { from{transform:translateY(-100%)} to{transform:translateY(100vh)} }
        @keyframes d2blink { 50%{opacity:.2} }
        @keyframes d2slide { from{transform:translateX(-10px)} to{transform:translateX(10px)} }
      `}</AnimatedStyle>
      <div className="pointer-events-none fixed inset-0 z-20 opacity-10" style={{ background: "repeating-linear-gradient(0deg,transparent 0 3px,#65ff8a 4px)", animation: "d2scan 9s linear infinite" }} />
      <DesignNav current={2} mode="NEON PINBALL TERMINAL" />
      <section className="mx-auto max-w-3xl px-4 py-7">
        <div className="mb-5 flex items-end justify-between border-b-2 border-[#65ff8a] pb-4">
          <div><div className="text-[10px] font-bold tracking-[.4em] text-[#65ff8a]">ARCADE / FLEET_SCORE</div><div className="mt-2 text-4xl font-black tracking-[-.08em]">HIGH SCORE BOARD</div></div>
          <div className="text-right text-[10px] text-white/40">SYS {data.regime ?? "BOOT"}<br /><span className="text-[#65ff8a]" style={{ animation: "d2blink 1.2s infinite" }}>● CONNECTED</span></div>
        </div>
        <FleetTotals data={data} className="border border-[#65ff8a]/35 bg-[#65ff8a]/5 p-5" />
        <div className="my-5 flex gap-2 overflow-hidden whitespace-nowrap border-y border-white/15 py-3 text-[10px] font-bold text-[#65ff8a]">
          <span style={{ animation: "d2slide 2s ease-in-out infinite alternate" }}>/// LIVE POSITIONS /// </span><PositionChips positions={data.allPos} accent="#65ff8a" />
        </div>
        <div className="space-y-3">
          {rows.map((row, i) => <div key={row.id} style={{ transform: `rotate(${i % 2 ? "1" : "-1"}deg)`, animation: `d2slide ${2 + i}s ease-in-out infinite alternate` }}><BotLine row={row} /></div>)}
        </div>
        <div className="mt-6 grid grid-cols-3 gap-2 text-center text-[10px] uppercase text-white/45">
          <div className="border border-white/15 p-3">Ships online<br /><strong className="text-lg text-white">{rows.filter(r => r.status === "LIVE").length}/3</strong></div>
          <div className="border border-white/15 p-3">Open positions<br /><strong className="text-lg text-white">{data.allPos.length}</strong></div>
          <div className="border border-white/15 p-3">Win rate<br /><strong className="text-lg text-[#65ff8a]">{data.total?.win_rate == null ? "—" : `${(data.total.win_rate * 100).toFixed(1)}%`}</strong></div>
        </div>
      </section>
    </main>
  );
}