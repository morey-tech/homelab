# morey-tech/homelab
## kubernetes/ocp-mgmt
### Login
```
oc login -u admin --server=https://api.ocp-mgmt.rh-lab.morey.tech:6443
```

### Set Up HTPasswd Auth
Create HTPasswd file with `admin` user.
```
htpasswd -B -c ocp-mgmt.htpasswd admin
# enter password
```

Create secret with HTPasswd contents.
```
oc create secret generic htpass-secret --from-file=htpasswd=ocp-mgmt.htpasswd -n openshift-config
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