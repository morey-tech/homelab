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
STREAM_COLORS = {'Direct Play': '#73BF69', 'Direct Stream': '#FADE2A', 'Transcoding': '#5794F2'}
RESOURCE_COLORS = {'Plex memory': '#B877D9', 'SABnzbd CPU': '#FF9830', 'SABnzbd memory': '#56D9D1'}
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


def bandwidth_query(scope):
    return f'({stream_query(f"tautulli_{scope}_bandwidth_kilobits_per_second")}) / 1000'


def sab_query(metric, scale=1):
    selector = f'{metric}{{job="sabnzbd",instance="sabnzbd"}}'
    up = fresh('up{job="sabnzbd",instance="sabnzbd"}')
    return f'(({fresh(selector)} >= 0) * {scale}) and on(job, instance) ({up} == 1)'


def media_share_query():
    labels = 'job="qnap",instance="qnap-01",share="storage-media"'
    total = fresh(f'sharedFolderCapacity{{{labels}}}')
    free = fresh(f'sharedFolderFreeSize{{{labels}}}')
    up = fresh('up{job="qnap",instance="qnap-01"}')
    valid = f'({total} > 0) and ({free} >= 0) and ({free} <= {total})'
    return f'(100 * ({total} - {free}) / {total} and ({valid})) and on(job, instance) ({up} == 1)'


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
        if title in RESOURCE_COLORS:
            p['fieldConfig']['defaults']['color'] = {'mode': 'fixed', 'fixedColor': RESOURCE_COLORS[title]}
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
        service(app, name, 0, 5+i*7, 8 if app == 'plex' else 5, 7)
    spec = importlib.util.spec_from_file_location('cluster_dashboard', ROOT / 'scripts/build-dashboard.py')
    cluster = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cluster)
    host = cluster.build('ocp-home')
    queries = [(next(p for p in host['panels'] if p['title'] == 'Node network ' + direction)['targets'][0]['expr'],
                '{{instance}} · ' + label)
               for direction, label in [('receive', 'Receive'), ('transmit', 'Transmit')]]
    graph('Shared host network — bond0 (all workloads)', queries, 16, 7, 8, 6, 'bps',
          'Shared context for Plex and SABnzbd on OCP Home. Whole-host bond0 receive/transmit traffic includes all workloads; '
          'it is not attributable to either app. Plex uses host networking, so its pod counters cannot isolate Plex traffic. '
          'Physical bond members are excluded. Five-minute average bits/s; unavailable or stale telemetry appears as gaps.')
    for i, (app, name) in enumerate(SECONDARY):
        service(app, name, (i % 2)*12, 19+(i//2)*5, 4, 5)
    description = ('Current Plex sessions reported by Tautulli, including paused sessions. '
                   'Polled every 30 seconds. Failed, missing, or stale collection shows Unknown or gaps, not zero. '
                   'History begins when collection deploys. The three playback types are stacked; their combined height gives total sessions.')
    def stream_stat(title, metric, x):
        p = graph(title, [(stream_query(metric), 'Streams')], x, 0, 3, 5, 'short', description, INFRA)
        p['type'] = 'stat'
        p['targets'][0].update(instant=True, range=False)
        p['fieldConfig']['defaults']['decimals'] = 0
        p['fieldConfig']['defaults'].pop('custom')
        if title in STREAM_COLORS:
            p['fieldConfig']['defaults']['color'] = {'mode': 'fixed', 'fixedColor': STREAM_COLORS[title]}
        p['options'] = {'reduceOptions': {'calcs': ['lastNotNull'], 'fields': '', 'values': False},
                        'colorMode': 'value', 'graphMode': 'none', 'textMode': 'auto', 'justifyMode': 'auto'}
        return p

    p = graph('Plex stream history', [(stream_query(metric), label) for metric, label in [
        ('tautulli_streams_direct_play', 'Direct Play'),
        ('tautulli_streams_direct_stream', 'Direct Stream'), ('tautulli_streams_transcode', 'Transcoding')]],
        16, 0, 8, 7, 'short', description, INFRA)
    p['id'] = 34
    p['fieldConfig']['defaults']['decimals'] = 0
    p['fieldConfig']['defaults']['custom']['lineInterpolation'] = 'stepAfter'
    p['fieldConfig']['defaults']['custom']['stacking'] = {'mode': 'normal', 'group': 'A'}
    p['fieldConfig']['defaults']['custom']['fillOpacity'] = 60
    p['fieldConfig']['overrides'] = [
        {'matcher': {'id': 'byName', 'options': label},
         'properties': [{'id': 'color', 'value': {'mode': 'fixed', 'fixedColor': color}}]}
        for label, color in STREAM_COLORS.items()]
    # Preserve IDs for existing panels; retired Total panel ID 33 stays unused.
    stream_stat('Direct Stream', 'tautulli_streams_direct_stream', 3)['id'] = 35
    stream_stat('Transcoding', 'tautulli_streams_transcode', 6)['id'] = 36
    stream_stat('Direct Play', 'tautulli_streams_direct_play', 0)['id'] = 37
    secondary_panels = [p for p in panels if p['gridPos']['y'] >= 19]
    for p in secondary_panels:
        p['gridPos']['y'] += 1  # Leave room for the collapsible row header.
    row = {'id': 38, 'title': 'Secondary media services', 'type': 'row',
           'collapsed': True, 'gridPos': {'x': 0, 'y': 19, 'w': 24, 'h': 1},
           'panels': secondary_panels}
    p = stream_stat('SAB remaining', 'tautulli_streams', 9)
    p['id'] = 39
    p['description'] = ('Bytes left to download across the SABnzbd queue, including queued/paused work. '
                        'Excludes repair, unpacking, and import work. API MiB is converted to bytes. '
                        'Missing, stale, or failed telemetry shows Unknown, not an empty queue.')
    p['targets'][0].update(expr=sab_query('sabnzbd_queue_remaining_mebibytes', 1048576), legendFormat='Remaining')
    p['fieldConfig']['defaults'].update(unit='bytes', decimals=1,
                                       color={'mode': 'fixed', 'fixedColor': '#FF9830'})
    p = graph('Plex bandwidth estimates', [(bandwidth_query('wan'), 'WAN estimate'),
                                          (bandwidth_query('lan'), 'LAN estimate')],
              16, 13, 8, 6, 'suffix:Mbps',
              'Tautulli estimates of bandwidth reserved for remote (WAN) and local (LAN) Plex sessions. '
              'Not measured interface traffic. Polled every 30 seconds; kbps converted to Mbps. '
              'Missing, failed, or stale collection appears as gaps.', INFRA)
    p['id'] = 40
    p['fieldConfig']['defaults']['decimals'] = 2
    p['fieldConfig']['overrides'] = [
        {'matcher': {'id': 'byName', 'options': label},
         'properties': [{'id': 'color', 'value': {'mode': 'fixed', 'fixedColor': color}}]}
        for label, color in [('WAN estimate', '#B877D9'), ('LAN estimate', '#56D9D1')]]
    p = graph('Media share used', [(media_share_query(), 'storage-media')], 12, 0, 4, 5, 'percent',
              'qnap-01 storage-media logical shared-folder used percentage: (total minus free) / total. '
              'Includes snapshots/allocation according to NAS reporting; not pool usage. '
              'Missing, invalid, stale, or failed telemetry shows Unknown.', INFRA)
    p['id'] = 41
    p['type'] = 'gauge'
    p['targets'][0].update(instant=True, range=False)
    p['fieldConfig']['defaults'].pop('custom')
    p['fieldConfig']['defaults'].update(max=100, decimals=1, color={'mode': 'thresholds'},
        thresholds={'mode': 'absolute', 'steps': [{'color': 'green', 'value': None},
                    {'color': 'yellow', 'value': 80}, {'color': 'red', 'value': 90}]})
    p['options'] = {'reduceOptions': {'calcs': ['lastNotNull'], 'fields': '', 'values': False},
                    'showThresholdLabels': False, 'showThresholdMarkers': True}
    p = graph('SAB download speed', [(sab_query('sabnzbd_download_kibibytes_per_second', 1024), 'Download')],
              10, 12, 6, 7, 'Bps', 'SABnzbd application download speed, sampled every 30 seconds. '
              'API KiB/s is converted to bytes/s. Not total host traffic or unpacking speed. '
              'Missing, failed, or stale collection appears as gaps.', INFRA)
    p['id'] = 42
    p['fieldConfig']['defaults']['color'] = {'mode': 'fixed', 'fixedColor': '#F2CC0C'}
    panels = [p for p in panels if p['gridPos']['y'] < 19] + [row]
    panels.sort(key=lambda p: (p['gridPos']['y'], p['gridPos']['x']))
    return {'uid': 'media-services', 'title': 'Media Services', 'schemaVersion': 39, 'version': 1,
            'editable': False, 'tags': ['homelab', 'ocp-home', 'media'], 'timezone': 'browser',
            'refresh': '30s', 'time': {'from': 'now-6h', 'to': 'now'}, 'panels': panels,
            'templating': {'list': []}, 'annotations': {'list': []},
            'links': [{'title': 'Homelab dashboards', 'type': 'dashboards', 'tags': ['homelab'],
                       'asDropdown': True, 'includeVars': False, 'keepTime': True}]}


if __name__ == '__main__':
    (ROOT / 'dashboards/media.json').write_text(json.dumps(build(), indent=2) + '\n')
