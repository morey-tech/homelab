# Episode ingestion prototype

This local CLI prepares one committed individual transcript for review. It uses
the existing `local-llm` service on the RTX 3090 to propose teaching questions and
review their support. It does not write to LanceDB, send Discord messages, run the
scraper, or alter the daily lesson workload. It is not included in Kustomize yet.

## Prepare an episode

Run from the homelab repository root with Python 3.10+ and Git. Unit tests require
Python 3.11+. The prototype has no additional Python dependencies.

Inspect source parsing without credentials or inference:

```bash
python3 kubernetes/ocp-mgmt/applications/rr-lessons/prototype/prepare.py \
  --repo /projects/rr-scraper \
  --revision 8b0c3b7570d217d5296ac6dd81f10042d120c5c9 \
  --episode 1 \
  --prepare-only \
  --output /tmp/rr-episode-1-source
```

Generate and review teaching questions using your authenticated ocp-mgmt context:

```bash
python3 kubernetes/ocp-mgmt/applications/rr-lessons/prototype/prepare.py \
  --repo /projects/rr-scraper \
  --revision 8b0c3b7570d217d5296ac6dd81f10042d120c5c9 \
  --episode 1 \
  --model-revision cdbee75f17c01a7cc42f958dc650907174af0554 \
  --oc-context "$(oc config current-context)" \
  --output /tmp/rr-episode-1-review
```

`--oc-context` reads the current login token into memory. It does not issue a new
token or persist it in output. Alternatively supply `--token-file` containing an
existing valid inference bearer token. The account must be allowed to access
`inferenceservices/local-llm` in `inference-server`.

The default endpoint is the existing HTTPS inference Route. Change `--base-url`
and `--model` when needed. `--model-revision` records the weights revision you
verified is deployed; it does not switch models. Update it when deployed weights
change so old inference checkpoints cannot be reused by mistake. Unspecified
model revisions are allowed for exploration but are not reproducible provenance.

The transcript is read with `git show` from the resolved commit, not from working
tree files. No automatic fetch occurs. Use the actual source revision for another
episode or a corrected transcript. Citation URLs require that revision to have
been pushed to the source repository. Missing episodes fail explicitly.

## Preparation and review

1. Capture the source commit, raw-file SHA-256, episode number, and source URLs.
   Title and publication date remain unknown until explicit metadata is available.
2. Split at paragraph boundaries, subdividing long paragraphs into passages of at
   most 1,800 characters. Every passage keeps exact character offsets, line numbers,
   source text, stable IDs, and previous/next links. Speaker labels are heuristic
   hints carried from explicit labels and may need human correction.
3. Group passages into focus sections of at most 6,000 characters, adding one
   neighboring passage on each side. These are bounded processing windows, not
   semantic topic boundaries. Every passage belongs to exactly one focus section.
4. Ask for zero to three teaching questions per section, each with a concept,
   answer-outline claims, evidence IDs, additional context IDs, qualifications,
   and prerequisites. Model-generated quotations are not required: the report
   displays original passages directly from the source snapshot.
5. Reject invalid schemas, invented passage IDs, and questions unsupported by any
   focus passage. Skip exact normalized duplicate questions. Semantic duplicates
   still need human review; the prototype does not claim to merge them.
6. Review each candidate in a separate request using its cited passages and their
   neighbors. The same model checks support, sufficient context, and teachability.
   Passing this check marks a candidate `needs_human_review`, never approved. The
   reviewer also assigns a confidence rating and explains the weakest evidence.

Candidate headings include review status and confidence, with unvalidated ratings
marked explicitly. The question appears first beneath the heading, followed by
confidence details or rejection reasons, then the answer outline and source context.
Candidates needing human review display **Model confidence in source faithfulness**:

| Rating | Meaning |
|--------|---------|
| High | Every substantive statement is explicit in the cited source, with sufficient context and correct attribution |
| Medium | The central explanation is supported, but wording, attribution, or context requires interpretation |
| Low | Weak, missing, or conflicting evidence, or a substantial inference in the premise, answer, or qualifications |

These are uncalibrated model assessments, not probabilities of correctness. Rate
the weakest substantive statement, not the average. A failed review must have low
confidence; confidence never overrides the support checks or human-review gate.
The structured report stores `review.confidence` and `review.confidence_reason`.
Old reports without a rating display `Not assessed` when rendered and need a new
model review to obtain one. Existing output manifests remain protected; use a new
output directory after this prompt/schema change.

Rejected candidates show **Why rejected** and any failed reviewer checks. If the
review itself fails validation (for example, it reports unsupported claims with
high confidence), the report preserves its explanation and labels its confidence
as unvalidated. Well-formed questions retain their readable outlines and source
context; malformed candidates show the original JSON. `rejection_reason` is also
stored in the structured report. These diagnostics do not change acceptance rules.

Each inference request is checked using the deployed server's `/tokenize`
endpoint. Input, the 2,400-token output allowance, and a 256-token reserve must fit
the configured 32,768-token context budget. Requests run sequentially. Oversized
review contexts fail explicitly rather than silently dropping source passages.
Requests use [vLLM schema-constrained output](https://docs.vllm.ai/en/latest/features/structured_outputs/)
to enforce field types and restrict evidence IDs to supplied passages. Local
validation still checks the response, and schema compliance does not establish
factual support.

The review uses the same model as extraction, so its mistakes may be correlated.
Exact source references establish provenance, not proof that an interpretation is
correct. Wider discussion may be needed beyond the neighboring passages. Evaluate
speaker attribution, historical context, missing qualifications, and distinctness
before calling any question ready for ingestion.

## Output and retries

| Artifact | Contents |
|----------|----------|
| `source.md` | Exact committed episode snapshot |
| `manifest.json` | Source and pipeline fingerprints, prompt hashes, model identity and request settings |
| `report.json` | All passages and sections, candidates, evidence references, reviews, and failures |
| `report.md` | Human-readable questions, answer outlines, review judgments, and original supporting context |
| `responses/` | Raw extraction/review completion responses, including malformed or truncated output |

Reuse the exact command and output directory to resume. Completed inference calls
are reused from checkpoints; transport failures can be retried. Invalid model
responses remain cached for diagnosis. Use a new output directory for a fresh
generation, prompt change, model revision, code change, or source revision. A
manifest mismatch fails rather than combining incompatible results. Run only one
process per output directory. The output directory must be dedicated to this CLI.

`--limit-sections 1` provides a smaller live smoke test. Limited runs and failed
sections produce status `partial` and exit code 1; an unrestricted rerun resumes
and fills the remaining sections. A completed report means all extraction
sections were processed, not that every candidate passed. Candidate rejection
details must still be inspected. Empty questions arrays are permitted for sections
without useful teaching material. `--prepare-only` creates a `prepared` report and
does not overwrite an existing enriched report.

Progress goes to stderr with timings and input-token counts. Authentication
headers and HTTP error bodies are not logged. Reports contain public source text
and generated output; keep them outside Git while iterating.

## Validation and next step

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s kubernetes/ocp-mgmt/applications/rr-lessons/prototype -p 'test_*.py' -v
git diff --check

```

Tests cover immutable Git reads, source offsets and coverage, long paragraphs,
speaker hints, context expansion, evidence-ID validation, model-review rejection,
context limits, checkpoint reuse, malformed completions, partial runs, and manifest
invalidation. They use temporary repositories and mocked inference, with no cluster
or Discord access. Confidence tests cover invalid or absent ratings, failed-check
consistency, legacy reports, and preservation of human review at every rating.

Initial validation on 2026-10-11 passed 12 tests and parsed all 424 archived
episodes into 80,629 exact source passages and 4,766 sections, preserving paragraph
boundaries and every non-whitespace source character. Live episode 1 preparation
also exposed false positives in the model reviewer: it accepted an altered
business-share denominator and an overstated restriction on non-resident clients.
Schema-constrained output addresses formatting errors, but these factual failures
remain evidence against automatically approving the generated material.

Before expanding the workflow, review several complete episodes with varied
formats and record which candidates are supported, useful, redundant, or missing
context. Next work is better segmentation and question selection where evidence
shows a need, followed by embeddings and an authenticated, versioned ingestion
API. Automatic discovery of source commits and Kubernetes scheduling come after
the episode preparation output is validated. Daily delivery remains independent.
