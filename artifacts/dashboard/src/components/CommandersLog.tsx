import { useMemo } from "react";
import { cn } from "@/lib/utils";
import {
  useRecentTrades, useJournal,
  useKrakenStatus, useKrakenPerformance,
  useOptionsState, useForexState,
  type RecentTradeItem,
} from "@/hooks/use-trading";
import {
  computeStreak, computeXP, getRank, getNextRank, StreakChip,
  ORACLE_RANKS, KRAKEN_RANKS, OPTIONS_RANKS, FOREX_RANKS,
  BOT_THEMES, type KrakenTradeEntry,
} from "@/lib/dashboard-shared";
import { Trophy, Zap } from "lucide-react";

export function CommandersLog() {
  const { data: recentTrades } = useRecentTrades(20);
  const { data: journal } = useJournal();
  const djStatus = useKrakenStatus("davy-jones");
  const bbStatus = useKrakenStatus("blackbeard");
  const caStatus = useKrakenStatus("calypso");
  const djPerf = useKrakenPerformance("davy-jones");
  const bbPerf = useKrakenPerformance("blackbeard");
  const caPerf = useKrakenPerformance("calypso");
  const { data: optState } = useOptionsState();
  const { data: fxState } = useForexState();

  const oracleStreak = useMemo(() => computeStreak(recentTrades?.trades ?? []), [recentTrades?.trades]);
  const oracleWins = journal?.summary?.wins ?? 0;
  const oracleTotal = journal?.summary?.total ?? 0;
  const oracleXP = computeXP(oracleWins, oracleTotal);
  const oracleRank = getRank(oracleXP, ORACLE_RANKS);

  const krakenBots = [
    { id: "davy-jones", status: djStatus.data, perf: djPerf.data },
    { id: "blackbeard", status: bbStatus.data, perf: bbPerf.data },
    { id: "calypso", status: caStatus.data, perf: caPerf.data },
  ];

  const optionsWins = optState?.total_wins ?? 0;
  const optionsTotal = optState?.total_trades ?? 0;
  const optionsXP = computeXP(optionsWins, optionsTotal);
  const optionsRank = getRank(optionsXP, OPTIONS_RANKS);
  const optionsStreak = { count: 0, direction: "none" as const };

  const forexWins = fxState?.total_wins ?? 0;
  const forexTotal = fxState?.total_trades ?? 0;
  const forexXP = computeXP(forexWins, forexTotal);
  const forexRank = getRank(forexXP, FOREX_RANKS);
  const forexStreak = { count: 0, direction: "none" as const };

  const entries = [
    {
      name: "Oracle",
      icon: "🔮",
      accent: "#818cf8",
      streak: oracleStreak,
      xp: oracleXP,
      rank: oracleRank,
      wins: oracleWins,
      total: oracleTotal,
      ranks: ORACLE_RANKS,
    },
    ...krakenBots.map((b) => {
      const t = BOT_THEMES[b.id] ?? BOT_THEMES["davy-jones"];
      const recentKrTrades = [...(b.status?.recent_trades ?? [])].reverse();
      const streak = computeStreak(recentKrTrades);
      const wins = b.perf?.win_count ?? 0;
      const total = b.perf?.total_trades ?? 0;
      const xp = computeXP(wins, total);
      const rank = getRank(xp, KRAKEN_RANKS);
      return {
        name: b.status?.bot_name ?? b.id.replace("-", " "),
        icon: t.icon,
        accent: t.accent,
        streak,
        xp,
        rank,
        wins,
        total,
        ranks: KRAKEN_RANKS,
      };
    }),
    {
      name: "Apex Predator",
      icon: "🎯",
      accent: "#ef4444",
      streak: optionsStreak,
      xp: optionsXP,
      rank: optionsRank,
      wins: optionsWins,
      total: optionsTotal,
      ranks: OPTIONS_RANKS,
    },
    {
      name: "Navigator",
      icon: "🧭",
      accent: "#14b8a6",
      streak: forexStreak,
      xp: forexXP,
      rank: forexRank,
      wins: forexWins,
      total: forexTotal,
      ranks: FOREX_RANKS,
    },
  ];

  const recentKills = useMemo(() => {
    const kills: { agent: string; icon: string; accent: string; symbol: string; pnlPct: number; side: string; ts: string }[] = [];
    (recentTrades?.trades ?? []).forEach((t: RecentTradeItem) => {
      if (t.pnl_pct != null && t.pnl_pct > 0) {
        kills.push({ agent: "Oracle", icon: "🔮", accent: "#818cf8", symbol: t.symbol ?? "?", pnlPct: t.pnl_pct, side: "long", ts: t.closed_at ?? "" });
      }
    });
    krakenBots.forEach((b) => {
      const t = BOT_THEMES[b.id] ?? BOT_THEMES["davy-jones"];
      (b.status?.recent_trades ?? []).forEach((tr: KrakenTradeEntry) => {
        if (tr.pnl_pct != null && tr.pnl_pct > 0) {
          kills.push({ agent: b.status?.bot_name ?? b.id, icon: t.icon, accent: t.accent, symbol: tr.symbol ?? "?", pnlPct: tr.pnl_pct, side: tr.side ?? "long", ts: tr.closed_at ?? "" });
        }
      });
    });
    kills.sort((a, b) => b.pnlPct - a.pnlPct);
    return kills.slice(0, 8);
  }, [recentTrades?.trades, djStatus.data, bbStatus.data, caStatus.data]);

  return (
    <div className="rounded-2xl border border-amber-500/15 bg-gradient-to-r from-slate-950/90 via-amber-950/5 to-slate-950/90 p-4 shadow-[0_0_40px_rgba(245,158,11,0.04)]">
      <div className="flex items-center gap-2 mb-3">
        <Trophy className="h-3.5 w-3.5 text-amber-400" />
        <span className="text-[10px] uppercase font-bold tracking-widest text-amber-400/80">Commander&apos;s Log</span>
        <span className="text-[8px] text-muted-foreground/40 ml-auto font-mono">{entries.length} agents</span>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3">
        {entries.map((e) => {
          const winRate = e.total > 0 ? ((e.wins / e.total) * 100).toFixed(0) : "—";
          const next = getNextRank(e.xp, e.ranks);
          const progress = next
            ? Math.min(((e.xp - e.rank.xp) / (next.xp - e.rank.xp)) * 100, 100)
            : 100;
          return (
            <div
              key={e.name}
              className="rounded-xl border border-white/5 bg-slate-900/60 p-3 space-y-2"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span className="text-sm">{e.icon}</span>
                  <span className="text-[10px] font-bold text-white capitalize truncate">{e.name}</span>
                </div>
                <StreakChip count={e.streak.count} direction={e.streak.direction} />
              </div>
              <div className="flex items-center gap-1.5">
                <span className={cn("text-[9px] font-bold", e.rank.tw)}>
                  {e.rank.icon} {e.rank.label}
                </span>
              </div>
              <div className="h-1 bg-slate-800 rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-1000 ease-out"
                  style={{ backgroundColor: e.accent, width: `${progress}%` }}
                />
              </div>
              <div className="flex items-center justify-between text-[8px] text-muted-foreground/50 font-mono">
                <span>{e.xp.toLocaleString()} XP</span>
                <span>{winRate !== "—" ? `${winRate}% WR` : "— WR"} · {e.total} trades</span>
              </div>
            </div>
          );
        })}
      </div>
      {recentKills.length > 0 && (
        <div className="mt-3 pt-3 border-t border-amber-500/10">
          <div className="flex items-center gap-2 mb-2">
            <Zap className="h-3 w-3 text-amber-400/60" />
            <span className="text-[9px] uppercase font-bold tracking-wider text-amber-400/50">Recent Kills</span>
          </div>
          <div className="flex flex-wrap gap-1.5 max-h-20 overflow-y-auto scrollbar-thin">
            {recentKills.map((k, i) => (
              <div key={`${k.agent}-${k.symbol}-${i}`} className="flex items-center gap-1 rounded-lg bg-slate-800/60 border border-white/5 px-2 py-1">
                <span className="text-[10px]">{k.icon}</span>
                <span className="text-[9px] font-mono text-white/70">{k.symbol.replace("/USD", "")}</span>
                <span className="text-[9px] font-mono font-bold text-green-400">+{k.pnlPct.toFixed(2)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
