# Episode ingestion prototype

`prepare.py` prepares one committed individual transcript for review using the
existing `local-llm` service on the RTX 3090. `retrieve.py` selects high-confidence
candidates for an explicitly permitted local LanceDB experiment, embeds their
questions, and retrieves their original evidence and context. Neither CLI sends
Discord messages, runs the scraper, or alters the daily lesson workload. They are
not included in Kustomize and do not write to the deployed LanceDB service.

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
Logs and report headings label passing high-confidence candidates **Ready for human
review**; passing medium/low-confidence candidates are **Needs human review**.
Completed episode reports display **Preparation complete**. These display labels
retain the existing `needs_human_review` JSON status and `human_review: pending`
for compatibility with report selection; they do not grant production approval.
Rejection logs name the failed checks and include the reviewer's explanation.
When the model reports medium/high confidence alongside failed checks, the message
explicitly identifies that inconsistent rating instead of describing it as low confidence.

Candidates needing human review display **Model confidence in source faithfulness**:

| Rating | Meaning |
|--------|---------|
| High | Every substantive statement is explicit in the cited source, with sufficient context and correct attribution |
| Medium | The central explanation is supported, but wording, attribution, or context requires interpretation |
| Low | Weak, missing, or conflicting evidence, or a substantial inference in the premise, answer, or qualifications |

These are uncalibrated model assessments, not probabilities of correctness. Rate
the weakest substantive statement, not the average. A failed review must have low
confidence; confidence never overrides the support checks or production
human-review gate. The local retrieval experiment below permits high-confidence
candidates still awaiting human review without changing their original status.
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

## Local indexing and retrieval

For this prototype, use candidates with `needs_human_review`, no validation error,
all three review checks passing, and validated `high` confidence. Rejected and
medium/low candidates are excluded even if a rejected model response claims high
confidence. Human rejection is also respected. This is an experiment selection
policy, not approval to publish lessons; stored records retain the pending review
and `production_approved: false`.

Create the tested Python 3.12 CPU environment (separate from the deployment's
Python runtime). Install PyTorch from its CPU index before the remaining pinned
dependencies:

```bash
python3.12 -m venv /tmp/rr-rag-venv
/tmp/rr-rag-venv/bin/python -m pip install 'torch==2.8.0+cpu' \
  --index-url https://download.pytorch.org/whl/cpu
/tmp/rr-rag-venv/bin/python -m pip install \
  -r kubernetes/ocp-mgmt/applications/rr-lessons/prototype/retrieval-requirements.txt

HF_HOME=/tmp/rr-hf-cache HF_HUB_DISABLE_IMPLICIT_TOKEN=1 OMP_NUM_THREADS=2 \
  /tmp/rr-rag-venv/bin/python \
  kubernetes/ocp-mgmt/applications/rr-lessons/prototype/retrieve.py ingest \
  --report /tmp/rr-episode-428-confidence \
  --report /tmp/rr-episode-429-confidence \
  --allow-prototype-high-confidence \
  --output /tmp/rr-rag-high-confidence

HF_HOME=/tmp/rr-hf-cache HF_HUB_OFFLINE=1 OMP_NUM_THREADS=2 \
  /tmp/rr-rag-venv/bin/python \
  kubernetes/ocp-mgmt/applications/rr-lessons/prototype/retrieve.py search \
  --index /tmp/rr-rag-high-confidence \
  --query 'Which jobs might give someone a path toward owning a business?' \
  --limit 3 --output /tmp/rr-rag-career-search
```

The first ingestion downloads [BGE small English v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5)
at revision `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`. Subsequent queries can run
offline. The model runs locally on CPU and produces normalized 384-dimensional
vectors. Its documented retrieval instruction is prepended to queries; documents
contain the concept and question. Inputs exceeding the model's token limit fail
instead of being silently truncated. The model cache lives in
`/tmp/rr-embedding-models`. No transcript text is sent to an external embedding API.

This first retrieval design indexes **questions**, then returns each question's
answer outline, qualifications, prerequisites, exact supporting passages, and
neighboring context. Generated outlines remain labeled proposals. The source
snapshot hash, passage offsets/IDs/citation lines, evidence references, and context
coverage are validated before indexing. Source commits, report and generation
manifest hashes, and embedding configuration are retained for provenance.

| Index artifact | Contents |
|---|---|
| `selection.json` | Selected records with source context, exclusion reasons, policy, and report provenance |
| `manifest.json` | Selection and implementation fingerprints, pinned embedding identity, runtime versions, and vector settings |
| `db/` | Local LanceDB `teaching_questions` table with vectors and complete context payloads |
| Query output `retrieval.json` / `retrieval.md` | Ranked questions, distances, source citations, qualifications, and original context |

An identical ingestion reuses the index without adding rows. Changed reports,
implementation, or embedding settings require a fresh output directory; this snapshot approach avoids
mixing revisions or leaving superseded questions searchable. Failed builds are
staged separately and do not expose a partial index. Use one writer per directory.
Partial preparation reports are allowed for this experiment and retain their
processed-section counts; they are not complete episode ingestions.

Search uses exact cosine nearest neighbors through the [LanceDB Python API](https://lancedb.github.io/lancedb/python/python/).
At this corpus size an approximate vector index is unnecessary. Search always
returns the nearest candidates, including for unrelated queries; distances are
not confidence scores. Relevance/abstention checks and token-budgeted context
assembly are required before adding answer or lesson generation. No answer is
generated by this command.

## Validation and next step

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s kubernetes/ocp-mgmt/applications/rr-lessons/prototype -p 'test_*.py' -v
git diff --check

# Include real database persistence/retrieval tests (no model download needed):
PYTHONDONTWRITEBYTECODE=1 /tmp/rr-rag-venv/bin/python -m unittest discover \
  -s kubernetes/ocp-mgmt/applications/rr-lessons/prototype -p 'test_*.py' -v
```

Tests cover immutable Git reads, source offsets and coverage, long paragraphs,
speaker hints, context expansion, evidence-ID validation, model-review rejection,
context limits, checkpoint reuse, malformed completions, partial runs, and manifest
invalidation. They use temporary repositories and mocked inference, with no cluster
or Discord access. Confidence tests cover invalid or absent ratings, failed-check
consistency, legacy reports, and preservation of human review at every rating.
Retrieval tests cover selection exclusions, source tampering, missing context,
cross-episode IDs, persistence, idempotency, configuration mismatch, and failed
build cleanup. Two real LanceDB tests are skipped when its dependencies are absent.

Local retrieval validation on 2026-10-11 selected four questions from episode 428
and one from 429, using only the first three prepared sections of each. Eight
other candidates were excluded. Five hand-picked paraphrase queries each ranked
the intended question first; this small smoke check is not a retrieval-quality
benchmark. An unrelated gardening query still returned nearest neighbors,
confirming the need for a relevance gate. Repeated ingestion reused the five-row
index. All 22 tests passed with the retrieval dependencies installed.

Initial validation on 2026-10-11 passed 12 tests and parsed all 424 archived
episodes into 80,629 exact source passages and 4,766 sections, preserving paragraph
boundaries and every non-whitespace source character. Live episode 1 preparation
also exposed false positives in the model reviewer: it accepted an altered
business-share denominator and an overstated restriction on non-resident clients.
Schema-constrained output addresses formatting errors, but these factual failures
remain evidence against automatically approving the generated material.

The [embedding comparison plan](evaluation/README.md) defines concrete starter
queries, source-linked review inputs, relevance grading, controlled comparison
settings, and acceptance criteria for the two CPU Qwen3 embedding services. Its
input builder runs without inference. Draft source-linked queries still need a
frozen teaching-question corpus and human relevance judgments before scoring.
The HTTP embedding adapter and scoring runner are the next implementation step.

An authenticated, versioned ingestion/search API, automatic source discovery,
and scheduling follow validated episode ingestion. Daily delivery remains
independent.
