# Kubernetes: Rubrik
The Rubrik environment is made up of the 4 nodes in the recomissioned Rubrik SuperMicro chassis.

## How to bootstrap the cluster
After running the ansible script in `ansible/` for the `rubrik` environment, set the kube config.
```
kubeconfig-set
```

:::note
`kubeconfig-set` is a bash alias for `export KUBECONFIG=kubeconfig.yaml`.
:::

Test connectivity to the Kubernetes cluster:
```
k get nodes
```

### External Secrets
External Secrets Operator (ESO) is used to populate Kubernetes Secrets in the cluster with secrets stored in Bitwarden.

To bootstrap the cluster, the `bitwarden-cli` Secret used by ESO needs to be created manually.

1. Copy the contents of the Notes section of the `rubrik.lab.home.morey.tech external-secrets bitwarden` entry in `n*******s@morey.tech` Bitwarden account.
2. Create the `system/external-secrets/bitwarden-secret.yaml` file and paste the contents of the Notes section from Bitwarden.

Then create the namesapce, apply the secret and kustomization to the cluster:
```
kubectl create namespace external-secrets-system
kubectl apply -n external-secrets-system -f system/external-secrets/bitwarden-secret.yaml
kustomize build system/external-secrets/ --enable-helm | kubectl apply -f -
```

### Argo CD
Render the manifests for `argo-cd`  with kustomize, and apply them to the cluster.
```
kubectl apply -k system/argo-cd/
```

Wait for Argo CD to be ready.
```
kubectl wait deployment -n argocd --all --for=condition=Available=True --timeout=90s
```

Then apply the configuration for Argo CD (e.g. the Applications, ApplicationSets, AppProjects).
```
kubectl apply -f bootstrap/
```

## Connecting to Argo CD
Navigate to [argocd.rubrik.lab.home.morey.tech](https://argocd.rubrik.lab.home.morey.tech).

Get the generated admin password with:
```
argocd admin initial-password --kubeconfig kubeconfig.yml -n argocd
```

Then update the root user password to the `admin (root) - vm/ct` entry in Bitwarden.


In the event that the `argocd.` ingress is not working correctly, port-forward the `argocd-server` Service.
```
kubectl port-forward svc/argocd-server -n argocd 8080:443
```