#!/bin/bash
set -e

# Detect project root (works in both DevSpaces and local DevContainer)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "Installing Ansible collections..."
cd "$PROJECT_ROOT/ansible"
ansible-galaxy collection install -r requirements.yml

echo "Ansible collections installed successfully!"

echo "Setting up SSH config for LXC containers..."
mkdir -p ~/.ssh
cat > ~/.ssh/config << 'EOF'
# SSH Config for Homelab LXC Containers
# Ignore host key checking for containers that are frequently destroyed/recreated

# NFS Container
Host nfs nfs.lab nfs.lab.morey.tech 192.168.3.54
    HostName 192.168.3.54
    User labuser
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    LogLevel ERROR

# Batch Job Container
Host batch-job batch batch.lab batch-job.lab batch-job.lab.morey.tech 192.168.3.55
    HostName 192.168.3.55
    User labuser
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    LogLevel ERROR
EOF
chmod 600 ~/.ssh/config

echo "SSH config created successfully!"

echo "Note: GitHub CLI authentication happens automatically on first shell launch."

echo "Verifying Claude CLI installation..."
if command -v claude &> /dev/null; then
    claude --version
    echo "Claude CLI is available!"
else
    echo "Warning: Claude CLI not found. This should be installed in the devspace-base image."
fi

echo "Workspace setup complete!"
