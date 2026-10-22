#!/usr/bin/env python3
"""Create and verify off-site custom-format PostgreSQL backups in App Storage."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import psycopg2

TABLES = (
    "bots_state",
    "alpaca_etf_positions",
    "kill_switch_events",
    "system_degradations",
    "platform_migrations",
    "reconciliation_log",
)
PREFIX = "backups/quant-terminal/"
RETENTION_DUMPS = 14   # two weeks of daily dumps (~2.8 MB each, Oct 2026)


def _storage_client():
    from replit.object_storage import Client

    bucket_id = os.environ.get("DEFAULT_OBJECT_STORAGE_BUCKET_ID")
    if not bucket_id:
        raise RuntimeError("DEFAULT_OBJECT_STORAGE_BUCKET_ID is not configured")
    return Client(bucket_id)


def _connection_parts(database_url: str) -> tuple[list[str], dict[str, str]]:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise ValueError("DATABASE_URL is not a PostgreSQL URL")
    query = parse_qs(parsed.query)
    args = [
        "--host", parsed.hostname,
        "--port", str(parsed.port or 5432),
        "--username", unquote(parsed.username or ""),
        "--dbname", unquote(parsed.path.lstrip("/")),
        "--no-password",
    ]
    env = os.environ.copy()
    env["PGPASSWORD"] = unquote(parsed.password or "")
    env["PGSSLMODE"] = query.get("sslmode", ["require"])[0]
    return args, env


def _source_snapshot(database_url: str):
    parsed = urlparse(database_url)
    params = parse_qs(parsed.query)
    conn = psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port or 5432,
        user=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
        dbname=unquote(parsed.path.lstrip("/")),
        sslmode=params.get("sslmode", ["require"])[0],
    )
    conn.set_session(
        isolation_level="REPEATABLE READ",
        readonly=True,
        autocommit=False,
    )
    with conn.cursor() as cur:
        cur.execute("SELECT pg_export_snapshot(), current_setting('server_version')")
        snapshot, server_version = cur.fetchone()
        counts = {}
        for table in TABLES:
            cur.execute(f'SELECT COUNT(*) FROM public."{table}"')
            counts[table] = int(cur.fetchone()[0])
    return conn, snapshot, server_version, counts


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _get_remote_size(storage: Any, object_name: str) -> int | None:
    getter = getattr(storage, "get_size", None)
    if getter:
        return getter(object_name)
    # The official SDK exposes object listing without size metadata. Use its
    # authenticated bucket handle to reload only the object's GCS metadata.
    handle = storage._Client__get_bucket_handle()
    blob = handle.blob(object_name)
    try:
        blob.reload()
    except Exception:
        return None
    return int(blob.size) if blob.size is not None else None


def _prune_old_dumps(storage: Any, prefix: str, new_dump: str, expected_size: int) -> list[str]:
    """Prune only after the just-uploaded dump is confirmed present and sized."""
    objects = storage.list(prefix=prefix)
    names = [obj.name for obj in objects if obj.name.endswith(".dump")]
    if new_dump not in names or _get_remote_size(storage, new_dump) != expected_size:
        return []
    names.sort()
    if len(names) <= RETENTION_DUMPS:
        return []
    removed: list[str] = []
    for old_name in names[:-RETENTION_DUMPS]:
        storage.delete(old_name)
        storage.delete(f"{old_name}.sha256", ignore_not_found=True)
        removed.append(old_name)
    return removed


def backup_once() -> dict[str, Any]:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        raise RuntimeError("pg_dump is not installed")

    storage = _storage_client()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    object_name = f"{PREFIX}{stamp}.dump"
    checksum_name = f"{object_name}.sha256"
    started = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="quant-terminal-backup-") as temp_dir:
        dump_path = Path(temp_dir) / "production.dump"
        manifest_path = Path(temp_dir) / "manifest.sha256"
        source_conn, snapshot, server_version, source_counts = _source_snapshot(database_url)
        try:
            pg_args, pg_env = _connection_parts(database_url)
            result = subprocess.run(
                [pg_dump, "--format=custom", f"--snapshot={snapshot}", "--file", str(dump_path), *pg_args],
                env=pg_env,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode:
                raise RuntimeError(f"pg_dump failed ({result.returncode}): {(result.stderr or result.stdout)[-3000:]}")
        finally:
            source_conn.rollback()
            source_conn.close()

        digest = _sha256_file(dump_path)
        dump_size = dump_path.stat().st_size
        manifest = {
            "object": object_name,
            "sha256": digest,
            "size_bytes": dump_size,
            "source_server_version": server_version,
            "source_counts": source_counts,
        }
        manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
        storage.upload_from_filename(object_name, str(dump_path))
        if _get_remote_size(storage, object_name) != dump_size:
            raise RuntimeError("uploaded dump is missing or its remote size does not match")
        storage.upload_from_filename(checksum_name, str(manifest_path))
        if not storage.exists(checksum_name):
            raise RuntimeError("uploaded SHA-256 manifest could not be confirmed")

        removed = _prune_old_dumps(storage, PREFIX, object_name, dump_size)
        return {
            **manifest,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "pruned": removed,
        }


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _run_checked(args: list[str], *, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(args, capture_output=True, text=True, env=env, check=False)
    if result.returncode:
        raise RuntimeError(f"{Path(args[0]).name} failed ({result.returncode}): {(result.stderr or result.stdout)[-3000:]}")


def verify_latest() -> dict[str, Any]:
    storage = _storage_client()
    dumps = sorted(obj.name for obj in storage.list(prefix=PREFIX) if obj.name.endswith(".dump"))
    if not dumps:
        raise RuntimeError("no backup dumps found in App Storage")
    object_name = dumps[-1]
    with tempfile.TemporaryDirectory(prefix="quant-terminal-restore-check-") as temp_dir:
        root = Path(temp_dir)
        dump_path = root / "backup.dump"
        manifest_path = root / "manifest.json"
        data_dir = root / "pgdata"
        storage.download_to_filename(object_name, str(dump_path))
        storage.download_to_filename(f"{object_name}.sha256", str(manifest_path))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        actual_digest = _sha256_file(dump_path)
        if actual_digest != manifest.get("sha256"):
            raise RuntimeError("backup SHA-256 does not match its sidecar")
        if dump_path.stat().st_size != int(manifest["size_bytes"]):
            raise RuntimeError("downloaded backup size does not match its sidecar")

        initdb = shutil.which("initdb")
        pg_ctl = shutil.which("pg_ctl")
        pg_restore = shutil.which("pg_restore")
        if not all((initdb, pg_ctl, pg_restore)):
            raise RuntimeError("initdb, pg_ctl, and pg_restore must be installed")
        user = os.environ.get("USER", "runner")
        port = _free_port()
        server_log = root / "postgres.log"
        _run_checked([initdb, "-D", str(data_dir), "-U", user, "--auth-local=trust", "--auth-host=trust"])
        server_started = False
        try:
            try:
                _run_checked([
                    pg_ctl, "-D", str(data_dir), "-l", str(server_log),
                    "-o", f"-h 127.0.0.1 -k {root} -p {port} -F", "-w", "start",
                ])
            except RuntimeError as exc:
                detail = server_log.read_text(encoding="utf-8", errors="replace")[-3000:] if server_log.exists() else ""
                raise RuntimeError(f"{exc}; local PostgreSQL log: {detail}") from exc
            server_started = True
            restore_env = os.environ.copy()
            restore_env.pop("PGPASSWORD", None)
            _run_checked([
                pg_restore, "--exit-on-error", "--no-owner", "--no-privileges",
                "--host", "127.0.0.1", "--port", str(port), "--username", user,
                "--dbname", "postgres", str(dump_path),
            ], env=restore_env)
            conn = psycopg2.connect(host="127.0.0.1", port=port, user=user, dbname="postgres")
            try:
                restored = {}
                with conn.cursor() as cur:
                    for table in TABLES:
                        cur.execute(f'SELECT COUNT(*) FROM public."{table}"')
                        restored[table] = int(cur.fetchone()[0])
            finally:
                conn.close()
        finally:
            if server_started:
                subprocess.run([pg_ctl, "-D", str(data_dir), "-m", "fast", "-w", "stop"], capture_output=True, text=True)

        source = manifest.get("source_counts", {})
        comparisons = {
            table: {"source": int(source[table]), "restored": restored[table], "match": int(source[table]) == restored[table]}
            for table in TABLES
        }
        if not all(row["match"] for row in comparisons.values()):
            raise RuntimeError(f"restored row counts differ: {comparisons}")
        return {"object": object_name, "sha256": actual_digest, "counts": comparisons}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", help="restore newest backup into a temporary local PostgreSQL and compare row counts")
    args = parser.parse_args()
    result = verify_latest() if args.verify else backup_once()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
