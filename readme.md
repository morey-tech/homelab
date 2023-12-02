# Homelab

## Ansible

```
ansible-playbook kind-personal.yml -t <action>
```
actions:
- `template` - Add cluster config to host.
- `create` - Create the cluster, when one doesn't exist.
- `recreate