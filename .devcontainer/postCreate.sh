#!/bin/bash
set -e

echo "Installing Ansible collections..."
cd /workspaces/homelab/ansible
ansible-galaxy collection install -r requirements.yml

echo "Ansible collections installed successfully!"
