#!/usr/bin/env python3
"""Freeze literal PB build/startup/SIL evidence without promoting acceptance."""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    'lio': ('pb2025-lio-tf-source-20261013-02',
        ['BUILD_COMMAND.json', 'BUILD_RESULT.json', 'BINARY_AUDIT.json', 'colcon.log',
         'GENERATION_CONFIG.json', 'OVERLAY_MANIFEST.json', 'build_owned.py', 'audit_binaries.py']),
    'terrain': ('pb2025-terrain-scan-build-20261013',
        ['BUILD_COMMAND.json', 'BUILD_RESULT.json', 'BINARY_AUDIT.json', 'colcon.log',
         'SOURCE_MANIFEST.json', 'FRAME_AUDIT_20261014.json', 'build_owned.py', 'prepare_source.py']),
    'plugins_failed': ('pb2025-nav2-plugins-actual-build-20261013', ['BUILD_RESULT.json', 'build.log']),
    'plugins_timeout': ('pb2025-nav2-plugins-actual-build-20261013-02', ['BUILD_RESULT.json', 'build.log']),
    'plugins_unique_soname': ('pb2025-nav2-plugins-actual-build-20261014-03',
        ['BUILD_RESULT.json', 'build.log', 'src/pb_nav2_plugins/SOURCE_IDENTITY.json',
         'src/pb_nav2_plugins/CMakeLists.txt', 'src/pb_nav2_plugins/costmap_plugins.xml']),
    'controller_resume': ('pb-controller-resume-20261014-01', ['RESULT.json', 'resume_build.log', 'resume_controller.py']),
    'controller_source': ('pb2025-nav2-plugins-actual-build-20261013-02',
        ['src/pb_omni_pid_pursuit_controller/SOURCE_IDENTITY.json']),
    'loader': ('pb-nav2-elf-loader-audit-20261014',
        ['RESULT.json', 'PLUGIN_CLASS_TIMEOUT.json', 'SOURCE_TEST_RESULT.json', 'audit.py', 'compile_probe.py', 'plugin_probe.cpp']),
    'owned_context': ('pb-stack-owned-context-probe-20261014-01', ['RESULT.json', 'stdout.log', 'stderr.log']),
    'dds_scope': ('pb-stack-dds-scope-probe-20261014-01', ['RESULT.json', 'stdout.log', 'stderr.log']),
    'runtime_import': ('pb-slot-import-isolation-20261014-01',
        ['RESULT.json', 'stdout.log', 'stderr.log', 'FAILED_FOCUSED_COMMAND.json', 'WINDOWS_FOCUSED_RESULT.json']),
    'cold_sensors': ('navigation-sensors-humble-cold-20261014',
        ['RESULT.json', 'EVIDENCE_MANIFEST.json', 'first_observation.json.gz', 'last_observation.json.gz']),
    'numpy2_dds': ('pb-humble-dds-numpy2-actual-20261013', ['RESULT.json', 'local_manifest.json']),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.absolute()
    if out.exists() or not out.is_relative_to(ROOT / 'docs' / 'validation'):
        parser.error('new repository docs/validation directory required')
    out.mkdir(parents=True)
    records = []

    def preserve(source, relative):
        raw = source.read_bytes()
        compress = len(raw) > 1000000 and source.suffix != '.gz'
        target = out / (str(relative) + ('.gz' if compress else ''))
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = gzip.compress(raw, mtime=0) if compress else raw
        target.write_bytes(payload)
        restored = gzip.decompress(target.read_bytes()) if compress else target.read_bytes()
        if restored != raw or source.read_bytes() != raw:
            raise RuntimeError('evidence bytes changed during preservation')
        records.append(dict(path=target.relative_to(out).as_posix(),
            original_path=source.relative_to(ROOT).as_posix(), bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(), encoding='gzip' if compress else 'literal',
            stored_bytes=len(payload), stored_sha256=hashlib.sha256(payload).hexdigest()))

    for label, (directory, names) in GROUPS.items():
        for name in names:
            preserve(ROOT / 'artifacts' / directory / name, Path(label) / name)
    preserve(ROOT / 'artifacts' / 'pb-navigation-sil-config-20261014-02.json', Path('STACK_CONFIG.json'))
    attempts = sorted((ROOT / 'artifacts').glob('pb-navigation-sil-actual-20261014-attempt*'),
                      key=lambda p: int(p.name.rsplit('attempt', 1)[1]))
    for directory in attempts:
        if not (directory / 'RESULT.json').is_file():
            raise RuntimeError('actual attempt still running or missing final result: ' + directory.name)
        label = directory.name.rsplit('-', 1)[1]
        for source in sorted(directory.rglob('*')):
            if source.is_file():
                preserve(source, Path(label) / source.relative_to(directory))
    manifest = dict(schema='polar.evidence.preservation.v2',
        qualification='raw build, startup, sensors and individually labelled bounded SIL; no full match or hardware acceptance',
        files=records)
    (out / 'PRESERVATION_MANIFEST.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(literal_records=len(records), actual_attempts=len(attempts),
                         restored_bytes_verified=True, out=str(out))))


if __name__ == '__main__':
    main()
