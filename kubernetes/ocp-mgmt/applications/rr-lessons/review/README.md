# Lesson desk deployment

The `rr-lessons-review` Deployment serves the review UI and a read-only inbox API
in the existing `rr-lessons` namespace and Argo CD Application. The initial inbox
is empty. It never imports the prototype's episode 428 fixture or browser progress.

After the approved changes have been pushed and Argo CD has reconciled, open
[Lesson desk](https://review-rr-lessons.apps.ocp-mgmt.rh-lab.morey.tech).

| Component | Configuration |
|-----------|---------------|
| Runtime | Digest-pinned `python:3.14.8-slim-trixie`, matching the deployed LanceDB runtime |
| HTTP server | Uvicorn, one worker; minimal hash-pinned dependencies installed into an `emptyDir` by the init container |
| Code and UI | Versioned ConfigMaps; changing assets changes their hashes and rolls the Deployment |
| Database | SQLite at `/data/reviews.sqlite3`, on a dedicated 1 GiB `rr-lessons-review` PVC |
| Storage | `lvms-vg-nvme`, ReadWriteOnce; eligible nodes `ms-02` and `ms-04` |
| Updates | One replica, `Recreate`; short downtime during updates |
| Access | HTTPS edge Route with HTTP redirect; router-only ingress; no application login in this read-only foundation |
| Pod restrictions | `restricted-v2`, arbitrary non-root UID, read-only root filesystem, no service-account token, dropped capabilities |

This follows the neighboring LanceDB workload's container pattern: the runtime
image is already published, while application code is delivered through GitOps
ConfigMaps. It does not require a new custom-image build or a registry push.
Startup needs package-index connectivity to install the three pinned dependencies.

SQLite uses its rollback journal on local block-backed storage. The PVC is not
shared with other workloads. This is a single-instance service, not a highly
available database. PVC deletion requires Argo CD confirmation and application
deletion retains it. Retention is not a backup. See the upstream guidance on
[appropriate SQLite uses](https://www.sqlite.org/whentouse.html).

## Current boundary

Startup creates schema version 1 with empty `episodes`, `sections`, `questions`,
and `reviews` tables and foreign-key relationships. Source/content/review JSON
columns leave room for the prototype's evidence-linked records. Existing data is
preserved on restart. Unsupported schema versions fail startup rather than being
replaced or reset. Do not insert data manually into the deployed database yet;
the ingestion and review contracts will be implemented in the next phase.

| Endpoint | Behavior |
|----------|----------|
| `GET /` | UI assets, shared with the local prototype |
| `GET /runtime.json` | Selects server mode, never demo mode |
| `GET /api/inbox` | Database-backed episode, section, question, and review counts; `reviewEnabled: false` |
| `GET /healthz` | Process liveness |
| `GET /readyz` | Database schema/table accessibility |

All write methods return 405. The sample fixture, source code, and database file
are not HTTP assets. A database failure returns 503 and an inbox error, not zero
counts. The readiness probe removes an unhealthy instance from service.

The deployed UI has no demo review/import controls and does not use browser storage
as its data source. The existing local prototype still loads `runtime.json` in
demo mode and supports the three-example evidence-first workflow and exports.
If database records exist, the deployed UI reports counts and that review intake
is not yet connected; it does not pretend those records can already be graded.

Future work is the episode intake worker, transcript sectioning and question
generation, the read/write review API, and reviewer authentication/authorization.
Those services should use the API rather than mount SQLite from another pod.
The existing Discord CronJob and LanceDB workload remain unchanged.

## Local checks

Run from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s kubernetes/ocp-mgmt/applications/rr-lessons/review -v
node kubernetes/ocp-mgmt/applications/rr-lessons/prototype/review-ui/test-state.mjs
kustomize build kubernetes/ocp-mgmt/applications/rr-lessons > /tmp/rr-lessons.yaml
git diff --check
```

Run the actual HTTP service against a disposable local database:

```bash
python3 -m venv /tmp/rr-review-service-venv
/tmp/rr-review-service-venv/bin/pip install --require-hashes \
  -r kubernetes/ocp-mgmt/applications/rr-lessons/review/requirements.txt
REVIEW_DB_PATH=/tmp/rr-review-local/reviews.sqlite3 \
REVIEW_STATIC_DIR="$PWD/kubernetes/ocp-mgmt/applications/rr-lessons/prototype/review-ui" \
PYTHONDONTWRITEBYTECODE=1 \
/tmp/rr-review-service-venv/bin/python -m uvicorn server:app \
  --app-dir kubernetes/ocp-mgmt/applications/rr-lessons/review \
  --host 127.0.0.1 --port 8766 --workers 1
```

Open [the local empty inbox](http://127.0.0.1:8766), forwarding port 8766 in
DevSpaces if necessary. An existing database at that path is intentionally reused.

## GitOps deployment and verification

Review the manifests and application changes before committing. The human pushes
approved commits; Argo CD reconciles this directory through the parent application.
Do not apply local files or create test Jobs to bypass that sequence.

After reconciliation, use the authenticated ocp-mgmt context:

```bash
oc -n rr-lessons get deployment/rr-lessons-review pvc/rr-lessons-review route/rr-lessons-review
oc -n rr-lessons rollout status deployment/rr-lessons-review --timeout=180s
oc -n rr-lessons logs deployment/rr-lessons-review -c install-dependencies
oc -n rr-lessons logs deployment/rr-lessons-review -c review
curl --fail --silent --show-error https://review-rr-lessons.apps.ocp-mgmt.rh-lab.morey.tech/readyz
curl --fail --silent --show-error https://review-rr-lessons.apps.ocp-mgmt.rh-lab.morey.tech/api/inbox
```

Expect readiness, four zero counts on a fresh PVC, and `reviewEnabled: false`.
Confirm the browser shows the empty inbox and makes no request for `sample.json`.
PVC binding, SCC admission, init-container installation, and Route reachability
must be checked after GitOps deployment; a manifest dry run cannot prove them.
