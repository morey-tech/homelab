# Ansible: Rubrik
Run `ansible` commands from in the `ansible/ms` folder to ensure that the `ansible.cfg` is used.

```
cd ansible/ms
```

## Ansible Vault
Take the password from the `Ansible ms Vault Password` entry in Bitwarden and place it in the `vault-password.txt` file.

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

## Setting Up Proxmox API Permisssions
Create a new user named `ansible` with the Realm `Proxmox VE` on the Proxmox datacenter.
- https://ms-02.home.morey.tech:8006/#v1:0:18:4:31::::::14

Assign `PVEAdmin` role and path `/` to the `ansible@pve` user and the `ansible@pve!ansible` token.
- https://ms-02.home.morey.tech:8006/#v1:0:18:4:31::::::6

Create an API token with the Token ID `ansible`.
- https://ms-02.home.morey.tech:8006/#v1:0:18:4:31::::::=apitokens

## Upgrading Nodes
```
ansible-playbook upgrade.yml
```