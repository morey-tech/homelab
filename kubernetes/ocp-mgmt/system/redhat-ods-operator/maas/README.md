# Models-as-a-Service routing

OpenCode selects local Qwen or Claude through [the MaaS gateway](https://maas.apps.ocp-mgmt.rh-lab.morey.tech). Routing follows the request's `model` field; it does not automatically classify prompts or fall back between providers.

| OpenCode model | Gateway API | Backend |
|---|---|---|
| `maas-local/local-llm` | `/v1/chat/completions` | Existing Qwen3-4B-Instruct-2507 vLLM service on `tr-gpu` |
| `maas-anthropic/claude-sonnet-4-6` | `/v1/messages` | Anthropic Claude Sonnet 4.6 |

The gateway is OpenShift AI 3.5 Models-as-a-Service (MaaS), with Red Hat Connectivity Link for authentication. External model routing and native API passthrough are Technology Preview features. llm-d's scheduler distributes requests among local inference workers; it is not needed to select between these two backends. The existing single-GPU KServe workload and its authenticated endpoint remain available to other clients.

## Resources and access

- `openshift-operators` installs Connectivity Link from `stable-1.4`, starting at `1.4.4`, with manual InstallPlan approval. User workload monitoring is enabled in `openshift-monitoring`.
- This directory configures Kuadrant/Authorino, the gateway, dashboard flags, PostgreSQL, and MaaS access policies. The parent DataScienceCluster enables `aigateway.modelsAsAService`; the deprecated `kserve.modelsAsService` remains `Removed`.
- The AI Gateway operator manages MaaS workloads in `redhat-ai-gateway-infra`. PostgreSQL 16 stores API key state on a 5 GiB `lvms-vg-nvme` PVC. External Secrets generates one immutable database credential, retained independently of its ExternalSecret. Preserve both the Secret and PVC together; no database backup is configured here. The database is a single-instance homelab deployment, with internal plaintext connections restricted by NetworkPolicy to its namespace.
- The gateway uses the existing `data-science-gateway-class`, a ClusterIP Service, and a passthrough Route. Its HTTPS listener explicitly references the existing `apps-wildcard-cert` Secret in `openshift-ingress`, which covers `*.apps.ocp-mgmt.rh-lab.morey.tech` and is renewed by the ingress certificate configuration. Passthrough terminates TLS at this gateway, so the ingress controller's default certificate is not inherited automatically. No additional Certificate or MetalLB address is required.
- Authorino's CR mounts the injected OpenShift service CA at `/etc/ssl/certs/openshift-service-ca`. Mounting over `/etc/ssl/certs` conflicts with the operator's serving-certificate mount at `/etc/ssl/certs/tls.crt` and prevents container creation. Because the Authorino CR has no environment-variable field, `authorino-trust.yaml` uses partial server-side apply to manage only `SSL_CERT_DIR` on the generated Deployment, adding the service CA directory while retaining Go's default Linux CA directories. The operator owns the remaining Deployment fields; pruning/deleting this partial resource is disabled. Wave 1 applies the override after the wave 0 Authorino CR; on a fresh installation Argo may retry until the operator creates the Deployment. The gateway annotation enables the operator's Authorino TLS bootstrap.
- [Inference resources](../../../applications/inference-server/maas.yaml) register both backends as `ExternalProvider`/`ExternalModel` resources. The external-model API also supports internal endpoints. A dedicated ClusterIP exposes vLLM port 8080 only to the MaaS gateway and existing monitoring namespaces through NetworkPolicy. The sentinel credential satisfies the ExternalProvider schema; vLLM does not validate it. Client authentication occurs at MaaS.
- RHOAI 3.5.1's payload processor (`a98a2650e74f8b832ff75206f795cbb62b9cd688`) hard-codes port 443 and TLS in its provider resources. The legacy `maas.opendatahub.io/port` and `/tls` annotations do not configure `inference.opendatahub.io` models. The dedicated local Service therefore maps port 443 to vLLM pod port 8080, while `local-vllm-transport.yaml` disables upstream TLS only for this destination/port from the MaaS gateway. Its client-namespace DestinationRule takes precedence over the generated backend-namespace rule; it does not modify operator-owned resources. Client-facing HTTPS and the existing pod NetworkPolicy remain in effect. Recheck this compatibility configuration when upgrading the payload processor.
- Anthropic's provider credential comes from the same Bitwarden item as Dev Spaces' existing Claude key. Dev Spaces uses an automatically rotated shared MaaS key; administrators can still create personal keys. Provider credentials are never included in the OpenCode gateway profile.
- `devspaces-models` grants the existing `cluster-admins` group access to exactly these two model references. The policy also grants the dedicated `system:serviceaccount:devspaces-maas:maas-key-rotator` identity access; its separate `devspaces-workspaces` subscription supplies shared workspace credentials. The subscription declares 100,000 tokens/minute per model; **native Anthropic passthrough is not metered by MaaS in this preview**. Configure Claude spending and rate limits at Anthropic.

`payload-processing.yaml` places `model-provider-resolver` before `stream-usage-enforcer`. The resolver populates the input API format, allowing the enforcer to skip native Anthropic Messages while retaining OpenAI streaming usage for Qwen. The shipped reverse order injects `stream_options` into Claude requests, which Anthropic rejects. Response translation remains disabled to preserve native SSE streaming. MaaS clients must send a Bearer key on both APIs; the provider's Anthropic credential is injected downstream.

The profile ConfigMap opts out of MaaS default reconciliation with `opendatahub.io/managed: "false"`. Partial server-side apply owns only `custom-ipp-config.yaml`, preserving the preprocessor profile. A wave 2 partial Deployment applies only the profile checksum annotation to roll the processor after the wave 1 ConfigMap update. Recompute that SHA-256 when editing the profile. Both partial resources disable pruning/deletion because the operator owns their lifecycle. After GitOps deployment, test Claude streaming and Qwen usage reporting again; API acceptance alone does not prove the running processor loaded the new order.

Claude uses the native Anthropic SDK and `messages` format to retain incremental streaming and provider features. Cross-format OpenAI-to-Anthropic translation can buffer the entire response. Qwen uses OpenAI Chat Completions, with vLLM's Hermes tool parser enabled for OpenCode tool calls. Its served context is 65,536 tokens after the [Hermes prerequisite rollout](../../../applications/inference-server/README.md#32k-baseline-and-64k-pilot-validation); start a new session when switching from a longer Claude conversation if necessary.

## Automatic workspace keys

[Key rotation](key-rotation/README.md) runs in the dedicated `devspaces-maas` namespace. The CronJob uses a projected service-account token to issue 90-day keys, checks every 15 minutes, and renews with 30 days remaining. Keys and metadata are generated at runtime, never committed. The rotator validates both model registrations before publishing; old keys retain their original expiration. A Prometheus alert detects stalled checks.

## GitOps rollout

All changes require review and approved local commits before the human pushes. Do not apply these files manually or create test Jobs. Deploy the prerequisite commit first; ApplicationSet sync waves do not order separate Applications.

1. Push the reviewed Connectivity Link and monitoring prerequisites. Inspect the `rhcl-operator` InstallPlan in the OpenShift console, including its dependent operators, and approve it there. Confirm the installed version is at least 1.4.2 and User Workload Monitoring is running.
2. Push the reviewed MaaS platform and inference changes. Let Argo CD reconcile `redhat-ods-operator-system`, `inference-server`, and the ApplicationSet namespace label. Within the platform Application, wave 0 creates the database and gateway prerequisites, wave 1 enables MaaS, and wave 2 registers access policies. Missing MaaS APIs are skipped during pre-sync dry runs and retried after the operator installs them.
3. Confirm platform readiness and both model registrations. Deploy [automatic key rotation](key-rotation/README.md) and wait for the generated source Secret before pushing the Dev Spaces defaults. Wait for `maas-api-key` ExternalSecret readiness, then start/restart workspaces as described in the [Dev Spaces instructions](../../openshift-devspaces/README.md#maas-model-selection).

```bash
oc get subscription rhcl-operator -n openshift-operators
oc get installplan -n openshift-operators
oc get pods -n openshift-user-workload-monitoring
oc get kuadrant kuadrant -n kuadrant-system
oc get authorino authorino -n kuadrant-system
oc get datasciencecluster default-dsc
oc get pods,pvc,externalsecret -n redhat-ai-gateway-infra
oc get certificate apps-wildcard-cert -n openshift-ingress
oc get gateway maas-default-gateway -n openshift-ingress
oc get route maas -n openshift-ingress
oc get pods -n openshift-ingress -l app=payload-processing
oc get externalproviders.inference.opendatahub.io -n inference-server
oc get externalmodels.inference.opendatahub.io -n inference-server
oc get maasmodelrefs -n inference-server
oc get maasauthpolicies,maassubscriptions -n models-as-a-service
```

Require a ready database, `AIGatewayReady` and `ModelsAsAServiceReady`, gateway `Programmed=True`, a ready certificate, and ready model references before using OpenCode. Check Authorino logs for CA errors and the gateway for successful body-based routing. Check the generated vLLM Deployment includes `--enable-auto-tool-choice` and `--tool-call-parser=hermes`. ServingRuntime reconciliation restarts the single GPU pod, temporarily interrupting its existing clients.

## Validation after deployment

From a new workspace with the automatically injected `MAAS_API_KEY`, discover the models:

```bash
curl --fail-with-body --silent --show-error \
  https://maas.apps.ocp-mgmt.rh-lab.morey.tech/v1/models \
  -H "Authorization: Bearer $MAAS_API_KEY"
```

Test each API with a short streaming request. The Claude request is billed to the existing Anthropic account.

```bash
curl --fail-with-body --no-buffer \
  https://maas.apps.ocp-mgmt.rh-lab.morey.tech/v1/chat/completions \
  -H "Authorization: Bearer $MAAS_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"local-llm","messages":[{"role":"user","content":"Say hello briefly."}],"max_tokens":32,"stream":true}'

curl --fail-with-body --no-buffer \
  https://maas.apps.ocp-mgmt.rh-lab.morey.tech/v1/messages \
  -H "Authorization: Bearer $MAAS_API_KEY" \
  -H 'anthropic-version: 2023-06-01' \
  -H 'Content-Type: application/json' \
  -d '{"model":"claude-sonnet-4-6","messages":[{"role":"user","content":"Say hello briefly."}],"max_tokens":32,"stream":true}'
```

Also verify requests without a MaaS key or with an invalid key are rejected, unrelated workspace pods cannot reach `local-llm-maas:443`, and `/models` in OpenCode switches between both backends. Exercise a harmless approved file-read tool with each model, then a multi-turn request larger than 16 KiB. Red Hat documents truncation in older gateway/wasm builds; require an OpenShift gateway proxy incorporating the Service Mesh 3.3.1 fix. Do not infer success from short greetings alone. Verify existing AnythingLLM and other KServe clients still authenticate and receive responses.

These runtime checks require the GitOps-deployed resources and are deferred until after the human push. If they fail, diagnose read-only and prepare a reviewed Git fix; do not patch generated cluster workloads. OpenCode defaults to MaaS after the credential-injection rollout; the direct Anthropic profile remains available through an explicit `OPENCODE_CONFIG` override.

## References

- [OpenShift AI 3.5 MaaS configuration, external providers, and passthrough limitations](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/3.5/html-single/govern_llm_access_with_models-as-a-service/index)
- [Red Hat companion platform guide](https://rh-aiservices-bu.github.io/rhoai-maas-guide/modules/main/02-platform-config.html)
- [Authorino custom certificate volumes](https://github.com/Kuadrant/authorino-operator#custom-resource-definition-crd)
- [vLLM tool calling](https://docs.vllm.ai/en/stable/features/tool_calling/)

### Local Qwen transport verification

After both Argo applications reconcile, repeat the authenticated streaming request above. In the MaaS gateway's Envoy configuration, require `outbound|443||local-llm-maas.inference-server.svc.cluster.local` with endpoint port 8080 and no upstream TLS transport socket. The previous failure was `500 NC cluster_not_found`: the route requested port 443 but the Service exposed only 8080. Merely adding port 443 without the DestinationRule would leave TLS enabled against a plaintext runtime.

The scoped DestinationRule relies on [Istio's client-namespace lookup precedence](https://istio.io/latest/docs/ops/best-practices/traffic-management/#cross-namespace-configuration). Both applications may reconcile in either order; wait for both before testing. Verify Claude's TLS configuration and the existing authenticated KServe endpoint remain unchanged.

## OpenClaw access

[Standalone OpenClaw](../../../applications/openclaw/README.md) has its own `openclaw` auth policy and subscription for `local-llm` only (30000 tokens/minute). `openclaw-key-rotation/` runs the shared rotator in the isolated `openclaw-maas` namespace and validates only Qwen. It issues 90-day credentials with renewal at 30 days remaining, independently of Dev Spaces. ESO distributes the key only to the `openclaw` application. Deploy these prerequisites before the application.
