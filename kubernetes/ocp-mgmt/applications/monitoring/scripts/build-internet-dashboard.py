#!/usr/bin/env python3
"""Build Internet Quality using the infrastructure store and guarded rules."""
import copy
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
DS = {'type': 'prometheus', 'uid': 'infrastructure'}


def build():
    panels = []

    def panel(title, expressions, unit, description, *, height=7, kind='timeseries', maximum=None):
        index = len(panels)
        defaults = {'unit': unit, 'min': 0, 'noValue': 'Unknown',
                    'custom': {'drawStyle': 'line', 'lineWidth': 1, 'fillOpacity': 0,
                               'spanNulls': False, 'showPoints': 'never'}}
        if maximum is not None:
            defaults['max'] = maximum
        result = {'id': index + 1, 'title': title, 'type': kind, 'datasource': DS,
                  'description': description,
                  'gridPos': {'x': 12 * (index % 2), 'y': 7 * (index // 2), 'w': 12, 'h': height},
                  'fieldConfig': {'defaults': defaults, 'overrides': []},
                  'targets': [{'refId': chr(65 + n), 'expr': expr, 'legendFormat': legend,
                               'datasource': DS, 'range': True, 'instant': False, 'interval': '1m'}
                              for n, (expr, legend) in enumerate(expressions)],
                  'options': {'legend': {'displayMode': 'table', 'placement': 'bottom',
                                         'calcs': ['lastNotNull', 'max']},
                              'tooltip': {'mode': 'multi', 'sort': 'desc'}}}
        panels.append(result)
        return result

    loss = 'internet:ping_loss:ratio1m'
    service = 'internet:service_success:ratio1m'
    panel('Packet loss — one minute', [(f'100 * {loss}', '{{target}}')], 'percent',
          'Estimated ICMP round-trip loss from sent/received counter rates. One ping/s per target. '
          'Local socket errors, stopped sending, restarts and missing scrapes are unknown. '
          'Late replies can cross window boundaries; loss is clamped to 0–100%.', maximum=100)
    panel('Packet loss — five minutes', [('100 * internet:ping_loss:ratio5m', '{{target}}')], 'percent',
          'Mean of five complete one-minute observations; a missing minute creates a gap.', maximum=100)
    for quantile in ['p50', 'p95']:
        panel(f'Round-trip latency — {quantile}',
              [(f'internet:ping_rtt_seconds:{quantile}_5m', '{{target}}')], 's',
              'Histogram estimate over five minutes, for replies received only. Lost packets have no latency. '
              'The local pfSense baseline includes the pod and cluster network path.')
    panel('DNS / HTTPS success — one minute', [(f'100 * {service}', '{{target}}')], 'percent',
          'Four probes/minute. A valid failed probe is 0%; failed collection is unknown. '
          'HTTPS also depends on cluster DNS, TLS and the remote application.', maximum=100)
    panel('DNS / HTTPS duration', [(
          'probe_duration_seconds{job="internet_services"} '
          'and (up{job="internet_services"} == 1) '
          'and (time() - timestamp(probe_duration_seconds{job="internet_services"}) < 30)', '{{target}}')], 's',
          'Whole probe duration including failed-probe timeouts. This is not ICMP round-trip latency.')
    panel('Loss by minute', [(f'({loss} >= bool 0.05) + ({loss} >= bool 0.99)', '{{target}}')], 'short',
          '0: below 5% loss; 1: at least 5%; 2: at least 99%. Gaps are unknown, not healthy.', kind='state-timeline', maximum=2)
    state = panels[-1]
    state['fieldConfig']['defaults']['mappings'] = [{'type': 'value', 'options': {
        '0': {'text': '<5% loss', 'color': 'green'}, '1': {'text': 'Degraded ≥5%', 'color': 'orange'},
        '2': {'text': 'Unreachable ≥99%', 'color': 'red'}}}]
    state['options'] = {'mergeValues': True, 'showValue': 'never', 'rowHeight': 0.8,
                        'legend': {'displayMode': 'list', 'placement': 'bottom'}, 'tooltip': {'mode': 'single'}}
    panel('Valid measurement coverage — rolling 24 hours', [
        (f'100 * count_over_time({loss}[24h]) / 1440', '{{target}} ping'),
        (f'100 * count_over_time({service}[24h]) / 1440', '{{target}}'),
    ], 'percent', 'Valid one-minute observations divided by 1440 expected minutes. '
       'Starts below 100% during the first day. A missing series is unknown. '
       'Interpret every daily statistic alongside coverage.', maximum=100)
    panel('Mean loss — rolling 24 hours', [(f'100 * avg_over_time({loss}[24h])', '{{target}}')], 'percent',
          'Mean one-minute packet loss over observed minutes only; does not impute missing data.', maximum=100)
    panel('DNS / HTTPS success — rolling 24 hours', [(f'100 * avg_over_time({service}[24h])', '{{target}}')], 'percent',
          'Successful scheduled probes during observed minutes only; compare with measurement coverage.', maximum=100)

    # Reuse the existing tested interface query, narrowed to the documented WAN.
    spec = importlib.util.spec_from_file_location('pfsense', ROOT / 'scripts/build-pfsense-dashboard.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PHYSICAL = "ix2"
    source = module.build()
    for direction, title in [('transmit', 'WAN upload'), ('receive', 'WAN download')]:
        original = next(p for p in source['panels'] if p['title'] == f'Physical interface {direction}')
        p = panel(title, [], 'bps', 'Existing pfSense ix2 WAN counters, five-minute average. '
                  'Compare with loss and latency to identify possible link saturation.')
        p['targets'] = copy.deepcopy(original['targets'])

    p = panel('DNS / HTTPS reachability by target', [
        (f'({service} == bool 1) + ({service} > bool 0)', '{{target}}'),
    ], 'short', 'Compare concurrent failures across targets and with the LAN/ping baseline. '
       '0: all probes failed; 1: some failed; 2: all succeeded. Missing collection remains a gap. '
       'Targets sharing a provider are not independent votes: Google/YouTube, Amazon/AWS, '
       'Quay/Red Hat, and the two Plex endpoints may share infrastructure. '
       'Registry authentication challenges and expected AWS API errors count as reachable.',
       kind='state-timeline', maximum=2)
    p['gridPos'].update(w=24, h=12)
    p['fieldConfig']['defaults']['mappings'] = [{'type': 'value', 'options': {
        '0': {'text': 'Probe failed', 'color': 'red'}, '1': {'text': 'Intermittent', 'color': 'orange'},
        '2': {'text': 'Reachable', 'color': 'green'}}}]
    p['options'] = {'mergeValues': True, 'showValue': 'never', 'rowHeight': 0.8,
                    'legend': {'displayMode': 'list', 'placement': 'bottom'}, 'tooltip': {'mode': 'single'}}

    # Preserve existing panel IDs, including the full-width service timeline.
    # Insert modem context below WAN traffic, with upload/download columns aligned.
    service_timeline = p

    def fresh(metric, job='modem', instance='hitron', extra=''):
        selector = f'{metric}{{job="{job}",instance="{instance}"{extra}}}'
        return f'({selector} and (time() - timestamp({selector}) < 180))'

    modem_up = fresh('up')
    modem_success = fresh('hitron_collection_success')
    modem_recent = fresh('hitron_last_success_timestamp_seconds')
    modem_valid = (f'({modem_up} == 1) and on(job, instance) ({modem_success} == 1) '
                   f'and on(job, instance) ({modem_recent} > 0) '
                   f'and on(job, instance) (time() - {modem_recent} < 150)')

    def observed(expr):
        return f'({expr}) and on(job, instance) ({modem_valid})'

    def modem_panel(title, expressions, unit, description, **kwargs):
        p = panel(title, expressions, unit, description, **kwargs)
        index = len(panels) - 14
        p['gridPos'].update(x=12 * (index % 2), y=42 + 7 * (index // 2))
        # Do not display an earlier successful value as the latest reading.
        p['options']['legend']['calcs'] = ['last', 'max']
        return p

    for direction, title in [('transmit', 'Modem WAN upload — packets'),
                             ('receive', 'Modem WAN download — packets')]:
        selector = f'hitron_wan_packets_total{{job="modem",instance="hitron",direction="{direction}"}}'
        current = fresh('hitron_wan_packets_total', extra=f',direction="{direction}"')
        modem_panel(title, [(observed(f'rate({selector}[5m]) and {current}'),
                             f'Hitron {direction}')], 'pps',
                    'Five-minute packet rate, aligned beneath the matching pfSense WAN bit-rate panel. '
                    'Packet counts and bits/s are different units, not interchangeable throughput measurements. '
                    'Bridge-mode counter coverage is not yet verified. Failed or stale collection creates gaps.')

    pf_up = fresh('up', 'pfsense', 'pfsense')
    modem_panel('Modem / pfSense uptime', [
        (observed(fresh('hitron_interface_uptime_seconds')), 'Hitron {{interface}} uptime'),
        (f'{fresh("sysUpTime", "pfsense", "pfsense")} and on(job, instance) ({pf_up} == 1)',
         'pfSense SNMP agent uptime'),
    ], 's', 'Compare resets on a shared time axis. Hitron LAN/WAN uptime reset semantics are unverified. '
       'pfSense sysUpTime is SNMP agent uptime, not firewall uptime: a service restart can reset it independently.')
    health = modem_panel('Modem / pfSense collection health', [
        (pf_up, 'pfSense SNMP scrape'),
        (modem_up, 'Modem exporter scrape'),
        (f'{modem_success} and on(job, instance) ({modem_up} == 1)', 'Modem API collection'),
    ], 'short', 'Scrape health and modem API collection are separate. An API failure can mean authentication, '
       'transport or payload failure; it does not prove an ISP outage. Missing or stale samples stay unknown.',
       kind='state-timeline', maximum=1)
    health['fieldConfig']['defaults']['mappings'] = [{'type': 'value', 'options': {
        '0': {'text': 'Failed', 'color': 'red'}, '1': {'text': 'Successful', 'color': 'green'}}}]
    health['options'] = {'mergeValues': True, 'showValue': 'never', 'rowHeight': 0.8,
                         'legend': {'displayMode': 'list', 'placement': 'bottom'},
                         'tooltip': {'mode': 'single'}}
    modem_panel('Modem API collection duration', [
        (f'{fresh("hitron_collection_duration_seconds")} and on(job, instance) ({modem_up} == 1)', 'Collection duration'),
    ], 's', 'Duration of the most recently completed poll, including failed polls and login retries. '
       'Not ping RTT. Available while the exporter is reachable, even when modem collection fails.')
    modem_panel('Modem last successful collection age', [
        (f'(time() - ({modem_recent} > 0)) and on(job, instance) ({modem_up} == 1)', 'Age of last success'),
    ], 's', 'Continues rising during modem API failures while exporter collection is working. '
       'Unknown before the first successful poll or when the exporter scrape is failed/stale.')
    modem_panel('Modem collection errors / logins', [
        (f'increase({metric}{{job="modem",instance="hitron"}}[5m]) '
         f'and {fresh(metric)} and on(job, instance) ({modem_up} == 1)', legend)
        for metric, legend in [('hitron_collection_errors_total', 'Failed polls / 5m'),
                               ('hitron_login_attempts_total', 'Login attempts / 5m')]
    ], 'short', 'Estimated increases over five minutes, handling exporter counter resets. '
       'Login spikes can identify session renewal; no credential values are exposed.')
    info = modem_panel('Modem model / firmware / mode', [(observed(fresh('hitron_info')),
                        '{{model}} · {{firmware}} · {{mode}}')], 'short',
                       'Current model, firmware and operating mode. Unknown if collection is failed or stale.', kind='stat')
    info['targets'][0].update(instant=True, range=False)
    info['options'] = {'reduceOptions': {'calcs': ['last'], 'fields': '', 'values': False},
                       'textMode': 'name', 'colorMode': 'none', 'graphMode': 'none'}
    service_timeline['gridPos']['y'] = 70
    panels.sort(key=lambda p: (p['gridPos']['y'], p['gridPos']['x']))

    return {'uid': 'internet-quality', 'title': 'Internet Quality', 'schemaVersion': 39,
            'version': 1, 'editable': False, 'tags': ['homelab', 'infrastructure', 'internet'],
            'description': 'IPv4 quality from ocp-mgmt. Local baseline, independent external targets, '
                           'DNS/HTTPS checks, pfSense WAN traffic and Hitron modem telemetry. Unknown monitoring intervals remain gaps.',
            'timezone': 'utc', 'refresh': '30s', 'time': {'from': 'now-6h', 'to': 'now'},
            'graphTooltip': 1, 'panels': panels, 'templating': {'list': []},
            'links': [{'title': 'Homelab dashboards', 'type': 'dashboards', 'tags': ['homelab'],
                       'asDropdown': True, 'includeVars': False, 'keepTime': True}]}


if __name__ == '__main__':
    (ROOT / 'dashboards/internet.json').write_text(json.dumps(build(), indent=2) + '\n')
