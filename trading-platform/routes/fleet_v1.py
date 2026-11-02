"""FLEET-V1 dashboard API (sleeve_runtime/FLEET-V1-LIVE-SPEC.md section 7).

Every number here is read, not computed: the runtime's own state
(bots_state.metadata, written by sleeve_runtime/fleet_live.py), the risk
limits, the kill switch, and the research record (research_harness's
exploration_log.jsonl and ledger.jsonl). The browser only formats them.

- GET  /fleet-v1/state                    per-account signal, targets, drawdown mode
- GET  /fleet-v1/record                   the FLEET-V1 exploration and held-out record
- POST /fleet-v1/{bot_id}/clear-halt      owner action: leave a hard drawdown halt
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

import routes._deps  # noqa: F401  (puts the repo root on sys.path for sleeve_runtime)

fleet_v1_router = APIRouter()

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPLORATION_LOG = REPO_ROOT / "research_harness" / "exploration_log.jsonl"
LEDGER = REPO_ROOT / "research_harness" / "ledger.jsonl"
ACCOUNTS = {"oracle": "FLEET-V1-F1"}          # Momentum's account runs MOMO-V2 since 2 Nov (routes/momo_v2.py)
ROLE = {"oracle": "The fleet (65% equity core + 35% cross-asset)"}
CLEAR_CONFIRMATION_ENV_VAR = "KILL_SWITCH_RESET_CONFIRMATION"    # same owner token as a kill-switch reset
PLAN_ID = "FLEET-V1"
REGISTRATION = "FLEET-V1-F1"


def _variant(bot_id: str):
    from sleeve_runtime.fleet_live import VARIANTS
    reg = ACCOUNTS.get(bot_id)
    if reg is None:
        raise HTTPException(status_code=404, detail=f"{bot_id} does not run FLEET-V1")
    return VARIANTS[reg]


def _read_state(bot_id: str) -> dict[str, Any]:
    from core.bot_state import read_metadata
    return (read_metadata(bot_id) or {}).get(_variant(bot_id).state_key, {}) or {}


def since_cutover(st: dict[str, Any]) -> dict[str, Any] | None:
    """Pure: the account's sleeve-equity return and SPY's price return since cutover."""
    first, last = st.get("cutover") or {}, st.get("mark") or {}
    try:
        return {"from": first["day"], "to": last["day"],
                "account_return": last["equity"] / first["equity"] - 1,
                "spy_price_return": last["spy"] / first["spy"] - 1,
                "note": "SPY is price return (adjusted closes; dividends after cutover are not in it)"}
    except (KeyError, TypeError, ZeroDivisionError):
        return None


def _account_view(bot_id: str) -> dict[str, Any]:
    v = _variant(bot_id)
    st = _read_state(bot_id)
    dd = st.get("drawdown") or {}
    return {
        "bot_id": bot_id,
        "registration": v.registration,
        "role": ROLE[bot_id],
        "core_weight": v.core_weight,
        "xasset_weight": v.xasset_weight,
        "signal_day": st.get("signal_day"),
        "votes": st.get("votes"),
        "vol20": st.get("vol20"),
        "exposure": st.get("exposure"),
        "targets": st.get("targets") or {},
        "last_rebalance_key": st.get("key"),
        "last_rebalance_at": st.get("at"),
        "last_rebalance_done": st.get("done"),
        "attempts": st.get("attempts"),
        "errors": st.get("errors") or [],
        "since_cutover": since_cutover(st),
        "drawdown": {
            "mode": dd.get("mode", "normal"),
            "halted": bool(dd.get("halted")),
            "drawdown": dd.get("drawdown"),
            "high_water_mark": dd.get("hwm"),
            "closing_equity": dd.get("equity"),
            "as_of": dd.get("as_of"),
            "error": dd.get("error"),
            "cleared_by": dd.get("cleared_by"),
            "cleared_at": dd.get("cleared_at"),
        },
    }


@fleet_v1_router.get("/fleet-v1/state", tags=["FLEET-V1"])
async def fleet_v1_state() -> dict[str, Any]:
    from config.settings import settings
    from core.kill_switch import latch_tripped
    from core.risk_limits import ENFORCE_DRAWDOWN_LIMITS, HARD_DRAWDOWN, SOFT_DRAWDOWN
    from core.stop_policy import STOP_EXEMPT

    def read() -> dict[str, Any]:
        return {
            "accounts": [_account_view(b) for b in ACCOUNTS],
            "limits": {"soft": SOFT_DRAWDOWN, "hard": HARD_DRAWDOWN, "enforced": ENFORCE_DRAWDOWN_LIMITS,
                       "soft_action": "every target halved until equity is back to 95% of the high-water mark",
                       "hard_action": "sold to cash; trading halts until the owner clears it"},
            "kill_switch": {"armed": bool(settings.kill_switch_armed), "tripped": bool(latch_tripped())},
            "stop_free": {b: sorted(s) for b, s in STOP_EXEMPT.items()},
        }

    try:
        return await asyncio.to_thread(read)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"FLEET-V1 | state read failed: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=503, detail=f"FLEET-V1 state unreadable: {type(exc).__name__}")


def _last_jsonl(path: Path, match) -> dict[str, Any] | None:
    if not path.exists():
        return None
    found = None
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if match(row):
                found = row
    return found


def _figures(s: dict[str, Any] | None) -> dict[str, Any] | None:
    """The comparable figures of one series, as the research run recorded them."""
    if not s:
        return None
    exact = s.get("exact") or {}
    return {
        "cagr": exact.get("cagr"),
        "sharpe": exact.get("sharpe"),
        "max_drawdown": exact.get("max_dd"),
        "max_drawdown_after_haircut": s.get("max_dd_after_haircut"),
        "vol_pct": s.get("vol_pct"),
        "correlation_to_B": s.get("correlation_to_B"),
    }


def record_view(exploration: dict[str, Any] | None, heldout: dict[str, Any] | None) -> dict[str, Any]:
    """Pure: pick the dashboard's fields out of the two research records."""
    out: dict[str, Any] = {"plan": "research_harness/explore/FLEET-V1-PLAN.md",
                           "exploration": None, "heldout": None}
    if exploration:
        rows = {**(exploration.get("candidates") or {}), **(exploration.get("controls") or {})}
        n2 = (exploration.get("controls") or {}).get("N2") or {}
        out["exploration"] = {
            "window": exploration.get("window"),
            "ran_at": exploration.get("ran_at"),
            "code_commit": exploration.get("code_commit"),
            "series": {k: _figures(rows.get(k)) for k in ("B", "C1", "C2", "F1", "F2", "A0", "N1", "S2")
                       if rows.get(k)},
            "n2_sharpe_p95": n2.get("sharpe_p95"),
            "selected": (exploration.get("selection") or {}).get("selected"),
            "selection_verdict": (exploration.get("selection") or {}).get("verdict"),
            "rolling_win_share": {k: v.get("win_share") for k, v in
                                  ((exploration.get("rolling") or {}).get("by_candidate") or {}).items()},
        }
    if heldout:
        res = heldout.get("result") or {}
        test = res.get("test") or {}
        spent = res.get("spent_information_only") or {}
        out["heldout"] = {
            "registration": heldout.get("registration_id"),
            "ran_at": heldout.get("ran_at"),
            "code_commit": heldout.get("code_commit"),
            "verdict": res.get("verdict"),
            "test": {"window": test.get("window"),
                     "series": {k: _figures(v) for k, v in (test.get("series") or {}).items()},
                     "pass_bar": (test.get("pass_bar") or {}).get("items"),
                     "deflated_sharpe": (test.get("deflated_sharpe_F1") or {}).get("dsr")},
            "spent": {"window": spent.get("window"), "label": spent.get("label"),
                      "series": {k: _figures(v) for k, v in (spent.get("series") or {}).items()}},
        }
    return out


@fleet_v1_router.get("/fleet-v1/record", tags=["FLEET-V1"])
async def fleet_v1_record() -> dict[str, Any]:
    def read() -> dict[str, Any]:
        exploration = _last_jsonl(EXPLORATION_LOG, lambda r: r.get("plan") == PLAN_ID)
        heldout = _last_jsonl(LEDGER, lambda r: r.get("registration_id") == REGISTRATION
                              and r.get("kind") == "holdout_test")
        return record_view(exploration, heldout)
    return await asyncio.to_thread(read)


# Every account whose runtime keeps a drawdown governor in bots_state.metadata.
HALT_STATE_KEYS = {"oracle": "fleet_v1_f1", "spy_qqq_trend": "momo_v2"}


class ClearHaltRequest(BaseModel):
    confirmation_token: str
    by: str = "owner"


@fleet_v1_router.post("/fleet-v1/{bot_id}/clear-halt", tags=["FLEET-V1"])
async def fleet_v1_clear_halt(bot_id: str, request: ClearHaltRequest) -> dict[str, Any]:
    """Owner action: leave a hard drawdown halt. The high-water mark restarts
    at the account's current equity. Needs the same confirmation token as a
    kill-switch reset."""
    expected = os.getenv(CLEAR_CONFIRMATION_ENV_VAR, "").strip()
    if not expected:
        raise HTTPException(status_code=403, detail="Halt-clear confirmation is not configured.")
    if not hmac.compare_digest(request.confirmation_token, expected):
        raise HTTPException(status_code=403, detail="Invalid confirmation.")
    state_key = HALT_STATE_KEYS.get(bot_id)
    if state_key is None:
        raise HTTPException(status_code=404, detail=f"{bot_id} has no drawdown governor")

    def clear() -> dict[str, Any]:
        from core.bot_state import merge_metadata, read_metadata
        from execution.reconciliation import _client_for
        from sleeve_runtime.fleet_live import clear_halt

        st = (read_metadata(bot_id) or {}).get(state_key, {}) or {}
        dd = st.get("drawdown") or {}
        if not dd.get("halted"):
            raise HTTPException(status_code=409, detail=f"{bot_id} is not halted.")
        equity = float(_client_for(bot_id).get_account().equity)
        st = {**st, "drawdown": clear_halt(dd, equity, by=request.by[:60])}
        merge_metadata(bot_id, {state_key: st})
        logger.warning(f"Drawdown governor | {bot_id} hard halt cleared by {request.by!r}; "
                       f"new high-water mark {equity:,.2f}")
        return {"bot_id": bot_id, "drawdown": st["drawdown"]}

    return await asyncio.to_thread(clear)
