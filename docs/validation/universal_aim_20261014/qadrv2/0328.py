"""Codec identity and exact pixels, no time thresholds, GL, model, or native work."""
import base64
import hashlib
import importlib.util
from pathlib import Path
import random
from types import SimpleNamespace
from unittest.mock import patch
import pytest

from rm_match.platform_v2 import base64_codec as codec


@pytest.fixture(autouse=True)
def fresh_codec_cache():
    codec._binding.cache_clear()
    yield
    codec._binding.cache_clear()


def test_default_is_exact_existing_encoder_with_no_optional_import():
    from rm_match.platform_v2.camera import encode_raw_base64
    with patch.object(codec.importlib,'import_module',side_effect=AssertionError('Optional codec imported')):
        assert codec.load_raw_encoder() is encode_raw_base64
        assert codec.load_raw_encoder('stdlib_chunked') is encode_raw_base64
        assert codec.raw_encoder_metadata()['extension_sha256'] is None
        assert codec.load_raw_encoder()(b'ab')=='YWI='


@pytest.mark.parametrize('name',['unknown','pybase64','pybase64_1_5_2',None,True,{},lambda raw:raw])
def test_unknown_codec_callback_and_free_import_path_refused(name):
    with pytest.raises(ValueError,match='Unknown'):codec.load_raw_encoder(name)


def test_explicit_missing_dependency_never_falls_back_to_stdlib():
    with patch.object(codec.importlib,'import_module',side_effect=ModuleNotFoundError('not installed')):
        with pytest.raises(ValueError,match='installed pybase64'):codec.load_raw_encoder('pybase64_1_5_1')


@pytest.mark.parametrize('distribution_version,package_version',[('1.5.0','1.5.1'),('1.5.1','1.5.0')])
def test_explicit_wrong_package_or_distribution_version_refused(distribution_version,package_version):
    package=SimpleNamespace(__version__=package_version)
    with patch.object(codec.importlib,'import_module',return_value=package),patch.object(codec.metadata,'version',return_value=distribution_version):
        with pytest.raises(ValueError,match='exactly'):codec.load_raw_encoder('pybase64_1_5_1')


def test_pure_python_encoder_is_refused_even_with_claimed_pinned_version():
    fallback=lambda raw,**kwargs:base64.b64encode(raw).decode('ascii')
    package=SimpleNamespace(__version__='1.5.1',b64encode_as_string=fallback)
    extension=SimpleNamespace(__name__='pybase64._pybase64',b64encode_as_string=fallback)
    with patch.object(codec.importlib,'import_module',side_effect=[package,extension]),patch.object(codec.metadata,'version',return_value='1.5.1'):
        with pytest.raises(ValueError,match='non-C'):codec.load_raw_encoder('pybase64_1_5_1')


@pytest.fixture
def c_encoder():
    if importlib.util.find_spec('pybase64') is None:
        pytest.skip('Optional pinned pybase64 C wheel is not installed in baseline CI')
    # An installed but wrong version/fallback is an actual failure, never a skip.
    return codec.load_raw_encoder('pybase64_1_5_1')


def assert_parity(encode,raw):
    actual=encode(raw)
    assert type(actual) is str
    assert actual==base64.b64encode(raw).decode('ascii')
    assert base64.b64decode(actual,validate=True)==raw
    assert '\n' not in actual and '\r' not in actual


def test_real_c_codec_canonical_random_odd_sizes_and_192k_boundaries(c_encoder):
    rng=random.Random(57214)
    for size in [0,1,2,3,5,7,191,192*1024-1,192*1024,192*1024+1,192*1024+2,384*1024+1]:
        assert_parity(c_encoder,rng.randbytes(size))


def test_real_c_codec_rejects_mutable_and_oversize_raw_before_encoding(c_encoder):
    for value in [bytearray(b'ab'),memoryview(b'ab'),'ab',None,b'\x00'*(codec.MAX_RAW_BYTES+1)]:
        with pytest.raises(ValueError,match='immutable'):c_encoder(value)
    assert_parity(c_encoder,b'\x19'*codec.MAX_RAW_BYTES)


def test_real_c_identity_is_exact_and_setup_cache_does_not_hash_each_frame(c_encoder):
    identity=codec.raw_encoder_metadata('pybase64_1_5_1')
    assert identity['version']=='1.5.1' and identity['module']=='pybase64._pybase64'
    assert identity['extension_sha256']==hashlib.sha256(Path(identity['extension_path']).read_bytes()).hexdigest()
    identity['version']='mutated caller copy'
    with patch.object(Path,'read_bytes',side_effect=AssertionError('Per-frame extension rehash')):
        assert codec.load_raw_encoder('pybase64_1_5_1') is c_encoder
        assert codec.raw_encoder_metadata('pybase64_1_5_1')['version']=='1.5.1'
        assert_parity(c_encoder,b'\xff\x00\xfe')


def test_real_saved_1440x1080_bgr_and_rgb_swap_pixel_parity(c_encoder):
    root=Path(__file__).resolve().parents[1]
    run=root/'artifacts/wsl-native-live-20261013-attempt8-stdin-scalar-caps'
    if not run.exists():pytest.skip('Actual saved sensor evidence absent in fresh CI checkout')
    from tools.diagnose_native_saved_compute import select_saved_native_input
    saved=select_saved_native_input(run);bgr=saved['content']
    assert len(bgr)==1440*1080*3
    rgb=bytearray(len(bgr));rgb[0::3]=bgr[2::3];rgb[1::3]=bgr[1::3];rgb[2::3]=bgr[0::3]
    assert_parity(c_encoder,bgr);assert_parity(c_encoder,bytes(rgb))


def test_existing_raw_only_factory_still_mints_identity_bound_token():
    from rm_match.platform_v2.camera_pixels import encode_camera_pixels
    raw=b'\x00\xff\x19'*2
    encoded,token=encode_camera_pixels(raw,robot_id='red_sentry',episode=0,frame_id=1,
        capture_sim_time=.41,encoding='rgb8',width=2,height=1,stride_bytes=6)
    camera=dict(frame_id=1,capture_sim_time=.41,image=dict(encoding='rgb8',width=2,height=1,
        stride_bytes=6,data_base64=encoded))
    assert token.matches(camera,robot_id='red_sentry',episode=0)
    assert token.raw_bytes is raw and base64.b64decode(encoded,validate=True)==raw
