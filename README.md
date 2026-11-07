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
| Fetched → included → included and labeled → clicked | 2,400 → 891 → 685 → 24 |
| Overcount if impressions are billed on fetch | **3.5×** (seeds 1–20: 3.4× to 3.9×, median 3.6×) |
| Inclusion detector vs simulated ground truth | precision 100.0%, recall 99.1% |
| Disclosure detector on held-out phrasings | precision 50.0%, recall 28.6% (21 hand-written answers) |
| Page fetches declaring a user-agent token that pass billing rules | 19.5% (2,522 of 12,959) |

How to read these:

- **The 3.5× is fetches ÷ answers the detector scored as included and labeled.** That's 2,400 ÷ 685. It assumes every fetch would have been billed as one impression, and it counts only what the detector saw, so a missed inclusion makes the overcount look larger, not smaller.
- **Inclusion precision of 100% is by construction.** The simulator never puts the advertiser's name or click URL into an answer that didn't include the ad, and those are two of the detector's three signals. Recall is the number that can move. Real answers mention brands for their own reasons, so real precision will be lower.
- **In-sample disclosure detection is also near perfect by construction**: the simulated agents use only three label phrasings, and the detector was written with them in view. On held-out wording it misses most labels (`(Ad)`, `#ad`, "Brought to you by", "affiliate link") and fires on non-labels ("not a sponsor of this article", "paid parking"). See [Held-out check](#held-out-check).

| Agent | Inclusion | Disclosure kept | Link kept | Clicks / 1k fetches |
|---|---|---|---|---|
| Faithful assistant | 57.2% | 91.5% | 81.0% | 18.3 |
| Summarizing assistant | 43.0% | 50.4% | 21.7% | 5.0 |
| Search assistant | 42.5% | 81.2% | 93.7% | 15.0 |
| Sponsorship-averse assistant | 5.8% | 97.1% | 57.1% | 1.7 |

Across seeds 1–20 (same sample size), min / median / max:

| Agent | Inclusion | Disclosure kept | Clicks / 1k fetches |
|---|---|---|---|
| Faithful assistant | 52.7% / 58.3% / 61.8% | 88.0% / 91.6% / 94.7% | 10.0 / 18.3 / 30.0 |
| Summarizing assistant | 39.2% / 43.6% / 49.3% | 37.4% / 45.9% / 54.4% | 0.0 / 4.2 / 10.0 |
| Search assistant | 34.7% / 39.7% / 42.5% | 75.0% / 79.5% / 83.8% | 5.0 / 15.0 / 25.0 |
| Sponsorship-averse assistant | 4.5% / 6.2% / 8.3% | 90.3% / 96.8% / 100.0% | 0.0 / 0.0 / 5.0 |

Inclusion and disclosure rates are stable. Clicks are not: 24 clicks in a run is too few to rank agents on, and the per-agent click rate moves by a factor of two or more between seeds.

Two things stand out:

- **Agents differ more than pages do.** The same sponsored block gets very different delivery depending on which assistant reads it. A summarizing agent keeps the ad's message but drops the label about half the time (it kept it in 37% to 54% of included answers across seeds). That's a disclosure problem for the advertiser and a trust problem for the publisher.
- **Where to set the page-count rule is a business decision.** Spoofers that fake an assistant's token are easy: all 240 in the log come from IPs outside the operator's range and the IP rule rejects every one. The hard case is relayed traffic, scripted sessions pushed through a real assistant, so the IP checks out (136 sessions). Only behaviour catches those, and the main signal is how many pages a session fetches, which overlaps with genuine research-style questions:

| Max pages per user session | Genuine sessions rejected | Invalid sessions billed | Invalid page fetches billed | Billable vs truth |
|---|---|---|---|---|
| 3 | 15.4% | 5 | 15 | −35.6% |
| 4 | 9.4% | 6 | 19 | −24.1% |
| **5 (default)** | **4.8%** | **10** | **39** | **−12.6%** |
| 6 | 2.9% | 12 | 51 | −6.6% |
| 8 | 1.6% | 18 | 96 | −0.7% |
| 10 | 1.0% | 29 | 199 | +5.5% |
| 15 | 1.0% | 40 | 344 | +10.9% |
| 20 | 1.0% | 57 | 653 | +21.6% |

  The default of 5 bills 39 invalid page fetches but lands 12.6% below the true billable volume (−12.9% to −17.5% across seeds). A threshold of 8 gets the total almost exactly right, but only because about 96 invalid fetches billed offset about 116 genuine ones lost; that's two errors cancelling, not accuracy. About 1% of genuine sessions are rejected at any threshold because their source IP fails verification. The genuine and relayed page-count distributions are modeling choices (genuine: mostly 1–3 pages with a long tail up to 20; relayed: 3–40), so the table shows the shape of the trade-off, not real-world rates.

## How it works

```
fixtures/pages.json      fictional publisher pages, each with one sponsored block and user queries
lab/page.py              renders a page as the Markdown an agent fetches, ad wrapped in <!-- agent-ad --> markers
lab/agents.py            simulated agents: probabilities to include, keep the label, keep the link, paraphrase
lab/detect.py            reads the final answer and decides included / disclosed / linked, with the rule that fired
lab/traffic.py           labeled session log + ordered rules: declared token -> verified source IP -> behaviour
lab/heldout.py           scores the detector on fixtures/heldout.json, hand-written wording it was not tuned on
lab/stats.py             Wilson 95% intervals, precision / recall
lab/run.py               runs everything (seed 42, plus seeds 1-20 for the robustness readout), writes docs/results.json
scripts/build_dashboard.py  builds docs/index.html with the results embedded
```

**Inclusion detection** uses three signals in order of strength: the tracked click URL, the advertiser's name, and claim overlap (the share of a claim's content words found in the answer, threshold 0.5). Overlap catches paraphrased ads even when the agent strips both the name and the link. Every detection records which signal fired, so results can be audited.

**Disclosure detection** looks for sponsorship language within a window around the ad mention. URLs are masked first, so an id like `ad-luma-07` inside a link never counts as a label.

**Traffic classification** is a set of transparent rules, not a black-box model, because billing decisions have to be explainable to buyers and sellers:

1. A request that claims a known AI token but comes from an IP outside that operator's published range is **invalid**.
2. A verified user-agent token (`ChatGPT-User`, `Claude-User`, `Perplexity-User`) with a question-sized session (at most 5 pages by default) is **billable**. The same token crawling in bulk, fetching `robots.txt`, or hammering click URLs is **invalid**.
3. Verified indexer and training tokens are counted but never billed.
4. A browser user agent fetching at crawler speed with no referer is flagged as a **stealth scraper**.

## Held-out check

The simulated agents only ever write three label phrasings, so in-sample disclosure scores say little. `fixtures/heldout.json` has 21 hand-written answers that name the advertiser with other wording: 14 with a real label and 7 without one, including near-misses. It also has 10 claim paraphrases that drop the advertiser's name and link.

| Detector | Held-out answers | Precision | Recall |
|---|---|---|---|
| Disclosure | 21 | 50.0% | 28.6% |
| Inclusion (no name or link) | 10 | 100.0% | 50.0% |

The disclosure rule is a keyword list, and it shows: it misses labels that don't use its words and can't read negation. Claim overlap catches paraphrases that keep the claim's nouns and misses ones that reword them ("a cooling pad for your bed" for "cooling mattress topper"). The detector was not changed to fit this set. The set was written by the same author who wrote the detector, so it is a stress test, not a substitute for labeled real answers.

## Run it

```bash
python -m lab.run                      # writes docs/results.json and prints a summary
python scripts/build_dashboard.py      # writes docs/index.html
python -m pytest -q                    # 22 tests
```

Python 3.10+, standard library only (pytest for tests). `python -m lab.run --n 2000 --seed 1` changes sample size and seed. CI regenerates `docs/results.json` and fails if it differs from the committed file, and a test checks that the headline numbers in this README match it.

## Limitations

- All data is simulated. The in-sample detector numbers are validated against the simulator's ground truth, which uses a known set of label phrasings; the held-out set shows how much lower they fall on other wording. Real deployment needs a hand-labeled sample of real agent answers to measure precision and recall honestly.
- Clicks are a fixed 4% chance per answer with a surviving link, so click counts are small and noisy (see the seed ranges).
- Real source verification uses each operator's published IP ranges or reverse DNS; here it is a boolean on the session.
- Claim overlap is lexical. Heavy semantic paraphrase would need an embedding or model-graded check, and that check would need its own validation set.

Publishers, advertisers and products in the fixtures are fictional.
