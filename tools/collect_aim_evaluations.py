"""Collect immutable per-case evidence without pooling unequal scenarios/durations."""
import argparse,collections,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('roots',nargs='+',type=Path);p.add_argument('--out',required=True,type=Path);a=p.parse_args()
cases=[]
for root in a.roots:
 for path in sorted(root.glob('*/summary.json')):
  s=json.loads(path.read_text());folder=path.parent
  rows=[json.loads(l) for l in (folder/'actor_ticks.jsonl').read_text().splitlines()]
  processed=[r for r in rows if r['telemetry'].get('detector_executed')]
  contacts=json.loads((folder/'contacts.json').read_text())
  colours=collections.Counter(d['colour'] for r in processed for d in r['telemetry'].get('raw_detection_details',[]))
  cases.append(dict(path=str(folder),summary=s,processed_frames=len(processed),
    raw_positive_frames=sum(r['telemetry'].get('raw_detections',0)>0 for r in processed),
    team_accepted_frames=sum(r['telemetry'].get('detections',0)>0 for r in processed),
    raw_colour_counts=dict(colours),colour_details_available=any('raw_detection_details' in r['telemetry'] for r in processed),
    impact_geometries=dict(collections.Counter(c['geom'] for c in contacts)),
    video_sha256=hashlib.sha256((folder/'evaluation.mp4').read_bytes()).hexdigest() if (folder/'evaluation.mp4').exists() else None))
a.out.parent.mkdir(parents=True,exist_ok=True)
a.out.write_text(json.dumps(dict(cases=cases,aggregation_policy='Per-case only. No pooled success rate across unequal durations, profiles, source variants or motion scenarios.',
 conclusions_require='Interpret detector presence, team acceptance, tracking, firing, geometric contacts and valid damage separately. Optical and appearance revisions remain separate. Truth geometry is evaluator-only.'),indent=2))
print(f'{len(cases)} cases -> {a.out}')
