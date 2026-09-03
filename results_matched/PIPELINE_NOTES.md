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

## Matched-config re-run (2026-09-02) — for publication rigor

Following a request to hold serving variables as constant as possible across
models for the paper, three things happened, in order.

### 1. `max_tokens` harness fix

The harness never set `max_tokens` explicitly in v1 — each model relied on its
server's implicit default. Added an explicit `--max-tokens` flag to
`src/experiment.py` (default 1024) and threaded it through `Client.chat()` in
`src/llm.py`. This is the actual methodological gap this re-run closes.

Effect on speed was **not uniform across models**: deepseek sped up
(~35min→~21min; the cap cut off previously-unbounded long tails), gemma slowed
down (~26min→~51min; cause unclear — possibly scheduling/batching behavior
change from the explicit field, not truncation, since answers were
unaffected), qwen's effect is confounded with the TP=2 change below. Answer
distributions (parse_ok, capacity_violation, missed_by_grounding) were
unchanged within noise for all three models — see `results_matched/REPORT.md`
§2 for exact numbers.

### 2. deepseek launch-command reconstruction failure (two crashes)

Attempted to also match deepseek's `max-model-len` (v1: `auto`) and
`kv-cache-dtype` (v1: `fp8`) to gemma/qwen's values. Both attempts crashed:

- Removing `--kv-cache-dtype fp8` (falls back to `auto`):
  `AssertionError: DeepseekV4 fp8_ds_mla layout only supports fp8 kv-cache, got auto`
- Setting `--max-model-len 16384` (down from `auto` = 1,048,576):
  `RuntimeError: Assertion error (.../layout.hpp:39): t.dim() == N` inside
  `_deepseek_v4_fp8_o_proj_einsum` (custom DeepGEMM FP8 kernel), during the
  profiling dummy-run.

Root cause: the relaunch command had been reconstructed from `docker exec
vllm_node ps aux` output on the original (pre-existing, 7-day-old) container,
which shows process argv but **not** environment variables or applied
source-code mods. The user supplied the actual original launch command, which
included:

```
--apply-mod mods/instanttensor-hybrid-draft-loader \
-e CUTE_DSL_ARCH=sm_121a -e VLLM_USE_AOT_COMPILE=1 -e VLLM_USE_BREAKABLE_CUDAGRAPH=0 \
-e VLLM_USE_MEGA_AOT_ARTIFACT=-1 -e VLLM_MEMORY_PROFILE_INCLUDE_ATTN=1 \
-e VLLM_USE_FLASHINFER_SAMPLER=1 -e VLLM_USE_B12X_WO_PROJECTION=1 -e VLLM_USE_B12X_MHC=1 \
-e VLLM_USE_B12X_FP8_GEMM=1 -e VLLM_USE_B12X_MOE=1 -e VLLM_USE_B12X_SPARSE_INDEXER=1 \
-e VLLM_USE_V2_MODEL_RUNNER=1 -e VLLM_MOE_SKIP_PADDING=0 \
-e B12X_MLA_SM120_UNIFIED=1 -e B12X_MOE_FORCE_A8=1
```

Relaunching with this mod+env set, `kv-cache-dtype=fp8`, and `max-model-len=auto`
(i.e. **identical to v1 in everything except the harness `max_tokens` cap**)
started cleanly with zero errors. **Lesson for future relaunches of this
model**: never reconstruct a `vllm-node-b12x` launch command from `ps aux`
alone — always capture the full `-e`/`--apply-mod` flags used, or ask whoever
set it up. `kv-cache-dtype=fp8` and `max-model-len=auto` are hard architectural
requirements for DeepSeek-V4-Flash on this kernel stack, not tunable choices.

### 3. qwen TP=2 experiment (explicit user request, separate from the above)

User asked to run qwen across both DGX Sparks (TP=2) instead of v1's solo
(TP=1), to test whether its slow single-stream decode (~4.3 tok/s in v1,
clearly the bottleneck of the whole session) was memory-bandwidth-bound.
Flagged to the user before proceeding that this breaks TP parity with gemma
(which stayed TP=1) — proceeded anyway per explicit instruction.

Launch (stock `vllm-node-tf5` image, no mods/env-vars needed, unlike deepseek):

```
./launch-cluster.sh -t vllm-node-tf5 --name vllm_qwen -d \
  exec vllm serve /home/dgx-spark-01/ai_data/models/Qwen3.8-27B-BF16 \
  --host 0.0.0.0 --port 8000 --served-model-name qwen3.8-27b \
  --tensor-parallel-size 2 --trust-remote-code \
  --max-model-len 16384 --gpu-memory-utilization 0.85 \
  --default-chat-template-kwargs '{"enable_thinking":false}'
```

Started cleanly on the first attempt across both nodes. Smoke test measured
**12.7 s/call (bare) / 14.2 s/call (instrumented)**, vs. v1's solo baseline of
~22–34 s/call — roughly **1.7–2x faster**. Full run: ~2h39m vs. v1's ~4h26m,
with answer distributions unchanged within noise. Confirms the v1 bottleneck
was genuinely memory-bandwidth-bound (qwen is dense/non-MoE, so TP=2 halves the
weight-read burden per GPU) rather than an artifact of the harness or a
fixable software issue.

### Timing summary (matched runs)

| model | matched full-run wall time | v1 wall time | config differences from v1 |
|---|---|---|---|
| deepseek-v4-flash | ~21 min | ~35 min | none besides harness `max_tokens=1024` |
| gemma-4-26b-moe | ~51 min | ~26 min | none besides harness `max_tokens=1024` (slower, cause unclear) |
| qwen3.8-27b | ~2h39m | ~4h26m | harness `max_tokens=1024` **and** TP=2 (was solo/TP=1) |

Full numbers and analysis in `results_matched/REPORT.md`.
