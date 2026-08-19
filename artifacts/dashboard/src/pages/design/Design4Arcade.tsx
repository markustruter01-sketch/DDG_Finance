import { useFleetData } from "@/hooks/useFleetData";
import { AnimatedStyle, DesignNav, FleetTotals, getBotRows, PositionChips } from "./DesignShared";

export default function Design4Arcade() {
  const data = useFleetData();
  const rows = getBotRows(data);
  return (
    <main className="min-h-screen overflow-hidden bg-[#f7f0df] font-sans text-[#111]">
      <AnimatedStyle>{`
        @keyframes d4marquee { to{transform:translateX(-50%)} }
        @keyframes d4spin { to{transform:rotate(360deg)} }
        @keyframes d4wiggle { 0%,100%{transform:rotate(-1deg) translateY(0)} 50%{transform:rotate(1deg) translateY(-6px)} }
      `}</AnimatedStyle>
      <DesignNav current={4} mode="LOUD / MONEY IS A CONTACT SPORT" />
      <div className="overflow-hidden border-b-4 border-black bg-[#ff4d6d] py-2 text-xs font-black uppercase tracking-[.25em]"><div className="whitespace-nowrap" style={{ animation: "d4marquee 18s linear infinite" }}>NOISE IS DATA · REGIME IS A MOOD · PROFIT IS A COLOR · NOISE IS DATA · REGIME IS A MOOD · PROFIT IS A COLOR · </div></div>
      <section className="mx-auto max-w-3xl px-4 py-7">
        <div className="grid gap-5 md:grid-cols-[1.4fr_.6fr]"><div className="border-4 border-black bg-[#ffd166] p-5 shadow-[10px_10px_0_#111]"><div className="text-[11px] font-black uppercase tracking-[.22em]">The big number</div><FleetTotals data={data} className="mt-5" /></div><div className="relative flex min-h-48 flex-col justify-between border-4 border-black bg-[#5ce1e6] p-5 shadow-[10px_10px_0_#111]"><div className="text-[11px] font-black uppercase">Kill switch</div><div className="text-5xl font-black">{data.killTripped ? "!" : "✓"}</div><div className="text-xs font-black uppercase">{data.killTripped ? "TRIPPED · STOP" : "ARMED · GO TIME"}</div><div className="absolute -right-5 -top-5 h-16 w-16 rounded-full border-4 border-black bg-[#ff4d6d]" style={{ animation: "d4spin 8s linear infinite" }} /></div></div>
        <div className="mt-8 grid gap-5 md:grid-cols-3">{rows.map((row, i) => <div key={row.id} className="border-4 border-black bg-white p-4 shadow-[7px_7px_0_#111]" style={{ animation: `d4wiggle ${3 + i}s ease-in-out infinite` }}><div className="flex items-start justify-between"><div className="text-3xl">{row.icon}</div><div className="rounded-full border-2 border-black px-2 py-1 text-[9px] font-black uppercase">{row.statusMeta.label}</div></div><div className="mt-6 text-[11px] font-black uppercase">{row.name}</div><div className="mt-1 text-2xl font-black">{row.bot ? `$${Math.round(row.bot.equity).toLocaleString()}` : "—"}</div><div className="mt-1 text-sm font-black" style={{ color: row.bot?.pnl && row.bot.pnl >= 0 ? "#00966d" : "#d72d50" }}>{row.bot ? `${(row.bot.pnl_pct * 100).toFixed(2)}%` : "SYNC"}</div><div className="mt-4 border-t-2 border-black pt-3 text-[10px] font-bold uppercase">WF {row.wf} · WR {row.bot?.win_rate == null ? "—" : `${(row.bot.win_rate * 100).toFixed(1)}%`} · POS {row.positionCount}</div><div className="mt-3"><PositionChips positions={row.livePositions} accent="#111" /></div></div>)}</div>
        <div className="mt-8 border-4 border-black bg-[#b8f2e6] p-5 shadow-[8px_8px_0_#111]"><div className="mb-3 text-xs font-black uppercase">All live positions · {data.allPos.length}</div><PositionChips positions={data.allPos} accent="#111" /></div>
      </section>
    </main>
  );
}