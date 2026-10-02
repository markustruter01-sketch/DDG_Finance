import { useFleetData } from "@/hooks/useFleetData";
import { AnimatedStyle, BotLine, DesignNav, FleetTotals, useBotRows, PositionChips } from "./DesignShared";

export default function Design3MissionControl() {
  const data = useFleetData();
  const rows = useBotRows(data);
  return (
    <main className="relative min-h-screen overflow-hidden bg-[#dfe8f3] font-sans text-[#102033]">
      <AnimatedStyle>{`
        @keyframes d3aurora { 0%,100%{transform:translate(0,0) rotate(0)} 50%{transform:translate(30px,-20px) rotate(12deg)} }
        @keyframes d3float { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-8px)} }
        @media (prefers-reduced-motion: reduce){*{animation:none!important}}
      `}</AnimatedStyle>
      <div className="pointer-events-none absolute -left-24 -top-32 h-96 w-96 rounded-full bg-cyan-300/50 blur-3xl" style={{ animation: "d3aurora 12s ease-in-out infinite" }} />
      <div className="pointer-events-none absolute -right-20 top-52 h-80 w-80 rounded-full bg-violet-300/50 blur-3xl" style={{ animation: "d3aurora 16s ease-in-out infinite reverse" }} />
      <DesignNav current={3} mode="AURORA GLASS / FLEET WEATHER" />
      <section className="relative mx-auto max-w-3xl px-4 py-8">
        <div className="mb-6 flex items-start justify-between"><div><div className="text-xs font-black uppercase tracking-[.28em] text-[#46617b]">Good afternoon, operator</div><h1 className="mt-2 text-4xl font-black tracking-[-.06em]">Your money has weather.</h1></div><div className="rounded-2xl border border-white/70 bg-white/45 px-3 py-2 text-right text-[10px] font-bold uppercase text-[#46617b] shadow-lg backdrop-blur-xl">Now<br /><strong className="text-lg text-[#102033]">{data.regime ?? "SYNC"}</strong></div></div>
        <div className="rounded-[2rem] border border-white/80 bg-white/45 p-6 shadow-[0_25px_80px_rgba(55,90,130,.18)] backdrop-blur-2xl"><FleetTotals data={data} /></div>
        <div className="mt-5 grid gap-4 md:grid-cols-3">
          {rows.map((row, i) => <div key={row.id} className="rounded-[1.75rem] border border-white/75 bg-white/45 p-4 shadow-xl backdrop-blur-xl" style={{ animation: `d3float ${4 + i}s ease-in-out infinite`, animationDelay: `${i * -1}s` }}><div className="flex items-center justify-between"><span className="text-2xl" style={{ color: row.accent }}>{row.icon}</span><span className="rounded-full bg-white/60 px-2 py-1 text-[9px] font-black uppercase" style={{ color: row.statusMeta.color }}>{row.statusMeta.label}</span></div><div className="mt-5 text-[10px] font-black uppercase tracking-widest text-[#46617b]">{row.name}</div><div className="mt-1 text-2xl font-black">{row.bot ? `$${Math.round(row.bot.equity).toLocaleString()}` : "—"}</div><div className="mt-1 text-sm font-bold" style={{ color: row.bot?.pnl && row.bot.pnl >= 0 ? "#09815c" : "#c53959" }}>{row.bot ? `${(row.bot.pnl_pct * 100).toFixed(2)}% · ${Math.round(row.bot.pnl).toLocaleString()}` : "Awaiting data"}</div><div className="mt-4 border-t border-[#46617b]/10 pt-3 text-[10px] text-[#46617b]">WF {row.wf} · {row.positionCount} strategy positions · WR {row.bot?.win_rate == null ? "—" : `${(row.bot.win_rate * 100).toFixed(1)}%`}</div><div className="mt-3"><PositionChips positions={row.livePositions} accent={row.accent} /></div></div>)}
        </div>
        <div className="mt-5 rounded-3xl border border-white/75 bg-white/40 p-5 shadow-xl backdrop-blur-xl"><div className="mb-3 text-[10px] font-black uppercase tracking-[.2em] text-[#46617b]">Live holdings · {data.allPos.length}</div><PositionChips positions={data.allPos} accent="#46617b" /></div>
      </section>
    </main>
  );
}