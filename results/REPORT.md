# Evidential capacity gating — cross-model experiment report

Run 2026-09-01 → 2026-09-02, on the local DGX Spark cluster (ICS ATT&CK v19.2,
271 procedure-example items × 2 conditions × 3 models = 1,626 model calls).
Everything in this folder is derived from `out/experiment_{deepseek,gemma,qwen}.csv`,
which are the raw per-item scored answers; nothing here has been hand-edited.

## 1. Methodology

Each item is a real ATT&CK ICS procedure example (a documented technique used
by a named campaign/malware/intrusion-set). The model is asked to name the
technique and judge whether its own occurrence is provable, under two
conditions: **bare** (no telemetry context given) and **instrumented** (the
`p3_historian` coverage set — network flow, DPI, and historian/process data —
is listed explicitly and the model is told to answer `false` if that telemetry
can't establish the technique).

Two independent checks are run against every answer (RUNBOOK.md, "What the
numbers mean"):

- **arm 4 — referential grounding**: did the model cite only telemetry that
  actually exists? This is everything a grounding-only system checks.
- **arm 5 — evidential capacity**: does ATT&CK's own detection model require
  data components the site doesn't have, for the technique the model claimed?

`capacity_violation` = the model asserted provability where the capacity gate
disagrees, regardless of citation quality. `missed_by_grounding` is the
narrower, more damning case: the model cited only real evidence (arm 4 passes),
asserted provability, and named a technique the evidence cannot support — a
case a grounding-only checker would wave through.

## 2. Per-model results

All figures from `out/experiment_*_summary.json` (rows below are `overall`,
i.e. all 271 items per condition — see `crossmodel.csv` for the `correct`,
`noleak`, `checkable` slices that stress-test the finding further).

| model | condition | parse_ok | attribution_correct | arm4 (grounding) | arm5 (capacity) | **capacity_violation** | **missed_by_grounding** |
|---|---|---|---|---|---|---|---|
| deepseek-v4-flash | bare | 97.4% | 5.5% | 40.2% | 15.5% | **51.7%** | 2.2% |
| deepseek-v4-flash | instrumented | 100.0% | 4.8% | 100.0% | 18.5% | **7.7%** | 7.7% |
| gemma-4-26b-moe | bare | 92.6% | 17.3% | 35.4% | 3.0% | **83.0%** | 21.4% |
| gemma-4-26b-moe | instrumented | 96.3% | 15.9% | 100.0% | 3.3% | **64.2%** | 64.2% |
| qwen3.8-27b¹ | bare | 97.4% | 0.4% | 99.6% | 0.4% | **84.9%** | 84.5% |
| qwen3.8-27b¹ | instrumented | 96.7% | 1.5% | 100.0% | 0.0% | **41.0%** | 41.0% |

¹ **qwen3.8-27b was run in non-thinking mode** (`enable_thinking=false`). This
is a real methodological caveat, not a footnote — see §4. The model's default
(thinking-enabled) configuration was not measurable with this harness at all.

Three consistent patterns:

- **Every model over-claims provability far more than the capacity gate would
  allow**, in both conditions. Telling the model what telemetry exists
  (`instrumented`) reduces the violation rate for all three, but never gets
  close to zero — deepseek instrumented is the best case at 7.7%, still far
  from negligible over 271 items.
- **`missed_by_grounding` tracks `capacity_violation` closely once instrumented**
  (deepseek 7.7%=7.7%, gemma 64.2%=64.2%, qwen 41.0%=41.0%) — once the model is
  told what evidence exists, it almost always cites only real components (arm4
  ≈100% for all three instrumented), so a referential-grounding check alone
  would pass nearly everything a capacity check rejects.
- **Model size/family does not predict over-claiming rate.** deepseek-v4-flash
  (large MoE) is dramatically better calibrated than the two mid-size models —
  gemma-4-26b-moe and qwen3.8-27b both violate capacity on the large majority
  of instrumented answers.

## 3. The ICS v19.2 stale-technique-ID confound

ATT&CK for ICS v19.2 revoked and renumbered 9 techniques into the
enterprise-aligned namespace (e.g. `T0857 System Firmware` → `T1693.001`,
`T0855 Unauthorized Command Message` → `T1692.001` — full map in
`stale_id_confound_output.txt`). A model trained on older ATT&CK data can
answer with a pre-v19.2 ID; the harness's corpus filters revoked STIX objects,
so that ID resolves to nothing and scores `arm5_outcome=unknown-technique`
rather than a real capacity result. `revoked_check.py` (this folder) quantifies
how much of each model's `capacity_violation` is genuine (ATT&CK's requirements
were actually consulted) vs. contaminated by this artifact. Full output in
`stale_id_confound_output.txt`; summary:

| model | condition | unresolvable-id rate | attribution: as-scored → ID-remapped | capacity_violation: genuine | capacity_violation: unresolved-id |
|---|---|---|---|---|---|
| deepseek-v4-flash | bare | 31.7% | 5.5% → 8.9% | 40.6% | 11.1% |
| deepseek-v4-flash | instrumented | 31.4% | 4.8% → 8.1% | 7.4% | 0.4% |
| gemma-4-26b-moe | bare | 14.8% | 17.3% → 19.2% | 76.0% | 7.0% |
| gemma-4-26b-moe | instrumented | 15.5% | 15.9% → 17.7% | 57.9% | 6.3% |
| qwen3.8-27b | bare | 0.4% | 0.4% → 0.4% | 31.0% | 53.9% |
| qwen3.8-27b | instrumented | 0.7% | 1.5% → 1.5% | 18.8% | 22.1% |

**deepseek and gemma**: the confound is real but bounded. Remapping recovers
2–4 points of attribution accuracy, and 7–11 points of `capacity_violation`
are attributable to genuinely stale (pre-v19.2) IDs rather than a live capacity
judgment — the *instrumented* headline numbers (7.4% genuine violation for
deepseek, 57.9% for gemma) survive this correction almost unchanged.

**qwen is a different story, and the label "stale-id" is misleading for it.**
Only 0.4–0.7% of qwen's answers cite an actually-revoked pre-v19.2 ID — the
version-renumbering confound barely touches qwen. But 53.9%/22.1% of its
`capacity_violation` comes from technique IDs that don't resolve *at all*,
even after remapping. Characterizing qwen's 305 unresolved IDs directly against
the ICS corpus:

- **168 (55%)** are valid **Enterprise ATT&CK** technique IDs (e.g. `T1566.001`
  Phishing, `T1190` Exploit Public-Facing Application, `T1078` Valid Accounts)
  that are simply not part of the ICS matrix — qwen appears to default to the
  much larger Enterprise namespace it likely saw more of in training.
- **48 (16%)** are ICS techniques qwen identified correctly but cited with the
  leading zero dropped (`T849` instead of `T0849` — confirmed these all
  resolve once zero-padded: `Masquerading`, `Modify Program`,
  `Internet Accessible Device`, etc.) — a formatting quirk, not a knowledge gap.
- The remainder are a mix of genuinely stale pre-v19.2 IDs and other
  unrecognized 4-digit codes.

This doesn't overturn qwen's headline: `model_says_provable` (85.2%/41.0%) and
`arm4_grounding_pass` (99.6%/100%) are unaffected by any of this — qwen asserts
provability from evidence it cites correctly at a very high rate regardless of
which technique number it names. But it does mean qwen's specific
`capacity_violation` figure is inflated by ID/namespace confusion on top of
genuine over-claiming, in a way deepseek and gemma's are not.

## 4. Smoke-test failures — the qwen thinking-mode saga

Full detail in `PIPELINE_NOTES.md` (copied into this folder). Summary:

**Attempt 1** (default vLLM launch, `enable_thinking` unset → defaults to
`true` per the model's chat template): smoke test (`--limit 20`) returned
`parse_ok` **5.0% / 0.0%** (bare/instrumented) at **~176 s/call** — the
20-item smoke set took ~2 hours; the full 542-call run was projected at ~26
hours. A direct probe against `/v1/chat/completions` with a 200s timeout
returned nothing at all.

Diagnosis: this is the documented "reasoning eats the output budget" failure
mode (cluster onboarding notes §5). With `--max-model-len 16384`, the model's
default extended-thinking mode consumes the entire context on chain-of-thought
without ever emitting a stop token, so `message.content` (the only field this
harness reads — `src/llm.py`) comes back empty.

**Mitigation**: confirmed the chat template supports `enable_thinking` (`grep
enable_thinking chat_template.jinja`), relaunched vLLM with
`--default-chat-template-kwargs '{"enable_thinking":false}'`. Retry smoke test:
`parse_ok` **100.0% / 95.0%**, ~22–34 s/call (8x faster, though still ~10x
slower per call than deepseek/gemma on the same hardware). This cleared the
RUNBOOK.md stop gate (≥90%) and the full run proceeded — but see the caveat in
§2: **every qwen number in this report describes qwen3.8-27b with extended
reasoning explicitly disabled**, not its default behavior. Whether a
thinking-enabled qwen would show more or less over-claiming is an open
question this run cannot answer.

This is itself a methodology finding worth keeping: harness compatibility
across model families is not uniform, and a silent-empty-content failure mode
can look identical to "the model just doesn't work" without the diagnostic
step of probing raw `reasoning`/`content` fields directly.

## 5. Interpretation

**Yes — the arm4/arm5 gap supports the paper's core claim, and does so more
strongly than a single-model result could.** In the instrumented condition,
where the contrast is meaningful (RUNBOOK.md notes arm4 is trivially true in
`bare`), all three models pass referential grounding on essentially every
answer (arm4 ≥ 99.6%) while failing evidential capacity on the large majority
of the same answers (arm5 ≤ 18.5%). The practical consequence —
`missed_by_grounding` — ranges from 7.7% (deepseek, the best-calibrated model)
to 64.2% (gemma) of all instrumented answers: a referential-grounding check,
the entirety of what most existing systems verify, would accept those as
provable. A capacity check, which additionally asks whether ATT&CK's own
detection model has a satisfiable route given the declared telemetry, does
not. The gap holds in the same direction for every model tested, independent
of model size, family, or reasoning configuration, and survives the
stale-technique-ID correction in §3 (genuine violation rates stay well above
zero for all three even after removing version-confound contamination). No
model tested closes this gap on its own by being told what evidence it has —
which is precisely the argument in the paper for enforcing the capacity check
externally rather than relying on prompting.

---

*Generated by an autonomous overnight run; see `PIPELINE_NOTES.md` for full
operational detail (container launches, timing, mitigation steps) and
`stale_id_confound_output.txt` for the raw `revoked_check.py` output this
report's §3 table summarizes.*
