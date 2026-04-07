"""
analysis/groq_budget.py  —  SHIM (Groq → Claude migration)
============================================================
Groq has been retired as the LLM provider.  All budget tracking and
throttle logic is now handled by ClaudeBudget in analysis/claude_budget.py.

This shim re-exports every public symbol so that existing call-sites
(analysis/groq_client.py, routes/*, etc.) continue to work unchanged
during the Task #67 backend migration sweep.

DO NOT add new logic here.  Work in analysis/claude_budget.py instead.
"""

from analysis.claude_budget import ClaudeBudget, budget  # noqa: F401

GroqBudget = ClaudeBudget

__all__ = ["GroqBudget", "ClaudeBudget", "budget"]
