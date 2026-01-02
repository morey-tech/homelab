#!/bin/bash
set -e

echo "Installing Ansible collections..."
cd /workspaces/homelab/ansible
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

echo "Setting up GitHub CLI authentication..."

# Extract GitHub token from git credential helper
GITHUB_TOKEN=$(printf "protocol=https\nhost=github.com\n\n" | git credential fill 2>/dev/null | grep "^password=" | cut -d= -f2)

if [ -n "$GITHUB_TOKEN" ]; then
    # Authenticate gh CLI
    if echo "$GITHUB_TOKEN" | gh auth login --with-token 2>/dev/null; then
        echo "GitHub CLI authenticated successfully!"
        gh auth status
    else
        echo "Warning: Failed to authenticate gh CLI. Manual login may be required."
    fi
    # Clear token from memory
    unset GITHUB_TOKEN
else
    echo "No GitHub credentials found. Skipping gh CLI authentication."
    echo "To authenticate manually, run: gh auth login"
fi

echo "Workspace setup complete!"
