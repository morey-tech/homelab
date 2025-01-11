# Ansible: Rubrik
Run `ansible` commands from in the `ansible/ms` folder to ensure that the `ansible.cfg` is used.

```
cd ansible/ms
```

## Initial Configuration
Ensure the authentication to the hosts has been configured to use ssh keys. (replace `<nn>` with the node number, `01`)
```
ssh-copy-id root@ms-<nn>.home.morey.tech
```

Confirm with the `ping` module.
```bash
ansible -m ping all
```

```
ms-<nn>.home.morey.tech | SUCCESS => {
    "ansible_facts": {
        "discovered_interpreter_python": "/usr/bin/python3"
    },
    "changed": false,
    "ping": "pong"
}
```

## Updating Nodes
