# See here for image contents: https://github.com/microsoft/vscode-dev-containers/tree/v0.245.2/containers/ubuntu/.devcontainer/base.Dockerfile
FROM mcr.microsoft.com/vscode/devcontainers/base:0-ubuntu-22.04

ARG USERNAME=tecno
ARG USER_UID=1001
ARG USER_GID=$USER_UID

# Add non-root user.
RUN groupmod -n $USERNAME vscode \
    && usermod -l $USERNAME vscode \
    && usermod -d /home/tecno -m tecno

# Install packages, and clean  up apt.
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get install -y sudo libssl-dev libffi-dev python3-dev python3-pip iputils-ping dnsutils bash-completion apache2-utils tmux \
    && apt-get clean -y && rm -rf /var/lib/apt/lists/*

# Add user to suders file.
RUN echo $USERNAME ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME

# Relative to `.devcontainer/`.
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install -r /tmp/requirements.txt

# Install `oc` and `kubectl`
ENV OC_VERSION=4.17.0-okd-scos.0
RUN wget https://github.com/openshift/okd/releases/download/${OC_VERSION}/openshift-client-linux-${OC_VERSION}.tar.gz \
    && tar -xvf openshift-client-linux-${OC_VERSION}.tar.gz \
    && mv oc kubectl /usr/local/bin/

ENV KUBECTX_VERSION=v0.9.5
RUN curl -Lo /tmp/kubectx.tar.gz "https://github.com/ahmetb/kubectx/releases/download/${KUBECTX_VERSION}/kubectx_${KUBECTX_VERSION}_linux_x86_64.tar.gz" \
    && tar -xvf /tmp/kubectx.tar.gz -C /tmp \
    && mv /tmp/kubectx /usr/local/bin/kubectx \
    && curl -Lo /tmp/kubens.tar.gz "https://github.com/ahmetb/kubectx/releases/download/${KUBECTX_VERSION}/kubens_${KUBECTX_VERSION}_linux_x86_64.tar.gz" \
    && tar -xvf /tmp/kubens.tar.gz -C /tmp \
    && mv /tmp/kubens /usr/local/bin/kubens

ENV KONFIG_VERSION=v0.2.6
RUN curl -Lo konfig https://github.com/corneliusweig/konfig/raw/${KONFIG_VERSION}/konfig \
    && chmod +x konfig \
    && sudo mv -i konfig /usr/local/bin

ENV KUBENEAT_VERSION=v2.0.4
RUN wget https://github.com/itaysk/kubectl-neat/releases/download/${KUBENEAT_VERSION}/kubectl-neat_linux_amd64.tar.gz \
    && tar -xvzf kubectl-neat_linux_amd64.tar.gz kubectl-neat \
    && mv kubectl-neat /usr/local/bin/kubeneat \
    && chmod 755 /usr/local/bin/kubeneat

ENV KUBESEAL_VERSION=0.18.5
RUN wget https://github.com/bitnami-labs/sealed-secrets/releases/download/v${KUBESEAL_VERSION}/kubeseal-${KUBESEAL_VERSION}-linux-amd64.tar.gz \
    && tar -xvzf kubeseal-${KUBESEAL_VERSION}-linux-amd64.tar.gz kubeseal \
    && mv kubeseal /usr/local/bin/ \
    && chmod 755 /usr/local/bin/kubeseal

# Select desired TAG from https://github.com/argoproj/argo-cd/releases
ENV ARGOCD_VERSION=v2.8.4
RUN curl -sSL -o /usr/local/bin/argocd https://github.com/argoproj/argo-cd/releases/download/$ARGOCD_VERSION/argocd-linux-amd64 \
    && chmod +x /usr/local/bin/argocd \
    && echo 'source <(argocd completion bash)' >> /usr/share/bash-completion/completions/argocd

ENV HELM_VERSION=3.13.1
RUN curl -LO "https://get.helm.sh/helm-v${HELM_VERSION}-linux-amd64.tar.gz" \
    && tar -zxvf "helm-v${HELM_VERSION}-linux-amd64.tar.gz" \
    && mv linux-amd64/helm /usr/local/bin/ \
    && rm -rf "helm-v${HELM_VERSION}-linux-amd64.tar.gz" linux-amd64 \
    && echo 'source <(helm completion bash)' >> /usr/share/bash-completion/completions/helm

ENV K9S_VERSION=v0.30.8
RUN curl -LO "https://github.com/derailed/k9s/releases/download/${K9S_VERSION}/k9s_Linux_amd64.tar.gz" \
    && tar -zxvf "k9s_Linux_amd64.tar.gz" \
    && mv k9s /usr/local/bin/ \
    && rm -rf "k9s_Linux_amd64.tar.gz"

# https://github.com/kubernetes-sigs/kustomize/releases
ENV KUSTOMIZE_VERSION=v5.3.0
RUN curl -Lo /tmp/kustomize.tar.gz https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2F${KUSTOMIZE_VERSION}/kustomize_${KUSTOMIZE_VERSION}_linux_amd64.tar.gz \
    && tar -xvf /tmp/kustomize.tar.gz -C /tmp \
    && mv /tmp/kustomize /usr/local/bin/kustomize \
    && chmod +x /usr/local/bin/kustomize \
    && echo 'source <(kustomize completion bash)' >> /usr/share/bash-completion/completions/kustomize

ENV TERRAFORM_VERSION=1.7.4
RUN curl -LO "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" \
    && unzip terraform_${TERRAFORM_VERSION}_linux_amd64.zip \
    && mv terraform /usr/local/bin/ \
    && rm -rf terraform_${TERRAFORM_VERSION}_linux_amd64.zip

ENV VCLUSTER_VERSION=v0.20.0-beta.1
RUN curl -L -o vcluster "https://github.com/loft-sh/vcluster/releases/download/${VCLUSTER_VERSION}/vcluster-linux-amd64" \
    && install -c -m 0755 vcluster /usr/local/bin \
    && rm -f vcluster

# Add aliases and such
RUN echo 'source /etc/profile.d/bash_completion.sh' >> /etc/bash.bashrc \
    && echo 'alias k="kubectl"' >> /etc/bash.bashrc \
    && echo 'source <(kubectl completion bash)' >> /etc/bash.bashrc \
    && echo 'complete -F __start_kubectl k' >> /etc/bash.bashrc \
    && mkdir -p /home/$USERNAME/.kube/ && touch /home/$USERNAME/.kube/config \
    && chown -R $USERNAME:$USERNAME /home/$USERNAME/.kube/

# [Optional] Set the default user. Omit if you want to keep the default as root.
USER $USERNAME

COPY .bash_aliases /home/$USERNAME/.bash_aliases
