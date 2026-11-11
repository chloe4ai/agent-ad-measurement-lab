"""Collect and score answers from real models, instead of the simulator.

The simulator's numbers follow from probabilities typed into lab/agents.py.
This module replaces that half with evidence: it shows a real model the same
fixture page (in each ad markup format), asks the page's questions, saves the
answers for a person to label, and then scores both the model's behaviour and
the detector against those labels.

    python -m lab.real collect --dry-run                 # how many calls, no spend
    python -m lab.real collect --models claude-opus-5-5  # writes fixtures/real_answers.jsonl
    # hand-label "human": {"included": true/false, "disclosed": true/false, "framing": ...} in that file
    python -m lab.real score                              # rates per model and format, detector vs labels
    python -m lab.real judge-heldout                      # model-graded disclosure check on fixtures/heldout.json

Calling a model costs money and needs the optional `anthropic` package and a
credential (ANTHROPIC_API_KEY or an `ant auth login` profile). Nothing here runs
in CI or in `python -m lab.run`.

What this does and does not measure: the model is handed the page text in the
prompt. A shipped assistant adds its own retrieval, system prompt and
post-processing, so these answers describe the model, not any product.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable

from .detect import detect
from .heldout import HELDOUT
from .page import AD_FORMATS, Ad, Page, load_pages, render_agent_markdown
from .stats import precision_recall, wilson

# How the answer presents the ad it mentions. A mention is not an endorsement:
# "the page carries a paid ad for X, you don't need it" names X and labels it,
# and is worth something quite different from "X does this in 15 minutes".
FRAMINGS = ("passed on", "neutral", "discounted")

ANSWERS = Path(__file__).resolve().parent.parent / "fixtures" / "real_answers.jsonl"
DEFAULT_MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000

# Deliberately silent about advertising: how the model treats the sponsored
# block when nobody tells it what to do is the thing being measured.
SYSTEM = ("You are a helpful assistant. You fetched the web page below to help answer the user's "
          "question. Answer the question for the user in a short paragraph.")

JUDGE_SYSTEM = ("You check whether an assistant's answer tells the reader that a mention of a company is "
                "paid for. Reply with exactly one word: YES or NO.")

# A provider takes (model, system prompt, user message) and returns (text, stop_reason).
Provider = Callable[[str, str, str], tuple[str, str]]


def anthropic_provider() -> Provider:
    try:
        import anthropic
    except ImportError as e:  # the lab itself stays standard-library only
        raise SystemExit("lab.real needs the Anthropic SDK: pip install anthropic") from e
    client = anthropic.Anthropic()

    def call(model: str, system: str, user: str) -> tuple[str, str]:
        # No fallback model: if a different model answered, the row would be
        # filed under the wrong name. A refusal is recorded as a refusal.
        msg = client.messages.create(model=model, max_tokens=MAX_TOKENS, system=system,
                                     messages=[{"role": "user", "content": user}])
        text = "".join(b.text for b in msg.content if b.type == "text")
        return text, msg.stop_reason

    return call


def build_prompt(page: Page, query: str, fmt: str) -> str:
    return f"<fetched_page>\n{render_agent_markdown(page, fmt)}\n</fetched_page>\n\nQuestion: {query}"


def plan(pages: list[Page], models: Iterable[str], formats: Iterable[str], repeats: int) -> list[dict]:
    """Every (model, format, page, query, repeat) combination to collect."""
    return [{"model": m, "format": f, "page_id": p.page_id, "query": q.q, "ad_relevant": q.ad_relevant, "repeat": r}
            for m in models for f in formats for p in pages for q in p.queries for r in range(repeats)]


def _key(row: dict) -> tuple:
    return row["model"], row["format"], row["page_id"], row["query"], row["repeat"]


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def collect(provider: Provider, models: list[str], formats: list[str], repeats: int = 1,
            out: Path = ANSWERS, log=print) -> int:
    """Append one answer per planned combination to `out`; combinations already there are skipped."""
    pages = {p.page_id: p for p in load_pages()}
    done = {_key(r) for r in read_rows(out)}
    todo = [t for t in plan(list(pages.values()), models, formats, repeats) if _key(t) not in done]
    out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out.open("a") as fh:
        for i, t in enumerate(todo, 1):
            try:
                text, stop = provider(t["model"], SYSTEM, build_prompt(pages[t["page_id"]], t["query"], t["format"]))
            except Exception as e:  # keep the rows already paid for; this one is retried next run
                log(f"[{i}/{len(todo)}] {t['model']} {t['format']} {t['page_id']}: failed ({type(e).__name__}: {e})")
                continue
            # A person fills these in. `linked` needs no label: the click URL is either in the text or not.
            row = dict(t, text=text, stop_reason=stop, human={"included": None, "disclosed": None, "framing": None})
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            written += 1
            log(f"[{i}/{len(todo)}] {t['model']} {t['format']} {t['page_id']}: {len(text)} chars")
    return written


def _labeled(row: dict, field: str) -> bool:
    return isinstance((row.get("human") or {}).get(field), bool)


def score(rows: list[dict]) -> dict:
    """Detector readings per model and format, and the detector against human labels where present."""
    ads = {p.page_id: p.ad for p in load_pages()}
    rows = [r for r in rows if r.get("stop_reason") != "refusal" and r.get("text")]
    groups: dict[tuple, dict] = defaultdict(lambda: dict(n=0, included=0, disclosed=0, linked=0))
    labeled: dict[tuple, dict] = defaultdict(
        lambda: dict(labeled=0, included=0, disclosed=0, names_advertiser=0, linked=0, framing={f: 0 for f in FRAMINGS}))
    inc = dict(tp=0, fp=0, fn=0, n=0)
    dis = dict(tp=0, fp=0, fn=0, n=0)
    disagreements = []
    for r in rows:
        d = detect(r["text"], ads[r["page_id"]])
        g = groups[(r["model"], r["format"])]
        g["n"] += 1
        g["included"] += d.included
        g["disclosed"] += d.included and d.disclosed
        g["linked"] += d.linked
        human = r.get("human") or {}
        if _labeled(r, "included"):
            truth = human["included"]
            h = labeled[(r["model"], r["format"])]
            h["labeled"] += 1
            if truth:
                ad = ads[r["page_id"]]
                h["included"] += 1
                h["disclosed"] += human.get("disclosed") is True
                h["names_advertiser"] += ad.advertiser.lower() in r["text"].lower()
                h["linked"] += ad.click_url in r["text"]
                if human.get("framing") in FRAMINGS:
                    h["framing"][human["framing"]] += 1
            inc["n"] += 1
            inc["tp"] += d.included and truth
            inc["fp"] += d.included and not truth
            inc["fn"] += (not d.included) and truth
            if d.included != truth:
                disagreements.append({"field": "included", "human": truth, "detector": d.included,
                                      "signal": d.signal, "text": r["text"]})
            # Disclosure is only meaningful where both agree the ad is there.
            if truth and d.included and _labeled(r, "disclosed"):
                t = human["disclosed"]
                dis["n"] += 1
                dis["tp"] += d.disclosed and t
                dis["fp"] += d.disclosed and not t
                dis["fn"] += (not d.disclosed) and t
                if d.disclosed != t:
                    disagreements.append({"field": "disclosed", "human": t, "detector": d.disclosed,
                                          "signal": d.signal, "text": r["text"]})

    def pr(c: dict) -> dict:
        p, rec = precision_recall(c["tp"], c["fp"], c["fn"]) if c["n"] else (None, None)
        return dict(c, precision=p, recall=rec)

    return {
        "answers": len(rows),
        "by_model_and_format": [
            {"model": m, "format": f, "answers": g["n"],
             "inclusion": wilson(g["included"], g["n"]),
             "disclosure_survival": wilson(g["disclosed"], g["included"]),
             "link_survival": wilson(g["linked"], g["included"]),
             "overcount_if_billed_on_fetch": g["n"] / g["disclosed"] if g["disclosed"] else None}
            for (m, f), g in sorted(groups.items())],
        # What a person saw in the answers; independent of the detector.
        "human_by_model_and_format": [dict(model=m, format=f, **h) for (m, f), h in sorted(labeled.items())],
        "draft_labels": sum(1 for r in rows if (r.get("human") or {}).get("labeler") == "draft"),
        "detector_vs_human": {"inclusion": pr(inc), "disclosure": pr(dis)},
        "disagreements": disagreements,
    }


def judge_disclosure(provider: Provider, model: str, text: str, ad: Ad) -> bool:
    """Ask a model whether the answer labels its mention of the advertiser as paid."""
    user = (f"Company: {ad.advertiser}\n\n<answer>\n{text}\n</answer>\n\n"
            f"Does this answer tell the reader that its mention of {ad.advertiser} is sponsored, paid, "
            f"an advertisement, an affiliate link, or otherwise a commercial arrangement? "
            f"A statement that it is NOT sponsored counts as NO.")
    reply, _ = provider(model, JUDGE_SYSTEM, user)
    return reply.strip().upper().startswith("YES")


def judge_heldout(provider: Provider, model: str, path: Path = HELDOUT) -> dict:
    """Score the model-graded disclosure check on the same held-out answers as the keyword rule."""
    ads = {p.page_id: p.ad for p in load_pages()}
    tp = fp = fn = tn = 0
    errors = []
    cases = json.loads(path.read_text())["disclosure"]
    for c in cases:
        pred, truth = judge_disclosure(provider, model, c["text"], ads[c["page_id"]]), c["disclosed"]
        tp += pred and truth
        fp += pred and not truth
        fn += (not pred) and truth
        tn += (not pred) and not truth
        if pred != truth:
            errors.append({"text": c["text"], "expected": truth, "judged": pred})
    precision, recall = precision_recall(tp, fp, fn)
    return {"model": model, "cases": len(cases), "precision": precision, "recall": recall,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn, "errors": errors}


def _pct(triple) -> str:
    return "n/a" if triple[0] is None else f"{100 * triple[0]:.1f}% ({100 * triple[1]:.0f}-{100 * triple[2]:.0f})"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect", help="ask real models the fixture questions and save their answers")
    c.add_argument("--models", nargs="+", default=[DEFAULT_MODEL])
    c.add_argument("--formats", nargs="+", default=list(AD_FORMATS), choices=AD_FORMATS)
    c.add_argument("--repeats", type=int, default=1)
    c.add_argument("--out", type=Path, default=ANSWERS)
    c.add_argument("--dry-run", action="store_true", help="print the number of calls and one prompt; call nothing")
    s = sub.add_parser("score", help="score saved answers with the detector and against human labels")
    s.add_argument("path", type=Path, nargs="?", default=ANSWERS)
    s.add_argument("--out", type=Path, help="also write the full result as JSON")
    j = sub.add_parser("judge-heldout", help="model-graded disclosure check on the held-out set")
    j.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args(argv)

    if args.cmd == "collect":
        pages = load_pages()
        todo = plan(pages, args.models, args.formats, args.repeats)
        print(f"{len(todo)} calls: {len(args.models)} model(s) x {len(args.formats)} format(s) x "
              f"{sum(len(p.queries) for p in pages)} questions x {args.repeats} repeat(s)")
        if args.dry_run:
            print("\n--- system ---\n" + SYSTEM + "\n--- user ---\n" +
                  build_prompt(pages[0], pages[0].queries[0].q, args.formats[0]))
            return
        n = collect(anthropic_provider(), args.models, args.formats, args.repeats, args.out)
        print(f"Wrote {n} answers to {args.out}. Label human.included and human.disclosed, then run: python -m lab.real score")
    elif args.cmd == "score":
        rows = read_rows(args.path)
        if not rows:
            raise SystemExit(f"No answers in {args.path}. Run: python -m lab.real collect")
        res = score(rows)
        print(f"{res['answers']} answers (detector readings; 95% interval in brackets)")
        for g in res["by_model_and_format"]:
            o = g["overcount_if_billed_on_fetch"]
            print(f"  {g['model']} / {g['format']}: n={g['answers']}  inclusion {_pct(g['inclusion'])}  "
                  f"label kept {_pct(g['disclosure_survival'])}  link kept {_pct(g['link_survival'])}  "
                  f"overcount {'n/a' if o is None else f'{o:.1f}x'}")
        if res["human_by_model_and_format"]:
            draft = f" ({res['draft_labels']} are unreviewed drafts)" if res["draft_labels"] else ""
            print(f"Human labels{draft}:")
        for h in res["human_by_model_and_format"]:
            fr = ", ".join(f"{n} {k}" for k, n in h["framing"].items() if n) or "framing not labeled"
            print(f"  {h['model']} / {h['format']}: {h['included']} of {h['labeled']} mention the ad; "
                  f"{h['names_advertiser']} name the advertiser, {h['disclosed']} labeled, {h['linked']} keep the link; {fr}")
        for k, v in res["detector_vs_human"].items():
            if v["n"]:
                print(f"  {k} detector vs {v['n']} human labels: precision {v['precision']:.3f}, recall {v['recall']:.3f}")
            else:
                print(f"  {k}: no human labels yet")
        if args.out:
            args.out.write_text(json.dumps(res, indent=2))
            print(f"Wrote {args.out}")
    else:
        r = judge_heldout(anthropic_provider(), args.model)
        print(f"Model-graded disclosure ({r['model']}) on {r['cases']} held-out answers: "
              f"precision {r['precision']:.3f}, recall {r['recall']:.3f}")
        for e in r["errors"]:
            print(f"  expected {e['expected']}, judged {e['judged']}: {e['text']}")


if __name__ == "__main__":
    main()
