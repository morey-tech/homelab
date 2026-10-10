# Daily Rational Reminder lessons

The `rr-lessons` CronJob runs at **08:00 America/Toronto**, including daylight-saving changes. It asks the RTX 3090-backed `local-llm` on ocp-mgmt to teach one concept from [morey-tech/rr-scraper](https://github.com/morey-tech/rr-scraper), then posts an explanation, practical takeaway, reflection question, and source links to Discord.

## Configuration

| Setting | Value |
|---------|-------|
| Namespace / Argo CD Application | `rr-lessons` |
| Schedule | `0 8 * * *`, `America/Toronto` |
| Lesson runtime | `python:3.14.8-slim-trixie`, pinned by digest |
| Git init runtime | `alpine/git:2.54.0`, pinned by digest |
| Source | `transcripts/all.md` on `master`, resolved to a commit per run |
| Model | `local-llm` / Qwen3-4B-Instruct-2507 |
| Inference endpoint | `https://local-llm-inference-server.apps.ocp-mgmt.rh-lab.morey.tech/v1` |
| Discord credential | Bitwarden Login item `80644688-fc2a-483a-b1d5-b4df000e7b11`, password field |
| Kubernetes Secret | `rr-lessons-discord`, key `webhook-url` |
| Shared storage | One 1 GiB `rr-lessons` PVC on `qnap-nvme` |
| History directory | PVC `history/`, mounted at `/data` |
| Transcript cache directory | PVC `transcripts/`, mounted read-only at `/transcripts` in Python |

The application explicitly declares its own namespace. Its ServiceAccount, ExternalSecret, generated ConfigMaps, PVC, and CronJob all reside there. The inference-server application owns the cross-namespace `rr-lessons-local-llm` RoleBinding, granting only `get` on `inferenceservices/local-llm`. The job reads a projected one-hour ServiceAccount token for each inference call. No GPU is requested by the job itself.

The Bitwarden password must hold the full Discord webhook URL. ESO reads it through `bitwarden-login` and refreshes hourly; the job requires the resulting Secret. A newly created item must first be visible to the Bitwarden CLI backend. If it is not, inspect ESO status and follow the existing [Bitwarden procedures](../../system/external-secrets/README.md). Do not put the webhook URL in Git or logs. New jobs pick up rotated credentials automatically.

Edit `prompt.txt` to change lesson style, `cronjob.yaml` to change schedule, and `kustomization.yaml` to change model configuration. Keep `LESSON_TIMEZONE` consistent with the CronJob's `timeZone`. Apply changes through the repository's review, local commit, human push, and Argo CD workflow.

## Source selection and delivery

The combined transcript is canonical: at implementation time it included episode 430, while the individual files stopped at 366. The `sync-transcripts` init container maintains a shallow bare Git repository in the shared PVC's `transcripts/` directory. The first run fetches the `master` tip; later runs use `git fetch --depth=1 --no-tags`, reusing existing Git objects and Git's transfer compression instead of downloading the complete raw file every day. Git negotiates objects, rather than applying a textual `git diff`; actual transfer size depends on upstream changes and server packing. See [Git fetch](https://git-scm.com/docs/git-fetch).

The init container mounts the shared PVC at `/storage`, creates `history/` and `transcripts/`, and exports only `transcripts/all.md` into the cache with its commit in a `revision` file. Python mounts those directories separately using `subPath`: history is writable at `/data`, while the cached file and commit are read-only at `/transcripts/all.md` and `/transcripts/revision`. An unchanged commit leaves those files untouched. A changed commit replaces the snapshot before the lesson container starts; Git garbage collection prunes unreachable objects older than seven days to limit cache growth. The Git object store includes the repository's other files, but they are not checked out or executed. Git runs without model or Discord credentials. Python mounts the cache read-only and makes no GitHub API or raw-file requests.

Failed fetches fail the init container and prevent delivery from a stale cache. The CronJob's `Forbid` policy serializes scheduled jobs; do not run concurrent manual jobs against the same cache. The cache directory can be rebuilt without changing the separate history directory; both share the same PVC and capacity. Monitor PVC use as the upstream repository grows; the shallow cache is not a hard disk-usage bound.

Python reads the cached file (up to 64 MiB), splits its `## Episode N` headings, and constructs passages of at most 12,000 characters. Only one passage per request goes to the model, keeping input comfortably below its configured 32K context. No vector database or external model API is needed.

Selection favors the least-used episodes, then the least-used passages within those episodes. A date-seeded choice breaks ties. The model also receives the last 14 lesson titles to discourage repeated concepts, though this is not a guarantee of semantic uniqueness. It can skip introductions or housekeeping; the job tries up to three passages. Output must contain the required fields and a short exact quote from its source. This checks quotation grounding, not the factual accuracy of the entire generated lesson. The prompt asks for educational explanations and historical context instead of treating old financial rules or recommendations as current facts.

Messages contain a commit-pinned transcript link with line numbers and the original episode link. Discord mentions are disabled. The job uses a single embed and [`wait=true`](https://docs.discord.com/developers/resources/webhook#execute-webhook) to request a confirmed message ID.

History in `/data/history.json` records the date, source, generated payload, delivery status, and confirmed message ID. Atomic writes and a filesystem lock protect history; `concurrencyPolicy: Forbid` prevents overlapping scheduled jobs. A confirmed day is skipped on rerun. Namespace and PVC deletion require review so delivery history is not silently lost.

Before posting, the job persists status `sending`; afterward it records `sent`. If Discord times out or the process stops in between, the job fails and does **not** automatically resend. This favors avoiding duplicate messages over guaranteed delivery: even a definitive webhook error or a crash just before posting leaves the date unconfirmed. Inspect Discord and the saved payload before planning any recovery. Future days still run. Exactly-once delivery cannot be guaranteed across the external request and history write.

Source and generation failures may retry twice within the job's 30-minute deadline. A run missed by more than an hour is skipped, without a catch-up flood. Failed jobs remain visible with the last three failures retained. See [Kubernetes CronJob scheduling](https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/) for scheduling and concurrency behavior.

## Validation and operations

Run local checks from the repository root with Python 3.9+ and Git installed. Cache tests use a temporary local Git origin and require no network access:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s kubernetes/ocp-mgmt/applications/rr-lessons -p 'test_*.py' -v
kustomize build kubernetes/ocp-mgmt/applications/rr-lessons
kustomize build kubernetes/ocp-mgmt/applications/inference-server
git diff --check
```

After approved commits are pushed by the human and Argo CD reconciles both applications, verify namespace placement, the secret, storage, and permissions:

```bash
oc get application rr-lessons inference-server -n openshift-gitops
oc get namespace rr-lessons
oc get externalsecret rr-lessons-discord -n rr-lessons
oc get secret rr-lessons-discord -n rr-lessons
oc get pvc,cronjob,jobs,pods -n rr-lessons
oc get rolebinding rr-lessons-local-llm -n inference-server
oc auth can-i get inferenceservices.serving.kserve.io/local-llm -n inference-server --as=system:serviceaccount:rr-lessons:rr-lessons
oc get cronjob rr-lessons -n rr-lessons -o jsonpath='{.spec.schedule}{" "}{.spec.timeZone}{"\n"}'
```

Allow the first scheduled run to exercise the deployed configuration, then inspect its log and the Discord lesson:

```bash
oc logs -n rr-lessons -l app=rr-lessons --all-containers=true --tail=100
oc logs -n rr-lessons -l app=rr-lessons -c sync-transcripts --tail=100
oc get jobs -n rr-lessons --sort-by=.metadata.creationTimestamp
```

Confirm the lesson explains a concept supported by its linked passage, includes the takeaway and question, and that reruns do not produce a second confirmed lesson for the same local day. Live model output, projected-token authentication, Bitwarden visibility, NFS writes, and Discord delivery require post-GitOps validation; local tests mock the external APIs.

`lessons.py --preview` generates a Discord payload without posting or changing history. It still needs model access and `LLM_TOKEN_FILE` pointing to a valid token file, plus `LLM_BASE_URL`; it uses today's saved payload if one already exists. Otherwise, it reads the cache at `TRANSCRIPT_CACHE_DIR` (default `/transcripts`). `--preview --transcript-file /tmp/rr-all.md` bypasses the cache and uses a local copy of the canonical transcript for development. Do not create ad hoc cluster test jobs for uncommitted code.
