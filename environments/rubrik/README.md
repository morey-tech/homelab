# Environment: Rubrik
The Rubrik environment is made up of the 4 nodes in the recomissioned Rubrik SuperMicro chassis.

## How to bootstrap the cluster:
Optionally, after running the ansible script in `ansible/` for the `rubrik` environment, set the kube config.
```
export KUBECONFIG=kubeconfig.yml
```

From the `environments/rubrik` folder, render the manifests for `argo-cd`  with kustomize, and apply them to the cluster.
```
kubectl kustomize ./bootstrap/argo-cd/ | kubectl --kubeconfig kubeconfig.yml apply -f -
```

If the CRDs aren't registered quickly enough, you may see the following error. Simply re-run the command.
```
resource mapping not found for name: "argo-cd" namespace: "argocd" from "STDIN": no matches for kind "Application" in version "argoproj.io/v1alpha1"
ensure CRDs are installed first
resource mapping not found for name: "cluster-services" namespace: "argocd" from "STDIN": no matches for kind "ApplicationSet" in version "argoproj.io/v1alpha1"
ensure CRDs are installed first
``` 

## Connecting to Argo CD
```
kubectl port-forward svc/argocd-server -n argocd 8080:443
```

If running in a dev container, VS code should automatically set up the forward from the container to your workstation.

Then, go to [https://127.0.0.1:8080/](https://127.0.0.1:8080).

Get the generated admin password with:
```
argocd admin initial-password --kubeconfig kubeconfig.yml -n argocd
```