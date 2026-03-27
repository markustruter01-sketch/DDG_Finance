"""
On-Chain Bitcoin Intelligence
-------------------------------
Fetches Bitcoin on-chain signals from free public APIs:
  1. Blockchain.com — hash rate, difficulty
  2. Mempool.space — fee estimates, mempool depth
  3. alternative.me — Fear & Greed (shared with sentiment.py)

These signals augment the crypto-only system prompt with data the
LLM cannot infer from price action alone.

All calls are cached for 1 hour.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from loguru import logger

_cache: dict[str, Any] = {"data": None, "ts": 0}
_CACHE_TTL = 3600


def _fetch_hashrate() -> dict | None:
    try:
        r = httpx.get(
            "https://blockchain.info/q/hashrate",
            timeout=10,
            follow_redirects=True,
        )
        r.raise_for_status()
        hashrate_gh = float(r.text.strip())
        return {"hashrate_gh_s": hashrate_gh}
    except Exception as exc:
        logger.warning(f"OnChain | Hashrate fetch failed: {exc}")
        return None


def _fetch_mempool() -> dict | None:
    try:
        r = httpx.get("https://mempool.space/api/mempool", timeout=10)
        r.raise_for_status()
        data = r.json()
        return {
            "mempool_tx_count": data.get("count", 0),
            "mempool_vsize_bytes": data.get("vsize", 0),
        }
    except Exception as exc:
        logger.warning(f"OnChain | Mempool fetch failed: {exc}")
        return None


def _fetch_fee_estimates() -> dict | None:
    try:
        r = httpx.get("https://mempool.space/api/v1/fees/recommended", timeout=10)
        r.raise_for_status()
        data = r.json()
        return {
            "fastest_fee_sat_vb": data.get("fastestFee"),
            "half_hour_fee_sat_vb": data.get("halfHourFee"),
            "hour_fee_sat_vb": data.get("hourFee"),
            "economy_fee_sat_vb": data.get("economyFee"),
        }
    except Exception as exc:
        logger.warning(f"OnChain | Fee estimates fetch failed: {exc}")
        return None


def _fetch_btc_supply() -> dict | None:
    try:
        r = httpx.get(
            "https://blockchain.info/q/totalbc",
            timeout=10,
            follow_redirects=True,
        )
        r.raise_for_status()
        total_sats = float(r.text.strip())
        total_btc = total_sats / 1e8
        supply_pct = (total_btc / 21_000_000) * 100
        return {
            "total_btc_mined": round(total_btc, 2),
            "supply_mined_pct": round(supply_pct, 2),
            "remaining_btc": round(21_000_000 - total_btc, 2),
        }
    except Exception as exc:
        logger.warning(f"OnChain | BTC supply fetch failed: {exc}")
        return None


def get_onchain_data(force: bool = False) -> dict:
    now = time.time()
    if not force and _cache["data"] and (now - _cache["ts"]) < _CACHE_TTL:
        return {**_cache["data"], "cached": True, "cache_age_seconds": int(now - _cache["ts"])}

    hashrate = _fetch_hashrate()
    mempool = _fetch_mempool()
    fees = _fetch_fee_estimates()
    supply = _fetch_btc_supply()

    data: dict[str, Any] = {
        "hashrate": hashrate,
        "mempool": mempool,
        "fee_estimates": fees,
        "supply": supply,
        "cached": False,
        "cache_age_seconds": 0,
    }

    _cache["data"] = data
    _cache["ts"] = now

    logger.info(
        f"OnChain | Hashrate={hashrate}, "
        f"Mempool={mempool.get('mempool_tx_count') if mempool else 'N/A'} txs, "
        f"FastFee={fees.get('fastest_fee_sat_vb') if fees else 'N/A'} sat/vB"
    )
    return data


def get_onchain_prompt_block() -> str:
    data = get_onchain_data()
    lines = ["\n=== BITCOIN ON-CHAIN INTELLIGENCE ==="]

    if data.get("hashrate"):
        hr = data["hashrate"]["hashrate_gh_s"]
        lines.append(f"Network Hash Rate: {hr:,.0f} GH/s")
        if hr > 0:
            lines.append("  -> Hash rate healthy: miners are profitable, network secure")

    if data.get("supply"):
        s = data["supply"]
        lines.append(
            f"BTC Supply: {s['total_btc_mined']:,.0f} / 21,000,000 mined "
            f"({s['supply_mined_pct']:.1f}%)"
        )

    if data.get("mempool"):
        mp = data["mempool"]
        lines.append(f"Mempool: {mp['mempool_tx_count']:,} pending transactions")
        if mp["mempool_tx_count"] > 100_000:
            lines.append("  -> HIGH mempool congestion: network demand is elevated")
        elif mp["mempool_tx_count"] < 10_000:
            lines.append("  -> LOW mempool activity: on-chain demand is subdued")

    if data.get("fee_estimates"):
        f = data["fee_estimates"]
        lines.append(
            f"Fees: fast={f['fastest_fee_sat_vb']} | "
            f"30min={f['half_hour_fee_sat_vb']} | "
            f"economy={f['economy_fee_sat_vb']} sat/vB"
        )
        if f["fastest_fee_sat_vb"] and f["fastest_fee_sat_vb"] > 50:
            lines.append("  -> HIGH fees: strong on-chain demand (bullish signal)")
        elif f["fastest_fee_sat_vb"] and f["fastest_fee_sat_vb"] < 5:
            lines.append("  -> LOW fees: weak on-chain demand (bearish signal)")

    lines.append("")
    return "\n".join(lines)
