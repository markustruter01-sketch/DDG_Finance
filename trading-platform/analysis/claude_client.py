"""
analysis/claude_client.py  —  Anthropic Claude LLM Client
==========================================================
Sole LLM provider for the trading platform.  Replaces Groq (Llama-3.3-70B)
and Gemini with Claude.

Model routing
-------------
  SONNET  (claude-sonnet-4-6)  — regime analysis, fleet commander, self-critic
                                  audit, fleet chat.  High reasoning quality.
  HAIKU   (claude-haiku-4-5)   — commentary, learning journal, feedback
                                  injection.  Fast + cheap for high-frequency calls.

JSON enforcement
----------------
Claude has no native JSON mode (unlike Groq/Gemini).  Every call that needs
structured output MUST:
  1. Prepend "Respond with ONLY valid JSON. No markdown fences, no explanation."
     to the system_prompt (done automatically by call_claude when json_mode=True).
  2. Use two-stage extraction on the response:
       Stage 1 — direct json.loads()
       Stage 2 — regex r'\\{.*\\}' with re.DOTALL
       Stage 3 — raise RuntimeError (never silently swallow bad output)

Usage
-----
    from analysis.claude_client import call_claude, SONNET, HAIKU

    raw = call_claude(
        system_prompt="...",
        user_prompt="...",
        model=SONNET,
        max_tokens=4096,
        call_type="regime",
        json_mode=True,
    )
    data = json.loads(raw)   # guaranteed valid JSON when json_mode=True
"""

from __future__ import annotations

import json
import re

import anthropic
from loguru import logger

from config.settings import settings
from analysis.claude_budget import budget as _budget

SONNET = "claude-sonnet-4-6"
HAIKU  = "claude-haiku-4-5"

_JSON_PREAMBLE = (
    "Respond with ONLY valid JSON. "
    "No markdown fences, no prose, no explanation — just the JSON object."
)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


def _extract_json(raw: str) -> str:
    """
    Two-stage JSON extractor.

    Stage 1: direct json.loads — handles clean responses.
    Stage 2: regex \\{.*\\} with DOTALL — handles responses with leading/trailing prose.
    Stage 3: RuntimeError — never silently return malformed data.
    """
    text = raw.strip()

    # Stage 1: direct parse
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass

    # Stage 2: regex extraction
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
    model: str = SONNET,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    call_type: str = "unknown",
    json_mode: bool = False,
) -> str:
    """
    Call Claude and return the response text.

    Parameters
    ----------
    system_prompt : str
        System-level instruction for Claude.
    user_prompt : str
        User message / data payload.
    model : str
        SONNET or HAIKU.  Defaults to SONNET.
    temperature : float
        Sampling temperature (0.0–1.0).
    max_tokens : int
        Maximum completion tokens.
    call_type : str
        Budget tracking label (e.g. "regime", "commentary", "audit").
    json_mode : bool
        When True, prepends the JSON preamble to system_prompt and runs
        two-stage JSON extraction before returning.  The return value is
        guaranteed to be valid JSON or a RuntimeError is raised.

    Returns
    -------
    str
        Raw text response (or extracted JSON string when json_mode=True).

    Raises
    ------
    RuntimeError
        On API failure or (when json_mode=True) unparseable response.
    """
    client = _get_client()

    effective_system = (
        f"{_JSON_PREAMBLE}\n\n{system_prompt}" if json_mode else system_prompt
    )

    logger.info(
        f"Claude | Sending request [{call_type}] model={model} "
        f"temp={temperature} max_tokens={max_tokens} json_mode={json_mode}"
    )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=effective_system,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except anthropic.APIError as exc:
        logger.error(f"Claude | API error [{call_type}]: {exc}")
        raise RuntimeError(f"Claude API call failed: {exc}") from exc
    except Exception as exc:
        logger.error(f"Claude | Unexpected error [{call_type}]: {exc}")
        raise RuntimeError(f"Claude API call failed: {exc}") from exc

    content = response.content[0].text
    usage   = response.usage

    prompt_tokens     = usage.input_tokens
    completion_tokens = usage.output_tokens
    total_tokens      = prompt_tokens + completion_tokens

    logger.info(
        f"Claude | Response received [{call_type}] model={model} — "
        f"input={prompt_tokens} output={completion_tokens} total={total_tokens}"
    )

    _budget.consume(total_tokens, call_type=call_type)

    if json_mode:
        return _extract_json(content)

    return content
