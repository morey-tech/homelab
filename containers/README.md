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

## Conventions

- Use `Containerfile` (OCI standard) rather than `Dockerfile`
- Include a `README.md` describing the container's purpose
- Include a `.containerignore` to minimize build context
- Use meaningful labels in the Containerfile
