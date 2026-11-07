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
    assert wilson(0, 0) == (0.0, 0.0, 0.0)


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
    real = run_mod.run(200, seed=5)
    monkeypatch.setattr(run_mod, "detect", lambda text, ad: Detection(False, False, False, "none"))
    null = run_mod.run(200, seed=5)
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
