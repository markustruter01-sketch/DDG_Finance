"""
News Payload Input Sanitizer
-----------------------------
Reduces LLM token consumption by stripping noise from news headlines
before they are injected into the Groq user prompt.

Operations (applied in order):
  1. Strip description suffix  — removes " — <description>" appended in news_client.py
  2. Remove [Removed] articles — catches any that slipped past news_client.py filter
  3. Deduplicate by title fingerprint — first 8 significant words, case-normalised
  4. Cap total headlines        — defaults to 15 (configurable)

Estimated token savings: ~40-60% of news section (descriptions alone add 30-80 tokens
per article; 25 articles × 50 tokens = ~1,250 tokens per cycle).
"""

import re
from loguru import logger


_STOP_WORDS = frozenset({
    "the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or",
    "is", "are", "was", "were", "be", "been", "its", "it", "this", "that",
    "as", "by", "with", "from", "will", "has", "have", "had", "not",
})

_CATEGORY_PREFIX_RE = re.compile(r"^\[[A-Z]+\]\s*")
_REMOVED_RE = re.compile(r"\[Removed\]", re.IGNORECASE)


def _title_fingerprint(headline: str) -> str:
    """Return a dedup key: first 8 non-stop-word tokens, lower-cased."""
    raw = _CATEGORY_PREFIX_RE.sub("", headline)
    raw = raw.split(" — ")[0]
    tokens = [
        t.lower().strip(".,!?\"';:-")
        for t in raw.split()
        if t.lower().strip(".,!?\"';:-") and t.lower().strip(".,!?\"';:-") not in _STOP_WORDS
    ]
    return " ".join(tokens[:8])


def _strip_description(headline: str) -> str:
    """
    Remove the description part appended by news_client.py.
    Input:  '[MACRO] Fed holds rates — Central bank keeps benchmark unchanged at 5.25%'
    Output: '[MACRO] Fed holds rates'
    """
    match = _CATEGORY_PREFIX_RE.match(headline)
    prefix = match.group(0) if match else ""
    body = headline[len(prefix):]
    title_only = body.split(" — ")[0].strip()
    return f"{prefix}{title_only}"


def sanitize_news_payload(
    headlines: list[str],
    cap: int = 15,
) -> list[str]:
    """
    Sanitize a raw list of news headlines for LLM injection.

    Args:
        headlines: Raw headlines from news_client.fetch_news()['all_headlines'].
                   Each item may include a description suffix and a [CATEGORY] prefix.
        cap:       Maximum number of headlines to return. Defaults to 15.

    Returns:
        Deduplicated, description-stripped, capped list of headlines.
    """
    raw_count = len(headlines)
    seen_fingerprints: set[str] = set()
    result: list[str] = []

    for headline in headlines:
        if _REMOVED_RE.search(headline):
            continue

        clean = _strip_description(headline)

        fp = _title_fingerprint(clean)
        if fp in seen_fingerprints:
            continue

        seen_fingerprints.add(fp)
        result.append(clean)

        if len(result) >= cap:
            break

    removed = raw_count - len(result)
    logger.debug(
        f"InputSanitizer | news: {raw_count} raw → {len(result)} clean "
        f"({removed} removed: dupes/descriptions/removed)"
    )
    return result
