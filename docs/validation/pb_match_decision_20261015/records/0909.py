"""Explicit canonical raw encoders. Optional C identity is checked only at setup.

Select a fixed local enum; no callbacks, import paths, or network configuration.
The C encoder's pinned API supplies standard alphabet, padding, and no wrapping.
"""
from __future__ import annotations
from copy import deepcopy
from functools import lru_cache
import hashlib
import importlib
from importlib import metadata
from importlib.machinery import ExtensionFileLoader,EXTENSION_SUFFIXES
from pathlib import Path
from types import BuiltinFunctionType

MAX_RAW_BYTES=8*1024*1024
CODECS=('stdlib_chunked','pybase64_1_5_1')


def _codec_name(codec):
    if type(codec) is not str or codec not in CODECS:raise ValueError('Unknown raw base64 codec')
    return codec


@lru_cache(maxsize=2)
def _binding(codec):
    if codec=='stdlib_chunked':
        from .camera import encode_raw_base64
        return encode_raw_base64,dict(codec=codec,version=None,module=encode_raw_base64.__module__,
            function='encode_raw_base64',extension_path=None,extension_sha256=None)
    try:
        package=importlib.import_module('pybase64')
        version=metadata.version('pybase64')
        if version!='1.5.1' or getattr(package,'__version__',None)!='1.5.1':
            raise ValueError('Raw codec requires exactly pybase64 1.5.1')
        extension=importlib.import_module('pybase64._pybase64')
    except (ImportError,metadata.PackageNotFoundError) as exc:
        raise ValueError('Raw codec requires installed pybase64 1.5.1 C extension') from exc
    encode=getattr(extension,'b64encode_as_string',None);spec=getattr(extension,'__spec__',None)
    origin=getattr(extension,'__file__',None)
    if (getattr(extension,'__name__',None)!='pybase64._pybase64'
        or type(encode) is not BuiltinFunctionType or encode.__module__!='pybase64._pybase64'
        or getattr(package,'b64encode_as_string',None) is not encode
        or spec is None or spec.name!='pybase64._pybase64'
        or not isinstance(spec.loader,ExtensionFileLoader) or type(origin) is not str
        or spec.origin!=origin or not any(origin.endswith(suffix) for suffix in EXTENSION_SUFFIXES)):
        raise ValueError('Raw codec rejects non-C pybase64 fallback or mismatched extension')
    path=Path(origin)
    try:extension_sha=hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:raise ValueError('Raw codec C extension identity unavailable') from exc
    if encode(b'\x00\xff',altchars=None,padded=True,wrapcol=0)!='AP8=':
        raise ValueError('Raw codec canonical C encoding self-check failed')
    def bounded_encode(raw):
        if type(raw) is not bytes or len(raw)>MAX_RAW_BYTES:
            raise ValueError('Raw codec requires immutable bytes bounded to 8 MiB')
        result=encode(raw,altchars=None,padded=True,wrapcol=0)
        if type(result) is not str or len(result)!=4*((len(raw)+2)//3):
            raise ValueError('Raw codec C output shape mismatch')
        return result
    identity=dict(codec=codec,version=version,module=extension.__name__,function='b64encode_as_string',
        extension_path=str(path.resolve()),extension_sha256=extension_sha)
    return bounded_encode,identity


def load_raw_encoder(codec='stdlib_chunked'):
    """Return the cached checked local encoder; fail before camera startup."""
    return _binding(_codec_name(codec))[0]


def raw_encoder_metadata(codec='stdlib_chunked'):
    """Copied setup identity; extension hashing is never done per frame."""
    return deepcopy(_binding(_codec_name(codec))[1])
