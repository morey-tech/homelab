# Environment: Rubrik
The Rubrik environment is made up of the 4 nodes in the recomissioned Rubrik SuperMicro chassis.

## Ansible
Run `ansible` commands from in the `anbible/` folder to ensure that the `ansible.cfg` is used.

```
cd ansible
```

Run the Ansible playbook for the `rubrik` environment:
```
ansible-playbook rubik.yaml
```

For testing on a limited subset of hosts in an environment, use `-l <host-fqdn>`.
```
ansible-playbook rubrik.yml -l rubrik-[abd].lab.home.morey.tech
```

After running the playbook, generate a cluster join command on the "primary" node (default `rubrik-a`) for each additional node:
```
ansible rubrik-a.maas.home.morey.tech -a "microk8s add-node"
```

Copy the generated `microk8s join` command in the output and run it on the other host to join it to the cluster:
```
ansible rubrik-<n>.maas.home.morey.tech -a "microk8s join 192.168.3.17:25000/xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx/xxxxxxxxxx" 
```

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