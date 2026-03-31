"""
Rule Engine — Phase 4: Permanent Hardcoded Rules
--------------------------------------------------
Scans execution_post_mortems for recurring failure patterns and promotes
them to permanent rules that are injected into every LLM system prompt.

Architecture:
  - rollup_permanent_rules() runs after each evening post-mortem cycle.
    It groups losses in execution_post_mortems by (ticker, regime, exit_reason)
    and for any pattern that has occurred >= PROMOTION_THRESHOLD (default 3) times,
    it generates a deterministic RULE: string and upserts it into hardcoded_rules.

  - get_active_rules() is called by feedback_injection.py at every prompt-build
    to inject the current set of permanent rules into the foundational system prompt.
    Rules injected here are NEVER forgotten — they persist across restarts.

Idempotent: re-running the rollup only updates failure_count and rule_text;
it never creates duplicate rows (ON CONFLICT … DO UPDATE).

Exit-reason labels used in rule text:
  ratchet_stop  → premature stop-loss whipsawing (execution failure)
  time_exit     → momentum stalled before the mandatory 5-day time exit (thesis failure)
  algo_cover    → algorithmic short covered before Z-score mean-reverted (execution gap)
  allocation_sell → position liquidated on rebalance before thesis resolved
  manual        → manually closed before natural exit
  unknown       → unclassified exit
"""

from __future__ import annotations

from loguru import logger


# Number of identical failures required before the pattern becomes a permanent rule.
PROMOTION_THRESHOLD = 3


# ── Exit-reason → human-readable label ─────────────────────────────────────

_EXIT_LABELS: dict[str, str] = {
    "ratchet_stop":    "premature stop-loss whipsawing (stop triggered before thesis resolved)",
    "time_exit":       "momentum stalling before the mandatory 5-day time exit",
    "algo_cover":      "algorithmic short cover before full Z-score mean-reversion",
    "allocation_sell": "forced rebalance liquidation before thesis completed",
    "manual":          "discretionary manual exit overriding the system",
    "unknown":         "unclassified exit (no exit reason captured)",
}

_EXIT_PREFIX: dict[str, str] = {
    "ratchet_stop":    "EXECUTION FAILURE",
    "time_exit":       "THESIS FAILURE",
    "algo_cover":      "EXECUTION GAP",
    "allocation_sell": "ALLOCATION CONFLICT",
    "manual":          "MANUAL OVERRIDE",
    "unknown":         "UNCLASSIFIED",
}


def _generate_rule_text(
    ticker: str,
    regime: str,
    asset_class: str | None,
    exit_reason: str,
    failure_count: int,
    latest_lesson: str | None,
) -> str:
    """
    Produce a concise, actionable RULE string for the LLM system prompt.
    Format mirrors the user-specified example:
      RULE: Historical data shows a high failure rate [description]. Abort similar setups.
    """
    label  = _EXIT_LABELS.get(exit_reason, exit_reason)
    prefix = _EXIT_PREFIX.get(exit_reason, "FAILURE")
    ac     = f" ({asset_class})" if asset_class else ""

    base = (
        f"RULE [{prefix}]: Historical data shows {ticker}{ac} in {regime} regime "
        f"has failed {failure_count}× due to {label}. "
        f"Abort similar {ticker} setups in {regime} conditions — prefer SGOV instead."
    )

    # Append the most recent lesson text if it adds new information
    if latest_lesson and latest_lesson not in base:
        lesson_short = latest_lesson[:200].rstrip(".")
        base += f" Latest lesson: {lesson_short}."

    return base


# ── DB scan → rule promotion ────────────────────────────────────────────────

def rollup_permanent_rules(threshold: int = PROMOTION_THRESHOLD) -> dict:
    """
    Scan execution_post_mortems for recurring LOSS patterns.

    Groups rows by (ticker, regime, asset_class, exit_reason) where pnl_pct < 0.
    Any group with count >= threshold is promoted to a permanent rule via
    upsert_hardcoded_rule().

    Returns a summary dict:
      {
        "patterns_scanned": int,
        "rules_promoted": int,
        "rules_updated": int,
        "threshold": int,
      }
    """
    try:
        from db.postgres import get_conn, is_pg_available, upsert_hardcoded_rule
    except ImportError as exc:
        logger.warning(f"Rule engine | DB import failed: {exc}")
        return {"error": str(exc)}

    if not is_pg_available():
        logger.debug("Rule engine | PostgreSQL unavailable — skipping rollup")
        return {"skipped": True, "reason": "pg_unavailable"}

    # Fetch recurring loss patterns
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        ticker,
                        regime,
                        MAX(asset_class)          AS asset_class,
                        exit_reason,
                        COUNT(*)                  AS failure_count,
                        MAX(hardcoded_lesson_text) AS latest_lesson
                    FROM   execution_post_mortems
                    WHERE  pnl_pct < 0
                      AND  exit_reason IS NOT NULL
                      AND  exit_reason != 'unknown'
                    GROUP  BY ticker, regime, exit_reason
                    HAVING COUNT(*) >= %s
                    ORDER  BY failure_count DESC
                    """,
                    (threshold,),
                )
                rows = cur.fetchall()
    except Exception as exc:
        logger.error(f"Rule engine | Scan query failed: {exc}")
        return {"error": str(exc)}

    patterns_scanned = len(rows)
    rules_promoted   = 0
    rules_updated    = 0

    for row in rows:
        ticker, regime, asset_class, exit_reason, failure_count, latest_lesson = row

        rule_text = _generate_rule_text(
            ticker=ticker,
            regime=regime,
            asset_class=asset_class,
            exit_reason=exit_reason,
            failure_count=failure_count,
            latest_lesson=latest_lesson,
        )

        # Check whether this is a new rule or an update
        try:
            from db.postgres import get_hardcoded_rules
            existing = get_hardcoded_rules()
            key = (ticker, regime, exit_reason)
            is_new = not any(
                (r["ticker"], r["regime"], r["exit_reason"]) == key
                for r in existing
            )
        except Exception:
            is_new = True

        ok = upsert_hardcoded_rule(
            ticker=ticker,
            regime=regime,
            asset_class=asset_class,
            exit_reason=exit_reason,
            failure_count=failure_count,
            rule_text=rule_text,
        )

        if ok:
            if is_new:
                rules_promoted += 1
                logger.info(
                    f"Rule engine | NEW permanent rule promoted: "
                    f"{ticker} [{regime}/{exit_reason}] count={failure_count}"
                )
            else:
                rules_updated += 1
                logger.debug(
                    f"Rule engine | Rule updated: "
                    f"{ticker} [{regime}/{exit_reason}] count={failure_count}"
                )

    summary = {
        "patterns_scanned": patterns_scanned,
        "rules_promoted":   rules_promoted,
        "rules_updated":    rules_updated,
        "threshold":        threshold,
    }
    logger.info(
        f"Rule engine | Rollup complete — "
        f"patterns={patterns_scanned} promoted={rules_promoted} updated={rules_updated} "
        f"(threshold={threshold})"
    )
    return summary


# ── Prompt injection helper ─────────────────────────────────────────────────

def get_active_rules(regime: str | None = None) -> list[dict]:
    """
    Return active permanent rules from hardcoded_rules, optionally filtered
    by the current regime.  Regime-matched rules are returned first (they are
    most immediately relevant), followed by cross-regime rules.

    Returns [] if the table is empty or unavailable (non-fatal).
    """
    try:
        from db.postgres import get_hardcoded_rules, is_pg_available
        if not is_pg_available():
            return []

        if regime:
            # Regime-specific first, then any other active rules
            regime_rules  = get_hardcoded_rules(regime=regime)
            all_rules      = get_hardcoded_rules()
            regime_keys    = {(r["ticker"], r["regime"], r["exit_reason"]) for r in regime_rules}
            other_rules    = [
                r for r in all_rules
                if (r["ticker"], r["regime"], r["exit_reason"]) not in regime_keys
            ]
            return regime_rules + other_rules
        else:
            return get_hardcoded_rules()
    except Exception as exc:
        logger.warning(f"Rule engine | get_active_rules failed (non-fatal): {exc}")
        return []


def build_permanent_rules_block(regime: str | None = None) -> str:
    """
    Build the ==[PERMANENT RULES]== section for the LLM system prompt.
    Returns an empty string if no rules are active yet (fresh system).

    These rules are derived from >= {PROMOTION_THRESHOLD} identical failures
    and are injected into EVERY prompt — they cannot be overridden by the LLM.
    """
    rules = get_active_rules(regime=regime)
    if not rules:
        return ""

    lines = [
        f"\n\n=== PERMANENT RULES (DERIVED FROM {PROMOTION_THRESHOLD}+ CONFIRMED FAILURES) ===",
        "The following rules have been extracted from repeated observed failures.",
        "They are NON-NEGOTIABLE constraints — treat them with equal weight to the",
        "position-sizing hard cap. Do NOT override them regardless of current signals.\n",
    ]

    # Group by regime for readability
    current_regime_rules = [r for r in rules if r["regime"] == regime] if regime else []
    other_rules          = [r for r in rules if r not in current_regime_rules]

    if current_regime_rules:
        lines.append(f"▼ Rules active for the current {regime} regime:\n")
        for r in current_regime_rules:
            lines.append(f"  • {r['rule_text']}")
        lines.append("")

    if other_rules:
        lines.append("▼ Cross-regime rules (apply in any market condition):\n")
        for r in other_rules:
            lines.append(f"  • [{r['regime']}] {r['rule_text']}")
        lines.append("")

    logger.info(
        f"Rule engine | Injecting {len(rules)} permanent rule(s) into system prompt "
        f"(regime={regime}, current={len(current_regime_rules)}, cross={len(other_rules)})"
    )
    return "\n".join(lines)
