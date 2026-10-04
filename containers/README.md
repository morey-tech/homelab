# Containers

This directory contains custom container image definitions for the homelab infrastructure.

## Structure

Each sub-directory represents a separate container image:

```
containers/
├── <container-name>/
│   ├── Containerfile      # OCI-compliant container definition
│   ├── README.md          # Container description and usage
│   └── .containerignore   # Files to exclude from build context
```

## Building Containers

Build a container locally using Podman:

```bash
cd containers/<container-name>
podman build -t <container-name>:latest .
```

Or with Docker:

```bash
cd containers/<container-name>
docker build -f Containerfile -t <container-name>:latest .
```

## Container Dependencies

The CI build system automatically handles container dependencies using a naming convention and explicit configuration:

### Dependency Categories

1. **Base Containers** (Auto-detected)
   - Containers with names ending in `-base`
   - Built first in the pipeline
   - Example: `devspace-base`

2. **Dependent Containers** (Explicitly Listed)
   - Containers that depend on base containers
   - Listed in `.github/workflows/container-build.yml` under `DEPENDENT_CONTAINERS`
   - Built after base containers complete
   - Example: `devspace-homelab` (depends on `devspace-base`)

3. **Independent Containers** (All Others)
   - Containers that don't depend on other project containers
   - Build in parallel with base containers
   - Example: `hf-cli`

### Build Order

```mermaid
graph LR
    A[detect-changes] --> B[build-base-containers]
    A --> C[build-independent-containers]
    B --> D[build-dependent-containers]
    
    style B fill:#e1f5ff
    style D fill:#e1f5ff
    style C fill:#ccffcc
```

**Pipeline Stages:**
1. **Base containers** build first (e.g., `devspace-base`)
2. **Independent containers** build in parallel with base (e.g., `hf-cli`)
3. **Dependent containers** build after base completes (e.g., `devspace-homelab`)

### Adding New Containers

**For a new base container:**
- Name it with the `-base` suffix (e.g., `myapp-base`)
- No workflow configuration needed (auto-detected)

**For a container depending on a base:**
- Add container name to `DEPENDENT_CONTAINERS` in `.github/workflows/container-build.yml`
- Reference the base image in your `FROM` statement

**For an independent container:**
- No special configuration needed
- Will build in parallel with base containers

### Example Dependency Structure

Current containers:
- `devspace-base` → Base container (auto-detected by `-base` suffix)
- `devspace-homelab` → Depends on `devspace-base` (explicitly listed)
- `hf-cli` → Independent container

## Build Cache

All three build stages import and export a [BuildKit registry cache](https://docs.docker.com/build/cache/backends/registry/) at `ghcr.io/morey-tech/homelab/CONTAINER:buildcache`, where `CONTAINER` is the container directory name. Export retains `mode=max` to cache intermediate layers. These existing cache references are unchanged; builds no longer duplicate cache imports and exports through the GitHub Actions cache backend. This does not disable other actions' own caches, such as QEMU's.

The [September 26 homelab build](https://github.com/morey-tech/homelab/actions/runs/36262103755/job/108459791355) spent 324 seconds exporting GHA cache versus 17 seconds exporting registry cache. Registry-only caching removes that duplicate export; actual end-to-end savings and future cache hits must be checked in subsequent builds. Disk cleanup remains unchanged. Existing GHA cache entries are left to expire under GitHub's retention policy.

Workflow-only changes can run detection without selecting an image build. After the reviewed change is committed and pushed, manually dispatch a representative build (this publishes images and updates the cache):

```bash
gh workflow run container-build.yml --ref main -f container=devspace-homelab
gh run list --workflow container-build.yml --limit 5
```

Check the build log for a successful `:buildcache` import, `CACHED` steps where inputs are unchanged, a successful registry cache export, and no `exporting to GitHub Actions Cache` phase. Compare the build-step duration with the previous run. A missing registry cache permits a cold build and is populated on successful export.

## Conventions

- Use `Containerfile` (OCI standard) rather than `Dockerfile`
- Include a `README.md` describing the container's purpose
- Include a `.containerignore` to minimize build context
- Use meaningful labels in the Containerfile
- **All containers must support both arm64 and x86_64 (amd64) architectures**
  - Use `ARG TARGETARCH` for architecture detection during multi-platform builds
  - Download architecture-specific binaries using conditional logic based on `$TARGETARCH`
- **Use `-base` suffix for base containers** that other containers will depend on
