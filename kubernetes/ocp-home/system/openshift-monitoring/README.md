# Grafana Metrics Access

This component grants the Grafana instance hosted on `ocp-mgmt` read-only access to the existing OCP Home monitoring API. It does not change scrape configuration, platform retention, Alertmanager, or the Thanos Route.

The system ApplicationSet discovers this directory and deploys `openshift-monitoring-system` into the existing `openshift-monitoring` namespace. The `grafana-ocp-mgmt` service account has only `get` permission on `prometheuses/api` named `k8s` in that namespace. The token controller populates `grafana-ocp-mgmt-token-v1`; no credential value is committed to Git.

## Initial Rollout

Deploy the OCP Home identity before enabling its Grafana data source in OCP Management. Review and commit the identity/ApplicationSet changes separately, have the human push them, and wait for GitOps reconciliation:

```bash
oc --context=ocp-home-tailnet get application openshift-monitoring-system -n openshift-gitops
oc --context=ocp-home-tailnet auth can-i get prometheuses.monitoring.coreos.com/k8s \
  --subresource=api -n openshift-monitoring \
  --as=system:serviceaccount:openshift-monitoring:grafana-ocp-mgmt
```

After the Application is Synced and Healthy and the permission check returns `yes`, retrieve the generated token:

```bash
oc --context=ocp-home-tailnet get secret grafana-ocp-mgmt-token-v1 \
  -n openshift-monitoring -o jsonpath='{.data.token}' | base64 --decode
```

Put the token in the **password** field of Bitwarden login item **OCP Home Grafana metrics**, UUID `762ec6ea-79b5-4e9f-be81-b4dc014da106`. Do not paste it into chat, Git, or a dashboard. The management Bitwarden backend syncs its local vault every two minutes.

Then review, commit, and push the management data-source/dashboard changes. Management External Secrets reads the password into `monitoring/ocp-home-metrics-token-v1`; Grafana reads it at startup. Publishing the consumer before the Bitwarden credential exists can prevent Grafana from starting (or produce 401s if the item password is empty), including temporary loss of the management dashboard.

The data source uses the existing [Thanos HTTPS route](https://thanos-querier-openshift-monitoring.apps.ocp-home.rh-lab.morey.tech), currently resolved to `192.168.6.71` from the management cluster. The Route certificate uses a publicly trusted issuer; keep certificate and hostname verification enabled. Grafana does not use the administrative Tailscale API proxy.

## Rotation

This controller-generated token is long-lived; review/rotate it at least every 90 days and immediately if exposed. Rotation spans both clusters and Bitwarden:

1. Add a second versioned token Secret for the same service account in `grafana-metrics.yaml`, retaining the old Secret. Review, commit, and push; wait for OCP Home GitOps to create it.
2. Copy the new token into the same Bitwarden item's password field and allow its management-side cache to sync.
3. In management Git, advance the ExternalSecret metadata/target name and Grafana's matching Secret reference together (for example, `ocp-home-metrics-token-v1` to `ocp-home-metrics-token-v2`). Review, commit, and push. The new Secret reference recreates Grafana so it reads the replacement token.
4. Verify the OCP Home data source and dashboard through Grafana. Only then remove the old source token Secret from OCP Home Git and deploy that reviewed change, revoking the old token.

An ESO refresh alone does not reload Grafana's environment. Keep the old OCP Home token valid until the new Grafana pod has been verified. Do not rotate by deleting the live Secret or bypassing GitOps.

## Validation

Before review:

```bash
kustomize build kubernetes/ocp-home/system/openshift-monitoring
```

After both clusters reconcile:

```bash
oc --context=logged-user get externalsecret ocp-home-metrics-token-v1 -n monitoring
python3 kubernetes/ocp-mgmt/applications/monitoring/scripts/check-cluster.py --cluster ocp-home
```

See [management monitoring](../../../ocp-mgmt/applications/monitoring/README.md) for dashboard details and checks. Existing OCP Home warning alerts remain visible; this integration does not remediate them.
