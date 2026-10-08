#!/usr/bin/env python3
"""Generate the Git-provisioned dashboard; standard library only."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLUSTERS = {
    'ocp-mgmt': {'title': 'OCP Management', 'nodes': ('ms-02', 'ms-03', 'ms-04', 'tr-gpu'),
                 'gpu': 'nvidia', 'network_devices': 'en.*|eth.*'},
    'ocp-home': {'title': 'OCP Home', 'nodes': ('ocp-home-01.rh-lab.morey.tech',),
                 'gpu': 'intel', 'network_devices': 'bond0'},
}


def fresh(selector):
    return f'({selector} and (time() - timestamp({selector}) < 180))'


def source_up(selector):
    return f'(max({fresh(selector)}) == 1)'


KSM = source_up('up{job="kube-state-metrics",endpoint="https-main"}')
CVO = source_up('up{job="cluster-version-operator"}')
PROM = source_up('up{job="prometheus-k8s"}')
WATCHDOG = source_up('ALERTS{alertname="Watchdog",alertstate="firing"}')
AVAILABLE = fresh('cluster_operator_conditions{condition="Available"}')
# Watchdog is the always-firing platform alert: it proves alert evaluation data
# is present before an absent critical/warning series can be interpreted as zero.
KNOWN = f'{KSM} and on() {CVO} and on() {PROM} and on() {WATCHDOG} and on() (count({AVAILABLE}) > 0)'
PROBLEMS = '(count(count by (name) (cluster_operator_conditions{condition="Available"} == 0 or cluster_operator_conditions{condition=~"Degraded|Failing"} == 1)) or vector(0))'
CRITICAL = '(count(ALERTS{alertstate="firing",severity="critical"}) or vector(0))'
WARNING = '(count(ALERTS{alertstate="firing",severity="warning"}) or vector(0))'
PROGRESSING = '(count(cluster_operator_conditions{condition="Progressing"} == 1) or vector(0))'


def node_regex(nodes):
    # PromQL regex strings need both literal dots and escaped backslashes.
    return json.dumps('|'.join(re.escape(node) for node in nodes))


def status_queries(nodes):
    ready = 'sum(max by (node) (' + fresh('kube_node_status_condition{condition="Ready",status="true",node=~' + node_regex(nodes) + '}') + ')) or vector(0)'
    bad = f'clamp_max((({ready}) != bool {len(nodes)}) + ({PROBLEMS} > bool 0) + ({CRITICAL} > bool 0), 1)'
    attention = f'clamp_max(({WARNING} > bool 0) + ({PROGRESSING} > bool 0), 1)'
    health = f'(clamp_max(2 * ({bad}) + ({attention}), 2) and on() ({KNOWN})) or vector(-1)'
    return ready, health


def guarded(expr, gate=KNOWN):
    return f'({expr}) and on() ({gate})'


def target(expr, instant=True, legend=''):
    return {'refId': 'A', 'expr': expr, 'instant': instant, 'range': not instant,
            'legendFormat': legend, 'datasource': {'type': 'prometheus', 'uid': 'ocp-mgmt'}, 'editorMode': 'code'}


def panel(title, expr, x, y, w, h, kind='stat', unit='short', description=''):
    defaults = {'unit': unit, 'noValue': 'Unknown', 'decimals': 0,
                'color': {'mode': 'thresholds'},
                'thresholds': {'mode': 'absolute', 'steps': [{'color': 'green', 'value': None}]}}
    p = {'title': title, 'type': kind, 'datasource': {'type': 'prometheus', 'uid': 'ocp-mgmt'}, 'description': description,
         'gridPos': {'x': x, 'y': y, 'w': w, 'h': h},
         'targets': [target(expr, kind != 'timeseries')],
         'fieldConfig': {'defaults': defaults, 'overrides': []}}
    if kind == 'stat':
        p['options'] = {'reduceOptions': {'calcs': ['last'], 'fields': '', 'values': False},
                        'colorMode': 'background', 'graphMode': 'none', 'textMode': 'auto',
                        'orientation': 'auto', 'justifyMode': 'auto'}
    elif kind == 'timeseries':
        defaults.update({'min': 0, 'max': 100, 'decimals': 1, 'color': {'mode': 'palette-classic'},
                         'custom': {'drawStyle': 'line', 'lineWidth': 2, 'fillOpacity': 10,
                                    'spanNulls': False}})
        p['options'] = {'legend': {'displayMode': 'list', 'placement': 'bottom', 'showLegend': True},
                        'tooltip': {'mode': 'multi', 'sort': 'desc'}}
        p['targets'][0]['legendFormat'] = '{{instance}}'
    return p


def mapping(p, values):
    p['fieldConfig']['defaults']['mappings'] = [{'type': 'value', 'options': {
        str(k): {'text': text, 'color': color} for k, (text, color) in values.items()}}]


def table(title, expr, x, description, columns):
    p = panel(title, expr, x, 16, 12, 6, 'table', description=description)
    p['targets'][0]['format'] = 'table'
    p['options'] = {'showHeader': True, 'cellHeight': 'sm', 'footer': {'show': False}}
    p['fieldConfig']['defaults']['noValue'] = '—'
    p['transformations'] = [{'id': 'filterFieldsByName', 'options': {'include': {'names': columns}}}]
    return p


def build(cluster='ocp-mgmt'):
    config = CLUSTERS[cluster]
    nodes = config['nodes']
    ready, health = status_queries(nodes)
    panels = []
    p = panel('Cluster health', health, 0, 0, 4, 4, description=f'Healthy: {len(nodes)} expected nodes Ready, no operator problems or critical/warning alerts. Attention: warnings or progressing operators. Unhealthy: missing/unready nodes, unavailable/degraded/failing operators, or critical alerts. Unknown: required monitoring sources or Watchdog missing/down/stale (>180 seconds). Query errors must be treated as unknown.')
    mapping(p, {-1: ('Unknown', 'gray'), 0: ('Healthy', 'green'), 1: ('Attention', 'yellow'), 2: ('Unhealthy', 'red')})
    panels.append(p)
    p = panel(f'Ready nodes / {len(nodes)}', guarded(ready, KSM), 4, 0, 4, 4,
              description=f'Expected: {", ".join(nodes)}. Missing node series count as not Ready when kube-state-metrics is healthy.')
    p['fieldConfig']['defaults']['thresholds']['steps'] = [{'color': 'red', 'value': None}, {'color': 'green', 'value': len(nodes)}]
    panels.append(p)
    for title, expr, x, color in [('Operator problems', PROBLEMS, 8, 'red'), ('Critical alerts', CRITICAL, 12, 'red'), ('Warning alerts', WARNING, 16, 'yellow')]:
        p = panel(title, guarded(expr), x, 0, 4, 4,
                  description='Zero is shown only when monitoring sources and the Watchdog heartbeat are available. Operator problems count distinct operators, including the version operator Failing condition.')
        p['fieldConfig']['defaults']['thresholds']['steps'].append({'color': color, 'value': 1})
        panels.append(p)
    p = panel('Source age', 'max(time() - timestamp(up{job="kube-state-metrics",endpoint="https-main"} or up{job="cluster-version-operator"} or ALERTS{alertname="Watchdog",alertstate="firing"}))', 20, 0, 4, 4, unit='s', description='Age of the oldest available core source sample. Missing sources are detected by Cluster health.')
    p['fieldConfig']['defaults']['thresholds']['steps'] += [{'color': 'yellow', 'value': 90}, {'color': 'red', 'value': 180}]
    panels.append(p)
    node_filter = 'job="node-exporter",instance=~' + node_regex(nodes)
    node_up = fresh('up{' + node_filter + '}') + ' == 1'
    cpu = f'(100 * (1 - avg by (instance) (rate(node_cpu_seconds_total{{{node_filter},mode="idle"}}[5m])))) and on(instance) ({node_up})'
    memory = f'(100 * (1 - node_memory_MemAvailable_bytes{{{node_filter}}} / node_memory_MemTotal_bytes{{{node_filter}}})) and on(instance) ({node_up})'
    panels += [panel('Node CPU usage', cpu, 0, 4, 12, 6, 'timeseries', 'percent'),
               panel('Node memory usage', memory, 12, 4, 12, 6, 'timeseries', 'percent')]
    for i, node in enumerate(nodes):
        expr = f'(max({fresh(f"kube_node_status_condition{{condition=\"Ready\",status=\"true\",node=\"{node}\"}}")}) or vector(-1))'
        p = panel(node + ' readiness', guarded(expr, KSM), i * (24 // len(nodes)), 10, 24 // len(nodes), 3)
        mapping(p, {-1: ('Missing', 'red'), 0: ('Not Ready', 'red'), 1: ('Ready', 'green')})
        panels.append(p)
    if config['gpu'] == 'nvidia':
        gpu_up = source_up('up{job="nvidia-dcgm-exporter"}')
        gpu = lambda name: fresh(name + '{hostname="tr-gpu",gpu="0"}')
        vram = f'100 * {gpu("DCGM_FI_DEV_FB_USED")} / ({gpu("DCGM_FI_DEV_FB_USED")} + {gpu("DCGM_FI_DEV_FB_FREE")})'
        gpu_panels = [
            ('GPU utilization', gpu('DCGM_FI_DEV_GPU_UTIL'), 'percent'),
            ('GPU memory used', vram, 'percent'),
            ('GPU temperature', gpu('DCGM_FI_DEV_GPU_TEMP'), 'celsius'),
            ('GPU power', gpu('DCGM_FI_DEV_POWER_USAGE'), 'watt'),
        ]
        gpu_description = 'Existing DCGM telemetry for RTX 3090 GPU 0 on tr-gpu.'
    else:
        gpu_up = source_up('up{job="intel-gpu-exporter",namespace="openshift-nfd"}')
        gpu = lambda name: fresh(name + '{job="intel-gpu-exporter",namespace="openshift-nfd"}')
        gpu_panels = [
            ('GPU render utilization', gpu('igpu_engines_render_3d_0_busy'), 'percent'),
            ('GPU video utilization', gpu('igpu_engines_video_0_busy'), 'percent'),
            ('GPU frequency', gpu('igpu_frequency_actual') + ' * 1000000', 'hertz'),
            ('GPU power', gpu('igpu_power_gpu'), 'watt'),
        ]
        gpu_description = 'Existing Intel iGPU exporter on OCP Home; video panel covers video engine 0.'
    for i, (title, expr, unit) in enumerate(gpu_panels):
        p = panel(title, guarded(expr, gpu_up), i * 6, 13, 6, 3, unit=unit,
                  description=gpu_description + ' Missing/down/stale telemetry displays Unknown.')
        p['options']['colorMode'] = 'value'
        p['fieldConfig']['defaults']['color'] = {'mode': 'fixed', 'fixedColor': 'blue'}
        panels.append(p)
    panels += [table('Active warning and critical alerts', 'ALERTS{alertstate="firing",severity=~"warning|critical"}', 0,
                     'An empty table means no active warning/critical alerts only if Cluster health has known data. Watchdog and informational alerts are omitted.', ['alertname', 'severity', 'namespace', 'node']),
               table('Operator problems', 'max by (name, condition) (cluster_operator_conditions{condition="Available"} == 0 or cluster_operator_conditions{condition=~"Degraded|Failing"} == 1)', 12,
                     'Available=0 or Degraded/Failing=1. An empty table means no problems only when Cluster health has known data.', ['name', 'condition'])]
    # Keep existing panel IDs while making room below CPU/memory for traffic.
    for p in panels:
        if p['gridPos']['y'] >= 10:
            p['gridPos']['y'] += 6
    network_filter = node_filter + ',device=~' + json.dumps(config['network_devices'])
    network_scope = ('bond0 only; its physical members are excluded to avoid counting traffic twice.'
                     if cluster == 'ocp-home' else
                     'Physical Ethernet interfaces (en*/eth*) separately, including idle ports; virtual interfaces are excluded.')
    for direction, x in [('receive', 0), ('transmit', 12)]:
        counter = f'node_network_{direction}_bytes_total{{{network_filter}}}'
        expr = (f'8 * max by (instance, device) ((rate({counter}[5m]) and {fresh(counter)}) '
                f'and on(job, instance) ({node_up}))')
        p = panel('Node network ' + direction, expr, x, 10, 12, 6, 'timeseries', 'bps',
                  description='Five-minute average bits/s per node and interface. ' + network_scope +
                              ' Rates handle counter resets and require two samples. Failed scrapes or samples older than 180 seconds show gaps; idle interfaces remain zero. No cluster traffic total is inferred.')
        p['fieldConfig']['defaults'].pop('max')
        p['targets'][0]['legendFormat'] = '{{instance}} · {{device}}'
        panels.append(p)
    for i, p in enumerate(panels, 1):
        p['id'] = i
        p['datasource']['uid'] = cluster
        for query in p['targets']:
            query['datasource']['uid'] = cluster
    return {'uid': cluster + '-overview', 'title': config['title'] + ' Overview', 'tags': ['homelab', 'openshift', cluster],
            'schemaVersion': 39, 'version': 1, 'editable': False, 'timezone': 'browser', 'refresh': '30s',
            'time': {'from': 'now-6h', 'to': 'now'}, 'panels': panels, 'templating': {'list': []},
            'links': [{'title': 'Cluster dashboards', 'type': 'dashboards', 'tags': ['homelab'], 'asDropdown': True, 'includeVars': False, 'keepTime': True},
                      {'title': 'OpenShift Console', 'type': 'link', 'url': f'https://console-openshift-console.apps.{cluster}.rh-lab.morey.tech', 'targetBlank': True},
                      {'title': 'OpenShift Alerts', 'type': 'link', 'url': f'https://console-openshift-console.apps.{cluster}.rh-lab.morey.tech/monitoring/alerts', 'targetBlank': True}]}


if __name__ == '__main__':
    for cluster in CLUSTERS:
        (ROOT / f'dashboards/{cluster}.json').write_text(json.dumps(build(cluster), indent=2) + '\n')
