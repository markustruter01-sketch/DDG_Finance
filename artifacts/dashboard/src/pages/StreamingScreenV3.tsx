import { useMemo } from "react";
import {
  useStatusSummary,
  useKrakenFleetSummary,
  useKrakenPerformance,
  useOptionsState,
  useForexState,
  useVault,
  useForexVault,
  useJournal,
} from "@/hooks/use-trading";
import { useRealFeed } from "@/components/streaming/useRealFeed";
import { NewsIntelligence } from "@/components/streaming/NewsIntelligence";
import { GeminiThinking } from "@/components/streaming/GeminiThinking";
import { SalesTicker } from "@/components/streaming/SalesTicker";
import { AnimatedValue } from "@/components/streaming/AnimatedValue";

const C = {
  green: "#4ade80",
  red: "#f87171",
  orange: "#fb923c",
  cyan: "#22d3ee",
  violet: "#a78bfa",
  amber: "#fbbf24",
  slate: "rgba(148,163,184,0.5)",
  slateDim: "rgba(148,163,184,0.35)",
  white: "#ffffff",
};

const BOT_META = [
  { key: "oracle",      name: "Oracle",       icon: "🔮", color: "#8b5cf6", market: "Stocks" },
  { key: "davy-jones",  name: "Davy Jones",   icon: "⚓",  color: "#22d3ee", market: "Crypto" },
  { key: "blackbeard",  name: "Blackbeard",   icon: "🏴‍☠️", color: "#ef4444", market: "Crypto" },
  { key: "calypso",     name: "Calypso",      icon: "🌊",  color: "#3b82f6", market: "Crypto" },
  { key: "apex",        name: "Apex Predator",icon: "🎯",  color: "#f59e0b", market: "Options" },
  { key: "navigator",   name: "Navigator",    icon: "🧭",  color: "#a78bfa", market: "Forex" },
];

const BOT_COLORS: Record<string, string> = {
  "Oracle": "#8b5cf6",
  "Davy Jones": "#22d3ee",
  "Blackbeard": "#ef4444",
  "Calypso": "#3b82f6",
  "Apex Predator": "#f59e0b",
  "Navigator": "#a78bfa",
};

function fmtUsd(v: number, compact = false): string {
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (compact && abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
  if (compact && abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(1)}k`;
  return `${sign}$${abs.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
}

function fmtPnl(v: number, compact = false): string {
  const abs = Math.abs(v);
  const sign = v >= 0 ? "+" : "-";
  if (compact && abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
  if (compact && abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(1)}k`;
  return `${sign}$${abs.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
}

function pnlColor(v: number) {
  return v >= 0 ? C.green : C.red;
}

function Card({ children, className = "", style = {} }: { children: React.ReactNode; className?: string; style?: React.CSSProperties }) {
  return (
    <div
      className={`rounded-xl border bg-slate-900/70 ${className}`}
      style={{ borderColor: "rgba(255,255,255,0.07)", ...style }}
    >
      {children}
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[9px] uppercase tracking-widest font-bold mb-1.5" style={{ color: C.slate }}>
      {children}
    </div>
  );
}

function HeroBanner() {
  const { data: summary } = useStatusSummary();
  const { data: fleet } = useKrakenFleetSummary();
  const { data: optState } = useOptionsState();
  const { data: fxState } = useForexState();
  const { data: vault } = useVault();
  const { data: fxVault } = useForexVault();
  const { wins, losses, openPositions } = useRealFeed(50);

  const alpacaEq = summary?.portfolio_totals?.equity ?? 100_000;
  const krakenEq = fleet?.total_equity_usd ?? 300_000;
  const optEq = optState?.total_equity ?? 100_000;
  const fxEq = fxState?.total_equity ?? 100_000;
  const grandTotal = alpacaEq + krakenEq + optEq + fxEq;
  const startTotal = 800_000;
  const pnlUsd = grandTotal - startTotal;
  const pnlPct = startTotal > 0 ? ((grandTotal - startTotal) / startTotal) * 100 : 0;

  const totalTrades = wins + losses;
  const winRate = totalTrades > 0 ? (wins / totalTrades) * 100 : 0;

  const openCount = openPositions.length;
  const unrealisedPnl = openPositions.reduce((sum, p) => sum + p.pnlUsd, 0);

  const totalVaulted = (vault?.total_vaulted_usd ?? 0) + (fxVault?.vault_total_usd ?? 0);

  return (
    <div className="grid gap-2.5 shrink-0" style={{ gridTemplateColumns: "1fr 1fr 1fr 1fr" }}>
      <Card className="px-4 py-3 flex flex-col justify-center" style={{ borderColor: pnlPct >= 0 ? "rgba(74,222,128,0.2)" : "rgba(248,113,113,0.2)" }}>
        <div className="text-[9px] uppercase tracking-widest font-bold mb-1" style={{ color: C.slateDim }}>Combined P&L</div>
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="text-3xl font-mono font-black" style={{ color: pnlColor(pnlUsd), lineHeight: 1 }}>
            <AnimatedValue value={fmtPnl(pnlUsd)} />
          </span>
          <span className="text-lg font-mono font-semibold" style={{ color: pnlColor(pnlPct) }}>
            {pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(2)}%
          </span>
        </div>
        <div className="text-[9px] font-mono mt-1" style={{ color: C.slateDim }}>all-time vs $600k start</div>
      </Card>

      <Card className="px-4 py-3 flex flex-col justify-center" style={{ borderColor: "rgba(34,211,238,0.15)" }}>
        <div className="text-[9px] uppercase tracking-widest font-bold mb-1" style={{ color: C.slateDim }}>Total Capital</div>
        <div className="text-3xl font-mono font-black" style={{ color: C.cyan, lineHeight: 1 }}>
          <AnimatedValue value={fmtUsd(grandTotal)} />
        </div>
        <div className="text-[9px] font-mono mt-1" style={{ color: C.slateDim }}>fleet-wide balance</div>
      </Card>

      <Card className="px-4 py-3 flex flex-col justify-center" style={{ borderColor: "rgba(167,139,250,0.15)" }}>
        <div className="text-[9px] uppercase tracking-widest font-bold mb-1" style={{ color: C.slateDim }}>Open Positions</div>
        <div className="flex items-baseline gap-2">
          <span className="text-3xl font-mono font-black" style={{ color: C.violet, lineHeight: 1 }}>{openCount}</span>
          {openCount > 0 && (
            <span className="text-lg font-mono font-semibold" style={{ color: pnlColor(unrealisedPnl) }}>
              {fmtPnl(unrealisedPnl, true)}
            </span>
          )}
        </div>
        <div className="text-[9px] font-mono mt-1" style={{ color: C.slateDim }}>unrealised P&L</div>
      </Card>

      <Card className="px-4 py-3 flex flex-col justify-center" style={{ borderColor: "rgba(52,211,153,0.15)" }}>
        <div className="text-[9px] uppercase tracking-widest font-bold mb-1" style={{ color: C.slateDim }}>Growth Vault</div>
        <div className="text-3xl font-mono font-black" style={{ color: "#34d399", lineHeight: 1 }}>
          <AnimatedValue value={fmtUsd(totalVaulted)} />
        </div>
        <div className="text-[9px] font-mono mt-1" style={{ color: C.slateDim }}>
          {wins}W / {losses}L · {winRate.toFixed(1)}% win rate
        </div>
      </Card>
    </div>
  );
}

function WelcomeCard() {
  return (
    <Card className="px-4 py-2.5 flex items-center gap-3 shrink-0" style={{ borderColor: "rgba(167,139,250,0.12)" }}>
      <span style={{ fontSize: 20 }}>👋</span>
      <div>
        <span className="text-[12px] font-black uppercase tracking-wide mr-2" style={{ color: "#ddd6fe" }}>Welcome to AlgoEdge Live —</span>
        <span className="text-[12px] font-mono" style={{ color: "rgba(203,213,225,0.65)" }}>
          Six automated AI bots trading{" "}
          <span style={{ color: C.amber }}>Stocks</span>,{" "}
          <span style={{ color: C.cyan }}>Crypto</span>,{" "}
          <span style={{ color: C.violet }}>FOREX</span> &{" "}
          <span style={{ color: C.orange }}>Futures</span> 24/7.{" "}
          <span style={{ color: "#ddd6fe", fontWeight: 700 }}>Want your own? Message us — no experience needed.</span>
        </span>
      </div>
    </Card>
  );
}

function BotPnlCard({ meta, pnlToday, pnlAllTime, wins, losses, todayWins, todayLosses }: {
  meta: typeof BOT_META[number];
  pnlToday: number;
  pnlAllTime: number;
  wins: number;
  losses: number;
  todayWins: number;
  todayLosses: number;
}) {
  const hasTodayData = todayWins + todayLosses > 0;
  return (
    <div
      className="rounded-lg px-3 py-2.5 flex flex-col gap-1 shrink-0"
      style={{ border: `1px solid ${meta.color}22`, backgroundColor: "rgba(15,23,42,0.6)" }}
    >
      <div className="flex items-center gap-1.5">
        <span style={{ fontSize: 14 }}>{meta.icon}</span>
        <span className="text-[10px] font-black uppercase tracking-wider" style={{ color: meta.color }}>{meta.name}</span>
        <span className="ml-auto text-[8px] font-mono uppercase" style={{ color: C.slateDim }}>{meta.market}</span>
      </div>

      <div className="grid grid-cols-2 gap-1.5">
        <div>
          <div className="text-[7px] uppercase tracking-widest font-bold mb-0.5" style={{ color: C.slateDim }}>Today</div>
          <div className="text-[14px] font-mono font-black" style={{ color: pnlColor(pnlToday) }}>
            {fmtPnl(pnlToday, true)}
          </div>
          <div className="text-[8px] font-mono" style={{ color: C.slateDim }}>
            {hasTodayData ? `${todayWins}W / ${todayLosses}L` : "—"}
          </div>
        </div>
        <div>
          <div className="text-[7px] uppercase tracking-widest font-bold mb-0.5" style={{ color: C.slateDim }}>All-Time</div>
          <div className="text-[14px] font-mono font-black" style={{ color: pnlColor(pnlAllTime) }}>
            {fmtPnl(pnlAllTime, true)}
          </div>
          <div className="text-[8px] font-mono" style={{ color: C.slateDim }}>
            {wins}W / {losses}L
          </div>
        </div>
      </div>
    </div>
  );
}

function LeftColumn() {
  const { data: summary } = useStatusSummary();
  const { data: journal } = useJournal();
  const { data: djPerf } = useKrakenPerformance("davy-jones");
  const { data: bbPerf } = useKrakenPerformance("blackbeard");
  const { data: caPerf } = useKrakenPerformance("calypso");
  const { data: optState } = useOptionsState();
  const { data: fxState } = useForexState();
  const { trades: allTrades } = useRealFeed(200);

  const alpacaStart = summary?.portfolio_totals?.initial_capital ?? 100_000;
  const alpacaEq = summary?.portfolio_totals?.equity ?? alpacaStart;
  const oraclePnlAll = alpacaEq - alpacaStart;
  const oracleWins = journal?.summary?.wins ?? 0;
  const oracleLosses = journal?.summary?.losses ?? 0;

  const apexStart = optState?.starting_capital ?? 100_000;
  const apexEq = optState?.total_equity ?? optState?.paper_equity ?? apexStart;
  const apexPnlAll = apexEq - apexStart;

  const fxStart = fxState?.starting_capital ?? 100_000;
  const fxEq = fxState?.total_equity ?? fxState?.paper_equity ?? fxStart;
  const navPnlAll = fxEq - fxStart;

  const todayByBot = useMemo(() => {
    const cutoff = Date.now() - 24 * 60 * 60 * 1000;
    const map: Record<string, { pnl: number; wins: number; losses: number }> = {};
    for (const t of allTrades) {
      if (!t.date || new Date(t.date).getTime() < cutoff) continue;
      if (!map[t.bot]) map[t.bot] = { pnl: 0, wins: 0, losses: 0 };
      map[t.bot].pnl += t.pnlUsd;
      if (t.isWin) map[t.bot].wins++; else map[t.bot].losses++;
    }
    return map;
  }, [allTrades]);

  function todayStats(botName: string) {
    return todayByBot[botName] ?? { pnl: 0, wins: 0, losses: 0 };
  }

  const oToday = todayStats("Oracle");
  const djToday = todayStats("Davy Jones");
  const bbToday = todayStats("Blackbeard");
  const caToday = todayStats("Calypso");
  const apToday = todayStats("Apex Predator");
  const navToday = todayStats("Navigator");

  const bots = [
    { meta: BOT_META[0], pnlToday: oToday.pnl, pnlAllTime: oraclePnlAll, wins: oracleWins, losses: oracleLosses, todayWins: oToday.wins, todayLosses: oToday.losses },
    { meta: BOT_META[1], pnlToday: djToday.pnl, pnlAllTime: djPerf?.total_pnl_usd ?? 0, wins: djPerf?.win_count ?? 0, losses: djPerf?.loss_count ?? 0, todayWins: djToday.wins, todayLosses: djToday.losses },
    { meta: BOT_META[2], pnlToday: bbToday.pnl, pnlAllTime: bbPerf?.total_pnl_usd ?? 0, wins: bbPerf?.win_count ?? 0, losses: bbPerf?.loss_count ?? 0, todayWins: bbToday.wins, todayLosses: bbToday.losses },
    { meta: BOT_META[3], pnlToday: caToday.pnl, pnlAllTime: caPerf?.total_pnl_usd ?? 0, wins: caPerf?.win_count ?? 0, losses: caPerf?.loss_count ?? 0, todayWins: caToday.wins, todayLosses: caToday.losses },
    { meta: BOT_META[4], pnlToday: apToday.pnl, pnlAllTime: apexPnlAll, wins: optState?.total_wins ?? 0, losses: (optState?.total_trades ?? 0) - (optState?.total_wins ?? 0), todayWins: apToday.wins, todayLosses: apToday.losses },
    { meta: BOT_META[5], pnlToday: navToday.pnl, pnlAllTime: navPnlAll, wins: fxState?.total_wins ?? 0, losses: (fxState?.total_trades ?? 0) - (fxState?.total_wins ?? 0), todayWins: navToday.wins, todayLosses: navToday.losses },
  ];

  return (
    <div className="flex flex-col gap-2 h-full overflow-hidden">
      <SectionLabel>Per-Bot Performance</SectionLabel>
      <div className="flex flex-col gap-1.5 flex-1 overflow-hidden">
        {bots.map((b) => (
          <BotPnlCard key={b.meta.key} {...b} />
        ))}
      </div>
    </div>
  );
}

function CenterColumn() {
  const { wins, losses, trades, openPositions } = useRealFeed(50);
  const totalTrades = wins + losses;
  const winRate = totalTrades > 0 ? (wins / totalTrades) * 100 : 0;

  const cutoff24h = Date.now() - 24 * 60 * 60 * 1000;
  const trades24h = trades.filter(t => new Date(t.date).getTime() > cutoff24h);
  const wins24h = trades24h.filter(t => t.isWin).length;
  const losses24h = trades24h.filter(t => !t.isWin).length;
  const wr24h = (wins24h + losses24h) > 0 ? (wins24h / (wins24h + losses24h)) * 100 : 0;

  const unrealisedPnl = openPositions.reduce((sum, p) => sum + p.pnlUsd, 0);

  return (
    <div className="flex flex-col gap-2 h-full overflow-hidden">
      <SectionLabel>Win / Loss Record</SectionLabel>

      <div className="grid grid-cols-2 gap-1.5 shrink-0">
        <Card className="px-3 py-2 text-center" style={{ borderColor: "rgba(74,222,128,0.2)" }}>
          <div className="text-[8px] uppercase tracking-widest font-bold mb-0.5" style={{ color: "rgba(74,222,128,0.5)" }}>All-Time Wins</div>
          <div className="text-2xl font-mono font-black" style={{ color: C.green }}>{wins}</div>
        </Card>
        <Card className="px-3 py-2 text-center" style={{ borderColor: "rgba(248,113,113,0.2)" }}>
          <div className="text-[8px] uppercase tracking-widest font-bold mb-0.5" style={{ color: "rgba(248,113,113,0.5)" }}>All-Time Losses</div>
          <div className="text-2xl font-mono font-black" style={{ color: C.red }}>{losses}</div>
        </Card>
        <Card className="px-3 py-2 text-center" style={{ borderColor: "rgba(74,222,128,0.12)" }}>
          <div className="text-[8px] uppercase tracking-widest font-bold mb-0.5" style={{ color: "rgba(74,222,128,0.35)" }}>Today Wins</div>
          <div className="text-xl font-mono font-black" style={{ color: C.green }}>{wins24h}</div>
        </Card>
        <Card className="px-3 py-2 text-center" style={{ borderColor: "rgba(248,113,113,0.12)" }}>
          <div className="text-[8px] uppercase tracking-widest font-bold mb-0.5" style={{ color: "rgba(248,113,113,0.35)" }}>Today Losses</div>
          <div className="text-xl font-mono font-black" style={{ color: C.red }}>{losses24h}</div>
        </Card>
      </div>

      <div className="grid grid-cols-2 gap-1.5 shrink-0">
        <Card className="px-3 py-1.5 text-center" style={{ borderColor: "rgba(251,191,36,0.15)" }}>
          <div className="text-[8px] uppercase tracking-widest font-bold mb-0.5" style={{ color: "rgba(251,191,36,0.5)" }}>All-Time Win Rate</div>
          <div className="text-lg font-mono font-black" style={{ color: C.amber }}>{winRate.toFixed(1)}%</div>
        </Card>
        <Card className="px-3 py-1.5 text-center" style={{ borderColor: "rgba(251,191,36,0.1)" }}>
          <div className="text-[8px] uppercase tracking-widest font-bold mb-0.5" style={{ color: "rgba(251,191,36,0.4)" }}>Today Win Rate</div>
          <div className="text-lg font-mono font-black" style={{ color: C.amber }}>{wr24h.toFixed(1)}%</div>
        </Card>
      </div>

      {openPositions.length > 0 && (
        <div className="shrink-0">
          <div className="text-[8px] uppercase tracking-widest font-bold mb-1" style={{ color: C.slateDim }}>
            Open Positions ({openPositions.length}) · Unrealised {fmtPnl(unrealisedPnl, true)}
          </div>
          <div className="flex flex-col gap-0.5">
            {openPositions.slice(0, 4).map((p) => (
                <div
                  key={p.id}
                  className="flex items-center gap-2 px-3 py-1.5 rounded-lg"
                  style={{ backgroundColor: p.pnlUsd >= 0 ? "rgba(74,222,128,0.04)" : "rgba(248,113,113,0.04)", border: `1px solid ${p.pnlUsd >= 0 ? "rgba(74,222,128,0.08)" : "rgba(248,113,113,0.08)"}` }}
                >
                  <span style={{ fontSize: 12 }}>{p.icon}</span>
                  <span className="font-mono font-bold text-[10px] truncate flex-1" style={{ color: "rgba(203,213,225,0.8)" }}>{p.symbol}</span>
                  {p.side && (
                    <span className="text-[8px] font-mono font-bold px-1 py-0.5 rounded" style={{
                      color: p.side === "short" ? C.red : C.green,
                      backgroundColor: p.side === "short" ? "rgba(248,113,113,0.1)" : "rgba(74,222,128,0.1)",
                    }}>
                      {p.side.toUpperCase()}
                    </span>
                  )}
                  <span className="text-[11px] font-mono font-bold shrink-0" style={{ color: pnlColor(p.pnlUsd) }}>
                    {fmtPnl(p.pnlUsd, true)}
                  </span>
                  <span className="h-1.5 w-1.5 rounded-full shrink-0" style={{ backgroundColor: C.cyan, boxShadow: `0 0 4px ${C.cyan}` }} />
                </div>
            ))}
          </div>
        </div>
      )}

      <div className="flex flex-col gap-1 flex-1 min-h-0">
        <div className="text-[8px] uppercase tracking-widest font-bold" style={{ color: C.slateDim }}>Recent Closed Trades</div>
        <div className="flex flex-col gap-0.5 flex-1 overflow-hidden">
          {trades.length === 0 ? (
            <div className="text-[11px] font-mono text-center py-4" style={{ color: C.slateDim }}>No trades yet</div>
          ) : (
            trades.map((t) => (
              <div
                key={t.id}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg shrink-0"
                style={{ backgroundColor: t.isWin ? "rgba(74,222,128,0.04)" : "rgba(248,113,113,0.04)", border: `1px solid ${t.isWin ? "rgba(74,222,128,0.07)" : "rgba(248,113,113,0.07)"}` }}
              >
                <span style={{ fontSize: 12 }}>{t.icon}</span>
                <span className="font-mono font-bold text-[10px] truncate flex-1" style={{ color: "rgba(203,213,225,0.8)" }}>{t.symbol}</span>
                {t.side && (
                  <span className="text-[8px] font-mono font-bold px-1 py-0.5 rounded" style={{
                    color: t.side === "short" ? C.red : C.green,
                    backgroundColor: t.side === "short" ? "rgba(248,113,113,0.1)" : "rgba(74,222,128,0.1)",
                  }}>
                    {t.side.toUpperCase()}
                  </span>
                )}
                <span className="text-[11px] font-mono font-bold shrink-0" style={{ color: t.isWin ? C.green : C.red }}>
                  {t.pnlUsd !== 0 ? fmtPnl(t.pnlUsd, true) : `${t.pnlPct >= 0 ? "+" : ""}${t.pnlPct.toFixed(2)}%`}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function RightColumn() {
  const { data: vault } = useVault();
  const { data: fxVault } = useForexVault();
  const totalVaulted = (vault?.total_vaulted_usd ?? 0) + (fxVault?.vault_total_usd ?? 0);
  const totalSweeps = (vault?.total_sweeps ?? 0) + (fxVault?.sweeps?.length ?? 0);
  const vaulted24h = vault?.vaulted_24h ?? 0;

  return (
    <div className="flex flex-col gap-2 h-full overflow-hidden">
      <div className="shrink-0">
        <SectionLabel>News Intelligence</SectionLabel>
        <NewsIntelligence />
      </div>

      <div className="flex-1 flex flex-col min-h-0">
        <SectionLabel>AI Fleet Commander</SectionLabel>
        <div className="flex-1 min-h-0">
          <GeminiThinking />
        </div>
      </div>

      <Card className="px-4 py-3 shrink-0" style={{ borderColor: "rgba(52,211,153,0.2)" }}>
        <div className="flex items-center gap-2 mb-2">
          <span style={{ fontSize: 14 }}>🏦</span>
          <span className="text-[10px] font-black uppercase tracking-wider" style={{ color: "#34d399" }}>Growth Vault</span>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <div className="text-[7px] uppercase tracking-widest font-bold mb-0.5" style={{ color: "rgba(52,211,153,0.5)" }}>Total Vaulted</div>
            <div className="text-[16px] font-mono font-black" style={{ color: "#34d399" }}>{fmtUsd(totalVaulted)}</div>
          </div>
          <div>
            <div className="text-[7px] uppercase tracking-widest font-bold mb-0.5" style={{ color: "rgba(52,211,153,0.5)" }}>Sweeps</div>
            <div className="text-[16px] font-mono font-black" style={{ color: "#34d399" }}>{totalSweeps}</div>
          </div>
          {vaulted24h > 0 && (
            <div className="col-span-2">
              <div className="text-[7px] uppercase tracking-widest font-bold mb-0.5" style={{ color: "rgba(52,211,153,0.5)" }}>Today</div>
              <div className="text-[14px] font-mono font-bold" style={{ color: "#4ade80" }}>+{fmtUsd(vaulted24h)}</div>
            </div>
          )}
        </div>
        <div className="text-[9px] font-mono mt-1.5 leading-snug" style={{ color: "rgba(52,211,153,0.4)" }}>
          20% of every winning trade auto-vaulted across all bots.
        </div>
      </Card>
    </div>
  );
}

export default function StreamingScreenV3() {
  return (
    <div
      style={{
        height: "100%",
        width: "100%",
        backgroundColor: "#020617",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      <div className="flex-1 flex flex-col p-3 gap-2.5 min-h-0 overflow-hidden">
        <HeroBanner />
        <WelcomeCard />

        <div className="flex-1 grid gap-2.5 min-h-0 overflow-hidden" style={{ gridTemplateColumns: "270px 1fr 300px" }}>
          <div className="min-h-0 overflow-hidden">
            <LeftColumn />
          </div>

          <div className="min-h-0 overflow-hidden">
            <CenterColumn />
          </div>

          <div className="min-h-0 overflow-hidden">
            <RightColumn />
          </div>
        </div>
      </div>

      <SalesTicker />
    </div>
  );
}
