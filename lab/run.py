"""Run the full lab and write results to docs/results.json.

    python -m lab.run            # default: 600 answers per agent, seed 42
    python -m lab.run --n 2000 --seed 1
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path

from . import heldout, traffic
from .agents import PROFILES, answer
from .detect import detect
from .page import load_pages, render_agent_markdown
from .stats import precision_recall, wilson

OUT = Path(__file__).resolve().parent.parent / "docs" / "results.json"
BASE_CTR = 0.04  # chance a person clicks a surviving tracked link


def _positive_int(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return n


ROBUSTNESS_SEEDS = tuple(range(1, 21))


def _spread(values: list[float | None]) -> dict:
    vals = [v for v in values if v is not None]
    if not vals:
        return {"min": None, "median": None, "max": None, "n": 0}
    return {"min": min(vals), "median": statistics.median(vals), "max": max(vals), "n": len(vals)}


def robustness(n_per_agent: int, seeds=ROBUSTNESS_SEEDS) -> dict:
    """Re-run the lab across seeds so headline figures come with a range, not one draw."""
    runs = [_simulate(n_per_agent, s) for s in seeds]
    names = [a["agent"] for a in runs[0]["agents"]]
    tf = [r["traffic"]["page_fetches"] for r in runs]
    return {
        "seeds": list(seeds),
        "overcount_if_billed_on_fetch": _spread([r["funnel"]["overcount_if_billed_on_fetch"] for r in runs]),
        "inclusion_recall": _spread([r["detector_validation"]["inclusion"]["recall"] for r in runs]),
        "billable_vs_truth": _spread([p["billable_after_rules"] / p["truly_billable"] - 1 for p in tf]),
        "agents": [{
            "agent": name,
            "inclusion": _spread([r["agents"][i]["inclusion"][0] for r in runs]),
            "disclosure_survival": _spread([r["agents"][i]["disclosure_survival"][0] for r in runs]),
            "clicks_per_1k_fetches": _spread([r["agents"][i]["clicks_per_1k_fetches"] for r in runs]),
        } for i, name in enumerate(names)],
    }


def run(n_per_agent: int = 600, seed: int = 42, robustness_seeds=ROBUSTNESS_SEEDS) -> dict:
    """One full run at `seed`, plus a min/median/max readout across `robustness_seeds`."""
    res = _simulate(n_per_agent, seed)
    # Wording the detector was not written for; see fixtures/heldout.json.
    res["detector_validation"]["heldout"] = heldout.evaluate()
    if robustness_seeds:
        res["robustness"] = robustness(n_per_agent, robustness_seeds)
    return res


def _simulate(n_per_agent: int, seed: int) -> dict:
    if n_per_agent < 1:
        raise ValueError("n_per_agent must be at least 1")
    # Two independent streams: one simulates the agents (ground truth), one
    # simulates people clicking. Nothing the detector returns touches either,
    # so swapping the detector can never change what actually happened.
    rng = random.Random(seed)
    click_rng = random.Random(f"clicks-{seed}")
    pages = load_pages()
    agents_out, examples = [], []
    det_tp = det_fp = det_fn = 0
    dis_tp = dis_fp = dis_fn = 0
    truth = dict(included=0, included_and_disclosed=0, linked=0)

    for profile in PROFILES:
        counts = dict(fetched=0, included=0, disclosed=0, linked=0, clicks=0)
        relevant = dict(n=0, included=0)
        for i in range(n_per_agent):
            page = pages[i % len(pages)]
            query = rng.choice(page.queries)
            ans = answer(profile, page, query, rng)
            d = detect(ans.text, page.ad)

            truth["included"] += ans.truth_included
            truth["included_and_disclosed"] += ans.truth_included and ans.truth_disclosed
            truth["linked"] += ans.truth_linked

            counts["fetched"] += 1
            counts["included"] += d.included
            counts["disclosed"] += d.included and d.disclosed
            counts["linked"] += d.linked
            # Clicks come from the click server, not from reading the answer:
            # a person can only click a link that is really there.
            if click_rng.random() < BASE_CTR and ans.truth_linked:
                counts["clicks"] += 1
            if query.ad_relevant:
                relevant["n"] += 1
                relevant["included"] += d.included

            det_tp += d.included and ans.truth_included
            det_fp += d.included and not ans.truth_included
            det_fn += (not d.included) and ans.truth_included
            if d.included and ans.truth_included:
                dis_tp += d.disclosed and ans.truth_disclosed
                dis_fp += d.disclosed and not ans.truth_disclosed
                dis_fn += (not d.disclosed) and ans.truth_disclosed

            if len([e for e in examples if e["agent"] == profile.name]) < 2 and ans.truth_included:
                examples.append({"agent": profile.name, "query": ans.query,
                                 "answer": ans.text, "detected_by": d.signal,
                                 "disclosed": d.disclosed})

        n = counts["fetched"]
        inc = counts["included"]
        agents_out.append({
            "agent": profile.name,
            "fetched": n,
            "inclusion": wilson(inc, n),
            "disclosure_survival": wilson(counts["disclosed"], inc),
            "link_survival": wilson(counts["linked"], inc),
            "delivered_disclosed": counts["disclosed"],
            "clicks": counts["clicks"],
            "clicks_per_1k_fetches": 1000 * counts["clicks"] / n,
            "inclusion_when_relevant": wilson(relevant["included"], relevant["n"]),
        })

    total_fetched = sum(a["fetched"] for a in agents_out)
    total_delivered = sum(a["delivered_disclosed"] for a in agents_out)
    precision, recall = precision_recall(det_tp, det_fp, det_fn)
    d_precision, d_recall = precision_recall(dis_tp, dis_fp, dis_fn)

    return {
        "config": {"n_per_agent": n_per_agent, "seed": seed, "base_ctr": BASE_CTR},
        "sample_page": render_agent_markdown(pages[0]),
        "agents": agents_out,
        "funnel": {
            "fetched": total_fetched,
            "included": sum(round(a["inclusion"][0] * a["fetched"]) for a in agents_out),
            "included_and_disclosed": total_delivered,
            "clicks": sum(a["clicks"] for a in agents_out),
            "overcount_if_billed_on_fetch": total_fetched / total_delivered if total_delivered else None,
        },
        # What the simulator actually produced; independent of the detector.
        "ground_truth": truth,
        "detector_validation": {
            "inclusion": {"precision": precision, "recall": recall,
                          "tp": det_tp, "fp": det_fp, "fn": det_fn},
            "disclosure": {"precision": d_precision, "recall": d_recall,
                           "tp": dis_tp, "fp": dis_fp, "fn": dis_fn},
        },
        "examples": examples,
        "traffic": traffic.evaluate(traffic.generate(seed=seed)),
    }


def main_args(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=_positive_int, default=600, help="answers simulated per agent")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    res = run(args.n, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(res, indent=2))

    f = res["funnel"]
    print(f"Fetched {f['fetched']}  ->  included {f['included']}  ->  "
          f"included+disclosed {f['included_and_disclosed']}  ->  clicks {f['clicks']}")
    over = f["overcount_if_billed_on_fetch"]
    if over is None:
        print("No answer in this run both included the ad and kept its label, "
              "so the fetch overcount is undefined. Try a larger --n.")
    else:
        print(f"Billing on fetches would overcount delivered, labeled ads by {over:.1f}x "
              f"(fetches / detected included-and-labeled answers)")
    for k in ("inclusion", "disclosure"):
        v = res["detector_validation"][k]
        print(f"{k.capitalize()} detector vs ground truth: precision {v['precision']:.3f}, recall {v['recall']:.3f}")
    for k, v in res["detector_validation"]["heldout"].items():
        print(f"Held-out {k} ({v['cases']} hand-written answers): precision {v['precision']:.3f}, "
              f"recall {v['recall']:.3f}")
    rb = res["robustness"]["overcount_if_billed_on_fetch"]
    if rb["n"]:
        print(f"Across seeds {res['robustness']['seeds'][0]}-{res['robustness']['seeds'][-1]}: overcount "
              f"min {rb['min']:.1f}x, median {rb['median']:.1f}x, max {rb['max']:.1f}x")
    pf = res["traffic"]["page_fetches"]
    print(f"Traffic: {pf['declared_user_agent']} page fetches declare a user-agent token; "
          f"{pf['billable_after_rules']} billable after rules (truth {pf['truly_billable']})")
    print(f"Wrote {args.out}")


def main() -> None:
    main_args()


if __name__ == "__main__":
    main()
