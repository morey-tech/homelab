FROM bitnami/kubectl:1.25 as kubectl

# See here for image contents: https://github.com/microsoft/vscode-dev-containers/tree/v0.245.2/containers/ubuntu/.devcontainer/base.Dockerfile
FROM mcr.microsoft.com/vscode/devcontainers/base:0-ubuntu-22.04

ARG USERNAME=tecno
ARG USER_UID=1001
ARG USER_GID=$USER_UID

# Add non-root user.
RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME --shell /bin/bash

# Install packages, and clean  up apt.
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get install -y sudo libssl-dev libffi-dev python3-dev python3-pip iputils-ping dnsutils \
    && apt-get clean -y && rm -rf /var/lib/apt/lists/*

# Add user to suders file.
RUN echo $USERNAME ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME

# Relative to `.devcontainer/`.
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install -r /tmp/requirements.txt

# Add kubectl to main image
COPY --from=kubectl /opt/bitnami/kubectl/bin/kubectl /usr/local/bin/

RUN VERSION=0.18.5 \
    && wget https://github.com/bitnami-labs/sealed-secrets/releases/download/v${VERSION}/kubeseal-${VERSION}-linux-amd64.tar.gz \
    && tar -xvzf kubeseal-${VERSION}-linux-amd64.tar.gz kubeseal \
    && mv kubeseal /usr/local/bin/ \
    && chmod 755 /usr/local/bin/kubeseal

# Select desired TAG from https://github.com/argoproj/argo-cd/releases
RUN VERSION=v2.8.4 \
    && curl -sSL -o /usr/local/bin/argocd https://github.com/argoproj/argo-cd/releases/download/$VERSION/argocd-linux-amd64 \
    && chmod +x /usr/local/bin/argocd

ENV HELM_VERSION=3.13.1
RUN curl -LO "https://get.helm.sh/helm-v${HELM_VERSION}-linux-amd64.tar.gz" \
    && tar -zxvf "helm-v${HELM_VERSION}-linux-amd64.tar.gz" \
    && mv linux-amd64/helm /usr/local/bin/ \
    && rm -rf "helm-v${HELM_VERSION}-linux-amd64.tar.gz" linux-amd64

# [Optional] Set the default user. Omit if you want to keep the default as root.
USER $USERNAME

COPY .bash_aliases /home/$USERNAME/.bash_aliases
