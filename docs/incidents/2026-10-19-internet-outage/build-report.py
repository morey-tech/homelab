#!/usr/bin/env python3
"""Regenerate incident CSV/PNG/PDF offline from saved Prometheus responses.
Requires matplotlib and reportlab. No network access or cluster changes.
"""
import csv
import json
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent
TZ = ZoneInfo('America/New_York')
def stamp(s):
    return datetime.fromisoformat('2026-10-19T' + s + '+00:00').timestamp()
START, END = stamp('13:33:54.858'), stamp('14:40:38.520')
def read(name):
    response = json.loads((ROOT / (name + '.json')).read_text())
    assert response['status'] == 'success'
    return response['data']['result']
DATA = {name: read(name) for name in ['ping', 'pfsense', 'modem', 'services', 'health']}
def select(group, metric, **labels):
    return [s for s in DATA[group] if s['metric']['__name__'] == metric
            and all(s['metric'].get(k) == v for k, v in labels.items())]
def points(group, metric, **labels):
    matched = select(group, metric, **labels)
    assert len(matched) == 1, (metric, labels)
    return [(t, float(v)) for t, v in matched[0]['values']]
def deltas(values, scale=1):
    # Counter reset or a missing scrape is unknown, not zero or interpolated traffic.
    return [(t, (v - pv) * scale / (t - pt) if v >= pv and t-pt <= 90 else float('nan'))
            for (pt, pv), (t, v) in zip(values, values[1:])]
def latest(values, t, max_age):
    eligible = [(s, v) for s, v in values if 0 <= t-s <= max_age]
    return max(eligible, default=(None, None))
def iso(t):
    return datetime.fromtimestamp(t, ZoneInfo('UTC')).isoformat() if t is not None else ''
loss = {target: points('ping', 'internet:ping_loss:ratio1m', target=target)
        for target in ['cloudflare', 'google', 'quad9', 'pfsense']}
wan = {direction: deltas(points('pfsense', metric, ifName='ix2'), 8/1e6)
       for direction, metric in [('download', 'ifHCInOctets'), ('upload', 'ifHCOutOctets')]}
modem = {direction: deltas(points('modem', 'hitron_wan_packets_total', direction=direction))
         for direction in ['receive', 'transmit']}
health = points('modem', 'hitron_collection_success')
series = {**{k+'_loss_pct': [(t,v*100) for t,v in vals] for k,vals in loss.items()},
          **{k+'_mbps': vals for k,vals in wan.items()},
          **{'modem_'+k+'_pps': vals for k,vals in modem.items()},
          'modem_collection_success': health,
          'modem_lan_uptime_s': points('modem', 'hitron_interface_uptime_seconds', interface='lan'),
          'modem_wan_uptime_s': points('modem', 'hitron_interface_uptime_seconds', interface='wan'),
          'pfsense_snmp_uptime_s': points('pfsense', 'sysUpTime'),
          'wan_link_status': points('pfsense', 'ifOperStatus', ifName='ix2')}
rows=[]
for t,_ in loss['cloudflare']:
    if not START <= t <= END:
        continue
    row={'timestamp_utc': iso(t), 'time_edt': datetime.fromtimestamp(t,TZ).isoformat()}
    for name,vals in series.items():
        s,v=latest(vals,t,0 if name.endswith('_loss_pct') else 60)
        # Never reuse modem data at a known failed collection observation.
        if name.startswith('modem_') and name != 'modem_collection_success' and latest(health,t,60)[1] != 1:
            s,v=None,None
        row[name] = v if v is not None and math.isfinite(v) else None
        row[name+'_source_utc'] = iso(s)
    rows.append(row)
with (ROOT/'minute-correlation.csv').open('w') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader();w.writerows(rows)

fig, axes=plt.subplots(6,1,figsize=(12,14),sharex=True,layout='constrained')
def plot(ax, vals, label, scale=1, **kw):
    # Insert NaN across missing observations to avoid visually bridging collection gaps.
    ts=[]; ys=[]
    for t,v in vals:
        if ts and t-ts[-1]>90:
            ts.append(ts[-1]+60); ys.append(float('nan'))
        ts.append(t);ys.append(v*scale)
    ax.plot([datetime.fromtimestamp(t,TZ) for t in ts],ys,label=label,**kw)
for k,v in loss.items(): plot(axes[0],v,k,100)
axes[0].set_ylabel('Ping loss (%)');axes[0].set_ylim(-3,105)
for k,v in wan.items(): plot(axes[1],v,k)
axes[1].set_ylabel('WAN Mbps'); axes[1].set_yscale('symlog',linthresh=.01)
for k,v in modem.items(): plot(axes[2],v,k)
axes[2].set_ylabel('Modem packets/s'); axes[2].set_yscale('symlog',linthresh=1)
for interface,style in [('lan','-'),('wan','--')]:
    plot(axes[3],points('modem','hitron_interface_uptime_seconds',interface=interface),'Hitron '+interface,1/3600,linestyle=style)
plot(axes[3],points('pfsense','sysUpTime'),'pfSense SNMP agent',1/3600)
axes[3].set_ylabel('Uptime (hours)')
plot(axes[4],health,'Modem API success',drawstyle='steps-post')
axes[4].set_ylabel('Collection success');axes[4].set_ylim(-.05,1.1)
# Show failed target counts only when every target has a recent sample.
for kind in ['dns','https']:
    targets=select('services','probe_success',kind=kind)
    vals=[]
    for t in range(int(START),int(END)+1,15):
        current=[latest([(ts,float(v)) for ts,v in s['values']],t,20)[1] for s in targets]
        vals.append((t,sum(v==0 for v in current) if all(v is not None for v in current) else float('nan')))
    plot(axes[5],vals,f'{kind.upper()} failed / {len(targets)}',drawstyle='steps-post')
axes[5].set_ylabel('Failed targets');axes[5].set_xlabel('19 October 2026 • EDT (UTC−04:00)')
for ax in axes:
    ax.axvspan(datetime.fromtimestamp(stamp('13:41:04.554'),TZ),datetime.fromtimestamp(stamp('13:54:04.554'),TZ),color='red',alpha=.09)
    ax.grid(alpha=.25);ax.legend(loc='upper right',fontsize=8,ncol=2)
    ax.set_xlim(datetime.fromtimestamp(START,TZ),datetime.fromtimestamp(END,TZ))
axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%H:%M',tz=TZ))
fig.suptitle('Internet outage correlation — 19 October 2026\nShading: approximate Internet interruption; later HTTPS failures are separate',fontsize=14)
fig.savefig(ROOT/'outage-correlation.png',dpi=160)
plt.close(fig)

styles=getSampleStyleSheet()
styles['BodyText'].fontSize=9
styles['BodyText'].leading=12
story=[]
paragraphs=(ROOT/'analysis.txt').read_text().strip().split('\n\n')
for i,block in enumerate(paragraphs):
    if i==0:
        story.append(Paragraph(escape(block),styles['Title']));continue
    heading,body=block.split('\n',1)
    if heading == 'What the new modem data adds':
        story.append(PageBreak())
    story.append(Paragraph(escape(heading),styles['Heading2']))
    story.append(Paragraph(escape(body).replace('\n','<br/>'),styles['BodyText']))
    story.append(Spacer(1,5))
story.append(PageBreak())
story.append(Image(str(ROOT/'outage-correlation.png'),width=510,height=595))
def footer(canvas,doc):
    canvas.setFont('Helvetica',8);canvas.drawString(42,25,'Internet incident | 2026-10-19 | Times EDT unless marked UTC')
    canvas.drawRightString(A4[0]-42,25,str(doc.page))
SimpleDocTemplate(str(ROOT/'outage-correlation.pdf'),pagesize=A4,rightMargin=42,leftMargin=42,topMargin=36,bottomMargin=42).build(story,onFirstPage=footer,onLaterPages=footer)
print(f'Generated {len(rows)} correlation rows, PNG and PDF.')
