import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/hooks/use-trading-client";
import { useLeaderboard } from "@/hooks/use-leaderboard";
import { Shell, Status } from "@/components/Shell";
import { returnSince, type Curve } from "@/lib/curves";
import { Bars, DoneTick } from "@/components/Motion";
import { WheelPicker } from "@/components/WheelPicker";

// Me vs the machines (Markus, 20 Nov 2026). Markus's own pretend account
// (twins/human.py) and the 2027 predictions (twins/predictions.py). Overview
// first: the head-to-head; then the trade ticket, holdings and trade log; then
// the predictions. Every figure comes from the API; trades write pretend
// decisions only (no orders), filled at the next US open by the same engine.

// name/about: funds and currencies; name/sector/industry: shares (twins/human.py catalog).
type Asset = { symbol: string; label: string; name?: string; about?: string; sector?: string; industry?: string };
type AssetClass = { id: string; label: string; assets: Asset[]; two_way?: boolean };
type Catalog = { classes: AssetClass[]; shares_available: boolean };
type Trade = { id: number; at: string; fills_after: string; asset: string; side: string; percent: number; reason: string };
type Account = { version: number; twin_id: string; label: string; start_at: string; start_equity: number;
  equity: number | null; valued_day: string | null; target: { asset: string; percent: number }[]; trades: Trade[] };
type AccountView = { accounts: Account[]; rules: { start_equity: number; max_gross_pct: number; record_year: number; min_reason: number } };
type Row = { id: string; name: string; kind: string; family: string | null; return_pct: number | null; curve: Curve };
type MarketF = { direction: "up" | "flat" | "down"; change_pct: number };
type Entry = { id: number; author: string; model: string | null; thesis: string; filed_at: string; versions: number;
  forecasts: { markets: Record<string, MarketF>; macro: Record<string, number> } };
type Predictions = { year: number; lock_at: string; locked: boolean; markets: Record<string, string>;
  macro: Record<string, string>; flat_band_pct: number; entries: Entry[] };

const AUTHOR: Record<string, string> = { Markus: "Markus", member_1: "AI member 1", member_2: "AI member 2", member_3: "AI member 3" };
const AI_REAL = new Set(["forex_ai"]);
const RULE_REAL = new Set(["oracle", "jerome_macro", "spy_qqq_trend"]);
const tone = (v: number | null | undefined) => (v == null || v === 0 ? "" : v > 0 ? "gain" : "loss");
const pct = (v: number | null | undefined) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`);
const money = (v: number | null | undefined) => (v == null ? "—" : `$${v.toLocaleString("en-AU", { maximumFractionDigits: 0 })}`);
const err = (e: unknown) => {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : e instanceof Error ? e.message : "Request failed";
};

// Everyone is measured from the same day: the first day Markus's account has a value (front-end audit 21 Nov:
// the real bots start 9 Nov, the league 19 Nov, the AI copies later, so their own "since start" don't compare).
function group(rows: Row[], pick: (r: Row) => boolean, from: string | null) {
  const vals = rows.filter(pick).map((r) => (from ? returnSince(r.curve, from) : null)).filter((v): v is number => v != null);
  if (!vals.length) return { best: null, avg: null, n: 0 };
  return { best: Math.max(...vals), avg: vals.reduce((a, b) => a + b, 0) / vals.length, n: vals.length };
}

/** "LMT (Lockheed Martin — Aerospace & Defense)": the ticker, then what it is. */
const describe = (a: Asset) => {
  const what = a.about || a.industry || a.sector;
  return a.name ? `${a.label} (${a.name}${what ? ` — ${what}` : ""})` : a.label;
};
const ALL = "";
const counted = (values: string[]) => {
  const n = new Map<string, number>();
  values.filter(Boolean).forEach((v) => n.set(v, (n.get(v) ?? 0) + 1));
  return [...n.entries()].sort(([a], [b]) => a.localeCompare(b));
};

function TradeTicket({ catalog, onDone }: { catalog: Catalog; onDone: () => void }) {
  const [cls, setCls] = useState(catalog.classes[0]?.id ?? "");
  const klass = catalog.classes.find((c) => c.id === cls);
  const [sector, setSector] = useState(ALL);
  const [industry, setIndustry] = useState(ALL);
  const [find, setFind] = useState("");
  const [asset, setAsset] = useState("");
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [percent, setPercent] = useState(10);
  const [reason, setReason] = useState("");
  const qc = useQueryClient();
  const send = useMutation({
    mutationFn: async () => (await api.post("/human/trade", { asset, side, percent, reason })).data as { fills_at_open_after: string },
    onSuccess: () => { setReason(""); qc.invalidateQueries({ queryKey: ["human-account"] }); onDone(); },
  });
  const all = klass?.assets ?? [];
  const bySector = all.some((a) => a.sector);                       // shares: sort them by type
  const sectors = useMemo(() => counted(all.map((a) => a.sector ?? "")), [all]);
  const inSector = all.filter((a) => sector === ALL || a.sector === sector);
  const industries = useMemo(() => counted(inSector.map((a) => a.industry ?? "")), [inSector]);
  const q = find.trim().toLowerCase();
  const shown = inSector.filter((a) => (industry === ALL || a.industry === industry)
    && (!q || a.symbol.toLowerCase().includes(q) || (a.name ?? "").toLowerCase().includes(q)));
  const chosen = all.find((a) => a.symbol === asset);
  useEffect(() => { if (asset && !shown.some((a) => a.symbol === asset)) setAsset(""); });   // a filter hid it
  const valid = !!chosen && reason.trim().length >= 10;
  const base = chosen?.name?.split(" vs ")[0];
  return (
    <section className="glass panel me-ticket" aria-label="Place a trade">
      <div className="panel-head"><h2>Place a trade</h2><span className="label">sets how much of the account one asset is · fills at the next US open</span></div>
      <div className="ticket">
        <label className="field"><span className="label">Asset class</span>
          <select value={cls} onChange={(e) => { setCls(e.target.value); setSector(ALL); setIndustry(ALL); setFind(""); setAsset(""); setSide("buy"); }}>
            {catalog.classes.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
          </select></label>
        {bySector && (<>
          <label className="field"><span className="label">Sector</span>
            <select value={sector} onChange={(e) => { setSector(e.target.value); setIndustry(ALL); }}>
              <option value={ALL}>All sectors ({all.length})</option>
              {sectors.map(([s, n]) => <option key={s} value={s}>{s} ({n})</option>)}
            </select></label>
          {industries.length > 0 && (
            <label className="field"><span className="label">Industry</span>
              <select value={industry} onChange={(e) => setIndustry(e.target.value)}>
                <option value={ALL}>All industries ({inSector.length})</option>
                {industries.map(([s, n]) => <option key={s} value={s}>{s} ({n})</option>)}
              </select></label>
          )}
          <label className="field"><span className="label">Find a company</span>
            <input value={find} placeholder="name or ticker, e.g. Lockheed" onChange={(e) => setFind(e.target.value)} /></label>
        </>)}
        <label className="field ticket-asset"><span className="label">Asset{bySector ? ` (${shown.length})` : ""}</span>
          <select value={asset} onChange={(e) => setAsset(e.target.value)}>
            <option value="">{shown.length ? "Choose…" : "Nothing matches"}</option>
            {shown.map((a) => <option key={a.symbol} value={a.symbol}>{describe(a)}</option>)}
          </select></label>
        {klass?.two_way && (
          <div className="field"><span className="label">Direction</span>
            <div className="chips" role="group" aria-label="Direction">
              <button className={`chip${side === "buy" ? " on" : ""}`} aria-pressed={side === "buy"} onClick={() => setSide("buy")}>Buy {base ?? "the first currency"}</button>
              <button className={`chip${side === "sell" ? " on" : ""}`} aria-pressed={side === "sell"} onClick={() => setSide("sell")}>Sell {base ?? "the first currency"}</button>
            </div></div>
        )}
        <div className="field ticket-percent"><span className="label" id="ticket-percent">Share of the account (0% = sell it all)</span>
          <WheelPicker value={percent} onChange={setPercent} min={0} max={100} unit="%" labelledBy="ticket-percent" /></div>
        {chosen && (
          <p className="small ticket-what">
            <b>{chosen.label}</b> is {chosen.name || chosen.label}
            {chosen.about ? `: ${chosen.about}` : chosen.sector ? `, ${chosen.sector}${chosen.industry ? `, ${chosen.industry}` : ""}` : ""}.
            {" "}This trade sets it to <b>{percent}%</b> of the account{klass?.two_way ? ` (${side === "buy" ? "buying" : "selling"} the ${base})` : ""}.
          </p>
        )}
        <label className="field ticket-reason"><span className="label">Why (required)</span>
          <textarea rows={3} value={reason} maxLength={500} placeholder="What you see and why this trade fits your view" onChange={(e) => setReason(e.target.value)} /></label>
      </div>
      <div className="ticket-foot">
        <button className="btn" disabled={!valid || send.isPending} onClick={() => send.mutate()}>{send.isPending ? <><Bars /> Recording…</> : "Record trade"}</button>
        {send.isSuccess && <span className="small"><DoneTick />Recorded. Fills at the open after {send.data.fills_at_open_after}.</span>}
        {send.isError && <Status tone="problem" word={err(send.error)} />}
        {!catalog.shares_available && <span className="small">S&amp;P 500 list unavailable right now; funds and currencies still work.</span>}
      </div>
    </section>
  );
}

/** A typed number that can be emptied while typing (a plain controlled number box snapped back to 0). */
function NumberField({ value, step, onChange }: { value: number; step: number; onChange: (n: number) => void }) {
  const [text, setText] = useState(String(value));
  useEffect(() => { if (parseFloat(text) !== value && !(text === "" && value === 0)) setText(String(value)); }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  return <input type="number" step={step} value={text} onChange={(e) => { setText(e.target.value); const n = parseFloat(e.target.value); onChange(Number.isFinite(n) ? n : 0); }} />;
}

function PredictionForm({ p, mine }: { p: Predictions; mine?: Entry }) {
  const blank = Object.fromEntries(Object.keys(p.markets).map((k) => [k, { direction: "up", change_pct: 0 } as MarketF]));
  const [thesis, setThesis] = useState(mine?.thesis ?? "");
  const [m, setM] = useState<Record<string, MarketF>>(mine?.forecasts.markets ?? blank);
  const [macro, setMacro] = useState<Record<string, number>>(mine?.forecasts.macro ?? Object.fromEntries(Object.keys(p.macro).map((k) => [k, 0])));
  const qc = useQueryClient();
  const send = useMutation({
    mutationFn: async () => (await api.post("/predictions", { thesis, forecasts: { markets: m, macro } })).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["predictions"] }),
  });
  return (
    <section className="glass panel" aria-label="My 2027 prediction">
      <div className="panel-head"><h2>My {p.year} prediction</h2><span className="label">file again any time before the lock · the newest counts · every version kept</span></div>
      <label className="field"><span className="label">Thesis: how you think the world economy and markets will play out</span>
        <textarea rows={6} value={thesis} maxLength={4000} onChange={(e) => setThesis(e.target.value)} /></label>
      <div className="table-scroll"><table className="ng">
        <thead><tr><th>Market (31 Dec {p.year - 1} → 31 Dec {p.year})</th><th>Direction</th><th>Change %</th></tr></thead>
        <tbody>{Object.entries(p.markets).map(([k, label]) => (
          <tr key={k}><td>{label}</td>
            <td><select value={m[k]?.direction} onChange={(e) => setM({ ...m, [k]: { ...m[k], direction: e.target.value as MarketF["direction"] } })}>
              <option value="up">Up</option><option value="flat">Flat (±{p.flat_band_pct}%)</option><option value="down">Down</option></select></td>
            <td><NumberField step={0.5} value={m[k]?.change_pct ?? 0} onChange={(n) => setM({ ...m, [k]: { ...m[k], change_pct: n } })} /></td></tr>
        ))}
        {Object.entries(p.macro).map(([k, label]) => (
          <tr key={k}><td>{label}</td><td /><td><NumberField step={0.05} value={macro[k] ?? 0} onChange={(n) => setMacro({ ...macro, [k]: n })} /></td></tr>
        ))}</tbody></table></div>
      <div className="ticket-foot">
        <button className="btn" disabled={send.isPending || thesis.trim().length < 50} onClick={() => send.mutate()}>{send.isPending ? <><Bars /> Filing…</> : mine ? "File a new version" : "File my prediction"}</button>
        {send.isSuccess && <span className="small"><DoneTick />Filed.</span>}
        {send.isError && <Status tone="problem" word={err(send.error)} />}
      </div>
    </section>
  );
}

export default function MePage() {
  const qc = useQueryClient();
  const catalog = useQuery({ queryKey: ["human-catalog"], queryFn: async () => (await api.get("/human/catalog")).data as Catalog, staleTime: 3600_000 });
  const acct = useQuery({ queryKey: ["human-account"], queryFn: async () => (await api.get("/human/account")).data as AccountView });
  const board = useLeaderboard<{ rows: Row[] }>();
  const preds = useQuery({ queryKey: ["predictions"], queryFn: async () => (await api.get("/predictions")).data as Predictions });
  const ask = useMutation({
    mutationFn: async () => (await api.post("/predictions/ask-council")).data as Record<string, { filed?: number; error?: string }>,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["predictions"] }),
  });
  const [tab, setTab] = useState<number | null>(null);

  const accounts = acct.data?.accounts ?? [];
  const shown = accounts.find((a) => a.version === tab) ?? accounts[accounts.length - 1];
  const rows = board.data?.rows ?? [];
  const me = rows.find((r) => r.kind === "human");
  const from = me?.curve?.[0]?.[0] ?? null;          // my first valued day
  const ai = useMemo(() => group(rows, (r) => r.kind === "ai" || AI_REAL.has(r.id), from), [rows, from]);
  const rules = useMemo(() => group(rows, (r) => r.kind === "shadow" && r.family !== "forex" || RULE_REAL.has(r.id), from), [rows, from]);
  const spx = rows.find((r) => r.id === "Y-SPX");
  const spxR = spx && from ? returnSince(spx.curve, from) : null;
  const myReturn = shown?.equity != null ? 100 * (shown.equity / shown.start_equity - 1) : null;
  const myR = me && from ? returnSince(me.curve, from) : null;
  const ranked = rows.map((r) => (from ? returnSince(r.curve, from) : null)).filter((v): v is number => v != null);
  const p = preds.data;
  const mine = p?.entries.find((e) => e.author === "Markus");

  return (
    <Shell>
      <main className="controls">
        <div className="page-head"><div>
          <h1 className="page-title">Me vs the machines</h1>
          <p className="small" style={{ margin: 0 }}>Your own pretend account against the AI council and the rule bots, on the same prices and costs.
            The {acct.data?.rules.record_year ?? 2027} record opens empty at the 31 Dec 2026 close; until then it's practice.</p>
        </div></div>
        {(acct.isError || board.isError) && <Status tone="problem" word={`Unreadable: ${err(acct.error ?? board.error)}`} />}

        <section className="glass panel league-kpis" aria-label="Head to head">
          <div className="stat"><span className="label">Me{shown ? ` · ${shown.label}` : ""}</span><span className={`num-sm ${tone(myReturn)}`}>{pct(myReturn)}</span><span className="small">{money(shown?.equity ?? shown?.start_equity)} {shown?.valued_day ? `on ${shown.valued_day}` : "· not valued yet"}</span></div>
          <div className="stat"><span className="label">AI council</span><span className={`num-sm ${tone(ai.best)}`}>{pct(ai.best)}</span><span className="small">best of {ai.n} · average {pct(ai.avg)} · since {from ?? "—"}</span></div>
          <div className="stat"><span className="label">Rule bots</span><span className={`num-sm ${tone(rules.best)}`}>{pct(rules.best)}</span><span className="small">best of {rules.n} · average {pct(rules.avg)} · since {from ?? "—"}</span></div>
          <div className="stat"><span className="label">S&amp;P 500</span><span className={`num-sm ${tone(spxR)}`}>{pct(spxR)}</span><span className="small">buy and hold, same costs, since {from ?? "—"}</span></div>
          <div className="stat"><span className="label">My rank</span><span className="num-sm">{myR != null ? `${ranked.filter((v) => v > myR).length + 1} of ${ranked.length}` : "—"}</span><span className="small">every line on the board, same days</span></div>
        </section>

        {accounts.length > 1 && (
          <div className="chips" role="group" aria-label="Account">
            {accounts.map((a) => <button key={a.version} className={`chip${shown?.version === a.version ? " on" : ""}`} onClick={() => setTab(a.version)}>{a.label}</button>)}
          </div>
        )}
        <div className="me-grid">
        {catalog.data && <TradeTicket catalog={catalog.data} onDone={() => undefined} />}

          <section className="glass panel me-hold" aria-label="What I hold">
            <div className="panel-head"><h2>What I hold</h2><span className="label">target after the next open · rest in T-bills</span></div>
            {!shown?.target.length ? <div className="empty">Nothing yet: all in T-bills.</div> : (
              <table className="ng"><tbody>{shown.target.map((h) => (
                <tr key={h.asset}><td>{h.asset.replace("_", "/")}</td><td>{h.percent < 0 ? `sold ${(-h.percent).toFixed(1)}%` : `${h.percent.toFixed(1)}%`}</td></tr>
              ))}</tbody></table>
            )}
          </section>
          <section className="glass panel me-log" aria-label="Trade log">
            <div className="panel-head"><h2>Trade log</h2><span className="label">newest first · every reason kept</span></div>
            {!shown?.trades.length ? <div className="empty">No trades yet.</div> : (
              <div className="table-scroll" style={{ maxHeight: 320 }}><table className="ng"><tbody>{shown.trades.map((t) => (
                <tr key={t.id}><td className="small">{t.at.slice(0, 10)}</td>
                  <td>{t.side === "sell" ? "Sell" : "Buy"} {t.asset?.replace("_", "/")} → {t.percent}%<div className="note">{t.reason}</div></td></tr>
              ))}</tbody></table></div>
            )}
          </section>
        </div>

        <div className="fold">2027 predictions</div>
        {p && (<div className="split">
          <section className="glass panel" aria-label="Predictions side by side">
            <div className="panel-head"><h2>Who calls {p.year} best?</h2>
              <span className="label">{p.locked ? "locked" : `locks ${new Date(p.lock_at).toLocaleString("en-AU", { dateStyle: "medium", timeStyle: "short" })} Brisbane`} · scored Jan {p.year + 1}</span></div>
            {!p.entries.length ? <div className="empty">No predictions filed yet.</div> : (<>
              <div className="table-scroll"><table className="ng">
                <thead><tr><th>Market</th>{p.entries.map((e) => <th key={e.author}>{AUTHOR[e.author] ?? e.author}</th>)}</tr></thead>
                <tbody>
                  {Object.entries(p.markets).map(([k, label]) => (
                    <tr key={k}><td>{label}</td>{p.entries.map((e) => { const f = e.forecasts.markets[k];
                      return <td key={e.author}><span className={tone(f?.change_pct)}>{f ? `${f.direction} ${pct(f.change_pct)}` : "—"}</span></td>; })}</tr>
                  ))}
                  {Object.entries(p.macro).map(([k, label]) => (
                    <tr key={k}><td>{label}</td>{p.entries.map((e) => <td key={e.author}>{e.forecasts.macro[k]?.toFixed(2) ?? "—"}</td>)}</tr>
                  ))}
                </tbody></table></div>
              <div className="theses">{p.entries.map((e) => (
                <details key={e.author}><summary>{AUTHOR[e.author] ?? e.author}'s thesis{e.model ? ` (${e.model})` : ""} · filed {e.filed_at.slice(0, 10)}{e.versions > 1 ? ` · version ${e.versions}` : ""}</summary>
                  <p className="small" style={{ whiteSpace: "pre-wrap" }}>{e.thesis}</p></details>
              ))}</div>
            </>)}
            {!p.locked && (
              <div className="ticket-foot">
                <button className="btn" disabled={ask.isPending} onClick={() => { if (window.confirm("Ask the three AI council members for their 2027 predictions now? Each answers once; it costs a few cents.")) ask.mutate(); }}>
                  {ask.isPending ? <><Bars /> Asking the council… (can take a few minutes)</> : "Ask the AI council"}</button>
                {ask.isSuccess && <span className="small">{Object.entries(ask.data).map(([r, v]) => `${AUTHOR[r] ?? r}: ${v.filed ? "filed" : `not filed (${v.error})`}`).join(" · ")}</span>}
                {ask.isError && <Status tone="problem" word={err(ask.error)} />}
              </div>
            )}
            <p className="note">Scoring (set now): a point for each right direction (flat = within ±{p.flat_band_pct}%), ties broken by the
              smaller average miss; the three US numbers by average miss, from FRED. Predictions don't bind anyone's trades.</p>
          </section>
          {!p.locked && <PredictionForm p={p} mine={mine} key={mine?.id ?? "new"} />}
        </div>)}
      </main>
    </Shell>
  );
}
