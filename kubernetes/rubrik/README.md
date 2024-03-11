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

To bootstrap the cluster, the `bitwarden-cli` Secret used by ESO needs to be created manually. The contents of which can be found in the Notes section of the `rubrik.lab.home.morey.tech external-secrets bitwarden` entry in `n*******s@morey.tech` Bitwarden account. Copy the contents to `system/external-secrets/bitwarden-secret.yaml`, then apply it to the cluster:

```
kubectl create namespace external-secrets-system
kubectl apply -n external-secrets-system -f system/external-secrets/bitwarden-secret.yaml
kustomize build system/external-secrets/ --enable-helm | kubectl apply -f -
```

### Argo CD
Render the manifests for `argo-cd`  with kustomize, and apply them to the cluster.
```
kubectl apply -k system/argo-cd/
kubectl wait deployment -n argocd --all --for=condition=Available=True --timeout=90s
```

Wait for Argo CD to be ready. Then apply the configuration for Argo CD (e.g. the Applications, ApplicationSets, AppProjects).
```
kubectl apply -f bootstrap/
```

## Connecting to Argo CD
In the event that the `argocd.` ingress is not working correctly, port-forward the `argocd-server` Service.
```
kubectl port-forward svc/argocd-server -n argocd 8080:443
```

Navigate to [argocd.rubrik.lab.home.morey.tech](https://argocd.rubrik.lab.home.morey.tech).

Get the generated admin password with:
```
argocd admin initial-password --kubeconfig kubeconfig.yml -n argocd
```