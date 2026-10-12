# Rational Reminder lessons

The `rr-lessons` Argo CD Application manages the `rr-lessons` namespace and three workloads:

| Directory | Workload | Storage |
|-----------|----------|---------|
| [daily-lessons](daily-lessons/README.md) | CronJob delivering a transcript-based lesson to Discord at 08:00 America/Toronto using the local RTX 3090 model | 1 GiB `rr-lessons` PVC on `qnap-nvme` for transcript cache and delivery history |
| [lancedb](lancedb/README.md) | LanceDB service foundation for the RAG prototype; currently health and table inspection only | Separate 5 GiB `rr-lessons-lancedb` PVC on `lvms-vg-nvme` |
| [review](review/README.md) | Lesson desk review UI foundation, initially empty, with a read-only inbox API | Separate 1 GiB `rr-lessons-review` SQLite PVC on `lvms-vg-nvme` |

Each workload directory owns its manifests, application code, configuration, tests, and operations documentation. The review workload reuses UI assets from `prototype/review-ui`, excluding its sample data. The root Kustomization includes all three workloads and sets their namespace. Argo CD continues to target this application root.

The daily lesson job currently selects passages directly from its cached transcripts. The [episode ingestion prototype](prototype/README.md) prepares individual transcripts and evidence-linked teaching questions using the existing GPU model, then supports local LanceDB indexing and retrieval of selected high-confidence questions with source context. These processing tools still run locally. The deployed ingestion/review-write APIs and daily lesson integration remain future work.

## Validation and deployment

Render the complete application and run the daily lesson tests from the repository root:

```bash
kustomize build kubernetes/ocp-mgmt/applications/rr-lessons
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s kubernetes/ocp-mgmt/applications/rr-lessons/daily-lessons -p 'test_*.py' -v
git diff --check
```

See the [LanceDB validation instructions](lancedb/README.md#local-validation) for its dependency installation and service tests, and each workload's documentation for checks after deployment. Changes follow repository review, approved local commits, human push, and Argo CD reconciliation.
