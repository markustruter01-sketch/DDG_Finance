import { useFleetData } from "@/hooks/useFleetData";
import { AnimatedStyle, BotLine, DesignNav, FleetTotals, getBotRows } from "./DesignShared";

export default function Design5SpaceFleet() {
  const data = useFleetData();
  const rows = getBotRows(data);
  return (
    <main className="relative min-h-screen overflow-hidden bg-[#02030a] font-mono text-white">
      <AnimatedStyle>{`
        @keyframes d5radar { to{transform:rotate(360deg)} }
        @keyframes d5stars { from{transform:translateY(0)} to{transform:translateY(-80px)} }
        @keyframes d5ping { 0%,100%{transform:scale(.65);opacity:.3} 50%{transform:scale(1.25);opacity:1} }
      `}</AnimatedStyle>
      <div className="pointer-events-none absolute inset-0 opacity-30" style={{ backgroundImage: "radial-gradient(#45d8ff 1px,transparent 1px)", backgroundSize: "34px 34px", animation: "d5stars 12s linear infinite" }} />
      <DesignNav current={5} mode="ALIEN COMMAND / SECTOR 07" />
      <section className="relative mx-auto max-w-3xl px-4 py-7">
        <div className="grid gap-6 md:grid-cols-[.8fr_1.2fr] md:items-center">
          <div className="relative mx-auto flex h-64 w-64 items-center justify-center rounded-full border border-cyan-300/30 bg-cyan-400/5" style={{ backgroundImage: "linear-gradient(90deg,transparent 49.5%,#45d8ff55 50%,transparent 50.5%),linear-gradient(0deg,transparent 49.5%,#45d8ff55 50%,transparent 50.5%)" }}>
            <div className="absolute inset-0 rounded-full border border-cyan-300/20" style={{ animation: "d5radar 5s linear infinite" }} /><div className="absolute inset-7 rounded-full border border-cyan-300/20" /><div className="absolute inset-16 rounded-full border border-cyan-300/20" />
            {rows.map((row, i) => <span key={row.id} className="absolute h-3 w-3 rounded-full" style={{ left: `${32 + (i % 2) * 38}%`, top: `${28 + i * 15}%`, background: row.accent, boxShadow: `0 0 16px ${row.accent}`, animation: `d5ping ${2 + i / 2}s ease-in-out infinite` }} />)}
            <div className="relative text-center"><div className="text-[9px] uppercase tracking-[.35em] text-cyan-200/60">SECTOR 07</div><div className="mt-2 text-2xl font-black text-cyan-100">{data.regime ?? "SCANNING"}</div></div>
          </div>
          <div><FleetTotals data={data} /><div className="mt-5 grid grid-cols-3 gap-2 text-center text-[10px] uppercase text-cyan-100/50"><div className="border border-cyan-300/20 p-3">Bots<br /><strong className="text-xl text-white">{rows.length}</strong></div><div className="border border-cyan-300/20 p-3">Cargo<br /><strong className="text-xl text-white">{data.allPos.length}</strong></div><div className="border border-cyan-300/20 p-3">WF checks<br /><strong className="text-xl text-white">{rows.filter(r => r.wf === "PASS").length}</strong></div></div></div>
        </div>
        <div className="mt-8 space-y-3">{rows.map(row => <BotLine key={row.id} row={row} />)}</div>
        <div className="mt-5 border border-cyan-300/20 bg-cyan-300/[.04] p-4 text-[10px] uppercase tracking-[.2em] text-cyan-100/45">Telemetry stream · last update {data.lastCycle ? new Date(data.lastCycle).toLocaleTimeString() : "waiting"} · kill switch {data.killTripped ? "TRIPPED" : "ARMED"}</div>
      </section>
    </main>
  );
}