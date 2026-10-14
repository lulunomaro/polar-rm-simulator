#!/usr/bin/env python3
"""Production CPU thread-only overlay; no tracing, request allocation or inference."""
from __future__ import annotations
import argparse
from pathlib import Path

def checked_threads(value):
    if type(value) is not int or not 1<=value<=32:raise ValueError('inference_threads must be an integer in 1..32')
    return value

def render_threads(base,threads):
    base=Path(base);threads=checked_threads(threads)
    original=(base/'candidate/src/module/detector/armor_detection.cpp').read_bytes().replace(b'\r\n',b'\n')
    anchor=b'        openvino_model   = model.compile(openvino_core, config.model_location);'
    if original.count(anchor)!=1:raise ValueError('Production inference source anchor changed')
    replacement=(b'        rmcs::production_inference::configure(openvino_core);\n'+anchor+
        b'\n        rmcs::production_inference::verify_and_report(openvino_model);')
    armor=b'#include "production_inference_threads.hpp"\n'+original.replace(anchor,replacement,1)
    header=(base/'overlays/production_inference_threads.hpp').read_bytes().replace(b'\r\n',b'\n')
    if header.count(b'@INFERENCE_THREADS@')!=1:raise ValueError('Production thread header anchor changed')
    return {'armor_detection_threads.cpp':armor,
        'production_inference_threads.hpp':header.replace(b'@INFERENCE_THREADS@',str(threads).encode())}

def generate_threads(base,generated,threads):
    generated=Path(generated)
    if not generated.is_dir():raise ValueError('Existing prepared generated directory required')
    for name,content in render_threads(base,threads).items():
        with (generated/name).open('xb') as stream:stream.write(content)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',type=Path,required=True);parser.add_argument('--generated',type=Path,required=True)
    parser.add_argument('--inference-threads',type=int,required=True)
    args=parser.parse_args();generate_threads(args.base,args.generated,args.inference_threads)

if __name__=='__main__':main()
