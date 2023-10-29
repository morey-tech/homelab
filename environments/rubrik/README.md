# Environment: Rubrik
The Rubrik environment is made up of the 4 nodes in the recomissioned Rubrik SuperMicro chassis.

## How to bootstrap the cluster:
From the `environments/rubrik` folder:
```
kubectl kustomize ./bootstrap/argo-cd/ | kubectl --kubeconfig kubeconfig.yml apply -f -
```