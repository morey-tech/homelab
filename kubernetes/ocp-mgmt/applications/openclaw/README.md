# OpenClaw

Standalone OpenClaw using the existing Qwen model on the RTX 3090 through MaaS.
Argo CD application: `openclaw`. URL: [OpenClaw](https://openclaw.apps.ocp-mgmt.rh-lab.morey.tech).

## Deployment

Deploy the MaaS prerequisite commit first, then the application commit through GitOps.
The first key is created on the next quarter-hour CronJob schedule. The app may
remain pending until that key exists and ESO has synchronized it.

```bash
oc get application redhat-ods-operator-system openclaw -n openshift-gitops
oc get cronjob,jobs -n openclaw-maas
oc logs -n openclaw-maas -l app=maas-key-rotator --tail=20
oc get secret maas-workspace-key -n openclaw-maas
oc get clustersecretstore openclaw-maas
oc get externalsecret,pods,pvc,route -n openclaw
oc rollout status deployment/openclaw -n openclaw --timeout=300s
```

Open the URL and log in with the OpenShift `admin` account. The proxy supplies the
verified username to OpenClaw; no MaaS key or gateway token needs to be copied into
the browser. `gateway.auth.trustedProxy.allowUsers` in `openclaw.json` is the access
allowlist. Other authenticated users are denied by OpenClaw. Approved browser devices
receive chat/read/write/approval/question scopes, not automatic administrator scope.
This is one personal workspace, not isolated multi-user hosting.

## Architecture

- Pinned upstream OpenClaw 2026.10.5 image; one pod with an OAuth proxy sidecar.
- Gateway listens only on loopback. Only OAuth's HTTPS port is exposed by the Service.
- Reencrypt Route uses the existing apps wildcard certificate and an OpenShift
  service-serving certificate between the router and OAuth proxy.
- OAuth identity headers are trusted only from loopback. The proxy overwrites user
  headers and does not forward users' OAuth access tokens. Do not expose port 18789
  or add unauthenticated proxy paths. Processes within the pod share this trust boundary.
- `restricted-v2` is explicitly required, with an assigned non-root UID, dropped
  capabilities, read-only root filesystems, and no custom SCC.
- Service-account token automount is disabled. Only the OAuth sidecar receives a
  projected token. Its liveness check restarts it when the token changes because
  oauth-proxy loads its client secret at startup; browser connections may reconnect.
- 10Gi `lvms-vg-nvme` PVC, scheduled on `ms-02` or `ms-04`. This is local block storage,
  not NFS, and the claim becomes tied to its selected node. Node loss does not provide
  automatic storage failover. Back up the PVC before upgrades; Git does not contain state.
  Argo requires confirmation to prune it and retains it on application deletion.
- NetworkPolicy limits ingress to OpenShift routers and egress to cluster DNS,
  the ingress VIP/router (MaaS and OAuth), and API destinations needed by OAuth.
  The current VIP is `192.168.6.98`; update `network.yaml` if cluster addressing changes.
  This is IP/port filtering, not per-domain or per-process authorization. It allows
  other services sharing those destinations and is not an OpenShell sandbox.

## Model and credential lifecycle

The sole initial model is `maas/local-llm`, calling
`https://maas.apps.ocp-mgmt.rh-lab.morey.tech/v1` with OpenAI Chat Completions.
Its configured context is 32768 tokens with up to 8192 output tokens and one active
turn. OpenClaw requests no GPU; existing vLLM performs inference.

The `openclaw` MaaS subscription grants only `local-llm`, with a 30000 token/minute
quota. A dedicated service account in `openclaw-maas` issues 90-day keys and renews
when 30 days remain, using the [shared rotation runtime](../../system/redhat-ods-operator/maas/key-rotation/README.md).
ESO copies only `MAAS_API_KEY` into the application namespace. Dev Spaces credentials,
subscription, and quota remain separate. Key issuance and authenticated discovery
are checked every 15 minutes, with a stalled-check Prometheus alert.

`launch.mjs` reads the mounted key into the gateway process environment and checks
for a replacement every 30 seconds. A changed, nonempty key stops the gateway;
Kubernetes restarts it with the current key. Allow time for ESO and kubelet projection.
In-flight turns may be interrupted. Empty/missing projections leave the existing
process running. Keys are not logged. The agent process holds the MaaS key; this
setup does not provide credential-free inference isolation.

## Configuration and tools

`openclaw.json` is mounted read-only and owned by Git. ConfigMap name hashing rolls
out changes. UI/CLI configuration writes are intentionally unsupported; edit Git.
Session and workspace data remain on the PVC. `AGENTS.md` seeds the workspace only
when absent; subsequent workspace edits persist and changing its template does not
overwrite an existing copy.

Initial tools are workspace-scoped `read`, `write`, `edit`, and `session_status`.
Shell execution, browser automation, external integrations, and embedding-based
memory search are not enabled. Add capabilities deliberately with their required
network access. Kagenti, OpenShell, Kata, and model guardrails are not installed by
this application.

## Validation

```bash
kustomize build kubernetes/ocp-mgmt/applications/openclaw >/tmp/openclaw.yaml
python3 -B -m unittest discover -s kubernetes/ocp-mgmt/system/redhat-ods-operator/maas/key-rotation/runtime
node --test kubernetes/ocp-mgmt/applications/openclaw/test-launch.mjs
```

After GitOps deployment, verify:

1. The key Job succeeds, ESO is Ready, PVC is Bound, and the pod uses `restricted-v2`.
2. An unauthenticated browser is redirected to OpenShift OAuth; `admin` can chat and
   another user is denied. Verify WebSocket connections and no direct gateway Service.
3. Ask Qwen to write a unique sentence into `smoke-test.txt`, read it back, then edit
   it. Verify actual tool events and results. Successful model discovery alone does
   not prove vLLM tool-call compatibility.
4. Confirm session/workspace persistence after the next reviewed rollout. During a
   scheduled key rotation, verify gateway restart and a new successful model turn.
5. Verify OAuth login again after its projected token rotates and the sidecar restarts.

## References

- [Red Hat standalone deployment pattern](https://developers.redhat.com/articles/2026/04/14/deploying-agents-red-hat-ai-openclaw)
- [Defense in depth for agents](https://developers.redhat.com/articles/2026/05/14/every-layer-counts-defense-depth-ai-agents-red-hat-ai)
- [Community claw-installer](https://github.com/sallyom/claw-installer) — reference only; GitOps owns deployment here.
- [Upstream Kubernetes manifests](https://docs.openclaw.ai/install/kubernetes)
- [Trusted proxy authentication](https://docs.openclaw.ai/gateway/trusted-proxy-auth)
