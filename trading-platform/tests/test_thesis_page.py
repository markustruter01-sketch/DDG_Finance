"""The thesis page shows the thesis file word for word, and is up to date.

docs/plans/fund-thesis-2027.md is hashed into the lock record (roadmap v2, V2-23),
so the page built from it (scripts/thesis_page.py) must never reword it.
"""

from __future__ import annotations

import html
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("thesis_page", ROOT / "scripts" / "thesis_page.py")
tp = importlib.util.module_from_spec(SPEC)
sys.modules["thesis_page"] = tp          # dataclasses look the module up while it loads
SPEC.loader.exec_module(tp)

MD = tp.SOURCE.read_text(encoding="utf-8")


def visible_text(page: str) -> str:
    page = re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.S)
    page = re.sub(r"<[^>]+>", "", page)
    return re.sub(r"\s+", " ", html.unescape(page))


def squash(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def test_dashboard_page_is_built_from_the_current_thesis():
    on_disk = tp.DASHBOARD_OUT.read_text(encoding="utf-8")
    assert on_disk == tp.render(MD, "dashboard"), "run: python scripts/thesis_page.py dashboard"


def test_every_word_of_the_thesis_is_on_the_page():
    for variant in tp.VARIANTS:
        text = visible_text(tp.render(MD, variant))
        for b in tp.parse(MD):
            pieces = ([b.text] if b.text else []) + (b.items or []) + [c for r in (b.rows or []) for c in r]
            for piece in pieces:
                want = squash(tp.plain(piece))
                assert want in text, f"{variant}: missing or reworded: {want[:90]!r}"


def test_the_page_prints_the_source_hash():
    import hashlib
    digest = hashlib.sha256(MD.encode("utf-8")).hexdigest()
    for variant in tp.VARIANTS:
        assert digest in tp.render(MD, variant)


def test_the_54_calls_are_read_in_order_with_their_odds():
    calls = tp.calls(tp.parse(MD))
    assert [c.n for c in calls] == list(range(1, 55))
    assert all(0 < c.odds < 100 for c in calls)
    by_n = {c.n: c for c in calls}
    assert by_n[1].odds == 85 and by_n[26].odds == 25 and by_n[54].odds == 55   # spot checks against Part 7


def test_page_loads_nothing_but_fonts_and_its_own_files():
    for variant in tp.VARIANTS:
        page = tp.render(MD, variant)
        urls = re.findall(r'(?:src|href)="(https?://[^"]+)"', page)
        assert all(u.startswith(("https://fonts.googleapis.com", "https://fonts.gstatic.com")) for u in urls), urls
        assert "fetch(" not in page and "XMLHttpRequest" not in page
