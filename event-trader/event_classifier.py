"""Groq LLM classifier for event significance.

Reuses pattern from kraken-bot/jerome_investor.py:_call_groq().
Classifies events as LOW/MEDIUM/HIGH price impact.
"""
import os
import logging
from typing import Optional

logger = logging.getLogger("event-classifier")

GROQ_MODEL = "llama-3.3-70b-versatile"


def classify_event(event: dict) -> Optional[str]:
    """Returns 'LOW' | 'MEDIUM' | 'HIGH' | None."""
    prompt = f"""You are a crypto market analyst. Rate the likely PRICE IMPACT
of this upcoming event on the affected cryptocurrency.

Event: {event['title']}
Asset: {event['asset']}
Category: {event['category']}
Description: {event.get('description', 'N/A')}
Date: {event['date']}

Consider:
- Whether the market typically prices in this type of event
- Magnitude of historical similar events
- Asset-specific sensitivity
- Whether outcome is likely a surprise or already known

Respond with ONLY one word: HIGH, MEDIUM, or LOW.
No explanation, no punctuation, just one word."""

    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        logger.warning("GROQ_API_KEY not set, classifier disabled")
        return None

    try:
        from groq import Groq
        client = Groq(api_key=groq_key)
        resp = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
            temperature=0.1,
        )
        result = resp.choices[0].message.content.strip().upper()
        if result in ("HIGH", "MEDIUM", "LOW"):
            return result
        logger.warning(f"unexpected classifier output: {result!r}")
        return None
    except Exception as e:
        logger.error(f"groq classification failed: {e}")
        return None
