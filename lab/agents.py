"""Simulated AI agents that read an agent page and answer a user's question.

Real assistants differ in how they treat a sponsored block: some quote it, some
paraphrase it, some drop the disclosure, some strip sponsorship entirely. Each
profile below encodes one of those behaviours as probabilities, so the
measurement layer can be tested against known ground truth.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass

from .page import Page, Query

SYNONYMS = {
    "lowers": "reduces",
    "surface": "sleeping-surface",
    "temperature": "temp",
    "overnight": "through the night",
    "offers": "has",
    "free": "no-cost",
    "returns": "return shipping",
    "certified": "accredited",
    "test": "check",
    "minutes": "min",
    "reports": "results",
    "include": "come with",
    "estimate": "valuation",
    "holds": "grabs",
    "twice": "2x",
    "ships": "sends",
    "kit": "bundle",
    "runs": "does",
}

DISCLOSURE_STYLES = (
    "(Sponsored by {adv}.)",
    "{adv} paid to place this suggestion.",
    "Note: this is an advertisement from {adv}.",
)


@dataclass(frozen=True)
class AgentProfile:
    name: str
    p_include_relevant: float   # include the ad when it fits the question
    p_include_irrelevant: float  # include it anyway when it does not
    p_keep_disclosure: float     # given included, keep a sponsorship label
    p_keep_link: float           # given included, keep the tracked link
    paraphrase: float            # 0 = verbatim claim, 1 = heavy rewrite


PROFILES = (
    AgentProfile("Faithful assistant", 0.85, 0.30, 0.92, 0.80, 0.10),
    AgentProfile("Summarizing assistant", 0.70, 0.20, 0.45, 0.25, 0.75),
    AgentProfile("Search assistant", 0.65, 0.15, 0.80, 0.95, 0.30),
    AgentProfile("Sponsorship-averse assistant", 0.10, 0.02, 0.95, 0.50, 0.40),
)


@dataclass(frozen=True)
class Answer:
    agent: str
    page_id: str
    query: str
    ad_relevant: bool
    text: str
    # ground truth, known only because we simulated it
    truth_included: bool
    truth_disclosed: bool
    truth_linked: bool


def paraphrase(sentence: str, strength: float, rng: random.Random) -> str:
    words = sentence.split()
    out = []
    for w in words:
        key = re.sub(r"[^a-z]", "", w.lower())
        if key in SYNONYMS and rng.random() < strength:
            out.append(SYNONYMS[key])
        elif rng.random() < strength * 0.25 and len(words) > 8:
            continue  # summarizers drop filler words
        else:
            out.append(w)
    return " ".join(out)


def answer(profile: AgentProfile, page: Page, query: Query, rng: random.Random) -> Answer:
    ad = page.ad
    body = list(page.body)
    rng.shuffle(body)
    parts = [paraphrase(s, profile.paraphrase * 0.5, rng) for s in body[:2]]

    p_inc = profile.p_include_relevant if query.ad_relevant else profile.p_include_irrelevant
    included = rng.random() < p_inc
    disclosed = linked = False
    if included:
        claim = paraphrase(rng.choice(ad.claims), profile.paraphrase, rng)
        ad_part = claim.rstrip(".") + "."
        disclosed = rng.random() < profile.p_keep_disclosure
        linked = rng.random() < profile.p_keep_link
        if disclosed:
            ad_part += " " + rng.choice(DISCLOSURE_STYLES).format(adv=ad.advertiser)
        if linked:
            ad_part += f" [{ad.cta_text}]({ad.click_url})"
        parts.insert(rng.randint(1, len(parts)), ad_part)

    return Answer(
        agent=profile.name,
        page_id=page.page_id,
        query=query.q,
        ad_relevant=query.ad_relevant,
        text=" ".join(parts),
        truth_included=included,
        truth_disclosed=disclosed,
        truth_linked=linked,
    )
