# Embedding model comparison plan

Compare Qwen3-Embedding-0.6B and Qwen3-Embedding-4B on retrieving useful, properly qualified podcast teaching material. The decision is whether the larger model improves retrieval enough to justify its CPU time and RAM on `tr-gpu`. This phase evaluates retrieval and returned context; lesson writing and Discord delivery stay outside the experiment.

Status: input preparation works locally. The HTTP embedding adapter, scoring runner, approved relevance labels, and held-out evaluation set are not implemented yet. No comparison scores have been measured.

## Prepare the starter inputs

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  kubernetes/ocp-mgmt/applications/rr-lessons/prototype/evaluation/build_inputs.py \
  --repo /projects/rr-scraper \
  --output /tmp/rr-embedding-eval-inputs-v1
```

Read `/tmp/rr-embedding-eval-inputs-v1/review.md` to review the questions alongside exact source passages and neighbors. `inputs.json` records source commits and hashes, parser and builder hashes, query groups, context requirements, and outstanding gates. Exact episode snapshots are saved alongside it. Use a fresh output directory for each revision.

The committed `seed-queries.json` pins transcript commit `8b0c3b7570d217d5296ac6dd81f10042d120c5c9`. Its short evidence anchors must each match exactly once in that committed transcript; dirty checkout changes are ignored. The builder resolves them to the existing preparation pipeline's passage IDs, offsets, and citation links. It makes no inference requests, downloads no model, and changes no database or cluster resources.

| Starter input | Count | Purpose |
|---|---:|---|
| Episodes 428 and 429 | 2 | Reproducible source material already explored in the prototype |
| Answerable query groups | 6 | Career paths to ownership, income denominators, ownership risk, static allocation, return chasing, and human capital/leverage |
| Queries in those groups | 12 | Plain paraphrases, daily lesson briefs, mechanisms, distinctions, and false premises needing corrective evidence |
| Negative queries | 4 | Two unrelated requests and two finance-related requests the corpus cannot answer |
| Held-out queries | 0 | All starter queries are development material; none can establish a model winner |

The old `/tmp` preparation reports and five-record index were absent when this plan was built. The source-only bundle therefore honestly records **zero eligible teaching-question records**, not a fabricated benchmark corpus. Anchored passages are draft evidence targets, not record-level relevance labels. The builder always marks its output `draft_not_scorable`.

Once fresh preparation reports exist, supply repeated `--report` arguments to include a validated selection. For example, with reports prepared for the same pinned source:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  kubernetes/ocp-mgmt/applications/rr-lessons/prototype/evaluation/build_inputs.py \
  --repo /projects/rr-scraper \
  --report /tmp/rr-episode-428-eval \
  --report /tmp/rr-episode-429-eval \
  --output /tmp/rr-embedding-eval-with-corpus-v1
```

These report directories must first be created using `prepare.py` as described in the [prototype README](../README.md), with the pinned source revision, recorded generation-model revision, and **full episodes**. The prior three-section limit misses later leverage material. Report selection reuses `retrieve.select_reports`: only eligible high-confidence candidates enter the experiment, and their pending human-review status remains unchanged. Reports from another source snapshot fail validation. The builder writes the exact `selection.json` and its hash when reports are supplied. Adding more episodes requires updating the seed episode list and recording a new bundle.

## Freeze the corpus and relevance labels

1. Prepare episodes once with one pinned extraction/review configuration. Both embedding models receive the same selected records. Do not regenerate teaching questions between embedding runs.
2. Inspect source support for every selected record. Fix or exclude unsupported candidates before freezing. A model's `high` confidence is a selection aid, never the evaluation answer key or production approval.
3. Map each development query to actual `selection.json` record IDs by reading the record's evidence, neighboring passages, qualifications, and question. A passage-ID overlap is insufficient to establish relevance. Allow multiple useful records, including records from another episode.
4. Assign grades below to every query/record pair for the starter corpus. For the larger corpus, judge the union of both models' top 10, lexical baseline top 10, and known source-linked candidates with model identities and ranks hidden. Record unjudged entries as `null`; resolve every top-five result before scoring. Pooled judgments can miss other relevant records, so label larger-corpus Recall@5 as recall against judged positives and expand the pool if needed.
5. Freeze `selection.json`, approved `queries.json`, and `qrels.jsonl` with SHA-256 hashes before scoring. A judgment includes `query_id`, `record_id`, `grade`, `reason`, `evidence_ids`, `reviewer`, and `reviewed_at`. `reviewer` must identify the actual reviewer; it must not be filled automatically with an invented approval.

| Grade | Criterion |
|---:|---|
| 3 | Directly answers or corrects the query and includes the necessary attribution, assumptions, and qualifications |
| 2 | Substantively useful, but only addresses part of the question or needs additional context |
| 1 | Related topic or vocabulary, without useful support for the requested explanation |
| 0 | Irrelevant, misleading for this query, or supports a conflicting interpretation |

False-premise queries are answerable when retrieved context corrects the premise. A leverage discussion is merely related to a request for a personalized dollar amount; it does not make that negative query answerable. Negative labels must be reconsidered whenever the selected corpus changes. If an expected positive has no useful selected record, record a **corpus coverage failure** and repair the corpus or reclassify the query before evaluation. Do not charge extraction omissions to the embedding model or silently drop difficult cases.

Give near-duplicate teaching records a common relevance-unit ID before evaluation. Retrieve enough rows to report the first five distinct units for both models, and compute quality metrics on those units, so repeated versions of one answer cannot inflate the score. Preserve raw record rankings for diagnostics.

## Expand beyond the starter smoke test

Before a model-selection run, target at least **100 eligible records across six complete episodes**, spanning both familiar topics and additional topics such as diversification, fees, and retirement. Choose episodes by inspecting actual source coverage; do not assume these topics exist in the starter pair. Keep on-topic distractors in the corpus, especially salary versus ownership, fixed allocations versus return chasing, and borrowing costs versus expected returns.

Create at least **40 held-out queries: 30 answerable and 10 unsupported**, in addition to development queries. Hold out entire topic/evidence groups; two paraphrases of the same question cannot land on opposite sides of the split. Include queries from episodes whose topics were not used to tune instructions. A human should write natural queries without copying indexed questions and approve relevance from source evidence before inspecting model rankings. The starter set is assistant-authored and already visible, so it is unsuitable as held-out evidence.

Use development data to choose formatting, any acceptance threshold, and performance settings. Freeze these before revealing held-out scores. Record source coverage and all exclusions. This is a small, task-specific evaluation, not evidence of general embedding superiority.

## Keep the comparison controlled

| Setting | Primary comparison |
|---|---|
| Services | `qwen3-embedding-0-6b` and `qwen3-embedding-4b` in `inference-server` |
| Revisions | 0.6B: `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`; 4B: `5cf2132abc99cad020ac570b19d031efec650f2b` |
| Runtime | Same deployed Red Hat image digest, FP32, eight configured threads / eight CPU limit each |
| Dimensions | Native 1,024 versus 2,560; record vector storage cost. Equal-dimension comparison is a separate follow-up |
| Indexed text | Exactly `concept + "\n" + question`, as in `retrieve.py` |
| Returned payload | Original answer outline, qualifications, prerequisites, evidence, and neighboring passages |
| Query formatting | Same task instruction for both models; no instruction on documents |
| Search | Exact cosine search in separate local LanceDB databases; no ANN, reranker, or generation |
| Truncation | None; check fully formatted inputs against both tokenizers and the 4,096-token serving limit |
| Corpus | Same frozen selection, stable IDs, ordering, and duplicate relevance units |

Use the [Qwen model card's query instruction format](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B):

```text
Instruct: Given a podcast learning request, retrieve teaching questions whose source context supports a useful and qualified explanation.
Query:{query}
```

Verify last-token pooling and normalize all finite, nonzero vectors to unit length in the evaluation adapter. Request native dimensions in the first comparison. Keep prompt text and preprocessing hashes in each run manifest. Never mix one model's query vectors with another model's index. The [4B model card](https://huggingface.co/Qwen/Qwen3-Embedding-4B) documents its native dimensions. A lexical baseline using the same indexed text is required to show that gains extend beyond word matching; existing local BGE is optional context, not a third mandatory deployment.

Record actual service specs, runtime versions, resource limits, utilization settings, and node load. The 0.6B memory-utilization override differs from the 4B default; preserve and disclose it. Resource allocations need not be identical, but do not silently change them between runs. Call only one embedding model at a time for the controlled comparison. Both may remain resident; record other workloads and repeat contaminated performance samples.

## Test sequence and artifacts

1. **Readiness and API gate:** both deployed services are healthy with stable restart counts. Verify authentication enforcement, model identity, expected output dimensions, finite nonzero vectors, input/output order in batches, and repeated-input cosine agreement of at least 0.999. Confirm over-limit input is rejected without silent truncation. Record failures before quality testing; the earlier CPU startup failure makes readiness a prerequisite.
2. **Starter smoke test:** embed the same selection with each model, retrieve all 16 draft development queries, and present blinded side-by-side context for human labeling. Do not publish a winner or treat draft labels as ground truth.
3. **Development:** expand the corpus, review judgments, fix coverage gaps, choose the common instruction, and calibrate any relevance threshold separately for each model. Record every tuning decision.
4. **Frozen quality run:** embed the approved held-out queries once, store ranked results and cosine distances, then compute per-query, per-group, per-query-type, and aggregate metrics. Show source context for every regression, not just average scores.
5. **Performance run:** with both models ready, make five unmeasured warm-up requests each. Alternate model order across three rounds. Use the same fixed, hashed input list: 100 single-query requests per round and corpus ingestion with batch sizes 1 and 8. Record request token counts and batch lengths; batch 8 is an API load test even though the server schedules at most two sequences concurrently. Keep HTTP retries off for measurement and count failures/timeouts explicitly. Repeat query text embeddings as requests; do not use a client cache. Report medians and p95 across all measured requests, plus each round.
6. **Decision:** apply the criteria below. Keep borderline cases provisional and gather more independent query groups rather than tuning against the held-out set.

Measure end-to-end authenticated embedding latency, corpus embedding wall time, input tokens/second, CPU usage/throttling, pod memory working set/peak, restart counts, and vector/index bytes. Report cold startup separately from warm latency using an observed GitOps rollout; do not restart pods or change deployments just to benchmark. Record readiness-to-first-request latency separately. Operational checks must follow the repository's GitOps workflow.

Each run directory should contain `run.json` (source, labels, corpus and configuration hashes; service URLs without credentials; model revisions; image digest; software versions; timestamps; node resources), immutable input copies, one index per model, raw rankings, request timing/error records, metrics JSON, and a readable comparison with examples. Never persist bearer tokens or authorization headers. Store generated transcript excerpts, vectors, and large results outside Git; commit the plan, seed definitions, and eventually the runner and reviewed compact labels.

## Evaluation criteria and decision rule

These are proposed prototype acceptance targets to freeze before the held-out run, not measured results or existing service guarantees.

| Measure | Definition / target |
|---|---|
| Primary: nDCG@5 | Graded gain `2^grade - 1`, log2 rank discount, ideal ranking from judged distinct relevance units; mean at least 0.80 on answerable queries |
| Useful first result | Fraction of answerable queries whose first unit has grade 2 or 3; at least 80% |
| Recall@5 | Fraction of judged grade-2/3 units retrieved in the first five distinct units, averaged across answerable queries; at least 90%. Also report Hit@5 (any useful unit), which is a different measure |
| MRR@5 | Reciprocal rank of the first grade-2/3 unit, or zero if absent; diagnostic, not the primary selection criterion |
| Evidence integrity | 100% of returned evidence IDs, offsets and source hashes resolve; no fabricated source text or citations |
| Context usefulness | Human review finds sufficient qualifications and attribution in at least 90% of top-ranked grade-2/3 payloads; every false-premise case must preserve corrective context |
| Unsupported requests | Raw nearest-neighbor search always returns results. Only evaluate rejection if a relevance gate is implemented: calibrate on development data, then target at most 10% false acceptance on held-out negatives while accepting at least 80% of held-out answerable queries |
| Reliability | No OOM kills/restarts attributable to the measured workload; no malformed/nonfinite vectors; every error or timeout reported, never dropped from latency accounting |
| CPU cost | Provisional warm single-query p95 at most 30 seconds and embedding 100 teaching records within 15 minutes at batch 8; report RAM and CPU alongside quality |

Exclude negative queries from nDCG/Recall/MRR rather than assigning them arbitrary ideal rankings. For answerable queries with zero judged positives, fail dataset validation. For a relevance gate, specify exactly which score and comparison direction it uses, calibrate each model's threshold independently, and report accepted-query coverage alongside rejection errors. Raw cosine distances are not calibrated confidence. Without this gate, report unsupported-query behavior descriptively and mark automatic daily use as unready; it does not block a retrieval-only comparison.

Average paraphrases within each query group, then macro-average groups for the primary comparison. Use a paired bootstrap over **groups**, not repeated timing requests or individual near-duplicate queries, with 10,000 resamples and a recorded seed to estimate the 95% interval for the 4B-minus-0.6B nDCG difference. Keep per-query and per-type results visible. With a small held-out set the interval may remain wide.

Prefer 0.6B if both meet the gates and quality is practically tied. Choose 4B only if it meets the operational targets and improves held-out group-averaged nDCG@5 by at least **0.05 absolute**, with the paired interval above zero and no loss of critical corrective context. If 0.6B fails a quality gate and 4B passes, inspect the failures and use that as additional evidence; still disclose uncertainty. If neither passes, select neither and diagnose corpus coverage, context assembly, query formatting, and retrieval design before enlarging the model. A retrieved lesson must remain source-supported regardless of the winning embedding model.

## Next implementation

First generate and review the full-episode corpus and starter input bundle. Then add an authenticated HTTP embedder to the local prototype, using the existing token-file or `oc` login approach, and an evaluation runner that refuses draft/missing judgments for scored runs. Keep a distinct exploration mode for draft inputs. Test metric calculations with hand-computable rankings, tied scores, multiple positives, duplicate units, empty positives, and negatives before collecting model scores. Only after the comparison should retrieval be considered for the daily lesson workflow.
