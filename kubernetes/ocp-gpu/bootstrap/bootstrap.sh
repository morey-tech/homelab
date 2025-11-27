#!/bin/bash

# Bootstrap script for OCP GPU cluster
# This script automates the initial setup of the OpenShift GPU cluster

set -e  # Exit immediately if a command exits with a non-zero status

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

EXPECTED_CLUSTER="https://api.ocp-gpu.rh-lab.morey.tech:6443"
HTPASSWD_FILE="../ocp-gpu.htpasswd"
BITWARDEN_SECRET_FILE="../system/external-secrets/bitwarden-secret.yaml"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${GREEN}=== OCP GPU Cluster Bootstrap ===${NC}\n"

# Step 1: Check if oc command is authenticated
echo -e "${YELLOW}[1/9] Checking oc authentication...${NC}"
if ! oc whoami &> /dev/null; then
    echo -e "${RED}ERROR: oc command is not authenticated.${NC}"
    echo "Please log in to the OpenShift cluster using:"
    echo "  oc login ${EXPECTED_CLUSTER}"
    exit 1
fi
CURRENT_USER=$(oc whoami)
echo -e "${GREEN}✓ Authenticated as: ${CURRENT_USER}${NC}\n"

# Step 2: Check if authenticated to the correct cluster
echo -e "${YELLOW}[2/9] Verifying cluster connection...${NC}"
CURRENT_CLUSTER=$(oc whoami --show-server)
if [ "$CURRENT_CLUSTER" != "$EXPECTED_CLUSTER" ]; then
    echo -e "${RED}ERROR: Connected to wrong cluster.${NC}"
    echo "Expected: ${EXPECTED_CLUSTER}"
    echo "Current:  ${CURRENT_CLUSTER}"
    echo "Please log in to the correct cluster using:"
    echo "  oc login ${EXPECTED_CLUSTER}"
    exit 1
fi
echo -e "${GREEN}✓ Connected to correct cluster: ${EXPECTED_CLUSTER}${NC}\n"

# Step 3: Check if bitwarden secret file exists
echo -e "${YELLOW}[3/9] Checking for bitwarden secret file...${NC}"
if [ ! -f "${SCRIPT_DIR}/${BITWARDEN_SECRET_FILE}" ]; then
    echo -e "${RED}ERROR: bitwarden secret file not found at: ${SCRIPT_DIR}/${BITWARDEN_SECRET_FILE}${NC}"
    echo ""
    echo "To create the bitwarden secret file:"
    echo "  1. Copy the contents of the Notes section from 'ocp-gpu.rh-lab.morey.tech external-secrets bitwarden' entry in Bitwarden"
    echo "  2. Create ${SCRIPT_DIR}/${BITWARDEN_SECRET_FILE} with those contents"
    exit 1
fi
echo -e "${GREEN}✓ bitwarden secret file found${NC}\n"

# Step 4: Create external-secrets-system namespace
echo -e "${YELLOW}[4/9] Creating external-secrets-system namespace...${NC}"
if oc get namespace external-secrets-system &> /dev/null; then
    echo -e "${YELLOW}⚠ Namespace external-secrets-system already exists, skipping creation${NC}\n"
else
    oc create namespace external-secrets-system
    echo -e "${GREEN}✓ external-secrets-system namespace created${NC}\n"
fi

# Step 5: Deploy external secrets
echo -e "${YELLOW}[5/9] Deploying external secrets...${NC}"

echo "  → Applying bitwarden-secret.yaml"
oc apply -n external-secrets-system -f "${SCRIPT_DIR}/${BITWARDEN_SECRET_FILE}"
echo -e "${GREEN}  ✓ bitwarden secret applied${NC}\n"

echo "  → Building and applying external-secrets kustomization"
oc kustomize "${SCRIPT_DIR}/../system/external-secrets/" --enable-helm | oc apply -f -
echo "  Waiting for external-secrets operator to initialize..."
sleep 30  # TODO: Replace with proper wait condition
echo -e "${GREEN}  ✓ external secrets deployed${NC}\n"

# Step 6: Check if htpasswd file exists
echo -e "${YELLOW}[6/9] Checking for htpasswd file...${NC}"
if [ ! -f "${SCRIPT_DIR}/${HTPASSWD_FILE}" ]; then
    echo -e "${RED}ERROR: htpasswd file not found at: ${SCRIPT_DIR}/${HTPASSWD_FILE}${NC}"
    echo ""
    echo "To create the htpasswd file, run:"
    echo "  cd ${SCRIPT_DIR}/.."
    echo "  htpasswd -B -c ocp-gpu.htpasswd admin"
    echo "  # Enter password from Bitwarden when prompted"
    exit 1
fi
echo -e "${GREEN}✓ htpasswd file found${NC}\n"

# Step 7: Create htpasswd secret
echo -e "${YELLOW}[7/9] Creating htpasswd secret...${NC}"
if oc get secret htpass-secret -n openshift-config &> /dev/null; then
    echo -e "${YELLOW}⚠ Secret htpass-secret already exists, skipping creation${NC}\n"
else
    oc create secret generic htpass-secret \
        --from-file=htpasswd="${SCRIPT_DIR}/${HTPASSWD_FILE}" \
        -n openshift-config
    echo -e "${GREEN}✓ htpasswd secret created${NC}\n"
fi

# Step 8: Deploy bootstrap files in order
echo -e "${YELLOW}[8/9] Deploying bootstrap files...${NC}\n"

echo "  → Applying 0-gitops-operator.yaml (GitOps Operator)"
oc apply -f "${SCRIPT_DIR}/0-gitops-operator.yaml"
echo "  Waiting for operator to initialize..."
sleep 30  # TODO: Replace with: oc wait --for=condition=Available deployment/openshift-gitops-operator -n openshift-gitops-operator --timeout=300s
echo -e "${GREEN}  ✓ GitOps operator deployed${NC}\n"

echo "  → Applying 1-cluster-argocd-instance.yaml (Argo CD Instance)"
oc apply -f "${SCRIPT_DIR}/1-cluster-argocd-instance.yaml"
echo "  Waiting for Argo CD instance to be ready..."
sleep 60  # TODO: Replace with: oc wait --for=condition=Available argocd/cluster-argocd -n openshift-gitops --timeout=600s
echo -e "${GREEN}  ✓ Argo CD instance deployed${NC}\n"

echo "  → Applying 2-cluster-role.yaml (Cluster Permissions)"
oc apply -f "${SCRIPT_DIR}/2-cluster-role.yaml"
echo "  Waiting for permissions to propagate..."
sleep 10  # TODO: Replace with more sophisticated check if needed
echo -e "${GREEN}  ✓ Cluster role deployed${NC}\n"

echo "  → Applying 3-app-of-apps.yaml (App of Apps)"
oc apply -f "${SCRIPT_DIR}/3-app-of-apps.yaml"
echo "  Waiting for application to sync..."
sleep 15  # TODO: Replace with: oc wait --for=jsonpath='{.status.sync.status}'=Synced application/cluster-config -n openshift-gitops --timeout=300s
echo -e "${GREEN}  ✓ App of Apps deployed${NC}\n"

# Step 9: Done
echo -e "${GREEN}=== Bootstrap Complete ===${NC}\n"
echo "The cluster has been bootstrapped successfully!"
echo ""
echo "Next steps:"
echo "  1. Monitor ArgoCD applications: oc get applications -n openshift-gitops"
echo "  2. Access ArgoCD UI: oc get route cluster-argocd-server -n openshift-gitops"
echo "  3. The htpasswd authentication will be configured automatically via ArgoCD"
echo ""
