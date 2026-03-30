"""
Signal Guard — Pre-LLM News & Sentiment Guardrails
-----------------------------------------------------
Three independent, composable guards that run BEFORE the LLM is called.
Bad signals are killed without costing a single Groq token.

Guards:
  1. MultiSourceConsensusGuard  — removes single-source headlines           (SOFT)
  2. TemporalQuarantineGuard    — blocks analysis on Fri 14:00 → Mon 09:30 ET
                                   and ±30 min around economic blackout events (HARD)
  3. PriceToSentimentDivergence — downgrades sentiment band one step when
                                   SPY 5-day avg volume < SPY 20-day avg volume
                                   and the current band is Greed/Extreme Greed   (SOFT)

All guards log at DEBUG level on normal (passing) runs and at INFO/WARNING on
any intervention so operational behaviour is always auditable.

Usage:
    from analysis.signal_guard import run_all_guards, get_last_guard_result

    context = {
        "news_data":      news_data,       # dict from news_client.fetch_news()
        "market_data":    market_data,     # dict from yfinance_client.fetch_market_data()
        "sentiment_band": "Greed",         # label from data.sentiment.get_sentiment()
    }
    result = run_all_guards(context)

    if result.hard_block:
        # Temporal quarantine — skip LLM, return cached regime
        return

    # Use result.filtered_headlines instead of news_data["all_headlines"]
    # Use result.adjusted_sentiment if not None instead of the original sentiment_band
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time as _time_t
from typing import Any

from loguru import logger

try:
    import pytz
    _ET = pytz.timezone("America/New_York")
except ImportError:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")


# ── Sentinel for module-level last-result (populated by run_all_guards) ────────
_last_guard_result: dict[str, Any] | None = None


# ══════════════════════════════════════════════════════════════════════════════
# Result types
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class GuardResult:
    """Outcome from a single guard check."""
    name: str
    passed: bool
    reason: str
    severity: str     # "hard" | "soft"
    meta: dict = field(default_factory=dict)


@dataclass
class GuardRunResult:
    """Aggregated outcome from run_all_guards()."""
    results: list[GuardResult]
    hard_block: bool
    filtered_headlines: list[str]    # consensus-filtered subset of all_headlines
    adjusted_sentiment: str | None   # downgraded band (None = no change)
    run_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "hard_block": self.hard_block,
            "run_at": self.run_at,
            "adjusted_sentiment": self.adjusted_sentiment,
            "filtered_headline_count": len(self.filtered_headlines),
            "guards": [
                {
                    "name":     r.name,
                    "passed":   r.passed,
                    "severity": r.severity,
                    "reason":   r.reason,
                    **r.meta,
                }
                for r in self.results
            ],
        }


# ══════════════════════════════════════════════════════════════════════════════
# Guard 1 — Multi-Source Consensus (SOFT)
# ══════════════════════════════════════════════════════════════════════════════

_STOP_WORDS = frozenset({
    "a", "an", "the", "of", "in", "on", "at", "for", "to", "by",
    "is", "are", "was", "were", "be", "been", "being", "has", "have",
    "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "and", "or", "but", "as", "with", "from", "that",
    "this", "it", "its", "their", "after", "before", "says", "amid",
})


def _topic_words(text: str) -> frozenset[str]:
    """Return a frozenset of significant lowercase words from a headline."""
    tokens = re.findall(r"[a-z]{3,}", text.lower())
    return frozenset(t for t in tokens if t not in _STOP_WORDS)


def multi_source_consensus_guard(
    news_data: dict,
    min_sources: int = 2,
) -> tuple[GuardResult, list[str]]:
    """
    SOFT guard: filter headlines whose underlying article comes from a news source
    that has contributed only ONE article to the entire fetched batch. Single-source
    articles receive no independent corroboration and should not drive LLM decisions.

    Additionally, a headline is retained if at least one OTHER article in a different
    category has ≥3 significant title-word overlap with it (topic corroboration).

    Returns:
        GuardResult    — always passed=True (soft guard — never hard-blocks)
        filtered_list  — the consensus-filtered headline list
    """
    by_category: dict = news_data.get("by_category", {})
    all_headlines: list[str] = news_data.get("all_headlines", [])

    # Build a flat list of articles with (source, category, title, headline_str)
    articles_meta: list[dict] = []
    for cat, cat_data in by_category.items():
        for art in cat_data.get("articles", []):
            articles_meta.append({
                "source":   art.get("source", "Unknown"),
                "category": cat,
                "title":    art.get("title", ""),
            })

    if not articles_meta:
        logger.debug("SignalGuard | Consensus: no article metadata — skipping filter")
        return (
            GuardResult(
                name="multi_source_consensus",
                passed=True,
                reason="No article metadata available — filter skipped",
                severity="soft",
                meta={"original_count": len(all_headlines), "filtered_count": len(all_headlines)},
            ),
            all_headlines,
        )

    # Determine which articles are "corroborated":
    # An article passes if at least ONE OTHER article in the batch satisfies
    # EITHER condition (distinct source OR distinct category) AND shares
    # ≥3 significant title words with it.
    # This matches the spec: "ticker/topic passes if it appears in ≥2 distinct
    # articles (different sources or different category tags)".
    def _is_corroborated(art: dict) -> bool:
        src = art["source"]
        cat = art["category"]
        art_words = _topic_words(art["title"])
        if len(art_words) < 3:
            return True   # very short titles — keep by default (can't meaningfully score)
        for other in articles_meta:
            if other is art:
                continue
            # Must differ by source name OR by category tag (or both)
            if other["source"] == src and other["category"] == cat:
                continue   # same source AND same category → cannot corroborate
            other_words = _topic_words(other["title"])
            if len(art_words & other_words) >= 3:
                return True   # topic corroborated by a distinct-source/category article
        return False

    # Build the keep-set: category+first-8-words of title
    corroborated_titles: set[str] = set()
    dropped_sources: list[str] = []
    for art in articles_meta:
        title_key = " ".join(art["title"].lower().split()[:8])
        if _is_corroborated(art):
            corroborated_titles.add(title_key)
        else:
            dropped_sources.append(art["source"])
            logger.debug(
                f"SignalGuard | Consensus: dropping single-source article "
                f"source='{art['source']}' category='{art['category']}' "
                f"title='{art['title'][:60]}'"
            )

    # Filter all_headlines to only those whose title key is corroborated
    _CATEGORY_RE = re.compile(r"^\[[A-Z]+\]\s*")
    filtered: list[str] = []
    for hl in all_headlines:
        bare = _CATEGORY_RE.sub("", hl).split(" — ")[0].strip()
        hl_key = " ".join(bare.lower().split()[:8])
        if hl_key in corroborated_titles:
            filtered.append(hl)

    dropped_count = len(all_headlines) - len(filtered)
    if dropped_count:
        logger.info(
            f"SignalGuard | Consensus: dropped {dropped_count}/{len(all_headlines)} "
            f"single-source headlines (sources: {list(set(dropped_sources))})"
        )
    else:
        logger.debug(
            f"SignalGuard | Consensus: all {len(all_headlines)} headlines corroborated — none dropped"
        )

    unique_sources = len({a["source"] for a in articles_meta})
    return (
        GuardResult(
            name="multi_source_consensus",
            passed=True,
            reason=f"Filtered {dropped_count} single-source headline(s); {len(filtered)} remain",
            severity="soft",
            meta={
                "original_count": len(all_headlines),
                "filtered_count": len(filtered),
                "dropped_count":  dropped_count,
                "unique_sources": unique_sources,
            },
        ),
        filtered,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Guard 2 — Temporal Quarantine (HARD)
# ══════════════════════════════════════════════════════════════════════════════

_FRIDAY    = 4   # weekday index
_MONDAY    = 0
_SATURDAY  = 5
_SUNDAY    = 6

_FRI_CLOSE  = _time_t(14, 0)   # Friday 14:00 ET — start of weekend quarantine
_MON_OPEN   = _time_t(9, 30)   # Monday 09:30 ET — end of weekend quarantine


def temporal_quarantine_guard(
    calendar_check: bool = True,
    blackout_window_minutes: int = 30,
) -> GuardResult:
    """
    HARD guard: returns passed=False (hard block) when:
      (a) The current ET time is in the weekend news blackout window:
          Friday 14:00 ET through Monday 09:30 ET
      (b) The current ET time is within ±blackout_window_minutes of a known
          economic calendar release (FOMC, CPI, NFP, PCE, GDP, …)

    When passed=False the pipeline must NOT call the LLM — it should reuse
    the last cached regime instead.
    """
    now_et = datetime.now(_ET)
    wd = now_et.weekday()
    t  = now_et.time().replace(tzinfo=None)

    # (a) Weekend quarantine
    weekend_active = (
        (wd == _FRIDAY   and t >= _FRI_CLOSE) or
        wd == _SATURDAY  or
        wd == _SUNDAY    or
        (wd == _MONDAY   and t < _MON_OPEN)
    )
    if weekend_active:
        day_names = {0: "Monday", 4: "Friday", 5: "Saturday", 6: "Sunday"}
        day_label = day_names.get(wd, f"day-{wd}")
        reason = (
            f"Weekend quarantine active: {day_label} {t.strftime('%H:%M')} ET "
            f"(Fri 14:00 → Mon 09:30)"
        )
        logger.info(f"SignalGuard | Temporal: HARD BLOCK — {reason}")
        return GuardResult(
            name="temporal_quarantine",
            passed=False,
            reason=reason,
            severity="hard",
            meta={"trigger": "weekend", "day": day_label, "time_et": t.strftime("%H:%M")},
        )

    # (b) Economic calendar blackout
    if calendar_check:
        try:
            from data.economic_calendar import is_blackout_active
            blackout = is_blackout_active()
            if blackout.get("active"):
                reason = (
                    f"Economic blackout: {blackout.get('event', 'unknown')} at "
                    f"{blackout.get('event_time_et', '?')} ET "
                    f"(±{blackout_window_minutes}min window)"
                )
                logger.info(f"SignalGuard | Temporal: HARD BLOCK — {reason}")
                return GuardResult(
                    name="temporal_quarantine",
                    passed=False,
                    reason=reason,
                    severity="hard",
                    meta={
                        "trigger": "calendar_blackout",
                        "event":   blackout.get("event"),
                        "window_minutes": blackout_window_minutes,
                    },
                )
        except Exception as exc:
            logger.warning(
                f"SignalGuard | Temporal: calendar check failed (non-fatal): {exc}"
            )

    logger.debug(
        f"SignalGuard | Temporal: no quarantine — "
        f"{now_et.strftime('%A')} {t.strftime('%H:%M')} ET"
    )
    return GuardResult(
        name="temporal_quarantine",
        passed=True,
        reason=f"No quarantine — {now_et.strftime('%A')} {t.strftime('%H:%M')} ET",
        severity="hard",
        meta={"day_of_week": now_et.strftime("%A"), "time_et": t.strftime("%H:%M")},
    )


# ══════════════════════════════════════════════════════════════════════════════
# Guard 3 — Price-to-Sentiment Divergence (SOFT)
# ══════════════════════════════════════════════════════════════════════════════

_SENTIMENT_DOWNGRADE: dict[str, str] = {
    "Extreme Greed": "Greed",
    "Greed":         "Neutral",
}


def _compute_spy_volume_ratio(market_data: dict) -> float | None:
    """
    Compute SPY 5-day average volume / SPY 20-day average volume from bar data.
    Returns None if data is unavailable.
    """
    spy = market_data.get("by_ticker", {}).get("SPY", {})
    bars = spy.get("bars", [])
    if len(bars) < 20:
        return None
    volumes = [float(b.get("v", 0)) for b in bars if b.get("v") is not None]
    if len(volumes) < 20:
        return None
    avg_5d  = sum(volumes[-5:])  / 5
    avg_20d = sum(volumes[-20:]) / 20
    if avg_20d <= 0:
        return None
    return avg_5d / avg_20d


def sentiment_volume_divergence_guard(
    market_data: dict,
    sentiment_band: str,
) -> tuple[GuardResult, str | None]:
    """
    SOFT guard: if the market sentiment band is bullish (Greed or Extreme Greed)
    but SPY 5-day average volume is below its 20-day average (conviction absent),
    downgrade the sentiment band by one step.

    Returns:
        GuardResult    — always passed=True (soft guard — adjusts inputs, never blocks)
        adjusted_band  — the (possibly downgraded) sentiment band; None = no change
    """
    adjusted_band: str | None = None

    if sentiment_band not in _SENTIMENT_DOWNGRADE:
        logger.debug(
            f"SignalGuard | Divergence: sentiment='{sentiment_band}' — no downgrade needed"
        )
        return (
            GuardResult(
                name="sentiment_volume_divergence",
                passed=True,
                reason=f"Sentiment '{sentiment_band}' not in bullish range — no adjustment",
                severity="soft",
                meta={"sentiment_band": sentiment_band, "adjusted": False},
            ),
            None,
        )

    vol_ratio = _compute_spy_volume_ratio(market_data)
    if vol_ratio is None:
        logger.debug("SignalGuard | Divergence: SPY volume data unavailable — skipping")
        return (
            GuardResult(
                name="sentiment_volume_divergence",
                passed=True,
                reason="SPY volume data unavailable — sentiment unchanged",
                severity="soft",
                meta={"sentiment_band": sentiment_band, "vol_ratio": None, "adjusted": False},
            ),
            None,
        )

    if vol_ratio < 1.0:
        adjusted_band = _SENTIMENT_DOWNGRADE[sentiment_band]
        logger.info(
            f"SignalGuard | Divergence: bullish sentiment '{sentiment_band}' "
            f"but SPY vol ratio {vol_ratio:.2f} (5d/20d < 1.0) — "
            f"downgrading to '{adjusted_band}'"
        )
        return (
            GuardResult(
                name="sentiment_volume_divergence",
                passed=True,
                reason=(
                    f"Sentiment downgraded {sentiment_band} → {adjusted_band}: "
                    f"SPY 5d/20d volume ratio={vol_ratio:.2f} < 1.0 (low conviction)"
                ),
                severity="soft",
                meta={
                    "sentiment_band":  sentiment_band,
                    "adjusted_band":   adjusted_band,
                    "vol_ratio":       round(vol_ratio, 3),
                    "adjusted":        True,
                },
            ),
            adjusted_band,
        )

    logger.debug(
        f"SignalGuard | Divergence: bullish sentiment '{sentiment_band}' "
        f"confirmed by vol ratio {vol_ratio:.2f} (≥1.0) — no downgrade"
    )
    return (
        GuardResult(
            name="sentiment_volume_divergence",
            passed=True,
            reason=(
                f"Sentiment '{sentiment_band}' confirmed by volume: "
                f"SPY 5d/20d ratio={vol_ratio:.2f} ≥ 1.0"
            ),
            severity="soft",
            meta={
                "sentiment_band": sentiment_band,
                "vol_ratio":      round(vol_ratio, 3),
                "adjusted":       False,
            },
        ),
        None,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Orchestrator
# ══════════════════════════════════════════════════════════════════════════════

def run_all_guards(context: dict) -> GuardRunResult:
    """
    Run all three signal guards in order and return a consolidated result.

    Context dict keys:
        news_data      (dict)  — output of news_client.fetch_news()
        market_data    (dict)  — output of yfinance_client.fetch_market_data()
        sentiment_band (str)   — market fear/greed label e.g. "Greed", "Neutral"

    Returns GuardRunResult with:
        hard_block           — True if temporal quarantine fired (LLM should be skipped)
        filtered_headlines   — consensus-filtered list to use in place of all_headlines
        adjusted_sentiment   — downgraded sentiment band (None = unchanged)
        results              — individual GuardResult objects for auditing
    """
    global _last_guard_result

    news_data      = context.get("news_data", {})
    market_data    = context.get("market_data", {})
    sentiment_band = context.get("sentiment_band", "Neutral")

    results: list[GuardResult] = []

    # Guard 1 — Temporal (HARD, check first to bail early before expensive ops)
    temporal_result = temporal_quarantine_guard()
    results.append(temporal_result)

    if not temporal_result.passed:
        # Hard block — skip remaining guards (they are irrelevant now)
        run_result = GuardRunResult(
            results=results,
            hard_block=True,
            filtered_headlines=news_data.get("all_headlines", []),
            adjusted_sentiment=None,
        )
        _last_guard_result = run_result.to_dict()
        return run_result

    # Guard 2 — Multi-source consensus (SOFT)
    consensus_result, filtered_headlines = multi_source_consensus_guard(news_data)
    results.append(consensus_result)

    # Guard 3 — Volume divergence (SOFT)
    divergence_result, adjusted_sentiment = sentiment_volume_divergence_guard(
        market_data, sentiment_band
    )
    results.append(divergence_result)

    run_result = GuardRunResult(
        results=results,
        hard_block=False,
        filtered_headlines=filtered_headlines,
        adjusted_sentiment=adjusted_sentiment,
    )
    _last_guard_result = run_result.to_dict()
    logger.debug(
        f"SignalGuard | All guards passed — "
        f"headlines={len(filtered_headlines)} "
        f"sentiment={adjusted_sentiment or sentiment_band} "
        f"hard_block=False"
    )
    return run_result


def get_last_guard_result() -> dict | None:
    """Return the most recent guard run result for /status exposure."""
    return _last_guard_result
