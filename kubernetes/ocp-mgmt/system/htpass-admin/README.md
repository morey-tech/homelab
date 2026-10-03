# HTPasswd Administrator Access

The bootstrap creates `htpass-secret` in `openshift-config` from the ignored `ocp-mgmt.htpasswd` file. This directory configures the HTPasswd identity provider, adds `admin` to the `cluster-admins` group, binds that group to the cluster-admin role, and identifies the cluster with a console banner.

Argo CD maps the same `cluster-admins` group to its administrator role through OpenShift OAuth. The minimal setup uses the default OpenShift login pages and requires no template synchronization Job.

From the repository root:

```bash
oc apply -k kubernetes/ocp-mgmt/system/htpass-admin
oc login -u admin --server=https://api.ocp-mgmt.rh-lab.morey.tech:6443
oc auth can-i '*' '*' --all-namespaces
```

See the [cluster bootstrap instructions](../../README.md#initial-setup) for creating the password file, recovering access, and removing kubeadmin after verifying the replacement account.
