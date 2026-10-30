import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { OctagonX, Pause, Play, RefreshCw } from "lucide-react";
import { api } from "@/hooks/use-trading-client";
import { botColor, formatBotLabel, useBotIdentity } from "@/lib/bot-identity";
import { Shell, Status, bneTime } from "@/components/Shell";

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

function PauseStatus({ paused }: { paused: boolean | null }) {
  if (paused === null) return <Status tone="late" word="Unknown, treated as paused" />;
  return paused ? <Status tone="late" word="Paused" /> : <Status tone="ok" word="Running" />;
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
    <li className="control-row" data-testid={`row-bot-${row.bot_id}`}>
      <div className="grow">
        <div className="card-title"><span className="dot" style={{ background: botColor(row.bot_id), marginRight: 8, verticalAlign: "middle" }} aria-hidden="true" />{formatBotLabel(identity)}</div>
        <div className="label">{row.bot_id}</div>
        {row.pause_reason && row.paused !== false && (
          <div className="note">Reason: {row.pause_reason}{row.paused_at ? ` · since ${bneTime(row.paused_at)}` : ""}</div>
        )}
        {toggle.isError && <div className="note"><span className="loss">Not changed: {errorText(toggle.error)}</span></div>}
      </div>
      <PauseStatus paused={row.paused} />
      <div className="control-actions">
        {action === "pause" && (
          <input className="input" value={reason} onChange={(e) => setReason(e.target.value)}
            placeholder="Reason (optional)" aria-label={`Pause reason for ${identity.displayName}`} />
        )}
        <button
          className="btn"
          data-testid={`button-${action}-${row.bot_id}`}
          disabled={toggle.isPending}
          onClick={() => {
            const verb = action === "pause" ? "Pause" : "Resume";
            if (window.confirm(`${verb} ${identity.displayName}?`)) toggle.mutate();
          }}
        >
          {action === "pause" ? <Pause size={15} aria-hidden="true" /> : <Play size={15} aria-hidden="true" />}
          {toggle.isPending ? "Saving…" : action === "pause" ? "Pause" : "Resume"}
        </button>
      </div>
    </li>
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
    <section className="glass panel stop-panel" aria-label="Emergency stop">
      <div className="panel-head">
        <h2><OctagonX size={16} aria-hidden="true" style={{ verticalAlign: "-3px", marginRight: 8 }} />Emergency stop</h2>
        <Status tone={tripped ? "problem" : "ok"} word={tripped ? "Kill switch tripped" : "Kill switch not tripped"} />
      </div>
      <p className="body" style={{ margin: 0 }}>
        Pauses every bot, then cancels pending buy and sell orders at the brokers. Protective stops are
        kept, and nothing is sold. Resume bots one by one above when it is safe.
      </p>
      <div className="control-actions">
        <input className="input" value={typed} onChange={(e) => setTyped(e.target.value)}
          placeholder={`Type ${STOP_WORD} to enable`} aria-label="Confirmation word" data-testid="input-emergency-confirm" />
        <button
          className="btn danger"
          data-testid="button-emergency-stop"
          disabled={typed !== STOP_WORD || trip.isPending}
          onClick={() => trip.mutate()}
        >
          {trip.isPending ? "Stopping…" : "Stop everything"}
        </button>
      </div>
      {trip.isSuccess && (
        <div className="small">Done. Pending orders cancelled: {trip.data?.cancelled_orders ?? 0}. {trip.data?.action}</div>
      )}
      {trip.isError && <div className="small"><span className="loss">Failed: {errorText(trip.error)}</span></div>}
    </section>
  );
}

export default function ControlsPage() {
  const state = useQuery({
    queryKey: PAUSE_KEY,
    queryFn: async () => (await api.get("/bots/pause-state")).data as PauseState,
    refetchInterval: 15_000,
  });

  return (
    <Shell>
      <main className="controls">
        <div className="page-head">
          <h1 className="page-title">Controls</h1>
          <button className="btn" onClick={() => state.refetch()}>
            <RefreshCw size={15} aria-hidden="true" /> {state.isFetching ? "Refreshing" : "Refresh"}
          </button>
        </div>

        {state.isLoading && <div className="note">Reading pause state…</div>}
        {state.isError && (
          <div className="glass panel" role="alert">
            <Status tone="problem" word="Pause state unreadable" />
            <div className="small">{errorText(state.error)}. The runner treats unreadable state as paused.</div>
          </div>
        )}
        {state.data && (
          <>
            <section className="glass panel" aria-label="Bots">
              <div className="panel-head"><h2>Bots</h2><span className="label">{state.data.bots.length} bots</span></div>
              <ul className="list">{state.data.bots.map((row) => <BotRow key={row.bot_id} row={row} />)}</ul>
            </section>
            <EmergencyStop tripped={state.data.kill_switch_tripped} />
          </>
        )}
      </main>
    </Shell>
  );
}
