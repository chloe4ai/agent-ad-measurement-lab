# Agent Ad Measurement Lab

**Live dashboard:** https://chloe4ai.github.io/agent-ad-measurement-lab/

When an AI agent fetches a page that carries a sponsored block, the fetch proves only that the page was downloaded. It does not prove the person ever saw the ad. This lab measures what actually reached the person:

- **Inclusion**: did the ad's content make it into the agent's answer?
- **Disclosure survival**: did a sponsorship label stay next to it?
- **Link survival**: did the tracked click URL make it through intact?
- **Traffic quality**: was the fetch made for a live user question, or by a search indexer, a training crawler, or a spoofer?

Display advertising needed viewability before an impression could be trusted. Agent-served ads need the same thing: a measure of what was delivered, not just what was fetched.

## What a run shows

Default run: 4 simulated agents × 600 answers, plus 4,000 traffic sessions (seed 42). Everything in this section is simulated; see [Real answers](#real-answers) for the part that is not.

| Metric | Result |
|---|---|
| Fetched → included → included and labeled → clicked | 2,400 → 836 → 635 → 16 |
| Overcount if impressions are billed on fetch | **3.8×** with equal traffic from each agent (seeds 1–20: 3.4× to 4.0×, median 3.7×); 1.9× to 27.3× depending on the agent |
| End to end: declared user-agent fetches per delivered, labeled answer | 19.4× (12,959 → 2,522 pass traffic rules → about 667 delivered and labeled) |
| Inclusion detector vs simulated ground truth | precision 100.0%, recall 96.9% |
| Disclosure detector on held-out phrasings | precision 53.3%, recall 33.3% (37 hand-written answers) |
| Page fetches declaring a user-agent token that pass billing rules | 19.5% (2,522 of 12,959) |

How to read these:

- **The 3.8× is fetches ÷ answers the detector scored as included and labeled.** That's 2,400 ÷ 635. It assumes every fetch would have been billed as one impression, and it counts only what the detector saw, so a missed inclusion makes the overcount look larger, not smaller.
- **The 3.8× is a property of the agent mix, not of agent traffic in general.** It pools four agents at 600 fetches each. Per agent the figure runs from 1.9× to 27.3×, so the blended number moves with whoever sends the traffic: `python -m lab.run --mix 0.7,0.1,0.1,0.1` (70% from the faithful assistant) gives 2.3×.
- **The end-to-end 19.4× is a projection.** It takes the page fetches that pass the traffic rules and scales them by the answer-level rates, assuming one fetch feeds one answer and that an invalid fetch reaches nobody. The two halves are simulated separately. On the simulator's ground truth the same chain gives 16.6×; the gap is the traffic rules rejecting genuine sessions plus the detector missing some inclusions.
- **Inclusion precision of 100% is by construction.** The simulator never puts the advertiser's name or click URL into an answer that didn't include the ad, and those are two of the detector's three signals. Recall is the number that can move. Real answers mention brands for their own reasons, so real precision will be lower.
- **In-sample disclosure detection is also perfect by construction**: the simulated agents use only six label phrasings, and the detector was written with them in view. On held-out wording it misses most labels (`(Ad)`, `#ad`, "Brought to you by", "affiliate link") and fires on non-labels ("not a sponsor of this article", "paid parking"). See [Held-out check](#held-out-check).

| Agent | Inclusion | Disclosure kept | Link kept | Fetches per delivered, labeled answer | Clicks / 1k fetches |
|---|---|---|---|---|---|
| Faithful assistant | 56.2% | 93.5% | 82.5% | 1.9× | 15.0 |
| Summarizing assistant | 41.2% | 46.2% | 33.6% | 5.3× | 6.7 |
| Search assistant | 38.2% | 80.3% | 97.8% | 3.3× | 5.0 |
| Sponsorship-averse assistant | 3.8% | 95.7% | 43.5% | 27.3× | 0.0 |

Across seeds 1–20 (same sample size), min / median / max:

| Agent | Inclusion | Disclosure kept | Fetches per delivered, labeled answer | Clicks / 1k fetches |
|---|---|---|---|---|
| Faithful assistant | 53.0% / 56.2% / 61.0% | 89.7% / 92.5% / 94.4% | 1.7× / 1.9× / 2.1× | 13.3 / 16.7 / 26.7 |
| Summarizing assistant | 36.3% / 40.3% / 43.5% | 41.4% / 46.0% / 51.0% | 4.5× / 5.4× / 6.2× | 1.7 / 5.0 / 11.7 |
| Search assistant | 36.0% / 39.8% / 45.0% | 73.2% / 79.8% / 87.4% | 2.9× / 3.1× / 3.7× | 10.0 / 15.0 / 25.0 |
| Sponsorship-averse assistant | 4.0% / 5.7% / 7.8% | 87.1% / 96.7% / 100.0% | 13.0× / 17.9× / 26.1× | 0.0 / 1.7 / 3.3 |

Inclusion and disclosure rates are stable. Clicks are not: 16 clicks in a run is too few to rank agents on, and the per-agent click rate moves by a factor of two or more between seeds. The seed-42 figure for the sponsorship-averse assistant (27.3×) sits above its seed 1–20 range because it rests on 22 delivered answers.

What the inclusion detector finds depends on what the agent left in the answer:

| What the answer kept | Answers with the ad | Detected | Recall |
|---|---|---|---|
| Tracked link | 595 | 595 | 100.0% |
| Advertiser name, no link | 174 | 174 | 100.0% |
| Claim wording only | 94 | 67 | 71.3% |

The last row is the agent that passes on the claim but not who made it ("one brand's topper reduces sleeping-surface temp…"). Only word overlap with the original claim catches it, and it misses about three in ten. How often each simulated agent strips the brand is a parameter in `lab/agents.py`, so the size of that row is a modeling choice; the recall within it is not.

Two things stand out:

- **Agents differ more than pages do.** The same sponsored block gets very different delivery depending on which assistant reads it. A summarizing agent keeps the ad's message but drops the label about half the time (it kept it in 41% to 51% of included answers across seeds). That's a disclosure problem for the advertiser and a trust problem for the publisher.
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
lab/page.py              renders a page as the Markdown an agent fetches, in one of four ad markup formats
lab/agents.py            simulated agents: probabilities to include, keep the label, keep the link, paraphrase, strip the brand
lab/detect.py            reads the final answer and decides included / disclosed / linked, with the rule that fired
lab/traffic.py           labeled session log + ordered rules: declared token -> verified source IP -> behaviour
lab/heldout.py           scores the detector on fixtures/heldout.json, hand-written wording it was not tuned on
lab/stats.py             Wilson 95% intervals, precision / recall
lab/run.py               runs everything (seed 42, plus seeds 1-20 for the robustness readout), writes docs/results.json
lab/real.py              optional: collects answers from real models, scores them against human labels
scripts/build_dashboard.py  builds docs/index.html with the results embedded
```

**Inclusion detection** uses three signals in order of strength: the tracked click URL, the advertiser's name, and claim overlap (the share of a claim's content words found in the answer, threshold 0.5). Overlap catches paraphrased ads even when the agent strips both the name and the link. Every detection records which signal fired, so results can be audited.

**Disclosure detection** looks for sponsorship language in the sentences that carry the ad (the ones with the link or the advertiser's name, or failing both, the sentence closest to a claim) and the sentence on either side. A label elsewhere in the answer does not count. URLs are masked first, so an id like `ad-luma-07` inside a link never counts as a label.

**Traffic classification** is a set of transparent rules, not a black-box model, because billing decisions have to be explainable to buyers and sellers:

1. A request that claims a known AI token but comes from an IP outside that operator's published range is **invalid**.
2. A verified user-agent token (`ChatGPT-User`, `Claude-User`, `Perplexity-User`) with a question-sized session (at most 5 pages by default) is **billable**. The same token crawling in bulk, fetching `robots.txt`, or hammering click URLs is **invalid**.
3. Verified indexer and training tokens are counted but never billed.
4. A browser user agent fetching at crawler speed with no referer is flagged as a **stealth scraper**.

## Held-out check

The simulated agents only ever write six label phrasings, so in-sample disclosure scores say little. `fixtures/heldout.json` has 37 hand-written answers that name the advertiser with other wording: 24 with a real label and 13 without one, including near-misses. It also has 20 answers with no advertiser name or link: 11 paraphrase a claim and 9 do not.

| Detector | Held-out answers | Precision | Recall |
|---|---|---|---|
| Disclosure | 37 | 53.3% | 33.3% |
| Inclusion (no name or link) | 20 | 100.0% | 45.5% |

The disclosure rule is a keyword list, and it shows: it misses labels that don't use its words and can't read negation. Claim overlap catches paraphrases that keep the claim's nouns and misses ones that reword them ("a cooling pad for your bed" for "cooling mattress topper"). The detector's vocabulary was not changed to fit this set. The set was written by the people who worked on the detector, so it is a stress test, not a substitute for labeled real answers.

`python -m lab.real judge-heldout` runs a model-graded disclosure check on the same 37 answers, for comparison with the keyword rule. It calls a real model, so its result is not committed here.

## Real answers

Every number above follows from probabilities typed into `lab/agents.py`. `lab/real.py` replaces that half with real model answers:

```bash
pip install anthropic                                  # optional; the lab itself needs no packages
python -m lab.real collect --dry-run                   # 48 calls per model: 4 ad formats × 12 questions. No spend.
python -m lab.real collect --models claude-opus-5-5    # appends to fixtures/real_answers.jsonl; re-running resumes
# hand-label "human": {"included": ..., "disclosed": ...} on each line of that file
python -m lab.real score                               # rates per model and ad format; detector vs your labels
```

The model gets the fixture page and one of its questions, with no instruction about advertising. The page is rendered in each of four **ad markup formats**, which is the variable a publisher controls:

| Format | How the sponsored block is marked |
|---|---|
| `comment-blockquote` | HTML comment markers around a quoted block; one label at the top (the default everywhere else in the lab) |
| `inline-label` | "Sponsored by …" inside every claim sentence, so quoting any one claim carries the label |
| `json-ld` | Structured data only; nothing in the prose says the block is paid |
| `unmarked` | Control: the ad written as ordinary article text |

`score` reports inclusion, label survival, link survival and the fetch overcount per model and format, plus the detector's precision and recall against the human labels and every answer where the two disagree.

### First real run

48 answers from `claude-opus-5-5`, one per question and format, in `fixtures/real_answers.jsonl`. The labels are a first-pass draft (`"labeler": "draft"`) and have not been reviewed by a person.

| Ad markup format | Answers | Mention the ad | Name the advertiser | Say it is paid | Discount it | Keep the link |
|---|---|---|---|---|---|---|
| `comment-blockquote` | 12 | 2 | 1 | 2 | 2 | 0 |
| `inline-label` | 12 | 5 | 2 | 5 | 5 | 0 |
| `json-ld` | 12 | 3 | 1 | 3 | 3 | 0 |
| `unmarked` | 12 | 3 | 3 | 3 | 3 | 0 |

What it shows:

- **The model behaved like none of the four simulated agents.** It never passed on a claim as advice. When it mentioned the ad at all (13 of 48 answers), it told the reader the page carried a paid ad and to weigh it accordingly: "The page I found included a sponsored ad for one such service (VoltCheck), but that was paid advertising, not an independent recommendation." All 13 mentions said the ad was paid, including the 3 from the `unmarked` page, where nothing in the page said so.
- **No answer kept the tracked link**, so no answer could produce a click.
- **"Included" is too coarse a measure.** By the lab's definition those 13 answers include the ad and label it. An advertiser would not count "you don't need it" as a delivered impression. The labels therefore carry a third field, `framing` (`passed on`, `neutral`, `discounted`), and all 13 are `discounted`. The simulator has no such behaviour and its overcount figures do not account for it.
- **The detector found 7 of the 13 mentions**, the ones that name the advertiser, and none of the 6 that describe the ad without naming it ("a sponsored ad for a pasta kit"). No false positives. Among the 7, it missed one label ("that's an ad").
- **Nothing can be said about formats.** With 12 answers each, 2 to 5 mentions per format is within noise.

This is one model, one run, 48 answers and unreviewed labels.

Two limits on what this will show. The model is handed the page in the prompt; a shipped assistant adds its own retrieval, system prompt and post-processing, so the answers describe a model, not a product. And 12 questions per format is enough to see large differences only; use `--repeats` for more.

## Who would use this

- **Publishers** selling sponsored placements on pages agents read: which markup keeps the label attached, and what to bill on.
- **Advertisers and agencies**: how many fetches stand behind one delivered, labeled mention, per assistant.
- **Verification vendors**: a worked definition of a delivered agent impression (valid fetch, ad included, label kept) and the validation each step needs.

## Run it

```bash
python -m lab.run                      # writes docs/results.json and prints a summary
python scripts/build_dashboard.py      # writes docs/index.html
python -m pytest -q                    # 35 tests
```

Python 3.10+, standard library only (pytest for tests). `python -m lab.run --n 2000 --seed 1` changes sample size and seed; `--mix 0.5,0.2,0.2,0.1` sets each agent's share of fetches. CI regenerates `docs/results.json` and fails if it differs from the committed file, and a test checks that the headline numbers in this README match it.

## Limitations

- All data is simulated. The in-sample detector numbers are validated against the simulator's ground truth, which uses a known set of label phrasings; the held-out set shows how much lower they fall on other wording. Real deployment needs a hand-labeled sample of real agent answers to measure precision and recall honestly.
- Clicks are a fixed 4% chance per answer with a surviving link, so click counts are small and noisy (see the seed ranges).
- Real source verification uses each operator's published IP ranges or reverse DNS, or a signed request; here it is a boolean on the session.
- The traffic rules and the answer funnel are simulated separately and joined by multiplying rates. Sessions do not produce answers.
- The traffic classes are this lab's own. They are not mapped to an industry invalid-traffic taxonomy.
- Claim overlap is lexical. Heavy semantic paraphrase would need an embedding or model-graded check, and that check would need its own validation set.

Publishers, advertisers and products in the fixtures are fictional.
