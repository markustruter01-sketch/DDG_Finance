"""
global_backtest_phase2.py — Phase 2: Portfolio Assembly + Benchmark Shootout

Parts:
  A. EM risk adaptations: vol-targeted sizing, vol-scaled stops, per-market regime
  B. Correlation cap: rolling 60d, ≤2 positions with pairwise ρ > 0.75
  C. Combined portfolio: all 4 regions, vol-targeted, corr-capped, 8-10 concurrent max
  D. Benchmark shootout: Global vs SPY-only (Moe) vs BaH-EEM vs BaH-SPY
  E. 2022 currency stress test: DXY spike vs per-region drawdown + correlation

PRE-REGISTERED SUCCESS BAR:
  PASS:    global portfolio beats SPY-only by ≥0.15 pooled Sharpe  OR
           reduces pooled maxDD by ≥20% (without giving back >0.05 Sharpe)
  PARTIAL: some regions add value → identify trimmed portfolio that beats SPY-only
  FAIL:    portfolio only matches or trails → "run US Core on SPY", done.

DATA: Yahoo Finance v8 adjClose daily (Alpaca SIP unavailable).
      Single source per window, no mid-window splicing.

READ-ONLY. No trades. No DB writes. Honor whatever the shootout says.
"""
from __future__ import annotations

import math
import datetime
import time
import sys
import os
import requests
from collections import defaultdict
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))
from global_universe import TICKER_REGION

# ── Universe ──────────────────────────────────────────────────────────────────
UNIVERSE = [
    "SPY", "QQQ",
    "EWY", "EWT", "INDA", "EWJ", "EWM", "VNM",
    "EWZ", "EWW", "ECH",
    "EEM", "EZA", "EPOL", "GREK", "TUR",
]

# ── Strategy parameters (Part A adaptations noted) ────────────────────────────
TARGET_VOL        = 0.12   # 12% portfolio vol target (Part A)
MAX_POSITION_WT   = 0.25   # hard cap per position (Part A)
MAX_DEPLOYMENT    = 0.85   # max total equity deployed
CASH_RESERVE      = 0.15   # min cash reserve
N_PLANNING        = 8      # planning N for vol-targeting denominator
MIN_HOLD_DAYS     = 5
TP1_PCT           = 0.06
TP2_PCT           = 0.12
TRAIL_STOP_MIN    = 0.08   # floor (Part A)
ATR_STOP_MULT     = 2.0    # stop = max(8%, 2×ATR%) (Part A)
ATR_PERIOD        = 14
VOL_PERIOD        = 20     # 20-day realized vol
CORR_PERIOD       = 60     # rolling 60d correlation (Part B)
CORR_THRESHOLD    = 0.75   # correlation cap threshold (Part B)
MAX_CORR_PARTNERS = 1      # allow 1 correlated buddy; 2nd correlated = skip
CRISIS_SPY_THRESH = -0.12  # SPY 20d global crash gate
MAX_POSITIONS     = 10     # max concurrent fleet positions
STARTING_EQUITY   = 100_000.0

# EMA parameters (unchanged from live Moe strategy)
EMA_FAST = 50
EMA_SLOW = 200

WINDOWS = [
    ("2008_GFC",   datetime.date(2008,1,1),  datetime.date(2009,12,31), datetime.date(2007,1,1)),
    ("2011_EM",    datetime.date(2011,1,1),  datetime.date(2012,6,30),  datetime.date(2010,1,1)),
    ("2015-16_EM", datetime.date(2015,1,1),  datetime.date(2016,12,31), datetime.date(2014,1,1)),
    ("2018",       datetime.date(2018,1,1),  datetime.date(2019,3,31),  datetime.date(2017,1,1)),
    ("2020_COVID", datetime.date(2020,1,1),  datetime.date(2021,6,30),  datetime.date(2019,1,1)),
    ("2022_rates", datetime.date(2022,1,1),  datetime.date(2023,3,31),  datetime.date(2021,1,1)),
    ("2023-24",    datetime.date(2023,1,1),  datetime.date(2024,12,31), datetime.date(2022,1,1)),
]
EM_BEAR = {"2011_EM","2015-16_EM"}

# ── Fetch ──────────────────────────────────────────────────────────────────────
_HDR = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

def _fetch(ticker: str, start: datetime.date, end: datetime.date, retries=4) -> Optional[dict]:
    p1 = int(datetime.datetime.combine(start, datetime.time.min, tzinfo=datetime.timezone.utc).timestamp())
    p2 = int(datetime.datetime.combine(end,   datetime.time.max, tzinfo=datetime.timezone.utc).timestamp())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"period1": p1, "period2": p2, "interval": "1d",
              "includePrePost": "false", "events": "div,splits"}
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=_HDR, timeout=30)
            if r.status_code == 429:
                time.sleep(5*(attempt+1)); continue
            if r.status_code != 200: return None
            data = r.json()
            res = (data.get("chart",{}).get("result") or [None])[0]
            if not res: return None
            ts  = res.get("timestamp",[])
            q   = res.get("indicators",{}).get("quote",[{}])[0]
            adj = (res.get("indicators",{}).get("adjclose") or [{}])[0]
            adj_c = adj.get("adjclose",[])
            o,h,l,c,v = q.get("open",[]),q.get("high",[]),q.get("low",[]),q.get("close",[]),q.get("volume",[])
            use_c = adj_c if adj_c and len(adj_c)==len(ts) else c
            rows  = [(t,oo,hh,ll,cc,vv) for t,oo,hh,ll,cc,vv in zip(ts,o,h,l,use_c,v) if None not in (oo,hh,ll,cc)]
            if not rows: return None
            t2,o2,h2,l2,c2,v2 = zip(*rows)
            dates = [datetime.date.fromtimestamp(t) for t in t2]
            return {"dates":list(dates),"opens":list(o2),"highs":list(h2),
                    "lows":list(l2),"closes":list(c2),"volumes":list(v2)}
        except Exception:
            if attempt < retries-1: time.sleep(2*(attempt+1))
    return None

# ── Technical indicators ───────────────────────────────────────────────────────

def _ema(prices, period):
    if len(prices) < period: return None
    k = 2.0/(period+1); e = prices[0]
    for p in prices[1:]: e = p*k + e*(1-k)
    return e

def _atr(highs, lows, closes, period, up_to):
    """Wilder ATR up to index `up_to` (inclusive)."""
    trs = []
    for i in range(max(1, up_to-period*2+1), up_to+1):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        trs.append(tr)
    return sum(trs[-period:]) / min(period, len(trs)) if trs else closes[up_to]*0.02

def _realized_vol(closes, up_to, period=20):
    """Annualized 20-day realized vol of returns ending at up_to."""
    rets = [closes[i]/closes[i-1]-1 for i in range(max(1,up_to-period+1), up_to+1) if closes[i-1]>0]
    if len(rets)<3: return 0.25
    mu = sum(rets)/len(rets)
    var = sum((r-mu)**2 for r in rets)/(len(rets)-1)
    return (var**0.5)*(252**0.5)

def _rolling_corr(ca, cb, up_to, period=60):
    """Pearson correlation of daily returns [up_to-period+1 .. up_to]."""
    ra,rb=[],[]
    for i in range(max(1,up_to-period+1), up_to+1):
        if ca[i-1]>0 and cb[i-1]>0:
            ra.append(ca[i]/ca[i-1]-1); rb.append(cb[i]/cb[i-1]-1)
    n=len(ra)
    if n<10: return 0.0
    ma,mb = sum(ra)/n, sum(rb)/n
    cov = sum((a-ma)*(b-mb) for a,b in zip(ra,rb))/(n-1)
    va  = sum((r-ma)**2 for r in ra)/(n-1)
    vb  = sum((r-mb)**2 for r in rb)/(n-1)
    if va<=0 or vb<=0: return 0.0
    return cov/((va*vb)**0.5)

def _entry_signal(closes, up_to):
    """EMA50>EMA200 AND EMA50 rising AND price>EMA50 (per-ETF regime)."""
    c = closes[max(0,up_to-255):up_to+1]
    if len(c) < EMA_SLOW+5: return False, 0.0
    ef_now  = _ema(c, EMA_FAST)
    es_now  = _ema(c, EMA_SLOW)
    ef_prev = _ema(c[:-5], EMA_FAST)
    if any(v is None for v in (ef_now,es_now,ef_prev)): return False, 0.0
    sig = ef_now>es_now and ef_now>ef_prev and c[-1]>ef_now
    strength = ef_now/es_now if es_now>0 else 0.0  # trend strength for corr-cap tie-break
    return sig, strength

def _crisis_gate(spy_c, up_to):
    """Returns True (= BLOCKED) if SPY 20d return ≤ -12%."""
    start = max(0, up_to-20)
    sl = spy_c[start:up_to+1]
    if len(sl)<21: return True
    return (sl[-1]/sl[0]-1) <= CRISIS_SPY_THRESH

# ── Position ──────────────────────────────────────────────────────────────────
class _Pos:
    __slots__ = ("ticker","region","entry_date","entry_price","original_qty",
                 "actual_qty","stop_price","stop_dist","tp1_price","tp2_price",
                 "scaled_tp1","scaled_tp2")
    def __init__(self, ticker, region, entry_date, entry_price, qty, stop_dist):
        self.ticker       = ticker
        self.region       = region
        self.entry_date   = entry_date
        self.entry_price  = entry_price
        self.original_qty = qty
        self.actual_qty   = qty
        self.stop_dist    = stop_dist
        self.stop_price   = entry_price*(1-stop_dist)
        self.tp1_price    = entry_price*(1+TP1_PCT)
        self.tp2_price    = entry_price*(1+TP2_PCT)
        self.scaled_tp1   = False
        self.scaled_tp2   = False
    def min_hold_ok(self, d): return (d-self.entry_date).days >= MIN_HOLD_DAYS
    def ratchet(self, price):
        ns = price*(1-self.stop_dist)
        if ns > self.stop_price: self.stop_price = ns

# ── Portfolio window runner ────────────────────────────────────────────────────

def _run_portfolio_window(aligned_dates, closes_map, highs_map, lows_map,
                          spy_closes, date_to_spy_idx, window_start, window_end,
                          eligible_tickers):
    equity  = STARTING_EQUITY
    cash    = STARTING_EQUITY
    positions: list[_Pos] = []
    eq_curve = [equity]
    peak, max_dd = equity, 0.0

    trade_log = []
    entry_log = []
    corr_cap_skips = []
    tp1f = tp2f = threedf = 0
    bars_in_window = bars_in_pos = 0

    # Per-region daily equity tracking (for Part E)
    region_daily: dict[str,list[float]] = defaultdict(list)

    def _tail(arr, dt, n):
        idx = aligned_dates.index(dt)
        return arr[max(0,idx-n+1):idx+1]

    def _idx(dt): return aligned_dates.index(dt)

    for date in aligned_dates:
        if not (window_start <= date <= window_end): continue
        bars_in_window += 1
        idx = _idx(date)

        # Current prices
        px = {t: closes_map[t][idx] for t in eligible_tickers if closes_map[t][idx] is not None}

        # ── Exits ──────────────────────────────────────────────────────────
        for pos in list(positions):
            t = pos.ticker
            if t not in px: continue
            price = px[t]
            pos.ratchet(price)

            # Stop
            if price <= pos.stop_price:
                pnl_usd = pos.actual_qty*price - pos.original_qty*pos.entry_price
                cash += pos.actual_qty*price
                positions.remove(pos)
                trade_log.append({"date":date,"ticker":t,"region":pos.region,
                                   "exit":"stop","pnl_usd":pnl_usd,
                                   "pnl_pct":(price-pos.entry_price)/pos.entry_price})
                continue

            min_ok = pos.min_hold_ok(date)

            # TP2 / TP1 scale-outs
            if min_ok and not pos.scaled_tp2 and price>=pos.tp2_price:
                sc = pos.original_qty*0.333; cash+=sc*price; pos.actual_qty-=sc
                pos.scaled_tp2=True; tp2f+=1
            if min_ok and not pos.scaled_tp1 and price>=pos.tp1_price:
                sc = pos.original_qty*0.333; cash+=sc*price; pos.actual_qty-=sc
                pos.scaled_tp1=True; tp1f+=1

            if not min_ok: continue

            c80 = _tail(closes_map[t], date, 80)
            # EMA50 exit (using own EMA, not SPY)
            sl = c80[-EMA_FAST:] if len(c80)>=EMA_FAST else c80
            e50 = _ema(sl, EMA_FAST)
            if e50 and price < e50:
                pnl_usd = pos.actual_qty*price - pos.original_qty*pos.entry_price
                cash += pos.actual_qty*price
                positions.remove(pos)
                trade_log.append({"date":date,"ticker":t,"region":pos.region,
                                   "exit":"ema50","pnl_usd":pnl_usd,
                                   "pnl_pct":(price-pos.entry_price)/pos.entry_price})
                continue

            # 3-day drop (last-3-bars only)
            if len(c80)>=4:
                chg = (c80[-1]-c80[-4])/c80[-4]
                if chg <= -0.05:
                    pnl_usd = pos.actual_qty*price - pos.original_qty*pos.entry_price
                    cash += pos.actual_qty*price
                    positions.remove(pos)
                    trade_log.append({"date":date,"ticker":t,"region":pos.region,
                                       "exit":"3day","pnl_usd":pnl_usd,
                                       "pnl_pct":(price-pos.entry_price)/pos.entry_price})
                    threedf+=1
                    continue

        # ── Entries ────────────────────────────────────────────────────────
        spy_gi = date_to_spy_idx.get(date)
        in_crisis = _crisis_gate(spy_closes, spy_gi) if spy_gi is not None else True

        held_tickers = {p.ticker for p in positions}
        pos_val   = sum(p.actual_qty*px.get(p.ticker, p.entry_price) for p in positions)
        deployed  = pos_val/equity if equity>0 else 1.0

        if not in_crisis and len(positions) < MAX_POSITIONS:
            # Collect all candidates this bar
            candidates = []
            for t in eligible_tickers:
                if t in held_tickers: continue
                if t not in px: continue
                sig, strength = _entry_signal(closes_map[t], idx)
                if sig:
                    candidates.append((strength, t))

            # Sort by trend strength descending
            candidates.sort(reverse=True)

            for strength, t in candidates:
                if len(positions) >= MAX_POSITIONS: break
                pos_val_now = sum(p.actual_qty*px.get(p.ticker, p.entry_price) for p in positions)
                deployed_now = pos_val_now/equity if equity>0 else 1.0
                if deployed_now >= MAX_DEPLOYMENT: break

                price   = px[t]
                vol_20d = _realized_vol(closes_map[t], idx, VOL_PERIOD)

                # Vol-targeted size (Part A)
                # size ∝ (TARGET_VOL/N_PLANNING) / vol_20d → allocates so each
                # position contributes TARGET_VOL/N equally to portfolio vol
                raw_wt = (TARGET_VOL / N_PLANNING) / max(vol_20d, 0.04)
                pos_wt = min(MAX_POSITION_WT, raw_wt)
                notional = equity * pos_wt
                # Cash constraint
                spare_cash = cash - equity*CASH_RESERVE
                notional = min(notional, spare_cash)
                if notional < equity*0.01: continue  # skip if < 1% of equity

                # Correlation cap (Part B)
                corr_partners = 0
                skip_by_corr  = False
                for held in positions:
                    if held.ticker not in closes_map: continue
                    rho = _rolling_corr(closes_map[t], closes_map[held.ticker], idx, CORR_PERIOD)
                    if rho > CORR_THRESHOLD:
                        corr_partners += 1
                        if corr_partners > MAX_CORR_PARTNERS:
                            skip_by_corr = True
                            break
                if skip_by_corr:
                    corr_cap_skips.append({"date":date,"ticker":t,"reason":"corr_cap"})
                    continue

                # Vol-scaled stop (Part A): max(8%, 2×ATR%)
                atr_val  = _atr(highs_map[t], lows_map[t], closes_map[t], ATR_PERIOD, idx)
                atr_pct  = atr_val/price
                stop_dist= max(TRAIL_STOP_MIN, ATR_STOP_MULT*atr_pct)

                qty  = notional/price
                cash -= notional
                p = _Pos(t, TICKER_REGION.get(t,"?"), date, price, qty, stop_dist)
                positions.append(p)
                held_tickers.add(t)
                entry_log.append({"date":date,"ticker":t,"notional":notional,
                                   "vol_20d":vol_20d,"stop_dist":stop_dist})

        # ── MTM ────────────────────────────────────────────────────────────
        pos_val = sum(p.actual_qty*px.get(p.ticker,p.entry_price) for p in positions)
        equity  = cash + pos_val
        eq_curve.append(equity)
        if positions: bars_in_pos += 1
        if equity>peak: peak=equity
        dd=(peak-equity)/peak if peak>0 else 0
        if dd>max_dd: max_dd=dd

        # Region decomp (for Part E)
        for reg in ["US_CORE","ASIA_PACIFIC","LATIN_AMERICA","FRONTIER_EM"]:
            reg_val = sum(p.actual_qty*px.get(p.ticker,p.entry_price)
                          for p in positions if p.region==reg)
            region_daily[reg].append(reg_val/equity if equity>0 else 0)

    # Force-close at window end
    last_px = {}
    for t in eligible_tickers:
        last_in_window = [d for d in aligned_dates if window_start<=d<=window_end]
        if last_in_window:
            idx2 = _idx(last_in_window[-1])
            last_px[t] = closes_map[t][idx2] if closes_map[t][idx2] is not None else None

    for pos in list(positions):
        lp = last_px.get(pos.ticker) or pos.entry_price
        pnl_usd = pos.actual_qty*lp - pos.original_qty*pos.entry_price
        cash += pos.actual_qty*lp
        trade_log.append({"date":window_end,"ticker":pos.ticker,"region":pos.region,
                           "exit":"window_end","pnl_usd":pnl_usd,
                           "pnl_pct":(lp-pos.entry_price)/pos.entry_price})
    equity=cash
    if equity<peak:
        dd=(peak-equity)/peak
        if dd>max_dd: max_dd=dd

    total_return = (equity-STARTING_EQUITY)/STARTING_EQUITY
    daily_rets   = [eq_curve[i]/eq_curve[i-1]-1 for i in range(1,len(eq_curve)) if eq_curve[i-1]>0]
    mu = sum(daily_rets)/len(daily_rets) if daily_rets else 0
    var= sum((r-mu)**2 for r in daily_rets)/(len(daily_rets)-1) if len(daily_rets)>1 else 0
    sharpe = mu/(var**0.5)*252**0.5 if var>0 else 0.0
    wr = len([t for t in trade_log if t["pnl_usd"]>0])/len(trade_log) if trade_log else 0
    time_in_cash = 1-(bars_in_pos/bars_in_window) if bars_in_window>0 else 1

    max_swing=0
    for i in range(1,len(eq_curve)):
        p=eq_curve[i-1]
        if p>0: max_swing=max(max_swing, abs(eq_curve[i]/p-1))

    return {
        "total_return":total_return,"max_dd":max_dd,"sharpe":sharpe,
        "win_rate":wr,"closed_trades":len(trade_log),"entries":len(entry_log),
        "time_in_cash":time_in_cash,"daily_rets":daily_rets,
        "corr_cap_skips":len(corr_cap_skips),"corr_cap_log":corr_cap_skips,
        "max_single_swing":max_swing,"trade_log":trade_log,
        "equity_curve":eq_curve,"region_daily":dict(region_daily),
    }


# ── SPY-only Moe (two-ticker portfolio) ───────────────────────────────────────

def _run_spy_qqq_portfolio(closes_map, highs_map, lows_map, aligned_dates,
                            date_to_spy_idx, window_start, window_end):
    """Exact Phase 1 two-ticker Moe with FIXED 40% sizing (original params)."""
    equity=STARTING_EQUITY; cash=STARTING_EQUITY
    positions:dict[str,_Pos]={}
    eq_curve=[equity]; peak=equity; max_dd=0.0
    trade_log=[]; tp1f=tp2f=threedf=0; bars_in_pos=bars_in_window=0

    SPY_QQQ = [t for t in ["SPY","QQQ"] if t in closes_map]

    def _tail2(t, dt, n):
        idx=aligned_dates.index(dt)
        return closes_map[t][max(0,idx-n+1):idx+1]

    for date in aligned_dates:
        if not (window_start<=date<=window_end): continue
        bars_in_window+=1
        idx=aligned_dates.index(date)
        px={t:closes_map[t][idx] for t in SPY_QQQ if closes_map[t][idx] is not None}

        for sym,pos in list(positions.items()):
            if sym not in px: continue
            price=px[sym]; pos.ratchet(price)
            if price<=pos.stop_price:
                pnl=pos.actual_qty*price-pos.original_qty*pos.entry_price
                cash+=pos.actual_qty*price; del positions[sym]
                trade_log.append({"sym":sym,"exit":"stop","pnl_usd":pnl}); continue
            min_ok=pos.min_hold_ok(date)
            if min_ok and not pos.scaled_tp2 and price>=pos.tp2_price:
                sc=pos.original_qty*0.333;cash+=sc*price;pos.actual_qty-=sc;pos.scaled_tp2=True;tp2f+=1
            if min_ok and not pos.scaled_tp1 and price>=pos.tp1_price:
                sc=pos.original_qty*0.333;cash+=sc*price;pos.actual_qty-=sc;pos.scaled_tp1=True;tp1f+=1
            if not min_ok: continue
            c80=_tail2(sym,date,80)
            sl=c80[-50:] if len(c80)>=50 else c80
            e50=_ema(sl,EMA_FAST)
            if e50 and price<e50:
                pnl=pos.actual_qty*price-pos.original_qty*pos.entry_price
                cash+=pos.actual_qty*price; del positions[sym]
                trade_log.append({"sym":sym,"exit":"ema50","pnl_usd":pnl}); continue
            if len(c80)>=4 and (c80[-1]-c80[-4])/c80[-4]<=-0.05:
                pnl=pos.actual_qty*price-pos.original_qty*pos.entry_price
                cash+=pos.actual_qty*price; del positions[sym]
                trade_log.append({"sym":sym,"exit":"3day","pnl_usd":pnl}); threedf+=1

        spy_gi = date_to_spy_idx.get(date)
        spy_c  = closes_map.get("SPY",[])
        crisis = _crisis_gate(spy_c, spy_gi) if spy_gi is not None else True

        pos_val=sum(p.actual_qty*px.get(s,p.entry_price) for s,p in positions.items())
        dep_pct=pos_val/equity if equity>0 else 1.0

        if not crisis:
            for sym in SPY_QQQ:
                if sym in positions or sym not in px: continue
                if dep_pct+0.40>0.80: break
                sig,_=_entry_signal(closes_map[sym],idx)
                if not sig: continue
                notional=min(equity*0.40, cash-equity*0.20)
                if notional<=0: continue
                qty=notional/px[sym]
                cash-=notional
                positions[sym]=_Pos(sym,"US_CORE",date,px[sym],qty,TRAIL_STOP_MIN)
                dep_pct+=0.40

        if positions: bars_in_pos+=1
        pos_val=sum(p.actual_qty*px.get(s,p.entry_price) for s,p in positions.items())
        equity=cash+pos_val; eq_curve.append(equity)
        if equity>peak: peak=equity
        dd=(peak-equity)/peak if peak>0 else 0
        if dd>max_dd: max_dd=dd

    for sym,pos in list(positions.items()):
        last=[d for d in aligned_dates if window_start<=d<=window_end]
        lp=closes_map[sym][aligned_dates.index(last[-1])] if last else pos.entry_price
        pnl=pos.actual_qty*lp-pos.original_qty*pos.entry_price
        cash+=pos.actual_qty*lp; trade_log.append({"sym":sym,"exit":"window_end","pnl_usd":pnl})
    equity=cash
    if equity<peak:
        dd=(peak-equity)/peak
        if dd>max_dd: max_dd=dd

    total_return=(equity-STARTING_EQUITY)/STARTING_EQUITY
    daily_rets=[eq_curve[i]/eq_curve[i-1]-1 for i in range(1,len(eq_curve)) if eq_curve[i-1]>0]
    mu=sum(daily_rets)/len(daily_rets) if daily_rets else 0
    var=sum((r-mu)**2 for r in daily_rets)/(len(daily_rets)-1) if len(daily_rets)>1 else 0
    sharpe=mu/(var**0.5)*252**0.5 if var>0 else 0.0
    wr=len([t for t in trade_log if t["pnl_usd"]>0])/len(trade_log) if trade_log else 0
    return {"total_return":total_return,"max_dd":max_dd,"sharpe":sharpe,
            "win_rate":wr,"closed_trades":len(trade_log),"daily_rets":daily_rets,
            "time_in_cash":1-(bars_in_pos/bars_in_window) if bars_in_window>0 else 1}


# ── Buy-and-hold ───────────────────────────────────────────────────────────────

def _buy_and_hold(closes, dates, window_start, window_end):
    d_range=[d for d in dates if window_start<=d<=window_end]
    if not d_range: return {"total_return":0,"max_dd":0,"sharpe":0,"daily_rets":[]}
    i0=dates.index(d_range[0]); i1=dates.index(d_range[-1])
    if closes[i0]<=0: return {"total_return":0,"max_dd":0,"sharpe":0,"daily_rets":[]}
    total_return=closes[i1]/closes[i0]-1
    # BaH equity curve
    rets=[closes[i]/closes[i-1]-1 for i in range(i0+1, i1+1) if closes[i-1]>0]
    mu=sum(rets)/len(rets) if rets else 0
    var=sum((r-mu)**2 for r in rets)/(len(rets)-1) if len(rets)>1 else 0
    sharpe=mu/(var**0.5)*252**0.5 if var>0 else 0
    # MaxDD
    eq=[100000.0]
    for r in rets: eq.append(eq[-1]*(1+r))
    peak=eq[0]; max_dd=0
    for e in eq:
        if e>peak: peak=e
        dd=(peak-e)/peak if peak>0 else 0
        if dd>max_dd: max_dd=dd
    return {"total_return":total_return,"max_dd":max_dd,"sharpe":sharpe,"daily_rets":rets}

# ── Sharpe pooling ─────────────────────────────────────────────────────────────

def _pool_sharpe(window_results):
    pooled=[]
    for r in window_results.values():
        if r and "daily_rets" in r: pooled.extend(r["daily_rets"])
    if len(pooled)<2: return 0.0
    mu=sum(pooled)/len(pooled)
    var=sum((r-mu)**2 for r in pooled)/(len(pooled)-1)
    return mu/(var**0.5)*252**0.5 if var>0 else 0.0

# ── Eligibility per window ─────────────────────────────────────────────────────
TICKER_FIRST = {
    "SPY": datetime.date(1993,2,1), "QQQ": datetime.date(1999,4,1),
    "EWY": datetime.date(2000,6,1), "EWT": datetime.date(2000,7,1),
    "INDA": datetime.date(2012,3,1), "EWJ": datetime.date(1996,4,1),
    "EWM": datetime.date(1996,4,1), "VNM": datetime.date(2009,9,1),
    "EWZ": datetime.date(2000,8,1), "EWW": datetime.date(1996,4,1),
    "ECH": datetime.date(2007,12,1), "EEM": datetime.date(2003,5,1),
    "EZA": datetime.date(2003,3,1), "EPOL": datetime.date(2010,6,1),
    "GREK": datetime.date(2012,1,1), "TUR": datetime.date(2008,4,1),
}

def _eligible(ticker, warmup_from):
    first = TICKER_FIRST.get(ticker, datetime.date(2020,1,1))
    return first <= warmup_from

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("="*100)
    print("PHASE 2 — PORTFOLIO ASSEMBLY + BENCHMARK SHOOTOUT")
    print("Vol-targeted sizing | Corr-cap | Per-market regime | Global crash gate")
    print("="*100)

    FETCH_START = datetime.date(2007,1,1)
    FETCH_END   = datetime.date(2024,12,31)

    # Fetch all data
    print("\nFetching data…")
    raw: dict[str,Optional[dict]] = {}
    for i,ticker in enumerate(UNIVERSE):
        first = TICKER_FIRST.get(ticker, FETCH_START)
        fetch_from = max(first, FETCH_START)
        sys.stdout.write(f"  {ticker:<6}… "); sys.stdout.flush()
        d = _fetch(ticker, fetch_from, FETCH_END)
        raw[ticker] = d
        print(f"{'OK '+str(len(d['dates']))+' bars' if d else 'FAILED'}")
        time.sleep(0.4)

    # Build master date list (SPY as calendar)
    spy_raw = raw["SPY"]
    master_dates = spy_raw["dates"]  # NYSE calendar
    spy_date_idx = {d:i for i,d in enumerate(master_dates)}
    spy_closes   = spy_raw["closes"]

    # Build aligned arrays: for each ticker, map master date → close/high/low (or None)
    closes_map: dict[str,list] = {}
    highs_map:  dict[str,list] = {}
    lows_map:   dict[str,list] = {}

    for ticker in UNIVERSE:
        d = raw.get(ticker)
        if not d:
            closes_map[ticker] = [None]*len(master_dates)
            highs_map[ticker]  = [None]*len(master_dates)
            lows_map[ticker]   = [None]*len(master_dates)
            continue
        tm = {dt:i for i,dt in enumerate(d["dates"])}
        c_arr,h_arr,l_arr=[],[],[]
        for md in master_dates:
            if md in tm:
                ii=tm[md]
                c_arr.append(d["closes"][ii]); h_arr.append(d["highs"][ii]); l_arr.append(d["lows"][ii])
            else:
                # Forward-fill (holds last known close for non-trading gaps)
                c_arr.append(c_arr[-1] if c_arr else None)
                h_arr.append(h_arr[-1] if h_arr else None)
                l_arr.append(l_arr[-1] if l_arr else None)
        closes_map[ticker]=c_arr; highs_map[ticker]=h_arr; lows_map[ticker]=l_arr

    # Replace None with nearest valid close (forward-fill, then backward-fill)
    for ticker in UNIVERSE:
        # Forward-fill
        last_valid = None
        for i in range(len(closes_map[ticker])):
            v = closes_map[ticker][i]
            if v is not None and v > 0:
                last_valid = v
            elif last_valid is not None:
                closes_map[ticker][i] = last_valid
                highs_map[ticker][i]  = last_valid
                lows_map[ticker][i]   = last_valid
        # Backward-fill (handles leading Nones for tickers that start late)
        last_valid = None
        for i in range(len(closes_map[ticker])-1, -1, -1):
            v = closes_map[ticker][i]
            if v is not None and v > 0:
                last_valid = v
            elif last_valid is not None:
                closes_map[ticker][i] = last_valid
                highs_map[ticker][i]  = last_valid
                lows_map[ticker][i]   = last_valid
        # Final pass: replace any remaining None/zero with 1.0 sentinel
        for i in range(len(closes_map[ticker])):
            if closes_map[ticker][i] is None or closes_map[ticker][i] <= 0:
                closes_map[ticker][i] = 1.0
                highs_map[ticker][i]  = 1.0
                lows_map[ticker][i]   = 1.0

    # ── Part C: Run portfolio across all windows ──────────────────────────────
    print("\n"+"="*100)
    print("PART C — GLOBAL PORTFOLIO (vol-targeted, corr-capped, all regions)")
    print("="*100)

    port_results  = {}
    spyqqq_results= {}
    bah_eem_results={}
    bah_spy_results={}

    for label,wstart,wend,warmup_from in WINDOWS:
        elig = [t for t in UNIVERSE if _eligible(t, warmup_from)]
        n_elig = len(elig)
        print(f"\nWindow: {label}  ({wstart}→{wend})  eligible tickers: {n_elig}")
        window_master = [d for d in master_dates if warmup_from<=d<=wend]
        if len(window_master)<50:
            print(f"  SKIP — insufficient data"); continue

        # Global portfolio
        r = _run_portfolio_window(
            window_master, closes_map, highs_map, lows_map,
            spy_closes, spy_date_idx, wstart, wend, elig
        )
        port_results[label] = r
        print(f"  GLOBAL:   ret={r['total_return']:+.1%}  maxDD={r['max_dd']:.1%}  "
              f"Sharpe={r['sharpe']:.3f}  trades={r['closed_trades']}  "
              f"inCash={r['time_in_cash']:.0%}  corrSkips={r['corr_cap_skips']}")

        # SPY-only Moe
        rs = _run_spy_qqq_portfolio(
            closes_map, highs_map, lows_map, window_master,
            spy_date_idx, wstart, wend
        )
        spyqqq_results[label] = rs
        print(f"  SPY-ONLY: ret={rs['total_return']:+.1%}  maxDD={rs['max_dd']:.1%}  "
              f"Sharpe={rs['sharpe']:.3f}  trades={rs['closed_trades']}  "
              f"inCash={rs['time_in_cash']:.0%}")

        # Buy-and-hold EEM
        eem_c = closes_map.get("EEM",[]); eem_d = master_dates
        re = _buy_and_hold(eem_c, eem_d, wstart, wend)
        bah_eem_results[label] = re

        # Buy-and-hold SPY
        rs2 = _buy_and_hold(spy_closes, master_dates, wstart, wend)
        bah_spy_results[label] = rs2

        print(f"  BaH-EEM:  ret={re['total_return']:+.1%}  maxDD={re['max_dd']:.1%}  Sharpe={re['sharpe']:.3f}")
        print(f"  BaH-SPY:  ret={rs2['total_return']:+.1%}  maxDD={rs2['max_dd']:.1%}  Sharpe={rs2['sharpe']:.3f}")

    # ── Part D: Benchmark Shootout ────────────────────────────────────────────
    print("\n"+"="*100)
    print("PART D — BENCHMARK SHOOTOUT")
    print("="*100)

    def _pooled_stats(res_dict):
        pooled=[]; rets_all=[]; dd_all=[]; ret_all=[]
        for r in res_dict.values():
            if not r: continue
            pooled.extend(r.get("daily_rets",[]))
            dd_all.append(r.get("max_dd",0))
            ret_all.append(r.get("total_return",0))
        mu=sum(pooled)/len(pooled) if pooled else 0
        var=sum((r-mu)**2 for r in pooled)/(len(pooled)-1) if len(pooled)>1 else 0
        ps = mu/(var**0.5)*252**0.5 if var>0 else 0
        avg_dd = sum(dd_all)/len(dd_all) if dd_all else 0
        worst_dd = max(dd_all) if dd_all else 0
        avg_ret = sum(ret_all)/len(ret_all) if ret_all else 0
        return ps, avg_dd, worst_dd, avg_ret

    def _em_bear_return(res_dict):
        rets=[res_dict[k]["total_return"] for k in EM_BEAR if k in res_dict and res_dict[k]]
        return sum(rets)/len(rets) if rets else float("nan")

    def _time_in_cash_avg(res_dict):
        vals=[res_dict[k]["time_in_cash"] for k in res_dict if res_dict[k] and "time_in_cash" in res_dict[k]]
        return sum(vals)/len(vals) if vals else float("nan")

    def _worst_window(res_dict):
        worst_label, worst_ret = "—", 0.0
        for k,r in res_dict.items():
            if r and r.get("total_return",0) < worst_ret:
                worst_ret = r["total_return"]; worst_label = k
        return worst_label, worst_ret

    strategies = [
        ("GLOBAL PORTFOLIO", port_results),
        ("SPY-ONLY (Moe)",   spyqqq_results),
        ("BaH EEM",          bah_eem_results),
        ("BaH SPY",          bah_spy_results),
    ]

    print(f"\n{'Strategy':<22}  {'PooledSharpe':>12}  {'PooledMaxDD':>11}  {'AvgReturn':>10}  "
          f"{'WorstWindow':>20}  {'InCash':>7}  {'EMbearAvg':>10}")
    print("-"*100)

    shootout = {}
    for name, res in strategies:
        ps, avg_dd, worst_dd, avg_ret = _pooled_stats(res)
        em_avg = _em_bear_return(res)
        worst_lbl, worst_ret = _worst_window(res)
        ic_str = f"{_time_in_cash_avg(res):.0%}" if "time_in_cash" in list(res.values() or [{}])[0] else "N/A"
        em_str = f"{em_avg:+.1%}" if not math.isnan(em_avg) else "N/A"
        worst_str = f"{worst_lbl}({worst_ret:+.1%})"
        print(f"{name:<22}  {ps:>12.3f}  {worst_dd:>11.1%}  {avg_ret:>+10.1%}  "
              f"{worst_str:>20}  {ic_str:>7}  {em_str:>10}")
        shootout[name] = {"pooled_sharpe":ps,"worst_dd":worst_dd,"avg_ret":avg_ret,
                          "em_avg":em_avg,"time_in_cash":_time_in_cash_avg(res)}

    # Per-window detail
    print(f"\n{'Window':<12}  {'Global':>8}  {'SPY-Moe':>8}  {'BaH-EEM':>8}  {'BaH-SPY':>8}")
    print("-"*55)
    for label,wstart,wend,_ in WINDOWS:
        def _s(r,k="total_return"):
            v=r.get(label,{})
            if not v: return "  SKIP"
            return f"{v.get(k,0):+.1%}"
        print(f"{label:<12}  {_s(port_results):>8}  {_s(spyqqq_results):>8}  "
              f"{_s(bah_eem_results):>8}  {_s(bah_spy_results):>8}")

    print(f"\nSharpe detail per window:")
    print(f"{'Window':<12}  {'Global':>8}  {'SPY-Moe':>8}  {'BaH-EEM':>8}  {'BaH-SPY':>8}")
    print("-"*55)
    for label,wstart,wend,_ in WINDOWS:
        def _sh(r):
            v=r.get(label,{})
            if not v: return "  SKIP"
            return f"{v.get('sharpe',0):>+.3f}"
        print(f"{label:<12}  {_sh(port_results):>8}  {_sh(spyqqq_results):>8}  "
              f"{_sh(bah_eem_results):>8}  {_sh(bah_spy_results):>8}")

    # ── Corr-cap report ────────────────────────────────────────────────────────
    print("\n"+"="*100)
    print("CORRELATION CAP REPORT — how often did redundant signals fire?")
    print("="*100)
    total_skips = 0
    skip_by_ticker: dict[str,int] = defaultdict(int)
    for label, r in port_results.items():
        n = r.get("corr_cap_skips",0)
        total_skips += n
        for ev in r.get("corr_cap_log",[]):
            skip_by_ticker[ev["ticker"]] += 1
        print(f"  {label:<12}: {n} corr-cap skips")
    print(f"  Total skips: {total_skips}")
    if skip_by_ticker:
        print(f"  By ticker: " + "  ".join(f"{t}:{n}" for t,n in sorted(skip_by_ticker.items(), key=lambda x:-x[1])[:10]))

    # ── Part E: 2022 Currency Stress Test ─────────────────────────────────────
    print("\n"+"="*100)
    print("PART E — 2022 CURRENCY STRESS TEST (DXY spike / strong-dollar year)")
    print("="*100)
    r22 = port_results.get("2022_rates")
    if r22:
        reg_dd: dict[str,float] = {}
        reg_ret: dict[str,float]= {}
        # Per-region P&L from trade log
        for reg in ["US_CORE","ASIA_PACIFIC","LATIN_AMERICA","FRONTIER_EM"]:
            reg_trades = [t for t in r22.get("trade_log",[]) if t.get("region")==reg]
            if reg_trades:
                reg_pnl = sum(t["pnl_usd"] for t in reg_trades)
                reg_ret[reg] = reg_pnl/STARTING_EQUITY
            else:
                reg_ret[reg] = 0.0

        print(f"\n  Overall portfolio 2022: ret={r22['total_return']:+.1%}  "
              f"maxDD={r22['max_dd']:.1%}  inCash={r22['time_in_cash']:.0%}")
        print(f"  vs SPY-only 2022:       ret={spyqqq_results.get('2022_rates',{}).get('total_return',0):+.1%}  "
              f"maxDD={spyqqq_results.get('2022_rates',{}).get('max_dd',0):.1%}")
        print(f"  vs BaH-EEM 2022:        ret={bah_eem_results.get('2022_rates',{}).get('total_return',0):+.1%}  "
              f"maxDD={bah_eem_results.get('2022_rates',{}).get('max_dd',0):.1%}")
        print(f"  vs BaH-SPY 2022:        ret={bah_spy_results.get('2022_rates',{}).get('total_return',0):+.1%}  "
              f"maxDD={bah_spy_results.get('2022_rates',{}).get('max_dd',0):.1%}")

        print(f"\n  Per-region P&L attribution (2022):")
        for reg,ret in reg_ret.items():
            t_count=len([t for t in r22.get("trade_log",[]) if t.get("region")==reg])
            print(f"    {reg:<16}: {ret:+.2%} of starting equity  ({t_count} closed trades)")

        # Pairwise correlation of regional allocations in 2022
        reg_daily = r22.get("region_daily",{})
        regs = [r for r in reg_daily if len(reg_daily[r])>20]
        if len(regs)>=2:
            print(f"\n  Pairwise regional allocation correlations (2022):")
            print(f"  (measures whether diversification vanished when dollar ripped)")
            for i,ra in enumerate(regs):
                for rb in regs[i+1:]:
                    da,db = reg_daily[ra], reg_daily[rb]
                    n=min(len(da),len(db))
                    if n<10: continue
                    mu_a=sum(da[:n])/n; mu_b=sum(db[:n])/n
                    cov=sum((a-mu_a)*(b-mu_b) for a,b in zip(da[:n],db[:n]))/(n-1)
                    va=sum((a-mu_a)**2 for a in da[:n])/(n-1)
                    vb=sum((b-mu_b)**2 for b in db[:n])/(n-1)
                    rho=cov/((va*vb)**0.5) if va>0 and vb>0 else 0
                    print(f"    {ra:<16} vs {rb:<16}: ρ={rho:+.3f}")

    # ── Verdict ────────────────────────────────────────────────────────────────
    print("\n"+"="*100)
    print("VERDICT")
    print("="*100)

    gps  = shootout.get("GLOBAL PORTFOLIO",{}).get("pooled_sharpe",0)
    sps  = shootout.get("SPY-ONLY (Moe)",{}).get("pooled_sharpe",0)
    gdd  = shootout.get("GLOBAL PORTFOLIO",{}).get("worst_dd",1)
    sdd  = shootout.get("SPY-ONLY (Moe)",{}).get("worst_dd",1)
    delta_sharpe = gps - sps
    dd_reduction = (sdd - gdd) / sdd if sdd > 0 else 0

    sharpe_pass  = delta_sharpe >= 0.15
    dd_pass      = dd_reduction >= 0.20 and delta_sharpe >= -0.05
    partial_pass = delta_sharpe >= 0 or dd_reduction >= 0.10

    print(f"\n  Global Portfolio pooled Sharpe:  {gps:.3f}")
    print(f"  SPY-only   pooled Sharpe:        {sps:.3f}")
    print(f"  Sharpe delta (Global − SPY):     {delta_sharpe:+.3f}")
    print(f"  Worst maxDD (Global):            {gdd:.1%}")
    print(f"  Worst maxDD (SPY-only):          {sdd:.1%}")
    print(f"  MaxDD reduction:                 {dd_reduction:+.1%}")
    print()

    if sharpe_pass:
        print("✅ PASS — Global portfolio beats SPY-only by ≥0.15 Sharpe.")
        print("   Diversification is real. Proceed to build.")
    elif dd_pass:
        print("✅ PASS — Global portfolio reduces maxDD by ≥20% without giving back Sharpe.")
        print("   Risk-adjusted case is sound. Proceed to build.")
    elif partial_pass:
        print("⚠️  PARTIAL — Some improvement but below pass threshold.")
        # Identify which regions helped
        region_sharpe = {}
        for reg in ["US_CORE","ASIA_PACIFIC","LATIN_AMERICA","FRONTIER_EM"]:
            reg_tickers = [t for t in UNIVERSE if TICKER_REGION.get(t)==reg]
            # Compare region trade P&L across all windows
            total_pnl = 0
            for r in port_results.values():
                for t in r.get("trade_log",[]):
                    if t.get("region")==reg: total_pnl+=t.get("pnl_usd",0)
            region_sharpe[reg] = total_pnl
        positive_regs = [r for r,p in region_sharpe.items() if p>0]
        print(f"   Regions with positive P&L contribution: {positive_regs}")
        print(f"   Trimmed portfolio (US_CORE + {positive_regs}) likely beats SPY-only.")
        print(f"   Run Phase 3 with trimmed universe, not full 16-ticker set.")
    else:
        print("❌ FAIL — Global portfolio does not beat SPY-only risk-adjusted.")
        print("   Verdict: run Moe strategy on SPY/QQQ only. No build needed.")
        print("   The diversification is more correlation than alpha in stressed windows.")

    print("\n  Sanity gates: ", end="")
    max_swing_all = max((r.get("max_single_swing",0) for r in port_results.values() if r), default=0)
    if max_swing_all > 0.50:
        print(f"⚠️  single-day swing {max_swing_all:.0%} — INSPECT")
    else:
        print(f"OK (max single-day swing: {max_swing_all:.1%})")
    print()


if __name__ == "__main__":
    main()
