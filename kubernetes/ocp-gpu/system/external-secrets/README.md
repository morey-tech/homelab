# External Secrets
External Secrets Operator (ESO) is used to populate Kubernetes Secrets in the cluster with secrets stored in Bitwarden.

To bootstrap the cluster, the `bitwarden-cli` Secret used by ESO needs to be created manually.

1. Copy the contents of the Notes section of the `ocp-gpu.rh-lab.morey.tech external-secrets bitwarden` entry in `n*******s@morey.tech` Bitwarden account.
2. Create the `system/external-secrets/bitwarden-secret.yaml` file and paste the contents of the Notes section from Bitwarden.

Then create the namesapce, apply the secret and kustomization to the cluster:
```
oc create namespace external-secrets-system
oc apply -n external-secrets-system -f system/external-secrets/bitwarden-secret.yaml
oc kustomize build system/external-secrets/ --enable-helm | kubectl apply -f -
```

## Working with Bitwarden CLI

### Unlocking and Using Session Tokens

The bitwarden-cli pod has credentials stored as environment variables. To use the CLI:

1. Unlock and get session token:
```bash
oc exec -n external-secrets-system deployment/bitwarden-cli -- \
  bw unlock --passwordenv BW_PASSWORD
```

2. Use the session token for commands:
```bash
# Replace <SESSION_TOKEN> with the token from unlock command
oc exec -n external-secrets-system deployment/bitwarden-cli -- \
  bw list items --session "<SESSION_TOKEN>"
```

### Syncing After Changes

After creating or modifying items in Bitwarden, sync to the CLI:

```bash
oc exec -n external-secrets-system deployment/bitwarden-cli -- \
  bw sync --session "<SESSION_TOKEN>"
```

### Getting Bitwarden Item UUIDs

When creating new ExternalSecrets, you need the UUID of the Bitwarden item:

```bash
# Search by name
oc exec -n external-secrets-system deployment/bitwarden-cli -- \
  bw get item "Item Name" --session "<SESSION_TOKEN>" | jq -r '.id'

# List all items
oc exec -n external-secrets-system deployment/bitwarden-cli -- \
  bw list items --session "<SESSION_TOKEN>" | jq -r '.[] | {id: .id, name: .name}'
```

The UUID is the value you use in `remoteRef.key` field of your ExternalSecret resource.
