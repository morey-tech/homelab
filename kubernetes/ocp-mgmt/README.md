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
# Enter password from Bitwarden.
```

Create secret with HTPasswd contents.
```
oc create secret generic htpass-secret --from-file=htpasswd=ocp-mgmt.htpasswd -n openshift-config
```

Add htpasswd identity provider and cluster role binding for admin user.
```
oc apply -f ./system/htpass-admin
```
