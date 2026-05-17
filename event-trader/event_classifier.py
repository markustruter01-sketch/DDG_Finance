"""Groq LLM classifier for event significance.

Reuses pattern from kraken-bot/jerome_investor.py:_call_groq().
Classifies events as LOW/MEDIUM/HIGH price impact.
Falls back to Gemini wrapper (trading-platform/analysis/groq_client)
if the Groq SDK fails with a proxies/environment error.
"""
import os
import sys
import logging
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))

logger = logging.getLogger("event-classifier")

GROQ_MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = (
    "You are a crypto market analyst. "
    "Respond with ONLY one word: HIGH, MEDIUM, or LOW. "
    "No explanation, no punctuation, just one word."
)


def _ensure_tp_path():
    tp = os.path.join(_HERE, '..', 'trading-platform')
    if tp not in sys.path:
        sys.path.insert(0, tp)


def classify_event(event: dict) -> Optional[str]:
    """Returns 'LOW' | 'MEDIUM' | 'HIGH' | None."""
    prompt = f"""Rate the likely PRICE IMPACT of this upcoming event on the affected cryptocurrency.

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

Respond with ONLY one word: HIGH, MEDIUM, or LOW."""

    groq_key = os.environ.get("GROQ_API_KEY", "")

    # Try Groq SDK first
    if groq_key:
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
            logger.warning(f"unexpected Groq output: {result!r}")
        except Exception as exc:
            logger.warning(f"Groq SDK failed ({exc}) — falling back to Gemini wrapper")

    # Fallback: Gemini wrapper (same interface as old Groq)
    try:
        _ensure_tp_path()
        from analysis.groq_client import call_groq
        raw = call_groq(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=prompt,
            temperature=0.1,
            max_tokens=10,
            call_type="event_classifier",
            json_mode=False,
        )
        result = raw.strip().upper()
        if result in ("HIGH", "MEDIUM", "LOW"):
            return result
        logger.warning(f"unexpected Gemini fallback output: {result!r}")
        return None
    except Exception as e:
        logger.error(f"event classification failed (both paths): {e}")
        return None
