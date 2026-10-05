# AnythingLLM on ocp-mgmt

[Open AnythingLLM](https://anythingllm.apps.ocp-mgmt.rh-lab.morey.tech) and sign in with the generated single-user password:

```bash
oc get secret anythingllm-auth -n anythingllm -o jsonpath='{.data.AUTH_TOKEN}' | base64 -d
```

Create a workspace and use the preconfigured system model. No external LLM account is required. `local-llm` serves Qwen3-4B-Instruct-2507, a non-thinking model; no `/no_think` suffix is needed. The configured context is 32,768 tokens, including prompt/history, retrieved documents, and generated output. The response limit remains 1,024 tokens. See the [32K rollout checks](../inference-server/README.md#32k-context-validation); verify both applications have reconciled before sending long prompts.

| Setting | Value |
|---------|-------|
| Namespace / Argo CD Application | `anythingllm` |
| Image | OpenShift-compatible `rh-aiservices-bu/anythingllm-workbench:1.9.1`, pinned by digest |
| Provider / model | Generic OpenAI / `local-llm` |
| Inference base URL | `https://local-llm-inference-server.apps.ocp-mgmt.rh-lab.morey.tech/v1` |
| Context / maximum response | 32,768 / 1,024 tokens |
| Embeddings / vector database | Native CPU embeddings / LanceDB |
| Persistence | 50 GiB RWO PVC on `lvms-vg-ai`, local to `tr-gpu` |
| Updates | One replica, `Recreate`; brief downtime expected |
| UI access | HTTPS, password-protected single-user mode |

## Deployment and verification

The application ApplicationSet explicitly includes this directory. Prerequisites are the [inference server](../inference-server/README.md), `lvms-vg-ai`, and External Secrets Operator with its Password generator CRD. The inference-server application owns the cross-namespace RoleBinding; synchronize both applications when enabling or removing this integration.

```bash
kustomize build kubernetes/ocp-mgmt/applications/anythingllm
oc get application anythingllm -n openshift-gitops
oc get pvc,pods,externalsecrets -n anythingllm
oc rollout status deployment/anythingllm -n anythingllm
python kubernetes/ocp-mgmt/applications/anythingllm/scripts/smoke-test.py
```

The smoke test validates TLS, rejected unauthenticated access, password login, and streaming generation through AnythingLLM. It creates and removes only a uniquely named test workspace. It requires permission to read the UI password Secret, does not display credentials, and leaves existing workspaces alone. Document ingestion and retrieval are separate from this chat smoke test.

To also test persistence across a pod replacement, allowing brief downtime:

```bash
python kubernetes/ocp-mgmt/applications/anythingllm/scripts/smoke-test.py --restart
```

## Credentials and configuration

External Secrets generates separate `AUTH_TOKEN` and `JWT_SECRET` values once and retains the `anythingllm-auth` Secret independently of application deletion. Do not commit generated values. This is AnythingLLM's built-in single-user password mode, not OpenShift OAuth or multi-user authentication.

The Kubernetes token controller populates `anythingllm-inference-token` for ServiceAccount `anythingllm`. Its only application permission is `get` on `inferenceservices/local-llm` in `inference-server`, which the authenticated KServe proxy requires. This manually declared service-account token does not expire automatically: AnythingLLM reads its API key from an environment variable and cannot refresh a projected token. Remove the `anythingllm-local-llm` RoleBinding to revoke inference access immediately. For rotation, replace the token Secret and restart AnythingLLM after Kubernetes has repopulated it. No Kubernetes API token is mounted into the pod by default.

The ConfigMap controls the provider, endpoint, model, and token limits. Change these in Git; environment values take precedence over saved settings after restart. The deployment requests no GPU: generation uses KServe, while embeddings run on CPU. Embedding weights are downloaded on first use and cached on the volume. Egress remains allowed for model access and document ingestion; NetworkPolicy accepts UI ingress only from OpenShift routers. Telemetry is disabled.

## Storage and recovery

Mount the PVC at `/opt/app-root/src/anythingllm`, not directly at `/app/server/storage`. The workbench launcher links its database, documents, vector data, collector directories, and `.env` into this persistent directory. The `.env` includes generated encryption keys and may contain saved provider credentials: treat volume backups as secrets.

The PVC has `Prune=confirm,Delete=false` to guard against accidental GitOps deletion. Local NVMe storage has no replication or node failover. Back up the entire volume and `anythingllm-auth` Secret together; stop the deployment while taking a filesystem backup to keep SQLite consistent. Keep a single replica and the recreate strategy when upgrading.

Image source: [AnythingLLM OpenShift workbench](https://github.com/rh-aiservices-bu/llm-on-openshift/tree/main/llm-clients/anythingllm).
