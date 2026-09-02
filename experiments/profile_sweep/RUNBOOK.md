# Profile sweep — runbook

Run **after** the DGX Spark is free from the current job. Read
[HYPOTHESIS.md](HYPOTHESIS.md) first — the predictions are registered in advance
and the point of the run is to test them, not to find a good number.

## What this answers

The first experiment reported capacity-violation rates at a single profile
(`p3_historian`). A reviewer can object that at `p3` only 10 of 97 ICS
techniques are evidenceable *at all*, so the gate rejects ~90% of possible
claims by construction — restrictiveness of the profile, not a property of the
models.

This sweep runs the same items and models at every instrumentation tier. If
violation falls as instrumentation improves, the gate is tracking evidence
availability. If it stays flat, it is not, and we need to know that now.

## Why `bare` is not re-run

The bare prompt contains no telemetry list, so the model's answer is
**identical regardless of profile** — only the scoring changes. `analyse_sweep.py`
re-scores the existing bare answers from `results/experiment_*.csv` against all
five profiles with **zero** model calls.

Consequence: **only the `instrumented` condition needs running.** That halves the
job from ~8,100 calls to ~4,065.

## Cost

271 items × 5 profiles × 3 models = **4,065 calls**, instrumented only.

Extrapolating from the first run's timing: deepseek and gemma ~20–40 min per
profile, qwen ~10× slower per call. Budget roughly **6–10 hours** total,
overnight. The driver is resumable — a completed profile is skipped, so an
interrupted sweep restarts where it stopped.

## Run

One model at a time if vLLM serves one model per process. Use the **exact** ids
from `--list-models`, and keep every other parameter identical to the first run
(temperature 0, `max_tokens` 1024, same context length, qwen still
`enable_thinking=false`) — otherwise the sweep is not comparable to it.

```bash
python experiments/profile_sweep/run_sweep.py \
    --backend openai --host http://localhost:8000 \
    --model "<deepseek-id>" --name deepseek

python experiments/profile_sweep/run_sweep.py \
    --backend openai --host http://localhost:8000 \
    --model "<gemma-id>" --name gemma

python experiments/profile_sweep/run_sweep.py \
    --backend openai --host http://localhost:8000 \
    --model "<qwen-id>" --name qwen
```

`--name` must be `deepseek` / `gemma` / `qwen` so the analysis can pair the
sweep with the original bare answers.

Smoke test first if anything about the server changed:

```bash
python experiments/profile_sweep/run_sweep.py ... --name deepseek --limit 20 --profiles p1_flow
```

## Analyse

```bash
python experiments/profile_sweep/analyse_sweep.py
```

Writes `sweep_results.csv` and `fig_profile_sweep.pdf/.png` into this folder, and
prints an explicit HOLDS / FAILS verdict for each pre-registered hypothesis.

## Reading the output

The figure plots capacity violation against instrumentation, with the **ontology
limit** (the fraction of checkable techniques evidenceable at each tier) as a
dashed reference line. That line is model-independent — it is what the ATT&CK
detection model permits, and no model can beat it.

| what you see | what it means |
|---|---|
| violation falls toward zero at `+controller` | **H1 holds.** The gate tracks instrumentation. The `p3` result stands. |
| violation stays flat | **H1 fails.** The gate is not measuring what it claims. Stop and investigate before writing. |
| `says_provable` tracks the dashed line | models are calibrated to available evidence; the gate's value narrows to the residual |
| `says_provable` ignores the dashed line | models assert provability independently of what they have — the core argument for external enforcement |
| the three model lines converge at high tiers | models only diverge when evidence is scarce — weakens the between-model argument |
| the spread persists at every tier | you cannot rely on model choice; enforcement must be external |

## Results to keep

```
out/experiment_sweep_*.csv               raw per-item answers
experiments/profile_sweep/sweep_results.csv
experiments/profile_sweep/fig_profile_sweep.*
```

`out/` is gitignored — force-add the raw CSVs or copy them into `results/` as
the first run did.
