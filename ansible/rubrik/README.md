# Ansible: Rubrik
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
ansible-playbook rubrik.yml
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

## Reset Microk8s to a fresh install
```
ansible rubrik-[abcd]* -a "microk8s leave" -b
ansible rubrik-[abcd]* -a "microk8s reset" -b
```