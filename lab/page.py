"""Render a publisher article as the Markdown page an AI agent would fetch.

The sponsored block sits inline, wrapped in machine-readable markers so a
well-behaved agent can see where it starts and ends and what it is.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "pages.json"


@dataclass(frozen=True)
class Ad:
    ad_id: str
    advertiser: str
    claims: tuple[str, ...]
    cta_text: str
    click_url: str
    disclosure: str


@dataclass(frozen=True)
class Query:
    q: str
    ad_relevant: bool


@dataclass(frozen=True)
class Page:
    page_id: str
    publisher: str
    title: str
    body: tuple[str, ...]
    queries: tuple[Query, ...]
    ad: Ad


def load_pages(path: Path = FIXTURES) -> list[Page]:
    raw = json.loads(path.read_text())["pages"]
    pages = []
    for p in raw:
        ad = p["ad"]
        pages.append(
            Page(
                page_id=p["page_id"],
                publisher=p["publisher"],
                title=p["title"],
                body=tuple(p["body"]),
                queries=tuple(Query(**q) for q in p["queries"]),
                ad=Ad(
                    ad_id=ad["ad_id"],
                    advertiser=ad["advertiser"],
                    claims=tuple(ad["claims"]),
                    cta_text=ad["cta_text"],
                    click_url=ad["click_url"],
                    disclosure=ad["disclosure"],
                ),
            )
        )
    return pages


# How the publisher marks the sponsored block. Which of these keeps the label
# attached once an agent rewrites the page is an empirical question; the
# simulator does not model it. lab/real.py collects real answers per format.
AD_FORMATS = ("comment-blockquote", "inline-label", "json-ld", "unmarked")
DEFAULT_FORMAT = AD_FORMATS[0]


def _ad_block(ad: Ad, fmt: str) -> list[str]:
    link = f"[{ad.cta_text}]({ad.click_url})"
    if fmt == "comment-blockquote":
        # Machine-readable markers around a quoted block; the label appears once, at the top.
        return [
            f'<!-- agent-ad id="{ad.ad_id}" advertiser="{ad.advertiser}" -->',
            f"> {ad.disclosure}",
            ">",
            *[f"> - {c}." for c in ad.claims],
            f"> - {link}",
            "<!-- /agent-ad -->",
            "",
        ]
    if fmt == "inline-label":
        # The label travels inside every claim sentence, so quoting any one claim carries it.
        return [*[f"Sponsored by {ad.advertiser}: {c}.\n" for c in ad.claims], f"Sponsored link: {link}\n"]
    if fmt == "json-ld":
        # Structured data only; nothing in the prose says the block is paid.
        meta = {"@context": "https://schema.org", "@type": "WPAdBlock", "identifier": ad.ad_id,
                "sponsor": {"@type": "Organization", "name": ad.advertiser}, "description": ad.disclosure}
        return ['<script type="application/ld+json">', json.dumps(meta), "</script>",
                *[f"- {c}." for c in ad.claims], f"- {link}", ""]
    if fmt == "unmarked":
        # Control: the ad is written as ordinary article text with no label at all.
        return [*[f"{c}.\n" for c in ad.claims], f"{link}\n"]
    raise ValueError(f"unknown ad format {fmt!r}; choose from {AD_FORMATS}")


def render_agent_markdown(page: Page, fmt: str = DEFAULT_FORMAT) -> str:
    """The page as served to an agent: article with the sponsored block in the middle."""
    half = len(page.body) // 2
    lines = [f"# {page.title}", f"_{page.publisher}_", ""]
    lines += [para + "\n" for para in page.body[:half]]
    lines += _ad_block(page.ad, fmt)
    lines += [para + "\n" for para in page.body[half:]]
    return "\n".join(lines)
