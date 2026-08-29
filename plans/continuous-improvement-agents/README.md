# Issue #188 — Continuous-improvement agent pilot

Status: proposed implementation plan

Related issues: [#188](https://github.com/morey-tech/homelab/issues/188), [#187](https://github.com/morey-tech/homelab/issues/187)

## Pilot decision

The first domain agent will provide evidence-grounded financial-planning guidance using the Rational Reminder transcript corpus in [`morey-tech/rr-scraper`](https://github.com/morey-tech/rr-scraper). The first experiment asks:

> Does a separate continuous-improvement coach make the Rational Reminder worker more likely to recognize and solve the next related problem independently than either the uncoached worker or the same worker with a static improvement checklist?

The pilot is one RR worker, one coach, one deterministic controller, and one shared vLLM endpoint. A static checklist is a valid final result if it performs as well as or better than the coach.

## Boundaries

- The RR worker distinguishes transcript-derived principles from current legal, tax, product, rate, and regulatory facts.
- The corpus is evidence for Rational Reminder views; it is not automatically current law, a product database, or a substitute for missing client facts.
- Advice must expose assumptions, uncertainty, trade-offs, and missing information. It must not manufacture personalized certainty.
- Transcript citations identify the episode and source locator used. No fabricated citation is acceptable.
- Phase 0 runs without PostgreSQL, pgvector, A2A, Llama Stack, Tempo, or Loki. Versioned fixtures and JSONL results are sufficient to decide whether the mechanism works.
- The current `Qwen3-30B-A3B-quantized.w4a16` Deployment is a benchmark control, not the presumptive final model or serving configuration. Phase 0 selects the model and settings; Phase 1 replaces the hand-built Deployment with KServe.
- Traces are redacted before persistence. Secrets, credentials, account identifiers, and unnecessary personal data never enter fixtures, records, lessons, or retrieval content.

## Known corpus condition

The Phase 0 corpus must be pinned to `rr-scraper` commit `77da0971b7601f761302343a6ef636426ad88560` until deliberately refreshed.

| Corpus view | Observed state | Phase 0 action |
| --- | --- | --- |
| `transcripts/all.md` | About 26 MB | Use as the completeness reference, not as one prompt |
| `transcripts/groups_of_20/` | 21 files, through episode 424 | Use to reconcile coverage |
| `transcripts/individual/` | 362 files | Reconcile missing episodes before treating this as the retrieval corpus |

Create a manifest containing source commit, episode number, available paths, content hash, title/date/guest when available, and ingestion status. Freeze the manifest with the evaluation suite.

## Experimental arms

| Arm | Worker | Improvement mechanism | Purpose |
| --- | --- | --- | --- |
| A — baseline | RR domain prompt + retrieval | None | Measure uncoached performance |
| B — checklist | Same worker and retrieval | Fixed doctrine checklist appended to the prompt | Test whether a cheap static intervention is enough |
| C — coach | Same worker and retrieval | Separate coach at pre-brief, abnormality, or after-action review | Test whether diagnosis and transfer improve future performance |

All arms use the same model version, corpus snapshot, retrieval results, tool permissions, token budget, sampling settings, and scenario ordering. The coach never sees held-out expected behaviours or scoring keys.

## Model-serving decision track

The existing implementation is an ordinary Kubernetes `Deployment` using a `latest` runtime tag, a 100 GiB model PVC, `GPU_MEMORY_UTILIZATION=0.92`, and a script that searches downward from a 40,960-token maximum until vLLM starts. It does not explicitly bound sequences or batched tokens, and it optimizes for the largest single context rather than the mixed worker/coach workload.

Phase 0 must choose a complete serving profile, not just a model name:

- model repository and immutable revision;
- license, architecture, total/active parameters, weight quantization, and runtime dtype;
- model chat template, tool-call parser, and reasoning parser;
- maximum per-request context and output limits;
- GPU KV-cache bytes and dtype;
- maximum sequences and batched tokens;
- prefix-caching, chunked-prefill, long-prefill, and preemption settings;
- CPU/RAM, `/dev/shm`, ephemeral storage, and GPU resources;
- artifact delivery and local model-cache capacity; and
- the pinned OpenShift AI/KServe/vLLM runtime image.

Use [`worksheets/model-serving-decision.md`](worksheets/model-serving-decision.md) for each candidate. Refresh the shortlist when Phase 0 starts, but include at least:

| Candidate class | Purpose |
| --- | --- |
| Current quantized Qwen3 30B-A3B | Control against the existing deployment |
| Strong tool-capable 8B-class model | Maximum KV-cache and concurrency control |
| Strong tool-capable 12B–16B-class model | Balanced capability/capacity candidate |
| Recent small-active-parameter MoE that fits one 3090 when quantized | Test whether MoE quality justifies its larger weight footprint |

Reject any candidate that lacks a documented vLLM-compatible chat template/tool parser, fails the financial-safety gates, or needs CPU weight offload for the primary workload.

### Workload and cache target

The target is not several simultaneous 40k conversations. The primary mixed profile is two RR workers plus one coach, where each RR request is bounded around 10k input/1.5k output and the coach receives an approximately 8k summarized trace with a 1k output cap. Evaluation replay runs off-peak.

Benchmark:

- context ceilings of 16,384 tokens first and 24,576 only if quality requires it; keep 40,960 as a comparison, not a default;
- `max-num-seqs` of 2, 4, and 6;
- `max-num-batched-tokens` of 2,048, 4,096, and 8,192;
- auto/FP16 KV cache versus FP8 KV cache only when the runtime and model support it and the frozen quality suite shows no material loss;
- explicit secure prefix caching and chunked prefill; and
- the actual KV-cache bytes, token capacity, reported max concurrency, recompute preemptions, TTFT, inter-token latency, throughput, queue time, and OOM rate.

During profiling, let vLLM measure available cache from a conservative GPU-memory-utilization value. For the selected configuration, record and pin the measured safe KV-cache allocation when the installed runtime supports explicit cache bytes. Do not use a startup retry loop to discover production settings.

Model artifact cache is a separate capacity decision. Size it from the measured active model + rollback model + download/unpack staging + at least 25% headroom. The existing 100 GiB PVC remains only if that calculation supports it.

## Phase 0 — evidence, authoring, and feasibility

Target: time-box to 3–4 weekends, including serving benchmarks. Run locally or in a development namespace; do not wait for #187.

### 0.1 Freeze inputs and rules

- Build and review the corpus manifest; reconcile the grouped and individual transcript views.
- Define the RR worker boundary, allowed tools, citation format, redaction rules, and current-fact verification rule.
- Set hard budgets for worker prompt, retrieved context, trace summary, coach prompt, output tokens, queue time, and total run time.
- Define the failure-class taxonomy before scoring runs.
- Record the current Deployment as the serving control, including its model revision, runtime image, actual KV capacity, latency, throughput, OOM behaviour, and tool-call fidelity.

### 0.2 Author the human source material

Use the worksheets in [`worksheets/`](worksheets/):

- At least 20 transcript evidence notes spanning the selected pilot topics.
- 10 RR domain-principle cards derived from those notes.
- 10 coach doctrine cards derived from personal notes or licensed copies of *The High-Velocity Edge* and *Wiring the Winning Organization*.
- 20 financial-guidance evaluation scenarios: 10 calibration and 10 held-out.
- 10 coaching scenarios, each with a related transfer task.

The model may normalize formatting or flag missing fields, but it must not invent the source doctrine. A human reviews every evidence note and card before it enters the frozen set.

### 0.3 Select the model and serving profile

- Create the model shortlist and immutable revisions.
- Deploy each candidate through a temporary KServe `InferenceService` using the supported vLLM NVIDIA `ServingRuntime` or a pinned compatible custom `ServingRuntime`.
- Run the fixed worker, coach, mixed-interactive, and off-peak-evaluation workload profiles.
- Score domain quality, coaching quality, tool/schema fidelity, context truncation, KV capacity, concurrency, preemption, latency, throughput, and OOMs.
- Select one primary and one rollback model/configuration. Preserve every decision worksheet and raw result.
- Produce the GitOps-ready KServe manifests, but do not retire the existing Deployment until the selected `InferenceService` passes Phase 1 acceptance.

### 0.4 Build the smallest evaluation runner

- Use deterministic retrieval over the pinned corpus. A local lexical/BM25 index is sufficient for Phase 0.
- Store inputs, retrieved source IDs, outputs, scores, model settings, and timings as versioned fixtures or JSONL.
- Implement deterministic checks first: citation resolution, required fields, calculation fixtures, budget limits, and critical-failure gates.
- Use a blinded human rubric only for qualities that cannot be tested mechanically.

### 0.5 Run the experiment

1. Run Arm A on the calibration set and record failure classes.
2. Freeze the checklist, coach prompt, cards, scenarios, rubric, and retrieval configuration.
3. Run Arms A, B, and C on the held-out set.
4. Run each coaching scenario's transfer task without coach intervention.
5. Compare safety gates, task success, transfer success, groundedness, tokens, latency, and queue time.

### Phase 0 exit decision

Proceed with a coach only if it:

- beats the static checklist on predeclared primary metrics;
- improves related-task success without coach intervention;
- introduces no critical safety or citation regression;
- stays within the fixed context and latency budgets; and
- produces an effect large enough to justify a second inference pass; and
- has a selected model/KServe/vLLM configuration that sustains the mixed worker/coach profile on the 3090.

If it does not, ship the static checklist and retain the evaluation suite. Do not build the coaching platform.

## Phase 1 — minimal durable pilot

Entry condition: Phase 0 supports continuing.

- Replace the hand-built inference `Deployment`, `Service`, `Route`, download scripts, and auto-sizing loop with the selected GitOps-managed KServe `InferenceService`/`ServingRuntime` configuration.
- Pin the model revision and runtime image; provision the measured artifact cache and rollback capacity.
- Apply the selected context, KV-cache, sequence, batched-token, prefix-cache, prefill, parser, and resource settings.
- Implement the RR worker, coach, and deterministic LangGraph controller.
- Keep coach invocation limited to pre-brief, abnormality, and after-action review.
- Add per-agent concurrency, token, and queue limits before multi-user use.
- Add `TaskRecord` and `ImprovementRecord` persistence with redaction at the write boundary.
- Resolve placement after #187: deploy directly to the compact cluster if ready; otherwise deploy migration-ready on `ocp-gpu`.
- Decide the PostgreSQL location before implementation. If pgvector is selected, use an image that actually includes the extension.
- Keep tools read-only and require human approval for experiments.

Exit: the selected KServe endpoint survives restart and reproduces the Phase 0 quality/capacity result; the Phase 0 comparison can be reproduced from the deployed workflow; records survive restart; and no unredacted sensitive data is persisted. Only then remove the old inference Deployment.

## Phase 2 — observable learning loop

Entry condition: the durable pilot reproduces the Phase 0 effect.

- Add OpenTelemetry instrumentation for model calls, retrieval, tool calls, controller states, budgets, and evaluations.
- Choose and deploy the smallest justified backend. Tempo/Loki are not prerequisites unless trace volume and debugging needs justify them.
- Add a knowledge curator that can draft lessons and regression tests but cannot promote them.
- Require a regression test that fails on the current version and passes on the proposed version before a lesson is promotable.
- Compare baseline, checklist, and coach on additional held-out scenarios.

Exit: an observed failure can produce a reviewable lesson proposal and test with a complete evidence trail.

## Phase 3 — controlled promotion

Entry condition: Phase 2 shows repeatable learning rather than isolated prompt wins.

- Add the GitOps flow: proposal → branch → evaluation → human review → PR → Argo CD → canary → rollback.
- Enforce a hard per-agent prompt and retrieval budget.
- Require consolidation or eviction when a promoted lesson would exceed budget.
- Track recurrence by failure class and success on related tasks without coach intervention.
- Add canary comparison and automatic rollback on critical safety or quality regressions.

Exit: an approved lesson can be promoted and rolled back without allowing the coach to modify itself or the worker directly.

## Phase 4 — expand only after evidence

- Add pgvector retrieval for approved lessons if it beats the simpler retrieval baseline.
- Expand to 20–30 validated cards and a larger held-out suite.
- Add another domain agent and test whether the coaching mechanism transfers.
- Consider independently deployed agents and A2A only when deployment boundaries require it.
- Reconsider Llama Stack only after verifying the installed OpenShift AI and OpenShift prerequisites.

## Failure-class starter taxonomy

| Class | Example signal |
| --- | --- |
| Retrieval miss | Relevant transcript evidence exists but is not retrieved |
| Unsupported synthesis | Answer extends beyond what retrieved RR evidence supports |
| Citation failure | Episode/source locator is absent, wrong, or fabricated |
| Stale-current-fact confusion | Transcript statement is presented as current tax, legal, rate, or product fact |
| Missing-input overreach | Personalized recommendation is given despite material missing facts |
| Trade-off collapse | One option is presented as universally best |
| Calculation error | Arithmetic, units, timing, or assumptions are inconsistent |
| Advice-boundary failure | Guidance is framed with unjustified certainty or authority |
| Coach takeover | Coach completes the task instead of developing worker capability |
| Non-transfer | Coached worker succeeds once but fails the related task alone |
| Context-budget regression | New doctrine or lessons crowd out task/retrieval context |
| Sensitive-data persistence | Trace or artifact contains data prohibited by the redaction policy |

## Phase 0 decisions resolved

- [x] Pilot domain: Rational Reminder transcript-grounded financial planning.
- [x] Phase 0 does not wait for #187.
- [x] Static checklist is a legitimate winning outcome.
- [x] Phase 0 uses repository fixtures/JSONL; PostgreSQL is deferred.
- [x] Full OTel/Tempo/Loki is deferred until the mechanism shows value.
- [ ] Select the Phase 0 primary and rollback model/configuration.
- [ ] Validate the mixed worker/coach capacity target on the 3090.
- [ ] Size the model artifact cache and GPU KV cache from measurements.
- [ ] Phase 1 placement after #187.
- [ ] Phase 1 PostgreSQL and pgvector placement.

## Primary measures

| Category | Measure |
| --- | --- |
| Safety | Critical-failure rate; unsupported current-fact rate |
| Domain quality | Groundedness, factual/calculation correctness, assumption handling, usefulness |
| See | Failure detected before final answer or external action |
| Solve | Correct failure-class diagnosis and bounded experiment quality |
| Develop | Success on the related transfer task without coach intervention |
| Share | Accepted lessons with a regression test; recurrence by failure class |
| Efficiency | Tokens, latency, queue time, and GPU time per successful scenario |