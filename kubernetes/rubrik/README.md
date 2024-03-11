# Environment: Rubrik
The Rubrik environment is made up of the 4 nodes in the recomissioned Rubrik SuperMicro chassis.

## MaaS
Deploy Ubuntu to the machines in MaaS.

## Ansible
Run `ansible` commands from in the `anbible/` folder to ensure that the `ansible.cfg` is used.

```
cd ansible
```

Test connectivity to the hosts:
```
ansible -m ping rubrik-*
```

Run the Ansible playbook for the `rubrik` environment:
```
ansible-playbook rubrik.yaml
```

:::info
For testing on a limited subset of hosts in an environment, use `-l <host-fqdn>`.
```
ansible-playbook rubrik.yml -l rubrik-[abd].maas.home.morey.tech
```
:::

After running the playbook, generate a cluster join command on the "primary" node (default `rubrik-a`) for each additional node:
```
ansible rubrik-a.maas.home.morey.tech -a "microk8s add-node"
```

Copy the generated `microk8s join` command in the output and run it on the other host to join it to the cluster:
```
ansible rubrik-<n>.maas.home.morey.tech -a "microk8s join 192.168.3.17:25000/xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx/xxxxxxxxxx" 
```

Confirm that the nodes are clustered together:
```
ansible rubrik-a.maas.home.morey.tech -a "microk8s status"
```

The expect status is:
```
microk8s is running
high-availability: yes
  datastore master nodes: 192.168.3.xx:19001 192.168.3.xx:19001 192.168.3.xx:19001
  datastore standby nodes: none
```

### Reset Microk8s to a fresh install
```
ansible rubrik-[abcd]* -a "microk8s leave" -b
ansible rubrik-[abcd]* -a "microk8s reset" -b
```

## How to bootstrap the cluster
After running the ansible script in `ansible/` for the `rubrik` environment, set the kube config.
```
# starting in ansible/
cd ../kubernetes/rubrik
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

```
kubectl create namespace external-secrets-system
kustomize build system/external-secrets/ --enable-helm | kubectl apply -f -
```

To bootstrap the cluster, the `bitwarden-cli` Secret used by ESO needs to be created manually. The contents of which can be found in the Notes section of the `rubrik.lab.home.morey.tech external-secrets bitwarden` entry in `n*******s@morey.tech` Bitwarden account. Copy the contents to `system/external-secrets/bitwarden-secret.yaml`, then apply it to the cluster:
```
kubectl apply -n external-secrets-system -f system/external-secrets/bitwarden-secret.yaml
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