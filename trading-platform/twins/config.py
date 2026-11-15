"""Every twin's definition, in one place.

Phase A twins (spec, "Build phases"):
- mirror: the bot's own real holdings, fed through the engine. Its balance
  must track the real account; that is the proof the engine is right.
- baseline_full: the bot's own asset list, always fully invested at its limit.
- baseline_spy: S&P 500 buy and hold.
Phase B adds "ai" (Bots 1-3) and "rules" (Forex).

Every twin of a bot starts on the same step with the same balance: the real
account's equity then, without the owner-kept lines (core.bot_registry
.OWNER_KEPT). A changed definition is a new VERSION with its own start.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from research_harness.explore.gear_v1 import COSTS as SHARE_COSTS  # noqa: F401  (one cost source)
from research_harness.sleeves import core_v1, xasset_v1

_KRAKEN_BOT = str(Path(__file__).resolve().parents[2] / "kraken-bot")
if _KRAKEN_BOT not in sys.path:
    sys.path.append(_KRAKEN_BOT)  # appended: trading-platform's own packages still win
from forex_quant_desk import FOREX_PAIRS  # noqa: E402  (read-only; the registered pairs)

REGISTRATION = "TWINS-V1"
VERSION = 1   # Phase A proving period. The strategy lock (21-22 Nov) starts version 2.

KINDS = ("mirror", "ai", "rules", "baseline_full", "baseline_spy")
DAILY = "alpaca_daily"    # US sessions: a decision after a close fills at the next session's open
HOURLY = "oanda_h1"       # forex hours: a decision fills at the next hourly bar's open

SHARE_BOTS = ("oracle", "jerome_macro", "spy_qqq_trend")
FOREX_BOT = "forex_ai"

# The mirror copies reality, so it gets room for whatever the bot really holds;
# limits are the bot's business. Baselines are held to the bots' no-borrowing rule.
MIRROR_MAX_GROSS = 10.0

# Mirror tolerance: Fable sets it after one week of mirror data (spec, "Open").
# Until then this provisional guard catches a gross engine error: an alarm when
# the mirror's return since its first full day is more than this many
# percentage points away from the real account's.
MIRROR_GUARD_PP = 1.0

# Copied from the live code, which the twins may not import (it carries the
# order path). tests/test_twins_config.py checks both still match.
FLEET_F1_SPLIT = (0.65, 0.35)          # sleeve_runtime.fleet_live.F1: core, cross-asset
MOMO_STATE_KEY = "momo_v2"             # sleeve_runtime.momo_live.STATE_KEY


@dataclass(frozen=True)
class TwinSpec:
    bot_id: str
    kind: str
    bars: str
    max_gross: float
    allow_short: bool = False
    stop_pct: float | None = None

    @property
    def twin_id(self) -> str:
        return f"{self.bot_id}:{self.kind}:v{VERSION}"


def phase_a_twins() -> list[TwinSpec]:
    out: list[TwinSpec] = []
    for bot in SHARE_BOTS:
        out += [TwinSpec(bot, "mirror", DAILY, MIRROR_MAX_GROSS, allow_short=True),
                TwinSpec(bot, "baseline_full", DAILY, 1.0),
                TwinSpec(bot, "baseline_spy", DAILY, 1.0)]
    # Forex has no "full at the limit" (a currency book has no direction to be
    # fully in); its rules twin (Phase B) is the yardstick beside the S&P.
    out += [TwinSpec(FOREX_BOT, "mirror", HOURLY, MIRROR_MAX_GROSS, allow_short=True),
            TwinSpec(FOREX_BOT, "baseline_spy", DAILY, 1.0)]
    return out


def baseline_weights(bot_id: str, kind: str, momo_names: list[str] | None = None) -> dict[str, float] | None:
    """Target weights for a baseline twin, or None when it has nothing to hold yet."""
    if kind == "baseline_spy":
        return {"SPY": 1.0}
    if kind != "baseline_full":
        raise ValueError(f"{kind} is not a baseline")
    core = core_v1.weights_for(core_v1.MAX_EXPOSURE, core_v1.MIXES["C1"])   # the 1.5x core
    if bot_id == "jerome_macro":          # FLEET-V1-C1: the core at its 1.5x limit, never in cash
        return core
    if bot_id == "oracle":                # FLEET-V1-F1: core at 1.5x + all four cross-asset lines
        core_w, xasset_w = FLEET_F1_SPLIT
        out = {s: core_w * w for s, w in core.items()}
        for line in xasset_v1.LINES:
            out[line] = out.get(line, 0.0) + xasset_w / len(xasset_v1.LINES)
        return out
    if bot_id == "spy_qqq_trend":         # MOMO-V2: this month's names, equal weight, no brakes
        names = sorted(set(momo_names or []))
        return {n: 1.0 / len(names) for n in names} if names else None
    raise ValueError(f"no baseline_full for {bot_id}")
