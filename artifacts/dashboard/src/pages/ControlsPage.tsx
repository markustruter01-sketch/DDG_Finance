import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { OctagonX, Pause, Play, RefreshCw, ShieldAlert } from "lucide-react";
import { api } from "@/hooks/use-trading-client";
import { formatBotLabel, useBotIdentity } from "@/lib/bot-identity";

// Controls for the live platform. bots_state.paused is the only pause switch;
// the runner treats a missing or unreadable row as paused.

type PauseRow = {
  bot_id: string;
  paused: boolean | null;
  pause_reason: string | null;
  paused_at: string | null;
};

type PauseState = { bots: PauseRow[]; kill_switch_tripped: boolean };

const PAUSE_KEY = ["/bots/pause-state"];
const STOP_WORD = "STOP";

function errorText(err: unknown): string {
  const e = err as { response?: { data?: { detail?: string } }; message?: string };
  return e?.response?.data?.detail ?? e?.message ?? "request failed";
}

function StatusPill({ paused }: { paused: boolean | null }) {
  const [label, cls] =
    paused === null
      ? ["UNKNOWN · treated as paused", "border-amber-500/40 bg-amber-500/10 text-amber-300"]
      : paused
        ? ["PAUSED", "border-amber-500/40 bg-amber-500/10 text-amber-300"]
        : ["RUNNING", "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"];
  return <span className={`rounded-full border px-2.5 py-0.5 text-[10px] font-bold tracking-widest ${cls}`}>{label}</span>;
}

function BotRow({ row }: { row: PauseRow }) {
  const qc = useQueryClient();
  const { getBotIdentity } = useBotIdentity();
  const identity = getBotIdentity(row.bot_id);
  const [reason, setReason] = useState("");
  const action = row.paused === false ? "pause" : "resume";
  const toggle = useMutation({
    mutationFn: async () =>
      (await api.post(`/bots/${row.bot_id}/${action}`, null, action === "pause" ? { params: { reason: reason || "manual pause from dashboard" } } : undefined)).data,
    onSettled: () => qc.invalidateQueries({ queryKey: PAUSE_KEY }),
  });

  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4" data-testid={`row-bot-${row.bot_id}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-white">{identity.icon} {formatBotLabel(identity)}</div>
          <div className="font-mono text-[11px] text-slate-500">{row.bot_id}</div>
        </div>
        <StatusPill paused={row.paused} />
      </div>
      {row.pause_reason && row.paused !== false && (
        <div className="mt-2 text-xs text-slate-400">Reason: {row.pause_reason}</div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {action === "pause" && (
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason (optional)"
            className="min-w-0 flex-1 rounded-lg border border-white/10 bg-slate-900 px-3 py-1.5 text-xs text-white placeholder:text-slate-600"
          />
        )}
        <button
          data-testid={`button-${action}-${row.bot_id}`}
          disabled={toggle.isPending}
          onClick={() => {
            const verb = action === "pause" ? "Pause" : "Resume";
            if (window.confirm(`${verb} ${identity.displayName}?`)) toggle.mutate();
          }}
          className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold transition disabled:opacity-50 ${
            action === "pause"
              ? "border-amber-500/40 bg-amber-500/10 text-amber-200 hover:bg-amber-500/20"
              : "border-emerald-500/40 bg-emerald-500/10 text-emerald-200 hover:bg-emerald-500/20"
          }`}
        >
          {action === "pause" ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
          {toggle.isPending ? "Saving…" : action === "pause" ? "Pause" : "Resume"}
        </button>
      </div>
      {toggle.isError && <div className="mt-2 text-xs text-red-400">Not changed: {errorText(toggle.error)}</div>}
    </div>
  );
}

function EmergencyStop({ tripped }: { tripped: boolean }) {
  const qc = useQueryClient();
  const [typed, setTyped] = useState("");
  const trip = useMutation({
    mutationFn: async () => (await api.post("/kill")).data as { cancelled_orders?: number; action?: string },
    onSettled: () => {
      setTyped("");
      qc.invalidateQueries({ queryKey: PAUSE_KEY });
    },
  });

  return (
    <div className="rounded-2xl border border-red-500/30 bg-red-500/[0.04] p-5">
      <div className="flex items-center gap-2 text-sm font-bold text-red-300">
        <OctagonX className="h-4 w-4" /> Emergency stop
      </div>
      <p className="mt-2 text-xs leading-relaxed text-slate-400">
        Pauses every bot, then cancels pending buy/sell orders at the brokers. Protective stops are
        kept, and nothing is sold. Resume bots one by one above when it is safe.
      </p>
      <div className="mt-2 text-xs text-slate-400">
        Kill switch: <span className={tripped ? "font-semibold text-red-300" : "text-slate-300"}>{tripped ? "TRIPPED" : "not tripped"}</span>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <input
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          placeholder={`Type ${STOP_WORD} to enable`}
          className="w-40 rounded-lg border border-red-500/30 bg-slate-900 px-3 py-1.5 text-xs text-white placeholder:text-slate-600"
          data-testid="input-emergency-confirm"
        />
        <button
          data-testid="button-emergency-stop"
          disabled={typed !== STOP_WORD || trip.isPending}
          onClick={() => trip.mutate()}
          className="rounded-lg border border-red-500/50 bg-red-500/20 px-4 py-1.5 text-xs font-bold text-red-100 transition hover:bg-red-500/30 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {trip.isPending ? "Stopping…" : "Stop everything"}
        </button>
      </div>
      {trip.isSuccess && (
        <div className="mt-2 text-xs text-emerald-300">
          Done. Pending orders cancelled: {trip.data?.cancelled_orders ?? 0}. {trip.data?.action}
        </div>
      )}
      {trip.isError && <div className="mt-2 text-xs text-red-400">Failed: {errorText(trip.error)}</div>}
    </div>
  );
}

export default function ControlsPage() {
  const state = useQuery({
    queryKey: PAUSE_KEY,
    queryFn: async () => (await api.get("/bots/pause-state")).data as PauseState,
    refetchInterval: 15_000,
  });

  return (
    <main className="min-h-screen bg-transparent px-4 pb-32 pt-8 text-white">
      <div className="mx-auto max-w-2xl space-y-5">
        <header className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldAlert className="h-5 w-5 text-slate-300" />
            <h1 className="text-lg font-bold">Controls</h1>
          </div>
          <button
            onClick={() => state.refetch()}
            className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-slate-300 hover:bg-white/5"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${state.isFetching ? "animate-spin" : ""}`} /> Refresh
          </button>
        </header>

        {state.isLoading && <div className="text-xs text-slate-500">Reading pause state…</div>}
        {state.isError && (
          <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-300">
            Pause state unreadable: {errorText(state.error)}. The runner treats unreadable state as paused.
          </div>
        )}
        {state.data && (
          <>
            <section className="space-y-3">
              {state.data.bots.map((row) => <BotRow key={row.bot_id} row={row} />)}
            </section>
            <EmergencyStop tripped={state.data.kill_switch_tripped} />
          </>
        )}
      </div>
    </main>
  );
}
