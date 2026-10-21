"""Which commit is this process running? One source of truth.

Reads BUILD_COMMIT at the repo root if the build stamped one, else asks git,
else returns "unknown". Published deployments have no .git, so without a stamp
the answer is "unknown" and callers must treat that as "cannot verify", not as
a mismatch.
"""

from __future__ import annotations

import os
import subprocess

UNKNOWN = "unknown"
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REPO_ROOT = os.path.dirname(_ROOT)


def current_commit() -> str:
    try:
        with open(os.path.join(_REPO_ROOT, "BUILD_COMMIT"), encoding="utf-8") as fh:
            stamp = fh.read().strip()[:12]
        if stamp:
            return stamp
    except OSError:
        pass
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_ROOT, stderr=subprocess.DEVNULL, timeout=3,
        ).decode().strip() or UNKNOWN
    except Exception:
        return UNKNOWN
