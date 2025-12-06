# HAProxy on pfSense - Research Context

*Captured: 2025-12-06*

This document contains detailed research findings gathered during planning.

---

## 1. Ansible Infrastructure Analysis

### Directory Structure
```
ansible/
├── ansible.cfg                    # Main config (inventory, roles_path, vault)
├── requirements.yml               # Collection dependencies
├── inventory/
│   └── hosts.yml                  # 326 lines, all hosts and groups
├── group_vars/
│   └── all.yml                    # Global vars (vaulted secrets)
├── roles/
│   ├── ms_create_vm/
│   ├── ms_delete_vm/
│   ├── pve_create_vm/
│   ├── pve_create_vm_from_cloudinit_template/
│   └── nginx_openshift_lb/
├── templates/
│   ├── nginx-reverse-proxy.conf.j2
│   ├── config.alloy.j2
│   ├── db.j2
│   └── named.conf.options.j2
└── [20+ playbooks]
```

### Ansible.cfg Settings
```ini
inventory = ./inventory/hosts.yml
roles_path = ./roles
vault_password_file = vault-password.txt
host_key_checking = False
interpreter_python = auto_silent
```

### pfSense in Inventory (hosts.yml)
```yaml
pfsense.home.morey.tech:
  ansible_user: admin
```

### Network Interfaces in pfSense
- `opt1` - Lab network (192.168.3.0/24, VLAN 3)
- `opt3` - RH Lab network (192.168.6.0/24, VLAN 6)

---

## 2. Rubrik Cluster Kubernetes Manifests

### MetalLB Configuration
**File**: `kubernetes/rubrik/system/metallb/config.yaml`

#### Address Pools
- `rubrik-static-address-pool`: 10.8.0.0/16 (manual assignment)
- `rubrik-dynamic-address-pool`: 10.9.0.0/16 (auto-assignment)

#### IP Allocation Map
| IP | Service |
|----|---------|
| 10.8.0.0 | k8s-gateway (DNS) |
| 10.8.0.1 | ingress-nginx-internal |
| 10.8.0.2 | ingress-nginx-external |
| 10.8.0.3 | plex |
| 10.8.0.4 | unifi |
| 10.8.0.5 | home-assistant-lb-tcp/udp |

#### BGP Configuration
```yaml
apiVersion: metallb.io/v1beta2
kind: BGPPeer
metadata:
  name: pfsense-peer
spec:
  myASN: 64501
  peerASN: 64500        # pfSense ASN
  peerAddress: 192.168.3.1  # pfSense gateway
```

### Ingress NGINX Internal
**File**: `kubernetes/rubrik/system/ingress-nginx-internal/ingress-nginx-metalb.yaml`
- Service: `ingress-nginx-internal-metallb`
- IP: `10.8.0.1`
- Ports: 80 (HTTP), 443 (HTTPS), 8883 (MQTTS)

### Ingress NGINX External
**File**: `kubernetes/rubrik/system/ingress-nginx-external/ingress-nginx-metalb.yaml`
- Service: `ingress-nginx-external-metallb`
- IP: `10.8.0.2`
- Ports: 80 (HTTP), 443 (HTTPS)

### K8s-Gateway
**File**: `kubernetes/rubrik/system/k8s-gateway/kustomization.yaml`
- IP: `10.8.0.0`
- Domains: `morey.tech`, `home.morey.tech`, `lab.home.morey.tech`, `rubrik.lab.home.morey.tech`

---

## 3. pfsensible Collection Analysis

### pfsensible.core (v0.6.2) - 47 Modules
Key modules:
- `pfsense_dhcp_static` - DHCP static mappings
- `pfsense_rule` - Firewall rules
- `pfsense_nat_port_forward` - NAT port forwarding
- `pfsense_haproxy_backend` - HAProxy backends
- `pfsense_haproxy_backend_server` - HAProxy backend servers
- `pfsense_shellcmd` - Shell command execution
- `pfsense_phpshell` - PHP code execution

### pfsensible.haproxy - 2 Modules Only

#### pfsense_haproxy_backend
Parameters:
- `name` (required) - Backend identifier
- `balance` - Algorithm: none, roundrobin, static-rr, leastconn, source, uri
- `balance_urilen`, `balance_uridepth`, `balance_uriwhole` - URI options
- `connection_timeout` - Connection timeout ms (default 30000)
- `server_timeout` - Server response timeout ms (default 30000)
- `retries` - Retry attempts
- `check_type` - Health check: none, Basic, HTTP, Agent, LDAP, MySQL, PostgreSQL, Redis, SMTP, ESMTP, SSL
- `check_frequency` - Check interval ms
- `log_checks` - Log health status changes
- `httpcheck_method` - HTTP method for checks
- `monitor_uri`, `monitor_httpversion`, `monitor_username`, `monitor_domain`
- `state` - present/absent

Example:
```yaml
- name: Add backend
  pfsensible.haproxy.pfsense_haproxy_backend:
    name: exchange
    balance: leastconn
    httpcheck_method: OPTIONS
    state: present
```

#### pfsense_haproxy_backend_server
(Parameters not fully documented in available sources)

### Missing Frontend Module
The collection does NOT include a module for:
- Frontend configuration
- TCP mode
- SSL passthrough
- ACL/SNI routing

---

## 4. Existing Reverse Proxy Patterns

### NGINX Reverse Proxy Template
**File**: `ansible/templates/nginx-reverse-proxy.conf.j2`

Layer 4 (stream) load balancing with SSL passthrough:
```nginx
stream {
    upstream rubrik_backend {
        server 192.168.3.20:80;
        server 192.168.3.21:80;
        server 192.168.3.22:80;
    }

    server {
        listen 80;
        proxy_pass rubrik_backend;
        proxy_ssl_server_name off;
    }

    upstream rubrik_backend_ssl {
        server 192.168.3.20:443;
        server 192.168.3.21:443;
        server 192.168.3.22:443;
    }

    server {
        listen 443;
        proxy_pass rubrik_backend_ssl;
        proxy_ssl_server_name on;  # SNI enabled
    }
}
```

### NGINX OpenShift LB Role
**File**: `ansible/roles/nginx_openshift_lb/templates/nginx.conf.j2`

Stream-based proxy for OpenShift:
```nginx
stream {
    upstream openshift_api {
        server {{ server }}:6443;
    }

    upstream openshift_https {
        server {{ server }}:443;
    }

    server {
        listen 6443;
        proxy_pass openshift_api;
    }

    server {
        listen 443;
        proxy_pass openshift_https;
    }
}
```

### Reverse Proxy LXC Container
- Name: `reverse-proxy.lab.morey.tech`
- IP: `192.168.3.103`
- VMID: 3103

---

## 5. Alternative Approaches Considered

### Option A: Partial Automation
- Use pfsensible.haproxy for backends/servers
- Document manual frontend setup for pfSense UI
- Pros: Uses official modules, maintainable
- Cons: Requires manual steps

### Option B: XML Manipulation
- Use `pfsense_phpshell` or `pfsense_shellcmd` to edit HAProxy config
- Pros: Fully automated
- Cons: Complex, fragile, hard to maintain

### Option C: NGINX Alternative
- Extend existing NGINX reverse-proxy
- Already has SNI/stream support
- Pros: Proven pattern, fully automated
- Cons: Not HAProxy (user specifically requested HAProxy)

---

## 6. Key Files Reference

| Purpose | Path |
|---------|------|
| Ansible inventory | `ansible/inventory/hosts.yml` |
| Ansible requirements | `ansible/requirements.yml` |
| Ansible config | `ansible/ansible.cfg` |
| NGINX reverse proxy template | `ansible/templates/nginx-reverse-proxy.conf.j2` |
| MetalLB config | `kubernetes/rubrik/system/metallb/config.yaml` |
| Internal ingress | `kubernetes/rubrik/system/ingress-nginx-internal/` |
| External ingress | `kubernetes/rubrik/system/ingress-nginx-external/` |
| K8s-gateway | `kubernetes/rubrik/system/k8s-gateway/` |

---

## 7. External Resources

- [pfsensible/haproxy GitHub](https://github.com/pfsensible/haproxy)
- [pfsensible/core GitHub](https://github.com/pfsensible/core)
- [pfsensible.haproxy on Ansible Galaxy](https://galaxy.ansible.com/ui/repo/published/pfsensible/haproxy/)
- [pfsensible.core on Ansible Galaxy](https://galaxy.ansible.com/ui/repo/published/pfsensible/core/)
