"""
analysis/claude_client.py  —  Anthropic Claude LLM Client
==========================================================
Sole LLM provider for the trading platform.  Replaces Groq (Llama-3.3-70B)
and Gemini with Claude.

Model routing (via settings)
-----------------------------
  smart=True  → settings.claude_model_smart  (claude-sonnet-4-6 by default)
               High-stakes calls: regime analysis, fleet commander, self-critic
               audit, fleet chat.
  smart=False → settings.claude_model_fast   (claude-haiku-4-5 by default)
               Default model. Fast + cheap: commentary, learning journal,
               feedback injection.

JSON enforcement
----------------
Claude has no native JSON mode.  With expect_json=True (default):
  1. Strict preamble prepended to system_prompt: must start with { and end with }.
  2. Two-stage extraction on the response:
       Stage 1 — direct json.loads()
       Stage 2 — regex \\{.*\\} with re.DOTALL
       Stage 3 — raise RuntimeError (never silently return malformed data)

Retry behavior
--------------
  RateLimitError          → up to 3 retries, backoff 1s / 2s / 4s, then re-raise.
  APIStatusError (5xx)    → same 3-retry policy.
  All other APIError      → re-raise immediately as RuntimeError.

Usage
-----
    from analysis.claude_client import call_claude

    raw = call_claude(
        system_prompt="You are a senior quant...",
        user_prompt=data_payload,
        call_type="regime",
        expect_json=True,   # default
        smart=False,        # default — Haiku; set True for Sonnet
    )
    data = json.loads(raw)  # guaranteed valid JSON when expect_json=True
"""

from __future__ import annotations

import json
import re
import time

import anthropic
from loguru import logger

from config.settings import settings
from analysis.claude_budget import budget as _budget

_JSON_PREAMBLE = (
    "You MUST respond with a valid JSON object only. "
    "Your response MUST start with { and end with }. "
    "No markdown fences, no prose, no explanation outside the JSON object."
)

_RETRY_WAITS: list[float] = [1.0, 2.0, 4.0]

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


def _extract_json(raw: str) -> str:
    """
    Two-stage JSON extractor with strict boundary enforcement.

    Stage 1: direct json.loads — handles clean responses.
    Stage 2: regex \\{.*\\} with DOTALL — strips surrounding prose.
    Stage 3: RuntimeError — never silently return malformed data.
    """
    text = raw.strip()

    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        candidate = match.group(0)
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    raise RuntimeError(
        f"Claude returned non-JSON response (first 200 chars): {text[:200]}"
    )


def call_claude(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    call_type: str = "unknown",
    expect_json: bool = True,
    smart: bool = False,
) -> str:
    """
    Call Claude and return the response text.

    Parameters
    ----------
    system_prompt : str
        System-level instruction for Claude.
    user_prompt : str
        User message / data payload.
    temperature : float
        Sampling temperature (0.0–1.0).
    max_tokens : int
        Maximum completion tokens.
    call_type : str
        Budget tracking label (e.g. "regime", "commentary", "audit").
    expect_json : bool
        Default True.  Prepends strict JSON preamble to system_prompt and
        runs two-stage JSON extraction.  Return value is guaranteed valid JSON
        or a RuntimeError is raised.
    smart : bool
        Default False (Haiku — fast/cheap).
        True → settings.claude_model_smart (Sonnet — high-stakes calls).

    Returns
    -------
    str
        Raw text response (or extracted JSON string when expect_json=True).

    Raises
    ------
    RuntimeError
        On API failure or (when expect_json=True) unparseable response.
    """
    client  = _get_client()
    model   = settings.claude_model_smart if smart else settings.claude_model_fast
    system  = f"{_JSON_PREAMBLE}\n\n{system_prompt}" if expect_json else system_prompt

    logger.info(
        f"Claude | Sending request [{call_type}] model={model} "
        f"temp={temperature} max_tokens={max_tokens} expect_json={expect_json}"
    )

    last_exc: Exception | None = None

    for attempt, wait in enumerate([None] + _RETRY_WAITS):
        if wait is not None:
            logger.warning(
                f"Claude | [{call_type}] retry {attempt}/{len(_RETRY_WAITS)} "
                f"after {wait}s (prev: {last_exc})"
            )
            time.sleep(wait)

        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except anthropic.RateLimitError as exc:
            last_exc = exc
            if attempt < len(_RETRY_WAITS):
                continue
            logger.error(
                f"Claude | [{call_type}] RateLimitError after {attempt + 1} attempts: {exc}"
            )
            raise RuntimeError(f"Claude RateLimitError after retries: {exc}") from exc
        except anthropic.APIStatusError as exc:
            last_exc = exc
            if exc.status_code >= 500 and attempt < len(_RETRY_WAITS):
                continue
            logger.error(
                f"Claude | [{call_type}] APIStatusError HTTP {exc.status_code}: {exc}"
            )
            raise RuntimeError(f"Claude APIStatusError {exc.status_code}: {exc}") from exc
        except anthropic.APIError as exc:
            logger.error(f"Claude | [{call_type}] APIError: {exc}")
            raise RuntimeError(f"Claude APIError: {exc}") from exc
        except Exception as exc:
            logger.error(f"Claude | [{call_type}] Unexpected error: {exc}")
            raise RuntimeError(f"Claude call failed: {exc}") from exc

        content       = response.content[0].text
        input_tokens  = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        total_tokens  = input_tokens + output_tokens

        logger.info(
            f"Claude | Response received [{call_type}] model={model} — "
            f"prompt_tokens={input_tokens} completion_tokens={output_tokens} "
            f"total={total_tokens}"
        )

        _budget.consume(total_tokens, call_type=call_type)

        if expect_json:
            return _extract_json(content)

        return content

    raise RuntimeError(f"Claude | [{call_type}] exhausted all retries")
