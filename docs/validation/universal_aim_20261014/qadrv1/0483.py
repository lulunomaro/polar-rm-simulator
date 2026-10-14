"""Decode every video frame with ffmpeg; no success from metadata alone."""
import argparse,hashlib,json,subprocess
from pathlib import Path
import imageio_ffmpeg
p=argparse.ArgumentParser();p.add_argument('video',type=Path);p.add_argument('--expected-frames',type=int);a=p.parse_args()
reader=imageio_ffmpeg.read_frames(str(a.video),pix_fmt='rgb24')
meta=next(reader);frames=0;first=None;last=None
for raw in reader:
 if frames==0:first=hashlib.sha256(raw).hexdigest()
 last=hashlib.sha256(raw).hexdigest();frames+=1
result=dict(file=a.video.name,sha256=hashlib.sha256(a.video.read_bytes()).hexdigest(),bytes=a.video.stat().st_size,
    width=meta['size'][0],height=meta['size'][1],fps=meta['fps'],decoded_frames=frames,duration=meta['duration'],
    first_decoded_frame_sha256=first,last_decoded_frame_sha256=last,decode_all_passed=True)
if a.expected_frames is not None:
 result['expected_frames']=a.expected_frames;result['frame_count_matches']=frames==a.expected_frames
 if frames!=a.expected_frames:raise SystemExit(json.dumps(result))
print(json.dumps(result,indent=2))
