# Dev Spaces MaaS key rotation

```bash
oc get cronjob,jobs -n devspaces-maas
oc logs -n devspaces-maas -l app=maas-key-rotator --tail=20
oc get secret maas-workspace-key -n devspaces-maas
oc get maassubscription devspaces-workspaces -n models-as-a-service
```

The CronJob checks every 15 minutes, creates a key on its first scheduled run, and renews when 30 days remain. Every creation explicitly requests `expiresIn: 90d`, matching the currently configured MaaS maximum of 90 days. The client rejects shorter lifetimes (with five minutes of timestamp tolerance because MaaS reports `createdAt` after storing the key). It also checks that both Qwen and Claude appear in authenticated model discovery before publishing. Discovery does not send billable inference requests.

The generated `maas-workspace-key` Secret contains `MAAS_API_KEY`, `key-id`, `created-at`, and `expires-at`. It is owned by the rotation job's workflow, not rendered by Kustomize or stored in Git/Bitwarden. Kubernetes automatically supplies and refreshes the job's projected service-account token. The service account has access to only the two model references, its own `devspaces-workspaces` subscription, and Secret creation/update in this dedicated namespace. It has no cluster-admin role. The administrator's existing `devspaces-models` subscription remains separate.

The job preserves the current Secret on validation failures. It uses resource-version checks when updating an existing Secret and confirms ambiguous writes before treating them as successful. A candidate that fails validation is revoked; an ambiguous unpublished candidate may remain valid until expiry rather than risk revoking a key that was persisted. A lost response during key creation can likewise leave an unused key until expiry. Keys are never logged.

Previous published keys are **not revoked early**: they retain the full requested lifetime. Under normal operation, renewal at about day 60 gives around 30 days of overlap. New workspaces receive the current key; existing environments continue using their old key and require a workspace stop/start once it expires. Starting a workspace does not extend a key's expiry. There is no proxy or automatic workspace restart.

## Distribution

The Kubernetes provider in the [Dev Spaces ExternalSecret](../../../openshift-devspaces/maas-api-key.yaml) reads only from `devspaces-maas`, using a separate read-only service account. ESO receives permission to request tokens only for that reader. The ClusterSecretStore is restricted to the `openshift-devspaces` namespace. Kubernetes' default `system:basic-user` binding supplies self-subject review permissions used by ESO validation.

The ExternalSecret publishes only `MAAS_API_KEY` into a Secret labelled `workspaces-config` in `openshift-devspaces`. Dev Spaces' native Secret synchronization then provides it to all user namespaces, including during first-workspace provisioning. `mount-on-start: true` prevents credential updates from restarting active workspaces. This is shared lab access: all workspace users can use the same two-model subscription and have access to its key.

## GitOps rollout and verification

1. Commit/push the reviewed rotation resources and MaaS access policy first. Let `redhat-ods-operator-system` reconcile. The first key appears on the next quarter-hour schedule, provided MaaS is ready.
2. Confirm the Job completed and the source Secret exists. Do not print its data. Service-account key issuance must be verified here; dry runs cannot prove it.
3. Commit/push the Dev Spaces Secret distribution and default-profile change. Wait for `ClusterSecretStore/devspaces-maas` and `ExternalSecret/maas-api-key` in `openshift-devspaces` to be Ready before opening new workspaces.
4. Start a new workspace (also verify a first-time user's namespace), confirm the key is present without printing it, and test both models with `opencode`.
5. Confirm `MaaSWorkspaceKeyRotationStalled` is loaded by monitoring. It fires after no successful check for over an hour, including failure to bootstrap, with a further 15-minute hold. Job logs report sanitized failure types/HTTP status. If renewal fails, fix the underlying API/access problem in Git; the existing key remains usable until expiry.

```bash
# Inside the new workspace; never echo the key or resolved provider config.
test -n "${MAAS_API_KEY:-}" && printf 'MaaS key injected\n'
opencode models maas-anthropic
opencode models maas-local
opencode
```

Unit tests exercise bootstrap, renewal timing, rejection recovery, invalid candidates, API outages, and ambiguous writes without network access:

```bash
python -B -m unittest discover -s kubernetes/ocp-mgmt/system/redhat-ods-operator/maas/key-rotation/runtime -p 'test_*.py'
```

[Dev Spaces Secret synchronization](https://docs.redhat.com/en/documentation/red_hat_openshift_dev_spaces/3.26/html/administration_guide/configuring-devspaces), [ESO Kubernetes provider](https://external-secrets.io/latest/provider/kubernetes/), and [MaaS API key lifecycle](https://github.com/opendatahub-io/models-as-a-service/blob/main/maas-api/README.md) describe the underlying interfaces.

## Shared runtime

The `runtime/` Kustomization packages the tested rotation script for both Dev Spaces and [OpenClaw](../../../../applications/openclaw/README.md). `MAAS_SUBSCRIPTION` and `MAAS_REQUIRED_MODELS` select the consumer; defaults preserve Dev Spaces behavior. OpenClaw uses an isolated `openclaw-maas` namespace, its own subscription, and only `local-llm`.
