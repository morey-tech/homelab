#!/usr/bin/env bash

# Minimal bootstrap for ms-02/ms-03/ms-04 and the tr-gpu worker.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLUSTER_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
EXPECTED_CLUSTER="https://api.ocp-mgmt.rh-lab.morey.tech:6443"
HTPASSWD_FILE="${HTPASSWD_FILE:-${CLUSTER_DIR}/ocp-mgmt.htpasswd}"
BITWARDEN_SECRET_FILE="${BITWARDEN_SECRET_FILE:-${CLUSTER_DIR}/system/external-secrets/bitwarden-secret.yaml}"

# OLM creates CRDs and deployments asynchronously. oc wait needs the resource
# to exist first, including on older oc clients without --for=create support.
wait_for_resource() {
    local deadline=$((SECONDS + 600))
    until oc get "$@" --request-timeout=10s >/dev/null 2>&1; do
        if (( SECONDS >= deadline )); then
            echo "ERROR: Timed out waiting for $*." >&2
            return 1
        fi
        sleep 5
    done
}

echo '=== OCP Management Cluster Bootstrap ==='

# Validate every local prerequisite before making any cluster changes.
for command in oc helm; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "ERROR: $command must be installed and available on PATH." >&2
        exit 1
    fi
done

CURRENT_CLUSTER=$(oc whoami --show-server)
if [[ "$CURRENT_CLUSTER" != "$EXPECTED_CLUSTER" ]]; then
    echo "ERROR: Expected ${EXPECTED_CLUSTER}; current cluster is ${CURRENT_CLUSTER}." >&2
    echo "Log in with: oc login ${EXPECTED_CLUSTER}" >&2
    exit 1
fi
oc whoami --request-timeout=10s

if [[ ! -s "$BITWARDEN_SECRET_FILE" ]]; then
    echo "ERROR: Bitwarden secret file is missing or empty: ${BITWARDEN_SECRET_FILE}" >&2
    echo "Copy the Notes from 'ocp-mgmt.rh-lab.morey.tech external-secrets bitwarden' in Bitwarden." >&2
    exit 1
fi
if [[ ! -s "$HTPASSWD_FILE" ]]; then
    echo "ERROR: HTPasswd file is missing or empty: ${HTPASSWD_FILE}" >&2
    echo "Run: htpasswd -B -c ${HTPASSWD_FILE} admin" >&2
    echo "Use the 'OpenShift ocp-mgmt admin password' entry in Bitwarden." >&2
    exit 1
fi

RENDER_DIR=$(mktemp -d)
trap 'rm -rf "$RENDER_DIR"' EXIT
# Render before applying so a chart download/build failure stops cleanly.
oc kustomize "${CLUSTER_DIR}/system/external-secrets/operator" --enable-helm > "${RENDER_DIR}/eso-operator.yaml"
oc kustomize "${CLUSTER_DIR}/system/external-secrets" --enable-helm > "${RENDER_DIR}/external-secrets.yaml"
oc kustomize "${CLUSTER_DIR}/system/htpass-admin" > "${RENDER_DIR}/htpass-admin.yaml"

echo '[1/5] Installing External Secrets Operator and Bitwarden'
oc create namespace external-secrets-system --dry-run=client -o yaml | oc apply -f -
oc apply -n external-secrets-system -f "$BITWARDEN_SECRET_FILE"
oc apply --server-side -f "${RENDER_DIR}/eso-operator.yaml"
oc wait --for=condition=Established crd/clustersecretstores.external-secrets.io --timeout=120s
for deployment in external-secrets-cert-controller external-secrets-webhook external-secrets; do
    oc rollout status "deployment/${deployment}" -n external-secrets-system --timeout=600s
done
# ClusterSecretStores require both the CRD and the admission webhook above.
oc apply --server-side -f "${RENDER_DIR}/external-secrets.yaml"
oc rollout status deployment/bitwarden-cli -n external-secrets-system --timeout=600s
oc wait --for=condition=Ready clustersecretstore/bitwarden-login clustersecretstore/bitwarden-fields clustersecretstore/bitwarden-notes --timeout=300s

echo '[2/5] Configuring administrator access'
oc create secret generic htpass-secret --from-file=htpasswd="$HTPASSWD_FILE" \
    -n openshift-config --dry-run=client -o yaml | oc apply -f -
oc apply -f "${RENDER_DIR}/htpass-admin.yaml"
# The authentication operator reconciles OAuth configuration; no forced restart.

echo '[3/5] Installing OpenShift GitOps'
oc apply -f "${SCRIPT_DIR}/0-gitops-operator.yaml"
wait_for_resource crd/argocds.argoproj.io
oc wait --for=condition=Established crd/argocds.argoproj.io --timeout=120s
oc wait --for=jsonpath='{.status.installedCSV}' subscription/openshift-gitops-operator -n openshift-gitops-operator --timeout=600s
GITOPS_CSV=$(oc get subscription/openshift-gitops-operator -n openshift-gitops-operator -o jsonpath='{.status.installedCSV}')
oc wait --for=jsonpath='{.status.phase}'=Succeeded "clusterserviceversion/${GITOPS_CSV}" -n openshift-gitops-operator --timeout=600s

echo '[4/5] Creating the cluster Argo CD instance'
oc apply -f "${SCRIPT_DIR}/1-cluster-argocd-instance.yaml"
oc apply -f "${SCRIPT_DIR}/2-cluster-role.yaml"
oc wait --for=jsonpath='{.status.phase}'=Available argocd/cluster-argocd -n openshift-gitops --timeout=600s
wait_for_resource crd/applications.argoproj.io
wait_for_resource crd/applicationsets.argoproj.io
oc wait --for=condition=Established crd/applications.argoproj.io crd/applicationsets.argoproj.io --timeout=120s

echo '[5/5] Enabling the minimal GitOps configuration'
# Merge this configuration before running: all GitOps sources track HEAD.
oc apply -f "${SCRIPT_DIR}/3-app-of-apps.yaml"
oc wait --for=jsonpath='{.status.sync.status}'=Synced application/openshift-gitops-config -n openshift-gitops --timeout=600s
for application in external-secrets-system htpass-admin-system; do
    wait_for_resource "application/${application}" -n openshift-gitops
    oc wait --for=jsonpath='{.status.sync.status}'=Synced "application/${application}" -n openshift-gitops --timeout=600s
    oc wait --for=jsonpath='{.status.health.status}'=Healthy "application/${application}" -n openshift-gitops --timeout=600s
done

echo '=== Bootstrap Complete ==='
echo 'kubeadmin has been retained. Verify admin login before removing it manually.'
echo "  oc login -u admin --server=${EXPECTED_CLUSTER}"
echo '  oc get applications -n openshift-gitops'
echo '  oc get route cluster-argocd-server -n openshift-gitops'
