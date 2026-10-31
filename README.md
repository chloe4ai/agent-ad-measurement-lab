# Agent Ad Measurement Lab

**Live dashboard:** https://chloe4ai.github.io/agent-ad-measurement-lab/

When an AI agent fetches a page that carries a sponsored block, the fetch proves only that the page was downloaded. It does not prove the person ever saw the ad. This lab measures what actually reached the person:

- **Inclusion**: did the ad's content make it into the agent's answer?
- **Disclosure survival**: did a sponsorship label stay next to it?
- **Link survival**: did the tracked click URL make it through intact?
- **Traffic quality**: was the fetch made for a live user question, or by a search indexer, a training crawler, or a spoofer?

Display advertising needed viewability before an impression could be trusted. Agent-served ads need the same thing: a measure of what was delivered, not just what was fetched.

## What a run shows

Default run: 4 simulated agents × 600 answers, plus 4,000 traffic sessions (seed 42).

| Metric | Result |
|---|---|
| Fetched → included → included and labeled → clicked | 2,400 → 855 → 637 → 32 |
| Overcount if impressions are billed on fetch | **3.8×** |
| Inclusion detector vs ground truth | precision 100.0%, recall 99.5% |
| Page fetches declaring a user-agent token that pass billing rules | 23.4% (2,827 of 12,065) |

| Agent | Inclusion | Disclosure kept | Link kept | Clicks / 1k fetches |
|---|---|---|---|---|
| Faithful assistant | 56.5% | 92.3% | 82.6% | 26.7 |
| Summarizing assistant | 43.7% | 44.7% | 27.5% | 5.0 |
| Search assistant | 37.5% | 79.1% | 96.0% | 20.0 |
| Sponsorship-averse assistant | 4.8% | 100.0% | 51.7% | 1.7 |

Two things stand out:

- **Agents differ more than pages do.** The same sponsored block gets very different delivery depending on which assistant reads it. A summarizing agent keeps the ad's message but drops the label more than half the time. That's a disclosure problem for the advertiser and a trust problem for the publisher.
- **Strict traffic rules cost real impressions.** The rules flag every declared user agent that fetches more than 5 pages as a crawler. That catches every spoofer, but it also rejects about 6% of genuine user sessions, so billable volume lands 15% below the true figure. Where to set that threshold is a business decision, not just a modeling one.

## How it works

```
fixtures/pages.json      fictional publisher pages, each with one sponsored block and user queries
lab/page.py              renders a page as the Markdown an agent fetches, ad wrapped in <!-- agent-ad --> markers
lab/agents.py            simulated agents: probabilities to include, keep the label, keep the link, paraphrase
lab/detect.py            reads the final answer and decides included / disclosed / linked, with the rule that fired
lab/traffic.py           labeled session log + ordered rules: declared token -> verified source IP -> behaviour
lab/stats.py             Wilson 95% intervals, precision / recall
lab/run.py               runs everything, writes docs/results.json
scripts/build_dashboard.py  builds docs/index.html with the results embedded
```

**Inclusion detection** uses three signals in order of strength: the tracked click URL, the advertiser's name, and claim overlap (the share of a claim's content words found in the answer, threshold 0.5). Overlap catches paraphrased ads even when the agent strips both the name and the link. Every detection records which signal fired, so results can be audited.

**Disclosure detection** looks for sponsorship language within a window around the ad mention. URLs are masked first, so an id like `ad-luma-07` inside a link never counts as a label.

**Traffic classification** is a set of transparent rules, not a black-box model, because billing decisions have to be explainable to buyers and sellers:

1. A request that claims a known AI token but comes from an IP outside that operator's published range is **invalid**.
2. A verified user-agent token (`ChatGPT-User`, `Claude-User`, `Perplexity-User`) with a question-sized session is **billable**. The same token crawling in bulk, fetching `robots.txt`, or hammering click URLs is **invalid**.
3. Verified indexer and training tokens are counted but never billed.
4. A browser user agent fetching at crawler speed with no referer is flagged as a **stealth scraper**.

## Run it

```bash
python -m lab.run                      # writes docs/results.json and prints a summary
python scripts/build_dashboard.py      # writes docs/index.html
python -m pytest -q                    # 14 tests
```

Python 3.10+, standard library only (pytest for tests). `python -m lab.run --n 2000 --seed 1` changes sample size and seed.

## Limitations

- All data is simulated. The detectors are validated against the simulator's ground truth, which uses a known set of label phrasings. Real deployment needs a hand-labeled sample of real agent answers to measure precision and recall honestly.
- Real source verification uses each operator's published IP ranges or reverse DNS; here it is a boolean on the session.
- Claim overlap is lexical. Heavy semantic paraphrase would need an embedding or model-graded check, and that check would need its own validation set.

Publishers, advertisers and products in the fixtures are fictional.
