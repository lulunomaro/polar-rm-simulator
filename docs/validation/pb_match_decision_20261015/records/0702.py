"""Portable JSON: unobservable/nonfinite diagnostics are null, never JS-invalid Infinity."""
import json,math

def json_safe(value):
    if isinstance(value,dict):return {str(k):json_safe(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [json_safe(v) for v in value]
    if hasattr(value,'tolist'):return json_safe(value.tolist())
    if isinstance(value,float) and not math.isfinite(value):return None
    return value

def dumps(value,**kwargs):
    return json.dumps(json_safe(value),allow_nan=False,**kwargs)
