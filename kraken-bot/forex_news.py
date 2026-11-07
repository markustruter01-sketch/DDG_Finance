"""Forex news desk: free, public headlines for the AI council, once a day.

Sources are official central-bank press feeds (RSS/Atom) and the GDELT news
index. Every source is optional: a source that fails is recorded with a short
reason and simply left out, so the council never waits on the news.

Safety (same rules as the council):
- HTTPS GET only, plain httpx, hard-coded host allowlist, no redirects,
  size-capped responses, no keys (all sources are public).
- Headlines are untrusted text. They are stripped to plain text (no links,
  markup or long tokens), capped in length and count, and passed to the models
  as data. The models' replies stay schema-checked, and the risk officer sizes
  every trade, so a misleading headline can at most cause a normal-size trade.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from urllib.parse import quote, urlparse

import httpx

TIMEOUT_SECONDS = 20.0
MAX_BYTES = 2_000_000
USER_AGENT = "ddg-forex-news/1.0"
MAX_AGE_HOURS = 72
PER_SOURCE = 6
GLOBAL_LIMIT = 15
MAX_HEADLINES = 40
TITLE_MAX_CHARS = 180

# One entry per source: (name, currency it speaks for or "global", URL).
CENTRAL_BANK_FEEDS: tuple[tuple[str, str, str], ...] = (
    ("Federal Reserve", "USD", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("European Central Bank", "EUR", "https://www.ecb.europa.eu/rss/press.xml"),
    ("Bank of England", "GBP", "https://www.bankofengland.co.uk/rss/news"),
    ("Bank of Japan", "JPY", "https://www.boj.or.jp/en/rss/whatsnew.xml"),
    ("Reserve Bank of Australia", "AUD", "https://www.rba.gov.au/rss/rss-cb-media-releases.xml"),
    ("Bank of Canada", "CAD", "https://www.bankofcanada.ca/content_type/press-releases/feed/"),
    ("Swiss National Bank", "CHF", "https://www.snb.ch/public/en/rss/pressrel"),
    ("Reserve Bank of New Zealand", "NZD", "https://www.rbnz.govt.nz/feeds/news"),
)
GDELT_QUERY = (
    '("central bank" OR "interest rate" OR inflation OR "currency" OR "exchange rate" '
    'OR tariff OR recession OR "jobs report") sourcelang:english'
)
GDELT_URL = (
    "https://api.gdeltproject.org/api/v2/doc/doc?mode=artlist&format=json&maxrecords=50"
    "&timespan=24h&sort=hybridrel&query=" + quote(GDELT_QUERY)
)

ALLOWED_HOSTS = frozenset(
    {urlparse(url).hostname for _, _, url in CENTRAL_BANK_FEEDS} | {urlparse(GDELT_URL).hostname}
)

Fetch = Callable[[str], bytes]


class NewsError(RuntimeError):
    """A source failed; the message is safe to log."""


def _http_get(url: str) -> bytes:
    if urlparse(url).hostname not in ALLOWED_HOSTS or not url.startswith("https://"):
        raise NewsError("host not on the allowlist")
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False,
                          headers={"User-Agent": USER_AGENT}) as client:
            response = client.get(url)
    except Exception as exc:
        raise NewsError(f"request failed ({type(exc).__name__})") from None
    if response.status_code != 200:
        raise NewsError(f"HTTP {response.status_code}")
    if len(response.content) > MAX_BYTES:
        raise NewsError("response too large")
    return response.content


_TAGS = re.compile(r"<[^>]*>")
_LINKS = re.compile(r"(https?://\S+|www\.\S+)", re.IGNORECASE)
_LONG = re.compile(r"[A-Za-z0-9+/=_\-]{40,}")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_SPACE = re.compile(r"\s+")


def clean_title(value: Any) -> str:
    """Plain text only: no markup, links, e-mail addresses or long tokens."""
    text = html.unescape(_TAGS.sub(" ", str(value or "")))
    for pattern in (_LINKS, _EMAIL, _LONG):
        text = pattern.sub("", text)
    text = _SPACE.sub(" ", text).replace("`", "").replace("{", "").replace("}", "").strip()
    return text[:TITLE_MAX_CHARS]


def _when(text: str | None) -> datetime | None:
    if not text:
        return None
    text = text.strip()
    try:
        moment = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def parse_feed(raw: bytes) -> list[tuple[str, datetime | None]]:
    """(title, published) from an RSS 2.0, RSS 1.0 (RDF) or Atom feed."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise NewsError("feed is not valid XML") from None
    items = []
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        fields = {child.tag.rsplit("}", 1)[-1]: (child.text or "") for child in node}
        title = clean_title(fields.get("title"))
        when = _when(fields.get("pubDate") or fields.get("date") or fields.get("updated") or fields.get("published"))
        if title:
            items.append((title, when))
    return items


def parse_gdelt(raw: bytes) -> list[tuple[str, datetime | None, str]]:
    """(title, seen, domain) from GDELT's artlist JSON."""
    import json
    try:
        data = json.loads(raw)
    except ValueError:
        raise NewsError("GDELT reply is not JSON") from None
    out = []
    for article in (data.get("articles") or []) if isinstance(data, dict) else []:
        title = clean_title(article.get("title"))
        seen = article.get("seendate") or ""
        when = None
        if re.fullmatch(r"\d{8}T\d{6}Z", seen):
            when = datetime.strptime(seen, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        domain = clean_title(article.get("domain"))[:60]
        if title:
            out.append((title, when, domain))
    return out


def gather_news(*, fetch: Fetch | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Collect today's headlines. Never raises.

    Returns {"headlines": [{"source", "about", "title", "hours_ago"}], "sources": [{"name", "status"}]}.
    """
    fetch = fetch or _http_get
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=MAX_AGE_HOURS)
    headlines: list[dict[str, Any]] = []
    sources: list[dict[str, str]] = []

    def keep(source: str, about: str, items: list[tuple[str, datetime | None]], limit: int = PER_SOURCE) -> int:
        fresh = [(t, w) for t, w in items if w is not None and cutoff <= w <= now + timedelta(hours=1)]
        fresh.sort(key=lambda tw: tw[1], reverse=True)
        seen: set[str] = set()
        added = 0
        for title, when in fresh:
            if title.lower() in seen or added >= limit:
                continue
            seen.add(title.lower())
            headlines.append({"source": source, "about": about, "title": title,
                              "hours_ago": max(0, round((now - when).total_seconds() / 3600))})
            added += 1
        return added

    for name, currency, url in CENTRAL_BANK_FEEDS:
        try:
            added = keep(name, currency, parse_feed(fetch(url)))
            sources.append({"name": name, "status": f"ok ({added} new)"})
        except NewsError as exc:
            sources.append({"name": name, "status": f"failed: {exc}"})
        except Exception as exc:  # a bad feed must never stop the council
            sources.append({"name": name, "status": f"failed: {type(exc).__name__}"})

    try:
        articles = parse_gdelt(fetch(GDELT_URL))
        added = keep("World news (GDELT)", "global", [(f"{t} ({d})" if d else t, w) for t, w, d in articles], limit=GLOBAL_LIMIT)
        sources.append({"name": "World news (GDELT)", "status": f"ok ({added} new)"})
    except NewsError as exc:
        sources.append({"name": "World news (GDELT)", "status": f"failed: {exc}"})
    except Exception as exc:
        sources.append({"name": "World news (GDELT)", "status": f"failed: {type(exc).__name__}"})

    headlines.sort(key=lambda h: h["hours_ago"])
    return {"headlines": headlines[:MAX_HEADLINES], "sources": sources}
