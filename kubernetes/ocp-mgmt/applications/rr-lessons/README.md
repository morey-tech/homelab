# Rational Reminder lessons

The `rr-lessons` Argo CD Application manages the `rr-lessons` namespace and the daily lesson workload:

| Directory | Workload | Storage |
|-----------|----------|---------|
| [daily-lessons](daily-lessons/README.md) | CronJob delivering a transcript-based lesson to Discord at 08:00 America/Toronto using the local RTX 3090 model | 1 GiB `rr-lessons` PVC on `qnap-nvme` for transcript cache and delivery history |

Each workload directory owns its manifests, application code, configuration, tests, and operations documentation. The root Kustomization includes the daily lesson workload and sets its namespace. Argo CD continues to target this application root.

The daily lesson job currently selects passages directly from its cached transcripts.

## Validation and deployment

Render the complete application and run the daily lesson tests from the repository root:

```bash
kustomize build kubernetes/ocp-mgmt/applications/rr-lessons
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s kubernetes/ocp-mgmt/applications/rr-lessons/daily-lessons -p 'test_*.py' -v
git diff --check
```

See the [daily lesson operations documentation](daily-lessons/README.md) for checks after deployment. Changes follow repository review, approved local commits, human push, and Argo CD reconciliation.
