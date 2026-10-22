"""Which commit is this process running? One source of truth.

Asks git first (the workspace), else reads BUILD_COMMIT at the repo root,
which the dashboard's production build stamps (published deployments have no
git), else returns "unknown". Callers must treat "unknown" as "cannot
verify", not as a mismatch.
"""

from __future__ import annotations

import os
import subprocess

UNKNOWN = "unknown"
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REPO_ROOT = os.path.dirname(_ROOT)


def current_commit() -> str:
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_ROOT, stderr=subprocess.DEVNULL, timeout=3,
        ).decode().strip()
        if head:
            return head
    except Exception:
        pass
    try:
        with open(os.path.join(_REPO_ROOT, "BUILD_COMMIT"), encoding="utf-8") as fh:
            stamp = fh.read().strip()[:7]
        return stamp or UNKNOWN
    except OSError:
        return UNKNOWN
