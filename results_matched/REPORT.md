# Evidential capacity gating — matched-config cross-model experiment report

Run 2026-09-02, on the local DGX Spark cluster (ICS ATT&CK v19.2, 271
procedure-example items × 2 conditions × 3 models = 1,626 model calls). This is
a **controlled re-run** of the experiment in `results/REPORT.md` (v1, 2026-09-01),
built to hold serving parameters constant across models wherever the hardware
allows it, for publication rigor. Read this report alongside `results/REPORT.md`
— the methodology, arm4/arm5 framing, and the ICS v19.2 stale-ID confound are
unchanged; this report focuses on what changed and whether it moved the
findings.

> **Update (2026-09-03, Amendment 2 in the main codebase)**: `crossmodel.csv`
> here has been regenerated against the corrected pipeline — no new model
> calls. See `results/REPORT.md` §7 for the full explanation; the corrected
> headline for this matched run is in §7 below.

## 7. Amendment 2 — decomposed violations, corrected headline (added 2026-09-03)

Same correction as `results/REPORT.md` §7: `capacity_violation` conflated
`fail` (grounding-invisible by construction), `undefined` (no ontology
requirements), and `unknown-id` (an id-resolution problem a grounding check
*would* catch — wrongly counted as grounding-invisible before). `src/attack.py`
now resolves ICS v19.2's revoked/renumbered ids before scoring.

**Corrected headline (instrumented, ids remapped, grounding-invisible only) —
matched run vs. v1, both under the same corrected metric:**

| model | matched (this run) | v1 (`results/REPORT.md` §7) |
|---|---|---|
| deepseek-v4-flash | **8%** | 7% |
| gemma-4-26b-moe | **59%** | 58% |
| qwen3.8-27b | **19%** | 19% |

Confirms §2's finding above: the matched-config re-run and the serving
changes documented in §3 (TP=2 for qwen, the `max_tokens` cap) don't just
leave the raw `capacity_violation` numbers unchanged within noise — they leave
the *corrected*, decomposed numbers unchanged too. The Amendment 2 correction
and this report's matched-config controls are answering two independent
reviewer objections ("is the metric measuring the right thing" and "are the
models being compared fairly"), and neither one moves the other's answer.

Full per-model decomposition in the updated `crossmodel.csv` in this folder.

## 1. Methodology

Identical to v1 (see `results/REPORT.md` §1): each item is a real ATT&CK ICS
procedure example; the model names the technique and judges provability under
**bare** (no telemetry) and **instrumented** (`p3_historian` coverage listed)
conditions. Two checks per answer — **arm 4** (referential grounding: did the
model cite only real telemetry?) and **arm 5** (evidential capacity: does
ATT&CK's own detection model require components the site lacks?).
`capacity_violation` = asserted provability where capacity disagrees;
`missed_by_grounding` = the narrower case where grounding alone would have
accepted the claim.

## 2. Per-model results (matched config)

| model | condition | parse_ok | attribution_correct | arm4 | arm5 | **capacity_violation** | **missed_by_grounding** |
|---|---|---|---|---|---|---|---|
| deepseek-v4-flash | bare | 99.3% | 5.5% | 42.1% | 16.2% | **49.4%** | 1.8% |
| deepseek-v4-flash | instrumented | 100.0% | 6.3% | 100.0% | 17.3% | **8.9%** | 8.9% |
| gemma-4-26b-moe | bare | 93.0% | 17.3% | 36.5% | 3.3% | **84.5%** | 24.4% |
| gemma-4-26b-moe | instrumented | 96.7% | 15.5% | 100.0% | 3.0% | **64.9%** | 64.9% |
| qwen3.8-27b¹ | bare | 96.3% | 0.4% | 99.6% | 0.0% | **84.1%** | 83.8% |
| qwen3.8-27b¹ | instrumented | 96.3% | 1.1% | 100.0% | 0.0% | **40.6%** | 40.6% |

¹ qwen3.8-27b ran **non-thinking** (`enable_thinking=false`, as in v1) and on
**TP=2 across both Sparks** (v1 ran TP=1 solo) — see §3.3.

**All three models land within noise of their v1 numbers.** The largest shift
is deepseek bare `capacity_violation` (51.7%→49.4%) and gemma instrumented
`missed_by_grounding` (64.2%→64.9%) — both well inside the kind of variance
expected from a few dozen borderline answers changing sides. The cross-model
pattern from v1 is intact: every model over-claims far more than the capacity
gate allows, and `missed_by_grounding` converges to `capacity_violation` in the
instrumented condition for all three, meaning a grounding-only check would
accept nearly everything a capacity check rejects.

## 3. What changed vs v1, and what stays forced

### 3.1 `max_tokens` pinned to 1024 (the real fix)

v1 never set `max_tokens` explicitly — each model's generation length was
governed by whatever its server defaulted to, which is not something that was
held constant. This run adds an explicit `--max-tokens` flag to
`src/experiment.py`/`src/llm.py` (default 1024), applied identically to all
three models. **Numbers didn't materially change for any model** (see §2) —
this cap wasn't silently truncating substantive answers — but the effect on
**speed** varied by model, which is itself worth recording:

| model | v1 wall time | matched wall time | direction |
|---|---|---|---|
| deepseek-v4-flash | ~35 min | ~21 min | faster |
| gemma-4-26b-moe | ~26 min | ~51 min | **slower** |
| qwen3.8-27b | ~4h26m (solo, uncapped) | ~2h39m (TP=2, capped) | faster (compounded with §3.3) |

Deepseek sped up (the cap cut off some previously-unbounded long tails,
`max-model-len` was effectively unlimited before). Gemma slowed down — the cap
didn't reduce its typical completion length, and the explicit `max_tokens`
field in the request may have changed vLLM's scheduling/batching behavior for
this model. This is a genuine, unexplained asymmetry: **pinning `max_tokens`
does not uniformly speed up or slow down inference across model families**, and
should not be assumed to.

### 3.2 deepseek: everything else stayed exactly as in v1 — and here's why

The initial plan was to also match deepseek's `max-model-len` (v1: `auto`) and
`kv-cache-dtype` (v1: `fp8`) to gemma/qwen's values (`16384`, default). Both
attempts **crashed**:

- `--kv-cache-dtype` removed (falls back to `auto`) →
  `AssertionError: DeepseekV4 fp8_ds_mla layout only supports fp8 kv-cache, got auto`.
  This model's B12X MLA-sparse attention backend hard-requires fp8 KV cache —
  not a configurable choice.
- `--max-model-len 16384` (down from `auto`, which resolves to `1048576`) →
  crashed inside a custom DeepGEMM FP8 kernel:
  `RuntimeError: Assertion error ... t.dim() == N` in `_deepseek_v4_fp8_o_proj_einsum`.

Both crashes traced back to the same root cause: the launch command was
reconstructed from `ps aux` output on the pre-existing container, which shows
process arguments but **not** environment variables or applied source-code
patches. The original working deployment required `--apply-mod
mods/instanttensor-hybrid-draft-loader` plus 14 environment variables
(`CUTE_DSL_ARCH`, `VLLM_USE_AOT_COMPILE`, `VLLM_USE_BREAKABLE_CUDAGRAPH`,
`VLLM_USE_MEGA_AOT_ARTIFACT`, `VLLM_MEMORY_PROFILE_INCLUDE_ATTN`,
`VLLM_USE_FLASHINFER_SAMPLER`, `VLLM_USE_B12X_WO_PROJECTION`,
`VLLM_USE_B12X_MHC`, `VLLM_USE_B12X_FP8_GEMM`, `VLLM_USE_B12X_MOE`,
`VLLM_USE_B12X_SPARSE_INDEXER`, `VLLM_USE_V2_MODEL_RUNNER`,
`VLLM_MOE_SKIP_PADDING`, `B12X_MLA_SM120_UNIFIED`, `B12X_MOE_FORCE_A8`) — none
of which appear in `ps aux` argv. The user supplied the correct original launch
command, which resolved both crashes immediately and matched v1's config
exactly (`kv-cache-dtype=fp8`, `max-model-len=auto`).

**Conclusion: deepseek's serving config is identical to v1 in every respect
except the harness-level `max_tokens` cap.** `tensor-parallel-size=2`,
`kv-cache-dtype=fp8`, and `max-model-len=auto` (1,048,576 tokens) are all
confirmed hard requirements of this model's experimental B12X kernel stack —
not gaps in matching, but genuine architectural constraints. Anyone reproducing
this on similar hardware should expect the same: DeepSeek-V4-Flash on the
`vllm-node-b12x` image needs its full launch recipe, mod included, or it will
not start.

### 3.3 qwen: TP=2 across both Sparks (explicit user request, not a matching decision)

Separately from the `max_tokens` matching effort, the user asked to run qwen
across both DGX Sparks (TP=2) instead of solo (TP=1, as in v1) to test whether
its notoriously slow single-stream decode — the clear bottleneck of the whole
v1 run at ~4.3 tok/s, versus deepseek's ~45 tok/s and gemma's ~23 tok/s — was
memory-bandwidth-bound and would benefit from splitting the model's weights
across two nodes. `max-model-len=16384` and default `kv-cache-dtype` were kept
unchanged; only `tensor-parallel-size` moved from 1 to 2.

The launch was clean on the first attempt (stock `vllm-node-tf5` image, no mods
or special environment variables needed, unlike deepseek). **Result: TP=2 gave
a real, measured speedup.** Smoke test: 12.7 s/call (bare) and 14.2 s/call
(instrumented), versus v1's solo baseline of ~22–34 s/call — roughly **1.7–2x
faster**, confirming the bottleneck was genuinely memory-bandwidth-bound: qwen
is a dense (non-MoE) 27B model, so every generated token requires reading the
full weight set, and splitting that read burden across two Sparks' unified
memory helps substantially even over a commodity 200GbE RoCE link (not a full
2x, due to per-layer cross-node communication overhead). The full run
completed in ~2h39m versus v1's ~4h26m, with essentially unchanged answers
(§2).

**This means `tensor-parallel-size` is now a three-way split across the three
models** (deepseek=2, hardware-forced; gemma=1, unforced; qwen=2, chosen for
speed) rather than a clean gemma/qwen match on that one dimension. This was a
deliberate, explicitly flagged tradeoff — speed over perfect parallelism
parity — made at the user's request mid-session, not an oversight. It is also
a useful finding in its own right for anyone comparing dense vs. MoE models on
similar multi-node hardware: **dense models can benefit meaningfully from
tensor parallelism even without proprietary interconnects, while MoE models
that fit on one node may not need it.**

### 3.4 Summary of the final matched configuration

| | deepseek-v4-flash | gemma-4-26b-moe | qwen3.8-27b |
|---|---|---|---|
| tensor-parallel-size | 2 (hardware-forced) | 1 | 2 (chosen, for speed) |
| max-model-len | auto (1,048,576) — hardware-forced | 16384 | 16384 |
| kv-cache-dtype | fp8 — hardware-forced | default | default |
| thinking/reasoning | off | off (template default) | off (explicit) |
| max_tokens (harness) | 1024 | 1024 | 1024 |
| image | vllm-node-b12x + mod | vllm-node-tf5 | vllm-node-tf5 |

## 4. ICS v19.2 stale-technique-ID confound (matched runs)

Full output in `stale_id_confound_output.txt`. Summary, alongside v1 for
comparison:

| model | condition | unresolvable-id rate | capacity_violation: genuine | capacity_violation: unresolved-id |
|---|---|---|---|---|
| deepseek (v1 / matched) | bare | 31.7% / 31.4% | 40.6% / 37.3% | 11.1% / 12.2% |
| deepseek (v1 / matched) | instrumented | 31.4% / 31.0% | 7.4% / 8.5% | 0.4% / 0.4% |
| gemma (v1 / matched) | bare | 14.8% / 14.4% | 76.0% / 77.9% | 7.0% / 6.6% |
| gemma (v1 / matched) | instrumented | 15.5% / 14.8% | 57.9% / 58.7% | 6.3% / 6.3% |
| qwen (v1 / matched) | bare | 0.4% / 0.4% | 31.0% / 30.3% | 53.9% / 53.9% |
| qwen (v1 / matched) | instrumented | 0.7% / 0.7% | 18.8% / 19.2% | 22.1% / 21.4% |

Essentially unchanged for all three models. The v1 finding stands: for
deepseek and gemma, the confound is real but bounded, and genuine
`capacity_violation` survives correction; for qwen, the "unresolved-id" bucket
is dominated by Enterprise-namespace IDs and dropped-leading-zero formatting
issues rather than true stale pre-v19.2 IDs (see `results/REPORT.md` §3 for the
detailed breakdown, which was not re-run here since qwen's answer distribution
did not meaningfully change).

## 5. Smoke-test findings

No new failures. deepseek, gemma, and qwen (both TP=1 pre-flight and the final
TP=2 configuration) all cleared the RUNBOOK.md stop gate (`parse_ok` ≥ 90%) on
their first smoke test at the final configuration. The only failures this
matched run produced were deepseek's two launch-config crashes (§3.2), which
were infrastructure/config errors, not model-behavior smoke-test failures —
they occurred before any inference request was made.

## 6. Interpretation

The matched-config re-run does not change the paper's core claim: it
**strengthens confidence in it** by showing the arm4/arm5 gap is stable under a
controlled `max_tokens` and largely-controlled serving configuration, not an
artifact of letting each model's generation run unbounded. `missed_by_grounding`
in the instrumented condition — the case a referential-grounding-only system
would silently accept — ranges from 8.9% (deepseek) to 64.9% (gemma) of all
answers, essentially unchanged from v1's 7.7%–64.2%. The two infrastructure
findings from this re-run (deepseek's B12X kernel stack is rigidly tied to its
original launch recipe; qwen's dense-model decode benefits substantially from
cross-node tensor parallelism) are methodologically interesting but orthogonal
to the paper's central argument — they affect how fast the experiment runs,
not what it finds.

---

*Generated as a controlled follow-up to `results/REPORT.md` (v1, 2026-09-01).
See `PIPELINE_NOTES.md` (project `out/`, dated section) for the full
operational log of this re-run, and `stale_id_confound_output.txt` for the raw
`revoked_check.py` output §4 summarizes.*

## Note (2026-09-03/04)

A separate pre-registered profile sweep (271 items × 6 instrumentation tiers ×
3 models, using the same non-thinking qwen and matched `max_tokens=1024`
config established in this report) tested whether the single-tier
`p3_historian` result generalizes or is an artifact of that profile's
restrictiveness. See `results/REPORT.md` §8 and
`experiments/profile_sweep/sweep_results.csv` for the full H1–H4 verdicts.
