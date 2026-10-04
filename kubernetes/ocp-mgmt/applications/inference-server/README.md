# KServe inference on ocp-mgmt

OpenShift AI manages `local-llm` through KServe's Standard deployment mode (formerly RawDeployment). A NVIDIA vLLM ServingRuntime runs one replica on `tr-gpu`'s 24 GiB RTX 3090. The initial Qwen3-0.6B model validates serving; it is not the final model selection.

| Setting | Value |
|---------|-------|
| Namespace / Argo CD Application | `inference-server` |
| InferenceService / API model name | `local-llm` |
| Model | `Qwen/Qwen3-0.6B`, revision `c1899de289a04d12100db370d81485cdf75e47ca` |
| Runtime | OpenShift AI 3.5.1 NVIDIA vLLM image, pinned by digest |
| Hardware | `tr-gpu-3090` profile, one `nvidia.com/gpu` |
| CPU / system RAM | Requests 2 CPU / 8 GiB RAM; limits 2 CPU / 16 GiB RAM |
| Context / concurrency | 4,096 tokens / 2 sequences |
| GPU memory target | 80% |
| Storage | 50 GiB expandable `models` PVC on `lvms-vg-ai` |
| Updates | `Recreate`: release the GPU before replacing the pod; downtime expected |
| Authentication | KServe's token-authenticating proxy and resource-scoped RBAC |

## Rollout and verification

Prerequisites: `lvms-vg-ai` ready on `tr-gpu`, NVIDIA validation completed, OpenShift AI ready, and hardware profile `tr-gpu-3090` installed. The application ApplicationSet explicitly discovers only this workload. Git owns the model configuration; edits to managed resources through the dashboard are reconciled back to Git.

The PVC and download Job share sync wave 0 so `WaitForFirstConsumer` can bind the local volume. The Job downloads the pinned revision into its own directory and records completion. Wave 1 starts KServe only after the Job succeeds. Restarts use the existing files without downloading again. No Hugging Face token is needed for this public model.

```bash
kustomize build kubernetes/ocp-mgmt/applications/inference-server
oc get application inference-server -n openshift-gitops
oc get pvc,job,pods -n inference-server
oc logs job/download-qwen3-06b-c1899de -n inference-server
oc get inferenceservice local-llm -n inference-server
oc get deployment local-llm-predictor -n inference-server -o jsonpath='{.spec.strategy}{"\n"}'
python kubernetes/ocp-mgmt/applications/inference-server/scripts/smoke-test.py
```

The smoke test obtains a short-lived token without displaying it and verifies TLS, rejection of unauthenticated access, model discovery, chat completion, and streaming. It requires a logged-in `oc` session authorized to request a token for `inference-client`.

## Clients

Get the KServe-managed HTTPS endpoint and request a token:

```bash
oc get inferenceservice local-llm -n inference-server -o jsonpath='{.status.url}{"/v1\n"}'
oc create token inference-client -n inference-server --duration=1h
```

Use the endpoint as an OpenAI-compatible base URL, the token as the API key, and `local-llm` as the model name. Tokens expire and must be renewed; no static credential is stored in Git. The Role permits only `get` on this InferenceService, which KServe's proxy checks before accepting requests. For Qwen3 smoke testing, pass `chat_template_kwargs: {enable_thinking: false}`.

The `networking.kserve.io/visibility: exposed` label enables the OpenShift AI-managed Route. KServe and the platform model controller own the Service and Route. The route allows ten-minute requests for generation and streaming. NetworkPolicy permits inference traffic through port 8443 and limits direct runtime port 8080 to monitoring namespaces.

## Model changes and recovery

Choose a model revision and compatible runtime, then update the download Job's name, repository, revision, expected artifacts, and target directory together with the InferenceService `storageUri`. The Job is a regular completed Job, not a recurring sync hook; rename it when changing immutable Job fields. Keep `local-llm` as the API name so clients do not need reconfiguration. Review GPU memory, context length, and concurrency for each model.

The PVC is guarded with `Prune=confirm,Delete=false`; retiring the application does not automatically delete model data. Storage is local to `tr-gpu`, with no failover or replication. Model weights can be downloaded again; back up irreplaceable datasets separately. To repeat the initial download after repairing missing artifacts, remove the `.download-complete` marker for that revision and delete its completed Job, then let Argo CD recreate it. Preserve any useful data before deleting a PVC.

The 3090 is a homelab configuration outside Red Hat's listed enterprise accelerator models. The smoke test establishes functionality for the pinned runtime and model; larger models require separate validation.
