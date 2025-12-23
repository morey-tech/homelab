# Ansible
## Lab

## Rubrik
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
- https://ms-04.home.morey.tech:8006/#v1:0:18:4:31::::::14

Assign `PVEAdmin` role and path `/` to the `ansible@pve` user and the `ansible@pve!ansible` token.
- https://ms-04.home.morey.tech:8006/#v1:0:18:4:31::::::6

Create an API token with the Token ID `ansible`.
- https://ms-04.home.morey.tech:8006/#v1:0:18:4:31::::::=apitokens

## Upgrading Nodes
```
ansible-playbook upgrade.yml
```

## UniFi Network Controller

The UniFi Network Controller runs on an LXC container on the LAN network.

- **Web UI**: https://192.168.1.13:8443
- **Inform URL**: http://192.168.1.13:8080/inform

### Create/Destroy
```bash
ansible-playbook lan-unifi-create.yml
ansible-playbook lan-unifi-destroy.yml
```

### Adopting Devices

To connect a device to the controller, SSH into it and run the `set-inform` command (credentials for provisioned devices are `root` / `server` in Bitwarden):

```bash
ssh root@<device-ip>

set-inform http://192.168.1.13:8080/inform
```

Note: It may take 2-3 tries before the device is picked up.