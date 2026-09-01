# Runbook — the LLM experiment

Operational sequence for running the experiment against a local model server.
Follow in order; step 2 is a **stop gate**.

## 0. Setup

```bash
python fetch_data.py --minimal          # 4 MB, ICS v19.2 only — all the experiment needs
```

Standard library only. Nothing to install unless you want figures (`matplotlib`).

## 1. Confirm the harness sees the models

```bash
python src/experiment.py --backend openai --host http://localhost:8000 --list-models
```

- vLLM / TGI / llama.cpp / LM Studio → `--backend openai`, default port usually `8000`
- Ollama → `--backend ollama`, default port `11434` (this is what `auto` tries first)

**Use the exact ids printed.** vLLM reports whatever it was launched with, which is
usually the full HuggingFace repo path, not a short alias.

## 2. Smoke test — STOP GATE

```bash
python src/experiment.py --backend openai --host http://localhost:8000 \
    --model "<exact-id>" --limit 20 --tag smoke
```

Look at **`parse_ok`** in the printed table.

| parse_ok | action |
|---|---|
| **≥ 90%** | proceed to step 3 |
| **< 90%** | **stop.** Do not run the full set. |

A low parse rate means the model is wrapping JSON in prose or ignoring the schema.
Running 271 items in that state wastes an hour and produces rows that are
formatting failures rather than measurements.

If parse_ok is low, options in order of preference:

1. **Report it** — a model that cannot emit clean JSON when explicitly asked is
   itself a finding worth recording, and the harness measures models as they
   actually behave.
2. **Constrained decoding** — vLLM supports `guided_json`. Not used by default,
   deliberately: forcing schema compliance would mask the behaviour above. Add it
   only if the alternative is losing a model from the comparison entirely.
3. **Prompt tightening** — the schema block is in `src/experiment.py` (`SCHEMA`).

Repeat the smoke test per model. They fail differently.

## 3. Full runs

271 items × 2 conditions per model. Run inside `tmux` or `screen` — each model
takes roughly 20–60 minutes depending on size and hardware.

```bash
python src/experiment.py --backend openai --host http://localhost:8000 \
    --model "<deepseek-id>" --tag deepseek

python src/experiment.py --backend openai --host http://localhost:8000 \
    --model "<qwen-id>" --tag qwen

python src/experiment.py --backend openai --host http://localhost:8000 \
    --model "<gemma-id>" --tag gemma
```

If vLLM serves one model per process, do these sequentially, restarting the
server between them. If two are served on different ports, run in parallel with
different `--host` values.

**Tags matter** — `aggregate.py` reads every `out/experiment_*.csv`, and the tag
is how runs stay distinguishable.

## 4. Aggregate

```bash
python src/aggregate.py
```

Prints the cross-model table, writes `out/crossmodel.csv` and a figure.

## 5. Results to keep

Small; everything else is regenerable.

```
out/experiment_*.csv
out/experiment_*_summary.json
out/crossmodel.csv
```

These are gitignored, so to bring them back either force-add
(`git add -f out/experiment_*.csv`) or copy them off directly.

---

## What the numbers mean

Each model answer gets two independent checks. This is the comparison the
experiment exists to make.

| | Question | What it represents |
|---|---|---|
| **arm 4** | did the model cite only telemetry that actually exists? | everything a referential-grounding system checks |
| **arm 5** | does ATT&CK require components this site lacks, for the technique the model claimed? | the capacity check |

**`missed_by_grounding`** is the headline: the model cited only real evidence,
asserted the claim was provable, and named a technique that evidence cannot
support. Grounding accepts it. Capacity does not.

**`capacity_violation`** is the broader version — asserted provability where the
gate disagrees, regardless of whether the citations were grounded.

### Conditions

- **bare** — no telemetry context. `arm4` is trivially true here (nothing cited),
  so the arm4/arm5 contrast is only meaningful in the instrumented condition.
- **instrumented** — the available data components are listed and the model is
  explicitly told to answer `false` if they cannot establish the technique.

If behaviour barely differs between the two, that is the interesting result:
telling a model what evidence it has does not make it respect the limits, which
is the argument for enforcing capacity outside the model rather than asking for
it in the prompt.

### Slices in `aggregate.py`

Each defeats a specific objection:

| slice | objection it answers |
|---|---|
| `overall` | the headline |
| `correct` | *"it just misidentified the technique"* — restricted to correct attributions |
| `noleak` | *"the answer was in the prompt"* — 24% of narratives paraphrase the technique name; this excludes them |
| `checkable` | *"you counted techniques ATT&CK gives no requirements for"* — excludes the 12 UNDEFINED |

A finding that survives all four across three model families is hard to argue
with.

## Notes

- `--profile` selects the assumed instrumentation. Default `p3_historian`
  (network + DPI + historian) is the typical OT deployment. Others:
  `p1_flow`, `p2_dpi`, `p4_host`, `p5_controller`.
- Temperature is 0 throughout; runs should be near-deterministic. Repeating one
  model twice is a cheap stability check worth doing once.
- Timeout is 180 s per call. Raise it in `src/llm.py` if large models time out.
