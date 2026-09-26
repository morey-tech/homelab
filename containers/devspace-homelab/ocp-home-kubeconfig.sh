# Merge the Dev Spaces-mounted OCP Home proxy kubeconfig into interactive shells.
# Not set as a container env var: the dashboard's kubeconfig injection treats
# $KUBECONFIG as a single directory (https://github.com/eclipse-che/che/issues/23972).
if [ -f /etc/ocp-home/kubeconfig ]; then
    export KUBECONFIG="$HOME/.kube/config:/etc/ocp-home/kubeconfig"
fi
