# morey-tech/homelab
## kubernetes/ocp-lab
### Login
```
oc login -u admin --server=https://api.ocp-lab.rh-lab.morey.tech:6443
```

### Set Up HTPasswd Auth
Create HTPasswd file with `admin` user.
```
htpasswd -B -c ocp-lab.htpasswd admin
# enter password from Bitwarden
```

Create secret with HTPasswd contents.
```
oc create secret generic htpass-secret --from-file=htpasswd=ocp-lab.htpasswd -n openshift-config
```

Add htpasswd identity provider.
```yaml
apiVersion: config.openshift.io/v1
kind: OAuth
metadata:
  name: cluster
spec:
  identityProviders:
    - htpasswd:
        fileData:
          name: htpass-secret
      mappingMethod: claim
      name: htpasswd
      type: HTPasswd
```

Assign admin permissions to user.
```
oc adm policy add-cluster-role-to-user cluster-admin admin
```