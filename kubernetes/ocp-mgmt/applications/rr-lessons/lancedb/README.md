# LanceDB approved-question index

This component is included by the parent `rr-lessons` Kustomization and shares its namespace and Argo CD Application. It has its own Deployment, ServiceAccount, ClusterIP Service, NetworkPolicy, and PVC.

[LanceDB OSS](https://docs.lancedb.com/) is an embedded database library. `server.py` is a small application wrapper around it, not an upstream LanceDB server or an implementation of the Enterprise remote API. The wrapper provides health/table inspection, revision-aware question publication, and vector search gated by current human approval. Embedding runs in the review publisher; the daily lesson job remains independent.

| Setting | Value |
|---------|-------|
| Deployment / Service / PVC | `rr-lessons-lancedb` |
| Namespace / Argo CD Application | `rr-lessons` |
| Internal endpoint | `http://rr-lessons-lancedb.rr-lessons.svc.cluster.local:8080` |
| Runtime | Python 3.14.8, same digest-pinned image as the lesson job |
| Dependencies | LanceDB 0.40.0, FastAPI 0.143.0, Uvicorn 0.54.0; transitive dependencies pinned with hashes |
| Data | `/data/lancedb` on a separate 5 GiB `lvms-vg-nvme` PVC |
| Placement | `ms-02` or `ms-04`; volume binds to the selected node |
| Availability | One replica, one Uvicorn worker, `Recreate` updates |
| Resources | 100m CPU / 256 MiB requested; 2 CPU / 2 GiB limits; no GPU |
| Access | Cluster-internal HTTP, ingress restricted to `app=rr-lessons-review` pods in the same namespace |

The container runs under OpenShift's assigned non-root UID with a read-only root filesystem, no Kubernetes token, and no inference or Discord credentials. NetworkPolicy restricts API access to the review workload in the same namespace; there is no external Route or application bearer credential. This trusts that workload as the writer. Other consumers need an explicit access/authentication design before being allowed to connect. The database pod can read live eligibility from the review service, without a Kubernetes API token.

## Startup and storage

The init container installs the hash-locked, wheel-only dependencies into an `emptyDir`, which the service mounts read-only. Each new pod needs access to PyPI; application startup does not install or resolve packages. This avoids referencing an unpublished custom image for the initial deployment. A prebuilt image can replace the installation step when the prototype's dependencies stabilize.

Startup checks write access with a temporary file and `fsync`, connects to LanceDB, and lists tables. No application table is created until the first publication or withdrawal. `/healthz` checks the HTTP process; `/readyz` checks database access. Storage errors fail readiness without causing the liveness check itself to restart the process. Dependency failures remain visible in the init-container logs.

The original `rr-lessons` PVC still holds transcript cache and delivery history. Only the database pod mounts the new claim; clients must use its API instead of mounting the database files into other workloads. Keep one replica. Local NVMe is not replicated, so a node failure takes the database offline. `Prune=confirm,Delete=false` protects the claim from automatic Argo CD removal; manually deleting it can still delete the underlying volume. Snapshot/export and recovery procedures will be needed before the prototype stores irreplaceable data.

## Verify after GitOps deployment

After review, approved local commits, and the human push, let Argo CD reconcile the existing application:

```bash
oc get application rr-lessons -n openshift-gitops
oc get pvc rr-lessons-lancedb -n rr-lessons
oc rollout status deployment/rr-lessons-lancedb -n rr-lessons --timeout=5m
oc logs deployment/rr-lessons-lancedb -n rr-lessons -c install-dependencies
oc logs deployment/rr-lessons-lancedb -n rr-lessons -c lancedb
oc port-forward service/rr-lessons-lancedb -n rr-lessons 8080:8080
```

In another terminal:

```bash
curl --fail http://127.0.0.1:8080/healthz
curl --fail http://127.0.0.1:8080/readyz
curl --fail http://127.0.0.1:8080/v1/tables
```

An empty database returns `{"tables":[],"page_token":null}`. Table listing accepts `limit` (1–100) and the opaque `page_token` returned by the preceding page. These endpoints are this wrapper's API; `lancedb.connect()` cannot use this HTTP URL as an OSS database URI.

Port-forwarding checks the application but does not exercise NetworkPolicy. In-cluster access, LVMS binding, SCC admission, and persistence across an actual pod replacement need post-GitOps verification. The lesson job is not yet a database client.

## Local validation

The tests use temporary real LanceDB storage and HTTP servers to exercise health, listing, request validation, idempotent publication, tombstones, persistence, and fail-closed review eligibility. They do not contact a cluster or send Discord messages.

```bash
python3 -m venv /tmp/rr-lancedb-test
/tmp/rr-lancedb-test/bin/python -m pip install --require-hashes --only-binary=:all: -r kubernetes/ocp-mgmt/applications/rr-lessons/lancedb/requirements.txt
PYTHONDONTWRITEBYTECODE=1 /tmp/rr-lancedb-test/bin/python -m unittest discover -s kubernetes/ocp-mgmt/applications/rr-lessons/lancedb -p 'test_*.py' -v
kustomize build kubernetes/ocp-mgmt/applications/rr-lessons
git diff --check
```

Update the lock deliberately from `requirements.in` using `uv` and validate it in the pinned Python runtime:

```bash
uv pip compile kubernetes/ocp-mgmt/applications/rr-lessons/lancedb/requirements.in --python-version 3.14 --generate-hashes --only-binary=:all: --output-file kubernetes/ocp-mgmt/applications/rr-lessons/lancedb/requirements.txt
```

## Approved-question API

| Endpoint | Purpose |
|----------|---------|
| `PUT /v1/questions/QUESTION_ID` | Index an approved revision or persist an inactive withdrawal marker |
| `POST /v1/search` | Cosine search using a query vector, restricted to current approved/indexed revisions |

Both endpoints require JSON, limited to 512 KiB. The write body contains
`revision` (positive integer), `active` (boolean), `record`, `vector`, and `model`.
An active record identifies the same question and review revision, carries the
approved question/outline and original supporting evidence, and records its
embedding input hash. A withdrawal uses `active: false`, `record: null`, and
`vector: null`. Question IDs contain only letters, digits, colon, underscore, and
hyphen. Invalid requests return 400; oversize bodies return 413.

The versioned shared contract pins Qwen3 Embedding 4B, its weights revision,
2,560 dimensions, L2 normalization, and the `approved-question-v1` input format.
Its table is `approved_questions_qwen3_4b_v1`. Model/input-format changes need a new
contract/table and deliberate reindexing; vectors from different spaces cannot be
mixed. Upserts use one row per question. Identical retries are idempotent; older
revisions or different content for the same revision return 409. Withdrawals retain
the newer revision in an inactive row so delayed writes cannot resurrect old data.
The application serializes writes and requires one Uvicorn worker/one replica.

A search body contains `vector`, `model` (the same contract metadata), and `limit`
(1–20). Generate the query vector with the same Qwen weights, using an appropriate
Qwen query instruction. This endpoint accepts vectors, not raw query text; a
human-facing search/lesson-generation client is separate work. Results contain
`record` and cosine `distance` (lower is closer); original text and citations travel
with the approved outline. The endpoint never returns vectors or inactive rows.

Before search, the service reads `/api/retrieval-state` from Lesson desk. Only
question/review revisions that are both currently approved and acknowledged as
indexed are eligible. It filters the database query by those exact revisions and
checks current eligibility again before returning results. Review-service outages
or malformed state return 503, with no fallback to cached approvals. Reopening in
Lesson desk therefore hides a question even while remote withdrawal is retrying.
Results are point-in-time snapshots: consumers must revalidate approval before
later publication/delivery. Directly opening the database bypasses this contract.

The first API supports small prototype corpora with exact vector search and live
eligibility predicates; pagination, ANN indexes, vacuum/retention scheduling, and
consumer authentication are not included. LanceDB preserves version history;
inactive rows and historical files are not a secure-erasure mechanism. Back up
review SQLite and LanceDB consistently. SQLite is the source of review authority;
a future reindex/recovery tool must reconcile its approved revisions rather than
trust stale database rows. No daily Discord workflow is changed by these APIs.
