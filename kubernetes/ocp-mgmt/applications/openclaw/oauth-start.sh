#!/bin/sh
set -eu
umask 077
# OAuth proxy reads its client secret only at startup. The liveness probe
# restarts this sidecar when kubelet rotates the projected token.
cp /var/run/secrets/kubernetes.io/serviceaccount/token /oauth-state/client-token
exec /usr/bin/oauth-proxy "$@"
