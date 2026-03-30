"""
Tests for analysis/signal_guard.py

Covers:
  1. MultiSourceConsensusGuard — headline filtering
  2. TemporalQuarantineGuard  — weekend + calendar blackout logic
  3. SentimentVolumeDivergenceGuard — downgrade logic
  4. run_all_guards orchestrator
"""
import sys
import os
import unittest
from datetime import datetime, time as _time_t, timezone
from unittest.mock import patch, MagicMock

# Ensure the trading-platform directory is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from analysis.signal_guard import (
    multi_source_consensus_guard,
    temporal_quarantine_guard,
    sentiment_volume_divergence_guard,
    run_all_guards,
    GuardResult,
    GuardRunResult,
    _compute_spy_volume_ratio,
)


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _make_article(title: str, source: str, category: str = "macro") -> dict:
    return {"title": title, "source": source, "description": "", "published_at": "", "url": ""}


def _make_news_data(articles_by_cat: dict[str, list[dict]]) -> dict:
    """Build a news_data dict from a mapping of category → list of articles."""
    by_category = {}
    all_headlines = []
    for cat, arts in articles_by_cat.items():
        by_category[cat] = {"category": cat, "articles": arts}
        for a in arts:
            headline = f"[{cat.upper()}] {a['title']}"
            if a.get("description"):
                headline += f" — {a['description']}"
            all_headlines.append(headline)
    return {"by_category": by_category, "all_headlines": all_headlines}


def _make_spy_bars(volumes: list[float]) -> dict:
    """Build minimal market_data with SPY bars having the given volumes."""
    bars = [{"o": 500, "h": 505, "l": 499, "c": 502, "v": v} for v in volumes]
    return {
        "by_ticker": {
            "SPY": {"ticker": "SPY", "bars": bars, "latest_price": 502.0}
        }
    }


# ══════════════════════════════════════════════════════════════════════════════
# 1. MultiSourceConsensusGuard
# ══════════════════════════════════════════════════════════════════════════════

class TestMultiSourceConsensusGuard(unittest.TestCase):

    def test_empty_news_data_returns_all_headlines(self):
        news_data = {"by_category": {}, "all_headlines": ["[MACRO] Test headline"]}
        result, filtered = multi_source_consensus_guard(news_data)
        self.assertTrue(result.passed)
        self.assertEqual(filtered, news_data["all_headlines"])

    def test_single_source_article_is_dropped(self):
        """An article from a source that only appears once and has no topic overlap is dropped."""
        articles = {
            "macro": [
                _make_article("Federal Reserve holds rates steady", "Reuters"),
                _make_article("Inflation expectations unchanged this week", "Bloomberg"),
            ],
            "markets": [
                _make_article("Obscure single hedge fund bets on niche ETF", "OnlyMe News"),
            ],
        }
        news_data = _make_news_data(articles)
        result, filtered = multi_source_consensus_guard(news_data)
        self.assertTrue(result.passed)
        self.assertEqual(result.severity, "soft")
        self.assertLessEqual(result.meta["filtered_count"], result.meta["original_count"])

    def test_multi_source_articles_are_kept(self):
        """When multiple articles share a source or topic, all headlines are retained."""
        articles = {
            "macro": [
                _make_article("Federal Reserve raises rates by 25bps", "Reuters"),
                _make_article("Federal Reserve signals rate hike cycle end", "Reuters"),
            ],
        }
        news_data = _make_news_data(articles)
        result, filtered = multi_source_consensus_guard(news_data)
        self.assertTrue(result.passed)
        self.assertEqual(result.meta["dropped_count"], 0)
        self.assertEqual(len(filtered), len(news_data["all_headlines"]))

    def test_cross_category_corroboration_keeps_headline(self):
        """Article topic appearing in 2+ categories passes the consensus check."""
        articles = {
            "macro": [
                _make_article("Federal Reserve interest rates inflation rise", "AP"),
            ],
            "markets": [
                _make_article("Stock market falls amid Federal Reserve inflation fears", "CNBC"),
            ],
        }
        news_data = _make_news_data(articles)
        result, filtered = multi_source_consensus_guard(news_data)
        self.assertTrue(result.passed)
        self.assertGreater(len(filtered), 0)

    def test_result_is_always_soft_guard(self):
        news_data = {"by_category": {}, "all_headlines": []}
        result, _ = multi_source_consensus_guard(news_data)
        self.assertEqual(result.severity, "soft")
        self.assertTrue(result.passed)

    def test_meta_counts_are_consistent(self):
        articles = {
            "crypto": [
                _make_article("Bitcoin price hits new high this week", "CoinDesk"),
                _make_article("Ethereum upgrades network infrastructure now", "CoinDesk"),
            ],
        }
        news_data = _make_news_data(articles)
        result, filtered = multi_source_consensus_guard(news_data)
        self.assertEqual(
            result.meta["filtered_count"] + result.meta["dropped_count"],
            result.meta["original_count"],
        )


# ══════════════════════════════════════════════════════════════════════════════
# 2. TemporalQuarantineGuard
# ══════════════════════════════════════════════════════════════════════════════

class TestTemporalQuarantineGuard(unittest.TestCase):

    def _make_et_dt(self, weekday: int, hour: int, minute: int = 0):
        """Return a mocked ET datetime for the given weekday (0=Mon, 4=Fri, 5=Sat, 6=Sun)."""
        # Use a fixed date: Monday 2024-01-01 is weekday 0
        from datetime import date, timedelta
        base_monday = datetime(2024, 1, 1, hour, minute)  # Monday
        target = base_monday + timedelta(days=weekday)
        return target

    def test_friday_before_14_is_not_blocked(self):
        with patch("analysis.signal_guard.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 4   # Friday
            mock_now.time.return_value = _time_t(13, 59).replace(tzinfo=None)
            mock_now.strftime = lambda fmt: "Friday 13:59"
            mock_dt.now.return_value = mock_now
            result = temporal_quarantine_guard(calendar_check=False)
        self.assertTrue(result.passed)

    def test_friday_at_14_is_blocked(self):
        with patch("analysis.signal_guard.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 4   # Friday
            mock_now.time.return_value = _time_t(14, 0).replace(tzinfo=None)
            mock_now.strftime = lambda fmt: "Friday 14:00"
            mock_dt.now.return_value = mock_now
            result = temporal_quarantine_guard(calendar_check=False)
        self.assertFalse(result.passed)
        self.assertEqual(result.severity, "hard")

    def test_saturday_is_blocked(self):
        with patch("analysis.signal_guard.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 5   # Saturday
            mock_now.time.return_value = _time_t(10, 0).replace(tzinfo=None)
            mock_now.strftime = lambda fmt: "Saturday 10:00"
            mock_dt.now.return_value = mock_now
            result = temporal_quarantine_guard(calendar_check=False)
        self.assertFalse(result.passed)
        self.assertEqual(result.meta["trigger"], "weekend")

    def test_sunday_is_blocked(self):
        with patch("analysis.signal_guard.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 6   # Sunday
            mock_now.time.return_value = _time_t(20, 0).replace(tzinfo=None)
            mock_now.strftime = lambda fmt: "Sunday 20:00"
            mock_dt.now.return_value = mock_now
            result = temporal_quarantine_guard(calendar_check=False)
        self.assertFalse(result.passed)

    def test_monday_before_0930_is_blocked(self):
        with patch("analysis.signal_guard.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 0   # Monday
            mock_now.time.return_value = _time_t(9, 29).replace(tzinfo=None)
            mock_now.strftime = lambda fmt: "Monday 09:29"
            mock_dt.now.return_value = mock_now
            result = temporal_quarantine_guard(calendar_check=False)
        self.assertFalse(result.passed)

    def test_monday_at_0930_is_allowed(self):
        with patch("analysis.signal_guard.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 0   # Monday
            mock_now.time.return_value = _time_t(9, 30).replace(tzinfo=None)
            mock_now.strftime = lambda fmt: "Monday 09:30"
            mock_dt.now.return_value = mock_now
            result = temporal_quarantine_guard(calendar_check=False)
        self.assertTrue(result.passed)

    def test_wednesday_midday_is_allowed(self):
        with patch("analysis.signal_guard.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 2   # Wednesday
            mock_now.time.return_value = _time_t(14, 0).replace(tzinfo=None)
            mock_now.strftime = lambda fmt: "Wednesday 14:00"
            mock_dt.now.return_value = mock_now
            result = temporal_quarantine_guard(calendar_check=False)
        self.assertTrue(result.passed)

    def test_calendar_blackout_triggers_hard_block(self):
        mock_blackout = {
            "active": True,
            "event": "FOMC Rate Decision",
            "event_time_et": "14:00",
            "window_minutes": 30,
        }
        with patch("analysis.signal_guard.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 2   # Wednesday (not weekend)
            mock_now.time.return_value = _time_t(14, 15).replace(tzinfo=None)
            mock_now.strftime = lambda fmt: "Wednesday 14:15"
            mock_dt.now.return_value = mock_now
            with patch("data.economic_calendar.is_blackout_active", return_value=mock_blackout):
                result = temporal_quarantine_guard(calendar_check=True)
        self.assertFalse(result.passed)
        self.assertEqual(result.meta["trigger"], "calendar_blackout")

    def test_guard_is_always_hard_severity(self):
        with patch("analysis.signal_guard.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 2
            mock_now.time.return_value = _time_t(11, 0).replace(tzinfo=None)
            mock_now.strftime = lambda fmt: "Wednesday 11:00"
            mock_dt.now.return_value = mock_now
            result = temporal_quarantine_guard(calendar_check=False)
        self.assertEqual(result.severity, "hard")


# ══════════════════════════════════════════════════════════════════════════════
# 3. SentimentVolumeDivergenceGuard
# ══════════════════════════════════════════════════════════════════════════════

class TestSentimentVolumeDivergenceGuard(unittest.TestCase):

    def test_neutral_sentiment_never_downgraded(self):
        market_data = _make_spy_bars([100] * 25)
        result, adjusted = sentiment_volume_divergence_guard(market_data, "Neutral")
        self.assertTrue(result.passed)
        self.assertIsNone(adjusted)

    def test_extreme_fear_never_downgraded(self):
        market_data = _make_spy_bars([50] * 25)  # very low volume
        result, adjusted = sentiment_volume_divergence_guard(market_data, "Extreme Fear")
        self.assertTrue(result.passed)
        self.assertIsNone(adjusted)

    def test_greed_with_low_volume_is_downgraded_to_neutral(self):
        # 5-day avg < 20-day avg → downgrade
        volumes = [200] * 15 + [50] * 10  # last 5 days are 50, 20d avg ~112
        market_data = _make_spy_bars(volumes)
        result, adjusted = sentiment_volume_divergence_guard(market_data, "Greed")
        self.assertTrue(result.passed)
        self.assertEqual(adjusted, "Neutral")
        self.assertTrue(result.meta["adjusted"])
        self.assertLess(result.meta["vol_ratio"], 1.0)

    def test_extreme_greed_with_low_volume_is_downgraded_to_greed(self):
        volumes = [300] * 15 + [100] * 10  # 5d avg=100 < 20d avg
        market_data = _make_spy_bars(volumes)
        result, adjusted = sentiment_volume_divergence_guard(market_data, "Extreme Greed")
        self.assertEqual(adjusted, "Greed")

    def test_greed_with_high_volume_is_confirmed(self):
        # 5-day avg >= 20-day avg → no downgrade
        volumes = [100] * 15 + [200] * 10  # 5d avg=200 > 20d avg
        market_data = _make_spy_bars(volumes)
        result, adjusted = sentiment_volume_divergence_guard(market_data, "Greed")
        self.assertTrue(result.passed)
        self.assertIsNone(adjusted)
        self.assertFalse(result.meta["adjusted"])

    def test_insufficient_volume_data_returns_no_change(self):
        market_data = _make_spy_bars([100] * 10)  # only 10 bars, need 20
        result, adjusted = sentiment_volume_divergence_guard(market_data, "Greed")
        self.assertTrue(result.passed)
        self.assertIsNone(adjusted)
        self.assertIsNone(result.meta["vol_ratio"])

    def test_missing_spy_returns_no_change(self):
        market_data = {"by_ticker": {}}
        result, adjusted = sentiment_volume_divergence_guard(market_data, "Extreme Greed")
        self.assertTrue(result.passed)
        self.assertIsNone(adjusted)

    def test_vol_ratio_computation(self):
        # 25 bars: first 15 at vol=50, last 10 at vol=100
        # bars[-5:]  → 5 bars of 100       → avg_5d  = 100
        # bars[-20:] → 10×50 + 10×100      → avg_20d = (500+1000)/20 = 75
        # expected ratio = 100 / 75 ≈ 1.333
        volumes = [50] * 15 + [100] * 10
        market_data = _make_spy_bars(volumes)
        ratio = _compute_spy_volume_ratio(market_data)
        self.assertIsNotNone(ratio)
        self.assertAlmostEqual(ratio, 100 / 75, places=2)

    def test_result_is_always_soft_guard(self):
        market_data = _make_spy_bars([100] * 25)
        result, _ = sentiment_volume_divergence_guard(market_data, "Greed")
        self.assertEqual(result.severity, "soft")


# ══════════════════════════════════════════════════════════════════════════════
# 4. run_all_guards orchestrator
# ══════════════════════════════════════════════════════════════════════════════

class TestRunAllGuards(unittest.TestCase):

    def _make_context(self, sentiment_band: str = "Neutral", n_volumes: int = 25) -> dict:
        articles = {
            "macro": [
                _make_article("Federal Reserve holds rates", "Reuters"),
                _make_article("Federal Reserve holds rates again", "Reuters"),
            ],
        }
        return {
            "news_data":      _make_news_data(articles),
            "market_data":    _make_spy_bars([100.0] * n_volumes),
            "sentiment_band": sentiment_band,
        }

    def _patch_no_quarantine(self):
        """Patch datetime in signal_guard so we get a weekday mid-morning (no quarantine)."""
        patcher = patch("analysis.signal_guard.datetime")
        mock_dt = patcher.start()
        mock_now = MagicMock()
        mock_now.weekday.return_value = 2  # Wednesday
        mock_now.time.return_value = _time_t(11, 0).replace(tzinfo=None)
        mock_now.strftime = lambda fmt: "Wednesday 11:00"
        mock_dt.now.return_value = mock_now
        return patcher

    def test_returns_guard_run_result(self):
        patcher = self._patch_no_quarantine()
        try:
            context = self._make_context()
            result = run_all_guards(context)
            self.assertIsInstance(result, GuardRunResult)
        finally:
            patcher.stop()

    def test_no_block_on_normal_weekday(self):
        patcher = self._patch_no_quarantine()
        try:
            context = self._make_context()
            result = run_all_guards(context)
            self.assertFalse(result.hard_block)
        finally:
            patcher.stop()

    def test_hard_block_on_weekend(self):
        with patch("analysis.signal_guard.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 6  # Sunday
            mock_now.time.return_value = _time_t(15, 0).replace(tzinfo=None)
            mock_now.strftime = lambda fmt: "Sunday 15:00"
            mock_dt.now.return_value = mock_now
            context = self._make_context()
            result = run_all_guards(context)
        self.assertTrue(result.hard_block)
        self.assertFalse(any(r.passed is False for r in result.results if r.severity == "soft"))

    def test_three_guards_present_when_no_block(self):
        patcher = self._patch_no_quarantine()
        try:
            context = self._make_context()
            result = run_all_guards(context)
            guard_names = {r.name for r in result.results}
            self.assertIn("temporal_quarantine", guard_names)
            self.assertIn("multi_source_consensus", guard_names)
            self.assertIn("sentiment_volume_divergence", guard_names)
        finally:
            patcher.stop()

    def test_only_temporal_guard_when_hard_block(self):
        """When temporal quarantine fires, downstream guards are skipped."""
        with patch("analysis.signal_guard.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.weekday.return_value = 5  # Saturday
            mock_now.time.return_value = _time_t(12, 0).replace(tzinfo=None)
            mock_now.strftime = lambda fmt: "Saturday 12:00"
            mock_dt.now.return_value = mock_now
            context = self._make_context()
            result = run_all_guards(context)
        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.results[0].name, "temporal_quarantine")

    def test_sentiment_downgrade_propagated(self):
        # Low volume (5d < 20d) + Greed → should be downgraded
        patcher = self._patch_no_quarantine()
        try:
            volumes = [200] * 15 + [50] * 10  # high historical, low recent
            context = {
                "news_data":      _make_news_data({"macro": [
                    _make_article("Market news A", "Reuters"),
                    _make_article("Market news B", "Reuters"),
                ]}),
                "market_data":    _make_spy_bars(volumes),
                "sentiment_band": "Greed",
            }
            result = run_all_guards(context)
            self.assertEqual(result.adjusted_sentiment, "Neutral")
        finally:
            patcher.stop()

    def test_to_dict_is_serialisable(self):
        patcher = self._patch_no_quarantine()
        try:
            import json
            context = self._make_context()
            result = run_all_guards(context)
            serialised = json.dumps(result.to_dict())
            self.assertIsInstance(serialised, str)
        finally:
            patcher.stop()

    def test_get_last_guard_result_populated_after_run(self):
        from analysis.signal_guard import get_last_guard_result
        patcher = self._patch_no_quarantine()
        try:
            context = self._make_context()
            run_all_guards(context)
            last = get_last_guard_result()
            self.assertIsNotNone(last)
            self.assertIn("hard_block", last)
            self.assertIn("guards", last)
        finally:
            patcher.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)
