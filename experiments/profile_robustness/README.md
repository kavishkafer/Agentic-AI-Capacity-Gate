# Experiment 3 — profile robustness

**No model calls. Runs on a laptop in a few seconds.**

```bash
python experiments/profile_robustness/robustness.py
```

## Why this exists

[`src/profiles.py`](../../src/profiles.py) is the only authored input in the
whole analysis. Everything else — `gate.py`, `attack.py` — is derived from the
published ATT&CK bundle. Every capacity number in the paper therefore rests on
five tier definitions we wrote ourselves, and a reviewer is entitled to ask
whether they were chosen to produce the result.

This experiment answers that from the ontology alone, with no models involved.

## What it reports

**1. Tier summary.** What each tier buys, and per component. The value is wildly
non-monotone — one component at `p2_dpi` buys 7 techniques, the four historian
components at `p3` buy 2 between them.

**2. Criticality.** Leave-one-out over every component in every tier. Shows what
is load-bearing and what is decoration.

**3. Catch-all.** Every tier recomputed without `Application Log Content`.

**4. Null profiles.** Each authored tier against 2,000 random component sets of
the same *effective* size — effective meaning "components ICS analytics actually
reference", since the rest are inert and counting them would make the null
unfair. This is the direct answer to *"you cherry-picked the tiers."*

**5. Acquisition order.** Greedy: what a site should instrument first. This is
the practitioner-facing output.

Writes `robustness_*.csv` and `fig_robustness.pdf/.png` here.

## The three findings

### p5's 100% ceiling is one data component

`Application Log Content` appears in 41 ICS analytics but is the sole
requirement of only 2. In the other 39 it completes an analytic whose other
requirements are already satisfied, so it lands all at once:

| tier | as authored | catch-all excluded |
|---|---|---|
| p1_flow … p4_host | unchanged | unchanged |
| **p5_controller** | **100.0%** | **51.8%** |

This is why `p5b_controller_strict` was added and why
[HYPOTHESIS.md Amendment 1](../profile_sweep/HYPOTHESIS.md) re-registers H1's
floor against p5b. It is also a finding in its own right: the ATT&CK ICS
detection model's apparent completeness at full instrumentation is carried by a
generic catch-all, not by specific OT telemetry.

### The historian tier is nearly worthless to ATT&CK

`p3_historian` adds four components — process history, device alarms, event
alarms, asset inventory — and buys **2 techniques**. Its 10 evidenceable
techniques rest on *network* telemetry: dropping `Network Traffic Content` costs
8, dropping `Network Traffic Flow` costs 8.

Process data is what OT sites actually have. ATT&CK ICS detection barely uses
it. Same family of result as `UNDEFINED`.

### The tiers are not cherry-picked, and the reason the large ones look bad is the finding

| tier | effective size | authored | random median | percentile (mid-p) |
|---|---|---|---|---|
| flow | 2 | 1 | 0 | 67% |
| +DPI | 3 | 8 | 1 | >99% |
| +historian | 7 | 10 | 3 | 97% |
| +host | 32 | 43 | 75 | 10% |
| +ctrl strict | 33 | 44 | 81 | 4% |

Percentiles are mid-p (ties counted half), so the small discrete counts at the
low tiers do not inflate them.

The small tiers sit **above** their size class — they were not built to look
restrictive, and the low ceilings at p1–p3 are the ontology's, not ours.

The large tiers sit **below** theirs, and that is the interesting half: a broad
host profile can hold nearly the whole component pool and still miss what
matters, because the components ICS analytics lean on hardest are the
controller-side ones a real plant is least likely to have.

## Determinism

Seeded (`SEED = 20260902`, `N_NULL = 2000`). Reruns reproduce exactly.
