# Claude Code Agent Workflow

This document describes the standard workflow for implementing features and fixes using Claude Code in this repository.

## Issue-to-PR Workflow

### 1. Create GitHub Issue
Document the problem with:
- Problem description
- Impact on workflow
- Current workaround (if any)
- Proposed solution (high-level)

```bash
gh issue create --title "feat: description" --label "enhancement" --body "..."
```

### 2. Comment with Proposed Solution
Add a detailed comment to the issue with:
- Technical approach
- Configuration changes required
- Expected outcome
- References to documentation

```bash
gh issue comment <issue-number> --body "..."
```

### 3. Create Feature Branch
```bash
git checkout -b feat/<feature-name>
# or for fixes:
git checkout -b fix/<fix-name>
```

### 4. Implement Changes
Make the necessary code/configuration changes.

### 5. Create Pull Request
```bash
gh pr create --title "feat: description" --body "..."
```

Link to the issue with `Closes #<issue-number>` in the PR body.

### 6. Test Changes
- Apply changes to the cluster for testing
- Verify functionality works as expected
- Document test results

### 7. Comment Test Results
Add a comment to the issue or PR with:
- What was tested
- Test outcomes
- Any issues encountered and how they were resolved

### 8. Merge PR
After successful testing:
```bash
gh pr merge <pr-number> --squash --delete-branch
```

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
6. **Commit** with message: `docs: restructure README hierarchy for better navigation`

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