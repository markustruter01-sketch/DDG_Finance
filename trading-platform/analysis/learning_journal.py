"""
LLM Learning Journal
---------------------
Extracts key insight sentences from every Groq LLM analysis output,
consolidates similar insights using Jaccard token-overlap (no extra API calls),
and persists a growing ledger of what the system has "learned" over time.

The top-confidence learnings are injected back into future LLM prompts via
feedback_injection.py, closing the learning loop.

Table: llm_learnings (PostgreSQL, see db/postgres.py)
"""

from __future__ import annotations

import re
import string
from datetime import datetime, timezone
from typing import Union

from loguru import logger

from analysis.schemas import RegimeAnalysisOutput, CryptoAnalysisOutput

# ── Stopword list (keeps word sets signal-rich) ────────────────────────────
_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "should",
    "could", "may", "might", "shall", "can", "need", "dare", "ought", "used",
    "to", "of", "in", "on", "at", "by", "for", "with", "about", "against",
    "between", "into", "through", "during", "before", "after", "above",
    "below", "from", "up", "down", "out", "off", "over", "under", "again",
    "further", "then", "once", "and", "or", "but", "if", "as", "until",
    "while", "this", "that", "these", "those", "it", "its", "which", "who",
    "whom", "what", "when", "where", "why", "how", "all", "both", "each",
    "few", "more", "most", "other", "some", "such", "no", "nor", "not",
    "only", "same", "so", "than", "too", "very", "just", "any", "our",
    "your", "their", "we", "i", "he", "she", "they", "you", "my", "his",
    "her", "its", "our", "also", "however", "currently", "given",
}

# Minimum token overlap for two insights to be considered the same
_JACCARD_THRESHOLD = 0.40
# Minimum tokens needed for a sentence to be considered an insight
_MIN_TOKENS = 6

# Category keyword mapping (first match wins)
_CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("crypto",    ["btc", "eth", "bitcoin", "ethereum", "crypto", "blockchain", "onchain", "altcoin"]),
    ("macro",     ["gdp", "fed", "federal", "inflation", "cpi", "unemployment", "yield", "treasury",
                   "interest", "rate", "recession", "growth", "fiscal", "monetary", "vix", "spread"]),
    ("momentum",  ["momentum", "trend", "moving", "average", "ma", "breakout", "bullish", "bearish",
                   "oversold", "overbought", "signal", "crossover", "rally", "pullback"]),
    ("risk",      ["risk", "stop", "loss", "drawdown", "volatility", "hedge", "downside", "protection",
                   "slippage", "liquidity", "tail", "worst", "crash", "correction"]),
    ("position",  ["position", "kelly", "allocation", "sizing", "weight", "slot", "capital",
                   "deploy", "diversif", "concentration", "cash", "sgov"]),
    ("macro",     ["market", "regime", "bull", "bear", "sideways", "sector", "rotation"]),  # fallback macro
]


def _clean_tokens(text: str) -> frozenset[str]:
    """Lowercase, strip punctuation, remove stopwords. Returns a frozenset of tokens."""
    text = text.lower()
    text = text.translate(str.maketrans("", "", string.punctuation))
    tokens = text.split()
    return frozenset(t for t in tokens if t not in _STOPWORDS and len(t) > 2)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard similarity between two token sets."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union > 0 else 0.0


def _categorize(text: str) -> str:
    """Assign a category tag based on keyword presence."""
    lower = text.lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(kw in lower for kw in keywords):
            return category
    return "macro"


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences. Handles abbreviations and decimal numbers."""
    text = text.strip()
    sentences = re.split(r'(?<=[.!?])\s+', text)
    out = []
    for s in sentences:
        s = s.strip()
        if s and not s.endswith("."):
            s = s.rstrip(".,;:") + "."
        if s:
            out.append(s)
    return out


def extract_insights(
    output: Union[RegimeAnalysisOutput, CryptoAnalysisOutput],
) -> list[tuple[str, str, str]]:
    """
    Extract (insight_text, regime, category) tuples from an LLM output.
    Sources: regime_rationale / market_regime + each allocation's thesis.
    Returns only sentences with enough distinct signal tokens.
    """
    results: list[tuple[str, str, str]] = []
    seen_texts: set[str] = set()

    if isinstance(output, RegimeAnalysisOutput):
        regime = output.regime
        rationale_text = getattr(output, "regime_rationale", "") or ""
        allocations = output.allocations or []
    else:
        regime = "Crypto"
        rationale_text = getattr(output, "market_regime", "") or ""
        allocations = output.allocations or []

    def _add(text: str, r: str) -> None:
        text = text.strip()
        if not text or text in seen_texts:
            return
        tokens = _clean_tokens(text)
        if len(tokens) < _MIN_TOKENS:
            return
        seen_texts.add(text)
        category = _categorize(text)
        results.append((text, r, category))

    for sentence in _split_sentences(rationale_text):
        _add(sentence, regime)

    for alloc in allocations:
        thesis = getattr(alloc, "thesis", "") or ""
        if thesis:
            for sentence in _split_sentences(thesis):
                _add(sentence, regime)

    return results


def consolidate_and_upsert(
    insight_text: str,
    regime: str,
    category: str,
) -> None:
    """
    Find an existing similar insight (same regime, Jaccard >= threshold) and
    increment its counter, or insert a new entry. Confidence score is a
    capped sigmoid on confirmed_count so it grows toward 1.0.
    """
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return

        new_tokens = _clean_tokens(insight_text)
        if not new_tokens:
            return

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, insight_text, confirmed_count
                    FROM llm_learnings
                    WHERE regime = %s
                    ORDER BY confirmed_count DESC
                    LIMIT 200
                    """,
                    (regime,),
                )
                rows = cur.fetchall()

            best_id: int | None = None
            best_sim: float = 0.0
            for row_id, row_text, _count in rows:
                sim = _jaccard(new_tokens, _clean_tokens(row_text))
                if sim > best_sim:
                    best_sim = sim
                    best_id = row_id

            with conn.cursor() as cur:
                if best_id is not None and best_sim >= _JACCARD_THRESHOLD:
                    cur.execute(
                        """
                        UPDATE llm_learnings
                        SET confirmed_count  = confirmed_count + 1,
                            last_seen        = NOW(),
                            confidence_score = LEAST(1.0, confirmed_count::double precision / (confirmed_count + 2.0) + 0.1)
                        WHERE id = %s
                        """,
                        (best_id,),
                    )
                    logger.debug(
                        f"LLM Journal | Merged insight (sim={best_sim:.2f}) into id={best_id}"
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO llm_learnings
                            (insight_text, regime, category, confidence_score)
                        VALUES (%s, %s, %s, 0.33)
                        """,
                        (insight_text, regime, category),
                    )
                    logger.debug(f"LLM Journal | New insight [{regime}/{category}]: {insight_text[:80]}")

    except Exception as exc:
        logger.warning(f"LLM Journal | consolidate_and_upsert error: {exc}")


def record_cycle_learnings(
    output: Union[RegimeAnalysisOutput, CryptoAnalysisOutput],
) -> None:
    """
    Main entry point — called after each successful LLM analysis cycle.
    Extracts all insights from the output and upserts them into the ledger.
    Never raises — always silent on failure so it cannot block trading.
    """
    try:
        insights = extract_insights(output)
        if not insights:
            logger.debug("LLM Journal | No extractable insights from this cycle")
            return
        for text, regime, category in insights:
            consolidate_and_upsert(text, regime, category)
        logger.info(f"LLM Journal | Processed {len(insights)} insight(s) from analysis cycle")
    except Exception as exc:
        logger.warning(f"LLM Journal | record_cycle_learnings failed (non-fatal): {exc}")


def get_journal_entries(
    regime: str | None = None,
    category: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """
    Return paginated journal entries sorted by confidence_score DESC.
    Optionally filter by regime or category.
    """
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return []

        conditions = []
        params: list = []
        if regime:
            conditions.append("regime = %s")
            params.append(regime)
        if category:
            conditions.append("category = %s")
            params.append(category)

        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(min(limit, 200))

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, insight_text, regime, category,
                           first_seen, last_seen,
                           confirmed_count, confidence_score
                    FROM llm_learnings
                    {where_clause}
                    ORDER BY confidence_score DESC, confirmed_count DESC
                    LIMIT %s
                    """,
                    params,
                )
                rows = cur.fetchall()

        return [
            {
                "id":              row[0],
                "insight_text":    row[1],
                "regime":          row[2],
                "category":        row[3],
                "first_seen":      row[4].isoformat() if row[4] else None,
                "last_seen":       row[5].isoformat() if row[5] else None,
                "confirmed_count": row[6],
                "confidence_score": round(row[7], 3),
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning(f"LLM Journal | get_journal_entries error: {exc}")
        return []


def get_top_learnings_for_prompt(
    limit: int = 10,
    crypto_only: bool = False,
) -> list[dict]:
    """
    Return the top learnings for injection into the LLM system prompt.
    If crypto_only, restrict to regime='Crypto'; otherwise exclude 'Crypto'.
    Only returns entries confirmed at least twice (confidence > 0.33).
    """
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            return []

        if crypto_only:
            regime_filter = "regime = 'Crypto'"
        else:
            regime_filter = "regime != 'Crypto'"

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT insight_text, regime, category, confirmed_count, confidence_score
                    FROM llm_learnings
                    WHERE {regime_filter}
                      AND confirmed_count >= 2
                    ORDER BY confidence_score DESC, confirmed_count DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()

        return [
            {
                "insight_text":    row[0],
                "regime":          row[1],
                "category":        row[2],
                "confirmed_count": row[3],
                "confidence_score": round(row[4], 3),
            }
            for row in rows
        ]
    except Exception as exc:
        logger.warning(f"LLM Journal | get_top_learnings_for_prompt error: {exc}")
        return []
