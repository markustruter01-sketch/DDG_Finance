import { useWeeklyReview, usePortfolio, useFleetEquity, useBotRegistry } from "@/hooks/use-trading";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui";
import { Activity, TrendingDown, TrendingUp, Shield, AlertTriangle, CheckCircle2, Clock, DollarSign } from "lucide-react";
import { cn } from "@/lib/utils";
import { getFleetStartingCapital, formatCapitalFull } from "@/lib/fleet-capital";
import { formatBotLabel, useBotIdentity } from "@/lib/bot-identity";

function fmt(v: number | null | undefined, prefix = "$") {
  if (v == null) return "—";
  return `${prefix}${Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtPct(v: number | null | undefined) {
  if (v == null) return "—";
  const sign = v >= 0 ? "+" : "−";
  return `${sign}${Math.abs(v).toFixed(2)}%`;
}

function timeAgo(iso: string | null | undefined) {
  if (!iso) return "never";
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function WeeklyReviewPanel() {
  const { getBotIdentity } = useBotIdentity();
  const { data, isLoading, isError } = useWeeklyReview();
  const { data: portfolio } = usePortfolio();
  const { data: fleetEq } = useFleetEquity();
  const { data: registry } = useBotRegistry();

  const liveTotal = fleetEq?.fleet_total?.equity ?? null;
  const liveTotalPnl = fleetEq?.fleet_total?.pnl ?? null;
  const startingCapital = getFleetStartingCapital(registry, fleetEq);
  const liveTotalPnlPct = startingCapital && liveTotalPnl != null ? (liveTotalPnl / startingCapital) * 100 : null;
  const equityReady = liveTotal != null;

  const oracleEquity = fleetEq?.oracle?.equity ?? null;
  const oracleLabel = formatBotLabel(getBotIdentity("oracle"));

  if (isLoading) {
    return (
      <Card className="border-white/5 bg-gradient-to-br from-slate-900 to-slate-950">
        <CardContent className="p-6">
          <div className="text-sm text-muted-foreground animate-pulse">Loading weekly review...</div>
        </CardContent>
      </Card>
    );
  }

  if (isError || !data) {
    return (
      <Card className="border-red-500/20 bg-gradient-to-br from-slate-900 to-slate-950">
        <CardContent className="p-6">
          <div className="text-sm text-red-400">Weekly review unavailable — check API connection</div>
        </CardContent>
      </Card>
    );
  }

  const summary = data.fleet_summary ?? {};
  const heartbeat = data.fleet_heartbeat ?? [];
  const oracleWeek = data.oracle_week ?? [];
  const topLosses = data.top_losses_week ?? [];
  const criticals = data.math_audit_criticals ?? null;
  const vault = data.vault ?? {};

  const pausedCount = summary.bots_paused ?? null;
  const staleCount = summary.bots_stale ?? null;

  const oracleWins = oracleWeek.find((r: any) => r.status === "Closed_Win");
  const oracleLosses = oracleWeek.find((r: any) => r.status === "Closed_Loss");
  const oracleWinCount = oracleWeek.length > 0 ? oracleWins?.count ?? 0 : null;
  const oracleLossCount = oracleWeek.length > 0 ? oracleLosses?.count ?? 0 : null;
  const oracleWeekPnl = oracleWeek.length > 0 && (oracleWins?.total_pnl != null || oracleLosses?.total_pnl != null)
    ? (oracleWins?.total_pnl ?? 0) + (oracleLosses?.total_pnl ?? 0)
    : oracleWeek.length > 0 ? 0 : null;

  const systemOk = pausedCount != null && staleCount != null && criticals != null && pausedCount === 0 && staleCount === 0 && criticals === 0;
  const systemWarn = (pausedCount ?? 0) > 0 || (staleCount ?? 0) > 0;
  const systemCrit = (criticals ?? 0) > 0;

  return (
    <Card className="border-white/5 bg-gradient-to-br from-slate-900 to-slate-950 overflow-hidden">
      <div className={cn(
        "h-1 w-full",
        systemCrit ? "bg-red-500" : systemWarn ? "bg-amber-500" : "bg-emerald-500"
      )} />

      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <Activity className="h-4 w-4 text-blue-400" />
            Monday Morning Review
          </div>
          <span className="text-[10px] text-muted-foreground font-normal">
            {timeAgo(data.generated_at)}
          </span>
        </CardTitle>
      </CardHeader>

      <CardContent className="space-y-4 pb-5">

        {/* ── Fleet Equity (live data, same source as main dashboard) ── */}
        <div className="rounded-xl border border-white/5 bg-white/3 p-4">
          <div className="text-[9px] uppercase tracking-widest text-muted-foreground mb-3 font-semibold">Fleet Equity</div>
          <div className="flex items-end justify-between">
            <div>
              <div className="text-2xl font-mono font-bold text-white tabular-nums">
                {equityReady
                  ? `$${liveTotal.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
                  : "—"}
              </div>
              <div className="text-xs text-muted-foreground mt-0.5">
                of {startingCapital == null ? "—" : formatCapitalFull(startingCapital)} starting
              </div>
            </div>
            <div className={cn(
              "text-right",
              liveTotalPnl == null ? "text-muted-foreground" : liveTotalPnl >= 0 ? "text-emerald-400" : "text-red-400"
            )}>
              <div className="text-lg font-mono font-bold">
                {liveTotalPnl == null
                  ? "—"
                  : `${liveTotalPnl >= 0 ? "+" : "−"}${fmt(liveTotalPnl)}`}
              </div>
              <div className="text-xs font-mono">
                {equityReady ? fmtPct(liveTotalPnlPct) : "—"}
              </div>
            </div>
          </div>

          {/* Bot equity breakdown */}
          <div className="mt-3 grid grid-cols-2 gap-2">
            {[
              { label: oracleLabel, val: oracleEquity, start: 100_000 },
              { label: "ETF Fleet", val: liveTotal, start: startingCapital },
            ].map(({ label, val, start }) => {
              const pnl = val != null && start != null ? val - start : null;
              return (
                <div key={label} className="rounded-lg bg-white/3 p-2">
                  <div className="text-[9px] text-muted-foreground uppercase tracking-wide">{label}</div>
                  <div className="text-xs font-mono font-bold text-white mt-0.5">
                    {val != null
                      ? `$${val.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
                      : "—"}
                  </div>
                  {pnl != null && (
                    <div className={cn("text-[10px] font-mono", pnl >= 0 ? "text-emerald-400" : "text-red-400")}>
                      {pnl >= 0 ? "+" : "−"}{fmt(pnl)}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* ── System Health ── */}
        <div className="rounded-xl border border-white/5 bg-white/3 p-4">
          <div className="text-[9px] uppercase tracking-widest text-muted-foreground mb-3 font-semibold">System Health</div>
          <div className="grid grid-cols-2 gap-3">

            {/* Bot status */}
            <div className="space-y-1.5">
              {heartbeat.map((bot: any) => (
                <div key={bot.bot_id} className="flex items-center justify-between">
                  <span className="text-[10px] font-mono text-slate-400">{bot.bot_id}</span>
                  <div className="flex items-center gap-1.5">
                    {bot.stale && (
                      <span className="text-[9px] text-amber-400 font-bold">STALE</span>
                    )}
                    <span className={cn(
                      "w-1.5 h-1.5 rounded-full",
                      bot.paused ? "bg-amber-400" :
                      bot.stale  ? "bg-red-400" :
                      bot.status === "running" ? "bg-emerald-400" : "bg-zinc-500"
                    )} />
                  </div>
                </div>
              ))}
            </div>

            {/* Health indicators */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-muted-foreground">Bots paused</span>
                <span className={cn("text-[11px] font-bold font-mono",
                  pausedCount > 0 ? "text-amber-400" : "text-emerald-400"
                )}>{pausedCount}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-muted-foreground">Stale heartbeats</span>
                <span className={cn("text-[11px] font-bold font-mono",
                  staleCount > 0 ? "text-red-400" : "text-emerald-400"
                )}>{staleCount}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-muted-foreground">Math audit FAILs</span>
                <span className={cn("text-[11px] font-bold font-mono",
                  criticals > 0 ? "text-red-400" : "text-emerald-400"
                )}>{criticals}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-muted-foreground">Vault total</span>
                <span className="text-[11px] font-mono text-slate-300">
                  {fmt(vault.total_vaulted)}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* ── Oracle This Week ── */}
        <div className="rounded-xl border border-white/5 bg-white/3 p-4">
          <div className="text-[9px] uppercase tracking-widest text-muted-foreground mb-3 font-semibold">{oracleLabel} — This Week</div>
          {oracleWinCount + oracleLossCount === 0 ? (
            <div className="text-xs text-muted-foreground italic">No closed trades this week</div>
          ) : (
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="text-center">
                  <div className="text-lg font-mono font-bold text-emerald-400">{oracleWinCount}</div>
                  <div className="text-[9px] text-muted-foreground">wins</div>
                </div>
                <div className="text-muted-foreground/30 text-lg">/</div>
                <div className="text-center">
                  <div className="text-lg font-mono font-bold text-red-400">{oracleLossCount}</div>
                  <div className="text-[9px] text-muted-foreground">losses</div>
                </div>
              </div>
              <div className={cn("text-right", oracleWeekPnl >= 0 ? "text-emerald-400" : "text-red-400")}>
                <div className="text-sm font-mono font-bold">
                  {oracleWeekPnl >= 0 ? "+" : "−"}{fmt(oracleWeekPnl)}
                </div>
                <div className="text-[9px] text-muted-foreground">week P&L</div>
              </div>
            </div>
          )}
        </div>

        {/* ── Top Losses This Week ── */}
        {topLosses.length > 0 && (
          <div className="rounded-xl border border-red-500/10 bg-red-500/3 p-4">
            <div className="text-[9px] uppercase tracking-widest text-red-400/70 mb-3 font-semibold flex items-center gap-1.5">
              <TrendingDown className="h-3 w-3" />
              Top Losses This Week
            </div>
            <div className="space-y-2">
              {topLosses.map((t: any, i: number) => (
                <div key={i} className="flex items-center justify-between">
                  <div>
                    <span className="text-[11px] font-mono font-bold text-white">{t.ticker}</span>
                    {t.exit_reason && (
                      <span className="ml-2 text-[9px] text-muted-foreground">{t.exit_reason}</span>
                    )}
                    {t.hold_hours && (
                      <span className="ml-1 text-[9px] text-muted-foreground">
                        · {t.hold_hours.toFixed(0)}h
                      </span>
                    )}
                  </div>
                  <span className="text-[11px] font-mono font-bold text-red-400">
                    −{fmt(t.realized_pnl)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Overall status badge ── */}
        <div className={cn(
          "rounded-lg p-3 flex items-center gap-2",
          systemCrit ? "bg-red-500/10 border border-red-500/20" :
          systemWarn ? "bg-amber-500/10 border border-amber-500/20" :
          "bg-emerald-500/10 border border-emerald-500/20"
        )}>
          {systemCrit ? (
            <AlertTriangle className="h-4 w-4 text-red-400 flex-shrink-0" />
          ) : systemWarn ? (
            <AlertTriangle className="h-4 w-4 text-amber-400 flex-shrink-0" />
          ) : (
            <CheckCircle2 className="h-4 w-4 text-emerald-400 flex-shrink-0" />
          )}
          <span className={cn("text-xs font-medium",
            systemCrit ? "text-red-400" :
            systemWarn ? "text-amber-400" :
            "text-emerald-400"
          )}>
            {systemCrit
              ? `${criticals} math audit failure${criticals !== 1 ? "s" : ""} — check immediately`
              : systemWarn
              ? `${pausedCount} bot${pausedCount !== 1 ? "s" : ""} paused · ${staleCount} stale heartbeat${staleCount !== 1 ? "s" : ""}`
              : "All systems healthy — fleet running normally"}
          </span>
        </div>

      </CardContent>
    </Card>
  );
}
