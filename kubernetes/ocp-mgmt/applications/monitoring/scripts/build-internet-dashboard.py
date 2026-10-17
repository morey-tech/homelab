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

    return {'uid': 'internet-quality', 'title': 'Internet Quality', 'schemaVersion': 39,
            'version': 1, 'editable': False, 'tags': ['homelab', 'infrastructure', 'internet'],
            'description': 'IPv4 quality from ocp-mgmt. Local baseline, independent external targets, '
                           'DNS/HTTPS checks and WAN traffic. Unknown monitoring intervals remain gaps.',
            'timezone': 'utc', 'refresh': '30s', 'time': {'from': 'now-6h', 'to': 'now'},
            'graphTooltip': 1, 'panels': panels, 'templating': {'list': []},
            'links': [{'title': 'Homelab dashboards', 'type': 'dashboards', 'tags': ['homelab'],
                       'asDropdown': True, 'includeVars': False, 'keepTime': True}]}


if __name__ == '__main__':
    (ROOT / 'dashboards/internet.json').write_text(json.dumps(build(), indent=2) + '\n')
