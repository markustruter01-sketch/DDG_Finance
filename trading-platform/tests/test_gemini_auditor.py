"""
tests/test_gemini_auditor.py
============================
Unit tests for Task #26 — Gemini Self-Critic Auditor.

Covers:
  • gemini_context_sanitizer — estimate_tokens, sanitize_daily_context,
    chunk_by_hours
  • gemini_auditor — Pydantic model validation, _merge_responses,
    run_daily_self_critic (mocked Gemini + DB), get_last_gemini_audit
"""

from __future__ import annotations

import json
import os
import time
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock


# ── Path bootstrap ─────────────────────────────────────────────────────────────
import sys
_REPO_ROOT    = Path(__file__).parent.parent.parent
_PLATFORM_DIR = Path(__file__).parent.parent
for p in [str(_REPO_ROOT), str(_PLATFORM_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 ── Sanitizer tests
# ══════════════════════════════════════════════════════════════════════════════

class TestGeminiContextSanitizer(unittest.TestCase):

    def setUp(self):
        from analysis.gemini_context_sanitizer import (
            TOKEN_BUDGET,
            CHUNK_THRESHOLD,
            estimate_tokens,
            sanitize_daily_context,
            chunk_by_hours,
        )
        self.TOKEN_BUDGET       = TOKEN_BUDGET
        self.CHUNK_THRESHOLD    = CHUNK_THRESHOLD
        self.estimate_tokens    = estimate_tokens
        self.sanitize           = sanitize_daily_context
        self.chunk_by_hours     = chunk_by_hours

    # ── estimate_tokens ────────────────────────────────────────────────────────

    def test_estimate_tokens_empty(self):
        self.assertEqual(self.estimate_tokens(""), 0)

    def test_estimate_tokens_ratio(self):
        text = "A" * 400
        self.assertEqual(self.estimate_tokens(text), 100)

    def test_estimate_tokens_large(self):
        text = "x" * 4_000_000
        self.assertEqual(self.estimate_tokens(text), 1_000_000)

    # ── sanitize_daily_context ─────────────────────────────────────────────────

    def test_sanitize_strips_html(self):
        raw = {"trades": [{"ticker": "AAPL", "thesis": "<b>Strong momentum</b>"}]}
        out = self.sanitize(raw)
        self.assertNotIn("<b>", out)
        self.assertIn("Strong momentum", out)

    def test_sanitize_strips_markdown_bold(self):
        raw = {"trades": [{"thesis": "**Very bullish** on MSFT"}]}
        out = self.sanitize(raw)
        self.assertNotIn("**", out)
        self.assertIn("Very bullish", out)

    def test_sanitize_deduplicates_news(self):
        raw = {
            "news_headlines": [
                "Fed raises rates by 25bps",
                "Fed raises rates by 25bps",   # duplicate
                "Inflation data below expectations",
            ]
        }
        out  = self.sanitize(raw)
        data = json.loads(out)
        self.assertEqual(len(data["news_headlines"]), 2)

    def test_sanitize_rounds_floats(self):
        raw = {"trades": [{"pnl": 1.123456789}]}
        out  = self.sanitize(raw)
        data = json.loads(out)
        pnl  = data["trades"][0]["pnl"]
        self.assertAlmostEqual(pnl, 1.1235, places=4)

    def test_sanitize_drops_none(self):
        raw = {"trades": [{"ticker": "AAPL", "notes": None}]}
        out  = self.sanitize(raw)
        data = json.loads(out)
        self.assertNotIn("notes", data["trades"][0])

    def test_sanitize_truncates_long_strings(self):
        long_thesis = "X" * 600
        raw = {"trades": [{"thesis": long_thesis}]}
        out  = self.sanitize(raw)
        data = json.loads(out)
        self.assertLessEqual(len(data["trades"][0]["thesis"]), 400 + 10)  # _MAX_STR_LEN

    def test_sanitize_returns_valid_json(self):
        raw = {
            "trades": [
                {"ticker": "SPY", "conviction_score": 0.75, "pnl_percentage": 2.5}
            ],
            "equity_curve": [
                {"ts": "2026-03-29T10:00:00Z", "total_equity": 100_000.0}
            ],
        }
        out = self.sanitize(raw)
        parsed = json.loads(out)     # must not raise
        self.assertIn("trades", parsed)

    # ── chunk_by_hours ─────────────────────────────────────────────────────────

    def _make_records(self, n: int, start: datetime, step_minutes: int = 5):
        return [
            {
                "ts": (start + timedelta(minutes=i * step_minutes)).isoformat(),
                "value": i,
            }
            for i in range(n)
        ]

    def test_chunk_empty_returns_empty(self):
        result = self.chunk_by_hours([], hours_per_chunk=8)
        self.assertEqual(result, [])

    def test_chunk_single_window(self):
        start   = datetime(2026, 3, 29, 9, 0, tzinfo=timezone.utc)
        records = self._make_records(10, start, step_minutes=5)
        chunks  = self.chunk_by_hours(records, hours_per_chunk=8)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(len(chunks[0]), 10)

    def test_chunk_splits_across_windows(self):
        start   = datetime(2026, 3, 29, 0, 0, tzinfo=timezone.utc)
        # 24 hours of records at 30-min spacing = 48 records → should split into 3 chunks
        records = self._make_records(48, start, step_minutes=30)
        chunks  = self.chunk_by_hours(records, hours_per_chunk=8)
        self.assertEqual(len(chunks), 3)
        total = sum(len(c) for c in chunks)
        self.assertEqual(total, 48)

    def test_chunk_no_ts_key_returns_single_chunk(self):
        records = [{"value": i} for i in range(20)]
        chunks  = self.chunk_by_hours(records, hours_per_chunk=8)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(len(chunks[0]), 20)

    def test_chunk_mixed_ts_and_no_ts(self):
        start   = datetime(2026, 3, 29, 9, 0, tzinfo=timezone.utc)
        ts_recs = self._make_records(5, start, step_minutes=60)
        no_ts   = [{"value": "no_timestamp"} for _ in range(3)]
        combined = ts_recs + no_ts
        chunks  = self.chunk_by_hours(combined, hours_per_chunk=8)
        # all go into one chunk (5 hours < 8h window) + 3 no-ts appended
        flat = [r for c in chunks for r in c]
        self.assertEqual(len(flat), 8)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 ── Pydantic model tests
# ══════════════════════════════════════════════════════════════════════════════

class TestGeminiAuditResponseModel(unittest.TestCase):

    def setUp(self):
        from analysis.gemini_auditor import _GeminiAuditResponse, _GeminiCondition
        self._GeminiAuditResponse = _GeminiAuditResponse
        self._GeminiCondition     = _GeminiCondition

    def test_default_values(self):
        r = self._GeminiAuditResponse()
        self.assertEqual(r.vetoed_tickers, [])
        self.assertEqual(r.conditions, [])
        self.assertEqual(r.overall_verdict, "CLEAN")

    def test_verdict_normalised_upper(self):
        r = self._GeminiAuditResponse(overall_verdict="caution")
        self.assertEqual(r.overall_verdict, "CAUTION")

    def test_invalid_verdict_defaults_to_caution(self):
        r = self._GeminiAuditResponse(overall_verdict="UNKNOWN_VERDICT")
        self.assertEqual(r.overall_verdict, "CAUTION")

    def test_tickers_uppercased(self):
        r = self._GeminiAuditResponse(vetoed_tickers=["aapl", "tsla"])
        self.assertEqual(r.vetoed_tickers, ["AAPL", "TSLA"])

    def test_tickers_strip_slash(self):
        r = self._GeminiAuditResponse(vetoed_tickers=["BTC/USD"])
        self.assertEqual(r.vetoed_tickers, ["BTCUSD"])

    def test_condition_type_nonempty(self):
        with self.assertRaises(Exception):
            self._GeminiCondition(type="  ")  # empty after strip

    def test_condition_with_value_and_ticker(self):
        c = self._GeminiCondition(type="news_blacklist", value=None, ticker="META")
        self.assertEqual(c.ticker, "META")
        self.assertIsNone(c.value)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 ── _merge_responses tests
# ══════════════════════════════════════════════════════════════════════════════

class TestMergeResponses(unittest.TestCase):

    def setUp(self):
        from analysis.gemini_auditor import _merge_responses, _GeminiAuditResponse, _GeminiCondition
        self._merge     = _merge_responses
        self._Resp      = _GeminiAuditResponse
        self._Cond      = _GeminiCondition

    def _resp(self, tickers, verdict, flags=None, conditions=None):
        return self._Resp(
            vetoed_tickers  = tickers,
            overall_verdict = verdict,
            critique_flags  = flags or [],
            conditions      = conditions or [],
        )

    def test_merge_empty(self):
        r = self._merge([])
        self.assertEqual(r.vetoed_tickers, [])
        self.assertEqual(r.overall_verdict, "CLEAN")

    def test_merge_single(self):
        r = self._merge([self._resp(["AAPL"], "HOLD")])
        self.assertEqual(r.overall_verdict, "HOLD")

    def test_merge_verdict_highest_wins(self):
        r = self._merge([
            self._resp([], "CLEAN"),
            self._resp([], "HOLD"),
            self._resp([], "CAUTION"),
        ])
        self.assertEqual(r.overall_verdict, "HOLD")

    def test_merge_ticker_union(self):
        r = self._merge([
            self._resp(["AAPL", "MSFT"], "CLEAN"),
            self._resp(["TSLA", "AAPL"], "CAUTION"),
        ])
        self.assertIn("AAPL", r.vetoed_tickers)
        self.assertIn("MSFT", r.vetoed_tickers)
        self.assertIn("TSLA", r.vetoed_tickers)
        # AAPL appears once
        self.assertEqual(r.vetoed_tickers.count("AAPL"), 1)

    def test_merge_conditions_deduped(self):
        cond = self._Cond(type="vpin_threshold", value=0.7)
        r = self._merge([
            self._resp([], "CLEAN", conditions=[cond]),
            self._resp([], "CLEAN", conditions=[cond]),   # duplicate
        ])
        self.assertEqual(len(r.conditions), 1)

    def test_merge_flags_concatenated(self):
        r = self._merge([
            self._resp([], "CLEAN", flags=["flag1", "flag2"]),
            self._resp([], "CLEAN", flags=["flag3"]),
        ])
        self.assertEqual(len(r.critique_flags), 3)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 ── run_daily_self_critic integration tests (mocked)
# ══════════════════════════════════════════════════════════════════════════════

class TestRunDailySelfCritic(unittest.TestCase):

    def setUp(self):
        # Ensure env vars are available for the run
        os.environ["AI_INTEGRATIONS_GEMINI_BASE_URL"] = "http://localhost:1106/modelfarm/gemini"
        os.environ["AI_INTEGRATIONS_GEMINI_API_KEY"]  = "dummy-test-key"

    def _mock_fetch(self):
        """Return a minimal but realistic data dict."""
        return {
            "trades": [
                {
                    "trade_id":        "T001",
                    "date":            "2026-03-29",
                    "ticker":          "SPY",
                    "asset_class":     "etf",
                    "conviction_score": 0.78,
                    "original_thesis": "Broad market ETF with strong momentum",
                    "pnl_percentage":  1.5,
                    "status":          "Closed_Win",
                }
            ],
            "equity_curve": [
                {"ts": "2026-03-29T10:00:00+00:00", "total_equity": 100_000.0},
                {"ts": "2026-03-29T12:00:00+00:00", "total_equity": 101_500.0},
            ],
            "degradations": [],
            "performance":  [
                {"date": "2026-03-29", "daily_pnl_pct": 1.5, "win_rate": 0.65}
            ],
        }

    def _mock_gemini_response(self):
        """Simulated Gemini REST response body."""
        payload = {
            "vetoed_tickers":   ["TSLA"],
            "conditions":       [{"type": "max_conviction_cap", "value": 0.85}],
            "critique_summary": "Portfolio is performing within expected parameters. "
                                "One ticker flagged for elevated volatility.",
            "critique_flags":   ["TSLA has unusual conviction inflation"],
            "overall_verdict":  "CAUTION",
        }
        return {
            "candidates": [
                {
                    "content": {
                        "role":  "model",
                        "parts": [{"text": json.dumps(payload)}],
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"promptTokenCount": 500, "candidatesTokenCount": 100},
        }

    def test_successful_run_writes_veto_file(self):
        from analysis import gemini_auditor

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = self._mock_gemini_response()

        with tempfile.TemporaryDirectory() as tmpdir:
            veto_path = Path(tmpdir) / "veto_conditions.json"

            with patch.object(gemini_auditor, "_VETO_FILE", veto_path), \
                 patch.object(gemini_auditor, "_fetch_audit_data", return_value=self._mock_fetch()), \
                 patch("requests.post", return_value=mock_resp):

                result = gemini_auditor.run_daily_self_critic()

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["overall_verdict"], "CAUTION")
        self.assertIn("TSLA", result["vetoed_tickers"])

    def test_gemini_http_error_fails_open(self):
        from analysis import gemini_auditor

        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.text = "Service Unavailable"

        with patch.object(gemini_auditor, "_fetch_audit_data", return_value=self._mock_fetch()), \
             patch("requests.post", return_value=mock_resp):

            result = gemini_auditor.run_daily_self_critic()

        self.assertEqual(result["status"], "failed")
        self.assertIn("503", result["reason"])

    def test_no_db_data_skips_cleanly(self):
        from analysis import gemini_auditor

        with patch.object(gemini_auditor, "_fetch_audit_data", return_value={}):
            result = gemini_auditor.run_daily_self_critic()

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "no_data")

    def test_missing_env_var_skips(self):
        from analysis import gemini_auditor

        saved = os.environ.pop("AI_INTEGRATIONS_GEMINI_BASE_URL", None)
        try:
            result = gemini_auditor.run_daily_self_critic()
            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["reason"], "env_vars_missing")
        finally:
            if saved:
                os.environ["AI_INTEGRATIONS_GEMINI_BASE_URL"] = saved

    def test_invalid_gemini_json_fails_open(self):
        from analysis import gemini_auditor

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "role":  "model",
                        "parts": [{"text": "this is not json {{{{"}],
                    }
                }
            ]
        }

        with patch.object(gemini_auditor, "_fetch_audit_data", return_value=self._mock_fetch()), \
             patch("requests.post", return_value=mock_resp):

            result = gemini_auditor.run_daily_self_critic()

        self.assertEqual(result["status"], "failed")

    def test_veto_file_not_written_on_failure(self):
        from analysis import gemini_auditor

        with tempfile.TemporaryDirectory() as tmpdir:
            veto_path = Path(tmpdir) / "veto_conditions.json"

            import requests as _req
            with patch.object(gemini_auditor, "_VETO_FILE", veto_path), \
                 patch.object(gemini_auditor, "_fetch_audit_data", return_value=self._mock_fetch()), \
                 patch("requests.post", side_effect=_req.ConnectionError("refused")):

                gemini_auditor.run_daily_self_critic()

            # File must NOT have been created
            self.assertFalse(veto_path.exists())


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 ── get_last_gemini_audit tests
# ══════════════════════════════════════════════════════════════════════════════

class TestGetLastGeminiAudit(unittest.TestCase):

    def test_not_run_when_file_missing(self):
        from analysis import gemini_auditor

        with tempfile.TemporaryDirectory() as tmpdir:
            veto_path = Path(tmpdir) / "veto_conditions.json"
            with patch.object(gemini_auditor, "_VETO_FILE", veto_path):
                result = gemini_auditor.get_last_gemini_audit()

        self.assertEqual(result["status"], "not_run")
        self.assertFalse(result["file_exists"])

    def test_ok_when_file_present(self):
        from analysis import gemini_auditor

        payload = {
            "generated_at":   "2026-03-30T04:15:00+00:00",
            "valid_until":    "2026-03-31T04:15:00+00:00",
            "vetoed_tickers": ["AAPL"],
            "conditions":     [],
            "critique_summary": "Clean session",
            "critique_flags": [],
            "overall_verdict": "CLEAN",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            veto_path = Path(tmpdir) / "veto_conditions.json"
            veto_path.write_text(json.dumps(payload))
            with patch.object(gemini_auditor, "_VETO_FILE", veto_path):
                result = gemini_auditor.get_last_gemini_audit()

        self.assertEqual(result["status"], "ok")
        self.assertIn("AAPL", result["vetoed_tickers"])
        self.assertEqual(result["overall_verdict"], "CLEAN")

    def test_error_when_file_corrupt(self):
        from analysis import gemini_auditor

        with tempfile.TemporaryDirectory() as tmpdir:
            veto_path = Path(tmpdir) / "veto_conditions.json"
            veto_path.write_text("{{{invalid json")
            with patch.object(gemini_auditor, "_VETO_FILE", veto_path):
                result = gemini_auditor.get_last_gemini_audit()

        self.assertEqual(result["status"], "error")
        self.assertTrue(result["file_exists"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
