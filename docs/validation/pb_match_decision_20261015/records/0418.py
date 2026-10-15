import json
from pathlib import Path
expected_boot='e521cc46-a722-4f54-b281-e4feea64a962'
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
items=[]
for label,pid,birth in [('nav_worker',329,259),('nav_peer',437,376),('decision_worker',643,1121),('decision_peer',675,1180)]:
    value=dict(label=label,pid=pid,expected_start_ticks=birth)
    try:
        fields=Path('/proc/%s/stat'%pid).read_text().rsplit(')',1)[1].split()
        actual=dict(state=fields[0],ppid=int(fields[1]),start_ticks=int(fields[19]))
    except FileNotFoundError:actual=None
    value.update(actual=actual,same_birth_present=boot==expected_boot and actual is not None and actual['start_ticks']==birth)
    items.append(value)
print(json.dumps(dict(scope='read-only old identity presence; does not reclassify old actual05 cleanup',expected_boot=expected_boot,current_boot=boot,boot_changed=boot!=expected_boot,identities=items,all_old_identities_absent=not any(x['same_birth_present'] for x in items))))