# KServe inference on ocp-mgmt

OpenShift AI manages `local-llm` through KServe's Standard deployment mode (formerly RawDeployment). A NVIDIA vLLM ServingRuntime runs one replica on `tr-gpu`'s 24 GiB RTX 3090. Qwen3-4B-Instruct-2507 replaces the initial Qwen3-0.6B validation model; context stays at 4,096 tokens until the new model's GPU memory headroom is measured.

| Setting | Value |
|---------|-------|
| Namespace / Argo CD Application | `inference-server` |
| InferenceService / API model name | `local-llm` |
| Model | `Qwen/Qwen3-4B-Instruct-2507`, revision `cdbee75f17c01a7cc42f958dc650907174af0554` |
| Model downloader | `hf-cli` build `sha-9e38f79`, `huggingface_hub` 1.33.0, pinned by digest |
| Runtime | OpenShift AI 3.5.1 NVIDIA vLLM image, pinned by digest |
| Hardware | `tr-gpu-3090` profile, one `nvidia.com/gpu` |
| CPU / system RAM | Requests 2 CPU / 8 GiB RAM; limits 2 CPU / 16 GiB RAM |
| Context / concurrency | 4,096 tokens / 2 sequences |
| Scaling | Fixed one replica; KServe autoscaler class `none` |
| GPU memory target | 80% |
| Storage | 50 GiB expandable `models` PVC on `lvms-vg-ai` |
| Updates | `Recreate`: release the GPU before replacing the pod; downtime expected |
| Authentication | KServe's token-authenticating proxy and resource-scoped RBAC |

## Rollout and verification

Prerequisites: `lvms-vg-ai` ready on `tr-gpu`, NVIDIA validation completed, OpenShift AI ready, and hardware profile `tr-gpu-3090` installed. The application ApplicationSet explicitly includes this workload. Git owns the model configuration; edits to managed resources through the dashboard are reconciled back to Git.

The PVC and download Job share sync wave 0 so `WaitForFirstConsumer` can bind the local volume. The stable-name `download-model` Job uses [Argo CD force replacement](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/#force-sync) (`Force=true,Replace=true`) to delete and recreate the Job when syncing it, allowing image, resource, and script changes without manual renaming. This annotation applies only to the Job, not the PVC or inference workload. The Job downloads the pinned revision into its own directory and records completion. Wave 1 starts KServe only after the Job succeeds. Subsequent runs skip downloading when the revision's completion marker exists. Although the model is public, downloads use a Bitwarden-backed HF token for authenticated Hub rate limits.

The wave -1 `hf-token` ExternalSecret reads the password field of Bitwarden Login item `9ca241df-26a6-4ef1-8026-b4d9016ebc27` through `bitwarden-login`. ESO refreshes the `hf-token` Secret hourly. Only the download container receives its `HF_TOKEN` key through a required `secretKeyRef`; it cannot start without that key. No token value is stored in Git or passed to the offline serving runtime or AnythingLLM. The cluster's Bitwarden account must have access to the item.

For rotation, update the item's password, wait for the Bitwarden backend and ESO to synchronize, then run a full Argo CD application sync to recreate the Job with the refreshed environment. Updating a Secret does not change an already-running container's environment. A cached model skips Hub access, so a successful cached run alone does not validate the token. Authentication does not replace the downloader's memory-pressure mitigations.

The downloader requests 1 GiB of system RAM and has a 4 GiB limit. The initial 2 GiB configuration was OOM-killed during the 4B model download. It now downloads one file at a time (`max_workers=1`) with [Xet disabled](https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables#hfhubdisablexet) to reduce transfer concurrency. This changes neither GPU allocation nor serving context. The model directory and download metadata are preserved so the replacement Job can reuse completed files.

The Job remains a normal tracked resource, not a hook, so changes to its spec participate in drift detection. A full application sync reruns it even when its spec has not changed, replacing its previous pod and logs; collect failure logs before another sync. Use a full application sync for model changes so the download and inference waves run together. Do not move the Job to `PreSync` or put the PVC in an earlier wave: a new `WaitForFirstConsumer` claim needs the download pod to bind. On migration to the stable name, Argo CD prunes the previously tracked revision-named Job.

```bash
kustomize build kubernetes/ocp-mgmt/applications/inference-server
oc get application inference-server -n openshift-gitops
oc get externalsecret hf-token -n inference-server
oc get pvc,job,pods -n inference-server
oc logs job/download-model -n inference-server
oc get inferenceservice local-llm -n inference-server
oc get deployment local-llm-predictor -n inference-server -o jsonpath='{.spec.strategy}{"\n"}'
python kubernetes/ocp-mgmt/applications/inference-server/scripts/smoke-test.py
```

The smoke test obtains a short-lived token without displaying it and verifies TLS, rejection of unauthenticated access, model discovery, chat completion, and streaming. It requires a logged-in `oc` session authorized to request a token for `inference-client`.

This single-GPU workload disables KServe's CPU-based HPA with `serving.kserve.io/autoscalerClass: none` and retains `minReplicas: 1` / `maxReplicas: 1`. KServe sets the Deployment replica count from `minReplicas` and removes its previously managed HPA during reconciliation. CPU metric warnings while pods are unready can occur during model startup; removing the unnecessary HPA does not fix an unready predictor or disable readiness probes and Prometheus scraping. After GitOps rollout, confirm the Deployment remains ready at one replica and the HPA is absent:

```bash
oc get deployment local-llm-predictor -n inference-server
oc get hpa local-llm-predictor -n inference-server --ignore-not-found
```

After the reviewed model change is committed, pushed, and reconciled by Argo CD, verify the new predictor's `storageUri` and successful startup, then run both client smoke tests. Inspect the new pod's startup memory profile before proposing any context increase:

```bash
oc get inferenceservice local-llm -n inference-server -o jsonpath='{.spec.predictor.model.storageUri}{"\n"}'
oc logs deployment/local-llm-predictor -n inference-server -c kserve-container | rg 'Model loading took|Available KV cache memory|GPU KV cache size|Maximum concurrency'
python kubernetes/ocp-mgmt/applications/anythingllm/scripts/smoke-test.py
```

Keep FP16, 80% GPU memory allocation, two concurrent sequences, and AnythingLLM's 4,096-token budget / 1,024-token response limit unchanged for this baseline. vLLM preallocates its KV cache, so GPU free-memory readings alone do not show the available context capacity. The cache token count is shared across concurrent requests, not a per-request context guarantee. The three weight shards total approximately 7.5 GiB; the old model directory remains on the 50 GiB PVC for rollback.

## Clients

Get the KServe-managed HTTPS endpoint and request a token:

```bash
oc get inferenceservice local-llm -n inference-server -o jsonpath='{.status.url}{"/v1\n"}'
oc create token inference-client -n inference-server --duration=1h
```

Use the endpoint as an OpenAI-compatible base URL, the token as the API key, and `local-llm` as the model name. Tokens expire and must be renewed; no static credential is stored in Git. The Role permits only `get` on this InferenceService, which KServe's proxy checks before accepting requests. Qwen3-4B-Instruct-2507 is non-thinking and needs no thinking-mode override.

[AnythingLLM](../anythingllm/README.md) uses the same endpoint from its own namespace. The separate `anythingllm-local-llm` RoleBinding grants its ServiceAccount the same model-scoped permission. Its controller-generated persistent token is kept in a Kubernetes Secret, never Git; this differs from the short-lived tokens above.

The `networking.kserve.io/visibility: exposed` label enables the OpenShift AI-managed Route. KServe and the platform model controller own the Service and Route. The route allows ten-minute requests for generation and streaming. NetworkPolicy permits inference traffic through port 8443 and limits direct runtime port 8080 to monitoring namespaces.

## Model changes and recovery

Choose a model revision and compatible runtime, then update the download Job's repository, revision, expected artifacts, and target directory together with the InferenceService `storageUri`. Keep the Job name `download-model`; Argo CD recreates it with the new pod template. Keep `local-llm` as the API name so clients do not need reconfiguration. Review GPU memory, context length, and concurrency for each model.

The PVC is guarded with `Prune=confirm,Delete=false`; retiring the application does not automatically delete model data. Storage is local to `tr-gpu`, with no failover or replication. Model weights can be downloaded again; back up irreplaceable datasets separately. A failed download without a completion marker can be retried with a full Argo CD sync after addressing its cause. A marker bypasses artifact checks, so recovery of damaged files in a previously completed directory requires a reviewed Git change selecting a fresh target directory in both the Job and InferenceService. Preserve any useful data before deleting a PVC.

The 3090 is a homelab configuration outside Red Hat's listed enterprise accelerator models. The smoke test establishes functionality for the pinned runtime and model; larger models require separate validation.
