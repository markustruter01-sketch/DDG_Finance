"""2027 predictions: checked, append-only, newest-before-lock counts, council replies filed."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

import twins  # noqa: F401
from twins import predictions as P
from twins.engine import NEW_YORK
from twins_pg import make_get_conn, needs_pg

THESIS = "Growth slows, the Fed cuts twice, the dollar eases and gold keeps rising as real rates fall."


def forecast(**over):
    m = {k: {"direction": "up", "change_pct": 5.0} for k in P.MARKETS}
    m.update(over)
    return {"markets": m, "macro": {k: 3.0 for k in P.MACRO}}


def test_check_rejects_gaps_and_contradictions():
    assert P.check(THESIS, forecast())["markets"]["SPY"] == {"direction": "up", "change_pct": 5.0}
    for bad, msg in ((forecast(SPY={"direction": "down", "change_pct": 4}), "does not match"),
                     (forecast(GLD={"direction": "flat", "change_pct": 6}), "does not match"),
                     ({"markets": {}, "macro": {}}, "direction"),
                     (dict(forecast(), macro={}), "number between")):
        with pytest.raises(ValueError, match=msg):
            P.check(THESIS, bad)
    with pytest.raises(ValueError, match="50"):
        P.check("too short", forecast())


@needs_pg
def test_file_keep_every_version_score_the_newest_and_lock():
    get_conn = make_get_conn()
    early, later = datetime(2026, 11, 21, 9, tzinfo=NEW_YORK), datetime(2026, 12, 20, 9, tzinfo=NEW_YORK)
    P.file(get_conn, early, author="Markus", thesis=THESIS, forecasts=forecast())
    P.file(get_conn, later, author="Markus", thesis=THESIS + " Revised.", forecasts=forecast(SPY={"direction": "down", "change_pct": -8}))
    with pytest.raises(ValueError, match="locked"):
        P.file(get_conn, datetime(2027, 1, 1, 0, 1, tzinfo=NEW_YORK), author="Markus", thesis=THESIS, forecasts=forecast())
    view = P.read(get_conn)
    mine = next(e for e in view["entries"] if e["author"] == "Markus")
    assert mine["versions"] == 2 and mine["forecasts"]["markets"]["SPY"]["change_pct"] == -8.0
    with get_conn() as conn, conn.cursor() as cur, pytest.raises(Exception, match="append-only"):
        cur.execute("DELETE FROM year_predictions")

    def fake(role, system, user):
        if role == "member_2":
            return {"model": "m2", "raw": "I think shares go up."}
        return {"model": f"model-{role}", "raw": json.dumps({"thesis": THESIS, "forecasts": forecast()})}
    out = P.ask_council(get_conn, later, {"SPY": {"close": 600}}, {}, call=fake, roles=("member_1", "member_2", "member_3"))
    assert "filed" in out["member_1"] and "error" in out["member_2"] and "filed" in out["member_3"]
    assert {e["author"] for e in P.read(get_conn)["entries"]} == {"Markus", "member_1", "member_3"}
