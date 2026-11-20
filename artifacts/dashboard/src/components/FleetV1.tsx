/** FLEET-V1 panels (sleeve_runtime/FLEET-V1-LIVE-SPEC.md section 7).
 *  Night Glass v5 building blocks only; every value comes from the API. */
import type { ReactNode } from "react";
import { Status } from "@/components/Shell";
import type { Comparison, Figures, FleetAccount, FleetRecord, FleetState, DrawdownMode, MomoState, VaultSummary } from "@/hooks/use-fleet-v1";
import { botColor } from "@/lib/bot-identity";

const LINES = ["IEF", "GLD", "DBC", "UUP"] as const;
const LINE_NAME: Record<string, string> = { IEF: "10-yr Treasuries", GLD: "Gold", DBC: "Commodities", UUP: "US dollar" };
const CORE = ["SPY", "SSO", "QQQ", "QLD"] as const;

export const pct = (v: number | null | undefined, digits = 1, signed = false) =>
  v == null || !Number.isFinite(v) ? "—"
    : `${signed ? (v >= 0 ? "+" : "−") : v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(digits)}%`;
const num = (v: number | null | undefined, digits = 2) => (v == null || !Number.isFinite(v) ? "—" : v.toFixed(digits));

function modeStatus(mode: DrawdownMode | undefined) {
  if (mode === "halt") return <Status tone="problem" word="Halted: in cash" />;
  if (mode === "soft") return <Status tone="late" word="Drawdown: half size" />;
  return <Status tone="ok" word="Normal size" />;
}

function Row({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <li>
      <span className="grow small">{label}{sub != null && <span className="note"> · {sub}</span>}</span>
      <span className="tab">{value}</span>
    </li>
  );
}

/** Drawdown from the high-water mark against the 15% and 22% lines. */
function DrawdownMeter({ dd, soft, hard }: { dd: number | null; soft: number; hard: number }) {
  const scale = hard * 1.25;
  const at = (x: number) => `${Math.min(100, (x / scale) * 100)}%`;
  return (
    <div>
      <div className="engine-invested">
        <span className="label">Drawdown from high-water mark</span>
        <span className="small tab">{dd == null ? "—" : pct(dd)}</span>
      </div>
      <div className="meter" style={{ position: "relative", overflow: "visible" }} role="meter"
        aria-label="Drawdown" aria-valuemin={0} aria-valuemax={Math.round(scale * 100)}
        aria-valuenow={dd == null ? undefined : Math.round(dd * 100)}>
        <i style={{ width: at(Math.max(0, dd ?? 0)) }} />
        <b title={`Soft limit ${pct(soft, 0)}`} style={{ position: "absolute", left: at(soft), top: -3, width: 1, height: 10, background: "#F5A524" }} />
        <b title={`Hard limit ${pct(hard, 0)}`} style={{ position: "absolute", left: at(hard), top: -3, width: 2, height: 10, background: "#F5A524" }} />
      </div>
      <div className="note">Lines at {pct(soft, 0)} (half size) and {pct(hard, 0)} (all cash, owner clears)</div>
    </div>
  );
}

export function FleetAccountPanel({ account, state }: { account: FleetAccount; state: FleetState }) {
  const t = account.targets;
  const sc = account.since_cutover;
  const xa = account.xasset_weight > 0;
  return (
    <section className="glass panel fleet-account" aria-label={account.registration}>
      <div className="panel-head">
        <h2><span className="dot" style={{ background: botColor(account.bot_id), marginRight: 8, verticalAlign: "middle" }} aria-hidden="true" />
          {account.registration}</h2>
        {modeStatus(account.drawdown.mode)}
      </div>
      <div className="note">{account.role}</div>
      <div className="engine-stats">
        <div className="stat"><span className="label">Trend votes</span><span className="num-sm">{account.votes ?? "—"} / 3</span></div>
        <div className="stat"><span className="label">Volatility (20d)</span><span className="num-sm">{pct(account.vol20, 0)}</span></div>
        <div className="stat"><span className="label">Core exposure</span><span className="num-sm">{account.exposure == null ? "—" : `${num(account.exposure)}×`}</span></div>
      </div>
      <DrawdownMeter dd={account.drawdown.drawdown} soft={state.limits.soft} hard={state.limits.hard} />
      {sc && (
        <div className="small tab">
          Since {sc.from}: account <b>{pct(sc.account_return, 1, true)}</b> · SPY <b>{pct(sc.spy_price_return, 1, true)}</b>
          <span className="note"> (SPY price only)</span>
        </div>
      )}
      <ul className="list">
        {CORE.map((s) => <Row key={s} label={s} value={pct(t[s] ?? 0)} sub={s === "SSO" || s === "QLD" ? "2×, 20% stop" : "20% stop"} />)}
        {xa && LINES.map((s) => (
          <Row key={s} label={`${s} · ${LINE_NAME[s]}`} value={(t[s] ?? 0) > 0 ? pct(t[s]) : "off"} sub="no stop" />
        ))}
      </ul>
      <div className="note">
        Targets set {account.signal_day ?? "—"}
        {account.last_rebalance_done === false && <span className="loss"> · last rebalance incomplete ({account.attempts} attempts)</span>}
        {account.errors.length > 0 && <span className="loss"> · {account.errors[0]}</span>}
        {account.drawdown.error && <span className="loss"> · {account.drawdown.error}</span>}
      </div>
    </section>
  );
}

// ── Bench: the research record ──────────────────────────────────────────────
const NAMES: Record<string, string> = {
  B: "S&P 500 (buy and hold)", F1: "F1 · the fleet (selected)", F2: "F2 · S&P-only core + cross-asset",
  C1: "C1 · core alone", C2: "C2 · S&P-only core", A0: "A0 · old G4 rules", N1: "N1 · constant 1.2×", S2: "S2 · cross-asset alone",
};

function FiguresTable({ series, order, haircut = false }: { series: Record<string, Figures | null>; order: string[]; haircut?: boolean }) {
  const rows = order.filter((k) => series[k]);
  return (
    <div className="table-scroll">
      <table className="ng">
        <thead><tr>
          <th>Series</th><th className="money">Yearly return</th><th className="money">Sharpe</th>
          <th className="money">Worst fall</th>{haircut && <th className="money">After haircut</th>}
        </tr></thead>
        <tbody>
          {rows.map((k) => {
            const f = series[k]!;
            return (
              <tr key={k}>
                <td>{NAMES[k] ?? k}</td>
                <td className="money">{pct(f.cagr)}</td>
                <td className="money">{num(f.sharpe)}</td>
                <td className="money">{pct(f.max_drawdown)}</td>
                {haircut && <td className="money">{pct(f.max_drawdown_after_haircut ?? null)}</td>}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function FleetRecordPanel({ record }: { record: FleetRecord }) {
  const ex = record.exploration;
  const ho = record.heldout;
  const failed = ho?.verdict?.startsWith("FAIL");
  return (
    <section className="glass panel" aria-label="FLEET-V1 research record">
      <div className="panel-head">
        <h2>FLEET-V1 · the tested record</h2>
        {ho ? <Status tone={failed ? "problem" : "ok"} word={failed ? "Held-out test: FAILED its bar" : "Held-out test: passed"} />
          : <Status tone="none" word="Held-out result not on this server yet" />}
      </div>
      <p className="body" style={{ margin: 0 }}>
        Pre-registered before any data was read ({record.plan}). F1 was chosen on 1987–2010 by the plan's rule, then tested once on
        2011–2020. It did not beat the S&amp;P 500's return; it roughly halved its worst fall. It runs for that, not for beating the index.
      </p>
      {ho && (
        <>
          <div className="panel-head"><h2>Held-out {ho.test.window?.join(" – ")}</h2><span className="label">{ho.verdict}</span></div>
          <FiguresTable series={ho.test.series} order={["B", "F1", "C1", "S2"]} />
          {ho.test.pass_bar && (
            <ul className="list">
              {Object.entries(ho.test.pass_bar).map(([k, ok]) => (
                <Row key={k} label={k.replace(/^\d_/, "").replace(/_/g, " ")} value={<Status tone={ok ? "ok" : "problem"} word={ok ? "met" : "missed"} />} />
              ))}
              <Row label="deflated Sharpe (19 trials)" value={num(ho.test.deflated_sharpe)} />
            </ul>
          )}
          <div className="panel-head"><h2>Spent window {ho.spent.window?.join(" – ") ?? ""}</h2><span className="label">information only</span></div>
          <FiguresTable series={ho.spent.series} order={["B", "F1", "C1", "S2"]} />
        </>
      )}
      {ex && (
        <>
          <div className="panel-head"><h2>Exploration {ex.window?.join(" – ")}</h2><span className="label">selected: {ex.selected ?? "none"}</span></div>
          <FiguresTable series={ex.series} order={["B", "F1", "F2", "C1", "C2", "S2", "A0", "N1"]} haircut />
          <div className="note">
            Random-gear null, 95th percentile Sharpe: {num(ex.n2_sharpe_p95)} · F1 beat the S&amp;P's Sharpe in{" "}
            {pct(ex.rolling_win_share?.F1 ?? null, 0)} of the ten-year windows ·
            reconstructed instruments before each ETF existed (haircut applied).
          </div>
        </>
      )}
    </section>
  );
}

// ── MOMO-V2: Momentum's account ──────────────────────────────────────────────
export function MomoPanel({ momo, limits }: { momo: MomoState; limits: FleetState["limits"] | null }) {
  const sc = momo.since_cutover;
  const weights = momo.names.map((n) => ({ name: n, w: momo.targets[n] ?? 0 }));
  const invested = Object.values(momo.targets).reduce((a, b) => a + b, 0);
  const brake = momo.held === "out" ? <Status tone="late" word="Brake on: all cash" />
    : momo.trend_on === false ? <Status tone="late" word="Trend broken" /> : modeStatus(momo.drawdown.mode);
  return (
    <section className="glass panel fleet-account" aria-label={momo.registration}>
      <div className="panel-head">
        <h2><span className="dot" style={{ background: botColor(momo.bot_id), marginRight: 8, verticalAlign: "middle" }} aria-hidden="true" />
          {momo.registration} <span className="note">experiment</span></h2>
        {brake}
      </div>
      <div className="note">{momo.role}</div>
      <div className="engine-stats">
        <div className="stat"><span className="label">Book trend</span>
          <span className="num-sm">{momo.trend_on == null ? "—" : momo.trend_on ? "Up" : "Down"}</span></div>
        <div className="stat"><span className="label">Invested</span><span className="num-sm">{pct(invested, 0)}</span></div>
        <div className="stat"><span className="label">Names held</span>
          <span className="num-sm">{momo.names.length - momo.stopped.length} / {momo.names.length || 50}</span></div>
      </div>
      <div className="note">
        Book index {num(momo.book_index, 1)} vs its 100-day average {num(momo.book_sma100, 1)} ·
        volatility {pct(momo.book_vol20, 0)} · sized at {pct(momo.invested_fraction, 0)}
      </div>
      {limits && <DrawdownMeter dd={momo.drawdown.drawdown} soft={limits.soft} hard={limits.hard} />}
      {sc && (
        <div className="small tab">
          Since {sc.from}: account <b>{pct(sc.account_return, 1, true)}</b> · SPY <b>{pct(sc.spy_price_return, 1, true)}</b>
          <span className="note"> (SPY price only)</span>
        </div>
      )}
      <ul className="list">
        {weights.slice(0, 8).map(({ name, w }) => (
          <Row key={name} label={name} value={momo.stopped.includes(name) ? "stopped" : pct(w)}
            sub={momo.stopped.includes(name) ? "cash until next month" : "20% stop"} />
        ))}
        {weights.length > 8 && <Row label={`… ${weights.length - 8} more`} value="" />}
      </ul>
      <div className="note">
        Picked {momo.selection_day ?? "—"} from the S&amp;P 500 ({momo.universe_source ?? "—"})
        {momo.skipped_unaffordable.length > 0 && <> · skipped (price above a 2% slot): {momo.skipped_unaffordable.join(", ")}</>}
        {momo.last_rebalance_done === false && <span className="loss"> · last rebalance incomplete ({momo.attempts} attempts)</span>}
        {momo.errors.length > 0 && <span className="loss"> · {momo.errors[0]}</span>}
      </div>
    </section>
  );
}

// ── The 2027 comparison: same days, after costs ─────────────────────────────
export function ComparisonPanel({ data, names }: { data: Comparison | undefined; names: Record<string, string> }) {
  const ids = Object.keys(names);
  return (
    <section className="glass panel comparison" aria-label="The 2027 comparison">
      <div className="panel-head">
        <h2>The 2027 comparison · same days</h2>
        <span className="label">verdict 31 Dec 2027</span>
      </div>
      {!data || data.days < 2 ? (
        <div className="note">Starts with the first two closes after cutover ({data?.since ?? "9 Nov 2026"}).</div>
      ) : (
        <div className="table-scroll">
          <table className="ng">
            <thead><tr><th>Account</th><th>Return</th><th>S&amp;P same days</th><th>Worst fall</th><th>Sharpe</th></tr></thead>
            <tbody>
              {ids.map((id) => {
                const a = data.accounts[id];
                return (
                  <tr key={id}>
                    <td><span className="dot" style={{ background: botColor(id), marginRight: 8 }} aria-hidden="true" />{names[id]}</td>
                    <td className="tab">{a ? pct(a.return, 1, true) : "—"}</td>
                    <td className="tab">{a ? pct(a.spy_same_days, 1, true) : "—"}</td>
                    <td className="tab">{a ? pct(a.worst_fall, 1) : "—"}</td>
                    <td className="tab">{a?.sharpe == null ? "—" : a.sharpe.toFixed(2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="note">{data.days} common days since {data.since} · {data.note} · Sharpe from 20 days</div>
        </div>
      )}
    </section>
  );
}

// ── VAULT-V2: the profit vault ──────────────────────────────────────────────
const usd = (v: number | null | undefined) =>
  v == null || !Number.isFinite(v) ? "—" : `${v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;

export function VaultPanel({ vault, names }: { vault: VaultSummary | undefined; names: Record<string, string> }) {
  const sum = (k: "income_month" | "income_lifetime" | "contributions_year" | "contributions_lifetime") =>
    vault?.bots.some((b) => b[k] != null) ? vault.bots.reduce((s, b) => s + (b[k] ?? 0), 0) : null;
  const yields = (vault?.bots ?? []).map((b) => b.yield_30d_realized).filter((y): y is number => y != null);
  return (
    <section className="glass panel fleet-account" aria-label="Vault">
      <div className="panel-head">
        <h2>Vault · {vault?.asset ?? "BIL"}</h2>
        {vault?.enabled ? <Status tone="ok" word="On" /> : <Status tone="none" word={vault ? "Off" : "…"} />}
      </div>
      <div className="stat">
        <span className="num">{usd(vault?.total)}</span>
        <span className="note">{vault?.rule ?? "10% of each month's new high, into T-bills"}</span>
      </div>
      <div className="engine-stats">
        <div className="stat"><span className="label">Income month</span><span className="num-sm">{usd(sum("income_month"))}</span></div>
        <div className="stat"><span className="label">Income total</span><span className="num-sm">{usd(sum("income_lifetime"))}</span></div>
        <div className="stat"><span className="label">Yield 30d</span>
          <span className="num-sm">{yields.length ? pct(yields.reduce((a, b) => a + b, 0) / yields.length, 1) : "—"}</span></div>
      </div>
      <ul className="list">
        {(vault?.bots ?? []).map((b) => (
          <Row key={b.bot_id} label={names[b.bot_id] ?? b.bot_id} value={usd(b.value)}
            sub={b.from_mark == null ? "mark set at first close"
              : b.from_mark >= 0 ? `${pct(b.from_mark, 1)} above its mark` : `${pct(-b.from_mark, 1)} below its mark`} />
        ))}
      </ul>
      <div className="note">
        Added this year {usd(sum("contributions_year"))} · all time {usd(sum("contributions_lifetime"))} ·
        next skim {vault?.next_skim ?? "—"} (before the open)
        {(vault?.bots ?? []).some((b) => b.voo_qty > 0) && <> · VOO from the old vault is being sold into BIL</>}
      </div>
    </section>
  );
}
