# Private reminder notifications

This separate ntfy service provides private notification delivery for the personal-notes system. Scheduled reminders become active with the subsequent Hermes integration; Signal Note to Self handles capture and conversation.

After GitOps deployment, install the ntfy iPhone app. Add the server [ntfy.apps.ocp-mgmt.rh-lab.morey.tech](https://ntfy.apps.ocp-mgmt.rh-lab.morey.tech), sign in as `hermes`, and subscribe to `personal-reminders`. Retrieve the generated password locally:

```bash
oc get secret hermes-password -n ntfy -o jsonpath='{.data.value}' | base64 -d
printf '\n'
```

Enable notifications in iOS and test while the phone is locked. The phone must be able to reach this private homelab Route to fetch alerts. If remote homelab access is disconnected, delivery may be delayed. Do not consider a reminder verified until it appears on the phone.

## Configuration

ntfy 2.33.1 is pinned by digest. It runs with arbitrary OpenShift UID, read-only root, no Kubernetes token, and a 1 GiB NVMe PVC for its authentication and message databases. The initialization container starts the server to create/migrate its auth database, sets the generated account password, then grants access only to `personal-reminders`. Anonymous access and signup are disabled. Account credentials are retained by ESO; changing them requires a GitOps-driven restart to re-run initialization and updating the phone's saved password.

The only inbound paths are the authenticated HTTPS Route and Hermes's internal connection. External HTTPS egress is limited to `ntfy.sh`, plus the existing cluster network ranges. On iOS, the [documented upstream relay](https://docs.ntfy.sh/config/#ios-instant-notifications) sends a wake-up identifier; the app fetches the actual notification from this server. The relay still receives delivery metadata. Alerts contain generic text and a task-page URL, never task titles, journal text, or transcripts. Signal input remains end-to-end encrypted to the linked homelab device; this separate notification path is not Signal encryption.

Messages are cached for 72 hours. A server acknowledgement means the alert was accepted, not that the phone displayed it. The Hermes worker records failures and retries at most five times. If an acknowledgement is lost, a retry can duplicate an alert. No public topics or additional recipients are configured.

## Checks and recovery

```bash
oc get externalsecret,pvc,pods,route,egressfirewall -n ntfy
oc rollout status deployment/ntfy -n ntfy
oc logs deployment/ntfy -n ntfy -c account --tail=20
```

The SQLite files are runtime state, not Git content. If this PVC is lost, the retained generated password recreates the account through initialization. Old cached notifications are lost; task schedules and delivery receipts recover separately through SilverBullet. Do not replay every old notification after a restore.

Local tests using fake credentials and a disabled upstream relay verified account initialization, anonymous denial, allowed-topic publishing, and denial for another topic. Actual iOS push, private-network background access, and the deployed egress policy remain post-GitOps checks.
