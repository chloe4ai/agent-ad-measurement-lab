"""Score the detector on hand-written answers it was not tuned on.

The simulator's agents only ever use three label phrasings, so the in-sample
disclosure numbers are close to perfect by construction. This set uses other
phrasings (and near-miss non-labels), plus paraphrases of ad claims that drop
the advertiser's name and link, to show how the rules do on wording they were
not written for.
"""
from __future__ import annotations

import json
from pathlib import Path

from .detect import detect
from .page import load_pages
from .stats import precision_recall

HELDOUT = Path(__file__).resolve().parent.parent / "fixtures" / "heldout.json"


def _score(cases: list[dict], field: str, ads: dict) -> dict:
    tp = fp = fn = tn = 0
    misses = []
    for c in cases:
        d = detect(c["text"], ads[c["page_id"]])
        pred, truth = getattr(d, field), c[field]
        tp += pred and truth
        fp += pred and not truth
        fn += (not pred) and truth
        tn += (not pred) and not truth
        if pred != truth:
            misses.append({"text": c["text"], "expected": truth, "detected": pred})
    precision, recall = precision_recall(tp, fp, fn)
    return {"cases": len(cases), "accuracy": (tp + tn) / len(cases) if cases else 0.0,
            "precision": precision, "recall": recall,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn, "errors": misses}


def evaluate(path: Path = HELDOUT) -> dict:
    data = json.loads(path.read_text())
    ads = {p.page_id: p.ad for p in load_pages()}
    for c in data["disclosure"]:
        assert detect(c["text"], ads[c["page_id"]]).included, c["text"]
    return {"disclosure": _score(data["disclosure"], "disclosed", ads),
            "inclusion": _score(data["inclusion"], "included", ads)}
