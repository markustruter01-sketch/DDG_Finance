"""
Learning Snapshot — cross-deploy knowledge persistence
-------------------------------------------------------
Solves the "learning stays in dev" problem.

On every deploy, the production database starts empty.  This module:
  1. export_snapshot()  — writes all llm_learnings rows +  Kraken adaptive
                          params to  data/learning_snapshot.json  (committed
                          to the repo so it travels with every deploy).
  2. seed_from_snapshot() — called at startup.  If llm_learnings is empty,
                            seeds from the snapshot so production always starts
                            with accumulated dev knowledge, not from zero.

The snapshot is deliberately human-readable JSON so you can inspect what
the bots have learned before you ship it to production.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Any

from loguru import logger

_SNAPSHOT_PATH = pathlib.Path(__file__).parent.parent / "data" / "learning_snapshot.json"
_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)


# ── Export ────────────────────────────────────────────────────────────────────

def export_snapshot() -> dict[str, Any]:
    """
    Dump all llm_learnings rows + Kraken adaptive_params to
    data/learning_snapshot.json.  Returns a summary dict.
    """
    snapshot: dict[str, Any] = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "llm_learnings": [],
        "kraken_adaptive_params": None,
    }

    # ── 1. LLM learnings ──────────────────────────────────────────────────────
    try:
        from db.postgres import get_conn, is_pg_available
        if is_pg_available():
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT insight_text, regime, category,
                               first_seen, last_seen,
                               confirmed_count, confidence_score
                        FROM llm_learnings
                        ORDER BY confidence_score DESC, confirmed_count DESC
                        """
                    )
                    rows = cur.fetchall()

            snapshot["llm_learnings"] = [
                {
                    "insight_text":     r[0],
                    "regime":           r[1],
                    "category":         r[2],
                    "first_seen":       r[3].isoformat() if r[3] else None,
                    "last_seen":        r[4].isoformat() if r[4] else None,
                    "confirmed_count":  r[5],
                    "confidence_score": round(r[6], 4),
                }
                for r in rows
            ]
            logger.info(
                f"Learning Snapshot | Exported {len(snapshot['llm_learnings'])} "
                "llm_learnings rows"
            )
    except Exception as exc:
        logger.warning(f"Learning Snapshot | llm_learnings export failed: {exc}")

    # ── 2. Kraken adaptive params (from JSON file) ────────────────────────────
    try:
        import pathlib as _pl
        kraken_params_path = (
            pathlib.Path(__file__).parent.parent.parent / "kraken-bot" / "adaptive_params.json"
        )
        if kraken_params_path.exists():
            snapshot["kraken_adaptive_params"] = json.loads(kraken_params_path.read_text())
            logger.info("Learning Snapshot | Exported Kraken adaptive_params")
    except Exception as exc:
        logger.warning(f"Learning Snapshot | kraken_adaptive_params export failed: {exc}")

    # ── 3. Write to disk ──────────────────────────────────────────────────────
    try:
        _SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, default=str))
        logger.success(
            f"Learning Snapshot | Saved to {_SNAPSHOT_PATH} "
            f"({len(snapshot['llm_learnings'])} learnings)"
        )
    except Exception as exc:
        logger.error(f"Learning Snapshot | Write failed: {exc}")

    return {
        "status": "ok",
        "llm_learnings_count": len(snapshot["llm_learnings"]),
        "kraken_params_exported": snapshot["kraken_adaptive_params"] is not None,
        "path": str(_SNAPSHOT_PATH),
        "exported_at": snapshot["exported_at"],
    }


# ── Seed ──────────────────────────────────────────────────────────────────────

def seed_from_snapshot() -> dict[str, Any]:
    """
    If llm_learnings table is empty AND data/learning_snapshot.json exists,
    seed the DB from the snapshot.  Safe to call at every startup — does
    nothing if the table already has rows.
    """
    result = {
        "seeded": False,
        "rows_inserted": 0,
        "kraken_params_restored": False,
        "reason": "",
    }

    if not _SNAPSHOT_PATH.exists():
        result["reason"] = "no snapshot file found"
        return result

    # ── Check if llm_learnings already has data ───────────────────────────────
    try:
        from db.postgres import get_conn, is_pg_available
        if not is_pg_available():
            result["reason"] = "PostgreSQL unavailable"
            return result

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM llm_learnings")
                existing = cur.fetchone()[0]

        if existing > 0:
            result["reason"] = f"table already has {existing} rows — skipping seed"
            logger.debug(f"Learning Snapshot | Seed skipped: {existing} rows already present")
            return result

    except Exception as exc:
        result["reason"] = f"DB check failed: {exc}"
        logger.warning(f"Learning Snapshot | Pre-seed check failed: {exc}")
        return result

    # ── Load snapshot ─────────────────────────────────────────────────────────
    try:
        snapshot = json.loads(_SNAPSHOT_PATH.read_text())
    except Exception as exc:
        result["reason"] = f"snapshot parse failed: {exc}"
        logger.error(f"Learning Snapshot | Snapshot file unreadable: {exc}")
        return result

    learnings = snapshot.get("llm_learnings", [])

    if not learnings:
        result["reason"] = "snapshot has no llm_learnings rows"
        return result

    # ── Insert rows ───────────────────────────────────────────────────────────
    inserted = 0
    try:
        from db.postgres import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                for row in learnings:
                    cur.execute(
                        """
                        INSERT INTO llm_learnings
                            (insight_text, regime, category,
                             first_seen, last_seen,
                             confirmed_count, confidence_score)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (
                            row["insight_text"],
                            row["regime"],
                            row["category"],
                            row.get("first_seen"),
                            row.get("last_seen"),
                            row.get("confirmed_count", 1),
                            row.get("confidence_score", 0.33),
                        ),
                    )
                    inserted += 1
        logger.success(
            f"Learning Snapshot | Seeded {inserted} llm_learnings rows from snapshot "
            f"(exported {snapshot.get('exported_at', 'unknown')})"
        )
        result["seeded"] = True
        result["rows_inserted"] = inserted
    except Exception as exc:
        result["reason"] = f"insert failed: {exc}"
        logger.error(f"Learning Snapshot | Seed insert failed: {exc}")
        return result

    # ── Restore Kraken params if file is still at defaults ────────────────────
    try:
        kraken_params_path = (
            pathlib.Path(__file__).parent.parent.parent / "kraken-bot" / "adaptive_params.json"
        )
        snap_params = snapshot.get("kraken_adaptive_params")
        if snap_params and kraken_params_path.exists():
            current = json.loads(kraken_params_path.read_text())
            snap_n = snap_params.get("metrics", {}).get("n", 0)
            current_n = current.get("metrics", {}).get("n", 0)
            if snap_n > current_n:
                kraken_params_path.write_text(json.dumps(snap_params, indent=2))
                result["kraken_params_restored"] = True
                logger.success(
                    f"Learning Snapshot | Restored Kraken adaptive_params "
                    f"(snapshot n={snap_n} > current n={current_n})"
                )
    except Exception as exc:
        logger.warning(f"Learning Snapshot | Kraken params restore failed: {exc}")

    return result


# ── Snapshot stats ────────────────────────────────────────────────────────────

def get_snapshot_info() -> dict[str, Any]:
    """Return metadata about the current snapshot file without loading all rows."""
    if not _SNAPSHOT_PATH.exists():
        return {
            "status":        "not_found",
            "exists":        False,
            "message":       "No snapshot file — use Export Snapshot to create one.",
        }
    try:
        snapshot  = json.loads(_SNAPSHOT_PATH.read_text())
        file_size = _SNAPSHOT_PATH.stat().st_size
        return {
            "status":                "ok",
            "exists":                True,
            "exported_at":           snapshot.get("exported_at"),
            "llm_learnings_count":   len(snapshot.get("llm_learnings", [])),
            "has_kraken_params":     snapshot.get("kraken_adaptive_params") is not None,
            "kraken_params_n":       (
                snapshot.get("kraken_adaptive_params", {}) or {}
            ).get("metrics", {}).get("n", 0),
            "file_size_bytes":       file_size,
            "path":                  str(_SNAPSHOT_PATH),
        }
    except Exception as exc:
        return {"status": "error", "exists": True, "error": str(exc)}
