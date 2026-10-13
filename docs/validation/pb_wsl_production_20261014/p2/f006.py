"""Read saved Host intervals; print the exact supplemental OUTLIERS.json data."""
import hashlib
import json
from pathlib import Path

p = Path(__file__).resolve().parent
raw = p / 'raw/HOST_RPC_PHASES.json'
h = json.loads(raw.read_bytes())
g = {}
for row in h['rows']:
    if row['op'] == 'act':
        g.setdefault(row['id'], {})[row['phase']] = row['local_wall']
i = max(g, key=lambda k: g[k]['packet_validated'] - g[k]['exchange_enter'])
v = g[i]
result = dict(max_packet_validation_rpc_id=i,
              max_packet_validation_ms=(v['packet_validated']-v['exchange_enter'])*1000,
              max_packet_validation_rpc_exchange_total_ms=(v['return_copy_end']-v['exchange_enter'])*1000,
              phases=v,
              max_total_rpc_230_packet_validation_ms=(g[230]['packet_validated']-g[230]['exchange_enter'])*1000,
              source_input_sha256=hashlib.sha256(raw.read_bytes()).hexdigest())
assert result == json.loads((p / 'OUTLIERS.json').read_bytes())
print(json.dumps(result, indent=2))
