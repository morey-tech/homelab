# Extract public-target counters for the health check. Fail closed on incomplete
# metrics, but leave packet loss itself to the comparison in check-health.sh.
$1 == "process_start_time_seconds" { process = $2; processes++ }
$1 == "smokeping_prober_errors_total" { errors = $2; error_metrics++ }
/^smokeping_(requests_total|response_duration_seconds_count)\{/ && /scope="internet"/ {
    target = $0
    sub(/^.*target="/, "", target)
    sub(/".*$/, "", target)
    if (target !~ /^[a-zA-Z0-9_-]+$/ || $NF !~ /^[0-9]+([.][0-9]+)?([eE][+-]?[0-9]+)?$/) {
        invalid = 1
        next
    }
    if ($0 ~ /^smokeping_requests_total/) {
        sent[target] = $NF
        send_metrics[target]++
    } else {
        received[target] = $NF
        receive_metrics[target]++
    }
}
END {
    if (invalid || processes != 1 || process <= 0 || error_metrics != 1 || errors != "0") exit 1
    print "@process", process
    for (target in sent) {
        if (send_metrics[target] != 1 || receive_metrics[target] != 1) exit 1
        print target, sent[target], received[target]
        targets++
    }
    for (target in received) if (!(target in sent)) exit 1
    if (!targets) exit 1
}
