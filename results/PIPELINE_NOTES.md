# Pipeline notes — CRCI 2026 experiment run (2026-09-01)

Operational notes from running `src/experiment.py` against three locally-served
models on the DGX Spark cluster. Kept alongside `out/` since it documents how
the numbers in `results/` were produced, not just what they are.

## qwen3.8-27b — thinking-mode failure and mitigation

**First attempt** (default launch, `enable_thinking` unset → defaults `true`
per the model's chat template):

```
python3 src/experiment.py --backend openai --host http://localhost:8000 \
    --model qwen3.8-27b --limit 20 --tag smoke_qwen
```

Result: `parse_ok` 5.0% (bare) / 0.0% (instrumented). ~176 s/call — the 20-item
smoke set alone took 3524s + 3601s ≈ 2 hours. At that rate the full 542-call run
would have taken ~26 hours.

Diagnosis: a direct probe (`curl` against `/v1/chat/completions` with a 200s
timeout) returned nothing — the call didn't even finish. This matches the
"reasoning eats the output budget" failure mode: `Qwen3.8-27B-BF16`'s chat
template defaults to extended thinking (`enable_thinking` is true unless set
otherwise — confirmed via `grep enable_thinking chat_template.jinja`), and with
`--max-model-len 16384` the model spends the entire context budget on
chain-of-thought without ever emitting a stop token or usable `content`. Our
harness (`src/llm.py`) only reads `message.content`, so this reads as silent,
near-total failure rather than an obvious error.

**Mitigation**: relaunched vLLM with extended reasoning explicitly disabled:

```
./launch-cluster.sh --solo -t vllm-node-tf5 --name vllm_qwen -d \
  exec vllm serve /home/dgx-spark-01/ai_data/models/Qwen3.8-27B-BF16 \
  --host 0.0.0.0 --port 8000 --served-model-name qwen3.8-27b \
  --tensor-parallel-size 1 --trust-remote-code \
  --max-model-len 16384 --gpu-memory-utilization 0.85 \
  --default-chat-template-kwargs '{"enable_thinking":false}'
```

Retry smoke test (`--tag smoke_qwen2`): `parse_ok` 100.0% (bare) / 95.0%
(instrumented) — clears the RUNBOOK.md stop gate (≥90%). ~22–34 s/call, ~8x
faster than the thinking-enabled attempt but still roughly 10x slower per call
than deepseek-v4-flash or gemma-4-26b-moe on the same hardware class (both
served with thinking off / non-reasoning by design).

**Caveat that must travel with every qwen number in the report**: this is
**qwen3.8-27b in non-thinking mode**. The model is not doing the extended
reasoning it would by default; results describe that configuration, not the
model's full-capability behaviour. This mirrors the documented mitigation
ordering in the cluster onboarding notes (§5): disabling thinking is the
"reliable but must-be-labeled" option, preferred here over silently falling
back to the `reasoning` field (option 3) because it required no harness code
changes and produced a usable parse rate immediately.

Full run launched under this configuration, tagged `qwen`
(`out/experiment_qwen.csv`). Given the measured pace, the full 542-call run
was estimated at ~4 hours.

## Timing summary (for context on the other two models)

| model | smoke parse_ok (bare/instr) | full-run wall time | notes |
|---|---|---|---|
| deepseek-v4-flash | 100% / 100% | ~35 min | TP=2, `--default-chat-template-kwargs.thinking=false` at launch (pre-existing 7-day-old container) |
| gemma-4-26b-moe | 100% / 100% | ~26 min | solo, no reasoning parser configured |
| qwen3.8-27b | 5%→100% / 0%→95% (2 attempts) | ~4 hr (est.) | solo, required thinking-disable mitigation; see above |
