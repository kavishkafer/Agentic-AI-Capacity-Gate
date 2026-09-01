# Evidential capacity gating over MITRE ATT&CK

Given a claim that an attack technique occurred, and the telemetry a site
actually collects, **could that telemetry ever have proven the claim?**

This is a decidable check over ATT&CK v18+'s published detection model:

```
C(c) = OR  over DET in Strategies(T)
       OR  over AN  in Analytics(DET)
       AND over dc  in DataComponents(AN) :  dc in coverage(c)
```

Technique `T` is evidenceable iff at least one of ATT&CK's own detection
analytics has **all** of its required data components available. Any route
counts; each route is all-or-nothing.

The same function serves two purposes: as a **runtime gate** (coverage derived
from a claim's cited evidence) and as a **measurement instrument** (coverage set
to a hypothetical instrumentation profile, swept across every technique).

## What is and is not authored here

The defence against circularity is structural, and it is enforced by the file
layout:

| File | Authored? |
|---|---|
| `src/attack.py` | **No** — reads the published STIX bundle |
| `src/gate.py` | **No** — the formula; nothing domain-specific |
| `src/profiles.py` | **Yes** — instrumentation tiers; the only judgement we supply |

The requirement side is entirely MITRE's. We supply only what a deployment can
observe, and we sweep it. `src/export_dettect.py` re-expresses those profiles in
DeTT&CT data-source administration format so they can be diffed against a real
estate rather than taken on trust.

## Quick start

```bash
python fetch_data.py            # ~107 MB of ATT&CK bundles (or --minimal for 4 MB)
python src/run_analysis.py      # measurement tables + CSVs
python src/demo.py              # one converged incident through Gates A/B/C
python src/figures.py           # figures (needs matplotlib)
python tests/test_gate.py       # 10 tests
```

Standard library only, except `figures.py`.

## The LLM experiment

Does a model claim techniques it cannot evidence from the telemetry it has been
told is available?

**See [RUNBOOK.md](RUNBOOK.md) for the full sequence — it has a stop gate at the
smoke test that matters.** Short version:

```bash
python src/experiment.py --backend openai --host http://localhost:8000 --list-models
python src/experiment.py --backend openai --host http://localhost:8000 \
    --model "<id>" --limit 20 --tag smoke     # check parse_ok first
python src/experiment.py --backend openai --host http://localhost:8000 \
    --model "<id>" --tag <name>               # 271 items x 2 conditions
python src/aggregate.py
```

Backends: Ollama, any OpenAI-compatible server (vLLM, TGI, llama.cpp), or an
offline `mock` for testing the harness.

Two checks are applied to every answer:

- **arm 4 — referential grounding**: did the model cite only telemetry that exists?
- **arm 5 — evidential capacity**: does ATT&CK require components the site lacks,
  for the technique the model claimed?

`missed_by_grounding` counts the gap: the model cited only real evidence, asserted
provability, and named a technique that evidence cannot support. A grounding check
accepts it; a capacity check does not.

## Three outcomes, not two

An analytic with no declared data components is *trivially* satisfied by a subset
test — the empty set is a subset of everything. Collapsing that into `PASS` lets
the least-evidenced claims through silently, so the gate distinguishes:

| | |
|---|---|
| `PASS` | at least one analytic fully covered |
| `FAIL` | the evidence cannot support the claim |
| `UNDEFINED` | ATT&CK specifies no requirements — no capacity check is possible |

`UNDEFINED` is a statement about the ontology, not the evidence. In ICS v19.2 it
covers all 12 Impact-tactic techniques.

## Layout

```
fetch_data.py       retrieve ATT&CK bundles (hash-verified)
src/
  attack.py         resolve Technique -> Strategy -> Analytic -> DataComponent
  gate.py           the capacity formula, three-valued
  profiles.py       instrumentation tiers            [authored]
  claims.py         claim model, Gates A and B
  packets.py        incident items from ATT&CK procedure examples
  llm.py            pluggable model client
  experiment.py     the LLM experiment
  aggregate.py      cross-model results + figure
  run_analysis.py   measurement tables
  figures.py        paper figures
  demo.py           worked incident
  export_dettect.py profiles -> DeTT&CT YAML
tests/test_gate.py  10 tests
```

`ANALYSIS.md` is the running record of what was built, what was found, and the
bugs that turned into findings.
