"""Build docs/index.html from docs/results.json (data is embedded, no server needed).

    python -m lab.run && python scripts/build_dashboard.py
"""
from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "docs" / "results.json"
REAL = ROOT / "docs" / "real_results.json"  # written by `python -m lab.real score --out`; optional
OUT = ROOT / "docs" / "index.html"

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent Ad Measurement Lab</title>
<style>
.viz-root{color-scheme:light;--surface-0:#f4f3f0;--surface-1:#fcfcfb;--border:#e2e0da;--grid:#ebe9e4;
  --text-primary:#0b0b0b;--text-secondary:#52514e;--text-muted:#7a7873;
  --s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--neutral:#8a8882;--accent:#2a78d6}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .viz-root{color-scheme:dark;
  --surface-0:#121211;--surface-1:#1a1a19;--border:#2e2d2a;--grid:#262523;--text-primary:#f0efec;
  --text-secondary:#c3c2b7;--text-muted:#8f8e86;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--neutral:#77756f;--accent:#3987e5}}
*{box-sizing:border-box}
body{margin:0;background:var(--surface-0);color:var(--text-primary);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
main{max-width:1040px;margin:0 auto;padding:40px 24px 64px}
h1{font-size:30px;line-height:1.2;margin:0 0 8px;letter-spacing:-.01em}
h2{font-size:19px;margin:0 0 4px}
.lede{color:var(--text-secondary);max-width:760px;margin:0 0 28px;font-size:16px}
.card{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:22px 24px;margin:0 0 20px;overflow-x:auto}
@media (max-width:600px){main{padding:24px 14px 48px}.card{padding:18px 14px}}
.sub{color:var(--text-secondary);margin:0 0 16px;font-size:14px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin:0 0 20px}
.tile{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:18px 20px}
.tile .v{font-size:34px;font-weight:650;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.tile .k{color:var(--text-secondary);font-size:13.5px;margin-top:2px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:20px}
@media (max-width:820px){.grid2{grid-template-columns:1fr}}
svg text{fill:var(--text-secondary);font-size:12.5px;font-variant-numeric:tabular-nums}
svg .lbl{fill:var(--text-primary);font-size:13px}
svg .val{fill:var(--text-primary);font-weight:600}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:13px;color:var(--text-secondary);margin:4px 0 10px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
table{border-collapse:collapse;width:100%;font-size:13.5px;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--grid)}
th{color:var(--text-secondary);font-weight:600}
td.n,th.n{text-align:right}
pre{background:var(--surface-0);border:1px solid var(--border);border-radius:8px;padding:14px;overflow:auto;
  font:12.5px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap;margin:0}
.ex{border-left:3px solid var(--border);padding:2px 0 2px 12px;margin:0 0 14px;font-size:14px}
.ex b{font-weight:600}.ex .meta{color:var(--text-muted);font-size:12.5px}
.tip{position:fixed;pointer-events:none;background:var(--surface-1);border:1px solid var(--border);border-radius:8px;
  padding:8px 10px;font-size:12.5px;box-shadow:0 4px 16px rgba(0,0,0,.12);opacity:0;transition:opacity .08s;z-index:9}
footer{color:var(--text-muted);font-size:12.5px;margin-top:28px}
a{color:var(--accent)}
</style>
</head>
<body class="viz-root">
<main>
  <h1>Agent Ad Measurement Lab</h1>
  <p class="lede">When an AI agent fetches a page that carries a sponsored block, the fetch proves only that
  the page was downloaded. This lab measures what actually reached the person: whether the ad made it into
  the agent's answer, whether its sponsorship label survived, whether the tracked link survived, and which
  agent fetches were made for a real user question in the first place.</p>

  <div class="tiles" id="tiles"></div>

  <section class="card">
    <h2>From fetch to delivered impression</h2>
    <p class="sub">All simulated answers, every agent combined. Each step keeps only what survived the step before.</p>
    <div id="funnel"></div>
    <h2 style="margin-top:22px">End to end: from declared fetch to delivered impression</h2>
    <p class="sub" id="e2eSub"></p>
    <div id="e2e"></div>
  </section>

  <section class="card">
    <h2>How each agent treats the sponsored block</h2>
    <p class="sub">Bars are point estimates; whiskers are Wilson 95% intervals. Disclosure and link survival are measured among answers that included the ad.</p>
    <div class="legend" id="legend"></div>
    <div class="grid2">
      <div><div class="sub" style="margin:0 0 4px;color:var(--text-primary);font-weight:600">Inclusion rate</div><div id="inc"></div></div>
      <div><div class="sub" style="margin:0 0 4px;color:var(--text-primary);font-weight:600">Disclosure survival</div><div id="dis"></div></div>
    </div>
    <div style="margin-top:18px"><table id="agentTable"></table></div>
  </section>

  <section class="card">
    <h2>Traffic quality: which fetches are billable?</h2>
    <p class="sub">A labeled synthetic session log, classified by ordered, auditable rules:
    declared user-agent token &rarr; source IP verified against the operator &rarr; session behaviour.</p>
    <div id="traffic"></div>
    <div style="margin-top:14px"><table id="trafficTable"></table></div>
    <h2 style="margin-top:22px">Where to set the page-count threshold</h2>
    <p class="sub" id="sweepSub">A verified user-agent token that fetches more pages than the threshold is treated as a crawler.
    Lower thresholds reject more genuine sessions; higher ones bill more relayed, scripted sessions that come from real operator IPs.</p>
    <table id="sweepTable"></table>
  </section>

  <section class="card" id="realCard">
    <h2>What a real model did with the same pages</h2>
    <p class="sub" id="realSub"></p>
    <table id="realTable"></table>
  </section>

  <section class="card">
    <h2>How far to trust the detector</h2>
    <p class="sub">Inclusion recall depends on what the agent left in the answer. A surviving link or advertiser name is
    easy; an ad passed on as unbranded wording is found only by word overlap with the original claim.</p>
    <table id="evidenceTable"></table>
    <p class="sub" style="margin-top:18px">The simulated agents use a handful of label phrasings the rules were written around.
    These are the same rules on hand-written answers with other wording.</p>
    <table id="heldoutTable"></table>
  </section>

  <section class="card">
    <h2>What the agent fetches</h2>
    <p class="sub">A fixture page as served to an agent: Markdown, with the sponsored block wrapped in machine-readable markers. Publishers and advertisers are fictional.</p>
    <pre id="page"></pre>
  </section>

  <section class="card">
    <h2>Sample answers and how they were scored</h2>
    <div id="examples"></div>
  </section>

  <footer id="foot"></footer>
</main>
<div class="tip" id="tip"></div>
<script>
const R = __DATA__;
const COLORS = ["var(--s1)","var(--s2)","var(--s3)","var(--s4)"];
const pct = x => x == null ? "n/a" : (100*x).toFixed(1) + "%";
const times = x => x == null ? "n/a" : x.toFixed(1) + "×";
const fmt = n => n.toLocaleString("en-US");
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const tip = document.getElementById("tip");
function showTip(e, h){ tip.innerHTML = h; tip.style.opacity = 1;
  tip.style.left = Math.min(e.clientX + 14, innerWidth - 260) + "px"; tip.style.top = (e.clientY + 14) + "px"; }
function hideTip(){ tip.style.opacity = 0; }
function bindTips(root){ root.querySelectorAll("[data-tip]").forEach(el => {
  el.addEventListener("mousemove", e => showTip(e, el.dataset.tip)); el.addEventListener("mouseleave", hideTip); }); }

// Tiles
const f = R.funnel, v = R.detector_validation, pf = R.traffic.page_fetches, E = R.end_to_end;
const overs = R.agents.map(a => a.overcount_if_billed_on_fetch).filter(x => x != null);
const overRange = overs.length ? ` (${times(Math.min(...overs))} to ${times(Math.max(...overs))} depending on the agent)` : "";
document.getElementById("tiles").innerHTML = [
  [times(f.overcount_if_billed_on_fetch), "overcount if impressions are billed on fetch instead of delivered, labeled answers" + overRange],
  [times(E.overcount_declared_vs_delivered), "end to end: fetches declaring a user-agent token per delivered, labeled answer (projected)"],
  [pct(v.inclusion.precision) + " / " + pct(v.inclusion.recall), "inclusion detector precision / recall against simulated ground truth"],
  [pct(pf.billable_after_rules / pf.declared_user_agent), "of page fetches declaring a user-agent token pass the billing rules"],
].map(([val, k]) => `<div class="tile"><div class="v">${val}</div><div class="k">${k}</div></div>`).join("");

// Horizontal bar helper (single measure, optional CI)
function hbars(el, rows, opts){
  const W = (opts.W && el.clientWidth > 700) ? opts.W : 480, rowH = 34, left = (W > 480 ? opts.left : 0) || 150, right = 80, top = 6;
  const H = top + rows.length * rowH + 22;
  const x = t => left + t * (W - left - right);
  let s = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="${esc(opts.aria)}">`;
  [0, .25, .5, .75, 1].forEach(t => {
    s += `<line x1="${x(t)}" x2="${x(t)}" y1="${top}" y2="${H-20}" stroke="var(--grid)"/>`;
    if (!opts.noTicks) s += `<text x="${x(t)}" y="${H-5}" text-anchor="middle">${Math.round(t*100)+"%"}</text>`;
  });
  rows.forEach((r, i) => {
    const y = top + i * rowH + 7, h = rowH - 14, w = Math.max(x(r.v) - x(0), 2);
    s += `<g data-tip="${esc(r.tip)}" style="cursor:default">`;
    s += `<rect x="0" y="${y-6}" width="${W}" height="${rowH}" fill="transparent"/>`;
    s += `<text class="lbl" x="${left-10}" y="${y+h/2+4}" text-anchor="end">${esc(r.label)}</text>`;
    // Bars too short for rounded corners are drawn as a plain sliver.
    s += w < 8 ? `<rect x="${x(0)}" y="${y}" width="${w}" height="${h}" fill="${r.color}"/>`
      : `<path d="M${x(0)},${y} h${w-4} a4,4 0 0 1 4,4 v${h-8} a4,4 0 0 1 -4,4 h-${w-4} z" fill="${r.color}"/>`;
    if (r.lo !== undefined) {
      s += `<line x1="${x(r.lo)}" x2="${x(r.hi)}" y1="${y+h/2}" y2="${y+h/2}" stroke="var(--text-primary)" stroke-width="1.5"/>`;
      s += `<line x1="${x(r.lo)}" x2="${x(r.lo)}" y1="${y+h/2-5}" y2="${y+h/2+5}" stroke="var(--text-primary)" stroke-width="1.5"/>`;
      s += `<line x1="${x(r.hi)}" x2="${x(r.hi)}" y1="${y+h/2-5}" y2="${y+h/2+5}" stroke="var(--text-primary)" stroke-width="1.5"/>`;
    }
    s += `<text class="val" x="${Math.max(x(r.hi ?? r.v), x(r.v)) + 8}" y="${y+h/2+4}">${r.text}</text></g>`;
  });
  el.innerHTML = s + "</svg>"; bindTips(el);
}

// Funnel
const steps = [["Fetched by an agent", f.fetched], ["Included in the answer", f.included],
  ["Included and labeled", f.included_and_disclosed], ["Clicked", f.clicks]];
hbars(document.getElementById("funnel"), steps.map(([l, n]) => ({label: l, v: n / f.fetched, color: "var(--s1)",
  text: fmt(n), tip: `<b>${l}</b><br>${fmt(n)} answers · ${pct(n / f.fetched)} of fetches`})),
  {aria: "Funnel from fetch to click", W: 960, left: 220, noTicks: true});

// End to end
const round = n => fmt(Math.round(n));
const e2e = [["Declare a user-agent token", E.declared_user_agent_fetches], ["Pass the traffic rules", E.pass_traffic_rules],
  ["Included in the answer", E.projected_included], ["Included and labeled", E.projected_included_and_disclosed],
  ["Clicked", E.projected_clicks]];
hbars(document.getElementById("e2e"), e2e.map(([l, n]) => ({label: l, v: n / E.declared_user_agent_fetches, color: "var(--s1)",
  text: round(n), tip: `<b>${l}</b><br>${round(n)} page fetches · ${pct(n / E.declared_user_agent_fetches)} of declared`})),
  {aria: "End-to-end funnel from declared fetch to click", W: 960, left: 220, noTicks: true});
document.getElementById("e2eSub").innerHTML = `Page fetches from the traffic log, filtered by the billing rules, then scaled by the
  answer-level rates above. A projection: it assumes one fetch feeds one answer and that an invalid fetch reaches nobody.
  On the simulator's ground truth the same chain gives ${times(E.true_overcount)}.`;

// Per-agent
document.getElementById("legend").innerHTML = R.agents.map((a, i) =>
  `<span><i style="background:${COLORS[i]}"></i>${esc(a.agent)}</span>`).join("");
const agentRows = key => R.agents.map((a, i) => ({label: a.agent.replace(" assistant", "").replace("Sponsorship", "Sponsor"), v: a[key][0],
  lo: a[key][1], hi: a[key][2], color: COLORS[i], text: pct(a[key][0]),
  tip: `<b>${esc(a.agent)}</b><br>${pct(a[key][0])} (95% CI ${pct(a[key][1])}–${pct(a[key][2])})`}));
hbars(document.getElementById("inc"), agentRows("inclusion"), {aria: "Inclusion rate by agent", left: 125});
hbars(document.getElementById("dis"), agentRows("disclosure_survival"), {aria: "Disclosure survival by agent", left: 125});
document.getElementById("agentTable").innerHTML =
  `<tr><th>Agent</th><th class="n">Fetches</th><th class="n">Inclusion</th><th class="n">When relevant</th>
   <th class="n">Disclosure kept</th><th class="n">Link kept</th><th class="n">Fetches per delivered, labeled answer</th>
   <th class="n">Clicks / 1k fetches (95% CI)</th></tr>` +
  R.agents.map(a => `<tr><td>${esc(a.agent)}</td><td class="n">${fmt(a.fetched)}</td><td class="n">${pct(a.inclusion[0])}</td>
   <td class="n">${pct(a.inclusion_when_relevant[0])}</td><td class="n">${pct(a.disclosure_survival[0])}</td>
   <td class="n">${pct(a.link_survival[0])}</td><td class="n">${times(a.overcount_if_billed_on_fetch)}</td>
   <td class="n">${a.clicks_per_1k_fetches == null ? "n/a" : `${a.clicks_per_1k_fetches.toFixed(1)} (${(1000*a.click_rate[1]).toFixed(1)}–${(1000*a.click_rate[2]).toFixed(1)})`}</td></tr>`).join("");

// Traffic
const tr = [["Declare a user-agent token", pf.declared_user_agent, "var(--neutral)"],
  ["Truly user-initiated", pf.truly_billable, "var(--s1)"], ["Billable after rules", pf.billable_after_rules, "var(--s1)"]];
hbars(document.getElementById("traffic"), tr.map(([l, n, c]) => ({label: l, v: n / pf.declared_user_agent, color: c,
  text: fmt(n), tip: `<b>${l}</b><br>${fmt(n)} page fetches`})),
  {aria: "Page fetches declared versus billable", W: 960, left: 220, noTicks: true});
const pc = R.traffic.per_class;
document.getElementById("trafficTable").innerHTML =
  `<tr><th>Class</th><th class="n">Sessions (truth)</th><th class="n">Predicted</th><th class="n">Precision</th><th class="n">Recall</th></tr>` +
  Object.values(pc).map(c => `<tr><td>${esc(c.label)}</td><td class="n">${fmt(c.truth)}</td><td class="n">${fmt(c.predicted)}</td>
   <td class="n">${pct(c.precision)}</td><td class="n">${pct(c.recall)}</td></tr>`).join("");

const sw = R.traffic.threshold_sweep || [];
document.getElementById("sweepTable").innerHTML = sw.length ?
  `<tr><th class="n">Max pages</th><th class="n">Genuine sessions rejected</th><th class="n">Invalid sessions billed</th>
   <th class="n">Invalid page fetches billed</th><th class="n">Billable vs truth</th></tr>` +
  sw.map(r => `<tr${r.max_user_pages === R.traffic.max_user_pages ? ' style="font-weight:600"' : ""}><td class="n">${r.max_user_pages}${r.max_user_pages === R.traffic.max_user_pages ? " (default)" : ""}</td>
   <td class="n">${pct(r.genuine_sessions_rejected)}</td><td class="n">${fmt(r.invalid_sessions_billed)}</td>
   <td class="n">${fmt(r.invalid_page_fetches_billed)}</td>
   <td class="n">${r.billable_vs_truth == null ? "n/a" : (r.billable_vs_truth >= 0 ? "+" : "") + pct(r.billable_vs_truth)}</td></tr>`).join("") : "";
if (!sw.length) document.getElementById("sweepSub").style.display = "none";
document.getElementById("evidenceTable").innerHTML =
  `<tr><th>What the answer kept</th><th class="n">Answers with the ad</th><th class="n">Detected</th><th class="n">Recall</th></tr>` +
  v.inclusion.recall_by_evidence.map(r => `<tr><td>${esc(r.evidence[0].toUpperCase() + r.evidence.slice(1))}</td>
   <td class="n">${fmt(r.answers)}</td><td class="n">${fmt(r.detected)}</td><td class="n">${pct(r.recall)}</td></tr>`).join("");
const ho = v.heldout || {};
document.getElementById("heldoutTable").innerHTML =
  `<tr><th>Rule</th><th class="n">Held-out answers</th><th class="n">Precision</th><th class="n">Recall</th>
   <th class="n">In-sample precision</th><th class="n">In-sample recall</th></tr>` +
  [["Disclosure label", "disclosure"], ["Inclusion, no name or link", "inclusion"]].filter(([, k]) => ho[k]).map(([l, k]) =>
   `<tr><td>${l}</td><td class="n">${fmt(ho[k].cases)}</td><td class="n">${pct(ho[k].precision)}</td><td class="n">${pct(ho[k].recall)}</td>
    <td class="n">${pct(v[k].precision)}</td><td class="n">${pct(v[k].recall)}</td></tr>`).join("");
if (R.real && R.real.human_by_model_and_format.length) {
  const hs = R.real.human_by_model_and_format, sum = k => hs.reduce((t, h) => t + h[k], 0);
  const di = R.real.detector_vs_human.inclusion, disc = hs.reduce((t, h) => t + h.framing.discounted, 0);
  document.getElementById("realSub").innerHTML = `Not simulated: ${fmt(R.real.answers)} answers from ${esc([...new Set(hs.map(h => h.model))].join(", "))},
    ${fmt(hs[0].labeled)} per ad markup format and link form, given the page and a question with no instruction about advertising.
    ${sum("included")} answers mention the ad; ${disc} of those present it as something to discount ("that's a paid ad, you don't need it"),
    and ${sum("linked")} keep the tracked link.` +
    (hs.some(h => h.click_url_form !== "absolute") ? ` Rows marked "bare path" saw a click link with no domain, which a model cannot turn into a usable link.` : "") + ` The rule-based detector found ${di.tp} of the ${di.tp + di.fn} mentions.` +
    (R.real.draft_labels ? ` Labels are a first-pass draft, not yet reviewed by a person.`
      : ` Labels were drafted with a model and reviewed by the author.`) +
    ` At ${fmt(hs[0].labeled)} answers per format the differences between formats are within noise.`;
  document.getElementById("realTable").innerHTML =
    `<tr><th>Ad markup format</th><th>Click link in page</th><th class="n">Answers</th><th class="n">Mention the ad</th><th class="n">Name the advertiser</th>
     <th class="n">Say it is paid</th><th class="n">Discount it</th><th class="n">Keep the tracked link</th><th class="n">Any link at all</th></tr>` +
    hs.map(h => `<tr><td>${esc(h.format)}</td><td>${h.click_url_form === "absolute" ? "full URL" : "bare path"}</td><td class="n">${h.labeled}</td><td class="n">${h.included}</td><td class="n">${h.names_advertiser}</td>
     <td class="n">${h.disclosed}</td><td class="n">${h.framing.discounted}</td><td class="n">${h.linked}</td><td class="n">${h.any_link}</td></tr>`).join("");
} else document.getElementById("realCard").style.display = "none";
document.getElementById("page").textContent = R.sample_page;
document.getElementById("examples").innerHTML = R.examples.map(e =>
  `<div class="ex"><div class="meta">${esc(e.agent)} · “${esc(e.query)}”</div>
   <div>${esc(e.answer)}</div>
   <div class="meta">Detected by: <b>${esc(e.detected_by)}</b> · label ${e.disclosed ? "kept" : "dropped"}</div></div>`).join("");
document.getElementById("foot").innerHTML =
  `Simulated data · ${fmt(R.config.n_per_agent)} answers per agent · seed ${R.config.seed} · ` +
  `${fmt(R.traffic.sessions)} traffic sessions. Rebuild with <code>python -m lab.run &amp;&amp; python scripts/build_dashboard.py</code>.`;
</script>
</body>
</html>
"""


def main() -> None:
    data = json.loads(RESULTS.read_text())
    data["real"] = json.loads(REAL.read_text()) if REAL.exists() else None
    payload = json.dumps(data).replace("</", "<\\/")
    OUT.write_text(TEMPLATE.replace("__DATA__", payload))
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
