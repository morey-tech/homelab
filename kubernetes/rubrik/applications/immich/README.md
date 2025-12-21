# Immich Migration: Rubrik → OCP-Home

Migration jobs for moving Immich PostgreSQL database from Rubrik cluster to OCP-Home.

## Context

| Aspect | Rubrik (Source) | OCP-Home (Target) |
|--------|-----------------|-------------------|
| PostgreSQL | 14 (Bitnami) | 16 (CNPG) |
| Vector Extension | pgvecto-rs (`vectors`) | pgvector/vchord (`vector`) |
| Operator | Bitnami Helm | CloudNativePG |

## Why Exclude Vector Tables?

The `face_search` and `smart_search` tables use incompatible vector types:
- Source: `vectors` type from pgvecto-rs
- Target: `vector` type from pgvector

Excluding these tables and recreating with the correct type allows Immich ML to regenerate embeddings.

## Usage

### 1. Create backup on Rubrik
```bash
export KUBECONFIG=/tmp/rubrik-kubeconfig
kubectl apply -f backup-job.yaml
kubectl logs -f job/immich-db-backup -n immich
```

### 2. Restore on OCP-Home
```bash
unset KUBECONFIG  # or set to ocp-home
oc apply -f restore-job.yaml
oc logs -f job/immich-db-restore -n immich
```

### 3. Start Immich
```bash
oc scale deployment immich-server -n immich --replicas=1
```

Immich ML will regenerate vector embeddings automatically via Smart Search and Face Detection jobs.
