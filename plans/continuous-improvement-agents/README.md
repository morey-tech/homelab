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
- The deployed `Qwen3-30B-A3B-quantized.w4a16` endpoint is the model baseline. Model changes are evaluated, not assumed to be improvements.
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

## Phase 0 — evidence, authoring, and feasibility

Target: 2–3 weekends. Run locally or in a development namespace; do not wait for #187.

### 0.1 Freeze inputs and rules

- Build and review the corpus manifest; reconcile the grouped and individual transcript views.
- Define the RR worker boundary, allowed tools, citation format, redaction rules, and current-fact verification rule.
- Set hard budgets for worker prompt, retrieved context, trace summary, coach prompt, output tokens, queue time, and total run time.
- Define the failure-class taxonomy before scoring runs.

### 0.2 Author the human source material

Use the worksheets in [`worksheets/`](worksheets/):

- At least 20 transcript evidence notes spanning the selected pilot topics.
- 10 RR domain-principle cards derived from those notes.
- 10 coach doctrine cards derived from personal notes or licensed copies of *The High-Velocity Edge* and *Wiring the Winning Organization*.
- 20 financial-guidance evaluation scenarios: 10 calibration and 10 held-out.
- 10 coaching scenarios, each with a related transfer task.

The model may normalize formatting or flag missing fields, but it must not invent the source doctrine. A human reviews every evidence note and card before it enters the frozen set.

### 0.3 Build the smallest evaluation runner

- Use deterministic retrieval over the pinned corpus. A local lexical/BM25 index is sufficient for Phase 0.
- Store inputs, retrieved source IDs, outputs, scores, model settings, and timings as versioned fixtures or JSONL.
- Implement deterministic checks first: citation resolution, required fields, calculation fixtures, budget limits, and critical-failure gates.
- Use a blinded human rubric only for qualities that cannot be tested mechanically.

### 0.4 Run the experiment

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
- produces an effect large enough to justify a second inference pass.

If it does not, ship the static checklist and retain the evaluation suite. Do not build the coaching platform.

## Phase 1 — minimal durable pilot

Entry condition: Phase 0 supports continuing.

- Implement the RR worker, coach, and deterministic LangGraph controller.
- Keep coach invocation limited to pre-brief, abnormality, and after-action review.
- Add per-agent concurrency, token, and queue limits before multi-user use.
- Add `TaskRecord` and `ImprovementRecord` persistence with redaction at the write boundary.
- Resolve placement after #187: deploy directly to the compact cluster if ready; otherwise deploy migration-ready on `ocp-gpu`.
- Decide the PostgreSQL location before implementation. If pgvector is selected, use an image that actually includes the extension.
- Keep tools read-only and require human approval for experiments.

Exit: the Phase 0 comparison can be reproduced from the deployed workflow, records survive restart, and no unredacted sensitive data is persisted.

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