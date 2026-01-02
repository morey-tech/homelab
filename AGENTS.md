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
