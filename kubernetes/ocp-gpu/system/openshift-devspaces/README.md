# OpenShift DevSpaces Configuration

This directory contains the OpenShift DevSpaces configuration for the ocp-gpu cluster, including automated credential management for seamless development workflows.

## Overview

OpenShift DevSpaces provides cloud-based development environments with automatic extension installation and pre-configured credentials. This setup eliminates manual authentication steps for both GitHub and Claude Code.

## Components

### 1. CheCluster Configuration

**File:** [checluster.yaml](checluster.yaml)

Defines the core DevSpaces cluster configuration:

```yaml
spec:
  components:
    pluginRegistry:
      openVSXURL: https://open-vsx.org
  devEnvironments:
    maxNumberOfRunningWorkspacesPerCluster: -1  # Unlimited
    maxNumberOfRunningWorkspacesPerUser: -1     # Unlimited
    maxNumberOfWorkspacesPerUser: -1            # Unlimited
    storage:
      pvcStrategy: per-workspace
      perWorkspaceStrategyPvcConfig:
        claimSize: 5Gi
```

**Key features:**
- Custom plugin registry using Open VSX
- Unlimited workspaces per user and cluster
- 5Gi persistent volume per workspace

**Reference:** [Red Hat DevSpaces Administration Guide - CheCluster Custom Resource](https://docs.redhat.com/en/documentation/red_hat_openshift_dev_spaces/3.24/html/administration_guide/configuring-devspaces#checluster-custom-resource-fields-reference)

### 2. GitHub OAuth Auto-Configuration

**File:** [github-oauth.yaml](github-oauth.yaml)

ExternalSecret that automatically configures GitHub OAuth for DevSpaces:

- **Bitwarden Item UUID:** `4afc34a2-53be-4b9b-b46c-b3a70008d238`
- **Source:** ClusterSecretStore `bitwarden-login`
- **Fields:** `username` (OAuth App ID), `password` (OAuth App Secret)
- **Target Secret:** `github-oauth-config`

**Purpose:** Enables automatic GitHub authentication for all users without manual OAuth setup.

### 3. Claude Code API Key Auto-Configuration

**File:** [claude-code-api-key.yaml](claude-code-api-key.yaml)

ExternalSecret that automatically injects Anthropic API key into workspaces:

- **Bitwarden Item UUID:** `4d42580d-6663-4dd2-b7b7-b3c700295b2f`
- **Source:** ClusterSecretStore `bitwarden-login`
- **Field:** `password` (contains Anthropic API key)
- **Target Secret:** `claude-code-api-key`
- **Environment Variable:** `ANTHROPIC_API_KEY`

**Purpose:** Eliminates manual OAuth authentication for Claude Code extension. API key is automatically available in all new workspaces.

## Auto-Mounting Mechanism

### DevWorkspace Secret Injection

The Claude Code API key is automatically mounted into all DevSpaces workspaces using the DevWorkspace controller's secret injection feature.

**How it works:**

1. **Secret Discovery:** The DevWorkspace controller watches for secrets with specific labels:
   ```yaml
   metadata:
     labels:
       controller.devfile.io/mount-to-devworkspace: 'true'
       controller.devfile.io/watch-secret: 'true'
   ```

2. **Mounting Configuration:** Annotations control how the secret is mounted:
   ```yaml
   metadata:
     annotations:
       controller.devfile.io/mount-as: env  # Mount as environment variables
   ```

3. **Result:** Every new workspace automatically receives the `ANTHROPIC_API_KEY` environment variable.

**Alternative mounting options:**
- `mount-as: env` - Environment variables (current configuration)
- `mount-as: file` - Files mounted to workspace container
- `mount-as: subpath` - Files mounted as subpaths

**Reference:** [DevWorkspace Operator - Secret Management](https://github.com/devfile/devworkspace-operator/blob/main/docs/additional-configuration.adoc)

## Bitwarden Integration

### Architecture

```
ExternalSecret ──> ClusterSecretStore ──> bitwarden-cli (webhook) ──> Bitwarden Vault
     │                 (bitwarden-login)      (port 8087)
     │
     └──> Kubernetes Secret ──> DevWorkspace Controller ──> Workspace Pod
```

### Credential Storage

| Credential | Bitwarden UUID | Field | Purpose |
|------------|---------------|-------|---------|
| GitHub OAuth | `4afc34a2-53be-4b9b-b46c-b3a70008d238` | username, password | GitHub authentication |
| Claude API Key | `4d42580d-6663-4dd2-b7b7-b3c700295b2f` | password | Claude Code authentication |

### Updating Credentials

To rotate or update credentials:

1. **Update in Bitwarden:**
   - Log into Bitwarden web vault
   - Locate the item by UUID
   - Update the relevant field (username, password)
   - Save changes

2. **Sync bitwarden-cli:**
   ```bash
   # Unlock and get session token
   SESSION=$(oc exec -n external-secrets-system deployment/bitwarden-cli -- \
     bw unlock --passwordenv BW_PASSWORD --raw)

   # Sync latest changes
   oc exec -n external-secrets-system deployment/bitwarden-cli -- \
     bw sync --session "$SESSION"
   ```

3. **Force ExternalSecret refresh:**
   ```bash
   # Delete secret to force recreation
   oc delete secret -n openshift-devspaces claude-code-api-key

   # ExternalSecrets Operator will recreate it automatically
   ```

4. **Restart existing workspaces:**
   - Existing workspaces need to be restarted to pick up the new secret
   - New workspaces will automatically get the updated credentials

**Note:** For detailed Bitwarden CLI usage, see [kubernetes/ocp-gpu/system/external-secrets/README.md](../external-secrets/README.md)

## Verification & Testing

### Verify ExternalSecret Sync Status

After ArgoCD syncs the manifests, verify the ExternalSecrets are working:

```bash
# Check ExternalSecret resource exists
oc get externalsecret -n openshift-devspaces

# Check sync status for Claude API key
oc describe externalsecret -n openshift-devspaces claude-code-api-key

# Verify Kubernetes secret was created
oc get secret -n openshift-devspaces claude-code-api-key

# Check secret has correct labels
oc get secret -n openshift-devspaces claude-code-api-key -o yaml | grep -A5 labels
```

**Expected output:**
- ExternalSecret status: `SecretSynced`
- Condition: `Ready=True`
- Secret contains `ANTHROPIC_API_KEY` key
- Labels include `controller.devfile.io/mount-to-devworkspace: 'true'`

### Test in New Workspace

1. **Create workspace:**
   - Navigate to DevSpaces dashboard (ocp-gpu cluster)
   - Create new workspace from repository
   - Wait for workspace to start

2. **Verify environment variable:**
   ```bash
   # In workspace terminal
   echo $ANTHROPIC_API_KEY
   env | grep ANTHROPIC
   ```

3. **Verify Claude Code authentication:**
   - Open Claude Code extension
   - Should show as authenticated (no OAuth prompt)
   - Test functionality by asking Claude a question
   - Should work immediately without manual authentication

4. **Test persistence:**
   - Stop and restart the workspace
   - Verify `ANTHROPIC_API_KEY` is still present
   - Verify Claude Code remains authenticated

## Troubleshooting

### ExternalSecret Not Syncing

**Symptoms:** Secret not created or outdated

**Check:**
```bash
# View ExternalSecret events
oc describe externalsecret -n openshift-devspaces claude-code-api-key

# Check External Secrets Operator logs
oc logs -n external-secrets-system deployment/external-secrets -f

# Verify bitwarden-cli is running
oc get pods -n external-secrets-system | grep bitwarden-cli
```

**Common causes:**
- Bitwarden item UUID incorrect or doesn't exist
- bitwarden-cli pod not running or not authenticated
- ClusterSecretStore misconfigured
- Network issues between External Secrets Operator and bitwarden-cli

### Environment Variable Not in Workspace

**Symptoms:** `ANTHROPIC_API_KEY` not present in workspace terminal

**Check:**
```bash
# Verify secret has correct labels
oc get secret -n openshift-devspaces claude-code-api-key -o yaml

# Check DevWorkspace controller logs
oc logs -n openshift-devspaces deployment/devspaces-dashboard -f

# Verify workspace pod has the secret mounted
oc describe pod -n <user-workspace-namespace> <workspace-pod-name>
```

**Common causes:**
- Secret missing required labels/annotations
- Workspace created before secret was synced (restart workspace)
- DevWorkspace controller not watching the secret namespace

### Claude Code Still Prompts for Authentication

**Symptoms:** Claude Code extension asks for OAuth despite environment variable present

**Check:**
```bash
# Verify API key is not empty
echo $ANTHROPIC_API_KEY | wc -c  # Should be > 1

# Check extension logs in VS Code
# View > Output > Select "Claude Code" from dropdown
```

**Common causes:**
- API key is empty or invalid
- Wrong Bitwarden field referenced (should be `password`)
- API key expired or revoked in Anthropic account
- Extension version doesn't support `ANTHROPIC_API_KEY` env var

## Deployment via ArgoCD

This configuration is deployed automatically via ArgoCD ApplicationSet:

**ApplicationSet:** [kubernetes/ocp-gpu/openshift-gitops-config/system-appset.yaml](../../openshift-gitops-config/system-appset.yaml)

**Deployment flow:**
1. Changes committed to git repository
2. ArgoCD detects changes automatically
3. ApplicationSet syncs `openshift-devspaces` resources
4. ExternalSecrets Operator syncs secrets from Bitwarden
5. DevWorkspace controller mounts secrets into new workspaces

**Manual sync (if needed):**
```bash
# Check application status
oc get application -n openshift-gitops | grep devspaces

# Force sync
oc patch application -n openshift-gitops <app-name> --type merge -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}'
```

## Related Documentation

### Red Hat DevSpaces
- [Administration Guide](https://docs.redhat.com/en/documentation/red_hat_openshift_dev_spaces/3.24/html/administration_guide/)
- [CheCluster Custom Resource Reference](https://docs.redhat.com/en/documentation/red_hat_openshift_dev_spaces/3.24/html/administration_guide/configuring-devspaces#checluster-custom-resource-fields-reference)

### External Secrets Operator
- [External Secrets Documentation](https://external-secrets.io/latest/)
- [Bitwarden Provider](https://external-secrets.io/latest/provider/bitwarden/)
- [Local setup documentation](../external-secrets/README.md)

### DevWorkspace Operator
- [GitHub Repository](https://github.com/devfile/devworkspace-operator)
- [Additional Configuration](https://github.com/devfile/devworkspace-operator/blob/main/docs/additional-configuration.adoc)
- [Secret Management](https://github.com/devfile/devworkspace-operator/blob/main/docs/additional-configuration.adoc#mounting-secrets)

### Claude Code
- [Claude Code Documentation](https://docs.anthropic.com/claude-code/)
- [API Key Authentication](https://docs.anthropic.com/claude/docs/authentication)

## Security Notes

- **API Key Storage:** Anthropic API key stored in Bitwarden, never committed to git
- **Access Control:** ExternalSecrets Operator has read-only access to Bitwarden via webhook
- **Secret Rotation:** Update credentials in Bitwarden, sync bitwarden-cli, force secret refresh
- **Audit:** All secret access logged by External Secrets Operator
- **Blast Radius:** API key scoped to ocp-gpu DevSpaces namespace only

## Maintenance

### Regular Tasks

- **Monitor secret sync:** Check ExternalSecret status regularly
  ```bash
  oc get externalsecret -n openshift-devspaces -w
  ```

- **Review API usage:** Monitor Anthropic API usage for anomalies
  - Check Anthropic dashboard for unexpected usage patterns
  - Review workspace creation logs if costs spike

- **Update API key:** Rotate credentials periodically (e.g., every 90 days)
  - Update in Bitwarden
  - Sync bitwarden-cli
  - Force secret refresh
  - Restart active workspaces

### Known Limitations

- **Existing workspaces:** Must be restarted to pick up secret changes
- **API key scope:** Single shared API key for all users (no per-user keys)
- **Rate limiting:** Shared API key means shared rate limits across all users
- **Cost tracking:** Cannot attribute API usage to individual users

## Architecture Decision: API Token vs OAuth

**Chosen approach:** Long-lived API token

**Alternative:** OAuth with refresh token rotation

**Rationale:**
- **Zero maintenance:** API tokens don't expire (vs OAuth tokens requiring periodic re-authentication)
- **Simpler setup:** Single secret vs complex OAuth flow and token storage
- **Lower complexity:** No CronJob needed for token renewal
- **Trade-off:** Shared API key means shared rate limits and costs

**For high-security or multi-tenant environments, consider:**
- Per-user API keys (requires custom solution)
- OAuth with automated refresh token renewal (requires CronJob)
- Anthropic organization keys with usage tracking
