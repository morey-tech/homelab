#!/bin/sh
# A fresh ICMP session must work while the original session stays silent.
# Never restart solely because Internet destinations are unreachable.
set -eu

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
work=$(mktemp -d "${HEALTH_WORK_DIR:-/var/run/smokeping-health}/check.XXXXXX")
fresh_pid=''
cleanup() {
    if [ -n "$fresh_pid" ]; then
        # Bound cleanup even if the diagnostic pinger does not handle SIGTERM.
        kill -KILL "$fresh_pid" 2>/dev/null || true
        wait "$fresh_pid" 2>/dev/null || true
    fi
    rm -rf "$work"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

snapshot() {
    wget -qO- -T 3 "http://127.0.0.1:$1/metrics" > "$work/metrics" &&
        awk -f "$script_dir/ping-snapshot.awk" "$work/metrics" > "$2"
}

snapshot 9374 "$work/before" || exit 1
sleep 5
snapshot 9374 "$work/after" || exit 1

# Ignore a process/counter reset. A candidate must still be sending and have
# no replies across both snapshots; healthy targets need no extra probes.
awk '
    NR == FNR {
        if ($1 == "@process") process = $2
        else { sent[$1] = $2; received[$1] = $3 }
        next
    }
    $1 == "@process" { same_process = ($2 == process); next }
    same_process && ($1 in sent) && $2 > sent[$1] && $3 == received[$1] {
        print $1, $2, $3
    }
' "$work/before" "$work/after" > "$work/candidates"
[ -s "$work/candidates" ] || exit 0

# Same config, permissions, pod and destinations, but new ICMP sockets/IDs.
# This listener is loopback-only and is never scraped by Alloy. Its counters
# cannot turn the main prober's outage into a success or reset its history.
smokeping_prober --config.file="$script_dir/smokeping.yml" \
    --web.listen-address=127.0.0.1:19374 --log.level=error \
    > "$work/fresh.log" 2>&1 &
fresh_pid=$!
sleep 10
if ! kill -0 "$fresh_pid" 2>/dev/null || ! snapshot 19374 "$work/fresh"; then
    echo 'Fresh ping check unavailable; no evidence to restart the main prober.' >&2
    exit 0
fi
snapshot 9374 "$work/final" || exit 1

# Recheck the original process after the fresh probes. Natural recovery during
# the check must not count as a liveness failure. Require several fresh replies
# to the SAME target, not success from a different provider or from LAN.
if [ "$(head -n 1 "$work/after")" != "$(head -n 1 "$work/final")" ]; then
    exit 0
fi
awk '
    FILENAME == ARGV[1] { sent[$1] = $2; received[$1] = $3; next }
    FILENAME == ARGV[2] { if ($1 != "@process" && $3 >= 5) fresh[$1] = 1; next }
    ($1 in sent) && fresh[$1] && $2 > sent[$1] && $3 == received[$1] { print $1 }
' "$work/candidates" "$work/fresh" "$work/final" > "$work/stuck"
if [ -s "$work/stuck" ]; then
    echo "Stuck ping session: fresh probes received replies while original targets stayed silent: $(tr '\n' ' ' < "$work/stuck")" >&2
    exit 1
fi
