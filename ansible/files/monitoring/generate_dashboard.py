#!/usr/bin/env python3
import json

# Base dashboard structure
dashboard = {
    "annotations": {"list": []},
    "editable": True,
    "fiscalYearStartMonth": 0,
    "graphTooltip": 0,
    "id": None,
    "links": [],
    "liveNow": False,
    "panels": [],
    "refresh": "1m",
    "schemaVersion": 39,
    "tags": ["mikrotik", "snmp", "network"],
    "templating": {"list": []},
    "time": {"from": "now-3h", "to": "now"},
    "timepicker": {},
    "timezone": "",
    "title": "Mikrotik CRS317 SwOS - Network Monitoring",
    "uid": "mikrotik-swos-main",
    "version": 2,
    "weekStart": ""
}

panels = []
panel_id = 1
y_pos = 0

# Header text panel
panels.append({
    "datasource": {"type": "prometheus", "uid": "Prometheus"},
    "gridPos": {"h": 3, "w": 24, "x": 0, "y": y_pos},
    "id": panel_id,
    "options": {
        "code": {"language": "plaintext", "showLineNumbers": False, "showMiniMap": False},
        "content": "# Mikrotik CRS317-1G-16S+ SwOS\n## IP: 192.168.1.14 | Location: Homelab",
        "mode": "markdown"
    },
    "pluginVersion": "12.0.2",
    "title": "Switch Information",
    "type": "text"
})
panel_id += 1
y_pos += 3

# Top row stats
stats = [
    ("System Uptime", 'sysUpTime{device_type="mikrotik_switch"} / 100', "dtdurations", None),
    ("Total Throughput", 'sum(rate(ifHCInOctets{device_type="mikrotik_switch"}[5m]) * 8) + sum(rate(ifHCOutOctets{device_type="mikrotik_switch"}[5m]) * 8)', "bps", [1000000000, 10000000000]),
    ("Total Errors (5m)", 'sum(increase(ifInErrors{device_type="mikrotik_switch"}[5m])) + sum(increase(ifOutErrors{device_type="mikrotik_switch"}[5m]))', "short", [1, 100]),
    ("Total Discards (5m)", 'sum(increase(ifInDiscards{device_type="mikrotik_switch"}[5m])) + sum(increase(ifOutDiscards{device_type="mikrotik_switch"}[5m]))', "short", [1, 100])
]

for i, (title, expr, unit, thresholds) in enumerate(stats):
    threshold_steps = [{"color": "green", "value": None}]
    if thresholds:
        threshold_steps.append({"color": "yellow", "value": thresholds[0]})
        threshold_steps.append({"color": "red", "value": thresholds[1]})

    panels.append({
        "datasource": {"type": "prometheus", "uid": "Prometheus"},
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "thresholds"},
                "mappings": [],
                "thresholds": {"mode": "absolute", "steps": threshold_steps},
                "unit": unit
            }
        },
        "gridPos": {"h": 4, "w": 6, "x": i * 6, "y": y_pos},
        "id": panel_id,
        "options": {
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {"values": False, "calcs": ["lastNotNull"]},
            "textMode": "auto"
        },
        "targets": [{
            "datasource": {"type": "prometheus", "uid": "Prometheus"},
            "expr": expr,
            "refId": "A"
        }],
        "title": title,
        "type": "stat"
    })
    panel_id += 1
y_pos += 4

# Port status - 17 individual stat panels (2 rows: 12 in first row, 5 in second row)
for port_idx in range(1, 18):  # ifIndex 1-17
    row = 0 if port_idx <= 12 else 1
    col = (port_idx - 1) % 12
    x = col * 2
    y = y_pos + (row * 3)

    panels.append({
        "datasource": {"type": "prometheus", "uid": "Prometheus"},
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "thresholds"},
                "mappings": [
                    {
                        "options": {
                            "1": {"color": "green", "text": "UP"},
                            "2": {"color": "dark-gray", "text": "DOWN"}
                        },
                        "type": "value"
                    }
                ],
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "dark-gray", "value": None},
                        {"color": "green", "value": 1},
                        {"color": "dark-gray", "value": 2}
                    ]
                },
                "unit": "short"
            }
        },
        "gridPos": {"h": 3, "w": 2, "x": x, "y": y},
        "id": panel_id,
        "options": {
            "colorMode": "background",
            "graphMode": "none",
            "justifyMode": "center",
            "orientation": "auto",
            "reduceOptions": {"values": False, "calcs": ["lastNotNull"]},
            "textMode": "name"
        },
        "targets": [{
            "datasource": {"type": "prometheus", "uid": "Prometheus"},
            "expr": f'ifOperStatus{{device_type="mikrotik_switch",ifIndex="{port_idx}"}}',
            "legendFormat": "{{ifDescr}}",
            "refId": "A"
        }],
        "title": f"Port {port_idx}",
        "type": "stat"
    })
    panel_id += 1

y_pos += 6  # After 2 rows of port status

# Interface detail rows - 17 collapsed row panels
for if_idx in range(1, 18):
    # Row panel (collapsed container)
    row_panel_id = panel_id
    panel_id += 1

    # Traffic panel
    traffic_panel_id = panel_id
    panel_id += 1

    # Errors panel
    errors_panel_id = panel_id
    panel_id += 1

    # Row container
    panels.append({
        "collapsed": True,
        "datasource": {"type": "prometheus", "uid": "Prometheus"},
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y_pos},
        "id": row_panel_id,
        "panels": [
            # Traffic panel (inside row)
            {
                "datasource": {"type": "prometheus", "uid": "Prometheus"},
                "fieldConfig": {
                    "defaults": {
                        "color": {"mode": "palette-classic"},
                        "custom": {
                            "axisBorderShow": False,
                            "axisCenteredZero": False,
                            "axisColorMode": "text",
                            "axisLabel": "",
                            "axisPlacement": "auto",
                            "barAlignment": 0,
                            "drawStyle": "line",
                            "fillOpacity": 10,
                            "gradientMode": "none",
                            "hideFrom": {"tooltip": False, "viz": False, "legend": False},
                            "insertNulls": False,
                            "lineInterpolation": "linear",
                            "lineWidth": 1,
                            "pointSize": 5,
                            "scaleDistribution": {"type": "linear"},
                            "showPoints": "never",
                            "spanNulls": False,
                            "stacking": {"group": "A", "mode": "none"},
                            "thresholdsStyle": {"mode": "off"}
                        },
                        "mappings": [],
                        "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}]},
                        "unit": "bps"
                    },
                    "overrides": [
                        {
                            "matcher": {"id": "byRegexp", "options": "/.*In.*/"},
                            "properties": [{"id": "custom.transform", "value": "negative-Y"}]
                        }
                    ]
                },
                "gridPos": {"h": 8, "w": 12, "x": 0, "y": y_pos + 1},
                "id": traffic_panel_id,
                "options": {
                    "legend": {
                        "calcs": ["mean", "max"],
                        "displayMode": "table",
                        "placement": "bottom",
                        "showLegend": True
                    },
                    "tooltip": {"mode": "multi", "sort": "none"}
                },
                "targets": [
                    {
                        "datasource": {"type": "prometheus", "uid": "Prometheus"},
                        "expr": f'rate(ifHCInOctets{{device_type="mikrotik_switch",ifIndex="{if_idx}"}}[5m]) * 8',
                        "legendFormat": "In - {{ifDescr}}",
                        "refId": "A"
                    },
                    {
                        "datasource": {"type": "prometheus", "uid": "Prometheus"},
                        "expr": f'rate(ifHCOutOctets{{device_type="mikrotik_switch",ifIndex="{if_idx}"}}[5m]) * 8',
                        "legendFormat": "Out - {{ifDescr}}",
                        "refId": "B"
                    }
                ],
                "title": f"Interface {if_idx} Traffic",
                "type": "timeseries"
            },
            # Errors panel (inside row)
            {
                "datasource": {"type": "prometheus", "uid": "Prometheus"},
                "fieldConfig": {
                    "defaults": {
                        "color": {"mode": "palette-classic"},
                        "custom": {
                            "axisBorderShow": False,
                            "axisCenteredZero": False,
                            "axisColorMode": "text",
                            "axisLabel": "",
                            "axisPlacement": "auto",
                            "barAlignment": 0,
                            "drawStyle": "line",
                            "fillOpacity": 10,
                            "gradientMode": "none",
                            "hideFrom": {"tooltip": False, "viz": False, "legend": False},
                            "insertNulls": False,
                            "lineInterpolation": "linear",
                            "lineWidth": 1,
                            "pointSize": 5,
                            "scaleDistribution": {"type": "linear"},
                            "showPoints": "never",
                            "spanNulls": False,
                            "stacking": {"group": "A", "mode": "none"},
                            "thresholdsStyle": {"mode": "off"}
                        },
                        "mappings": [],
                        "thresholds": {
                            "mode": "absolute",
                            "steps": [
                                {"color": "green", "value": None},
                                {"color": "red", "value": 1}
                            ]
                        },
                        "unit": "short"
                    }
                },
                "gridPos": {"h": 8, "w": 12, "x": 12, "y": y_pos + 1},
                "id": errors_panel_id,
                "options": {
                    "legend": {
                        "calcs": ["sum"],
                        "displayMode": "table",
                        "placement": "bottom",
                        "showLegend": True
                    },
                    "tooltip": {"mode": "multi", "sort": "none"}
                },
                "targets": [
                    {
                        "datasource": {"type": "prometheus", "uid": "Prometheus"},
                        "expr": f'increase(ifInErrors{{device_type="mikrotik_switch",ifIndex="{if_idx}"}}[5m])',
                        "legendFormat": "In Errors - {{ifDescr}}",
                        "refId": "A"
                    },
                    {
                        "datasource": {"type": "prometheus", "uid": "Prometheus"},
                        "expr": f'increase(ifOutErrors{{device_type="mikrotik_switch",ifIndex="{if_idx}"}}[5m])',
                        "legendFormat": "Out Errors - {{ifDescr}}",
                        "refId": "B"
                    },
                    {
                        "datasource": {"type": "prometheus", "uid": "Prometheus"},
                        "expr": f'increase(ifInDiscards{{device_type="mikrotik_switch",ifIndex="{if_idx}"}}[5m])',
                        "legendFormat": "In Discards - {{ifDescr}}",
                        "refId": "C"
                    },
                    {
                        "datasource": {"type": "prometheus", "uid": "Prometheus"},
                        "expr": f'increase(ifOutDiscards{{device_type="mikrotik_switch",ifIndex="{if_idx}"}}[5m])',
                        "legendFormat": "Out Discards - {{ifDescr}}",
                        "refId": "D"
                    }
                ],
                "title": f"Interface {if_idx} Errors & Discards",
                "type": "timeseries"
            }
        ],
        "title": f"Interface {if_idx} Details",
        "type": "row"
    })
    y_pos += 1

dashboard["panels"] = panels

# Output JSON
print(json.dumps(dashboard, indent=2))
