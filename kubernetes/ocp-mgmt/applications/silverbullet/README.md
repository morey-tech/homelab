# Personal notes in SilverBullet

After GitOps deployment, open [SilverBullet](https://silverbullet.apps.ocp-mgmt.rh-lab.morey.tech) on a Mac or iPhone with homelab connectivity. Use the generated `admin:password` shown by:

```bash
oc get secret browser-password -n silverbullet -o jsonpath='{.data.value}' | base64 -d
printf '\n'
```

Save the password in your password manager. Browser credentials and the separate automation API token are generated once by ESO, retained, and never committed. This is one private space shared by its owner and Hermes. The Route uses the existing private OpenShift ingress and HTTPS; it does not make the homelab reachable from outside your network. Use your normal remote access connection when away.

## Storage and access

SilverBullet 2.12.1 is pinned by digest and runs under `restricted-v2` with an arbitrary UID, read-only root, and no service-account token. Its supported `--single` mode enables `SB_USER` and `SB_AUTH_TOKEN`; upstream now treats this mode as legacy, so check its migration guidance before upgrading. The image's root bootstrap is bypassed using `/silverbullet /space --single`.

Markdown and attachments live on the 10 GiB `space` NVMe PVC. The initial Inbox, Journal, Projects, Tasks, index, and templates are seeded only when missing. Personal content is never replaced by a GitOps sync. The follow-up Hermes integration updates only marked index/dashboard sections; keep personal additions outside those markers. The notes browser works without Hermes. Agent capture, generated navigation updates, and reminders require Hermes.

Only ingress router pods, Hermes, and the backup workload can reach the API. SilverBullet has no pod egress. The API token gives automation access to the whole space; it is not limited to task pages. ESO's Kubernetes reader follows the repository's namespace-wide read/list/watch validation pattern; keep this namespace dedicated to notes credentials.

The [filesystem API](https://docs.silverbullet.md/HTTP%20API) supplies ETags. Agent writes use `If-Match` or `If-None-Match: *`, reread on conflicts, and stop after five conflicts. This preserves intervening browser edits. The worker-generated Tasks dashboard is a view; task pages hold authoritative status and schedule metadata.

## Backup

`notes-backup` runs at 03:15 America/Toronto. It reads the authenticated filesystem API, verifies the inventory did not change during the export, and writes a compressed archive plus SHA-256 file to `/backups/notes` on the separate QNAP `backups` PVC. A concurrent edit aborts that attempt; the Job retries twice. Bundled read-only library pages are excluded. Files larger than 100 MiB cause an explicit failure rather than a silently incomplete backup.

Fourteen successful archives are retained. The 30 GiB backup PVC is an initial allocation for mostly Markdown: fourteen full copies of a large attachment collection may exceed it. Expand capacity or adjust retention before that happens. Archives are private files in a mode-0700 directory, not encrypted at rest by this job. Keep the NAS share private and include it in the NAS's independent backup policy. No successful backup for two days raises `PersonalNotesBackupStalled` through cluster monitoring.

```bash
oc get cronjob,jobs,pvc -n silverbullet
oc logs -n silverbullet -l batch.kubernetes.io/job-name --all-containers --tail=20
oc get prometheusrule notes-backup -n silverbullet
```

After the Hermes integration is enabled, the archive also includes original captures, frozen action plans, task schedules, and `System/ReminderReceipts.md`. The reminder worker checkpoints receipts there before sending and after reconciliation. Its primary SQLite database remains on Hermes's PVC. Archives do not include Signal device keys, Hermes conversation history, ntfy credentials, or cached audio. Keep credentials in your password manager; relink Signal if its PVC is lost. Do not copy a running SQLite database file as a backup.

## Restore

1. Use a reviewed GitOps maintenance change to stop Hermes (`replicas: 0`) so captures and reminders cannot race recovery. Keep SilverBullet running, and close browser editors.
2. Retrieve an archive and its matching `.sha256` file from the private NAS backup directory. Save them locally as `/tmp/notes-backup.tar.gz` and `/tmp/notes-backup.tar.gz.sha256`. Retain a backup of the current space before replacing any pages.
3. Forward the service and read its API credential into a private temporary file:

```bash
oc port-forward -n silverbullet service/silverbullet 3000:3000
# In a second terminal:
umask 077
oc get secret api-token -n silverbullet -o jsonpath='{.data.value}' | base64 -d > /tmp/notes-api-token
python3 kubernetes/ocp-mgmt/applications/silverbullet/restore.py \
  /tmp/notes-backup.tar.gz --token-file /tmp/notes-api-token
rm /tmp/notes-api-token
```

The script verifies the checksum and rejects links, unsafe names, duplicate members, and oversized files. Matching existing content is skipped. Different existing pages stop restoration; add `--replace-existing` only when intentionally restoring over the current space. Even then, each replacement uses its observed ETag and aborts on a concurrent edit. Restoring is not an atomic space-wide transaction: a failure can leave a partial restore, and rerunning the same archive is safe. Files absent from the archive are not deleted.

4. Inspect the restored captures, Tasks pages, and delivery receipts. If the Hermes SQLite database survives, it remains authoritative for delivery history. If it is lost, the worker imports the restored receipt page into an empty database. Restoring an older archive can lose newer delivery receipts and cause a duplicate alert; check schedules before resuming.
5. Revert the reviewed maintenance change through GitOps. Confirm the dashboard and worker readiness. Recovery point is the latest successful nightly archive; a live PVC is not a backup.

## Validation

Local pinned-image tests verified arbitrary-UID startup, authenticated filesystem access, anonymous-read rejection, stale ETag rejection, and backup content restoration. Cluster Route admission, ESO readiness, scheduled NAS backups, and recovery from an actual NAS archive remain post-deployment checks. Signal capture and automated reminders are part of the subsequent Hermes integration deployment.
