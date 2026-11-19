"""Month-end freeze, drift check, one-page report and off-site copy
(TWINS-V2 "Record keeping"; roadmap Phase 2). No orders.

Each night, after the replay:
1. FREEZE: every twin (bot twins and league lines) gets its figures for each
   finished month written once to the append-only twin_month_freeze table:
   start and end value, return, worst fall inside the month, decisions,
   missed decisions, AI votes and their cost, and the last decision hash.
2. DRIFT: the nightly replay may revise history when price data is revised.
   Any frozen month whose return now differs by more than 0.1 points is
   reported and alarmed (shown, not hidden). The frozen row is never changed.
3. COPY: the frozen month (JSON + a one-page Markdown report) is committed to
   a GitHub repository, so the record survives the loss of the database and a
   cut-off decision log can be detected. Off until GITHUB_RECORDS_TOKEN and
   GITHUB_RECORDS_REPO are set in Replit Secrets (Markus). A file already
   there is never overwritten: a different one is an alarm.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import date, datetime, timedelta
from typing import Any, Callable

from loguru import logger

from twins import engine, store

DRIFT_GUARD_PP = 0.1
RECORDS_DIR = "records"


def month_start(d: date) -> date:
    return d.replace(day=1)


def next_month(m: date) -> date:
    return (m.replace(day=28) + timedelta(days=4)).replace(day=1)


def worst_fall(values: list[float]) -> float:
    peak, worst = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return worst


def figures(acct: dict[str, Any], rows: list[dict[str, Any]], month: date) -> dict[str, Any] | None:
    """The month's value figures from the equity rows, or None if it has no rows."""
    before = [r for r in rows if r["day"] < month and r["equity"]]
    inside = [r for r in rows if month <= r["day"] < next_month(month) and r["equity"]]
    if not inside:
        return None
    first = before[-1]["equity"] if before else acct["start_equity"]
    values = [first] + [r["equity"] for r in inside]
    refs = [r["ref_equity"] for r in inside if r.get("ref_equity")]
    return {"equity_start": round(first, 2), "equity_end": round(values[-1], 2),
            "return_pct": round(100 * (values[-1] / first - 1), 4),
            "worst_fall_pct": round(100 * worst_fall(values), 4),
            "ref_equity_end": round(refs[-1], 2) if refs else None, "days": len(inside)}


def finished_months(start: date, today: date) -> list[date]:
    """Every month from the one ``start`` falls in up to the one before ``today``'s."""
    out, m = [], month_start(start)
    while m < month_start(today):
        out.append(m)
        m = next_month(m)
    return out


def freeze_all(get_conn, now: datetime, only: set[str] | None = None) -> list[str]:
    """Freeze every finished month not frozen yet. Returns 'twin_id month' strings written.
    ``only``: the twins valued tonight; a twin whose replay failed waits, so a month
    is never frozen from equity rows missing its last days."""
    today = now.astimezone(engine.NEW_YORK).date()
    have = {(r["twin_id"], r["month"]) for r in store.frozen(get_conn)}
    written = []
    for acct in store.accounts(get_conn, active_only=False):
        if only is not None and acct["twin_id"] not in only:
            continue
        start = engine.step_of(acct["start_at"], acct["bars"])
        start = start.date() if isinstance(start, datetime) else start
        rows = store.equity_rows(get_conn, acct["twin_id"])
        for m in finished_months(start, today):
            if (acct["twin_id"], m) in have:
                continue
            fig = figures(acct, rows, m)
            if fig is None:
                continue
            lo = datetime.combine(m, datetime.min.time(), engine.NEW_YORK)
            hi = datetime.combine(next_month(m), datetime.min.time(), engine.NEW_YORK)
            row = {"twin_id": acct["twin_id"], "month": m, **fig,
                   **store.month_activity(get_conn, acct["twin_id"], lo, hi)}
            if store.freeze_month(get_conn, row):
                written.append(f"{acct['twin_id']} {m:%Y-%m}")
    return written


def drift(get_conn) -> list[dict[str, Any]]:
    """Frozen months whose return, recomputed from today's equity rows, moved > 0.1 points."""
    accts = {a["twin_id"]: a for a in store.accounts(get_conn, active_only=False)}
    rows_by = {}
    out = []
    for f in store.frozen(get_conn):
        acct = accts.get(f["twin_id"])
        if acct is None:
            continue
        rows = rows_by.setdefault(f["twin_id"], store.equity_rows(get_conn, f["twin_id"]))
        now = figures(acct, rows, f["month"])
        if now is None:
            continue
        gap = now["return_pct"] - f["return_pct"]
        if abs(gap) > DRIFT_GUARD_PP:
            out.append({"twin_id": f["twin_id"], "month": f["month"].isoformat(),
                        "frozen_pct": f["return_pct"], "now_pct": now["return_pct"], "gap_pp": round(gap, 4)})
    return out


# ── the one-page report and the off-site copy ────────────────────────────────
def payload(rows: list[dict[str, Any]], month: date) -> dict[str, Any]:
    return {"month": f"{month:%Y-%m}", "lines": [
        {k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in r.items()}
        for r in rows if r["month"] == month]}


def report_md(data: dict[str, Any]) -> str:
    """One page: every line, good or bad, best month return first."""
    lines = sorted(data["lines"], key=lambda r: -r["return_pct"])
    out = [f"# DDG Finance — {data['month']} (frozen figures)", "",
           "Paper money. Every line, good or bad. Figures are written once and never recomputed.", "",
           "| Line | Return | Worst fall | End value | Real account | Decisions | Missed | AI cost | Last hash |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for r in lines:
        real = f"{r['ref_equity_end']:,.2f}" if r["ref_equity_end"] is not None else "—"
        out.append(f"| {r['twin_id']} | {r['return_pct']:+.2f}% | {r['worst_fall_pct']:.2f}% | "
                   f"{r['equity_end']:,.2f} | {real} | {r['decisions']} | {r['missed']} | "
                   f"${r['ai_cost_usd']:.2f} | {(r['last_hash'] or '—')[:12]} |")
    return "\n".join(out) + "\n"


def _github(method: str, url: str, token: str, body: dict[str, Any] | None = None):
    import requests

    return requests.request(method, url, json=body, timeout=30,
                            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})


def copy_month(month: date, files: dict[str, str], *, token: str, repo: str,
               http: Callable[..., Any] = _github) -> str:
    """Commit each file once. 'copied' / 'already there' / raises on a different file."""
    done = []
    for name, text in files.items():
        url = f"https://api.github.com/repos/{repo}/contents/{RECORDS_DIR}/{name}"
        got = http("GET", url, token)
        if got.status_code == 200:
            there = base64.b64decode(got.json()["content"]).decode("utf-8")
            if hashlib.sha256(there.encode()).hexdigest() != hashlib.sha256(text.encode()).hexdigest():
                raise RuntimeError(f"{RECORDS_DIR}/{name} already in {repo} with different content: not overwritten")
            done.append("already there")
            continue
        if got.status_code != 404:
            raise RuntimeError(f"GitHub answered {got.status_code} reading {name}")
        put = http("PUT", url, token, {"message": f"DDG Finance frozen month {month:%Y-%m}: {name}",
                                       "content": base64.b64encode(text.encode()).decode()})
        if put.status_code not in (200, 201):
            raise RuntimeError(f"GitHub answered {put.status_code} writing {name}")
        done.append("copied")
    return "copied" if "copied" in done else "already there"


def copy_all(get_conn, now: datetime, *, token: str | None = None, repo: str | None = None,
             http: Callable[..., Any] = _github) -> dict[str, str]:
    """Copy every frozen month not copied yet (change_log kind 'month_copied')."""
    token = token if token is not None else os.getenv("GITHUB_RECORDS_TOKEN", "").strip()
    repo = repo if repo is not None else os.getenv("GITHUB_RECORDS_REPO", "").strip()
    if not token or not repo:
        return {"status": "off: GITHUB_RECORDS_TOKEN / GITHUB_RECORDS_REPO not set"}
    rows = store.frozen(get_conn)
    out = {}
    for month in sorted({r["month"] for r in rows}):
        done = store.last_change(get_conn, (f"month_copied_{month:%Y_%m}",))
        if done:
            continue
        data = payload(rows, month)
        text = json.dumps(data, indent=2, sort_keys=True) + "\n"
        files = {f"{month:%Y-%m}.json": text, f"{month:%Y-%m}.md": report_md(data)}
        out[f"{month:%Y-%m}"] = copy_month(month, files, token=token, repo=repo, http=http)
        store.log_change(get_conn, kind=f"month_copied_{month:%Y_%m}", source="twins:month_end",
                         summary=f"frozen month {month:%Y-%m} copied to {repo}",
                         detail={"repo": repo, "lines": len(data["lines"]),
                                 "sha256": hashlib.sha256(text.encode()).hexdigest()}, at=now)
    return out


def run(get_conn, now: datetime, alarm: Callable[..., None], resolve: Callable[..., None], *,
        only: set[str] | None = None, **copy_kw) -> dict[str, Any]:
    report: dict[str, Any] = {"frozen": freeze_all(get_conn, now, only)}
    moved = drift(get_conn)
    report["drift"] = moved
    if moved:
        m = moved[0]
        alarm("warning", "twin_freeze_drift",
              f"{len(moved)} frozen month(s) now read differently after price revisions, e.g. {m['twin_id']} "
              f"{m['month']}: frozen {m['frozen_pct']:+.2f}% vs now {m['now_pct']:+.2f}%. Frozen figures stand.")
    else:
        resolve("twin_freeze_drift")
    try:
        report["copy"] = copy_all(get_conn, now, **copy_kw)
        resolve("twin_freeze_copy_failed")
    except Exception as exc:
        logger.exception("month-end copy failed")
        alarm("error", "twin_freeze_copy_failed", f"month-end copy to GitHub failed: {type(exc).__name__}: "
              f"{str(exc)[:200]}")
        report["copy"] = f"failed: {type(exc).__name__}"
    return report
