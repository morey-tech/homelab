# Ansible

## Renovate PR Workflow

Renovate creates PRs for Ansible Galaxy collection updates in `requirements.yml`. Follow this workflow to test and merge them safely.

### 1. Review Breaking Changes

Check the PR description for release notes and breaking changes:

```bash
gh pr view <PR_NUMBER> --json body -q .body
```

Key things to check:
- **Version requirements** (e.g., pfSense 2.8.0+ for pfsensible.core 0.7.0+)
- **Removed/relocated modules** (e.g., Proxmox modules moved to community.proxmox in community.general 11.0.0)
- **Behavior changes** in modules you use

### 2. Identify Used Modules

Find which modules from the collection are used in playbooks:

```bash
grep -r "collection_name\." ansible/ --include="*.yml"
```

### 3. Checkout and Rebase

```bash
gh pr checkout <PR_NUMBER>
git fetch origin main && git rebase origin/main
```

Rebasing ensures the PR includes any recent changes to main.

### 4. Install Updated Collections

```bash
cd ansible
ansible-galaxy collection install -r requirements.yml --force
```

### 5. Test Playbooks

Run syntax checks on affected playbooks:

```bash
ansible-playbook --syntax-check <playbook>.yml
```

Run actual playbooks to test functionality:

```bash
ansible-playbook <playbook>.yml
```

### 6. Comment and Merge

Add testing results to the PR:

```bash
gh pr comment <PR_NUMBER> --body "## Testing Results
- Environment: <versions>
- Tested: <playbooks>
- Results: <pass/fail details>"
```

Push rebased branch and merge:

```bash
git push --force-with-lease
gh pr merge <PR_NUMBER> --squash --delete-branch
```

### Handling Breaking Changes

For major changes like module relocations:

1. Add new collection to `requirements.yml`
2. Update module FQCNs in all playbooks (e.g., `community.general.proxmox` → `community.proxmox.proxmox`)
3. Run syntax checks on all modified files
4. Test with actual playbook execution
5. Commit fixes to the PR branch before merging

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