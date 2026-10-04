# Agent Workflow

This document describes the standard workflow for coding agents implementing changes in this repository.

## Human Review and Local Commit Workflow

### 1. Implement Changes

Work directly on `main` by default. Do not create a branch, GitHub issue, or pull request unless explicitly requested. Preserve unrelated changes in the working tree.

### 2. Validate Changes

- Run checks appropriate to the change.
- Before committing, use local validation, read-only cluster inspection, and non-persisting server-side dry runs. Do not modify the cluster to validate uncommitted changes.
- Defer tests that require changed cluster resources until the approved commits have been pushed by the human and deployed through GitOps.
- Report test results and any validation that could not be completed.

### 3. Stop for Human Review Before Committing

After implementing and validating the changes, group them into a proposed sequence of semantic commits, each covering one logical purpose. Leave changes uncommitted and summarize the changes, validation results, and proposed commit breakdown for human review. Wait for explicit approval to commit; a request to implement a change is not approval to commit it.

### 4. Commit After Approval

After human review and explicit approval, create the approved local commits:

- Split changes into semantic commits by logical purpose, such as a feature, a bug fix, or an independent documentation update. Keep implementation and its directly related tests or documentation together; do not split mechanically by file or combine unrelated changes.
- Stage only the reviewed files or hunks for each commit, preserving unrelated working tree changes. Each commit should be coherent and independently understandable, with dependencies ordered first.
- Use Conventional Commit messages in the form `type(scope): description`, with an optional scope. Common types include `feat`, `fix`, `docs`, `refactor`, `test`, `build`, `ci`, and `chore`.
- Write a concise, imperative description, for example `feat(devspaces): persist Codex state` or `docs: clarify agent commit workflow`. Mark breaking changes with `!` after the type/scope or a `BREAKING CHANGE:` footer explaining the impact.

### 5. Leave Push to the Human

The human manually pushes the commits to `main`. Agents must not push automatically. Report the local commits and leave this command for the human to run:

```bash
git push origin main
```

### 6. Deploy Through GitOps

Do not apply changes to the cluster before they have been reviewed, committed, and pushed. This includes direct `oc` or `kubectl` apply, create, patch, edit, delete, and rollout restart operations, as well as ad hoc test Jobs or locally rendered manifests applied "for validation". A request to implement or deploy a change does not authorize bypassing this workflow.

After the human pushes, let Argo CD reconcile the committed manifests rather than applying local files directly. Observe the rollout and run the deferred cluster checks against the GitOps-deployed resources. Report any failures without introducing uncommitted cluster fixes.

---

## Example: DevSpaces Claude Extension Auto-Install

**Issue**: #114 - Auto-load Claude extension in DevSpaces workspaces
**PR**: #115 - feat(devspaces): auto-install extensions via .vscode/extensions.json

### Approaches Tested

| Approach | Works? | Notes |
|----------|--------|-------|
| `.vscode/extensions.json` in repo | Yes | Simplest, recommended |
| `DEFAULT_EXTENSIONS` env + postStart | Yes | More complex, but works |
| Devfile `attributes` for extensions.json | No | File not created in filesystem |
| CheCluster `defaultPlugins` | No | Designed for Theia, not che-code |

### Final Solution

1. **Add `.vscode/extensions.json`** to the repository:
```json
{
  "recommendations": [
    "Anthropic.claude-code",
    "redhat.ansible"
  ]
}
```

2. **Configure CheCluster** for Open VSX access:
```yaml
spec:
  components:
    pluginRegistry:
      openVSXURL: https://open-vsx.org
```

### Key Learnings

- CheCluster `defaultPlugins` field is designed for older Theia-based plugins, not VS Code extensions with che-code editor
- Devfile `attributes` store data in the DevWorkspace spec but don't create actual files in the workspace filesystem
- Che-code automatically installs extensions from `.vscode/extensions.json` when the Open VSX registry is accessible

---

## Example: README Documentation Update

**Task**: Update repository documentation following hierarchical structure

### Documentation Hierarchy

```
Root README (Architecture + Navigation)
    ↓
├── Subsystem READMEs (Technical Details)
│   ├── kubernetes/README.md - GitOps workflow
│   ├── ansible/README.md - Renovate workflow
│   └── terraform/README.md - Provisioning
└── Cluster READMEs (Application Catalogs)
    ├── kubernetes/ocp-home/README.md
    ├── kubernetes/ocp-gpu/README.md
    └── kubernetes/ocp-mgmt/README.md
```

### Documentation Style Guide

**Principles**:
- Practical, command-line focused (show executable examples first)
- Real URLs and commands (no placeholders like `<cluster-name>`)
- Tables for structured data (application catalogs, comparisons)
- Code blocks with bash syntax highlighting
- Clear section hierarchy (##, ###)
- Direct and concise (assume technical audience)

**Format Standards**:
- **Application Catalogs**: Use table format with columns: Application | Namespace | URL | Purpose | Notable Features
- **System Components**: Bullet list with component name and brief purpose
- **Commands**: Always in ```bash code blocks with actual working examples
- **Links**: Use markdown links, not plain URLs
- **Cluster URLs**: Document API, Console, and ArgoCD URLs for each cluster

### Application Catalog Table Example

```markdown
| Application | Namespace | URL | Purpose | Notable Features |
|-------------|-----------|-----|---------|-----------------|
| Immich | immich | [immich.apps.ocp-home...](https://immich.apps.ocp-home.rh-lab.morey.tech) | Photo/video management | Intel GPU, CloudNativePG |
| Home Assistant | home-assistant | [hass.apps.ocp-home...](https://hass.apps.ocp-home.rh-lab.morey.tech) | Home automation | MetalLB LoadBalancer |
```

### Files to Update

**Root README** (`README.md`):
- Architecture overview with cluster topology
- Repository structure tree
- Development environment setup
- Component summaries with links

**Cluster READMEs** (`kubernetes/ocp-*/README.md`):
- Application catalog table
- System components list
- Cluster-specific features
- Access URLs (API, Console, ArgoCD)
- Initial setup (preserve existing auth instructions)

**Subsystem READMEs** (preserve existing):
- `kubernetes/README.md` - GitOps workflow
- `ansible/README.md` - Renovate workflow
- `containers/README.md` - Build conventions

### Update Workflow

1. **Explore** existing documentation to understand current state
2. **Identify** applications deployed in each cluster (via kustomization.yaml)
3. **Document** URLs from route/ingress configurations
4. **Update** READMEs starting with root, then clusters
5. **Validate** all links work and commands are accurate
6. **Stop for human review** before committing; after explicit approval, commit with message: `docs: restructure README hierarchy for better navigation`. Leave the push to `main` to the human.

### Content to Preserve

When updating cluster READMEs:
- HTPasswd auth setup instructions
- oc login commands
- Bitwarden password references
- Existing working procedures

### Key Learnings

- **Hierarchical structure** makes large repositories navigable
- **Application catalogs** belong in cluster READMEs, not root
- **Real examples** (URLs, commands) are more valuable than placeholders
- **Consistency** in table formats and section structure improves discoverability
- **Links to detailed docs** keep root README focused on architecture
