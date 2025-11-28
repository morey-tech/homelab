# External Secrets
External Secrets Operator (ESO) is used to populate Kubernetes Secrets in the cluster with secrets stored in Bitwarden.

To bootstrap the cluster, the `bitwarden-cli` Secret used by ESO needs to be created manually.

1. Copy the contents of the Notes section of the `ocp-mgmt.rh-lab.morey.tech external-secrets bitwarden` entry in `n*******s@morey.tech` Bitwarden account.
2. Create the `system/external-secrets/bitwarden-secret.yaml` file and paste the contents of the Notes section from Bitwarden.

Then create the namesapce, apply the secret and kustomization to the cluster:
```
oc create namespace external-secrets-system
oc apply -n external-secrets-system -f system/external-secrets/bitwarden-secret.yaml
oc kustomize build system/external-secrets/ --enable-helm | kubectl apply -f -
```
