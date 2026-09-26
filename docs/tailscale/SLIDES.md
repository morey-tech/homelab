# Presentation: login-free cluster access with Tailscale

This is a slide-by-slide outline for presenting the solution described in [README.md](README.md). Each slide has:

- **Prompt:** paste it into Google Slides' "Help me create a slide" feature. Every prompt is self-contained and repeats the deck style, because each slide is generated on its own.
- **Speaker notes:** what to say. These aren't part of the prompt.

The deck runs about 20 minutes, plus the demo and questions.

**Tips:**
- Generated diagrams are often inaccurate. For the architecture and request-flow slides, it's more reliable to screenshot the Mermaid diagrams as rendered in [README.md](README.md) on GitHub and paste them in, and use the prompt for the layout and text only.
- For the policy workflow slide, use [acl-pr-check-comment.png](acl-pr-check-comment.png).

---

## 1. Title

**Prompt:**

```text
Create a title slide. Title: "Login-free cluster access with Tailscale". Subtitle: "Reaching one OpenShift cluster from another's Dev Spaces with the Tailscale Kubernetes operator". Add a small line at the bottom for the presenter name: "Nicholas Morey". Style: minimal, dark navy background, white text, one bright blue accent color, modern sans-serif font, no stock photos or clip art.
```

**Speaker notes:** This is a problem from my own homelab. I have two OpenShift clusters: one runs my home services, and the other runs my development environments. I wanted the dev environments to reach the home cluster without me handling any credentials, and Tailscale made that possible without a single token.

---

## 2. The problem

**Prompt:**

```text
Create a slide titled "The problem: a token paste every time". Left side: a numbered list of the old manual steps: "1. Open the ocp-home web console and log in", "2. Copy login command, log in again, display token", "3. Paste oc login --token=sha256~... into the workspace". Right side: three short pain points with small warning icons: "Lost on every workspace restart", "Expires every 24 hours", "Bearer token left in shell history and ~/.kube/config". Style: minimal, dark navy background, white text, one bright blue accent color, modern sans-serif font, no stock photos.
```

**Speaker notes:**
- Dev Spaces logs a workspace into the cluster it runs on, `ocp-gpu`, but not into `ocp-home`.
- So every time I wanted to use `ocp-home` from a workspace, I went through the console, copied a login command, and pasted a token.
- The workspace home directory isn't persistent, so a restart meant doing it all again.
- The token also expired daily, and it sat in the workspace as a plain bearer secret. Anyone who got hold of it could use my cluster.

---

## 3. The goal

**Prompt:**

```text
Create a slide titled "The goal". Show one large before-and-after code comparison. Before (greyed out): "oc login --token=sha256~... --server=https://api.ocp-home...:6443". After (highlighted in blue): "oc --context=ocp-home-tailnet get pods -A". Below it, four requirement chips in a row: "No credentials in workspaces", "Nothing to set up per workspace", "Access defined in one policy", "Everything as code". Style: minimal, dark navy background, white text, one bright blue accent color, monospace font for code, no stock photos.
```

**Speaker notes:** The goal was for every workspace to start with a working context for `ocp-home`, with nothing to log into and no secret stored anywhere in the workspace. I also wanted the access rules in one place, and everything deployed from Git so it's reviewable and reproducible.

---

## 4. Scenario and architecture

**Prompt:**

```text
Create a slide titled "Architecture: Tailscale operator on both clusters". Draw a left-to-right diagram with two large boxes. Left box labeled "ocp-gpu (Dev Spaces)" containing "Workspace" pointing to "Egress proxy (tag:ocp-gpu-devspaces)". Right box labeled "ocp-home" containing "API server proxy (tag:ocp-home-api)" pointing to "kube-apiserver". Connect the egress proxy to the API server proxy with a thick blue arrow labeled "WireGuard, TCP 443". Above both boxes, a small cloud labeled "Tailscale control plane: tags, grants, tests" with dotted lines to both proxies. Style: minimal, dark navy background, white text and outlines, one bright blue accent color, no stock photos.
```

**Speaker notes:**
- There's a Tailscale operator on each cluster, and they play opposite roles.
- On `ocp-home`, the operator runs its API server proxy in auth mode. It joins the tailnet as `ocp-home-api` and forwards requests to the real API server as the caller's Tailscale identity.
- On `ocp-gpu`, the operator runs one egress proxy. It's a single tailnet device shared by all workspaces, reachable through an ordinary Kubernetes Service.
- Workspaces don't run Tailscale at all. They get a kubeconfig with no credentials in it.

---

## 5. How identity becomes access

**Prompt:**

```text
Create a slide titled "How a Tailscale identity becomes Kubernetes permissions". Show a horizontal flow of four steps connected by arrows: "1. Workspace sends a request with no token", "2. Traffic arrives over WireGuard from device ocp-gpu-devspaces", "3. The tailnet policy grant maps that device to group tailnet-admins", "4. The API server proxy impersonates it, and RBAC binds tailnet-admins to cluster-admin". Under the flow, show a small code box with: "Username: ocp-gpu-devspaces.taile3c3a8.ts.net" and "Groups: tailnet-readers, tailnet-admins". Style: minimal, dark navy background, white text, one bright blue accent color, monospace font for code, no stock photos.
```

**Speaker notes:**
- There's no token anywhere in this flow.
- The API server proxy knows which device the connection comes from, because WireGuard keys are tied to device identity.
- A grant in the tailnet policy carries a Kubernetes capability, which says which groups that device gets.
- The proxy then calls the API server with impersonation headers, and normal OpenShift RBAC decides what those groups can do.
- TLS runs end to end: the kubeconfig uses `tls-server-name` so the certificate check matches the real tailnet hostname.

---

## 6. Tools and why

**Prompt:**

```text
Create a slide titled "Tools and why I chose them". Use a two-column table with 6 rows. Column headers: "Tool" and "Why". Rows: "Tailscale Kubernetes operator" / "API server proxy and egress proxies as Kubernetes resources"; "Argo CD, Kustomize, Helm" / "The same GitOps workflow as the rest of the homelab, with a pinned chart version"; "External Secrets and Bitwarden" / "OAuth client secrets never live in Git"; "GitHub Actions and gitops-pusher" / "Tailnet policy as code, with tests and a live diff on every PR"; "OpenShift NetworkPolicy and admission policy" / "Limit who can reach and create proxies"; "Mermaid" / "Diagrams versioned next to the code". Style: minimal, dark navy background, white text, one bright blue accent color, no stock photos.
```

**Speaker notes:** Infrastructure as code was a hard requirement. Everything in the clusters goes through Argo CD, the same way the rest of my homelab does, and secrets come from Bitwarden through External Secrets. The one thing still done by hand is the tailnet settings, meaning MagicDNS, HTTPS certificates and the OAuth clients. That's on the improvements list, to move to Terraform.

---

## 7. Tailnet policy as code

**Prompt:**

```text
Create a slide titled "Tailnet policy as code". Left side: a vertical three-step flow: "Pull request: syntax check and ACL tests", "Bot comment: test result and diff against the live policy", "Merge to main: policy applied automatically". Right side: leave a large empty image placeholder labeled "PR comment screenshot". Add a small footer note: "Upstream request: tailscale/gitops-acl-action#84". Style: minimal, dark navy background, white text, one bright blue accent color, no stock photos.
```

**Speaker notes:**
- Replace the placeholder with [acl-pr-check-comment.png](acl-pr-check-comment.png).
- Every policy change is a PR. The check runs `gitops-pusher test`, which validates the policy and runs its ACL tests. It also compares against the live policy, and a bot comment shows exactly what merging will change. This screenshot is the change that granted admin access.
- The official action doesn't expose its results as step outputs, so the PR check runs `gitops-pusher` directly for now. I opened [gitops-acl-action#84](https://github.com/tailscale/gitops-acl-action/issues/84) to ask for outputs.

---

## 8. Security in layers

**Prompt:**

```text
Create a slide titled "Security in layers". Show six stacked horizontal layers, like a layered cake, each with a short label on the left and a one-line control on the right: "Tailnet grants: only tag:ocp-gpu-devspaces gets tailnet-admins"; "Tag ownership: each operator can only use its own tags"; "RBAC on ocp-home: tailnet-admins bound to cluster-admin, everyone else view"; "NetworkPolicy on ocp-gpu: only the admin-devspaces namespace reaches the proxy"; "Admission policy: no Tailscale Services outside tailscale-system"; "SCC: privileged access only for the proxy service account". Style: minimal, dark navy background, white text, one bright blue accent color, no stock photos.
```

**Speaker notes:**
- Each layer is defined in code.
- The admission policy came from reading how the operator works: it acts on Tailscale annotations on any Service in any namespace. Without it, any namespace owner could have requested their own proxy with an operator-owned tag.
- Be honest about the trade-off: every workspace user shares one identity, so audit logs name the proxy, not the person.

---

## 9. Live demo

**Prompt:**

```text
Create a slide titled "Demo". Show a terminal-style dark code box with these commands, one per line: "oc config get-contexts", "oc --context=ocp-home-tailnet config view --minify", "oc --context=ocp-home-tailnet auth whoami", "oc --context=ocp-home-tailnet auth can-i '*' '*' -A", "oc --context=ocp-home-tailnet get nodes". Next to it, a short checklist: "No token in the kubeconfig", "Identity comes from Tailscale", "Survives workspace restarts". Style: minimal, dark navy background, white text, one bright blue accent color, monospace font for commands, no stock photos.
```

**Speaker notes:**
1. **Contexts:** in a Dev Spaces workspace on `ocp-gpu`, run `oc config get-contexts`. `logged-user` is the local cluster and the default; `ocp-home-tailnet` comes from the mounted kubeconfig.
2. **No credentials:** `config view --minify` shows the user entry is `{}`.
3. **Identity:** `auth whoami` shows the egress device's FQDN and the `tailnet-admins` group.
4. **Access:** `auth can-i '*' '*' -A` returns `yes`, and `get nodes` returns `ocp-home-01`.
5. **Optional, as code:** show [ocp-home-api.yaml](../../kubernetes/ocp-gpu/system/tailscale/ocp-home-api.yaml). One annotated Service creates the whole egress proxy.
6. **Optional, restarts:** restart the workspace and run `whoami` again.

Fallback: use screenshots of the same commands if the live environment isn't available.

---

## 10. Tailscale compared with other remote access

**Prompt:**

```text
Create a slide titled "Compared with other remote access options". Use a comparison table with 4 columns: "", "Traditional VPN", "Bastion host or public API with tokens", "Tailscale". Rows: "Access model" / "Whole network once connected" / "Anyone holding the key or token" / "Per-device identity with fine-grained grants"; "Open ports" / "VPN concentrator exposed" / "SSH or API exposed" / "None, NAT traversal"; "Credentials to manage" / "Client configs, shared keys" / "SSH keys, long-lived tokens" / "Identity provider login, device keys"; "Path" / "Hairpins through a hub" / "Hop through a jump box" / "Direct WireGuard between peers"; "Kubernetes auth" / "Still need tokens" / "Still need tokens" / "Identity mapped to RBAC groups". Highlight the Tailscale column in blue. Style: minimal, dark navy background, white text, one bright blue accent color, no stock photos.
```

**Speaker notes:** The key difference is where access decisions are made. A VPN grants access to a network, and a token grants access to whoever holds it. Tailscale grants access to specific services, based on who or what the device is, and the Kubernetes integration carries that identity all the way through to RBAC. In this project, that removed the need for a Kubernetes credential entirely.

---

## 11. Explaining it to someone new to Tailscale

**Prompt:**

```text
Create a slide titled "Explaining it without the jargon". Use three large cards side by side, each with a simple icon and two lines of text. Card 1, icon of an ID badge: "Your device is your badge" / "Every laptop, server, or pod proves who it is automatically". Card 2, icon of doors: "Badges open specific doors" / "One policy file says who can reach what, and as whom". Card 3, icon of a crossed-out key: "No keys to copy" / "Nothing to paste, rotate, or leak". Style: minimal, dark navy background, white text, one bright blue accent color, simple line icons, no stock photos.
```

**Speaker notes:** For someone who's never used Tailscale, I'd skip VPNs and tunnels and start with the badge analogy. Before, I had to go and get a temporary key every day and carry it around. Now my development environment has a badge, and the building knows which doors that badge opens. If I want to take access away, I change the list of doors or revoke the badge. There's no hunting down copied keys.

---

## 12. My experience with the product

**Prompt:**

```text
Create a slide titled "Experience with Tailscale". Two columns. Left column heading "Worked well" with bullets: "API server proxy gave token-free kubectl with one Helm value", "Grants with Kubernetes capabilities keep authorization in one place", "An egress proxy is one annotated Service", "Policy tests catch access regressions before merge". Right column heading "Friction" with bullets: "The operator image expects root; OpenShift needed a config directory workaround", "Kernel-mode egress proxies need privileged access on OpenShift", "The operator acts on Service annotations in every namespace", "The GitOps ACL action exposes no outputs for PR comments". Style: minimal, dark navy background, white text, one bright blue accent color, no stock photos.
```

**Speaker notes:**
- The core product experience was very good. Auth mode on the API server proxy did exactly what I wanted, and mapping grants to Kubernetes groups is an elegant way to keep authorization in the tailnet policy.
- Most of the friction was OpenShift-specific:
  - OpenShift's random UID means `HOME` is `/`, so I set `XDG_CONFIG_HOME` to give tsnet somewhere writable.
  - The egress proxy needs the privileged SCC.
  - I added an admission policy to control which Services the operator acts on.
- Where I hit a gap in tooling, I filed issues upstream instead of just working around it.

---

## 13. Lessons learned

**Prompt:**

```text
Create a slide titled "Lessons learned". Show five short rows, each with a bold problem and a lighter fix: "Operator expects root, OpenShift uses a random UID" / "Point XDG_CONFIG_HOME at /tmp"; "Argo CD fights the operator's changes" / "ignoreDifferences on the one field it owns"; "Dev Spaces mishandles a multi-path KUBECONFIG" / "Set it in shell init, reported as eclipse-che/che#23972"; "Tagged devices inherited allow-all access" / "Limit allow-all to user devices, add deny tests"; "Operator trusts annotations everywhere" / "Admission policy limits it to tailscale-system". Style: minimal, dark navy background, white text, one bright blue accent color, no stock photos.
```

**Speaker notes:**
- The most interesting lesson was the Dev Spaces one. My first design set `KUBECONFIG` for the whole container, which quietly broke Dev Spaces' own login injection. Workspaces fell back to the pod's service account.
- I traced it to the dashboard source, which treats `KUBECONFIG` as a single directory, and reported it upstream.
- The general lesson: verify end to end after every change, not just that each piece is Synced.

---

## 14. Customer value

**Prompt:**

```text
Create a slide titled "Customer value". Show four value tiles in a 2x2 grid, each with a large short headline and one supporting line: "Zero manual steps" / "From a console visit and token paste on every workspace start to nothing"; "No long-lived credentials" / "Nothing to leak, rotate, or clean up"; "One place to grant and revoke" / "Change the tailnet policy, not dozens of kubeconfigs"; "Reviewable and repeatable" / "Git history, PR diffs, and tests for every access change". Style: minimal, dark navy background, white text, one bright blue accent color, no stock photos.
```

**Speaker notes:**
- For me, it removed a daily annoyance and a real credential risk.
- For a customer, the same pattern applies to many clusters, CI runners, contractors or support staff: grant access by identity, revoke it centrally, and review every change as code.
- It also fits environments with no inbound ports, because both clusters only make outbound connections.

---

## 15. Future improvements

**Prompt:**

```text
Create a slide titled "What I would do next". Use a clean bulleted list of seven items, each with a bold lead phrase: "Per-user identity: audit logs that name the person", "Just-in-time admin instead of standing cluster-admin", "Session recording for kubectl exec", "High availability with a ProxyGroup, once off single-node clusters", "Tailnet settings and OAuth clients in Terraform", "More clusters behind one multi-context kubeconfig", "Scheduled checks that alert when access breaks or grows". Style: minimal, dark navy background, white text, one bright blue accent color, no stock photos.
```

**Speaker notes:**
- The top priority is per-user identity. The shared proxy identity was the right trade-off for a single-user homelab, but a team would want to see who did what.
- High availability wasn't worth it here, because both clusters are single-node OpenShift. Extra replicas would share the same node.

---

## 16. Questions and links

**Prompt:**

```text
Create a closing slide titled "Questions". Below the title, list three links in a clean monospace style: "github.com/morey-tech/homelab/tree/main/docs/tailscale", "tailscale/gitops-acl-action#84", "eclipse-che/che#23972". Add a small footer: "Tailnet: taile3c3a8.ts.net". Style: minimal, dark navy background, white text, one bright blue accent color, no stock photos.
```

**Speaker notes:** The README has the full design, the security model, the change history, and a compare link covering every commit.
