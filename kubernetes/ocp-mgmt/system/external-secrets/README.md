# External Secrets

External Secrets Operator (ESO) synchronizes Kubernetes Secrets from Bitwarden using the `bitwarden-cli` service in `external-secrets-system`.

## Bootstrap Credentials

Copy the Notes section of the `ocp-mgmt.rh-lab.morey.tech external-secrets bitwarden` entry in Bitwarden to `kubernetes/ocp-mgmt/system/external-secrets/bitwarden-secret.yaml`. The Secret must be named `bitwarden-cli` with `BW_PASSWORD`, `BW_CLIENTID`, and `BW_CLIENTSECRET` keys. Credentials are Git-ignored and applied manually by the bootstrap script.

Run the [cluster bootstrap](../../README.md#initial-setup) from the repository root:

```bash
bash kubernetes/ocp-mgmt/bootstrap/bootstrap.sh
```

The `operator/` Kustomization installs the ESO chart and its CRDs without custom resources. The script waits for ESO's CRD and webhook readiness before applying this directory's complete Kustomization, including the Bitwarden backend and ClusterSecretStores. Argo CD subsequently manages the complete directory with server-side apply.

## Validation

```bash
oc get pods -n external-secrets-system
oc get clustersecretstores
oc logs -n external-secrets-system deployment/bitwarden-cli
```

| ClusterSecretStore | Bitwarden content |
|--------------------|------------------|
| bitwarden-login | Login username/password properties |
| bitwarden-fields | Custom fields |
| bitwarden-notes | Secure notes |

No application ExternalSecrets are created by the bootstrap; they will be added with individual workload migrations.
