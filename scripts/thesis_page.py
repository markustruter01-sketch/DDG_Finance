"""Build the public thesis page from docs/plans/fund-thesis-2027.md.

One source of truth: the markdown file is the thesis (it is hashed into the lock
record, roadmap v2 order V2-23). This script turns it into one self-contained,
styled HTML page. It never rewords the text: every sentence of the file appears
on the page as written (trading-platform/tests/test_thesis_page.py checks it).
What it adds is presentation only: a cover, a contents rail, odds bars beside
every probability, a chart of the 54 calls, a chart of the 2027 ranges, and
coloured dots on the marks (BUILT, AGREED, PROPOSED, EXPECTED, UNKNOWN).

    python scripts/thesis_page.py dashboard   # -> artifacts/dashboard/public/paper.html
    python scripts/thesis_page.py public OUT  # -> the ddg.limited copy (asset paths from /)

The page prints the SHA-256 of the source file, so a reader can match it to the
hash in the lock record.
"""

from __future__ import annotations

import hashlib
import html
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "plans" / "fund-thesis-2027.md"
DASHBOARD_OUT = ROOT / "artifacts" / "dashboard" / "public" / "paper.html"

VARIANTS = {
    # where the page lives -> (asset prefix, back link, back label, icon)
    "dashboard": ("", "./", "Dashboard", "favicon.svg"),
    "public": ("/", "/finance", "DDG Finance", "favicon.ico"),
}

MARKS = {"BUILT": "built", "AGREED": "agreed", "PROPOSED": "proposed", "EXPECTED": "expected", "UNKNOWN": "unknown"}
PCT = re.compile(r"[−+-]?\d+(?:\.\d+)?%")


# ── markdown subset -> blocks ────────────────────────────────────────────────
@dataclass
class Block:
    kind: str                      # h1 h2 h3 p ul ol table hr
    text: str = ""
    items: list[str] | None = None
    rows: list[list[str]] | None = None


def parse(md: str) -> list[Block]:
    lines = md.splitlines()
    out: list[Block] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if not s:
            i += 1
            continue
        if s == "---":
            out.append(Block("hr"))
            i += 1
        elif s.startswith("### "):
            out.append(Block("h3", s[4:]))
            i += 1
        elif s.startswith("## "):
            out.append(Block("h2", s[3:]))
            i += 1
        elif s.startswith("# "):
            out.append(Block("h1", s[2:]))
            i += 1
        elif s.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            out.append(Block("table", rows=rows))
        elif re.match(r"- ", s):
            items = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                items.append(lines[i].strip()[2:])
                i += 1
            out.append(Block("ul", items=items))
        elif re.match(r"\d+\. ", s):
            items = []
            while i < len(lines) and re.match(r"\d+\. ", lines[i].strip()):
                items.append(re.sub(r"^\d+\. ", "", lines[i].strip()))
                i += 1
            out.append(Block("ol", items=items))
        else:
            para = [s]
            i += 1
            while i < len(lines) and lines[i].strip() and not re.match(r"(#|\||- |\d+\. |---)", lines[i].strip()):
                para.append(lines[i].strip())
                i += 1
            out.append(Block("p", " ".join(para)))
    return out


def plain(md_inline: str) -> str:
    """The words a reader sees for a piece of inline markdown."""
    return re.sub(r"\*\*|\*|`", "", md_inline)


def inline(md_inline: str, marks: bool = True) -> str:
    t = html.escape(md_inline, quote=False)
    parts = re.split(r"(`[^`]+`)", t)
    done = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            done.append(f"<code>{part[1:-1]}</code>")
            continue
        part = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", part)
        part = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", part)
        if marks:
            part = re.sub(r"\b(BUILT|AGREED|PROPOSED|EXPECTED|UNKNOWN)\b",
                          lambda m: f'<span class="mk mk-{MARKS[m.group(1)]}">{m.group(1)}</span>', part)
        done.append(part)
    return "".join(done)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", plain(text).lower()).strip("-")


def pct_value(s: str) -> float:
    return float(s.replace("−", "-").replace("%", ""))


# ── the 54 calls, read from Part 7's tables ──────────────────────────────────
@dataclass
class Call:
    n: int
    text: str
    odds: float
    section: str


def calls(blocks: list[Block]) -> list[Call]:
    out, in_part7, section = [], False, ""
    for b in blocks:
        if b.kind == "h1":
            in_part7 = b.text.startswith("Part 7")
        elif in_part7 and b.kind == "h2":
            section = b.text
        elif in_part7 and b.kind == "table" and b.rows and b.rows[0][:3] == ["#", "Expectation", "Odds"]:
            for r in b.rows[1:]:
                out.append(Call(int(r[0]), plain(r[1]), pct_value(r[2]), section))
    return out


# ── charts (SVG, drawn here; tooltips by the small script at the bottom) ─────
def strip_chart(cs: list[Call]) -> str:
    sections = []
    for c in cs:
        if c.section not in sections:
            sections.append(c.section)
    W, left, right, row_h, top = 760, 280, 24, 34, 26
    H = top + row_h * len(sections) + 34
    x = lambda p: left + (W - left - right) * p / 100
    g = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-labelledby="strip-t strip-d">',
         '<title id="strip-t">The 54 numbered expectations, placed by their odds</title>',
         f'<desc id="strip-d">One dot per expectation in Part 7, by section. Odds run from {min(c.odds for c in cs):.0f}% to '
         f'{max(c.odds for c in cs):.0f}%. The full list, with every number, is in Part 7.</desc>']
    for p in range(0, 101, 25):
        g.append(f'<line class="grid" x1="{x(p):.1f}" x2="{x(p):.1f}" y1="{top - 10}" y2="{H - 28}"/>')
        g.append(f'<text class="tick" x="{x(p):.1f}" y="{H - 10}" text-anchor="middle">{p}%</text>')
    g.append(f'<line class="coin" x1="{x(50):.1f}" x2="{x(50):.1f}" y1="{top - 10}" y2="{H - 28}"/>')
    g.append(f'<text class="tick" x="{x(50) + 6:.1f}" y="{top - 14}">a coin toss</text>')
    for i, sec in enumerate(sections):
        cy = top + row_h * i + row_h / 2
        g.append(f'<text class="rowlab" x="{left - 14}" y="{cy + 4:.1f}" text-anchor="end">{html.escape(sec)}</text>')
        seen: dict[float, int] = {}
        for c in (c for c in cs if c.section == sec):
            k = seen.get(c.odds, 0)
            seen[c.odds] = k + 1
            dy = (0, -9, 9, -18, 18)[min(k, 4)]
            tip = html.escape(f"{c.n}. {c.text} ({c.odds:.0f}%)", quote=True)
            g.append(f'<a href="#exp-{c.n}" class="dot" data-tip="{tip}" aria-label="{tip}">'
                     f'<circle cx="{x(c.odds):.1f}" cy="{cy + dy:.1f}" r="5"/></a>')
    g.append("</svg>")
    return "".join(g)


def range_chart(rows: list[list[str]]) -> str:
    """The 'eight-in-ten range' table as floating bars, returns only.
    The worst-fall row measures something else, so it stays in the table."""
    data = []
    for r in rows[1:]:
        if "worst fall" in r[0].lower():
            continue
        lo, hi = (pct_value(v) for v in PCT.findall(r[2])[:2])
        data.append((plain(r[0]), pct_value(PCT.findall(r[1])[0]), lo, hi, r[1], r[2]))
    W, left, right, row_h, top = 760, 300, 28, 40, 16
    H = top + row_h * len(data) + 36
    lo_ax, hi_ax = -25, 25
    x = lambda v: left + (W - left - right) * (v - lo_ax) / (hi_ax - lo_ax)
    g = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-labelledby="rng-t rng-d">',
         '<title id="rng-t">2027 returns: middle guess and eight-in-ten range</title>',
         '<desc id="rng-d">Each bar runs from the low to the high end of the range; the dot is the middle guess. '
         'The same numbers are in the table above.</desc>']
    for v in range(-20, 21, 10):
        cls = "zero" if v == 0 else "grid"
        g.append(f'<line class="{cls}" x1="{x(v):.1f}" x2="{x(v):.1f}" y1="{top - 6}" y2="{H - 30}"/>')
        g.append(f'<text class="tick" x="{x(v):.1f}" y="{H - 12}" text-anchor="middle">{"+" if v > 0 else ""}{v}%</text>')
    for i, (name, mid, lo, hi, mid_s, rng_s) in enumerate(data):
        cy = top + row_h * i + row_h / 2
        tip = html.escape(f"{name}: middle guess {mid_s}, range {rng_s}", quote=True)
        g.append(f'<g class="rng" data-tip="{tip}" tabindex="0" aria-label="{tip}">'
                 f'<rect class="hit" x="{left}" y="{cy - row_h / 2:.1f}" width="{W - left - right}" height="{row_h}"/>'
                 f'<text class="rowlab" x="{left - 14}" y="{cy + 4:.1f}" text-anchor="end">{html.escape(name)}</text>'
                 f'<rect class="bar" x="{x(lo):.1f}" y="{cy - 4:.1f}" width="{x(hi) - x(lo):.1f}" height="8" rx="4"/>'
                 f'<circle cx="{x(mid):.1f}" cy="{cy:.1f}" r="5"/>'
                 f'<text class="val" x="{x(mid):.1f}" y="{cy - 10:.1f}" text-anchor="middle">{html.escape(mid_s)}</text></g>')
    g.append("</svg>")
    return "".join(g)


# ── blocks -> html ────────────────────────────────────────────────────────────
def meter(cell_md: str) -> str:
    """A probability cell: the number as written, with a bar under it."""
    found = PCT.findall(cell_md)
    if len(found) != 1:
        return inline(cell_md)
    p = max(0.0, min(100.0, pct_value(found[0])))
    return f'<span class="odds">{inline(cell_md)}<span class="odds-bar" style="--p:{p:.0f}%" aria-hidden="true"></span></span>'


def lead_meter(item_md: str) -> str:
    """Part 0's six lines end in '(85%)' or '(70% to 80% each)': a small bar at the end."""
    m = re.search(r"\(([^()]*%[^()]*)\)\s*$", item_md)
    if not m:
        return ""
    vals = [pct_value(v) for v in PCT.findall(m.group(1))]
    if len(vals) == 1:
        return f'<span class="odds-bar lead" style="--p:{vals[0]:.0f}%" aria-hidden="true"></span>'
    if len(vals) >= 2:
        return (f'<span class="odds-bar lead band" style="--a:{vals[0]:.0f}%;--b:{vals[1]:.0f}%" '
                f'aria-hidden="true"></span>')
    return ""


def cell(md_cell: str, header: str) -> str:
    h = header.lower()
    if "odds" in h:
        return meter(md_cell)
    body = inline(md_cell)
    if header in ("Verdict", "State") or h.startswith("state"):
        words = plain(md_cell)
        tone = "neg" if re.search(r"Failed|not armed|waiting|lost", words) else (
            "pos" if re.search(r"BUILT|Done|In use", words) else "")
        if tone:      # the tone dot replaces the mark dot, so a cell never shows two
            body = f'<span class="tone {tone}">{inline(md_cell, marks=False)}</span>'
    if header == "Direction":
        arrow = {"up": "↑", "down": "↓"}.get(plain(md_cell).strip())
        if arrow:
            body = f'<span class="dir" aria-hidden="true">{arrow}</span>{body}'
    return body


def table(rows: list[list[str]], in_part7: bool) -> str:
    head = rows[0]
    cls = "calls" if head[:3] == ["#", "Expectation", "Odds"] else ""
    out = [f'<div class="table-wrap"><table class="{cls}"><thead><tr>']
    for h in head:
        num = ' class="n"' if h in ("#", "Odds") or "odds" in h.lower() else ""
        out.append(f"<th{num}>{inline(h)}</th>")
    out.append("</tr></thead><tbody>")
    for r in rows[1:]:
        rid = f' id="exp-{r[0]}"' if cls == "calls" and r[0].isdigit() else ""
        out.append(f"<tr{rid}>")
        for j, c in enumerate(r):
            h = head[j] if j < len(head) else ""
            num = ' class="n"' if h == "#" else (' class="o"' if "odds" in h.lower() else "")
            out.append(f"<td{num}>{cell(c, h)}</td>")
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def render(md: str, variant: str) -> str:
    asset, back_href, back_label, icon = VARIANTS[variant]
    blocks = parse(md)
    digest = hashlib.sha256(md.encode("utf-8")).hexdigest()
    cs = calls(blocks)

    title, subtitle = blocks[0].text, blocks[1].text
    assert blocks[0].kind == "h1" and blocks[1].kind == "h2", "the file must open with its title and subtitle"
    body = blocks[2:]

    # front matter = everything before the first rule
    k = next(i for i, b in enumerate(body) if b.kind == "hr")
    front, rest = body[:k], body[k + 1:]

    parts: list[tuple[str, str, list[Block]]] = []      # (id, heading, blocks)
    for b in rest:
        if b.kind == "h1":
            parts.append((slug(b.text.split(".")[0]), b.text, []))
        elif b.kind != "hr" and parts:
            parts[-1][2].append(b)

    toc = []
    sections = []
    for pid, heading, bs in parts:
        m = re.match(r"(Part \d+)\.\s*(.*)", heading)
        num, name = (m.group(1), m.group(2)) if m else ("", heading)
        toc.append(f'<li><a href="#{pid}"><span class="tn">{html.escape(num.replace("Part ", ""))}</span>'
                   f"{inline(name)}</a></li>")
        html_parts = [f'<section class="part" id="{pid}" aria-labelledby="{pid}-h">',
                      f'<h2 id="{pid}-h"><span class="pn">{html.escape(num)}.</span> {inline(name)}</h2>']
        in_part7 = num == "Part 7"
        prev_p = ""
        for b in bs:
            if b.kind == "h2":
                html_parts.append(f'<h3 id="{pid}-{slug(b.text)}">{inline(b.text)}</h3>')
            elif b.kind == "h3":
                html_parts.append(f"<h4>{inline(b.text)}</h4>")
            elif b.kind == "p":
                cls = ""
                if b.text.startswith("*") and b.text.endswith("*") and not b.text.startswith("**"):
                    cls = ' class="said"'
                html_parts.append(f"<p{cls}>{inline(b.text)}</p>")
                prev_p = b.text
            elif b.kind == "ul":
                if num == "Part 10":
                    html_parts.append('<dl class="gloss">')
                    for it in b.items or []:
                        mm = re.match(r"\*\*(.+?)\*\*\s*(.*)", it)
                        if mm:
                            html_parts.append(f"<div><dt>{inline(mm.group(1))}</dt> <dd>{inline(mm.group(2))}</dd></div>")
                        else:
                            html_parts.append(f"<div><dd>{inline(it)}</dd></div>")
                    html_parts.append("</dl>")
                    continue
                six = prev_p.startswith("**What I expect of 2027")
                html_parts.append(f'<ul class="{"six" if six else ""}">')
                for it in b.items or []:
                    html_parts.append(f"<li>{inline(it)}{lead_meter(it) if six else ''}</li>")
                html_parts.append("</ul>")
            elif b.kind == "ol":
                seven = prev_p.startswith("**The thesis, in seven sentences")
                html_parts.append(f'<ol class="{"seven" if seven else ""}">')
                for it in b.items or []:
                    html_parts.append(f"<li>{inline(it)}</li>")
                html_parts.append("</ol>")
            elif b.kind == "table":
                html_parts.append(table(b.rows or [], in_part7))
                if b.rows and "Eight-in-ten range" in b.rows[0]:
                    html_parts.append(f'<figure class="fig">{range_chart(b.rows)}'
                                      '<figcaption>The table above as a chart: the bar is the eight-in-ten range, '
                                      'the dot the middle guess. The worst-fall row measures a fall, not a return, '
                                      'so it is left to the table.</figcaption></figure>')
        html_parts.append("</section>")
        sections.append("".join(html_parts))

    front_html = "".join(
        f'<p class="{"status" if b.text.startswith("**Status") else ""}">{inline(b.text)}</p>'
        for b in front if b.kind == "p")

    strip = (f'<figure class="fig hero-fig">{strip_chart(cs)}'
             f'<figcaption>Every numbered expectation in Part 7, placed by the odds given to it. '
             f'Each one is marked right or wrong from the frozen record in January 2028. '
             f'Hover or tap a dot to read it; select it to jump to the line.</figcaption></figure>') if cs else ""

    return TEMPLATE.format(
        title=html.escape(title), subtitle=inline(subtitle), asset=asset, icon=icon,
        back_href=back_href, back_label=html.escape(back_label),
        front=front_html, strip=strip, toc="".join(toc), sections="".join(sections),
        digest=digest, n_calls=len(cs),
        desc=html.escape(plain(subtitle), quote=True),
    )


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta name="generator" content="scripts/thesis_page.py from docs/plans/fund-thesis-2027.md">
<link rel="icon" href="{asset}{icon}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;1,6..72,400&display=swap">
<style>
:root {{
  --night:#07080b; --graphite:#141518; --glass:rgba(255,255,255,0.045); --edge:rgba(255,255,255,0.10); --hair:rgba(255,255,255,0.08);
  --text:#fff; --text2:rgba(255,255,255,0.74); --text3:rgba(255,255,255,0.56);
  --ice:#6cc7f0; --mint:#3ddc97; --violet:#a78bfa; --amber:#f5a524;
  --sans:Geist, system-ui, -apple-system, sans-serif; --serif:Newsreader, Georgia, 'Times New Roman', serif;
  --measure:40rem; color-scheme:dark;
}}
*{{box-sizing:border-box}}
html{{scroll-padding-top:24px}}
@media (prefers-reduced-motion:no-preference){{html{{scroll-behavior:smooth}}}}
body{{margin:0;background:var(--graphite);color:var(--text);font:400 1.125rem/1.68 var(--serif);font-optical-sizing:auto;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}}
a{{color:inherit}}
:focus-visible{{outline:2px solid var(--ice);outline-offset:3px;border-radius:4px}}
.dusk{{position:absolute;inset:0 0 auto 0;height:min(78vh,720px);z-index:-1;background:linear-gradient(180deg,rgba(7,8,11,.30) 0%,rgba(20,21,24,.72) 58%,var(--graphite) 100%),url('{asset}backgrounds/david-becker.webp') center 38%/cover}}
.top{{display:flex;align-items:center;gap:12px;max-width:76rem;margin:0 auto;padding:22px 24px}}
.brand{{display:inline-flex;align-items:center;gap:12px;padding:0 14px 0 10px;min-height:46px;border-radius:14px;background:rgba(16,18,24,.52);border:1px solid var(--edge);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);font:400 19px/1 var(--sans);text-decoration:none}}
.brand img{{width:28px;height:28px}} .brand i{{width:1px;height:20px;background:rgba(255,255,255,.28)}} .brand b{{font-weight:600}}
.back{{margin-left:auto;white-space:nowrap;font:400 14px/1 var(--sans);color:var(--text2);text-decoration:none;padding:13px 16px;border-radius:12px;border:1px solid var(--edge);background:rgba(16,18,24,.4);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}}
.back:hover{{color:var(--text)}}
.cover{{max-width:76rem;margin:0 auto;padding:clamp(48px,11vh,128px) 24px 32px}}
.cover h1{{font:300 clamp(2.6rem,6.4vw,5.2rem)/1.02 var(--sans);letter-spacing:-0.035em;margin:0;max-width:14ch}}
.cover .sub{{font:400 clamp(1.15rem,2vw,1.45rem)/1.45 var(--serif);font-style:italic;color:var(--text2);max-width:34rem;margin:22px 0 0}}
.frontmatter{{max-width:76rem;margin:0 auto;padding:0 24px;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:4px 48px}}
.frontmatter p{{font:400 .95rem/1.6 var(--sans);color:var(--text2);margin:0 0 14px;max-width:34rem}}
.frontmatter p strong{{color:var(--text);font-weight:600}}
.frontmatter p.status{{grid-column:1/-1;max-width:none;padding:14px 18px;border-radius:14px;background:var(--glass);border:1px solid var(--edge);color:var(--text)}}
.hero-fig{{max-width:76rem;margin:28px auto 0;padding:22px 24px 8px;}}
.fig{{margin:28px 0}}
.fig svg{{display:block;width:100%;height:auto;overflow:visible}}
.fig figcaption{{font:400 .86rem/1.5 var(--sans);color:var(--text3);margin-top:10px;max-width:46rem}}
.chart .grid{{stroke:rgba(255,255,255,.09);stroke-width:1}}
.chart .zero{{stroke:rgba(255,255,255,.32);stroke-width:1}}
.chart .coin{{stroke:rgba(255,255,255,.30);stroke-width:1}}
.chart .tick{{font:400 11.5px var(--sans);fill:var(--text3);font-variant-numeric:tabular-nums}}
.chart .rowlab{{font:400 13px var(--sans);fill:var(--text2)}}
.chart .val{{font:500 12px var(--sans);fill:var(--text)}}
.chart circle{{fill:var(--ice);stroke:var(--graphite);stroke-width:2}}
.chart .dot{{cursor:pointer}} .chart .dot:hover circle,.chart .dot:focus circle{{r:7}}
.chart .bar{{fill:rgba(108,199,240,.42)}}
.chart .hit{{fill:transparent}} .chart .rng:hover .bar,.chart .rng:focus .bar{{fill:rgba(108,199,240,.62)}}
.tip{{position:fixed;z-index:20;max-width:22rem;pointer-events:none;padding:10px 12px;border-radius:12px;background:rgba(10,12,18,.92);border:1px solid var(--edge);font:400 13px/1.45 var(--sans);color:var(--text);box-shadow:0 8px 28px rgba(0,0,0,.4);opacity:0;transition:opacity .12s}}
.tip.on{{opacity:1}}
.layout{{max-width:76rem;margin:0 auto;padding:24px 24px 96px;display:grid;grid-template-columns:15rem minmax(0,1fr);gap:56px}}
.rail{{position:sticky;top:24px;align-self:start;max-height:calc(100vh - 48px);overflow:auto;padding-top:56px}}
.rail h2{{font:500 .8rem/1 var(--sans);color:var(--text3);margin:0 0 14px;letter-spacing:.01em}}
.rail ol{{list-style:none;margin:0;padding:0;border-left:1px solid var(--hair)}}
.rail li a{{display:flex;gap:10px;padding:7px 0 7px 14px;margin-left:-1px;border-left:2px solid transparent;font:400 .88rem/1.35 var(--sans);color:var(--text3);text-decoration:none}}
.rail li a:hover{{color:var(--text)}}
.rail li a.here{{color:var(--text);border-left-color:var(--ice)}}
.rail .tn{{min-width:1.2em;color:var(--text3);font-variant-numeric:tabular-nums}}
.doc{{min-width:0}}
.part{{padding-top:56px}}
.part+.part{{border-top:1px solid var(--hair);margin-top:24px}}
.part h2{{font:400 clamp(1.7rem,3vw,2.3rem)/1.15 var(--sans);letter-spacing:-0.02em;margin:0 0 24px;max-width:var(--measure)}}
.part h2 .pn{{color:var(--text3);font-weight:300}}
.part h3{{font:500 1.18rem/1.3 var(--sans);letter-spacing:-0.005em;margin:44px 0 12px;max-width:var(--measure)}}
.part h4{{font:600 1rem/1.3 var(--sans);margin:28px 0 8px}}
.doc p,.doc li,.doc dd{{max-width:var(--measure)}}
.doc p{{margin:0 0 1.05em}}
.doc strong{{font-weight:500;color:#fff}}
.doc p>strong:first-child{{font:600 .9em/1 var(--sans);letter-spacing:-0.005em}}
.doc em{{font-style:italic}}
.doc ul,.doc ol{{margin:0 0 1.2em;padding-left:1.25em}}
.doc li{{margin-bottom:.45em}}
.doc li::marker{{color:var(--text3)}}
code{{font:400 .82em/1 ui-monospace,'SF Mono',Menlo,monospace;color:var(--text2);background:rgba(255,255,255,.05);padding:.12em .35em;border-radius:5px;white-space:nowrap}}
td code{{white-space:normal;word-break:break-word}}
p.said{{font-size:1.25rem;line-height:1.55;color:var(--text);padding:6px 0 6px 22px;border-left:2px solid var(--violet)}}
ol.seven{{list-style:none;counter-reset:s;padding:0;margin:8px 0 32px}}
ol.seven li{{counter-increment:s;position:relative;padding:14px 0 14px 3rem;border-top:1px solid var(--hair);font-size:1.28rem;line-height:1.5;margin:0;max-width:44rem}}
ol.seven li:last-child{{border-bottom:1px solid var(--hair)}}
ol.seven li::before{{content:counter(s);position:absolute;left:0;top:15px;font:300 1.5rem/1.2 var(--sans);color:var(--ice);font-variant-numeric:tabular-nums}}
ul.six{{list-style:none;padding:0;display:grid;gap:10px;max-width:46rem}}
ul.six li{{display:grid;grid-template-columns:minmax(0,1fr) 7.5rem;gap:18px;align-items:center;margin:0;padding:12px 16px;border-radius:14px;background:var(--glass);border:1px solid var(--edge);font:400 1rem/1.5 var(--sans);max-width:none}}
.odds{{display:inline-flex;align-items:center;justify-content:flex-end;gap:10px;font:500 .9rem/1 var(--sans);font-variant-numeric:tabular-nums;white-space:nowrap}}
.odds .odds-bar{{width:4.5rem;flex:none}}
.odds-bar{{display:block;width:100%;height:6px;border-radius:3px;background:linear-gradient(90deg,var(--ice) 0 var(--p),rgba(108,199,240,.16) var(--p) 100%)}}
.odds-bar.lead{{height:8px;border-radius:4px}}
.odds-bar.band{{background:linear-gradient(90deg,rgba(108,199,240,.16) 0 var(--a),var(--ice) var(--a) var(--b),rgba(108,199,240,.16) var(--b) 100%)}}
.table-wrap{{overflow-x:auto;margin:16px 0 26px;border-radius:16px;border:1px solid var(--edge);background:var(--glass);-webkit-overflow-scrolling:touch}}
table{{width:100%;border-collapse:collapse;font:400 .9rem/1.5 var(--sans)}}
th,td{{text-align:left;padding:11px 14px;vertical-align:top;border-bottom:1px solid var(--hair)}}
tbody tr:last-child td{{border-bottom:0}}
th{{font-weight:500;color:var(--text3);font-size:.8rem;background:rgba(255,255,255,.025)}}
td{{color:var(--text2)}} td:first-child{{color:var(--text)}}
td.n,th.n{{text-align:right;font-variant-numeric:tabular-nums;width:2.5rem;color:var(--text3)}}
td.o{{width:9.5rem;text-align:right}} th.n:last-child{{text-align:right}}
table.calls td:nth-child(2){{color:var(--text)}}
table.calls tr:target td{{background:rgba(108,199,240,.10)}}
.tone{{display:inline-flex;align-items:baseline;gap:7px}}
.tone::before{{content:"";width:7px;height:7px;border-radius:50%;flex:none;transform:translateY(-1px)}}
.tone.neg::before{{background:var(--amber)}} .tone.pos::before{{background:var(--mint)}}
.dir{{margin-right:6px;color:var(--text3)}}
.mk{{font:600 .7em/1 var(--sans);letter-spacing:.06em;white-space:nowrap;display:inline-flex;align-items:center;gap:5px}}
.mk::before{{content:"";width:6px;height:6px;border-radius:50%}}
.mk-built::before{{background:var(--mint)}} .mk-agreed::before{{background:var(--ice)}} .mk-proposed::before{{background:var(--violet)}}
.mk-expected::before{{background:#fff}} .mk-unknown::before{{background:var(--amber)}}
dl.gloss{{display:grid;grid-template-columns:repeat(auto-fill,minmax(17rem,1fr));gap:12px;margin:8px 0 24px}}
dl.gloss div{{padding:14px 16px;border-radius:14px;background:var(--glass);border:1px solid var(--edge)}}
dl.gloss dt{{font:500 .98rem/1.3 var(--sans);margin-bottom:4px}}
dl.gloss dd{{margin:0;font:400 .92rem/1.5 var(--sans);color:var(--text2)}}
.colophon{{max-width:76rem;margin:0 auto;padding:28px 24px 64px;border-top:1px solid var(--hair);display:grid;gap:6px;font:400 .82rem/1.55 var(--sans);color:var(--text3)}}
.colophon b{{font-weight:500;color:var(--text2)}}
.colophon .hash{{font-family:ui-monospace,'SF Mono',Menlo,monospace;font-size:.78rem;word-break:break-all;color:var(--text2)}}
.toc-m{{display:none}}
@media (max-width:980px){{
  .layout{{grid-template-columns:minmax(0,1fr);gap:0}}
  .rail{{display:none}}
  .toc-m{{display:block;margin:8px 0 0;padding:14px 18px;border-radius:14px;background:var(--glass);border:1px solid var(--edge);font:400 .95rem/1.5 var(--sans)}}
  .toc-m summary{{cursor:pointer;color:var(--text2)}}
  .toc-m ol{{margin:10px 0 0;padding-left:1.3em}} .toc-m a{{text-decoration:none;color:var(--text2)}}
  .frontmatter{{grid-template-columns:minmax(0,1fr)}}
}}
@media (max-width:640px){{
  body{{font-size:1.06rem}}
  .top,.cover,.frontmatter,.hero-fig,.layout,.colophon{{padding-left:16px;padding-right:16px}}
  ol.seven li{{font-size:1.12rem;padding-left:2.2rem}}
  ul.six li{{grid-template-columns:minmax(0,1fr);gap:8px}}
  .hero-fig svg{{min-width:560px}} .hero-fig{{overflow-x:auto}}
  th,td{{padding:9px 10px}}
  td.o{{width:auto}} .odds{{gap:6px}} .odds .odds-bar{{width:2.25rem}}
}}
@media print{{
  .dusk,.top,.rail,.toc-m,.tip{{display:none!important}}
  body{{background:#fff;color:#111;font-size:11pt}}
  .layout{{display:block;padding:0}} .cover{{padding-top:0}}
  .doc strong,.cover h1,.part h2,.part h3{{color:#000}} .doc p,.doc li,td,.frontmatter p{{color:#222}}
  .table-wrap,ul.six li,dl.gloss div,.frontmatter p.status{{background:none;border-color:#bbb}}
  .chart circle{{stroke:#fff}} .chart .tick,.chart .rowlab{{fill:#444}} .chart .val{{fill:#000}}
  .part{{break-inside:auto}} tr,figure{{break-inside:avoid}}
}}
@media (forced-colors:active){{.chart circle{{fill:CanvasText}} .odds-bar{{border:1px solid CanvasText}}}}
</style>
</head>
<body>
<div class="dusk" aria-hidden="true"></div>
<header class="top">
  <a class="brand" href="{back_href}" aria-label="DDG Finance"><img src="{asset}ddg-mark-white-256.png" alt=""><b>DDG</b><i></i><span>Finance</span></a>
  <a class="back" href="{back_href}"><span aria-hidden="true">‹ </span>{back_label}</a>
</header>
<div class="cover">
  <h1>{title}</h1>
  <p class="sub">{subtitle}</p>
</div>
<div class="frontmatter">{front}</div>
{strip}
<div class="layout">
  <nav class="rail" aria-label="Contents"><h2>Contents</h2><ol>{toc}</ol></nav>
  <main class="doc" id="doc">
    <details class="toc-m"><summary>Contents</summary><ol>{toc}</ol></details>
    {sections}
  </main>
</div>
<footer class="colophon">
  <div><b>Source.</b> This page is built, word for word, from <code>docs/plans/fund-thesis-2027.md</code> in the DDG Finance repository.</div>
  <div><b>SHA-256 of that file:</b> <span class="hash">{digest}</span></div>
  <div>At the lock (12–13 Dec 2026) this hash goes into the lock record. If the two match, this is the text that will be scored.</div>
</footer>
<div class="tip" role="tooltip" id="tip"></div>
<script>
(function () {{
  var tip = document.getElementById('tip');
  function show(el, x, y) {{
    tip.textContent = el.getAttribute('data-tip');
    var w = Math.min(352, window.innerWidth - 24);
    tip.style.left = Math.max(12, Math.min(x + 14, window.innerWidth - w - 12)) + 'px';
    tip.style.top = Math.max(12, y - 54) + 'px';
    tip.classList.add('on');
  }}
  function hide() {{ tip.classList.remove('on'); }}
  document.querySelectorAll('[data-tip]').forEach(function (el) {{
    el.addEventListener('mousemove', function (e) {{ show(el, e.clientX, e.clientY); }});
    el.addEventListener('mouseleave', hide);
    el.addEventListener('focus', function () {{ var r = el.getBoundingClientRect(); show(el, r.left + r.width / 2, r.top); }});
    el.addEventListener('blur', hide);
  }});
  window.addEventListener('scroll', hide, {{ passive: true }});
  var links = Array.prototype.slice.call(document.querySelectorAll('.rail a'));
  if (!('IntersectionObserver' in window) || !links.length) return;
  var byId = {{}};
  links.forEach(function (a) {{ byId[a.getAttribute('href').slice(1)] = a; }});
  var io = new IntersectionObserver(function (entries) {{
    entries.forEach(function (en) {{
      if (en.isIntersecting) {{
        links.forEach(function (a) {{ a.classList.remove('here'); a.removeAttribute('aria-current'); }});
        var a = byId[en.target.id];
        if (a) {{ a.classList.add('here'); a.setAttribute('aria-current', 'true'); }}
      }}
    }});
  }}, {{ rootMargin: '-35% 0px -60% 0px' }});
  document.querySelectorAll('section.part').forEach(function (s) {{ io.observe(s); }});
}})();
</script>
</body>
</html>
"""


def main(argv: list[str]) -> int:
    variant = argv[1] if len(argv) > 1 else "dashboard"
    if variant not in VARIANTS:
        print(f"usage: thesis_page.py [{'|'.join(VARIANTS)}] [OUT]", file=sys.stderr)
        return 2
    out = Path(argv[2]) if len(argv) > 2 else (DASHBOARD_OUT if variant == "dashboard" else None)
    if out is None:
        print("the public variant needs an output path", file=sys.stderr)
        return 2
    page = render(SOURCE.read_text(encoding="utf-8"), variant)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out} ({len(page):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
