# HTPasswd Admin - Login Templates

This directory manages custom OAuth login page templates for the OpenShift cluster.

## How It Works

1. **HTML Templates**: Edit `login.html` and `providers.html` to customize the login pages
2. **ConfigMap Generation**: Kustomize generates a ConfigMap from the HTML files with a content-based hash suffix
3. **Secret Sync**: An ArgoCD PostSync hook Job converts the ConfigMap to Secrets in `openshift-config` namespace
4. **OAuth Update**: The OAuth controller automatically detects secret changes and updates the login pages

## Files

| File | Purpose |
|------|---------|
| `login.html` | Main login form template |
| `providers.html` | Identity provider selection template |
| `kustomization.yaml` | Kustomize config with configMapGenerator |
| `login-template-sync.yaml` | ArgoCD PostSync Job to sync secrets |

## Making Changes

1. Edit `login.html` or `providers.html`
2. Commit and push changes
3. ArgoCD will sync automatically:
   - Creates new ConfigMap with updated hash
   - PostSync Job creates/updates Secrets
   - OAuth controller picks up changes

## Manual Sync

If needed, you can manually trigger an ArgoCD sync:
```bash
argocd app sync <app-name>
```

## Troubleshooting

Check Job logs:
```bash
kubectl logs -n openshift-config -l job-name=login-template-sync
```

Verify secrets exist:
```bash
kubectl get secret -n openshift-config login-template providers-template
```
