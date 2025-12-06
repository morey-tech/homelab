# HAProxy on pfSense Ansible Playbook Plan

## Status: PENDING USER INPUT

## Objective
Create an Ansible playbook to configure HAProxy on pfSense with:
- Frontend for `rubrik.lab.home.morey.tech` (domain TBC)
- TCP mode for SSL passthrough
- SNI-based ACL routing
- Backend pointing to MetalLB IP for Rubrik cluster

---

## Research Findings

### Existing Infrastructure

| Component | Value |
|-----------|-------|
| pfSense Host | `pfsense.home.morey.tech` |
| Ansible User | `admin` |
| Ansible Directory | `/workspaces/homelab/ansible/` |
| Inventory File | `ansible/inventory/hosts.yml` |
| Requirements File | `ansible/requirements.yml` |

### Current Ansible Collections
- `community.general` v10.5.0
- `rhpds.assisted_installer` v0.0.2 (from git)
- `pfsensible.core` v0.6.2

### MetalLB IPs Available (Rubrik Cluster)

| Service | IP | Ports | Location |
|---------|-----|-------|----------|
| ingress-nginx-internal | 10.8.0.1 | 80, 443, 8883 | kubernetes/rubrik/system/ingress-nginx-internal/ |
| ingress-nginx-external | 10.8.0.2 | 80, 443 | kubernetes/rubrik/system/ingress-nginx-external/ |
| k8s-gateway (DNS) | 10.8.0.0 | 53 | kubernetes/rubrik/system/k8s-gateway/ |

### K8s-Gateway Domain Configuration
Domains handled: `morey.tech`, `home.morey.tech`, `lab.home.morey.tech`, `rubrik.lab.home.morey.tech`

---

## Critical Issue: pfsensible.haproxy Collection Limitations

The [pfsensible/haproxy](https://github.com/pfsensible/haproxy) collection only provides **2 modules**:

| Module | Purpose |
|--------|---------|
| `pfsense_haproxy_backend` | Backend configuration (balance, timeouts, health checks) |
| `pfsense_haproxy_backend_server` | Backend server management |

### What's Missing (NO FRONTEND MODULE)
- Frontend listener configuration
- TCP mode settings
- SSL passthrough configuration
- SNI-based ACL routing

### Available Parameters for pfsense_haproxy_backend
- `name` (required) - Backend identifier
- `balance` - Load balancing algorithm (none, roundrobin, static-rr, leastconn, source, uri)
- `connection_timeout` - Connection timeout in ms (default 30000)
- `server_timeout` - Server response timeout in ms (default 30000)
- `retries` - Retry attempts
- `check_type` - Health check method (none, Basic, HTTP, Agent, LDAP, MySQL, PostgreSQL, Redis, SMTP, ESMTP, SSL)
- `check_frequency` - Health check interval in ms
- `state` - present or absent

---

## Questions Pending User Response

1. **Domain Confirmation**: Is `rubrik.lab.home.morey.tech` the correct domain?

2. **Backend IP**: Which MetalLB IP should be the backend?
   - `10.8.0.1` (internal ingress)
   - `10.8.0.2` (external ingress)

3. **Frontend Configuration Approach**:
   - **Option A**: Ansible for backends only + manual frontend setup in pfSense UI
   - **Option B**: Use `pfsense_phpshell`/`pfsense_shellcmd` for XML manipulation (complex, less maintainable)
   - **Option C**: Use existing NGINX reverse-proxy at `reverse-proxy.lab.morey.tech` instead of HAProxy

4. **Future Domains**: Will more SNI-routed domains be added later?

---

## Existing Patterns in Codebase

### pfSense Task Delegation Pattern
```yaml
- name: Configure pfSense
  pfsensible.core.pfsense_dhcp_static:
    netif: "{{ pfsense_int }}"
    hostname: "{{ inventory_hostname_short }}"
    # ...
  delegate_to: pfsense.home.morey.tech
```

### Existing Reverse Proxy (NGINX)
Location: `ansible/templates/nginx-reverse-proxy.conf.j2`

Already has SSL passthrough with SNI:
```nginx
stream {
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

---

## Proposed Implementation (Pending Decisions)

### File Structure
```
ansible/
├── requirements.yml              # Add pfsensible.haproxy
├── pfsense-haproxy.yml          # New playbook
└── templates/
    └── haproxy-frontend.md      # Manual setup documentation (if Option A)
```

### Requirements.yml Addition
```yaml
- name: pfsensible.haproxy
  version: "latest"  # Check for latest version
```

---

## Next Steps
1. User to answer clarifying questions above
2. Finalize approach based on frontend module limitation
3. Create detailed implementation plan
4. Implement playbook

---
*Plan created: 2025-12-06*
*Status: Awaiting user input on critical decisions*
