"""Markus's own pretend account: human vs the AI council vs the rule bots in 2027.

Markus asked 20 Nov 2026 16:55 Brisbane: a fake account where he trades the
same things DDG Finance trades (S&P 500 shares, share index funds, bonds and
cash funds, commodity funds, the seven currency pairs), gives a reason for every
trade, and at the end of 2027 we see who did better: the AI council, the rule
bots, or him.

It is a twin like every other: an append-only, hash-chained list of target
weights, replayed nightly by the same engine with the same costs (5 bps a
trade, overnight financing on currencies). No orders, ever.

Rules (Opus 20 Nov, stated on the page):
- 100,000 fake US dollars at the start, the same as every league line.
- No borrowing: everything held adds to at most 100% of the account. Shares
  and funds long only; currencies either way. What is not invested sits in a
  T-bill fund (BIL), as the bots' idle cash does.
- A trade sets how much of the account one asset should be (0% = sell it all),
  with a reason (required). It fills at the next US session's open: placed
  before 09:30 New York it fills that day; placed later, the next session.
- Version 0 = practice until 31 Dec 2026. Version 1 = the 2027 record: opens
  empty at the 31 Dec 2026 close; trades from 1 Jan 2027 go there.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from research_harness.league import base, families
from twins import engine, store
from twins.config import DAILY

HUMAN_BOT = "markus"
START_EQUITY = 100_000.0
MAX_GROSS = 1.0
RECORD_YEAR = 2027
MIN_REASON = 10
RECORD_START = datetime(RECORD_YEAR - 1, 12, 31, 16, 0, tzinfo=engine.NEW_YORK)

INDEX_FUNDS = ("SPY", "QQQ", "SSO", "QLD", "RSP", "IWM", "DIA", "MDY")
BONDS_CASH = ("BIL", "SGOV", "SHY", "IEF", "TLT", "AGG", "TIP", "LQD", "HYG")
COMMODITIES = ("GLD", "SLV", "DBC", "USO", "DBA", "PDBC")
DOLLAR = ("UUP",)

# What each fund is, so the ticket never shows a bare ticker. Names: Alpaca's asset
# records (read 25 Nov 2026), shortened where Alpaca adds legal wording; TLT from iShares
# (Alpaca drops the "+"). "What it is" is a plain description. A test checks that every
# fund the catalog can show is here.
FUNDS: dict[str, tuple[str, str]] = {
    "SPY": ("SPDR S&P 500 ETF Trust", "the 500 biggest US companies"),
    "QQQ": ("Invesco QQQ Trust", "the 100 biggest non-financial Nasdaq companies, mostly tech"),
    "SSO": ("ProShares Ultra S&P500", "2× the S&P 500's daily move (borrowed exposure)"),
    "QLD": ("ProShares Ultra QQQ", "2× the Nasdaq-100's daily move (borrowed exposure)"),
    "RSP": ("Invesco S&P 500 Equal Weight ETF", "the S&P 500 with every company the same size"),
    "IWM": ("iShares Russell 2000 ETF", "2,000 small US companies"),
    "DIA": ("SPDR Dow Jones Industrial Average ETF Trust", "the 30 Dow Jones companies"),
    "MDY": ("SPDR S&P MidCap 400 ETF Trust", "400 mid-sized US companies"),
    "BIL": ("SPDR Bloomberg 1-3 Month T-Bill ETF", "US Treasury bills, 1–3 months: cash"),
    "SGOV": ("iShares 0-3 Month Treasury Bond ETF", "US Treasury bills, 0–3 months: cash"),
    "SHY": ("iShares 1-3 Year Treasury Bond ETF", "US government bonds, 1–3 years"),
    "IEF": ("iShares 7-10 Year Treasury Bond ETF", "US government bonds, 7–10 years"),
    "TLT": ("iShares 20+ Year Treasury Bond ETF", "US government bonds, 20+ years"),
    "AGG": ("iShares Core U.S. Aggregate Bond ETF", "the whole US investment-grade bond market"),
    "TIP": ("iShares TIPS Bond ETF", "US government bonds that rise with inflation"),
    "LQD": ("iShares iBoxx $ Investment Grade Corporate Bond ETF", "bonds of large, highly rated US companies"),
    "HYG": ("iShares iBoxx $ High Yield Corporate Bond ETF", "high-yield (junk) bonds of riskier US companies"),
    "GLD": ("SPDR Gold Shares", "gold"),
    "SLV": ("iShares Silver Trust", "silver"),
    "DBC": ("Invesco DB Commodity Index Tracking Fund", "a basket of commodities: energy, metals and crops"),
    "USO": ("United States Oil Fund", "crude oil, through oil futures"),
    "DBA": ("Invesco DB Agriculture Fund", "farm goods: grains, sugar, coffee, cocoa, livestock"),
    "PDBC": ("Invesco Optimum Yield Diversified Commodity Strategy No K-1 ETF",
             "a basket of commodities: energy, metals and crops"),
    "UUP": ("Invesco DB US Dollar Index Bullish Fund", "the US dollar against six major currencies"),
    "DBMF": ("iMGP DBi Managed Futures Strategy ETF", "managed futures: follows trends across markets"),
    "EEM": ("iShares MSCI Emerging Markets ETF", "big companies in emerging markets (China, India, Taiwan, Brazil and others)"),
    "EFA": ("iShares MSCI EAFE ETF", "big companies in developed markets outside the US and Canada"),
    "TAIL": ("Cambria Tail Risk ETF", "crash insurance: options that gain when US shares fall sharply"),
    "XLE": ("Energy Select Sector SPDR ETF", "big US energy companies (oil and gas)"),
}
CURRENCIES = {"EUR": "euro", "USD": "US dollar", "JPY": "Japanese yen", "GBP": "British pound",
              "AUD": "Australian dollar", "CAD": "Canadian dollar", "CHF": "Swiss franc", "NZD": "New Zealand dollar"}


def twin_id(version: int) -> str:
    return f"{HUMAN_BOT}:human:v{version}"


def version_for(now: datetime) -> int:
    return 1 if now.astimezone(engine.NEW_YORK) > RECORD_START else 0


def pairs() -> tuple[str, ...]:
    from research_harness.league.forex import PAIRS
    return PAIRS


def _fund(symbol: str) -> dict[str, str]:
    name, about = FUNDS.get(symbol, ("", ""))
    return {"symbol": symbol, "label": symbol, "name": name, "about": about}


def _pair(pair: str) -> dict[str, str]:
    base_c, quote = pair.split("_")
    return {"symbol": pair, "label": pair.replace("_", "/"), "name": f"{CURRENCIES.get(base_c, base_c)} vs {CURRENCIES.get(quote, quote)}",
            "about": f"buy = {CURRENCIES.get(base_c, base_c)} rises against the {CURRENCIES.get(quote, quote)}"}


def catalog(members: list[str], details: dict[str, dict[str, str]] | None = None) -> list[dict[str, Any]]:
    """Asset classes and what can be bought in each. Funds: only those the
    platform already prices (the league's fixed list); shares: today's S&P 500,
    with name, GICS sector and industry where ``details`` has them."""
    have = set(families.fixed_symbols())
    pick = lambda names: [_fund(s) for s in names if s in have]
    known = set(INDEX_FUNDS) | set(BONDS_CASH) | set(COMMODITIES) | set(DOLLAR)
    other = sorted(have - known)
    details = details or {}
    share = lambda s: {"symbol": s, "label": s, "name": details.get(s, {}).get("name", ""),
                       "sector": details.get(s, {}).get("sector", ""), "industry": details.get(s, {}).get("industry", "")}
    out = [{"id": "shares", "label": "US shares (S&P 500)", "assets": [share(s) for s in members]},
           {"id": "index", "label": "Share index funds", "assets": pick(INDEX_FUNDS)},
           {"id": "bonds", "label": "Bonds and cash funds", "assets": pick(BONDS_CASH)},
           {"id": "commodities", "label": "Commodities and the dollar", "assets": pick(COMMODITIES + DOLLAR)},
           {"id": "fx", "label": "Currencies", "two_way": True, "assets": [_pair(p) for p in pairs()]}]
    if other:
        out.insert(4, {"id": "other", "label": "Other funds", "assets": [_fund(s) for s in other]})
    return [c for c in out if c["assets"]]


def share_details(tickers: list[str], sectors: dict[str, str], rows: list[dict],
                  wiki: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    """{ticker: name, sector, industry}. Name: Wikipedia's company name, else the holdings
    file's; sector: the league's sector source, else Wikipedia's; industry: Wikipedia's
    GICS sub-industry ('' when Wikipedia was not reachable)."""
    held = {r["ticker"]: r.get("name", "") for r in rows}
    out = {}
    for t in tickers:
        w = wiki.get(t, {})
        out[t] = {"name": w.get("name") or held.get(t, ""), "sector": sectors.get(t) or w.get("sector", ""),
                  "industry": w.get("industry", "")}
    return out


def step_for(now: datetime) -> date:
    """The step a trade placed now belongs to: before the 09:30 open it is the
    previous weekday (fills at today's open); otherwise today, or Friday at a
    weekend (fills at the next session's open). A US holiday only delays a fill."""
    ny = now.astimezone(engine.NEW_YORK)
    d = ny.date()
    if ny.weekday() < 5 and ny.time() < engine.SESSION_OPEN:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def ensure_account(get_conn, version: int, now: datetime | None = None) -> dict[str, Any]:
    """The account for ``version``, opened on first use. Version 0 starts at the close before
    the first trade's fill (``now`` = the trade's time; the clock when not given)."""
    tid = twin_id(version)
    acct = next((a for a in store.accounts(get_conn, active_only=False) if a["twin_id"] == tid), None)
    if acct:
        return acct
    start = (datetime.combine(step_for(now or datetime.now(engine.NEW_YORK)), engine.SESSION_CLOSE, engine.NEW_YORK)
             if version == 0 else RECORD_START)
    store.create_account(get_conn, twin_id=tid, bot_id=HUMAN_BOT, kind="human", version=version, bars=DAILY,
                         start_at=start, start_equity=START_EQUITY,
                         config={"registration": "HUMAN-2027", "max_gross": MAX_GROSS, "allow_short": True,
                                 "stop_pct": None, "costs": "twins.config.SHARE_COSTS (5 bps); currency financing"})
    store.log_change(get_conn, kind="twin_start", bot_id=HUMAN_BOT, source="twins:human",
                     summary=f"human account {tid} opened with {START_EQUITY:,.0f}", detail={"twin_id": tid})
    return next(a for a in store.accounts(get_conn, active_only=False) if a["twin_id"] == tid)


def current_target(get_conn, tid: str) -> dict[str, float]:
    live = [d for d in store.decisions(get_conn, tid) if not d["missed"]]
    return {k: v for k, v in (live[-1]["weights"] if live else {}).items() if k != base.CASH}


def to_symbol(asset: str) -> str:
    """Catalog symbol -> simulator symbol (USD_CHF -> CHF_USD)."""
    return engine.synthetic(asset) if asset in pairs() else asset


def trade(get_conn, now: datetime, *, asset: str, side: str, percent: float, reason: str,
          members: list[str]) -> dict[str, Any]:
    """Set one asset's share of the account. Returns the new target. ValueError = refused."""
    reason = (reason or "").strip()
    if len(reason) < MIN_REASON:
        raise ValueError(f"give a reason (at least {MIN_REASON} characters)")
    allowed = {a["symbol"] for c in catalog(members) for a in c["assets"]}
    if asset not in allowed:
        raise ValueError(f"{asset} is not on the list")
    if side not in ("buy", "sell"):
        raise ValueError("side must be buy or sell")
    if not 0 <= percent <= 100:
        raise ValueError("percent must be between 0 and 100")
    fx = asset in pairs()
    if side == "sell" and not fx and percent > 0:
        raise ValueError("shares and funds cannot be sold short: use 0% to sell what you hold")
    sym = to_symbol(asset)
    w = percent / 100 * (1 if side == "buy" else -1)
    if fx and sym != asset:                     # buying USD_CHF = selling CHF in the simulator
        w = -w
    version = version_for(now)
    acct = ensure_account(get_conn, version, now)
    target = current_target(get_conn, acct["twin_id"])
    target.pop(sym, None)
    if abs(w) > 1e-9:
        target[sym] = w
    gross = sum(abs(v) for v in target.values())
    if gross > MAX_GROSS + 1e-9:
        raise ValueError(f"that makes {100 * gross:.1f}% of the account: the limit is 100% (no borrowing)")
    weights = dict(target)
    weights[base.CASH] = weights.get(base.CASH, 0.0) + max(0.0, 1.0 - gross)
    step = step_for(now)
    dec = store.append_decision(get_conn, twin_id=acct["twin_id"], decided_at=now,
                                step_at=datetime.combine(step, engine.SESSION_CLOSE, engine.NEW_YORK),
                                weights=weights, reason=reason[:500],
                                inputs={"asset": asset, "side": side, "percent": percent, "by": "Markus"})
    return {"twin_id": acct["twin_id"], "decision_id": dec["id"], "weights": dec["weights"],
            "fills_at_open_after": step.isoformat()}


def account(get_conn) -> dict[str, Any]:
    """Both versions: balance, holdings target and every trade with its reason."""
    out = []
    for version in (0, 1):
        tid = twin_id(version)
        acct = next((a for a in store.accounts(get_conn, active_only=False) if a["twin_id"] == tid), None)
        if not acct:
            continue
        rows = store.equity_rows(get_conn, tid)
        trades = [{"id": d["id"], "at": d["decided_at"].isoformat(), "fills_after": engine.step_of(d["step_at"], DAILY).isoformat(),
                   "asset": (d["inputs"] or {}).get("asset"), "side": (d["inputs"] or {}).get("side"),
                   "percent": (d["inputs"] or {}).get("percent"), "reason": d["reason"]}
                  for d in store.decisions(get_conn, tid) if not d["missed"]]
        target = current_target(get_conn, tid)
        holdings = [{"asset": next((p for p in pairs() if engine.synthetic(p) == s), s), "symbol": s,
                     "percent": round(100 * (-w if s in {engine.synthetic(p) for p in pairs()} and s not in pairs() else w), 2)}
                    for s, w in sorted(target.items(), key=lambda kv: -abs(kv[1]))]
        out.append({"version": version, "twin_id": tid, "label": "2027 record" if version else "Practice",
                    "start_at": acct["start_at"].isoformat(), "start_equity": acct["start_equity"],
                    "equity": rows[-1]["equity"] if rows else None, "valued_day": rows[-1]["day"].isoformat() if rows else None,
                    "target": holdings, "trades": trades[::-1]})
    return {"accounts": out, "rules": {"start_equity": START_EQUITY, "max_gross_pct": 100 * MAX_GROSS,
                                       "record_year": RECORD_YEAR, "min_reason": MIN_REASON}}
