"""Deterministic in-memory file interleaving, no factories or algorithms run."""
import copy
import hashlib
import json
from unittest.mock import patch

import rm_match.deployment.navigation_plugin as navigation
from rm_match.deployment.robotio_plugin import register_robotio_plugins
from rm_match.platform_v2.adapters import Registry

original = navigation.read_json_snapshot
reads = []


def snapshot(path):
    value, sha = original(path)
    reads.append(str(path))
    if len(reads) > 1:
        value = copy.deepcopy(value)
        value['adapters'][0]['supported_robots'].append('blue_sentry')
        sha = hashlib.sha256(json.dumps(value).encode()).hexdigest()
    return value, sha


registry = Registry()
try:
    with patch.object(navigation, 'read_json_snapshot', side_effect=snapshot):
        register_robotio_plugins(registry, 'examples/robotio_protocol_plugins.json')
    plugin_id = 'custom_protocol_nav_supply'
    descriptor = registry.get(plugin_id).descriptor
    catalog = next(row for row in registry.plugin_catalog() if row['plugin_id'] == plugin_id)
    result = dict(registered=True, descriptor_scope=descriptor['supported_robots'],
                  catalog_scope=catalog['supported_robots'])
except ValueError as error:
    result = dict(registered=False, error=str(error),
                  target_descriptors=registry.descriptors(),
                  target_catalog=registry.plugin_catalog())
result['component_reads'] = len(reads)
print(json.dumps(result, indent=2))
