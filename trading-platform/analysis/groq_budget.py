"""
analysis/groq_budget.py  —  SHIM (Groq → Claude migration)
============================================================
Groq has been retired as the LLM provider.  All functionality is now
handled by ClaudeBudget in analysis/claude_budget.py.

This module re-exports every public symbol so that existing call-sites
(groq_client.py, routes/*, etc.) continue to work without modification
during the Task #67 backend migration.

DO NOT ADD NEW LOGIC HERE.  Update analysis/claude_budget.py instead.
"""

from analysis.claude_budget import ClaudeBudget as GroqBudget, budget  # noqa: F401

__all__ = ["GroqBudget", "budget"]
