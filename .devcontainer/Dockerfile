# See here for image contents: https://github.com/microsoft/vscode-dev-containers/tree/v0.245.2/containers/ubuntu/.devcontainer/base.Dockerfile
ARG VARIANT="ubuntu-22.04"
FROM mcr.microsoft.com/vscode/devcontainers/base:0-${VARIANT}

RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get install -y libssl-dev libffi-dev python3-dev python3-pip \
    && apt-get clean -y && rm -rf /var/lib/apt/lists/*

# Relative to `.devcontainer/`.
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install -r /tmp/requirements.txt