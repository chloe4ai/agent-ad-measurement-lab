"""Traffic quality: which agent fetches are worth billing?

Not every request with an AI user agent is a person asking a question. Search
indexers and training crawlers fetch pages in bulk, and spoofers copy an
assistant's user-agent string to inflate impressions or clicks. Spoofers that
fake the token fail the source-IP check. Harder are relayed sessions: scripted
traffic pushed through a real assistant, so the IP checks out and only session
behaviour (how many pages, how fast, click hammering) can catch it. Only a fetch
made on behalf of a live user question should count as an agent impression.

This module generates a labeled synthetic session log and classifies it with
transparent, auditable rules (declared token -> verified source -> behaviour).
"""
from __future__ import annotations

import random
from dataclasses import dataclass

USER_TOKENS = ("ChatGPT-User", "Claude-User", "Perplexity-User")
INDEX_TOKENS = ("OAI-SearchBot", "Claude-SearchBot", "PerplexityBot")
TRAIN_TOKENS = ("GPTBot", "ClaudeBot", "CCBot", "Bytespider")
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 Safari/605.1.15"

CLASSES = ("user_agent", "search_indexer", "training_crawler", "invalid", "human_browser")
CLASS_LABELS = {
    "user_agent": "User-initiated agent fetch",
    "search_indexer": "Search indexer",
    "training_crawler": "Training crawler",
    "invalid": "Invalid (spoofed or stealth)",
    "human_browser": "Human browser",
}


@dataclass(frozen=True)
class Session:
    ua: str
    ip_verified: bool      # reverse-DNS / published IP range matches the declared operator
    pages: int             # distinct pages fetched in the session
    robots_fetched: bool   # requested /robots.txt
    median_gap_s: float    # median seconds between requests
    click_hits: int        # requests to tracked /c/ click URLs
    has_referer: bool
    truth: str             # ground-truth class (simulation only)


def _ua(token: str) -> str:
    return f"Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; {token}/1.0"


def generate(n: int = 4000, seed: int = 7) -> list[Session]:
    rng = random.Random(seed)
    mix = (("user_agent", 0.34), ("search_indexer", 0.14), ("training_crawler", 0.16),
           ("spoofed", 0.06), ("relayed", 0.03), ("stealth", 0.05), ("human_browser", 0.22))
    out: list[Session] = []
    for _ in range(n):
        r, acc, kind = rng.random(), 0.0, mix[-1][0]
        for k, w in mix:
            acc += w
            if r < acc:
                kind = k
                break
        if kind == "user_agent":
            # Most questions need a page or two; research-style questions have a
            # long tail of more pages. Capped at 20.
            pages = min(1 + int(rng.expovariate(1 / 1.6)), 20)
            out.append(Session(_ua(rng.choice(USER_TOKENS)), rng.random() > 0.01, pages, False,
                               rng.uniform(0.8, 6.0), int(rng.random() < 0.05), False, "user_agent"))
        elif kind == "search_indexer":
            out.append(Session(_ua(rng.choice(INDEX_TOKENS)), True, rng.randint(15, 400),
                               rng.random() < 0.9, rng.uniform(0.2, 2.0), 0, False, "search_indexer"))
        elif kind == "training_crawler":
            out.append(Session(_ua(rng.choice(TRAIN_TOKENS)), rng.random() > 0.06,
                               rng.randint(40, 2000), rng.random() < 0.85, rng.uniform(0.05, 1.0),
                               0, False, "training_crawler"))
        elif kind == "spoofed":
            out.append(Session(_ua(rng.choice(USER_TOKENS)), False, rng.randint(1, 60),
                               False, rng.uniform(0.05, 3.0), rng.randint(0, 12), False, "invalid"))
        elif kind == "relayed":
            # Scripted traffic driven through a real assistant: the request really
            # comes from the operator's IPs with a user token, so source checks
            # pass. Only behaviour gives it away, and small batches look like a
            # curious person.
            out.append(Session(_ua(rng.choice(USER_TOKENS)), True, rng.randint(3, 40), False,
                               rng.uniform(0.3, 3.0), rng.randint(0, 3), False, "invalid"))
        elif kind == "stealth":
            out.append(Session(BROWSER_UA, False, rng.randint(40, 600), False,
                               rng.uniform(0.02, 0.6), rng.randint(0, 3), False, "invalid"))
        else:
            out.append(Session(BROWSER_UA, False, rng.randint(1, 8), False,
                               rng.uniform(5, 90), int(rng.random() < 0.03), True, "human_browser"))
    return out


def _token(ua: str) -> tuple[str, str] | None:
    for table, family in ((USER_TOKENS, "user"), (INDEX_TOKENS, "index"), (TRAIN_TOKENS, "train")):
        for t in table:
            if t in ua:
                return t, family
    return None


MAX_USER_PAGES = 5  # default: a verified user token fetching more pages than this is treated as a crawler
SWEEP_THRESHOLDS = (3, 4, 5, 6, 8, 10, 15, 20)


def classify(s: Session, max_user_pages: int = MAX_USER_PAGES) -> tuple[str, str]:
    """Return (class, reason). Rules run in order; the first match wins."""
    tok = _token(s.ua)
    if tok:
        token, family = tok
        if not s.ip_verified:
            return "invalid", f"declares {token} but source IP is not the operator's"
        if family == "user":
            if s.pages > max_user_pages or s.robots_fetched or s.click_hits > 2:
                return "invalid", f"{token} declared, but behaves like a crawler"
            return "user_agent", f"verified {token}, question-sized session"
        if family == "index":
            return "search_indexer", f"verified {token}"
        return "training_crawler", f"verified {token}"
    if s.pages > 30 and not s.has_referer and s.median_gap_s < 1.0:
        return "invalid", "browser UA, crawler-speed bulk fetch, no referer"
    return "human_browser", "browser UA, human pacing"


def threshold_sweep(sessions: list[Session], thresholds=SWEEP_THRESHOLDS) -> list[dict]:
    """What each page-count threshold costs in genuine sessions and lets through in invalid ones."""
    genuine = [s for s in sessions if s.truth == "user_agent"]
    truly_billable = sum(s.pages for s in genuine)
    rows = []
    for th in thresholds:
        billed = [s for s in sessions if classify(s, th)[0] == "user_agent"]
        bad = [s for s in billed if s.truth != "user_agent"]
        billable = sum(s.pages for s in billed)
        rows.append({
            "max_user_pages": th,
            "genuine_sessions_rejected": sum(classify(s, th)[0] != "user_agent" for s in genuine) / len(genuine)
            if genuine else 0.0,
            "invalid_sessions_billed": len(bad),
            "invalid_page_fetches_billed": sum(s.pages for s in bad),
            "billable_after_rules": billable,
            "billable_vs_truth": billable / truly_billable - 1 if truly_billable else None,
        })
    return rows


def evaluate(sessions: list[Session]) -> dict:
    confusion = {t: {p: 0 for p in CLASSES} for t in CLASSES}
    for s in sessions:
        pred, _ = classify(s)
        confusion[s.truth][pred] += 1

    per_class = {}
    for c in CLASSES:
        tp = confusion[c][c]
        fp = sum(confusion[t][c] for t in CLASSES if t != c)
        fn = sum(confusion[c][p] for p in CLASSES if p != c)
        per_class[c] = {
            "label": CLASS_LABELS[c],
            "truth": sum(confusion[c].values()),
            "predicted": sum(confusion[t][c] for t in CLASSES),
            "precision": tp / (tp + fp) if tp + fp else 0.0,
            "recall": tp / (tp + fn) if tp + fn else 0.0,
        }

    declared_ai = [s for s in sessions if _token(s.ua)]
    naive_impressions = sum(s.pages for s in declared_ai)
    naive_user_claims = sum(s.pages for s in sessions if (_token(s.ua) or ("", ""))[1] == "user")
    billable = sum(s.pages for s in sessions if classify(s)[0] == "user_agent")
    truly_billable = sum(s.pages for s in sessions if s.truth == "user_agent")
    return {
        "sessions": len(sessions),
        "confusion": confusion,
        "per_class": per_class,
        "page_fetches": {
            "all_declared_ai": naive_impressions,
            "declared_user_agent": naive_user_claims,
            "billable_after_rules": billable,
            "truly_billable": truly_billable,
            "invalid_billed": sum(s.pages for s in sessions
                                  if classify(s)[0] == "user_agent" and s.truth != "user_agent"),
        },
        "rule_attribution": {
            "spoofed_caught_by_ip_rule": sum(1 for s in sessions if s.truth == "invalid" and _token(s.ua)
                                             and not s.ip_verified),
            "verified_invalid_sessions": sum(1 for s in sessions if s.truth == "invalid" and _token(s.ua)
                                             and s.ip_verified),
        },
        "max_user_pages": MAX_USER_PAGES,
        "threshold_sweep": threshold_sweep(sessions),
    }
