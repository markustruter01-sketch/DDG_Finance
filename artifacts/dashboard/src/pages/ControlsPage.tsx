import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { OctagonX, Pause, Play, RefreshCw } from "lucide-react";
import { api } from "@/hooks/use-trading-client";
import { botColor, formatBotLabel, useBotIdentity } from "@/lib/bot-identity";
import { Shell, Status, bneTime } from "@/components/Shell";
import { useClearHalt, useFleetV1State, useMomoV2State } from "@/hooks/use-fleet-v1";

type Governed = {
  bot_id: string;
  registration: string;
  drawdown: { mode: string; halted: boolean; drawdown: number | null; high_water_mark: number | null;
              as_of: string | null; cleared_by?: string | null; cleared_at?: string | null };
};
import { pct } from "@/components/FleetV1";

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
        <div className="label">{identity.code}</div>
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
      {tripped && <KillReset />}
    </section>
  );
}

/** Clears the kill switch's latch. Owner only: the server checks the token
 *  against its KILL_SWITCH_RESET_CONFIRMATION secret and writes a reset
 *  event. Bots stay paused until resumed one by one above. */
function KillReset() {
  const qc = useQueryClient();
  const [token, setToken] = useState("");
  const reset = useMutation({
    mutationFn: async () => (await api.post("/kill/reset", { confirmation_token: token })).data as { status: string },
    onSettled: () => {
      setToken("");
      qc.invalidateQueries({ queryKey: PAUSE_KEY });
      qc.invalidateQueries({ queryKey: ["/fleet-v1/state"] });
    },
  });
  return (
    <div className="halt-row" style={{ borderTop: "1px solid var(--ng-hairline)", paddingTop: 10 }}>
      <p className="body" style={{ margin: "0 0 8px" }}>
        The kill switch is tripped: every account is paused. Once the cause is fixed, clear the latch with the
        owner's reset token, then resume the accounts above. Nothing is bought or sold by the reset.
      </p>
      <div className="control-actions">
        <input className="input" type="password" value={token} onChange={(e) => setToken(e.target.value)}
          placeholder="Reset token" aria-label="Kill switch reset token" data-testid="input-kill-reset-token" />
        <button className="btn" data-testid="button-kill-reset" disabled={!token || reset.isPending}
          onClick={() => reset.mutate()}>
          {reset.isPending ? "Clearing…" : "Clear the kill switch"}
        </button>
      </div>
      {reset.isSuccess && <div className="small">Cleared. Resume the accounts above when ready.</div>}
      {reset.isError && <div className="small"><span className="loss">Refused: {errorText(reset.error)}</span></div>}
    </div>
  );
}

function HaltRow({ account }: { account: Governed }) {
  const [token, setToken] = useState("");
  const clear = useClearHalt(account.bot_id);
  const dd = account.drawdown;
  return (
    <li className="control-row" data-testid={`row-halt-${account.bot_id}`}>
      <div className="grow">
        <div className="card-title">{account.registration}</div>
        <div className="note">
          Drawdown {pct(dd.drawdown)} from high-water mark {dd.high_water_mark == null ? "—" : `$${Math.round(dd.high_water_mark).toLocaleString("en-AU")}`}
          {dd.as_of ? ` · as of ${dd.as_of} close` : ""}
          {dd.cleared_at ? ` · last cleared ${bneTime(dd.cleared_at)} by ${dd.cleared_by}` : ""}
        </div>
        {clear.isError && <div className="note"><span className="loss">Not cleared: {errorText(clear.error)}</span></div>}
      </div>
      {dd.halted ? <Status tone="problem" word="Halted (all cash)" />
        : dd.mode === "soft" ? <Status tone="late" word="Half size" /> : <Status tone="ok" word="Normal" />}
      {dd.halted && (
        <div className="control-actions">
          <input className="input" type="password" value={token} onChange={(e) => setToken(e.target.value)}
            placeholder="Owner confirmation" aria-label={`Confirmation to clear ${account.registration}`} />
          <button className="btn" disabled={!token || clear.isPending} data-testid={`button-clear-halt-${account.bot_id}`}
            onClick={() => {
              if (window.confirm(`Clear the halt on ${account.registration}? It trades again at the next cycle, and its high-water mark restarts at today's equity.`)) {
                clear.mutate(token, { onSettled: () => setToken("") });
              }
            }}>
            {clear.isPending ? "Clearing…" : "Clear halt"}
          </button>
        </div>
      )}
    </li>
  );
}

function DrawdownLimits() {
  const fleet = useFleetV1State();
  const momo = useMomoV2State();
  if (fleet.isError) {
    return <section className="glass panel" role="alert"><Status tone="problem" word="FLEET-V1 state unreadable" /></section>;
  }
  if (!fleet.data) return null;
  const { limits, kill_switch: ks } = fleet.data;
  return (
    <section className="glass panel" aria-label="Drawdown limits">
      <div className="panel-head">
        <h2>Drawdown limits</h2>
        <Status tone={ks.tripped ? "problem" : ks.armed ? "ok" : "late"}
          word={ks.tripped ? "Kill switch tripped" : ks.armed ? "Kill switch armed" : "Kill switch NOT armed"} />
      </div>
      <p className="body" style={{ margin: 0 }}>
        {limits.enforced ? "Enforced" : "Record only"}: above {pct(limits.soft, 0)} {limits.soft_action}; above {pct(limits.hard, 0)} {limits.hard_action}.
        {!ks.armed && " The kill switch is disarmed by the KILL_SWITCH_ARMED secret; arming it is an owner action in Replit's secrets."}
      </p>
      <ul className="list">
        {fleet.data.accounts.map((a) => <HaltRow key={a.bot_id} account={a} />)}
        {momo.data && <HaltRow key={momo.data.bot_id} account={momo.data} />}
      </ul>
    </section>
  );
}

type Link = { name: string; state: "working" | "failing" | "unknown"; last_ok: string | null; last_fail: string | null; last_error: string | null };

/** Every outside link and when it last worked / failed. A link that worked after its last failure is working. */
function Connections() {
  const links = useQuery({
    queryKey: ["connections"],
    queryFn: async () => (await api.get("/connections")).data as { links: Link[] },
    refetchInterval: 60_000,
  });
  const when = (iso: string | null) => (iso ? bneTime(iso) : "—");
  return (
    <section className="glass panel" aria-label="Connections">
      <div className="panel-head"><h2>Connections</h2><span className="label">Last worked · last failed</span></div>
      {links.isError && <Status tone="problem" word={`Connections unreadable: ${errorText(links.error)}`} />}
      <div className="table-scroll">
        <table className="ng">
          <thead><tr><th>Link</th><th>State</th><th>Last worked</th><th>Last failed</th><th>Last error</th></tr></thead>
          <tbody>
            {(links.data?.links ?? []).map((l) => (
              <tr key={l.name}>
                <td>{l.name}</td>
                <td><Status tone={l.state === "working" ? "ok" : l.state === "failing" ? "problem" : "none"} word={l.state === "working" ? "Working" : l.state === "failing" ? "Failing" : "No data yet"} /></td>
                <td>{when(l.last_ok)}</td>
                <td>{when(l.last_fail)}</td>
                <td className="small">{l.state === "failing" ? l.last_error : l.last_error ? <span className="note">{l.last_error} (recovered)</span> : "—"}</td>
              </tr>
            ))}
            {links.data && !links.data.links.length && <tr><td colSpan={5} className="note">No links reported yet. They appear after the next cycle.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}


type Alarm = { id: number; error_type: string; message: string; ts?: string; created_at?: string; severity?: string; bot_id?: string | null };

/** Overview first (approved design 20 Nov): what needs Markus, in order of urgency, then the counts. */
function NeedsYou({ state }: { state: PauseState }) {
  const alarms = useQuery({
    queryKey: ["unresolved-alarms"],
    queryFn: async () => (await api.get("/system/degradations", { params: { hours: 24 * 30, unresolved_only: true, limit: 50 } })).data as { events: Alarm[] },
    refetchInterval: 60_000,
  });
  const links = useQuery({
    queryKey: ["connections"],
    queryFn: async () => (await api.get("/connections")).data as { links: Link[] },
    refetchInterval: 60_000,
  });
  const open = alarms.data?.events ?? [];
  const failing = (links.data?.links ?? []).filter((l) => l.state === "failing");
  const paused = state.bots.filter((b) => b.paused !== false);
  const items: { tone: "problem" | "late"; text: string }[] = [
    ...(state.kill_switch_tripped ? [{ tone: "problem" as const, text: "Emergency stop has tripped" }] : []),
    ...failing.map((l) => ({ tone: "problem" as const, text: `${l.name} is failing${l.last_error ? `: ${l.last_error}` : ""}` })),
    ...(open.length ? [{ tone: "problem" as const, text: `${open.length} alarm${open.length > 1 ? "s" : ""} open · newest: ${open[0].message}` }] : []),
    ...paused.map((b) => ({ tone: "late" as const, text: `${b.bot_id} is ${b.paused === null ? "unknown (treated as paused)" : "paused"}${b.pause_reason ? `: ${b.pause_reason}` : ""}` })),
  ];
  return (<>
    <section className="glass panel league-kpis" aria-label="Controls at a glance">
      <div className="stat"><span className="label">Bots running</span><span className="num-sm">{state.bots.length - paused.length} / {state.bots.length}</span><span className="small">{paused.length ? `${paused.length} paused` : "none paused"}</span></div>
      <div className="stat"><span className="label">Emergency stop</span><span className={`num-sm ${state.kill_switch_tripped ? "loss" : ""}`}>{state.kill_switch_tripped ? "Tripped" : "Not tripped"}</span><span className="small">manual button below</span></div>
      <div className="stat"><span className="label">Open alarms</span><span className={`num-sm ${open.length ? "loss" : ""}`}>{alarms.isError ? "—" : open.length}</span><span className="small">last 30 days, unresolved</span></div>
      <div className="stat"><span className="label">Connections</span><span className={`num-sm ${failing.length ? "loss" : ""}`}>{links.data ? `${links.data.links.length - failing.length} / ${links.data.links.length}` : "—"}</span><span className="small">working</span></div>
    </section>
    <section className="glass panel" aria-label="Needs you" style={items.length ? { borderColor: "rgba(245,165,36,0.45)" } : undefined}>
      <div className="panel-head"><h2>Needs you</h2><span className="label">most urgent first</span></div>
      {!items.length ? <div className="empty">Nothing needs you right now.</div> : (
        <ul className="list">{items.map((x, i) => <li key={i}><Status tone={x.tone} word={x.text} /></li>)}</ul>
      )}
      {open.length > 0 && (
        <details style={{ marginTop: 8 }}><summary className="small" style={{ cursor: "pointer" }}>Every open alarm</summary>
          <table className="ng"><tbody>{open.map((a) => (
            <tr key={a.id}><td className="small">{(a.ts ?? a.created_at ?? "").slice(0, 16).replace("T", " ")}</td><td>{a.error_type}<div className="note">{a.message}</div></td></tr>
          ))}</tbody></table>
        </details>
      )}
    </section>
    <div className="fold">detail</div>
  </>);
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
            <NeedsYou state={state.data} />
            <div className="split">
              <div className="split-col">
                <section className="glass panel" aria-label="Bots">
                  <div className="panel-head"><h2>Bots</h2><span className="label">{state.data.bots.length} bots</span></div>
                  <ul className="list">{state.data.bots.map((row) => <BotRow key={row.bot_id} row={row} />)}</ul>
                </section>
                <EmergencyStop tripped={state.data.kill_switch_tripped} />
              </div>
              <div className="split-col">
                <Connections />
                <DrawdownLimits />
              </div>
            </div>
          </>
        )}
      </main>
    </Shell>
  );
}
