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


def render_agent_markdown(page: Page) -> str:
    """The page as served to an agent: article, then a marked sponsored block."""
    ad = page.ad
    half = len(page.body) // 2
    lines = [f"# {page.title}", f"_{page.publisher}_", ""]
    lines += [para + "\n" for para in page.body[:half]]
    lines += [
        f'<!-- agent-ad id="{ad.ad_id}" advertiser="{ad.advertiser}" -->',
        f"> {ad.disclosure}",
        ">",
        *[f"> - {c}." for c in ad.claims],
        f"> - [{ad.cta_text}]({ad.click_url})",
        "<!-- /agent-ad -->",
        "",
    ]
    lines += [para + "\n" for para in page.body[half:]]
    return "\n".join(lines)
