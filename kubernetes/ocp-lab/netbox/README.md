# ocp-lab
## netbox
Configuration to deploy the upstream `netbox` Helm chart in a OpenShift-compatible way.

### How to Deploy

```
oc new-project netbox
oc kustomize . --enable-helm | oc apply -f
```

### How to Clean Up
```
oc delete project netbox 
```
