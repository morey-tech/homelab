# LanceDB deployment foundation

This component is included by the parent `rr-lessons` Kustomization and shares its namespace and Argo CD Application. It has its own Deployment, ServiceAccount, ClusterIP Service, NetworkPolicy, and PVC.

[LanceDB OSS](https://docs.lancedb.com/) is an embedded database library. `server.py` is a small application wrapper around it, not an upstream LanceDB server or an implementation of the Enterprise remote API. This first deployment provides health and table inspection. Ingestion, embeddings, collections, search endpoints, and integration with the daily lesson job belong to the subsequent RAG prototype.

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
| Access | Cluster-internal HTTP, ingress restricted to `app=rr-lessons` pods in the same namespace |

The container runs under OpenShift's assigned non-root UID with a read-only root filesystem, no Kubernetes token, and no inference or Discord credentials. The API currently exposes read-only metadata without application authentication; NetworkPolicy controls pod access. There is no external Route. Define authenticated writer access before adding ingestion endpoints or allowing additional clients.

## Startup and storage

The init container installs the hash-locked, wheel-only dependencies into an `emptyDir`, which the service mounts read-only. Each new pod needs access to PyPI; application startup does not install or resolve packages. This avoids referencing an unpublished custom image for the initial deployment. A prebuilt image can replace the installation step when the prototype's dependencies stabilize.

Startup checks write access with a temporary file and `fsync`, connects to LanceDB, and lists tables. No application table is created. `/healthz` checks the HTTP process; `/readyz` checks database access. Storage errors fail readiness without causing the liveness check itself to restart the process. Dependency failures remain visible in the init-container logs.

The original `rr-lessons` PVC still holds transcript cache and delivery history. Only the database pod mounts the new claim; future clients must use its API instead of mounting the database files into other workloads. Keep one replica. Local NVMe is not replicated, so a node failure takes the database offline. `Prune=confirm,Delete=false` protects the claim from automatic Argo CD removal; manually deleting it can still delete the underlying volume. Snapshot/export and recovery procedures will be needed before the prototype stores irreplaceable data.

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

The tests launch the real HTTP server against temporary storage, exercise health and table listing, reject write requests, and reopen persisted vectors after process restarts. They do not contact a cluster or send Discord messages.

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
