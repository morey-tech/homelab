# morey-tech/homelab

## Ansible
Run `ansible` commands from in the `anbible/` folder to ensure that the `ansible.cfg` is used.

```
cd ansible
```

Each Evironment get's a playbook, so to provision an environment run:

```
ansible-playbook <name>.yaml
```

For example:
```
ansible-playbook kind-personal.yaml
```

For testing on a limited subset of hosts in an environment, use `-l <host-fqdn>`.
```
ansible-playbook kind-personal.yml -l rubrik-a.lab.home.morey.tech
```