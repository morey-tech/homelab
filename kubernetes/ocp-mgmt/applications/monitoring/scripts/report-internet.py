#!/usr/bin/env python3
"""Export observed Internet Quality minutes, daily coverage, and loss episodes.

Read-only Prometheus queries; use a local port-forward to the internal Service.
Dates are UTC, start-inclusive/end-exclusive. Episodes split at midnight and
at missing minutes. They describe observations, not proof of ISP responsibility.
"""
import argparse
import csv
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

PING_TARGETS = {'pfsense': 'lan', 'cloudflare': 'internet', 'google': 'internet', 'quad9': 'internet'}
SERVICE_TARGETS = {'cloudflare-dns': 'dns', 'google-dns': 'dns',
                   'cloudflare-https': 'https', 'google-https': 'https'}
LOSS = 'internet:ping_loss:ratio1m'
SUCCESS = 'internet:service_success:ratio1m'


def utc(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def episodes(points, threshold=0.05):
    """A missing minute ends the episode; never bridge an unobserved interval."""
    active = []
    for timestamp, value in sorted(points):
        if active and (timestamp - active[-1][0] > 61 or value < threshold):
            yield active
            active = []
        if value >= threshold:
            active.append((timestamp, value))
    if active:
        yield active


def summary(day, target, category, points, is_ping):
    values = [value for _, value in points]
    n = len(values)
    return {
        'date_utc': day.isoformat(), 'target': target, 'category': category,
        'observed_minutes': n, 'unknown_minutes': 1440 - n,
        'coverage_percent': round(100 * n / 1440, 3),
        'mean_loss_percent': round(100 * sum(values) / n, 3) if n and is_ping else '',
        'service_success_percent': round(100 * sum(values) / n, 3) if n and not is_ping else '',
        'minutes_loss_ge_5_percent': sum(v >= 0.05 for v in values) if is_ping else '',
        'minutes_loss_ge_99_percent': sum(v >= 0.99 for v in values) if is_ping else '',
    }


def fetch_day(base_url, day):
    # An instant range-vector query returns stored timestamps, avoiding the
    # instant-selector lookback that could repeat an old minute across a gap.
    start = datetime.combine(day, datetime.min.time(), timezone.utc).timestamp()
    query = '{__name__=~"internet:ping_loss:ratio1m|internet:service_success:ratio1m"}[1d]'
    params = urlencode({'query': query, 'time': start + 86400 - 0.001})
    with urlopen(base_url.rstrip('/') + '/api/v1/query?' + params, timeout=90) as response:
        payload = json.load(response)
    if payload.get('status') != 'success' or payload.get('warnings'):
        raise RuntimeError(f'Incomplete Prometheus response: {payload}')
    if payload['data']['resultType'] != 'matrix':
        raise RuntimeError('Expected stored range-vector samples')
    grouped = {}
    for series in payload['data']['result']:
        labels = series['metric']
        key = labels['__name__'], labels['target']
        if key in grouped:
            raise RuntimeError(f'Ambiguous duplicate target: {key}')
        points = [(float(t), float(v)) for t, v in series['values'] if math.isfinite(float(v))]
        if any(not 0 <= value <= 1 for _, value in points):
            raise RuntimeError(f'Invalid ratio for {key}')
        if any(not start <= t < start + 86400 for t, _ in points) or len(points) > 1440:
            raise RuntimeError(f'Unexpected recording interval for {key}')
        grouped[key] = points
    return grouped


def main():
    today = datetime.now(timezone.utc).date()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:19090')
    parser.add_argument('--start', type=date.fromisoformat, default=today - timedelta(days=7))
    parser.add_argument('--end', type=date.fromisoformat, default=today)
    parser.add_argument('--output', type=Path, required=True, help='New directory for CSV files')
    args = parser.parse_args()
    if not args.start < args.end <= today:
        parser.error('Use completed UTC days, with start before end and end no later than today')
    args.output.mkdir(parents=True, exist_ok=False)
    sample_fields = ['timestamp_utc', 'metric', 'target', 'ratio']
    daily_fields = list(summary(args.start, '', '', [], True))
    episode_fields = ['date_utc', 'target', 'scope', 'first_observation_utc', 'last_observation_utc',
                      'observed_degraded_minutes', 'max_loss_percent', 'mean_loss_percent']
    with (args.output / 'samples.csv').open('w', newline='') as samples_file, \
         (args.output / 'daily.csv').open('w', newline='') as daily_file, \
         (args.output / 'episodes.csv').open('w', newline='') as episodes_file:
        samples = csv.DictWriter(samples_file, fieldnames=sample_fields)
        daily = csv.DictWriter(daily_file, fieldnames=daily_fields)
        events = csv.DictWriter(episodes_file, fieldnames=episode_fields)
        for writer in [samples, daily, events]:
            writer.writeheader()
        day = args.start
        while day < args.end:
            data = fetch_day(args.url, day)
            for (metric, target), points in sorted(data.items()):
                for timestamp, value in points:
                    samples.writerow({'timestamp_utc': utc(timestamp), 'metric': metric,
                                      'target': target, 'ratio': value})
            for metric, targets in [(LOSS, PING_TARGETS), (SUCCESS, SERVICE_TARGETS)]:
                # Include all configured targets even when completely absent.
                for target, category in targets.items():
                    points = data.get((metric, target), [])
                    daily.writerow(summary(day, target, category, points, metric == LOSS))
                    if metric == LOSS:
                        for event in episodes(points):
                            values = [v for _, v in event]
                            events.writerow({'date_utc': day.isoformat(), 'target': target, 'scope': category,
                                'first_observation_utc': utc(event[0][0]), 'last_observation_utc': utc(event[-1][0]),
                                'observed_degraded_minutes': len(event),
                                'max_loss_percent': round(100 * max(values), 3),
                                'mean_loss_percent': round(100 * sum(values) / len(values), 3)})
            day += timedelta(days=1)
    (args.output / 'metadata.json').write_text(json.dumps({
        'complete': True, 'generated_at_utc': utc(datetime.now(timezone.utc).timestamp()),
        'start_inclusive_utc': args.start.isoformat(), 'end_exclusive_utc': args.end.isoformat(),
        'ping_targets': PING_TARGETS, 'service_targets': SERVICE_TARGETS,
        'interval_seconds': 60, 'degraded_loss_threshold': 0.05, 'unreachable_loss_threshold': 0.99,
        'notes': ['Means cover observed minutes only. Compare coverage before making availability claims.',
                  'Episodes split at missing minutes and UTC midnight. Times are observation times.',
                  'The absence of metadata.json indicates an incomplete export.',
                  'ICMP measures round-trip loss; these data alone do not assign ISP fault.'],
    }, indent=2) + '\n')
    print(f'Exported {args.start} through {args.end} (exclusive) to {args.output}')


if __name__ == '__main__':
    main()
