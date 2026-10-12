# Lesson desk: episode intake and review

Open [Lesson desk](https://review-rr-lessons.apps.ocp-mgmt.rh-lab.morey.tech), enter an
**episode number**, and click **Ingest episode**. The background worker prepares the
whole episode; the page shows its phase, section progress, and any failure.
You can close the page and return later. **Retry episode** starts a fresh attempt.

When preparation completes, open a question from the inbox:

1. Read the original supporting passages and neighboring context.
2. Acknowledge reading to reveal the question, answer outline, qualifications, and
   model review. Model confidence and rejection reasons stay hidden until this point.
3. Enter your reviewer name, grade source support and teaching value, and confirm
   scope and agreement with the evidence. Approve, request changes, or exclude.

Drafts and decisions are saved to SQLite, shared across browsers, and retained
across pod restarts. A conflicting edit from another tab stops saving and asks you
to reload the inbox. Reopening a decision requires the evidence-first checks again.
The reviewer name is attribution, not an authenticated identity.

## Background workflow

```mermaid
flowchart LR
    Button[Episode number + Ingest] --> Queue[SQLite queue]
    Queue --> Git[Incremental Git fetch]
    Git --> Source[Validate individual transcript]
    Source --> Sections[Passages + neighboring context]
    Sections --> GPU[3090: extract and review questions]
    GPU --> Import[Atomic SQLite intake]
    Import --> Inbox[Human review inbox]
```

- `pipeline.py` fetches the public `morey-tech/rr-scraper` repository into a shallow
  bare Git cache on the review PVC using Dulwich. No GitHub credentials, checkout,
  shell execution, or repository hooks are involved. It reads
  `transcripts/individual/episode_N.md` at the fetched HEAD commit. Missing episodes
  (including source gaps) fail explicitly; there is no fallback to another episode.
- The same `prototype/prepare.py`, `extract.txt`, and `review.txt` used by the CLI
  parse and prepare the transcript. UTF-8, the episode heading, and the 2 MiB source
  limit are checked. Passages retain exact text, character/line offsets, speaker
  hints, neighboring context, and immutable GitHub citations. Speaker hints are
  heuristic, not verified identities.
- The GPU service `local-llm` generates at most three questions per section and
  reviews the claims against referenced passages. Requests are token-counted against
  the existing 32,768-token context budget; extraction and review use temperature 0.
  The whole episode is processed, with no section limit. Question validation failures
  and model rejection reasons are retained in the preparation report.
- Structurally valid candidates, including model-rejected candidates, enter the
  human inbox. Exact duplicate question text and malformed candidates are skipped;
  their raw output and explanations remain in the report. A failed section extraction
  prevents importing that episode, rather than silently dropping the section.
- One transaction inserts the source manifest, sections and original passages,
  questions and evidence references, then marks the job complete.
  The internal `Database.import_intake` operation is the import boundary: the worker
  runs in the same process, so it does not make an HTTP request back to itself.

Generation model revision, source hash/commit, prompt hashes,
and pipeline code hash identify an intake. Repeating the same intake reuses it
without overwriting human reviews. A changed source commit or pipeline creates a
separate intake. Active submissions for the same episode share one job. The queue
allows ten outstanding episodes and processes one at a time.

The single worker uses a process lock. On restart, queued jobs remain queued and a
running job becomes **failed / interrupted**, with a retry button. Retries fetch
current HEAD and rerun preparation in a fresh directory; they do not reuse a bad
model completion from a previous attempt. Successful repeated intakes are reused.

## Storage and deployment

| Component | Configuration |
|-----------|---------------|
| Runtime | Digest-pinned `python:3.14.8-slim-trixie`; hash-pinned Uvicorn, Dulwich, and dependencies |
| Code | Versioned ConfigMaps for the server, shared UI assets, preparation script, and prompts |
| Worker | One background thread in the review service; one ASGI worker and one replica |
| SQLite | `/data/reviews.sqlite3`, schema version 2; version 1 migrates in place |
| Git cache | `/data/ingestion/rr-scraper.git` |
| Run artifacts | `/data/ingestion/runs/JOB_ID/`: source, manifest, report JSON/Markdown, raw completions |
| PVC | Existing 1 GiB `rr-lessons-review`, `lvms-vg-nvme`, RWO; nodes `ms-02` or `ms-04` |
| Resources | Review container: 256 MiB memory request, 1 GiB limit; models run in their existing services |
| Updates | `Recreate`; brief downtime during updates; PVC retained |
| Model access | Projected one-hour service-account token, reread before each request; GPU model-scoped RoleBinding in `inference-server` |
| Restrictions | `restricted-v2`, non-root, read-only root filesystem, dropped capabilities |

The Route retains the existing **trusted-homelab access model with no login**.
Anyone who can reach it can queue episodes and edit reviews. Router-only pod ingress
is not user authentication. Writes require same-origin JSON requests to prevent
cross-site browser submissions, but this does not authenticate callers. Authentication
and per-reviewer authorization remain future work before offering broader access.

Schema, source, and review validation are enforced server-side. Request bodies are
limited to 32 KiB; episode numbers to 1–99,999. The database is never served as an
asset, and no demo data is seeded. Database failure produces an error, not an empty
inbox. Keep the single-worker/single-replica configuration while SQLite and the queue
share a PVC. Back up the database and monitor PVC space; automatic artifact/cache
retention is not implemented for this MVP. Model credentials are not written to
reports, the database, or browser responses.

## API

| Endpoint | Behavior |
|----------|----------|
| `GET /runtime.json` | Server mode; no demo fixture |
| `POST /api/ingestions` | JSON `{"episode":428}`; returns a durable job with HTTP 202 |
| `GET /api/ingestions` | Latest 50 jobs, phases/progress/errors; UI displays latest ten |
| `GET /api/inbox` | Prepared questions and evidence, counts, saved reviews, and revisions |
| `PUT /api/reviews/QUESTION_ID` | JSON `{"revision":0,"review":{...}}`; validated draft/decision, HTTP 409 on stale revision |
| `GET /healthz` | Process liveness |
| `GET /readyz` | Database schema/table accessibility |

This phase ends at human review. Intake does not call an embedding service, create
vectors, or depend on the CPU models being available. Approval saves the reviewed
wording and decision; it does not trigger embedding or publication yet.

Embedding belongs in a later **post-approval publishing step**, using the approved
question text, including human edits. Qwen3 Embedding 4B remains the selected model
for that future step. The publisher must associate each vector with the approved
review revision and invalidate or replace it if the material is reopened or edited.
That publisher is not implemented in this MVP. The existing daily lesson CronJob,
LanceDB service, CPU model deployments, and local three-question demo are unchanged.

## Local validation

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s kubernetes/ocp-mgmt/applications/rr-lessons/review -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s kubernetes/ocp-mgmt/applications/rr-lessons/prototype -p test_prepare.py -v
node kubernetes/ocp-mgmt/applications/rr-lessons/prototype/review-ui/test-state.mjs
kustomize build kubernetes/ocp-mgmt/applications/rr-lessons > /tmp/rr-lessons.yaml
kustomize build kubernetes/ocp-mgmt/applications/inference-server > /tmp/inference-server.yaml
git diff --check
```

Tests use fake model responses and temporary SQLite databases. They exercise the
real preparation code, atomic import, failures, queue recovery/deduplication,
version-1 migration, GPU-only intake, rotating tokens, review checks, and conflicts.
They do not prove the live models' output quality or cluster authentication.

## GitOps verification

Review and commit the changes, then push manually and let Argo CD reconcile both
`rr-lessons` and `inference-server` (the latter grants the review ServiceAccount
access to the GPU service). Do not apply local manifests or run
uncommitted test Jobs on the cluster.

After reconciliation, using the authenticated ocp-mgmt context:

```bash
oc -n rr-lessons rollout status deployment/rr-lessons-review --timeout=180s
oc -n rr-lessons logs deployment/rr-lessons-review -c install-dependencies
oc -n rr-lessons logs deployment/rr-lessons-review -c review
curl --fail --silent --show-error https://review-rr-lessons.apps.ocp-mgmt.rh-lab.morey.tech/readyz
```

Expect schema version 2. In Lesson desk, ingest **428** and watch the phases through
preparation, import, and ready. Verify the original source links, qualifications,
model review, and persisted decision after reloading. Submit 428 again to verify
reuse without overwriting the decision. Test a missing episode for an explicit
failure with a retry action. Inspect model logs for authentication/tokenization or
context failures. Initial package installation, projected-token permissions,
GPU inference compatibility, and actual model quality need these post-deployment
checks; local mocks and manifest dry runs cannot establish them.
