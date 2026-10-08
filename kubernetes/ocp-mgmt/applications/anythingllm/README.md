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
| YNAB MCP | `ynab-mcp-server` 0.4.1 over stdio; read-only tools enabled |

## YNAB MCP

[ynab-credentials.yaml](ynab-credentials.yaml) reads the **password** field of Bitwarden Login item `1aa42e55-bbd7-4af8-9c28-b4dd00dc69cd` through `bitwarden-login`. Store the [YNAB personal access token](https://api.ynab.com/#personal-access-tokens) in that field; the username is unused. The cluster's External Secrets account must have access to the item, and the Bitwarden serving cache must have synchronized it. Never put the token in Git or the MCP JSON.

External Secrets refreshes `anythingllm-ynab` hourly. The token is projected as a file and read only when the YNAB child process starts. The launcher sets `YNAB_API_TOKEN` in that child process because upstream tools check it, in addition to passing the token to the API client. It is not stored in AnythingLLM's parent environment or persistent MCP configuration. The mount is optional so a missing credential leaves existing chat available, while YNAB fails to start. After token rotation and Secret projection, use **Agent Skills → MCP Servers → Refresh** to restart the MCP process with the new token.

The integration follows [AnythingLLM's Docker MCP setup](https://docs.anythingllm.com/mcp-compatibility/docker). On each pod creation, an init container installs the lockfile-pinned npm dependencies into an `emptyDir` and copies a digest-pinned Node 22 binary. AnythingLLM's existing Node 18 runtime is unchanged. Pod startup requires access to Docker Hub and the npm registry; failed installation blocks startup. No separate MCP Service or Route is needed.

The init container merges the Git-managed `ynab` entry into `storage/plugins/anythingllm_mcp_servers.json` on the PVC. Other MCP servers and settings are preserved; malformed saved JSON stops initialization instead of discarding it. Git controls the `ynab` entry: UI removal or edits are replaced on the next pod creation. ConfigMap content changes update the pod template through Kustomize's generated name.

The initial deployment exposes **14 read-only tools** from the [upstream server](https://github.com/calebl/ynab-mcp-server). Transaction creation, updates, deletion, approvals, and budget changes are excluded. Anyone with access to this single-user AnythingLLM instance can invoke the reading tools through an agent against the token's YNAB account. Optional TypeSafe categorization is not enabled. No default plan is configured: use `ynab_list_plans` and specify `planId` when multiple plans are available.

`YNAB_READ_ONLY` is set to `"true"` in [the managed MCP entry](mcp/anythingllm_mcp_servers.json). To enable all 24 read and write tools later, change it to `"false"` and deploy through GitOps. Version 0.4.1's published stdio entry point ignores that environment variable, so [the launcher](mcp/run-ynab.mjs) calls upstream's exported registry with an explicit `readOnly` option. It uses the upstream tool implementations in both modes.

### Use and verify after GitOps rollout

After review, approved local commits, and a human push, let Argo CD reconcile. Check:

```bash
oc get externalsecret anythingllm-ynab -n anythingllm
oc wait --for=condition=Ready externalsecret/anythingllm-ynab -n anythingllm --timeout=120s
oc rollout status deployment/anythingllm -n anythingllm
oc logs deployment/anythingllm -n anythingllm -c install-ynab-mcp
```

Open **Agent Skills → MCP Servers** in AnythingLLM. This starts the configured MCPs; they do not start just because the pod is ready. Confirm `ynab` is running and lists 14 tools, including `ynab_list_plans` and `ynab_get_transactions`, with no write tools such as `ynab_create_transaction` or `ynab_delete_transaction`. Configure the workspace's agent to use the existing Generic OpenAI provider and `local-llm`, then ask `@agent List my YNAB plans` to verify credential access with a read operation. Agent tool selection by the local model still needs this live check. Budget data returned by tools enters chat/model context and may be retained in chat history and logs.

### Local validation

The protocol test uses a fake token, initializes MCP, pings, and lists tools in both modes. It also invokes `ynab_list_plans` with mocked HTTP responses and verifies token propagation into the API request. It makes no external YNAB API calls. Use Node 22:

```bash
node --test kubernetes/ocp-mgmt/applications/anythingllm/scripts/test-mcp-config.cjs
ynab_test_dir=$(mktemp -d)
cp kubernetes/ocp-mgmt/applications/anythingllm/mcp/package*.json "$ynab_test_dir/"
cp kubernetes/ocp-mgmt/applications/anythingllm/mcp/run-ynab.mjs "$ynab_test_dir/"
npm ci --prefix "$ynab_test_dir" --omit=dev --ignore-scripts --no-audit --no-fund
node kubernetes/ocp-mgmt/applications/anythingllm/scripts/test-ynab-mcp.mjs "$ynab_test_dir"
rm -rf "$ynab_test_dir"
kustomize build kubernetes/ocp-mgmt/applications/anythingllm
```

Secret synchronization, pod initialization under OpenShift's assigned UID, UI discovery, real YNAB reads, and agent tool use are deferred until GitOps deployment.

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
