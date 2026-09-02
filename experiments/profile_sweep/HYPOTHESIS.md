# Profile sweep — pre-registered hypothesis

**Registered 2026-09-02, before any sweep run.** Recorded here so the result
cannot be read as post-hoc rationalisation, whichever way it falls.

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

## Primary prediction

**H1 — `capacity_violation` falls monotonically as instrumentation improves, and
approaches zero at `p5_controller`.**

At `p5` every checkable technique is evidenceable, so a claim can only violate
capacity if the model names an `UNDEFINED` technique or an unresolvable ID.
Violation should therefore collapse to roughly the UNDEFINED + unknown-ID rate,
not to the 40–72% seen at `p3`.

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
- models: deepseek-v4-flash, gemma-4-26b-moe, qwen3.8-27b (non-thinking, matching the first run)
- temperature 0, `max_tokens` 1024, identical context settings to the first run
- condition: **`instrumented` only** — see RUNBOOK.md §"Why bare is not re-run"
