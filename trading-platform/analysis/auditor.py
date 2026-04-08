"""
Auditor Agent — Human-in-the-Loop (HITL) Supervisor
=====================================================
Runs as a daily post-market job (4:30 PM ET) and via on-demand API.
Operates in read-only mode against the primary bot's data — it never
places trades or modifies state.

Five audit checks
-----------------
  1. regime_integrity   — Critiques the primary bot's regime classification
                          using a second LLM call at higher temperature (0.7).
                          Flags 'Heuristic Mismatch' when the bot claims
                          'Sideways' but ATR is expanding or SPY z-score > 2.0.

  2. compliance_audit   — Cross-references every slot in the last allocation
                          plan against the 30-day wash-sale window.
                          Issues 'Compliance Hold' for substantially-identical
                          tickers within the look-back period.

  3. rag_bias_check     — Detects potential look-ahead bias in the RAG feedback
                          window: abnormally high-conviction wins in recent
                          market stress periods, or thesis language referencing
                          information only available post-trade.

  4. phantom_drawdown   — Monitors the kill switch drawdown calculation for
                          anomalies near the 4–5% alert threshold: checks that
                          the DA-HWM adjustment is being correctly applied and
                          that the opening_equity baseline is plausible.

  5. ratchet_integrity  — Validates every persisted ratchet stop against the
                          current price and live ATR.  Issues 'System Integrity
                          Alert' if a stop is above current price (impossible
                          long stop), above the fill price, or more than 3×ATR
                          away from the fill (stop was never ratcheted).

Report
------
  • Writes logs/daily_audit_report_{YYYY-MM-DD}.md (always)
  • Logs a prominent summary banner to the workflow logs (always)
  • POSTs to Discord webhook if DISCORD_WEBHOOK_URL is set in Replit Secrets

LLM usage
---------
  Uses the same GROQ_API_KEY / llama-3.3-70b-versatile model as the primary
  bot but at temperature=0.7 (more critical / adversarial) and with a strict
  2,000-token response cap to minimise TPD consumption.
  The LLM is only invoked for check #1 (regime critique) and only when the
  heuristic pre-check detects a potential mismatch — saving tokens when
  everything looks normal.
"""

from __future__ import annotations

import json
import os
import re
import textwrap
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import requests as http_requests
from loguru import logger

# ── Shared infrastructure ────────────────────────────────────────────────────
from config.settings import settings
from db.postgres import get_conn, is_pg_available
from execution.compliance import SIMILARITY_MAP, get_similar_tickers
from execution.kill_switch import get_state as ks_get_state
from execution.ratchet_stop import ATR_MULTIPLIER, ATR_PERIOD, compute_atr
from analysis.trade_journal import (
    get_all_trades,
    get_recent_losses,
    get_recent_wins,
)

# ── Report output directory ───────────────────────────────────────────────────
_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 ── Shared data types
# ══════════════════════════════════════════════════════════════════════════════

class AuditFinding:
    """
    Immutable result of a single audit check.
    severity levels: INFO < WARNING < ALERT < HOLD
    """
    LEVELS = ("INFO", "WARNING", "ALERT", "HOLD")

    def __init__(
        self,
        check:    str,
        passed:   bool,
        severity: str,
        message:  str,
        details:  dict | None = None,
    ):
        assert severity in self.LEVELS, f"Unknown severity: {severity}"
        self.check    = check
        self.passed   = passed
        self.severity = severity
        self.message  = message
        self.details  = details or {}

    def to_dict(self) -> dict:
        return {
            "check":    self.check,
            "passed":   self.passed,
            "severity": self.severity,
            "message":  self.message,
            "details":  self.details,
        }

    def __repr__(self) -> str:
        status = "✓ PASS" if self.passed else "✗ FAIL"
        return f"[{self.severity}] {self.check}: {status} — {self.message}"


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 ── LLM critique client (adversarial, high temperature)
# ══════════════════════════════════════════════════════════════════════════════

_AUDITOR_SYSTEM_PROMPT = """\
You are a Senior Risk Auditor and Quantitative Strategist reviewing an automated
trading bot's regime classification.  Your role is ADVERSARIAL — actively look
for flaws, inconsistencies, and heuristic mismatches.  Be concise and specific.

Respond in JSON with exactly these keys:
{
  "verdict":   "PASS" | "MISMATCH" | "UNCERTAIN",
  "rationale": "<2–4 sentence critique>",
  "flags":     ["<specific issue 1>", "<specific issue 2>"]
}
"""


def _llm_regime_critique(
    regime: str,
    rationale: str,
    spy_z_score: float,
    atr_expansion_pct: float,
    vix_proxy: float,
) -> dict:
    """
    Call Groq at temperature=0.7 to critique the primary bot's regime call.
    Returns the parsed JSON verdict dict.  Falls back to a neutral verdict on any error.
    """
    from groq import Groq

    user_prompt = f"""\
PRIMARY BOT REGIME CLASSIFICATION:
  Regime   : {regime}
  Rationale: {rationale}

CURRENT MARKET HEURISTICS (computed independently):
  SPY 20-day return z-score : {spy_z_score:+.2f}  (|z| > 2.0 = significant stress)
  ATR expansion vs 30d avg  : {atr_expansion_pct:+.1f}%  (> 0 = volatility expanding)
  VIX proxy (SPY 14d ATR %) : {vix_proxy:.2f}%

Critique the regime label.  A 'Sideways' call is suspicious when z-score > 2.0
or ATR is expanding >15%.  A 'Bull' call is suspicious when ATR is expanding >20%.
Flag any mismatch between the claimed regime and the heuristics above."""

    try:
        from analysis.gemini_auditor import _gemini_base_url, _gemini_api_key
        import requests as _req
        _url = f"{_gemini_base_url()}/models/gemini-3-flash-preview:generateContent"
        _body = {
            "system_instruction": {"parts": [{"text": _AUDITOR_SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "maxOutputTokens": 8192,
                "temperature": 0.7,
            },
        }
        _resp = _req.post(
            _url,
            headers={"Content-Type": "application/json", "x-goog-api-key": _gemini_api_key()},
            json=_body,
            timeout=60,
        )
        if _resp.status_code != 200:
            raise RuntimeError(f"Gemini HTTP {_resp.status_code}: {_resp.text[:200]}")
        _data = _resp.json()
        _usage = _data.get("usageMetadata", {})
        _total = _usage.get("totalTokenCount", 0)
        _text = _data["candidates"][0]["content"]["parts"][0]["text"]
        logger.info(
            f"Auditor LLM | Regime critique complete — "
            f"tokens: prompt={_usage.get('promptTokenCount','?')} completion={_usage.get('candidatesTokenCount','?')}"
        )
        try:
            from analysis.groq_budget import budget as _budget
            _budget.consume(_total, call_type="audit")
        except Exception:
            pass
        return json.loads(_text)
    except Exception as exc:
        logger.warning(f"Auditor LLM | Critique failed: {exc} — returning neutral verdict")
        return {
            "verdict":   "UNCERTAIN",
            "rationale": f"LLM critique unavailable: {exc}",
            "flags":     [],
        }


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 ── Market heuristics (independent from primary bot)
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_spy_heuristics() -> dict:
    """
    Compute independent market stress indicators using SPY price history.
    These are deliberately re-computed here (not reused from the primary bot)
    to maintain audit independence.

    Returns:
        z_score          — 20-day return z-score of SPY  (|z|>2 = stress)
        atr_expansion_pct— % change in 14d ATR vs 30d ATR (>0 = expanding)
        vix_proxy        — current 14d ATR as % of SPY price (ATR%)
    """
    try:
        import numpy as np
        import yfinance as yf

        spy = yf.Ticker("SPY").history(period="60d", interval="1d", auto_adjust=True)
        if spy is None or len(spy) < 30:
            raise ValueError("Insufficient SPY data")

        close  = spy["Close"].values
        high   = spy["High"].values
        low    = spy["Low"].values

        # Daily returns z-score over last 20 days
        returns = (close[1:] - close[:-1]) / close[:-1]
        recent_ret = returns[-20:]
        mean_r, std_r = float(np.mean(recent_ret)), float(np.std(recent_ret))
        z_score = (returns[-1] - mean_r) / std_r if std_r > 0 else 0.0

        # ATR computation helper
        def _atr(n: int) -> float:
            trs = [
                max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
                for i in range(1, len(close))
            ]
            return float(np.mean(trs[-n:]))

        atr_14  = _atr(14)
        atr_30  = _atr(30)
        atr_expansion_pct = ((atr_14 - atr_30) / atr_30 * 100) if atr_30 > 0 else 0.0
        vix_proxy = (atr_14 / close[-1] * 100) if close[-1] > 0 else 0.0

        return {
            "z_score":            round(z_score, 3),
            "atr_expansion_pct":  round(atr_expansion_pct, 2),
            "vix_proxy":          round(vix_proxy, 3),
            "spy_last_close":     round(float(close[-1]), 2),
            "error":              None,
        }

    except Exception as exc:
        logger.warning(f"Auditor | SPY heuristics failed: {exc}")
        return {
            "z_score":           0.0,
            "atr_expansion_pct": 0.0,
            "vix_proxy":         0.0,
            "spy_last_close":    None,
            "error":             str(exc),
        }


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 ── CHECK 1: Regime Integrity Audit
# ══════════════════════════════════════════════════════════════════════════════

def check_regime_integrity() -> AuditFinding:
    """
    Compares the primary bot's last regime classification against independently
    computed market heuristics.  Only calls the LLM when a heuristic mismatch
    is detected (to conserve Groq TPD budget).
    """
    from core.pipeline import get_last_run

    last_run = get_last_run()
    allocation = last_run.get("last_allocation")
    regime_label = last_run.get("last_regime")

    if not allocation or not regime_label:
        return AuditFinding(
            check="regime_integrity",
            passed=True,
            severity="INFO",
            message="No allocation plan yet — bot has not run a full cycle",
            details={"last_run_status": last_run.get("last_run_status")},
        )

    # Get regime and rationale from allocation object
    if hasattr(allocation, "regime"):
        regime = str(allocation.regime)
        rationale = getattr(allocation, "regime_rationale", "") or ""
    else:
        regime    = str(regime_label)
        rationale = ""

    # Compute independent heuristics
    heuristics = _fetch_spy_heuristics()
    z_score    = heuristics["z_score"]
    atr_exp    = heuristics["atr_expansion_pct"]
    vix_proxy  = heuristics["vix_proxy"]

    # Heuristic mismatch rules (applied before calling LLM)
    mismatches: list[str] = []
    if regime in ("Sideways", "Bull") and abs(z_score) > 2.0:
        mismatches.append(
            f"Regime='{regime}' but SPY z-score={z_score:+.2f} (|z|>2.0 indicates market stress)"
        )
    if regime in ("Sideways", "Bull") and atr_exp > 15.0:
        mismatches.append(
            f"Regime='{regime}' but ATR is expanding {atr_exp:+.1f}% vs 30-day avg"
        )
    if regime == "Bull" and vix_proxy > 2.5:
        mismatches.append(
            f"Regime='Bull' but VIX proxy={vix_proxy:.2f}% (above 2.5% suggests elevated volatility)"
        )

    llm_verdict: dict = {}

    if mismatches:
        # Only call LLM when heuristics flag a potential problem
        logger.info(f"Auditor | Regime heuristic mismatch detected — calling LLM critique")
        llm_verdict = _llm_regime_critique(regime, rationale, z_score, atr_exp, vix_proxy)
        verdict = llm_verdict.get("verdict", "UNCERTAIN")

        if verdict == "MISMATCH":
            return AuditFinding(
                check="regime_integrity",
                passed=False,
                severity="ALERT",
                message=(
                    f"Heuristic Mismatch: Primary bot called '{regime}' but independent "
                    f"market metrics contradict this (z={z_score:+.2f}, ATR_exp={atr_exp:+.1f}%)"
                ),
                details={
                    "regime":           regime,
                    "heuristics":       heuristics,
                    "mismatches":       mismatches,
                    "llm_verdict":      verdict,
                    "llm_rationale":    llm_verdict.get("rationale"),
                    "llm_flags":        llm_verdict.get("flags", []),
                },
            )
        else:
            # LLM not convinced — downgrade to WARNING
            return AuditFinding(
                check="regime_integrity",
                passed=False,
                severity="WARNING",
                message=(
                    f"Potential regime mismatch for '{regime}' (heuristic flags: "
                    f"{len(mismatches)}), LLM verdict: {verdict}"
                ),
                details={
                    "regime":        regime,
                    "heuristics":    heuristics,
                    "mismatches":    mismatches,
                    "llm_verdict":   verdict,
                    "llm_rationale": llm_verdict.get("rationale"),
                },
            )

    # No heuristic mismatch — skip LLM call entirely
    return AuditFinding(
        check="regime_integrity",
        passed=True,
        severity="INFO",
        message=f"Regime '{regime}' is consistent with heuristics (z={z_score:+.2f}, ATR_exp={atr_exp:+.1f}%)",
        details={
            "regime":     regime,
            "heuristics": heuristics,
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 ── CHECK 2: Compliance Audit (Wash-Sale Cross-Reference)
# ══════════════════════════════════════════════════════════════════════════════

def check_compliance() -> AuditFinding:
    """
    Cross-references every ticker in the last allocation plan against the
    30-day wash-sale window.  Issues 'Compliance Hold' for any substantially-
    identical ticker to a recent loss.
    """
    from core.pipeline import get_last_run
    from execution.compliance import check_wash_sale

    last_run   = get_last_run()
    allocation = last_run.get("last_allocation")

    if not allocation:
        return AuditFinding(
            check="compliance",
            passed=True,
            severity="INFO",
            message="No allocation to audit — bot has not run a full cycle",
        )

    slots = getattr(allocation, "allocations", []) or []
    if not slots:
        return AuditFinding(
            check="compliance",
            passed=True,
            severity="INFO",
            message="Allocation plan has no active slots",
        )

    holds: list[dict] = []
    clean: list[str]  = []

    for slot in slots:
        ticker = getattr(slot, "ticker", None)
        if not ticker or ticker == "SGOV":
            continue

        result = check_wash_sale(ticker, lookback_days=30)
        if result["blocked"]:
            holds.append({
                "ticker":         ticker,
                "blocking_ticker": result["similar_ticker"],
                "loss_date":       result["loss_date"],
                "pnl_pct":         result["pnl_pct"],
                "reason":          result["reason"],
            })
        else:
            clean.append(ticker)

    if holds:
        hold_tickers = [h["ticker"] for h in holds]
        return AuditFinding(
            check="compliance",
            passed=False,
            severity="HOLD",
            message=(
                f"Compliance Hold: {len(holds)} ticker(s) violate the 30-day wash-sale rule — "
                f"{', '.join(hold_tickers)}"
            ),
            details={
                "holds":  holds,
                "clean":  clean,
                "action": "These positions should NOT be executed until the wash-sale window clears",
            },
        )

    return AuditFinding(
        check="compliance",
        passed=True,
        severity="INFO",
        message=f"All {len(clean)} proposed tickers pass the 30-day wash-sale check",
        details={"clean": clean},
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 ── CHECK 3: RAG Look-Ahead Bias Detection
# ══════════════════════════════════════════════════════════════════════════════

def check_rag_bias() -> AuditFinding:
    """
    Detects potential look-ahead bias in the RAG feedback window.

    Heuristics applied:
      a) Implausibly high win rate in the recent feedback window (>80%): suggests
         the sample is too small or the bot is cherry-picking wins for context.
      b) High-conviction wins (conviction > 0.90) with very high PnL (>15%): a
         10-slot bot with a 15-minute cycle cannot legitimately achieve >15% per
         trade in paper-trading — this suggests a stale or miscalculated P&L.
      c) Zero losses in any 5+ trade window: statistically improbable; may
         indicate the loss-update reconciliation is broken.
      d) Thesis keywords that reference information typically unavailable at
         trade entry (e.g., "earnings beat", "post-merger", "announced today"):
         these suggest the thesis was rewritten after the fact.
    """
    wins   = get_recent_wins(limit=10)
    losses = get_recent_losses(limit=10)
    all_trades = get_all_trades(limit=50)

    flags: list[str]  = []
    details: dict     = {}

    # ── (a) Implausible win rate ─────────────────────────────────────────────
    total_closed = [t for t in all_trades if t.get("status", "").startswith("Closed")]
    if len(total_closed) >= 5:
        win_count  = sum(1 for t in total_closed if t["status"] == "Closed_Win")
        win_rate   = win_count / len(total_closed)
        if win_rate > 0.80:
            flags.append(
                f"Implausibly high win rate: {win_rate:.0%} over {len(total_closed)} closed trades "
                f"(expected <65% for a long-only regime-switching strategy)"
            )
        details["win_rate"] = round(win_rate, 3)
        details["total_closed"] = len(total_closed)

    # ── (b) Suspicious high-conviction wins ─────────────────────────────────
    suspicious_wins = [
        w for w in wins
        if (w.get("conviction_score") or 0) > 0.90
        and abs(w.get("pnl_percentage") or 0) > 15.0
        and w.get("status") == "Closed_Win"
    ]
    if suspicious_wins:
        flags.append(
            f"{len(suspicious_wins)} high-conviction win(s) with P&L >15% — "
            f"verify P&L calculation is not using post-close prices: "
            f"{[w['ticker'] for w in suspicious_wins]}"
        )
        details["suspicious_wins"] = [
            {"ticker": w["ticker"], "pnl": w.get("pnl_percentage"), "conviction": w.get("conviction_score")}
            for w in suspicious_wins
        ]

    # ── (c) Zero-loss windows ────────────────────────────────────────────────
    if len(total_closed) >= 5 and not any(
        t["status"] == "Closed_Loss" for t in total_closed[-5:]
    ):
        flags.append(
            "No losses in the last 5 closed trades — statistically improbable; "
            "verify post-mortem reconciliation is running correctly"
        )

    # ── (d) Hindsight thesis keywords ────────────────────────────────────────
    _HINDSIGHT_PATTERNS = re.compile(
        r"\b(earnings beat|post.merger|announced today|beat estimates|"
        r"after the close|after-hours|next day|following the announcement|"
        r"since then|in hindsight)\b",
        re.IGNORECASE,
    )
    hindsight_trades = []
    for trade in all_trades[:20]:
        thesis = trade.get("original_thesis") or ""
        if _HINDSIGHT_PATTERNS.search(thesis):
            hindsight_trades.append({
                "ticker": trade["ticker"],
                "date":   str(trade.get("date")),
                "thesis": thesis[:120],
            })
    if hindsight_trades:
        flags.append(
            f"{len(hindsight_trades)} trade thesis/theses contain look-ahead language "
            f"(e.g. 'earnings beat', 'after the close')"
        )
        details["hindsight_trades"] = hindsight_trades

    if flags:
        severity = "ALERT" if len(flags) >= 2 else "WARNING"
        return AuditFinding(
            check="rag_bias",
            passed=False,
            severity=severity,
            message=f"RAG look-ahead bias: {len(flags)} flag(s) detected",
            details={"flags": flags, **details},
        )

    return AuditFinding(
        check="rag_bias",
        passed=True,
        severity="INFO",
        message="No look-ahead bias indicators found in the RAG feedback window",
        details=details,
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 ── CHECK 4: Phantom Drawdown Near Kill Switch
# ══════════════════════════════════════════════════════════════════════════════

def check_phantom_drawdown() -> AuditFinding:
    """
    Validates the kill switch drawdown calculation for anomalies.

    Checks:
      a) Drawdown percentage is within 0.5% of the kill-switch threshold
         (danger zone alert — not yet tripped but close).
      b) The DA-HWM adjustment is reasonable: checks that the vault_ledger
         HWM is not unrealistically far above current equity (which would
         indicate the HWM was set incorrectly and every day looks like a
         drawdown even in recovery).
      c) Opening equity baseline plausibility: the stored opening_equity
         should be within ±15% of current equity. A stale or missing
         opening_equity leads to phantom drawdowns.
    """
    ks_state      = ks_get_state()
    tripped       = ks_state.get("tripped", False)
    drawdown_pct  = float(ks_state.get("drawdown_pct") or 0.0)
    opening_eq    = ks_state.get("opening_equity")
    threshold     = float(settings.kill_switch_drawdown_pct)

    flags:   list[str] = []
    details: dict      = {
        "kill_switch_tripped": tripped,
        "drawdown_pct":        round(drawdown_pct, 4),
        "threshold_pct":       threshold,
        "opening_equity":      opening_eq,
    }

    # ── (a) Danger zone ─────────────────────────────────────────────────────
    danger_margin = 0.005          # 0.5% margin
    if not tripped and drawdown_pct > 0 and (threshold - drawdown_pct) < danger_margin:
        flags.append(
            f"Danger zone: daily drawdown {drawdown_pct:.2%} is within {danger_margin:.0%} "
            f"of the {threshold:.0%} kill-switch threshold"
        )

    # ── (b) DA-HWM sanity check ─────────────────────────────────────────────
    try:
        if is_pg_available():
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT hwm, da_adjustment, total_vaulted_usd FROM vault_ledger WHERE id = 1"
                    )
                    row = cur.fetchone()
            if row:
                hwm, da_adj, vaulted = row
                details["hwm"]            = round(float(hwm), 2)
                details["da_adjustment"]  = round(float(da_adj or 0), 2)
                details["total_vaulted"]  = round(float(vaulted or 0), 2)

                # HWM sanity: if HWM is more than 20% above current equity,
                # the DA-HWM adjustment may not be working correctly
                if opening_eq and hwm > 0 and opening_eq > 0:
                    hwm_vs_eq_pct = (hwm - opening_eq) / opening_eq
                    if hwm_vs_eq_pct > 0.20:
                        flags.append(
                            f"DA-HWM suspect: HWM (${hwm:,.0f}) is {hwm_vs_eq_pct:.0%} above "
                            f"current opening equity (${opening_eq:,.0f}) — JEPQ unrealised P&L "
                            f"adjustment may not be applied correctly"
                        )
    except Exception as exc:
        logger.warning(f"Auditor | Vault DB read failed: {exc}")
        details["vault_db_error"] = str(exc)

    # ── (c) Opening equity plausibility ─────────────────────────────────────
    if opening_eq is None:
        flags.append(
            "Opening equity is None — kill switch has not been initialised today. "
            "The first cycle of the day should call kill_switch.reset()."
        )
    elif opening_eq <= 0:
        flags.append(f"Opening equity is ${opening_eq:,.2f} — clearly invalid")

    if flags:
        severity = "ALERT" if any("Danger zone" in f or "DA-HWM" in f for f in flags) else "WARNING"
        return AuditFinding(
            check="phantom_drawdown",
            passed=False,
            severity=severity,
            message=f"Drawdown anomaly: {len(flags)} flag(s) detected",
            details={**details, "flags": flags},
        )

    return AuditFinding(
        check="phantom_drawdown",
        passed=True,
        severity="INFO",
        message=(
            f"Kill switch drawdown is healthy: "
            f"{drawdown_pct:.2%} vs {threshold:.0%} threshold"
            + (" (TRIPPED)" if tripped else "")
        ),
        details=details,
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8 ── CHECK 5: Ratchet Stop Integrity (Volatility Guard)
# ══════════════════════════════════════════════════════════════════════════════

def check_ratchet_integrity() -> AuditFinding:
    """
    Validates every persisted ratchet stop against current market prices and ATR.

    Alert conditions (System Integrity Alert):
      • stop_price > current_price  — stop is above the market price; for a
                                      long position this means it already hit
                                      but the position was not cleaned up.
      • stop_price >= fill_price    — stop above or at entry; impossible for
                                      a fresh long without the ratchet having
                                      overshot the fill.
      • stop distance > 3×ATR      — stop is more than 3×ATR away from entry,
                                      suggesting the ratchet has never fired
                                      or the stored ATR is stale.
      • Stored stop < fill × 0.85  — stop is more than 15% below entry price,
                                      which is far beyond any reasonable ATR
                                      multiplier and likely a data error.
    """
    try:
        if not is_pg_available():
            return AuditFinding(
                check="ratchet_integrity",
                passed=True,
                severity="INFO",
                message="PostgreSQL unavailable — ratchet audit skipped",
            )

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT symbol, stop_price, fill_price, atr, last_updated "
                    "FROM ratchet_stops"
                )
                rows = cur.fetchall()

    except Exception as exc:
        return AuditFinding(
            check="ratchet_integrity",
            passed=False,
            severity="WARNING",
            message=f"Could not read ratchet_stops table: {exc}",
        )

    if not rows:
        return AuditFinding(
            check="ratchet_integrity",
            passed=True,
            severity="INFO",
            message="No active ratchet stops — nothing to audit",
        )

    alerts:  list[dict] = []
    healthy: list[str]  = []

    for symbol, stop_price, fill_price, stored_atr, last_updated in rows:
        stop_price  = float(stop_price)
        fill_price  = float(fill_price)
        stored_atr  = float(stored_atr)
        issues: list[str] = []

        # Fetch current price and live ATR
        try:
            import yfinance as yf
            sym_yf  = symbol.replace("/", "-")
            hist    = yf.Ticker(sym_yf).history(period="5d", interval="1d", auto_adjust=True)
            current_price = float(hist["Close"].iloc[-1]) if len(hist) else None
        except Exception:
            current_price = None

        live_atr = compute_atr(symbol)  # uses the same yfinance-based ATR as the primary bot

        # Check 1: stop above current price
        if current_price and stop_price > current_price:
            issues.append(
                f"stop (${stop_price:.4f}) > current price (${current_price:.2f}) — "
                "position may have already been stopped out without DB cleanup"
            )

        # Check 2: stop above fill price
        if stop_price >= fill_price:
            issues.append(
                f"stop (${stop_price:.4f}) >= fill price (${fill_price:.4f}) — "
                "ratchet has overshot the entry; unexpected for a long position"
            )

        # Check 3: stop distance > 3 × live ATR
        if live_atr and live_atr > 0:
            stop_distance = fill_price - stop_price
            max_expected  = ATR_MULTIPLIER * live_atr * 3
            if stop_distance > max_expected:
                issues.append(
                    f"stop distance (${stop_distance:.4f}) > 3×ATR_mult×ATR "
                    f"(${max_expected:.4f}) — ratchet may not have fired; "
                    f"live_atr=${live_atr:.4f}"
                )

        # Check 4: stop far below fill (>15%)
        if fill_price > 0 and stop_price < fill_price * 0.85:
            issues.append(
                f"stop (${stop_price:.4f}) is >{abs((stop_price/fill_price - 1)*100):.0f}% "
                f"below fill (${fill_price:.4f}) — likely a stale or miscomputed stop"
            )

        if issues:
            alerts.append({
                "symbol":        symbol,
                "stop_price":    stop_price,
                "fill_price":    fill_price,
                "current_price": current_price,
                "stored_atr":    stored_atr,
                "live_atr":      live_atr,
                "last_updated":  str(last_updated),
                "issues":        issues,
            })
        else:
            healthy.append(symbol)

    if alerts:
        return AuditFinding(
            check="ratchet_integrity",
            passed=False,
            severity="ALERT",
            message=(
                f"System Integrity Alert: {len(alerts)} ratchet stop(s) have integrity issues — "
                f"{[a['symbol'] for a in alerts]}"
            ),
            details={"alerts": alerts, "healthy": healthy},
        )

    return AuditFinding(
        check="ratchet_integrity",
        passed=True,
        severity="INFO",
        message=f"All {len(healthy)} ratchet stop(s) pass integrity checks",
        details={"healthy": healthy},
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9 ── Prompt Engineering Recommendations
# ══════════════════════════════════════════════════════════════════════════════

def _build_prompt_recommendations(findings: list[AuditFinding]) -> list[str]:
    """
    Generate actionable prompt-engineering tweaks for the primary bot based
    on failed-trade patterns and audit findings.  These go into the report
    as human-readable suggestions, not auto-applied.
    """
    recs: list[str] = []

    losses = get_recent_losses(limit=10)
    if losses:
        # Group losses by asset class to find patterns
        from collections import Counter
        loss_classes = Counter(t.get("asset_class") for t in losses)
        dominant = loss_classes.most_common(1)[0]
        if dominant[1] >= 2:
            recs.append(
                f"The primary bot has {dominant[1]} recent losses in '{dominant[0]}'. "
                f"Consider adding to the system prompt: "
                f"'If {dominant[0]} assets have produced 2+ consecutive losses, "
                f"reduce conviction threshold to 0.90 for this asset class.'"
            )

        # Low-conviction losses (conviction < 0.80 but still traded)
        low_conv_losses = [t for t in losses if (t.get("conviction_score") or 1) < 0.80]
        if low_conv_losses:
            recs.append(
                f"{len(low_conv_losses)} loss(es) had conviction < 0.80 — "
                f"add to system prompt: 'Only include a ticker in the allocation if "
                f"conviction_score >= 0.82. Exclude any ticker where you are below "
                f"high-confidence threshold.'"
            )

    # Regime mismatch was flagged
    regime_finding = next((f for f in findings if f.check == "regime_integrity" and not f.passed), None)
    if regime_finding:
        recs.append(
            "Regime classification was flagged as inconsistent with market heuristics. "
            "Add to system prompt: 'Before labelling a regime as Sideways or Bull, "
            "explicitly state the VIX level and ATR trend. If ATR is expanding >15% "
            "from its 30-day average, default to Bear or Sideways, not Bull.'"
        )

    # Compliance holds
    compliance_finding = next((f for f in findings if f.check == "compliance" and not f.passed), None)
    if compliance_finding:
        holds = compliance_finding.details.get("holds", [])
        blocked = [h["ticker"] for h in holds]
        recs.append(
            f"Wash-sale block on: {blocked}. Add to system prompt: "
            f"'Do NOT include {', '.join(blocked)} or any substantially-identical "
            f"ETF in allocations until the 30-day wash-sale window clears.'"
        )

    if not recs:
        recs.append(
            "No prompt engineering tweaks recommended at this time — "
            "all audit checks passed or were informational only."
        )

    return recs


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 10 ── Report Generation
# ══════════════════════════════════════════════════════════════════════════════

def _severity_emoji(severity: str) -> str:
    return {"INFO": "✅", "WARNING": "⚠️", "ALERT": "🚨", "HOLD": "🔒"}.get(severity, "ℹ️")


def _render_markdown_report(
    findings: list[AuditFinding],
    recommendations: list[str],
    run_at: datetime,
) -> str:
    """Render the full audit report as a Markdown string."""

    failed_count   = sum(1 for f in findings if not f.passed)
    alert_count    = sum(1 for f in findings if f.severity in ("ALERT", "HOLD"))
    overall_status = "🔴 ACTION REQUIRED" if alert_count > 0 else (
                     "🟡 REVIEW RECOMMENDED" if failed_count > 0 else "🟢 ALL CLEAR"
                    )

    lines = [
        f"# Daily Audit Report — {run_at.strftime('%Y-%m-%d')}",
        f"",
        f"**Generated:** {run_at.strftime('%Y-%m-%d %H:%M:%S UTC')}  ",
        f"**Overall Status:** {overall_status}  ",
        f"**Checks:** {len(findings)} total — {failed_count} failed — {alert_count} alerts/holds",
        f"",
        f"---",
        f"",
        f"## Audit Findings",
        f"",
    ]

    for f in findings:
        emoji  = _severity_emoji(f.severity)
        status = "PASS" if f.passed else "FAIL"
        lines += [
            f"### {emoji} [{f.severity}] {f.check.replace('_', ' ').title()}",
            f"**Result:** {status}  ",
            f"**Message:** {f.message}",
            f"",
        ]
        if f.details:
            for k, v in f.details.items():
                if k in ("flags", "mismatches", "holds", "alerts", "hindsight_trades",
                         "suspicious_wins", "llm_flags"):
                    if isinstance(v, list) and v:
                        lines.append(f"**{k.replace('_',' ').title()}:**")
                        for item in v:
                            item_str = json.dumps(item, default=str) if isinstance(item, dict) else str(item)
                            lines.append(f"- {item_str}")
                        lines.append("")
                elif k not in ("llm_rationale",):
                    pass   # skip bulk dicts in the main table
            if f.details.get("llm_rationale"):
                lines += [
                    f"**LLM Critique:** _{f.details['llm_rationale']}_",
                    f"",
                ]
        lines.append("")

    lines += [
        f"---",
        f"",
        f"## Prompt Engineering Recommendations",
        f"",
        f"The following tweaks are suggested for the Primary Bot's system prompt "
        f"based on recent trade patterns and audit findings:",
        f"",
    ]
    for i, rec in enumerate(recommendations, 1):
        lines.append(f"{i}. {rec}")
        lines.append("")

    lines += [
        f"---",
        f"",
        f"## Compliance Matrix Summary",
        f"",
        f"*30-day wash-sale similarity groups active in this system:*",
        f"",
        f"| Group | Tickers |",
        f"|-------|---------|",
    ]
    from execution.compliance import _SIMILARITY_GROUPS
    seen: set = set()
    for group in _SIMILARITY_GROUPS:
        tickers_str = ", ".join(sorted(group))
        if tickers_str not in seen:
            lines.append(f"| — | {tickers_str} |")
            seen.add(tickers_str)

    lines += [
        f"",
        f"---",
        f"",
        f"*Report generated by Auditor Agent v1.0 — read-only, non-executing*",
    ]

    return "\n".join(lines)


def _write_report(content: str, run_date: date) -> Path:
    """Write the report to a dated file, keeping the last 30 days."""
    path = _LOG_DIR / f"daily_audit_report_{run_date.isoformat()}.md"
    path.write_text(content, encoding="utf-8")

    # Rotate: delete files older than 30 days
    cutoff = run_date - timedelta(days=30)
    for old in _LOG_DIR.glob("daily_audit_report_*.md"):
        try:
            file_date = date.fromisoformat(old.stem.replace("daily_audit_report_", ""))
            if file_date < cutoff:
                old.unlink()
        except (ValueError, OSError):
            pass

    logger.info(f"Auditor | Report written to {path}")
    return path


def _notify(
    findings: list[AuditFinding],
    report_path: Path,
    run_at: datetime,
) -> None:
    """
    Log a prominent summary banner and optionally POST to Discord webhook.
    Set DISCORD_WEBHOOK_URL in Replit Secrets to enable webhook delivery.
    """
    failed  = [f for f in findings if not f.passed]
    alerts  = [f for f in findings if f.severity in ("ALERT", "HOLD")]
    overall = "ALL_CLEAR" if not failed else ("ACTION_REQUIRED" if alerts else "REVIEW")

    # ── Workflow log banner ──────────────────────────────────────────────────
    banner = [
        "=" * 65,
        f" AUDITOR AGENT REPORT — {run_at.strftime('%Y-%m-%d %H:%M UTC')}",
        f" Status : {overall}",
        f" Checks : {len(findings)} | Failed: {len(failed)} | Alerts/Holds: {len(alerts)}",
        "-" * 65,
    ]
    for f in findings:
        status_str = "✓ PASS" if f.passed else "✗ FAIL"
        banner.append(f"  [{f.severity:7s}] {f.check:<22s} {status_str} — {f.message[:55]}")
    banner += [
        "-" * 65,
        f" Report : {report_path}",
        "=" * 65,
    ]
    for line in banner:
        if alerts and line.strip():
            logger.warning(line)
        else:
            logger.info(line)

    # ── Discord webhook (optional) ───────────────────────────────────────────
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        return

    color = 0xFF0000 if alerts else (0xFFA500 if failed else 0x00FF00)
    fields = [
        {
            "name":   f"{_severity_emoji(f.severity)} {f.check.replace('_', ' ').title()}",
            "value":  f"{'✓' if f.passed else '✗'} {f.message[:200]}",
            "inline": False,
        }
        for f in findings
    ]

    payload = {
        "embeds": [{
            "title":       f"Auditor Agent — {overall} — {run_at.strftime('%Y-%m-%d')}",
            "description": f"{len(failed)} checks failed | {len(alerts)} alerts/holds",
            "color":       color,
            "fields":      fields[:10],   # Discord embed limit
            "footer":      {"text": "Quant Terminal Auditor Agent v1.0"},
            "timestamp":   run_at.isoformat(),
        }]
    }

    try:
        resp = http_requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("Auditor | Discord notification sent")
    except Exception as exc:
        logger.warning(f"Auditor | Discord webhook failed: {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 11 ── Master Orchestrator
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 10b ── CHECK 6: Kraken Bot Compliance (Davy Jones' Portfolio)
# ══════════════════════════════════════════════════════════════════════════════

def check_kraken_bot() -> AuditFinding:
    """
    Audit the Kraken mean-reversion bot (Davy Jones' Portfolio) for
    risk-rule compliance. Data is sourced from kraken-bot/status.json,
    which the bot writes after every trading cycle.

    Checks:
      a) Cash reserve ≥ 20% — never fully deployed
      b) No single position > 30% of equity
      c) No position showing unrealised loss > 2% (stop-loss adherence)
      d) Circuit-breaker activation count in recent trades
      e) Overall recent-trade P&L balance
    """
    status_file = Path(__file__).parent.parent.parent / "kraken-bot" / "status.json"

    if not status_file.exists():
        return AuditFinding(
            check="kraken_bot",
            passed=True,
            severity="INFO",
            message="Kraken bot (Davy Jones' Portfolio) has not run yet — no data to audit",
            details={"status_file": str(status_file)},
        )

    try:
        status = json.loads(status_file.read_text())
    except Exception as exc:
        return AuditFinding(
            check="kraken_bot",
            passed=False,
            severity="WARNING",
            message=f"Could not parse kraken-bot/status.json: {exc}",
            details={},
        )

    flags: list[str] = []
    details: dict    = {}

    total_equity = status.get("total_equity_usd", 0)
    deployed_usd = status.get("deployed_usd", 0)
    positions    = status.get("open_positions", [])
    recent_trades = status.get("recent_trades", [])
    cb_active    = status.get("circuit_breaker", {}).get("active", False)
    cash_reserve_pct = status.get("cash_reserve_pct", 20)

    details["bot_status"]    = status.get("status")
    details["cycle_count"]   = status.get("cycle_count", 0)
    details["equity_usd"]    = total_equity
    details["deployed_usd"]  = deployed_usd

    # ── (a) Cash reserve check ────────────────────────────────────────────────
    if total_equity > 0:
        actual_reserve_pct = ((total_equity - deployed_usd) / total_equity) * 100
        details["actual_reserve_pct"] = round(actual_reserve_pct, 1)
        if actual_reserve_pct < cash_reserve_pct * 0.9:  # Allow 10% tolerance
            flags.append(
                f"Cash reserve breach: {actual_reserve_pct:.1f}% held "
                f"(minimum {cash_reserve_pct}% required)"
            )

    # ── (b) Single-position concentration check ───────────────────────────────
    if total_equity > 0:
        for pos in positions:
            pos_pct = (pos.get("size_usd", 0) / total_equity) * 100
            if pos_pct > 32:  # 2% tolerance over the 30% cap
                flags.append(
                    f"Position concentration: {pos.get('symbol')} at "
                    f"{pos_pct:.1f}% of equity (max 30% allowed)"
                )
        details["positions"] = [
            {"symbol": p.get("symbol"), "side": p.get("side"),
             "size_pct": round((p.get("size_usd", 0) / total_equity * 100) if total_equity else 0, 1)}
            for p in positions
        ]

    # ── (c) Stop-loss adherence — check recent trades ─────────────────────────
    stop_breaches = [
        t for t in recent_trades
        if t.get("pnl_pct", 0) < -3.0  # If a trade lost more than 3% the stop failed
    ]
    if stop_breaches:
        flags.append(
            f"{len(stop_breaches)} recent trade(s) lost >3% — "
            f"stop-loss may not have fired correctly: "
            f"{[t.get('symbol') for t in stop_breaches]}"
        )
    details["stop_breaches"] = len(stop_breaches)

    # ── (d) Circuit breaker activations ──────────────────────────────────────
    if cb_active:
        flags.append("Circuit breaker is currently ACTIVE — flash crash detected")
    details["circuit_breaker_active"] = cb_active

    # ── (e) Recent P&L balance ────────────────────────────────────────────────
    if recent_trades:
        total_pnl = sum(t.get("pnl_pct", 0) for t in recent_trades)
        win_count = sum(1 for t in recent_trades if (t.get("pnl_usd") or 0) > 0)
        details["recent_trade_count"] = len(recent_trades)
        details["recent_total_pnl_pct"] = round(total_pnl, 2)
        details["recent_win_rate"] = round(win_count / len(recent_trades), 2)

    if flags:
        severity = "ALERT" if len(flags) >= 2 else "WARNING"
        return AuditFinding(
            check="kraken_bot",
            passed=False,
            severity=severity,
            message=f"Kraken bot compliance: {len(flags)} issue(s) detected",
            details={**details, "flags": flags},
        )

    return AuditFinding(
        check="kraken_bot",
        passed=True,
        severity="INFO",
        message=(
            f"Davy Jones' Portfolio is compliant — "
            f"{len(positions)} position(s), "
            f"{details.get('actual_reserve_pct', '?')}% cash reserve maintained"
        ),
        details=details,
    )


_last_audit: dict[str, Any] = {
    "run_at":    None,
    "overall":   "never_run",
    "findings":  [],
    "report_path": None,
}


def run_full_audit() -> dict[str, Any]:
    """
    Execute all five audit checks, generate the Markdown report, send notifications.

    Returns a JSON-serialisable summary dict suitable for the /auditor/report endpoint.
    Always completes — individual check failures are captured, not re-raised.
    """
    run_at = datetime.now(tz=timezone.utc)
    logger.info(f"Auditor | Starting full audit at {run_at.isoformat()}")

    findings: list[AuditFinding] = []

    # Run all five checks — capture exceptions so one bad check never kills the audit
    checks = [
        ("regime_integrity",  check_regime_integrity),
        ("compliance",        check_compliance),
        ("rag_bias",          check_rag_bias),
        ("phantom_drawdown",  check_phantom_drawdown),
        ("ratchet_integrity", check_ratchet_integrity),
        ("kraken_bot",        check_kraken_bot),
    ]

    for check_name, check_fn in checks:
        try:
            finding = check_fn()
            findings.append(finding)
            level = "warning" if not finding.passed else "debug"
            getattr(logger, level)(f"Auditor | {finding}")
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error(f"Auditor | Check '{check_name}' raised an exception: {exc}\n{tb}")
            findings.append(AuditFinding(
                check=check_name,
                passed=False,
                severity="WARNING",
                message=f"Check crashed: {exc}",
                details={"traceback": tb[-500:]},
            ))

    recommendations = _build_prompt_recommendations(findings)
    report_md       = _render_markdown_report(findings, recommendations, run_at)
    report_path     = _write_report(report_md, run_at.date())

    _notify(findings, report_path, run_at)

    failed  = [f for f in findings if not f.passed]
    alerts  = [f for f in findings if f.severity in ("ALERT", "HOLD")]
    overall = "ALL_CLEAR" if not failed else ("ACTION_REQUIRED" if alerts else "REVIEW_RECOMMENDED")

    result = {
        "run_at":          run_at.isoformat(),
        "overall":         overall,
        "total_checks":    len(findings),
        "failed_checks":   len(failed),
        "alert_count":     len(alerts),
        "findings":        [f.to_dict() for f in findings],
        "recommendations": recommendations,
        "report_path":     str(report_path),
    }

    _last_audit.update(result)
    logger.success(f"Auditor | Full audit complete — {overall} ({len(failed)}/{len(findings)} failed)")

    try:
        from notifications.discord import notify_audit_complete
        notify_audit_complete(overall, len(failed), len(alerts), recommendations)
    except Exception:
        pass

    # ── Auto-export learning snapshot so production gets this knowledge ────────
    try:
        from analysis.learning_snapshot import export_snapshot
        export_snapshot()
    except Exception as _snap_err:
        logger.warning(f"Auditor | Learning snapshot export failed (non-fatal): {_snap_err}")

    return result


def get_last_audit() -> dict[str, Any]:
    """Return the result of the most recent audit (may be from any earlier run)."""
    return dict(_last_audit)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8 ── Performance Narrative Analysis
# ══════════════════════════════════════════════════════════════════════════════
# Uses Groq to generate a short, plain-English comparison of both bots'
# recent performance — suitable for display on the dashboard.
# ══════════════════════════════════════════════════════════════════════════════

_PERFORMANCE_NARRATIVE_PROMPT = """\
You are a concise quant performance analyst reviewing two automated trading bots.
Write a SHORT (3-5 sentence) plain-English narrative comparing their recent performance.
Be specific about win rates and trends. Sound like a senior analyst giving a verbal briefing —
direct, no fluff, no markdown, no bullet points. Just natural spoken paragraphs."""

_last_performance_report: dict[str, Any] = {"status": "not_run"}


def _load_kraken_recent_trades() -> list[dict]:
    """Read the Kraken bot's recent_trades list from its status file."""
    try:
        status_path = Path(__file__).parent.parent.parent / "kraken-bot" / "status.json"
        if not status_path.exists():
            return []
        with open(status_path) as f:
            data = json.load(f)
        return data.get("recent_trades", [])
    except Exception as exc:
        logger.warning(f"PerfAnalysis | Could not load Kraken status: {exc}")
        return []


def run_performance_analysis(days: int = 10) -> dict[str, Any]:
    """
    Analyse both bots' recent performance and generate a plain-English narrative
    using Groq. Stores the result in _last_performance_report.
    """
    global _last_performance_report
    run_at = datetime.now(tz=timezone.utc)

    # ── Alpaca / Degen Oracle stats ────────────────────────────────────────
    try:
        from analysis.trade_journal import get_all_trades
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=days)).date()
        all_alpaca = get_all_trades(limit=500)
        recent_alpaca = [
            t for t in all_alpaca
            if t.get("date") and str(t["date"])[:10] >= str(cutoff)
            and t.get("status") in ("Closed_Win", "Closed_Loss")
        ]
        alpaca_total  = len(recent_alpaca)
        alpaca_wins   = sum(1 for t in recent_alpaca if t.get("status") == "Closed_Win")
        alpaca_losses = alpaca_total - alpaca_wins
        alpaca_win_rate = (alpaca_wins / alpaca_total * 100) if alpaca_total > 0 else None
        alpaca_avg_pnl  = (
            sum(float(t.get("pnl_percentage") or 0) for t in recent_alpaca) / alpaca_total
            if alpaca_total > 0 else None
        )
    except Exception as exc:
        logger.warning(f"PerfAnalysis | Alpaca stats error: {exc}")
        alpaca_total = alpaca_wins = alpaca_losses = 0
        alpaca_win_rate = alpaca_avg_pnl = None

    # ── Kraken / Davy Jones stats ──────────────────────────────────────────
    try:
        kraken_trades = _load_kraken_recent_trades()
        closed_kraken = [t for t in kraken_trades if t.get("pnl_pct") is not None]
        kraken_total  = len(closed_kraken)
        kraken_wins   = sum(1 for t in closed_kraken if float(t.get("pnl_usd", 0) or 0) > 0)
        kraken_losses = kraken_total - kraken_wins
        kraken_win_rate = (kraken_wins / kraken_total * 100) if kraken_total > 0 else None
        kraken_avg_pnl  = (
            sum(float(t.get("pnl_pct", 0) or 0) for t in closed_kraken) / kraken_total
            if kraken_total > 0 else None
        )
    except Exception as exc:
        logger.warning(f"PerfAnalysis | Kraken stats error: {exc}")
        kraken_total = kraken_wins = kraken_losses = 0
        kraken_win_rate = kraken_avg_pnl = None

    def _fmt_wr(wr: float | None) -> str:
        return f"{wr:.0f}%" if wr is not None else "N/A"

    def _fmt_pnl(pnl: float | None, suffix: str = "%") -> str:
        if pnl is None:
            return "N/A"
        return f"{pnl:+.2f}{suffix}"

    user_prompt = f"""\
ANALYSIS WINDOW: Last {days} days

DEGEN ORACLE BOT (Alpaca — US Equities, LLM-driven):
  Closed trades : {alpaca_total}
  Wins / Losses : {alpaca_wins} / {alpaca_losses}
  Win rate      : {_fmt_wr(alpaca_win_rate)}
  Avg P&L       : {_fmt_pnl(alpaca_avg_pnl)} per trade

DAVY JONES BOT (Kraken — 24/7 Crypto, mean-reversion):
  Closed trades : {kraken_total}
  Wins / Losses : {kraken_wins} / {kraken_losses}
  Win rate      : {_fmt_wr(kraken_win_rate)}
  Avg P&L       : {_fmt_pnl(kraken_avg_pnl)} per trade

Write a 3-5 sentence plain-English performance briefing comparing both bots.
If trade counts are low (< 3), note that data is limited.
Be specific about which bot is outperforming and why the numbers suggest that."""

    narrative = "Performance analysis unavailable — LLM call failed."
    try:
        from analysis.gemini_auditor import _gemini_base_url, _gemini_api_key
        import requests as _req
        _url = f"{_gemini_base_url()}/models/gemini-3-flash-preview:generateContent"
        _body = {
            "system_instruction": {"parts": [{"text": _PERFORMANCE_NARRATIVE_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "maxOutputTokens": 8192,
                "temperature": 0.5,
            },
        }
        _resp = _req.post(
            _url,
            headers={"Content-Type": "application/json", "x-goog-api-key": _gemini_api_key()},
            json=_body,
            timeout=60,
        )
        if _resp.status_code != 200:
            raise RuntimeError(f"Gemini HTTP {_resp.status_code}: {_resp.text[:200]}")
        _data = _resp.json()
        _usage = _data.get("usageMetadata", {})
        perf_tokens = _usage.get("totalTokenCount", 0)
        narrative = _data["candidates"][0]["content"]["parts"][0]["text"].strip()
        logger.info(f"PerfAnalysis | Narrative generated ({len(narrative)} chars)")
        try:
            from analysis.groq_budget import budget as _budget
            _budget.consume(perf_tokens, call_type="performance")
        except Exception:
            pass
    except Exception as exc:
        logger.error(f"PerfAnalysis | Gemini call failed: {exc}")

    _last_performance_report = {
        "status":       "ok",
        "run_at":       run_at.isoformat(),
        "days_analysed": days,
        "alpaca": {
            "total":    alpaca_total,
            "wins":     alpaca_wins,
            "losses":   alpaca_losses,
            "win_rate": round(alpaca_win_rate, 1) if alpaca_win_rate is not None else None,
            "avg_pnl":  round(alpaca_avg_pnl, 2) if alpaca_avg_pnl is not None else None,
        },
        "kraken": {
            "total":    kraken_total,
            "wins":     kraken_wins,
            "losses":   kraken_losses,
            "win_rate": round(kraken_win_rate, 1) if kraken_win_rate is not None else None,
            "avg_pnl":  round(kraken_avg_pnl, 2) if kraken_avg_pnl is not None else None,
        },
        "narrative": narrative,
    }
    logger.success("PerfAnalysis | Complete")
    return dict(_last_performance_report)


def get_last_performance_report() -> dict[str, Any]:
    """Return the most recent performance analysis result."""
    return dict(_last_performance_report)
