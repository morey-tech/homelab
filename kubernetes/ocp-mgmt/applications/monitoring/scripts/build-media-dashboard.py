#!/usr/bin/env python3
"""Build pod resource graphs for the OCP Home media services."""
import json
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
DS = {'type': 'prometheus', 'uid': 'ocp-home'}
INFRA = {'type': 'prometheus', 'uid': 'infrastructure'}
PRIMARY = [('plex', 'Plex'), ('sabnzbd', 'SABnzbd')]
SECONDARY = [('sonarr', 'Sonarr'), ('radarr', 'Radarr'), ('bazarr', 'Bazarr'),
             ('lidarr', 'Lidarr'), ('overseerr', 'Overseerr'), ('tautulli', 'Tautulli'),
             ('profilarr', 'Profilarr'), ('maintainerr', 'Maintainerr'), ('cleanuparr', 'Cleanuparr')]


def fresh(selector):
    return f'({selector} and (time() - timestamp({selector}) < 180))'


def pod_filter(app):
    # Current private GitOps apps are Deployments in dedicated namespaces.
    return f'namespace="{app}",pod=~"{app}-[a-z0-9]+-[a-z0-9]+"'


def running(app):
    phase = f'kube_pod_status_phase{{job="kube-state-metrics",endpoint="https-main",{pod_filter(app)},phase="Running"}}'
    up = fresh('up{job="kube-state-metrics",endpoint="https-main"}')
    return f'(max by (namespace, pod) ({fresh(phase)} == 1)) and on() (max({up}) == 1)'


def container_metric(metric, app, extra):
    selector = f'{metric}{{job="kubelet",metrics_path="/metrics/cadvisor",{pod_filter(app)},{extra}}}'
    return selector


def collected(expr):
    up = fresh('up{job="kubelet",metrics_path="/metrics/cadvisor"}')
    return f'({expr}) and on(job, instance, metrics_path) ({up} == 1)'


def resource_query(app, metric, counter=False):
    selector = container_metric(metric, app, 'container!="",container!="POD"')
    value = f'rate({selector}[5m]) and {fresh(selector)}' if counter else fresh(selector)
    # Deduplicate scrape labels before summing application containers per pod.
    value = f'max by (namespace, pod, container) ({collected(value)})'
    return f'sum by (namespace, pod) (({value}) and on(namespace, pod) ({running(app)}))'


def network_query(app, direction):
    # cAdvisor exposes the shared pod network on the sandbox, once per interface.
    selector = container_metric(f'container_network_{direction}_bytes_total', app,
                                'container="POD",interface!="lo",interface!=""')
    value = collected(f'rate({selector}[5m]) and {fresh(selector)}')
    isolated = f'kube_pod_info{{job="kube-state-metrics",endpoint="https-main",{pod_filter(app)},host_network="false"}}'
    return (f'8 * sum by (namespace, pod) ((max by (namespace, pod, interface) ({value})) '
            f'and on(namespace, pod) ({running(app)}) '
            f'and on(namespace, pod) ({fresh(isolated)} == 1))')


def stream_query(metric='tautulli_streams'):
    selector = f'{metric}{{job="tautulli",instance="plex"}}'
    up = fresh('up{job="tautulli",instance="plex"}')
    return f'({fresh(selector)} >= 0) and on(job, instance) ({up} == 1)'


def build():
    panels = []

    def graph(title, queries, x, y, w, h, unit, description, datasource=DS):
        p = {'id': len(panels) + 1, 'title': title, 'type': 'timeseries', 'datasource': datasource,
             'description': description, 'gridPos': {'x': x, 'y': y, 'w': w, 'h': h},
             'targets': [{'refId': chr(65+i), 'datasource': datasource, 'expr': expr, 'legendFormat': legend,
                          'instant': False, 'range': True, 'interval': '30s', 'editorMode': 'code'}
                         for i, (expr, legend) in enumerate(queries)],
             'fieldConfig': {'defaults': {'unit': unit, 'min': 0, 'noValue': 'Unknown',
                 'color': {'mode': 'palette-classic'}, 'custom': {'drawStyle': 'line', 'lineWidth': 2,
                 'fillOpacity': 10, 'spanNulls': False, 'stacking': {'mode': 'none', 'group': 'A'}}}, 'overrides': []},
             'options': {'legend': {'showLegend': True, 'placement': 'bottom', 'displayMode': 'list'},
                         'tooltip': {'mode': 'multi', 'sort': 'desc'}}}
        panels.append(p)
        return p

    def service(app, name, x, y, w, h):
        base = 'OCP Home deployment pods; each line identifies a pod. Only fresh metrics for running pods with healthy monitoring sources are included. Missing data appears as gaps. '
        graph(name + ' CPU', [(resource_query(app, 'container_cpu_usage_seconds_total', True), '{{pod}}')],
              x, y, w, h, 'suffix:cores', base + 'Five-minute CPU usage in cores (1 = one fully utilized core), summed across application containers. Sandbox and parent cgroup metrics are excluded.')
        graph(name + ' memory', [(resource_query(app, 'container_memory_working_set_bytes'), '{{pod}}')],
              x+w, y, w, h, 'bytes', base + 'Container memory working set in bytes, summed per pod. This is not RSS or a percentage of a configured memory limit.')
        if app not in dict(PRIMARY):
            graph(name + ' network', [(network_query(app, 'receive'), '{{pod}} · Receive'),
                                     (network_query(app, 'transmit'), '{{pod}} · Transmit')],
                  x+2*w, y, w, h, 'bps', base + 'Five-minute receive/transmit rates in bits/s from pod sandbox interfaces, excluding loopback. Host-network pods are excluded to prevent attributing host traffic to the application.')

    for i, (app, name) in enumerate(PRIMARY):
        service(app, name, 0, i*5, 8, 5)
    spec = importlib.util.spec_from_file_location('cluster_dashboard', ROOT / 'scripts/build-dashboard.py')
    cluster = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cluster)
    host = cluster.build('ocp-home')
    queries = [(next(p for p in host['panels'] if p['title'] == 'Node network ' + direction)['targets'][0]['expr'],
                '{{instance}} · ' + label)
               for direction, label in [('receive', 'Receive'), ('transmit', 'Transmit')]]
    graph('Shared host network — bond0 (all workloads)', queries, 16, 0, 8, 10, 'bps',
          'Shared context for Plex and SABnzbd on OCP Home. Whole-host bond0 receive/transmit traffic includes all workloads; '
          'it is not attributable to either app. Plex uses host networking, so its pod counters cannot isolate Plex traffic. '
          'Physical bond members are excluded. Five-minute average bits/s; unavailable or stale telemetry appears as gaps.')
    for i, (app, name) in enumerate(SECONDARY):
        service(app, name, (i % 2)*12, 15+(i//2)*5, 4, 5)
    description = ('Current Plex sessions reported by Tautulli, including paused sessions. '
                   'Polled every 30 seconds. Failed, missing, or stale collection shows Unknown or gaps, not zero. '
                   'History begins when collection deploys; the total overlaps the three playback types and is not stacked.')
    p = graph('Plex current streams', [(stream_query(), 'Streams')], 0, 10, 4, 5, 'short', description, INFRA)
    p['type'] = 'stat'
    p['targets'][0].update(instant=True, range=False)
    p['fieldConfig']['defaults']['decimals'] = 0
    p['fieldConfig']['defaults'].pop('custom')
    p['options'] = {'reduceOptions': {'calcs': ['lastNotNull'], 'fields': '', 'values': False},
                    'colorMode': 'value', 'graphMode': 'none', 'textMode': 'auto', 'justifyMode': 'auto'}
    p = graph('Plex stream history', [(stream_query(metric), label) for metric, label in [
        ('tautulli_streams', 'Total'), ('tautulli_streams_direct_play', 'Direct Play'),
        ('tautulli_streams_direct_stream', 'Direct Stream'), ('tautulli_streams_transcode', 'Transcoding')]],
        4, 10, 20, 5, 'short', description, INFRA)
    p['fieldConfig']['defaults']['decimals'] = 0
    p['fieldConfig']['defaults']['custom']['lineInterpolation'] = 'stepAfter'
    return {'uid': 'media-services', 'title': 'Media Services', 'schemaVersion': 39, 'version': 1,
            'editable': False, 'tags': ['homelab', 'ocp-home', 'media'], 'timezone': 'browser',
            'refresh': '30s', 'time': {'from': 'now-6h', 'to': 'now'}, 'panels': panels,
            'templating': {'list': []}, 'annotations': {'list': []},
            'links': [{'title': 'Homelab dashboards', 'type': 'dashboards', 'tags': ['homelab'],
                       'asDropdown': True, 'includeVars': False, 'keepTime': True}]}


if __name__ == '__main__':
    (ROOT / 'dashboards/media.json').write_text(json.dumps(build(), indent=2) + '\n')
