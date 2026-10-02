import { useFleetData } from "@/hooks/useFleetData";
import { AnimatedStyle, DesignNav, FleetTotals, useBotRows, PositionChips } from "./DesignShared";

export default function Design1Vaudeville() {
  const data = useFleetData();
  const rows = useBotRows(data);
  return (
    <main className="relative min-h-screen overflow-hidden bg-[#071126] font-sans text-white">
      <AnimatedStyle>{`
        @keyframes d1float { 0%,100%{transform:translate3d(0,0,0) rotate(-3deg)} 50%{transform:translate3d(0,-18px,0) rotate(3deg)} }
        @keyframes d1spin { to{transform:rotate(360deg)} }
        @keyframes d1pulse { 0%,100%{opacity:.35;transform:scale(.92)} 50%{opacity:.8;transform:scale(1.08)} }
      `}</AnimatedStyle>
      <div className="pointer-events-none absolute -left-28 top-24 h-80 w-80 rounded-full bg-fuchsia-500/25 blur-3xl" style={{ animation: "d1pulse 6s ease-in-out infinite" }} />
      <div className="pointer-events-none absolute -right-20 top-1/3 h-96 w-96 rounded-full bg-cyan-400/20 blur-3xl" style={{ animation: "d1pulse 7s ease-in-out infinite reverse" }} />
      <DesignNav current={1} mode="ORBITAL SOCIAL CLUB" />
      <section className="relative mx-auto max-w-2xl px-5 pb-14 pt-10">
        <div className="relative mx-auto mb-8 flex h-56 w-56 items-center justify-center">
          <div className="absolute inset-0 rounded-full border border-cyan-200/20" style={{ animation: "d1spin 18s linear infinite" }} />
          <div className="absolute inset-7 rounded-full border border-dashed border-fuchsia-300/25" style={{ animation: "d1spin 11s linear infinite reverse" }} />
          <div className="absolute h-28 w-28 rounded-full bg-gradient-to-br from-cyan-300 to-fuchsia-500 opacity-70 blur-xl" />
          <div className="relative text-center"><div className="text-[10px] font-black uppercase tracking-[.3em] text-white/50">FLEET ORBIT</div><div className="mt-2 text-2xl font-black">LIVE DATA</div></div>
        </div>
        <FleetTotals data={data} className="text-center" />
        <div className="mt-10 grid gap-4 sm:grid-cols-3">
          {rows.map((row, i) => (
            <div key={row.id} className="relative" style={{ animation: `d1float ${4 + i}s ease-in-out infinite`, animationDelay: `${i * -1.3}s` }}>
              <div className="absolute -inset-1 rounded-[2rem] opacity-30 blur-xl" style={{ background: row.accent }} />
              <div className="relative rounded-[2rem] border border-white/15 bg-white/[.09] p-4 shadow-2xl backdrop-blur-xl">
                <div className="mb-5 flex items-center justify-between"><span className="text-3xl" style={{ color: row.accent }}>{row.icon}</span><span className="text-[9px] font-black uppercase" style={{ color: row.statusMeta.color }}>{row.statusMeta.label}</span></div>
                <div className="text-[10px] font-black uppercase tracking-widest text-white/50">{row.name}</div>
                <div className="mt-1 text-2xl font-black">{row.bot ? `$${Math.round(row.bot.equity).toLocaleString()}` : "—"}</div>
                <div className="mt-1 text-sm font-bold" style={{ color: row.bot?.pnl && row.bot.pnl >= 0 ? "#7dffb2" : "#ff9aaa" }}>{row.bot ? `${row.bot.pnl >= 0 ? "+" : ""}${(row.bot.pnl_pct * 100).toFixed(2)}%` : "SYNCING"}</div>
                <div className="mt-4 text-[9px] text-white/40">WF {row.wf} · WR {row.bot?.win_rate == null ? "—" : `${(row.bot.win_rate * 100).toFixed(1)}%`}</div>
                <div className="mt-3"><PositionChips positions={row.livePositions} accent={row.accent} /></div>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-8 rounded-full border border-white/10 bg-black/20 px-4 py-3 text-center text-[10px] font-bold uppercase tracking-[.18em] text-white/45">Every bot is a planet · every position is a moon · tap a card in the live app to explore</div>
      </section>
    </main>
  );
}