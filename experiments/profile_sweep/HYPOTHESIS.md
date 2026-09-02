# Profile sweep — pre-registered hypothesis

**Registered 2026-09-02, before any sweep run.** Recorded here so the result
cannot be read as post-hoc rationalisation, whichever way it falls.

## Amendment 1 — 2026-09-02, still before any sweep run

The ontology-side sensitivity analysis in
[`experiments/profile_robustness/`](../profile_robustness/) found that
`p5_controller`'s 100% ceiling rests entirely on a single generic data
component, `Application Log Content`. It appears in 41 ICS analytics but is the
sole requirement of only 2; in the other 39 it completes an analytic whose other
requirements are already met, so it lands all at once. Remove it and p5 falls
from **100% to 51.8%**.

H1 as originally written reasoned from "at p5 every checkable technique is
evidenceable". That premise is an artefact of one component — and one *we*
placed in the controller tier, not one MITRE put there.

**Amendment:** add a variant tier `p5b_controller_strict` = `p5_controller`
minus that component, and register H1's "approaches zero" claim **against p5b,
not p5**. Both are run and both are reported. p5b is a variant, not a sixth
cumulative tier, so monotonicity is tested over p1..p5 only.

Cost: +271 calls per model, +813 total.

Nothing else changes, and no sweep data existed when this was written.

**Disclosure.** No *instrumented* sweep data existed at registration or at this
amendment. However, the zero-cost re-scoring of the ORIGINAL bare answers
across profiles (see RUNBOOK §"Why bare is not re-run") had already been run
and examined before this amendment, and it shows violation falling
monotonically with instrumentation in the bare condition. The genuinely open
predictions therefore concern the **instrumented** condition — in particular
H3, whether models recalibrate when told what telemetry they have. We state
this so the registration cannot be read as stronger than it is.

## Amendment 2 — 2026-09-02, before any sweep run — PENDING RATIFICATION

Decomposing the first experiment's violations by `arm5_outcome` shows the
as-scored `capacity_violation` conflates three classes:

| class | meaning | catchable by |
|---|---|---|
| `fail` | id resolves, ontology consulted, evidence structurally insufficient | **capacity gating only** |
| `undefined` | ontology specifies no requirements | neither check |
| `unknown-technique` | id does not resolve | plain id-resolution grounding |

Only `fail` (and arguably `undefined`) is invisible to referential grounding;
counting unresolvable ids toward "invisible to grounding" overstates the
contribution, materially for qwen (22.5% of items).

Separately, v19 renumbered nine ICS techniques into T16xx sub-techniques
(April 2026, at or after every evaluated model's training cutoff), so models
answering the pre-v19 id (e.g. T0857 for System Firmware) are scored
unknown-technique for knowing only the numbering they were trained on. Every
remap target FAILS at `p3_historian`, so resolving stale ids never clears a
violation — it reclassifies it from unknown-id into `fail`.

**Amendment (pending supervisor ratification):**

1. Raw CSVs and the registered metric `capacity_violation` are unchanged.
2. All reporting decomposes violations into the three classes.
3. The headline defensible number is **grounding-invisible after stale-id
   remapping** = violations whose remap-resolved technique is `fail` or
   `undefined`. On the first experiment (instrumented): deepseek 7%,
   gemma 58%, qwen 19%.
4. Attribution is reported both as-scored and remapped.
5. The sweep analyser's registered quantities (H1's `violation_resolved`
   sequence) are computed exactly as registered; the decomposition is
   reported alongside, derived from the same CSVs.

## The objection this answers

At `p3_historian` only **10 of 97** ICS techniques are evidenceable at all. A
reviewer can therefore say:

> Your gate rejects roughly 90% of all possible claims by construction. That is
> not discrimination — it is a gate stuck on "no". The reported
> `capacity_violation` rates measure the restrictiveness of your chosen profile,
> not any property of the models.

That objection is fair and cannot be argued away in prose. It has to be tested.

## The test

Run the same items and the same models across all five instrumentation profiles.
The ontology ceiling — the fraction of the 85 checkable techniques that are
evidenceable at each tier — is already known from the measurement study:

| profile | evidenceable (of 85 checkable) |
|---|---|
| `p1_flow` | 1.2% |
| `p2_dpi` | 9.4% |
| `p3_historian` | 11.8% |
| `p4_host` | 50.6% |
| `p5_controller` | 100% |
| `p5b_controller_strict` *(variant, Amendment 1)* | 51.8% |

## Primary prediction

**H1 — `capacity_violation` falls monotonically across `p1..p5` as
instrumentation improves, and approaches zero at `p5b_controller_strict`.**

At `p5` every checkable technique is evidenceable, so a claim can only violate
capacity if the model names an `UNDEFINED` technique or an unresolvable ID.
Violation should therefore collapse to roughly the UNDEFINED + unknown-ID rate,
not to the 40–72% seen at `p3`.

**Per Amendment 1 the floor is judged at p5b, not p5.** p5's 100% is carried by
one catch-all component, so a collapse to zero there would be cheap. p5b is the
honest test: 51.8% of checkable techniques evidenceable, and violation should
still fall substantially below the `p3` rate without reaching zero.

- **If H1 holds**: the gate tracks instrumentation rather than rejecting
  reflexively. The `p3` numbers measure a real property of a real deployment.
- **If H1 fails** — violation stays flat across profiles — the gate is not
  measuring what it claims, and we need to know that before submission rather
  than after review.

## Secondary predictions

**H2 — `arm5_capacity_pass` rises with the ceiling.** Should approximately track
the table above. Large deviation means models preferentially name techniques
that are (or are not) evidenceable, which would itself be worth reporting.

**H3 — `model_says_provable` does *not* track the ceiling.** This is the
calibration claim. A perfectly calibrated model would assert provability at
roughly the rate the ontology permits. We predict models assert provability at a
rate largely independent of how much telemetry they are told they have —
overshooting badly at low profiles, and possibly undershooting at `p5`.

The quantity of interest is the **calibration gap**:

```
calibration_gap = model_says_provable − arm5_capacity_pass
```

positive = over-claiming, negative = under-claiming, zero = calibrated.

**H4 — the between-model spread persists at every profile.** deepseek stays best
calibrated, gemma worst, at all five tiers. If the spread closes at high
instrumentation, the architectural argument weakens: it would mean models only
diverge when evidence is scarce.

## What would change the paper

| outcome | consequence |
|---|---|
| H1 holds, H3 holds | strongest case. Gate tracks instrumentation; models do not. Report as the main defence of the `p3` result. |
| H1 holds, H3 fails | models *are* calibrated to available telemetry; the gate's value drops to catching the residual. Honest, weaker, still publishable. |
| H1 fails | serious. The gate is not tracking instrumentation. Investigate before submitting anything. |

## Run parameters, fixed in advance

- items: all 271 ATT&CK ICS procedure examples
- profiles: p1..p5 cumulative, plus the p5b variant (Amendment 1) = 6 runs per model
- models: deepseek-v4-flash, gemma-4-26b-moe, qwen3.8-27b (non-thinking, matching the first run)
- temperature 0, `max_tokens` 1024, identical context settings to the first run
- condition: **`instrumented` only** — see RUNBOOK.md §"Why bare is not re-run"
