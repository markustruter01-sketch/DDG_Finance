import { useFleetData, getBotStatus, fmtEq, fmtPct, fmtDollar, type BotStatus } from "@/hooks/useFleetData";

export type DesignFleetData = ReturnType<typeof useFleetData>;

export const BOT_META = [
  { id: "spy_qqq_trend", name: "SPY / QQQ", pilot: "Moe", icon: "◉", accent: "#ffd166" },
  { id: "oracle", name: "Asia Pacific", pilot: "Larry", icon: "◈", accent: "#b794f4" },
  { id: "jerome_macro", name: "Emerging Markets", pilot: "Curly", icon: "✦", accent: "#ff6b8a" },
] as const;

export const STATUS_META: Record<BotStatus, { label: string; color: string }> = {
  LIVE: { label: "LIVE", color: "#54f28b" },
  MKT_CLOSED: { label: "MARKET CLOSED", color: "#8b95ad" },
  DOWN: { label: "DOWN", color: "#ff5d73" },
  IDLE: { label: "IDLE", color: "#ffd166" },
};

export function getBotRows(data: DesignFleetData) {
  const positions = data.positionsByBot;
  return BOT_META.map((meta) => {
    const bot = meta.id === "oracle" ? data.oracle : meta.id === "jerome_macro" ? data.jerome : data.spy;
    const status = getBotStatus(bot, data.mktOpen, false);
    const livePositions = positions?.[meta.id]?.positions ?? [];
    return {
      ...meta,
      bot,
      status,
      statusMeta: STATUS_META[status],
      wf: data.wfMap.get(meta.id) ?? "INSUFFICIENT_DATA",
      livePositions,
       positionCount: positions?.[meta.id]?.strategy_count ?? bot?.positions ?? null,
    };
  });
}

export function DesignNav({ current, mode }: { current: number; mode: string }) {
  return (
    <nav className="flex items-center gap-2 overflow-x-auto border-b border-white/10 bg-black/25 px-4 py-3 backdrop-blur-xl">
      <span className="mr-2 shrink-0 text-[10px] font-black uppercase tracking-[0.25em] text-white/45">{mode}</span>
      {[1, 2, 3, 4, 5].map((n) => (
        <a key={n} href={`/design/${n}`} className={`shrink-0 rounded-full px-3 py-1 text-[10px] font-bold transition ${current === n ? "bg-white text-black" : "text-white/45 hover:bg-white/10 hover:text-white"}`}>
          0{n}
        </a>
      ))}
      <a href="/" className="ml-auto shrink-0 text-[10px] font-bold text-white/30 hover:text-white">HOME ↗</a>
    </nav>
  );
}

export function FleetTotals({ data, className = "" }: { data: DesignFleetData; className?: string }) {
  const total = data.total;
  const positive = total?.pnl == null ? true : total.pnl >= 0;
  return (
    <div className={className}>
      <div className="text-[10px] font-bold uppercase tracking-[0.25em] text-white/40">Fleet total assets</div>
      <div className="mt-2 flex flex-wrap items-baseline gap-3">
        <span className="text-5xl font-black tracking-[-0.08em] text-white">{total ? fmtEq(total.equity) : "—"}</span>
        <span className={`text-lg font-black ${positive ? "text-emerald-300" : "text-rose-300"}`}>
          {total ? `${fmtDollar(total.pnl)} ${fmtPct(total.pnl_pct)}` : "awaiting signal"}
        </span>
      </div>
      <div className="mt-3 flex flex-wrap gap-2 text-[10px] font-bold uppercase tracking-wider text-white/50">
        <span className="rounded-full bg-white/10 px-3 py-1">Regime · {data.regime ?? "SYNCING"}</span>
        <span className={`rounded-full px-3 py-1 ${
          data.killTripped == null
            ? "bg-amber-400/20 text-amber-200"
            : data.killTripped
              ? "bg-rose-400/20 text-rose-200"
              : "bg-emerald-400/15 text-emerald-200"
        }`}>
          Kill switch · {data.killTripped == null ? "UNKNOWN" : data.killTripped ? "TRIPPED" : "ARMED"}
        </span>
      </div>
    </div>
  );
}

export function PositionChips({ positions, accent = "#fff" }: { positions: DesignFleetData["allPos"]; accent?: string }) {
  if (!positions.length) return <span className="text-[10px] text-white/30">No live cargo</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {positions.map((p) => (
        <span key={`${p.bot_id}-${p.symbol}`} className="rounded-full border px-2 py-1 text-[10px] font-bold tabular-nums" style={{ color: accent, borderColor: `${accent}55`, background: `${accent}14` }}>
          {p.symbol} {p.unrealized_plpc >= 0 ? "+" : ""}{(p.unrealized_plpc * 100).toFixed(1)}%
        </span>
      ))}
    </div>
  );
}

export function BotLine({ row, compact = false }: { row: ReturnType<typeof getBotRows>[number]; compact?: boolean }) {
  const pnl = row.bot?.pnl ?? null;
  return (
    <div className={`relative overflow-hidden rounded-2xl border border-white/10 bg-white/[0.06] ${compact ? "p-3" : "p-4"}`}>
      <div className="absolute inset-y-0 left-0 w-1" style={{ background: row.accent, boxShadow: `0 0 18px ${row.accent}` }} />
      <div className="flex items-center gap-2 pl-2">
        <span className="text-xl" style={{ color: row.accent }}>{row.icon}</span>
        <div className="min-w-0">
          <div className="truncate text-xs font-black uppercase tracking-wider text-white">{row.name}</div>
          <div className="text-[10px] text-white/40">{row.pilot} · {row.positionCount} positions · WF {row.wf ?? "—"}</div>
        </div>
        <span className="ml-auto flex items-center gap-1 text-[9px] font-black uppercase" style={{ color: row.statusMeta.color }}>
          <i className="h-1.5 w-1.5 rounded-full" style={{ background: row.statusMeta.color, boxShadow: `0 0 8px ${row.statusMeta.color}` }} />{row.statusMeta.label}
        </span>
      </div>
      <div className="mt-3 flex items-baseline gap-2 pl-2">
         <span className={`${compact ? "text-xl" : "text-2xl"} font-black tabular-nums text-white`}>{fmtEq(row.bot?.equity)}</span>
         <span className={`text-sm font-black ${pnl == null ? "text-white/40" : pnl >= 0 ? "text-emerald-300" : "text-rose-300"}`}>{fmtPct(row.bot?.pnl_pct)}</span>
         <span className="text-[10px] text-white/40">{fmtDollar(pnl)} · WR {row.bot?.win_rate == null ? "—" : `${(row.bot.win_rate * 100).toFixed(1)}%`}</span>
      </div>
      <div className="mt-3 pl-2"><PositionChips positions={row.livePositions} accent={row.accent} /></div>
    </div>
  );
}

export function AnimatedStyle({ children }: { children: string }) {
  return <style dangerouslySetInnerHTML={{ __html: children }} />;
}