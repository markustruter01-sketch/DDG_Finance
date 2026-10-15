"""Reproducible daily-bar store.

A dataset is a folder of one CSV per symbol plus manifest.json recording the
source, when it was fetched, and a SHA-256 per file. Loading re-checks every
hash, so a silently changed file fails loudly instead of changing a result.
Every load is a window: explicit dates, a named dataset, a manifest hash.

Data lives outside git (default .local/research_data) because vendor data is
large and licensed; the manifest hash recorded in the ledger is what makes a
result re-runnable.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from research_harness.harness.holdout import check_window

DEFAULT_ROOT = Path(os.environ.get("QT_RESEARCH_DATA", ".local/research_data"))
BASE_FIELDS = ("day", "open", "high", "low", "close")


class DataIntegrityError(RuntimeError):
    """A dataset file does not match its manifest."""


def _csv_bytes(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(fields)
    for row in rows:
        writer.writerow(
            [row["day"].isoformat() if f == "day" else repr(float(row[f])) for f in fields]
        )
    return buf.getvalue().encode()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class BarStore:
    def __init__(self, root: Path | str = DEFAULT_ROOT) -> None:
        self.root = Path(root)

    # ── writing ──────────────────────────────────────────────────────────────
    def write_dataset(
        self,
        dataset: str,
        *,
        source: str,
        bars_by_symbol: dict[str, Iterable[dict[str, Any]]],
        fields: tuple[str, ...] = BASE_FIELDS,
        positive_fields: tuple[str, ...] | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        """Write an immutable dataset. Prices must be > 0; pass
        positive_fields=() for series that may be zero (interest rates)."""
        if fields[0] != "day":
            raise ValueError("first field must be 'day'")
        positive = fields[1:] if positive_fields is None else positive_fields
        folder = self.root / dataset
        if folder.exists():
            raise FileExistsError(f"dataset {dataset} already exists; datasets are immutable")
        # Build in a temp folder and rename at the end, so a failed pull never
        # leaves a half-written dataset that blocks the name forever.
        final, folder = folder, self.root / f".{dataset}.partial"
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        symbols: dict[str, Any] = {}
        for symbol, bars in sorted(bars_by_symbol.items()):
            rows = sorted(bars, key=lambda r: r["day"])
            days = [r["day"] for r in rows]
            if len(days) != len(set(days)):
                raise ValueError(f"{symbol}: duplicate days")
            for r in rows:
                for f in fields[1:]:
                    v = float(r[f])
                    if v != v or (f in positive and v <= 0):  # NaN, or non-positive price
                        raise ValueError(f"{symbol} {r['day']}: bad {f}={r[f]!r}")
            data = _csv_bytes(rows, fields)
            (folder / f"{symbol}.csv").write_bytes(data)
            symbols[symbol] = {
                "rows": len(rows),
                "first": days[0].isoformat() if days else None,
                "last": days[-1].isoformat() if days else None,
                "sha256": _sha(data),
            }
        manifest = {
            "dataset": dataset,
            "source": source,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "fields": list(fields),
            "notes": notes,
            "symbols": symbols,
        }
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
        folder.rename(final)
        return manifest

    # ── reading ──────────────────────────────────────────────────────────────
    def manifest(self, dataset: str) -> dict[str, Any]:
        path = self.root / dataset / "manifest.json"
        if not path.exists():
            raise FileNotFoundError(f"no dataset {dataset} under {self.root}")
        return json.loads(path.read_text())

    def manifest_hash(self, dataset: str) -> str:
        return _sha((self.root / dataset / "manifest.json").read_bytes())

    def load(
        self,
        dataset: str,
        symbol: str,
        *,
        start: date,
        end: date,
        registration_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Bars with start <= day <= end. Refuses held-out reads unless registered."""
        check_window(end, registration_id)
        meta = self.manifest(dataset)
        entry = meta["symbols"].get(symbol)
        if entry is None:
            raise KeyError(f"{symbol} not in dataset {dataset}")
        data = (self.root / dataset / f"{symbol}.csv").read_bytes()
        if _sha(data) != entry["sha256"]:
            raise DataIntegrityError(f"{dataset}/{symbol}.csv does not match its manifest")
        reader = csv.DictReader(io.StringIO(data.decode()))
        out = []
        for row in reader:
            day = date.fromisoformat(row["day"])
            if start <= day <= end:
                out.append({"day": day, **{k: float(v) for k, v in row.items() if k != "day"}})
        return out

    def load_rates(
        self,
        dataset: str,
        series: str,
        *,
        start: date,
        end: date,
        registration_id: str | None = None,
    ) -> dict[date, float]:
        """An annual-rate series (decimal, e.g. 0.05) as {day: rate}."""
        rows = self.load(dataset, series, start=start, end=end, registration_id=registration_id)
        return {r["day"]: r["rate"] for r in rows}
