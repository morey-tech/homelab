# Hermes comparison pilot

After GitOps deployment, open [Hermes](https://hermes.apps.ocp-mgmt.rh-lab.morey.tech), sign in through OpenShift OAuth, then use the Hermes username `admin` and its generated password:

```bash
oc get secret dashboard-password -n hermes -o jsonpath='{.data.value}' | base64 -d
printf '\n'
```

Treat the displayed password as a credential. ESO generates it once, alongside a separate stable session-signing key and OAuth cookie secret. These retained Secrets are not stored in Git. Every authenticated OpenShift user who also knows the Hermes password shares this single Hermes profile; it is not a per-user workspace service.

## Comparison with OpenClaw

| Setting | Hermes | OpenClaw |
|---|---|---|
| Browser | [Hermes](https://hermes.apps.ocp-mgmt.rh-lab.morey.tech) | [OpenClaw](https://openclaw.apps.ocp-mgmt.rh-lab.morey.tech) |
| Namespace | `hermes` | `openclaw` |
| State | Fresh `hermes-state` PVC, 10 GiB | Existing OpenClaw PVC |
| Model | MaaS `local-llm`, Qwen3-4B-Instruct-2507 | Same model |
| Model access | Separate `hermes` subscription, 100,000 tokens/minute | Existing `openclaw` subscription, 30,000 tokens/minute |
| Client context budget | 65,536 tokens; requires the shared server upgrade | Existing 32,768-token budget |
| Browser authentication | OpenShift OAuth, then Hermes password | Existing OAuth and device approval |

No OpenClaw files, sessions, credentials, skills, or memories are imported. Both applications remain independently deployable. They share the existing GPU backend, so compare the same prompts sequentially in fresh conversations. Assess response quality, file tasks, skill creation, memory recall, and the browser experience; concurrent requests also measure competition for the GPU.

The pilot enables Hermes file, memory, skills, session-search, and todo tools. The terminal tool is disabled. File-tool writes are limited to `/opt/data/workspace`; this is a write guard, not a read sandbox. Hermes manages its own memory and skills under `/opt/data`. Optional tools that require shell commands, additional dependencies, external providers, or new network destinations need separately reviewed configuration. Auxiliary model tasks use the same MaaS model.

## Runtime and storage

- The official `nousresearch/hermes-agent:v0.22.5` image is pinned by digest. `launch.py` starts the prebuilt dashboard directly, bypassing the image's root/s6 bootstrap so OpenShift can assign an arbitrary UID under `restricted-v2`.
- The root filesystem is read-only; the PVC and `/tmp` are writable. The application has no Kubernetes service-account token. The OAuth sidecar alone mounts its projected token.
- An unprivileged init container creates `hermes-home` inside the PVC and mounts that subdirectory at `/opt/data`. Hermes's gateway requires its home to be owned by the application UID with private permissions; the root-owned PVC mount point fails that check even when its group permissions allow writes. `fsGroupChangePolicy: OnRootMismatch` avoids widening private gateway-file permissions on subsequent mounts.
- On upgrade from the original layout, the init container moves existing state into `hermes-home` on the same filesystem, preserving the `/opt/data` paths seen by Hermes. `Recreate` stops the old processes first. SQLite databases, WAL files, skills, configuration, and workspace files move together. Interrupted migrations resume, and conflicting source/destination entries stop startup without overwriting either copy. A rollback must retain the subdirectory mount; reverting to a root mount would hide the migrated state.
- The dashboard listens on `127.0.0.1:9119`. Only the OAuth proxy's TLS port is exposed through a reencrypt Route. `dashboard.public_url` enables Hermes's native authentication gate even on loopback and supplies the exact browser origin.
- Kustomize generates the read-only managed configuration. Model, toolset, public origin, and dependency-install policy changes belong in Git. The initial `SOUL.md` and current-schema user configuration are seeded only when absent. The image's bundled-skills sync preserves user edits while adding/updating packaged skills; existing state is preserved on restart.
- The launcher reads projected MaaS and dashboard credentials without logging them. A changed credential restarts the dashboard container within roughly 30 seconds of volume projection, refreshing child processes as well. Active browser sessions may need to reconnect; MaaS rotation normally has about 30 days of key overlap.
- Local NVMe storage schedules on `ms-02` or `ms-04`; the bound volume pins subsequent runs to its node. PVC pruning requires confirmation and Argo deletion is disabled; the volume has no replication or backup in this deployment.
- The launcher starts the browser dashboard. A browser chat selecting the default profile can also start its profile gateway on demand, which requires the private home above. No Telegram, Discord, or other messaging credentials are configured in this pilot.

NetworkPolicy admits the OpenShift router and limits internal access to DNS, ingress/MaaS/OAuth, and the API endpoints required by the proxy. Public HTTPS additionally requires the namespace EgressFirewall: ClawHub and the GitHub API, raw-content, archive, and web hosts are allowed. OVN DNS rules operate on resolved IPs, not individual URLs. Package registries and arbitrary websites are not generally permitted. Automatic dependency installation is disabled; use Git-reviewed image/configuration changes for additional dependencies. Manage `network.yaml` and `egress-firewall.yaml` together.

## GitOps rollout

1. Review, commit, and push the [64K Qwen prerequisite](../inference-server/README.md#32k-baseline-and-64k-pilot-validation) first. Wait for Argo reconciliation and validate the new model limit and cache capacity. This restarts the shared predictor and briefly interrupts all local-model clients.
2. Review and commit the [Hermes MaaS prerequisites](../../system/redhat-ods-operator/maas/hermes-key-rotation/). After the human pushes, let `redhat-ods-operator-system` reconcile the isolated `hermes-maas` namespace, access policy, subscription, and rotator. The source credential appears on the next quarter-hour schedule when MaaS is ready.
3. Verify the source Secret exists without printing it, then review/commit and push the Hermes application and ApplicationSet entry. Argo creates `hermes` and reconciles its resources. Separate Applications are not ordered by sync waves; wait for credentials and storage before testing the browser.
4. Confirm ESO readiness, pod rollout, Route admission, and EgressFirewall status. Sign in through both login layers and start a fresh chat. Do not run the OpenClaw migration/import command.

```bash
oc get cronjob,jobs -n hermes-maas
oc logs -n hermes-maas -l app=maas-key-rotator --tail=20
oc get secret maas-workspace-key -n hermes-maas
oc get maasauthpolicy,maassubscription hermes -n models-as-a-service
oc get clustersecretstore hermes-maas
oc get externalsecret,pvc,pods,route,egressfirewall -n hermes
oc rollout status deployment/hermes -n hermes
oc logs deployment/hermes -n hermes -c dashboard --tail=50
```

After deployment, verify a short MaaS response, a harmless workspace file write/read, skill creation, memory recall in a new chat, and browser reconnection. Check the Skills Hub and OAuth flows through the deployed egress rules. Verify OpenClaw still works independently. Persistence across a GitOps-driven restart and adoption of a rotated key also require deployed resources. Do not create test Jobs or apply uncommitted manifests to perform these checks.

## Local validation

```bash
kustomize build kubernetes/ocp-mgmt/applications/hermes > /tmp/hermes-rendered.yaml
kustomize build kubernetes/ocp-mgmt/system/redhat-ods-operator/maas > /tmp/hermes-maas-rendered.yaml
python -B -m unittest discover -s kubernetes/ocp-mgmt/applications/hermes -p 'test_*.py'
python -B -m unittest discover -s kubernetes/ocp-mgmt/system/redhat-ods-operator/maas/key-rotation/runtime -p 'test_*.py'
git diff --check
```

The tests cover credential rotation, transient projection failures, exit propagation, and state migration/preservation, including interrupted moves and conflict rejection. Local image tests must include `profile=default` on the browser PTY request and a volume root owned by a different UID: an unscoped chat on a user-owned volume does not exercise the gateway bootstrap ownership checks. Cluster OAuth, actual model responses, storage placement, and egress policy behavior require the GitOps rollout.

## References

- [Hermes v0.22.5](https://github.com/NousResearch/hermes-agent/releases/tag/v0.22.5)
- [Dashboard authentication and reverse-proxy configuration](https://github.com/NousResearch/hermes-agent/blob/v0.22.5/website/docs/user-guide/features/web-dashboard.md)
- [Official container build](https://github.com/NousResearch/hermes-agent/blob/v0.22.5/Dockerfile)
- [MaaS access and rotation](../../system/redhat-ods-operator/maas/README.md#hermes-access)
