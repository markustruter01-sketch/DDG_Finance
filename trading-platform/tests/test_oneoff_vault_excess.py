import importlib.util
import pathlib

import pytest

_p = pathlib.Path(__file__).parents[1] / "scripts" / "oneoff_oracle_vault_excess.py"
_spec = importlib.util.spec_from_file_location("oneoff", _p)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

LEDGER = {"BIL": 25.250485556, "VOO": 3.28414826}
PRICE = {"BIL": 91.598, "VOO": 710.584}


def test_sells_only_the_excess_rounded_down():
    sells = m.plan_sells({"BIL": 31.907226319, "VOO": 4.144558243}, LEDGER, PRICE)
    by = {s["symbol"]: s for s in sells}
    assert by["BIL"]["qty"] == 6.65674 and by["VOO"]["qty"] == 0.860409
    for s in sells:                                   # never dips into vault shares
        assert s["qty"] <= {"BIL": 31.907226319, "VOO": 4.144558243}[s["symbol"]] - LEDGER[s["symbol"]]


def test_refuses_when_broker_is_below_ledger_or_excess_too_big():
    with pytest.raises(ValueError, match="below the vault ledger"):
        m.plan_sells({"BIL": 20.0, "VOO": 4.0}, LEDGER, PRICE)
    with pytest.raises(ValueError, match="above"):
        m.plan_sells({"BIL": 60.0, "VOO": 4.0}, LEDGER, PRICE)


def test_nothing_to_sell_when_equal():
    assert m.plan_sells(dict(LEDGER), LEDGER, PRICE) == []
