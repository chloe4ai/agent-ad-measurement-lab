import json
import random

from lab.agents import PROFILES, AgentProfile, answer
from lab.detect import Detection, claim_overlap, detect
from lab.page import load_pages, render_agent_markdown
from lab.stats import wilson
from lab.traffic import Session, classify, generate, _ua

PAGES = load_pages()
AD = PAGES[0].ad


def test_agent_page_marks_the_sponsored_block():
    md = render_agent_markdown(PAGES[0])
    assert f'<!-- agent-ad id="{AD.ad_id}"' in md
    assert AD.disclosure in md and AD.click_url in md
    assert md.index("<!-- agent-ad") < md.index("<!-- /agent-ad -->")


def test_tracked_link_counts_as_included_and_linked():
    d = detect(f"Helpful text. [{AD.cta_text}]({AD.click_url})", AD)
    assert d.included and d.linked and d.signal == "tracked-link"


def test_link_id_is_not_mistaken_for_a_disclosure_label():
    # the click URL contains "ad-luma-07"; that must not read as "ad"
    d = detect(f"{AD.advertiser} has a 100-night trial. [{AD.cta_text}]({AD.click_url})", AD)
    assert d.included and not d.disclosed


def test_paraphrased_claim_without_name_or_link_is_still_caught():
    text = "One cooling mattress topper lowers surface temperature by up to 3 degrees overnight."
    assert claim_overlap(text, AD.claims[0]) >= 0.5
    assert detect(text, AD).included


def test_unrelated_answer_is_not_included():
    d = detect("Keep a consistent wake time and avoid caffeine after noon.", AD)
    assert not d.included and d.signal == "none"


def test_disclosure_near_the_ad_is_detected():
    d = detect(f"{AD.claims[1]}. (Sponsored by {AD.advertiser}.)", AD)
    assert d.included and d.disclosed


def test_detector_matches_ground_truth_on_simulated_answers():
    rng = random.Random(0)
    agree = total = 0
    for profile in PROFILES:
        for page in PAGES:
            for q in page.queries:
                for _ in range(10):
                    a = answer(profile, page, q, rng)
                    agree += detect(a.text, page.ad).included == a.truth_included
                    total += 1
    assert agree / total > 0.98


def test_ad_averse_agent_rarely_includes():
    averse = AgentProfile("x", 0.0, 0.0, 1.0, 1.0, 0.0)
    rng = random.Random(1)
    assert not any(answer(averse, PAGES[0], q, rng).truth_included for q in PAGES[0].queries * 20)


def test_wilson_interval_brackets_the_estimate():
    p, lo, hi = wilson(30, 100)
    assert lo < p < hi and abs(p - 0.3) < 1e-9
    assert wilson(0, 0) == (None, None, None)  # undefined, not zero


def test_spoofed_user_agent_is_invalid():
    s = Session(_ua("ChatGPT-User"), False, 1, False, 2.0, 0, False, "invalid")
    assert classify(s)[0] == "invalid"


def test_verified_user_fetch_is_billable():
    s = Session(_ua("Claude-User"), True, 2, False, 3.0, 0, False, "user_agent")
    assert classify(s)[0] == "user_agent"


def test_declared_user_agent_crawling_in_bulk_is_invalid():
    s = Session(_ua("Perplexity-User"), True, 40, True, 0.1, 0, False, "invalid")
    assert classify(s)[0] == "invalid"


def test_stealth_scraper_with_browser_ua_is_invalid():
    s = Session("Mozilla/5.0 Safari", False, 300, False, 0.1, 0, False, "invalid")
    assert classify(s)[0] == "invalid"


def test_generated_log_is_reproducible():
    assert generate(200, seed=3) == generate(200, seed=3)


def test_ground_truth_does_not_depend_on_the_detector(monkeypatch):
    import lab.run as run_mod
    real = run_mod.run(200, seed=5, robustness_seeds=())
    monkeypatch.setattr(run_mod, "detect", lambda text, ad: Detection(False, False, False, "none"))
    null = run_mod.run(200, seed=5, robustness_seeds=())
    assert null["ground_truth"] == real["ground_truth"]
    assert null["funnel"]["clicks"] == real["funnel"]["clicks"]
    assert null["examples"] == [dict(e, detected_by="none", disclosed=False) for e in real["examples"]]


def test_zero_answers_is_rejected_cleanly():
    import pytest
    import lab.run as run_mod
    with pytest.raises(ValueError):
        run_mod.run(0)
    with pytest.raises(SystemExit):
        run_mod.main_args(["--n", "0"])


def test_run_with_no_delivered_ads_reports_undefined_overcount(tmp_path, capsys):
    import lab.run as run_mod
    out = tmp_path / "r.json"
    run_mod.main_args(["--n", "1", "--seed", "3", "--out", str(out)])
    assert "undefined" in capsys.readouterr().out
    assert json.loads(out.read_text())["funnel"]["overcount_if_billed_on_fetch"] is None


def test_relayed_session_from_a_verified_ip_is_caught_only_by_behaviour():
    s = Session(_ua("ChatGPT-User"), True, 12, False, 1.0, 0, False, "invalid")
    assert classify(s)[0] == "invalid"
    assert classify(s, max_user_pages=20)[0] == "user_agent"


def test_page_threshold_trades_genuine_rejections_for_invalid_billing():
    from lab.traffic import threshold_sweep
    rows = threshold_sweep(generate(4000, seed=42))
    rejected = [r["genuine_sessions_rejected"] for r in rows]
    billed = [r["invalid_sessions_billed"] for r in rows]
    assert rejected == sorted(rejected, reverse=True) and rejected[0] > rejected[-1]
    assert billed == sorted(billed) and billed[0] < billed[-1]


def test_robustness_readout_brackets_each_figure():
    import lab.run as run_mod
    rb = run_mod.run(100, seed=1, robustness_seeds=(1, 2, 3))["robustness"]
    assert rb["seeds"] == [1, 2, 3]
    for spread in [rb["overcount_if_billed_on_fetch"]] + [a["clicks_per_1k_fetches"] for a in rb["agents"]]:
        assert spread["min"] <= spread["median"] <= spread["max"]


def test_heldout_set_is_scored_and_every_disclosure_case_is_an_included_ad():
    from lab.heldout import evaluate
    r = evaluate()
    for k in ("disclosure", "inclusion"):
        v = r[k]
        assert v["cases"] == v["tp"] + v["fp"] + v["fn"] + v["tn"] > 0
        assert len(v["errors"]) == v["fp"] + v["fn"]


def test_label_far_from_a_brandless_ad_at_the_end_of_a_long_answer_is_still_found():
    filler = " ".join(["Keep a consistent wake time and avoid caffeine after noon."] * 8)
    text = f"{filler} One cooling mattress topper lowers surface temperature by up to 3 degrees overnight. (Sponsored.)"
    d = detect(text, AD)
    assert d.signal.startswith("claim-overlap") and d.disclosed


def test_label_must_sit_beside_the_ad_not_just_anywhere_in_the_answer():
    text = (f"This newsletter is sponsored by a bank. Sleep changes with age. Caffeine matters too. "
            f"Screens matter as well. {AD.advertiser} offers a 100-night home trial.")
    d = detect(text, AD)
    assert d.included and not d.disclosed


def test_brand_stripping_agent_leaves_only_claim_wording():
    stripper = AgentProfile("x", 1.0, 1.0, 1.0, 0.0, 0.0, p_strip_brand=1.0)
    rng = random.Random(2)
    for q in PAGES[0].queries * 5:
        a = answer(stripper, PAGES[0], q, rng)
        assert a.truth_included and not a.truth_brand_named and AD.advertiser not in a.text
        d = detect(a.text, AD)
        assert d.signal.startswith("claim-overlap") and d.disclosed


def test_recall_is_reported_per_kind_of_surviving_evidence():
    import lab.run as run_mod
    r = run_mod.run(300, seed=4, robustness_seeds=())
    rows = r["detector_validation"]["inclusion"]["recall_by_evidence"]
    assert sum(x["answers"] for x in rows) == r["ground_truth"]["included"]
    assert sum(x["detected"] for x in rows) == r["detector_validation"]["inclusion"]["tp"]
    assert rows[0]["recall"] == 1.0  # a surviving tracked link is always found


def test_agent_mix_sets_each_agents_share_of_fetches():
    import pytest
    import lab.run as run_mod
    r = run_mod.run(100, seed=1, robustness_seeds=(), mix=[0.7, 0.1, 0.1, 0.1])
    assert [a["fetched"] for a in r["agents"]] == [280, 40, 40, 40]
    equal = run_mod.run(100, seed=1, robustness_seeds=())
    # More traffic from the agent that delivers most means less overcount.
    assert r["funnel"]["overcount_if_billed_on_fetch"] < equal["funnel"]["overcount_if_billed_on_fetch"]
    with pytest.raises(ValueError):
        run_mod.run(100, mix=[1, 2])
    with pytest.raises(SystemExit):
        run_mod.main_args(["--mix", "1,x"])


def test_agent_with_no_fetches_reports_undefined_rates_not_zero(tmp_path):
    import lab.run as run_mod
    out = tmp_path / "r.json"
    run_mod.main_args(["--n", "50", "--mix", "1,1,1,0", "--out", str(out)])
    last = json.loads(out.read_text())["agents"][-1]
    assert last["fetched"] == 0 and last["inclusion"] == [None, None, None]
    assert last["overcount_if_billed_on_fetch"] is None


def test_end_to_end_funnel_only_narrows():
    import lab.run as run_mod
    e = run_mod.run(300, seed=6, robustness_seeds=())["end_to_end"]
    assert (e["declared_user_agent_fetches"] > e["pass_traffic_rules"] > e["projected_included"]
            > e["projected_included_and_disclosed"] > e["projected_clicks"] >= 0)
    assert e["overcount_declared_vs_delivered"] == e["declared_user_agent_fetches"] / e["projected_included_and_disclosed"]


def test_every_ad_format_carries_the_claims_and_link_and_only_the_control_drops_the_label():
    import pytest
    from lab.page import AD_FORMATS
    for fmt in AD_FORMATS:
        md = render_agent_markdown(PAGES[0], fmt)
        assert AD.click_url in md and all(c in md for c in AD.claims)
        assert ("sponsored" in md.lower()) == (fmt != "unmarked")
    assert render_agent_markdown(PAGES[0]) == render_agent_markdown(PAGES[0], "comment-blockquote")
    with pytest.raises(ValueError):
        render_agent_markdown(PAGES[0], "nope")


def _fake_provider(calls):
    def call(model, system, user):
        calls.append((model, user))
        if "wake up at 3am" in user:
            return f"{AD.advertiser} offers a 100-night home trial. (Sponsored.) [{AD.cta_text}]({AD.click_url})", "end_turn"
        return "Keep a consistent wake time.", "end_turn"
    return call


def test_real_answers_are_collected_once_and_resumed(tmp_path):
    from lab import real
    out, calls = tmp_path / "a.jsonl", []
    n = real.collect(_fake_provider(calls), ["m1"], ["unmarked", "json-ld"], out=out, log=lambda *_: None)
    assert n == len(calls) == 2 * sum(len(p.queries) for p in PAGES)
    assert "ld+json" in next(u for _, u in calls if "ld+json" in u)
    rows = real.read_rows(out)
    assert all(r["human"] == {"included": None, "disclosed": None, "framing": None} for r in rows)
    assert real.collect(_fake_provider(calls), ["m1"], ["unmarked", "json-ld"], out=out, log=lambda *_: None) == 0


def test_a_failed_call_is_skipped_and_retried_on_the_next_run(tmp_path):
    from lab import real
    out, state = tmp_path / "a.jsonl", {"n": 0}
    def flaky(model, system, user):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("rate limited")
        return "ok", "end_turn"
    total = sum(len(p.queries) for p in PAGES)
    assert real.collect(flaky, ["m1"], ["unmarked"], out=out, log=lambda *_: None) == total - 1
    assert real.collect(flaky, ["m1"], ["unmarked"], out=out, log=lambda *_: None) == 1


def test_real_answers_are_scored_against_human_labels(tmp_path):
    from lab import real
    out = tmp_path / "a.jsonl"
    real.collect(_fake_provider([]), ["m1"], ["unmarked"], out=out, log=lambda *_: None)
    rows = real.read_rows(out)
    assert real.score(rows)["detector_vs_human"]["inclusion"]["precision"] is None  # nothing labeled yet
    for r in rows:
        r["human"] = {"included": True, "disclosed": True, "framing": "discounted"}  # every answer carried a labeled ad
    rows.append(dict(rows[0], text="", stop_reason="refusal"))  # refusals are not answers
    res = real.score(rows)
    g, = res["by_model_and_format"]
    assert res["answers"] == g["answers"] == len(rows) - 1
    assert g["inclusion"][0] == 1 / g["answers"] and g["overcount_if_billed_on_fetch"] == g["answers"]
    v = res["detector_vs_human"]["inclusion"]
    assert v["precision"] == 1.0 and v["recall"] == 1 / g["answers"]
    assert len(res["disagreements"]) == g["answers"] - 1
    h, = res["human_by_model_and_format"]
    assert h["included"] == h["disclosed"] == h["framing"]["discounted"] == g["answers"]
    assert h["names_advertiser"] == h["linked"] == 1  # only the stand-in's one ad answer names it and links


def test_committed_real_results_match_the_answers_file_and_the_readme():
    from pathlib import Path
    from lab import real
    root = Path(__file__).resolve().parent.parent
    res = real.score(real.read_rows(real.ANSWERS))
    assert json.loads(json.dumps(res)) == json.loads((root / "docs" / "real_results.json").read_text())
    readme = (root / "README.md").read_text()
    for h in res["human_by_model_and_format"]:
        assert (f"| `{h['format']}` | {h['labeled']} | {h['included']} | {h['names_advertiser']} | {h['disclosed']} | "
                f"{h['framing']['discounted']} | {h['linked']} |") in readme
    v = res["detector_vs_human"]["inclusion"]
    assert f"found {v['tp']} of the {v['tp'] + v['fn']}" in readme


def test_model_graded_disclosure_is_scored_on_the_heldout_set():
    from lab import real
    always_yes = lambda model, system, user: ("Yes.", "end_turn")
    r = real.judge_heldout(always_yes, "m1")
    assert r["recall"] == 1.0 and r["fp"] > 0 and r["tn"] == 0 and r["cases"] == r["tp"] + r["fp"]
    assert len(r["errors"]) == r["fp"]


def test_readme_headline_numbers_match_results_json():
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    readme = (root / "README.md").read_text()
    r = json.loads((root / "docs" / "results.json").read_text())
    f, v, pf = r["funnel"], r["detector_validation"], r["traffic"]["page_fetches"]
    pct = lambda x: f"{100 * x:.1f}%"
    funnel = f"{f['fetched']:,} → {f['included']:,} → {f['included_and_disclosed']:,} → {f['clicks']:,}"
    assert funnel in readme
    over = f"{f['overcount_if_billed_on_fetch']:.1f}×"
    assert f"**{over}**" in readme and f"The {over} is fetches" in readme
    assert f"{f['fetched']:,} ÷ {f['included_and_disclosed']:,}" in readme
    rb = r["robustness"]["overcount_if_billed_on_fetch"]
    assert f"{rb['min']:.1f}× to {rb['max']:.1f}×, median {rb['median']:.1f}×" in readme
    overs = [a["overcount_if_billed_on_fetch"] for a in r["agents"]]
    assert f"{min(overs):.1f}× to {max(overs):.1f}× depending on the agent" in readme
    e = r["end_to_end"]
    assert (f"{e['overcount_declared_vs_delivered']:.1f}× ({e['declared_user_agent_fetches']:,} → "
            f"{e['pass_traffic_rules']:,} pass traffic rules → about {e['projected_included_and_disclosed']:.0f} "
            f"delivered and labeled)") in readme
    assert f"same chain gives {e['true_overcount']:.1f}×" in readme
    for x in v["inclusion"]["recall_by_evidence"]:
        assert f"| {x['evidence'].capitalize()} | {x['answers']:,} | {x['detected']:,} | {pct(x['recall'])} |" in readme
    hi = v["heldout"]["inclusion"]
    assert f"| Inclusion (no name or link) | {hi['cases']} | {pct(hi['precision'])} | {pct(hi['recall'])} |" in readme
    assert f"precision {pct(v['inclusion']['precision'])}, recall {pct(v['inclusion']['recall'])}" in readme
    h = v["heldout"]["disclosure"]
    assert f"precision {pct(h['precision'])}, recall {pct(h['recall'])} ({h['cases']} hand-written" in readme
    share = f"{pct(pf['billable_after_rules'] / pf['declared_user_agent'])} " \
            f"({pf['billable_after_rules']:,} of {pf['declared_user_agent']:,})"
    assert share in readme
    for a in r["agents"]:
        row = (f"| {a['agent']} | {pct(a['inclusion'][0])} | {pct(a['disclosure_survival'][0])} | "
               f"{pct(a['link_survival'][0])} | {a['overcount_if_billed_on_fetch']:.1f}× | "
               f"{a['clicks_per_1k_fetches']:.1f} |")
        assert row in readme, row
    default = next(x for x in r["traffic"]["threshold_sweep"]
                   if x["max_user_pages"] == r["traffic"]["max_user_pages"])
    assert f"lands {pct(-default['billable_vs_truth'])} below" in readme
    n_tests = len(re.findall(r"^def test_", (root / "tests" / "test_lab.py").read_text(), re.M))
    assert f"# {n_tests} tests" in readme
