# CPU embedding services

Two independent KServe InferenceServices provide OpenAI-compatible `/v1/embeddings` endpoints for the [podcast retrieval prototype](../../rr-lessons/prototype/README.md). They belong to the `inference-server` namespace and Argo CD Application. The prototype's current local embedding path and the daily lesson CronJob are unchanged; client integration and retrieval comparison follow deployment validation.

| InferenceService / API model name | Hugging Face model | Revision | Vector dimensions | CPU request / limit | RAM request / limit |
|---|---|---|---|---|---|
| `qwen3-embedding-0-6b` | `Qwen/Qwen3-Embedding-0.6B` | `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3` | 1,024 | 8 / 8 | 4 / 8 GiB |
| `qwen3-embedding-4b` | `Qwen/Qwen3-Embedding-4B` | `5cf2132abc99cad020ac570b19d031efec650f2b` | 2,560 | 8 / 8 | 20 / 32 GiB |

Both services run one replica on `tr-gpu`, with no GPU allocation. The common `vllm-cpu-embeddings` ServingRuntime uses pooling, FP32 weights, eager execution, a 4,096-token input limit, and at most two sequences / 8,192 batched tokens. The model cards advertise a larger context; this deployment starts with a smaller CPU workload. Memory allocations and the 15-minute startup allowance are initial estimates pending rollout measurements.

The 0.6B InferenceService adds `--gpu-memory-utilization=0.65`, which also controls the CPU backend's memory budget in this runtime. On 2026-10-12, startup failed before loading weights because the default 0.92 utilization required 7.36 GiB available within the 8 GiB container limit, but only 6.11 GiB remained after startup overhead. The 0.65 setting budgets 5.2 GiB and leaves 2.8 GiB of headroom while retaining the 8 GiB limit. This override applies only to the 0.6B service; the 4B service retains its existing configuration. Confirm model loading and request-time memory after GitOps rollout.

## Hardware and runtime provenance

On 2026-10-12, read-only `oc exec` into the existing `local-llm` pod on `tr-gpu` reported **AMD Ryzen Threadripper 3960X 24-Core Processor**: 24 physical cores, 48 logical CPUs, one NUMA node, and approximately 126 GiB installed RAM. The CPU has AVX2, FMA and F16C, but no AVX-512 or native BF16 instructions. FP32 avoids relying on native BF16 acceleration. `OMP_NUM_THREADS=8` and `VLLM_CPU_OMP_THREADS_BIND=nobind` bound each model's inference thread count without binding both services to the entire node. Kubernetes CPU quotas apply to the whole container; these settings do not reserve exclusive physical cores.

The running OpenShift AI 3.5.1 operator supplies `vllm-cpu-x86-runtime-template` in `redhat-ods-applications`, labeled **Technology Preview**, with vLLM runtime version `v0.24.0`. This deployment pins its exact image:

```text
registry.redhat.io/rhaii/vllm-cpu-rhel9@sha256:7a28b867955055a8836ea2a78e70b8bad63c1ee50e8a5f8dd95d1194f20ec489
```

Authenticated registry inspection verified Linux/amd64, Red Hat AI Inference Server version 3.5.1, and a CPU-specific build. The [Red Hat CPU documentation](https://docs.redhat.com/en/documentation/red_hat_ai_inference/3.4/html/getting_started/about-cpu-inference_getting-started) specifies AVX2 as the minimum instruction set. The [supported hardware matrix](https://docs.redhat.com/en/documentation/red_hat_ai/3/html-single/supported_product_and_hardware_configurations/supported_product_and_hardware_configurations) lists enterprise CPUs; this Threadripper is a homelab trial, not a claim of certified hardware support. Actual startup and embedding responses on this CPU remain post-GitOps checks. See also [vLLM CPU configuration](https://docs.vllm.ai/en/v0.24.0/getting_started/installation/cpu/) and the [0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) / [4B](https://huggingface.co/Qwen/Qwen3-Embedding-4B) model cards.

## Storage and synchronization

`download-embedding-models` downloads both immutable model revisions sequentially, using the existing digest-pinned `hf-cli` image and `hf-token` Secret. Each model has a separate directory on the existing 50 GiB `models` PVC. The volume had 39 GiB free at inspection; the two BF16 model downloads need roughly 9 GB before loading as FP32 in RAM. `ReadWriteOnce` permits these pods to share the volume because all run on `tr-gpu`. This local storage does not provide node failover.

The downloader keeps the full model snapshots, including tokenizer and sentence-transformers pooling metadata. It checks required nonempty files before writing a revision completion marker, and rechecks them before skipping a cached revision. This checks file presence, not full weight integrity. Interrupted downloads can resume through Hugging Face's local metadata.

The Job uses wave 0 with `Force=true,Replace=true`, matching the existing model download workflow. Both services use wave 1 and `Recreate`. Perform a full application sync for model changes so Argo CD waits for downloads before updating predictors. A failed download blocks wave 1 for the application, including pending chat-service changes; an already-running chat service continues serving. A full sync replaces the download Job and its logs, so collect failure logs first. Model revision changes must update both the Job and the corresponding `storageUri`.

## Authentication and rollout checks

KServe manages the HTTPS Routes and token-authenticating proxies. The `embedding-client` Role allows only `get` on these two InferenceServices. It is bound to the dedicated `embedding-client` ServiceAccount and the existing `rr-lessons` ServiceAccount. NetworkPolicy admits inference through port 8443 and limits direct port 8080 access to monitoring namespaces. The runtime receives no Hugging Face token and runs offline.

Before committing:

```bash
kustomize build kubernetes/ocp-mgmt/applications/inference-server
kustomize build kubernetes/ocp-mgmt/applications/inference-server/embeddings | oc apply --dry-run=server -f -
```

After human review, commit, push, and Argo CD reconciliation:

```bash
oc get application inference-server -n openshift-gitops
oc logs job/download-embedding-models -n inference-server
oc get inferenceservice qwen3-embedding-0-6b qwen3-embedding-4b -n inference-server
oc rollout status deployment/qwen3-embedding-0-6b-predictor -n inference-server --timeout=20m
oc rollout status deployment/qwen3-embedding-4b-predictor -n inference-server --timeout=20m
oc logs deployment/qwen3-embedding-0-6b-predictor -n inference-server -c kserve-container
oc logs deployment/qwen3-embedding-4b-predictor -n inference-server -c kserve-container
oc get inferenceservice qwen3-embedding-0-6b qwen3-embedding-4b -n inference-server -o custom-columns=NAME:.metadata.name,URL:.status.url
```

Verify both predictors select CPU execution, load the expected embedding model and pooling configuration, and stay ready without OOM kills or illegal-instruction errors. Then check authenticated `/v1/models` and `/v1/embeddings`, rejection of unauthenticated calls, finite vectors with the expected dimensions, and RAM usage under short requests. These runtime checks require deployment; a server-side dry run cannot exercise model loading or CPU kernels.

The dedicated ServiceAccount can supply a short-lived token to a later comparison client via `oc create token embedding-client -n inference-server --duration=1h`. Treat the token as a credential. Use the discovered Route plus `/v1` as the base URL and the InferenceService name as the API model name. The comparison phase should implement Qwen's query instruction formatting, validate pooling and normalization, and build a separate LanceDB table for each model and revision. Vectors from the two models are not interchangeable, even if reduced to the same dimension.
