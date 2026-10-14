"""Pure signed-index binding/private-prefix tests, not apt/download evidence."""
import hashlib
import json
import os
import io
from pathlib import Path
from unittest.mock import patch
import pytest
from tools import prepare_pb_aim_system_dependencies as dep
from tools import build_pb_aim_plugins as build

ROOT=Path(__file__).resolve().parents[1]

def test_real_seven_package_closure_keeps_missing_plugins_and_all_original_dependencies():
    source=ROOT/'artifacts/pb2025-aim-source-20261014-03'
    deps=ROOT/'artifacts/pb2025-aim-dependency-compat-20261014-03'
    if not source.exists() or not deps.exists():pytest.skip('Pinned actual source artifacts absent')
    packages=dep.requested_packages(source,deps)
    assert 'ros-humble-image-transport-plugins' in packages
    assert {'ros-humble-cv-bridge','ros-humble-vision-opencv','ros-humble-rosidl-default-runtime',
        'ros-humble-eigen3-cmake-module','libeigen3-dev','libopencv-dev','nlohmann-json3-dev'}<=set(packages)
    assert all('hik' not in value and 'gazebo' not in value for value in packages)

def test_apt_md5_uri_is_bound_to_signed_sha256_and_size_without_network():
    rows=dep.parse_uri_lines("'http://packages.ros.org/ros2/ubuntu/pool/a.deb' a.deb 17 MD5Sum:0123456789abcdef")
    index='Package: ros-humble-fixture\nVersion: 1\nFilename: pool/a.deb\nSize: 17\nMD5sum: 0123456789abcdef\nSHA256: '+'a'*64+'\n\n'
    dep.bind_signed_debs(rows,index,'signed-index-fixture')
    assert rows[0]['sha256']=='a'*64 and rows[0]['package']=='ros-humble-fixture'
    bad=dep.parse_uri_lines("'http://packages.ros.org/ros2/ubuntu/pool/a.deb' a.deb 18 MD5Sum:0123456789abcdef")
    dep.bind_signed_debs(bad,index,'fixture');assert 'sha256' not in bad[0]

@pytest.mark.parametrize('line',["'https://other.invalid/ubuntu/a.deb' a.deb 1 SHA256:"+'a'*64,
    "'http://packages.ros.org/ros2/ubuntu/a.deb' ../a.deb 1 SHA256:"+'a'*64])
def test_nonofficial_url_and_filename_escape_rejected(line):
    with pytest.raises(ValueError):dep.parse_uri_lines(line)

def fixture_prefix(tmp_path):
    prefix=tmp_path/'prefix';(prefix/'opt/ros/humble/share/image_transport_plugins').mkdir(parents=True)
    (prefix/'opt/ros/humble/lib').mkdir();(prefix/'usr/lib/x86_64-linux-gnu/pkgconfig').mkdir(parents=True)
    file=prefix/'opt/ros/humble/share/image_transport_plugins/package.xml';file.write_bytes(b'pure fixture marker')
    record=dict(schema=dep.SCHEMA,complete=True,maintainer_scripts_executed=False,prefix=str(prefix),
        files=dep.prefix_files(prefix),packages=[{'package':'pure-fixture-not-an-actual-deb'}])
    manifest=tmp_path/'DEPENDENCY_PREFIX.json';manifest.write_text(json.dumps(record))
    return prefix,manifest,hashlib.sha256(manifest.read_bytes()).hexdigest(),file

def test_explicit_extra_prefix_only_prepends_new_paths_keeps_original_environment(tmp_path):
    prefix,manifest,sha,file=fixture_prefix(tmp_path)
    original=dict(CMAKE_PREFIX_PATH='/old/cmake',AMENT_PREFIX_PATH='/old/ament',LD_LIBRARY_PATH='/old/lib',PKG_CONFIG_PATH='/old/pkg')
    result,ref=build.add_extra_prefix(original,manifest,sha)
    assert original['CMAKE_PREFIX_PATH']=='/old/cmake'
    assert result['CMAKE_PREFIX_PATH'].endswith(':/old/cmake') and result['CMAKE_PREFIX_PATH'].startswith(str(prefix/'opt/ros/humble'))
    assert ref['sha256']==sha and ref['prefix']==str(prefix)
    file.write_bytes(b'changed owned fixture')
    with pytest.raises(ValueError,match='byte_or_link_changed'):build.add_extra_prefix(original,manifest,sha)

def test_incomplete_prefix_and_wrong_manifest_sha_cannot_build(tmp_path):
    prefix,manifest,sha,file=fixture_prefix(tmp_path)
    with pytest.raises(ValueError,match='sha_changed'):dep.checked_extra_prefix(manifest,'0'*64)
    record=json.loads(manifest.read_bytes());record['complete']=False;manifest.write_text(json.dumps(record))
    with pytest.raises(ValueError,match='complete_owned'):dep.checked_extra_prefix(manifest,hashlib.sha256(manifest.read_bytes()).hexdigest())

def test_apt_only_uses_owned_lists_sources_cache_and_readonly_global_status(tmp_path):
    options=dep.private_apt_options(tmp_path)
    assert 'Dir::State::status=/var/lib/dpkg/status' in options
    assert 'Dir::State::lists='+str(tmp_path/'apt-lists') in options
    assert 'Dir::Cache='+str(tmp_path/'apt-cache') in options
    assert 'Dir::Etc::sourceparts=-' in options

class ResponseFixture(io.BytesIO):
    def __init__(self,data,url):super().__init__(data);self.url=url
    def geturl(self):return self.url

def download_row(payload=b'actual fixture archive bytes'):
    return dict(url='http://packages.ros.org/ros2/ubuntu/pool/a.deb',file='a.deb',bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest())

def test_https_same_host_asset_first_then_finite_retry_preserves_error_and_final_url(tmp_path):
    payload=b'actual fixture archive bytes';row=download_row(payload);calls=[]
    def response(url,timeout):
        calls.append(url)
        if len(calls)==1:raise TimeoutError('synthetic socket timeout; no network performed')
        return ResponseFixture(payload,url)
    target=dep.download_verified(row,tmp_path/'a.deb',open_url=response)
    assert target.read_bytes()==payload
    assert calls==['https://packages.ros.org/ros2/ubuntu/pool/a.deb',row['url']]
    assert row['download_attempts'][0]['error_type']=='TimeoutError'
    assert row['download_attempts'][1]['verified_sha256']==row['sha256']
    assert row['download_final_url']==row['url']

def test_corrupt_download_keeps_partial_hash_never_accepts_until_full_signed_sha(tmp_path):
    payload=b'actual fixture archive bytes';row=download_row(payload);calls=[]
    def response(url,timeout):
        calls.append(url);return ResponseFixture(b'x'*len(payload) if len(calls)==1 else payload,url)
    dep.download_verified(row,tmp_path/'a.deb',open_url=response)
    assert (tmp_path/'a.deb').read_bytes()==payload
    first=row['download_attempts'][0]
    assert first['ok'] is False and first['partial_sha256']!=row['sha256']
    assert (tmp_path/'a.deb.attempt1.partial').exists()

def test_redirect_to_other_host_is_rejected_even_when_payload_matches_sha(tmp_path):
    payload=b'actual fixture archive bytes';row=download_row(payload)
    def response(url,timeout):return ResponseFixture(payload,'https://other.invalid/ubuntu/pool/a.deb')
    with pytest.raises(TimeoutError,match='exhausted'):dep.download_verified(row,tmp_path/'a.deb',open_url=response)
    assert len(row['download_attempts'])==3 and not (tmp_path/'a.deb').exists()
    assert all('redirect_outside' in event['error'] for event in row['download_attempts'])

def test_all_network_attempts_bounded_and_never_reuse_old_partial(tmp_path):
    row=download_row();calls=[]
    def response(url,timeout):calls.append(url);raise TimeoutError('pure fixture')
    with pytest.raises(TimeoutError,match='exhausted'):dep.download_verified(row,tmp_path/'a.deb',open_url=response)
    assert len(calls)==3 and not (tmp_path/'a.deb').exists()
    assert [v['attempt'] for v in row['download_attempts']]==[1,2,3]

def test_full_cache_sha_reuse_and_bad_cache_rejection_do_not_modify_old_bytes(tmp_path):
    payload=b'actual fixture archive bytes';cache=tmp_path/'cache';cache.mkdir();old=cache/'a.deb';old.write_bytes(payload)
    row=download_row(payload)
    def forbidden(*args,**kwargs):raise AssertionError('network not permitted by full-cache fixture')
    dep.download_verified(row,tmp_path/'first.deb',caches=[cache],open_url=forbidden)
    assert row['download_source']=='verified_full_cache' and old.read_bytes()==payload
    old.write_bytes(b'corrupt old cache');row2=download_row(payload);calls=[]
    def response(url,timeout):calls.append(url);return ResponseFixture(payload,url)
    dep.download_verified(row2,tmp_path/'second.deb',caches=[cache],open_url=response)
    assert calls and row2['download_attempts'][0]['kind']=='cache' and row2['download_attempts'][0]['ok'] is False
    assert old.read_bytes()==b'corrupt old cache' and (tmp_path/'second.deb').read_bytes()==payload

def test_completed_bytes_after_original_download_budget_are_not_accepted(tmp_path):
    payload=b'actual fixture archive bytes';row=download_row(payload);clock=[0.]
    class LateResponse(ResponseFixture):
        def read1(self,size):clock[0]=181.;return payload
    def response(url,timeout):return LateResponse(payload,url)
    with pytest.raises(TimeoutError):dep.download_verified(row,tmp_path/'a.deb',open_url=response,clock=lambda:clock[0])
    assert not (tmp_path/'a.deb').exists()
    assert row['download_attempts'][0]['error_type']=='TimeoutError'
