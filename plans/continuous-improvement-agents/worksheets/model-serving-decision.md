---
id: MSD-___
status: draft
gpu: NVIDIA RTX 3090 24GiB
serving_platform: OpenShift AI KServe
engine: vLLM
author:
reviewer:
reviewed_on:
---

# Model-serving decision worksheet

Use this once for each shortlisted model/configuration pair. Model identity and serving settings are one decision: the same weights can behave very differently when context, KV cache, batching, and parsers change.

## Candidate identity

| Field | Value |
| --- | --- |
| Publisher and repository | |
| Immutable model revision | |
| License and use constraints | |
| Architecture | dense / MoE / hybrid |
| Total / active parameters | |
| Weight quantization | |
| Runtime dtype | |
| Native context limit | |
| Text-only mode available | |
| Tool parser and chat template | |
| Reasoning parser | |
| vLLM and RHOAI runtime versions tested | |

## Why this candidate

- Expected strength for RR financial guidance:
- Expected strength for Socratic coaching:
- Expected weakness:
- Reason to prefer it over the current Qwen configuration:
- Reason to reject it early:

## Fixed workload profiles

Use identical prompts, retrieved chunks, outputs, and concurrency shapes for every candidate.

| Profile | Concurrent requests | Input tokens each | Output cap each | Notes |
| --- | ---: | ---: | ---: | --- |
| RR worker | 1 | 10,000 | 1,500 | Domain prompt plus bounded transcript retrieval |
| Coach | 1 | 8,000 | 1,000 | Summarized trace, not raw transcript/history |
| Mixed interactive | 3 | 10k / 10k / 8k | 1.5k / 1.5k / 1k | Two workers plus one coach |
| Off-peak evaluation | 4 | 6,000 | 1,000 | Throughput-oriented replay |

Adjust these profiles only by versioning the worksheet; do not tune a profile per model.

## Serving configuration

| vLLM setting | Tested value | Rationale/result |
| --- | --- | --- |
| `--dtype` | | |
| `--quantization` | | |
| `--max-model-len` | 16384 / 24576 / control | Bound worst-case cache use; do not maximize automatically |
| `--gpu-memory-utilization` | | Use for profiling; record actual KV allocation |
| `--kv-cache-memory-bytes` | | Pin the measured safe allocation for repeatable deployment if supported |
| `--kv-cache-dtype` | auto / fp8 | FP8 requires an accuracy comparison |
| `--max-num-seqs` | 2 / 4 / 6 | Bound concurrent scheduler work |
| `--max-num-batched-tokens` | 2048 / 4096 / 8192 | Compare inter-token latency and throughput |
| Prefix caching | enabled | Use a cryptographic hash for multi-tenant safety |
| Prefix-cache hash | sha256 | |
| Chunked prefill | enabled / runtime default | Verify in logs; record actual behaviour |
| Long-prefill threshold | | Prevent long RR prompts from starving short requests |
| Watermark/preemption setting | | Record recompute preemptions |
| Tool-call parser | | Must match the model's documented template |
| Reasoning parser | | |
| Language-model-only | | Use for multimodal models when supported to recover memory |
| CPU/KV offload | disabled / experiment | Not a substitute for choosing a model that fits |

## Memory and cache measurements

Record values from startup logs and a loaded run; do not estimate from parameter count alone.

| Measurement | Value |
| --- | ---: |
| Total GPU memory | |
| Peak weight/runtime memory | |
| Allocated GPU KV-cache bytes | |
| KV-cache token capacity | |
| Maximum concurrency at 16k tokens reported by vLLM | |
| Stable mixed-profile concurrency | |
| Prefix-cache hit rate | |
| Recompute preemptions | |
| CUDA OOMs | |
| Host RAM and shared memory used | |

### Artifact cache

- Artifact size on disk:
- Tokenizer/template/additional files:
- Active model plus rollback model:
- Temporary download/unpack headroom:
- Required PVC/ModelCar/node-cache capacity:
- Storage class and physical device:

Size persistent/local artifact storage from measured artifacts: active model + rollback model + temporary staging + at least 25% operational headroom. A generic 100 GiB PVC is not automatically accepted.

## Quality results

| Suite | Score | Critical failures | Notes |
| --- | ---: | ---: | --- |
| RR calibration scenarios | | | |
| RR held-out scenarios | | | |
| Coaching scenarios | | | |
| Tool-call/schema fixtures | | | |
| Citation and calculation checks | | | |

## Performance results

| Profile | TTFT p50/p95 | Inter-token latency p50/p95 | Tokens/s | Queue p95 | Successful requests |
| --- | --- | --- | ---: | --- | ---: |
| RR worker | | | | | |
| Coach | | | | | |
| Mixed interactive | | | | | |
| Off-peak evaluation | | | | | |

## KServe deployment decision

- `ServingRuntime` or supported `ClusterServingRuntime`:
- Runtime image pinned by digest:
- `InferenceService` deployment mode:
- Model delivery: `ModelCar / PVC / object storage`:
- Replica count: `1`
- GPU request/limit: `1`
- CPU, RAM, `/dev/shm`, and ephemeral-storage requests/limits:
- Node selector/affinity for the 3090 node:
- Startup, readiness, and liveness probes:
- Route/authentication and NetworkPolicy:
- Metrics endpoint and ServiceMonitor:
- Rollback model/configuration:

## Selection gate

- [ ] Meets every critical financial-safety gate.
- [ ] Resolves tool calls and structured outputs with the pinned template/parser.
- [ ] Fits one 24 GiB RTX 3090 without CPU weight offload in the primary profile.
- [ ] Sustains the mixed interactive workload without OOM.
- [ ] Preemption and queue latency remain within declared limits.
- [ ] Coach quality beats the static checklist enough to justify its capacity cost.
- [ ] Context truncation does not materially reduce retrieval-grounded quality.
- [ ] FP8 or other KV quantization passes the same quality suite if enabled.
- [ ] Artifact cache supports active and rollback revisions.
- [ ] KServe manifest is reproducible and GitOps-managed.

## Decision

`selected / rejected / retain as rollback / benchmark control`

Rationale:


Known risks and next validation date: