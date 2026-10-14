"""Pure OpenCV API contract fixtures; no real camera, model, WSL or GL."""
import copy
import os
from types import SimpleNamespace
from unittest.mock import Mock,patch
import pytest
from rm_match.platform_v2 import host_opencv as helper


def cv_fixture(*counts):
    return SimpleNamespace(__version__='4.13.0',__file__='/reviewed/site-packages/cv2/__init__.py',
        getNumThreads=Mock(side_effect=counts or [32]),setNumThreads=Mock())


def test_default_queries_actual_host_state_without_setter_or_env_changes():
    cv=cv_fixture(32);before=copy.deepcopy(dict(os.environ))
    with patch.object(helper.importlib,'import_module',return_value=cv) as load:
        metadata=helper.configure_opencv_threads()
    load.assert_called_once_with('cv2');cv.setNumThreads.assert_not_called()
    cv.getNumThreads.assert_called_once_with()
    assert metadata['before_threads']==metadata['effective_threads']==32
    assert metadata['requested_threads'] is None and metadata['action']=='query_only'
    assert metadata['linux_native_changed'] is False and metadata['environment_changed'] is False
    assert metadata['images_processed']==metadata['inference_calls']==0
    assert dict(os.environ)==before


@pytest.mark.parametrize('threads',[1,4,32])
def test_explicit_option_requires_actual_effective_api_value(threads):
    cv=cv_fixture(32,threads)
    with patch.object(helper.importlib,'import_module',return_value=cv):metadata=helper.configure_opencv_threads(threads)
    cv.setNumThreads.assert_called_once_with(threads)
    assert cv.getNumThreads.call_count==2 and metadata['requested_threads']==metadata['effective_threads']==threads
    assert metadata['before_threads']==32 and metadata['opencv_version']=='4.13.0'
    assert metadata['module_path']==cv.__file__ and metadata['scope']=='host_camera_lenswarp_and_color_conversion'


@pytest.mark.parametrize('invalid',[True,False,0,-1,33,1.,'1',{},lambda:1])
def test_nonlocal_enum_alias_or_free_callback_rejected_before_import(invalid):
    with patch.object(helper.importlib,'import_module') as load:
        with pytest.raises(ValueError,match='require_local_integer'):helper.configure_opencv_threads(invalid)
        load.assert_not_called()


@pytest.mark.parametrize('after',[32,True,1.,0,None])
def test_environment_assumption_or_wrong_effective_type_is_not_success(after):
    cv=cv_fixture(32,after)
    with patch.object(helper.importlib,'import_module',return_value=cv):
        with pytest.raises(ValueError,match='not_effective'):helper.configure_opencv_threads(1)
    cv.setNumThreads.assert_called_once_with(1)


@pytest.mark.parametrize('before',[False,0,-1,32.,65537])
def test_invalid_before_query_never_sets_threads(before):
    cv=cv_fixture(before)
    with patch.object(helper.importlib,'import_module',return_value=cv):
        with pytest.raises(ValueError,match='before_threads_invalid'):helper.configure_opencv_threads(1)
    cv.setNumThreads.assert_not_called()


def test_missing_module_and_failed_set_or_query_are_explicit_no_fallback():
    with patch.object(helper.importlib,'import_module',side_effect=ImportError('missing')):
        with pytest.raises(ValueError,match='import_failed'):helper.configure_opencv_threads(1)
    for stage in ('before','set','after'):
        cv=cv_fixture(32,1)
        if stage=='before':cv.getNumThreads.side_effect=RuntimeError('query')
        elif stage=='set':cv.setNumThreads.side_effect=RuntimeError('set')
        else:cv.getNumThreads.side_effect=[32,RuntimeError('query')]
        with patch.object(helper.importlib,'import_module',return_value=cv):
            with pytest.raises(ValueError,match=stage+'_.*failed' if stage!='set' else 'set_failed'):
                helper.configure_opencv_threads(1)


def test_unavailable_version_or_path_cannot_masquerade_as_verified_module():
    for key,value in (('__version__',None),('__version__','x\n'),('__file__',None)):
        cv=cv_fixture();setattr(cv,key,value)
        with patch.object(helper.importlib,'import_module',return_value=cv):
            with pytest.raises(ValueError,match='identity_unavailable'):helper.configure_opencv_threads(1)
        cv.setNumThreads.assert_not_called()
