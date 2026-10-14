#!/usr/bin/env python3
"""Compose recorded native-camera evaluations. No simulation or model inference.

Every output picture uses one existing decoded frame from each paired source.
Only cropping, presentation resizing, and text overlays are performed. Source
files remain untouched; the manifest hashes and audits all supporting ledgers.
"""
import argparse
import bisect
import hashlib
import json
import math
import subprocess
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SIZE = (2048, 1152)
FPS = 30
BG = '#10151e'
INK = '#eef3fc'
MUTED = '#aab8cb'
AMBER = '#ffd17f'
COLORS = ['#75b6ff', '#6ee4bc']
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
FONTS = {}
SCENARIOS = ['stationary_near', 'lateral', 'variable_spin', 'occlusion', 'stationary_far']
TITLES = {'stationary_near': 'Stationary / near', 'lateral': 'Lateral motion',
          'variable_spin': 'Variable spin', 'occlusion': 'Occlusion',
          'stationary_far': 'Stationary / far'}


def font(size, bold=False):
    key = (size, bold)
    if key not in FONTS:
        FONTS[key] = ImageFont.truetype(BOLD if bold else FONT, size)
    return FONTS[key]


def text(draw, xy, value, size=24, fill=INK, bold=False):
    draw.text(xy, str(value), font=font(size, bold), fill=fill)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def probe(path):
    return json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-count_frames', '-show_entries',
        'stream=width,height,r_frame_rate,nb_frames,nb_read_frames,duration:format=duration:chapter=start_time,end_time:chapter_tags=title',
        '-of', 'json', str(path)], text=True))


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class Source:
    def __init__(self, directory):
        self.path = directory
        self.summary = json.loads((directory / 'summary.json').read_text())
        self.ticks = read_jsonl(directory / 'actor_ticks.jsonl')
        self.tick_times = [x['sim_time'] for x in self.ticks]
        self.events = json.loads((directory / 'referee_events.json').read_text())
        self.times = {
            'raw_positive': [x['sim_time'] for x in self.ticks if x['camera_frame'] and x['telemetry'].get('raw_detections', 0) > 0],
            'team_accepted': [x['sim_time'] for x in self.ticks if x['camera_frame'] and x['telemetry'].get('detections', 0) > 0],
            'shots': [x['sim_time'] for x in self.events if x['type'] == 'fire' and x.get('robot_id') == 'red_sentry'],
            'damage': [x['sim_time'] for x in self.events if x['type'] == 'impact' and x.get('shooter_id') == 'red_sentry' and x.get('valid_damage')],
        }
        self.impacts = [x for x in self.events if x['type'] == 'impact' and x.get('shooter_id') == 'red_sentry']
        for key in self.times:
            self.times[key].sort()
        self.totals = {k: len(v) for k, v in self.times.items()}
        for count, expected in [('team_accepted', 'detector_positive_frames'), ('shots', 'total_fired'), ('damage', 'judge_valid_damage_hits')]:
            assert self.totals[count] == self.summary[expected], (directory, count, self.totals, self.summary[expected])
        if 'raw_detector_positive_frames' in self.summary:
            assert self.totals['raw_positive'] == self.summary['raw_detector_positive_frames']
        assert all(abs(t['telemetry']['fire_angle_tol_deg'] - 3.) < 1e-9 for t in self.ticks)
        self.video = directory / 'evaluation.mp4'
        self.probe = probe(self.video)
        stream = self.probe['streams'][0]
        assert (stream['width'], stream['height']) == (1280, 800)
        assert stream['r_frame_rate'] == '30/1'
        self.frames = int(stream['nb_read_frames'])
        assert self.frames == self.summary['video_frames']
        self.hashes = {name: sha(directory / name) for name in ['evaluation.mp4', 'summary.json', 'actor_ticks.jsonl', 'referee_events.json']}

    def state(self, sim_time):
        tick = self.ticks[max(0, bisect.bisect_right(self.tick_times, sim_time + 1e-8) - 1)]
        counts = {k: bisect.bisect_right(v, sim_time + 1e-8) for k, v in self.times.items()}
        impact = next((x for x in reversed(self.impacts) if x['sim_time'] <= sim_time + 1e-8), None)
        return tick['telemetry'], counts, impact

    def manifest(self):
        return {'directory': str(self.path), 'sha256': self.hashes, 'probe': self.probe,
                'full_window_counts': self.totals, 'seconds': self.summary['seconds'],
                'camera_profile': self.summary['camera_profile'], 'timing': self.summary['timing'],
                'warp_black_border_fraction': self.summary.get('warp_black_border_fraction'),
                'visual_profile': self.summary['visual_profile']}


def panel(canvas, x, frame, source, sim_time, index):
    d = ImageDraw.Draw(canvas)
    color = COLORS[index]
    d.rounded_rectangle((x, 176, x + 976, 348), radius=14, fill='#1b2432')
    title = 'ORIGINAL' if index == 0 else 'PITCHFIX CANDIDATE'
    text(d, (x + 18, 186), title, 28, color, True)
    text(d, (x + 18, 226), f'Same 3.0 deg fire-angle threshold  |  {source.summary["seconds"]:.1f} s window', 20, MUTED)
    telemetry, counts, impact = source.state(sim_time)
    labels = [('raw_positive', 'Raw+ frames'), ('team_accepted', 'Team-accepted'), ('shots', 'Actual shots'), ('damage', 'Valid damage hits')]
    for j, (key, label) in enumerate(labels):
        xx = x + 18 + j * 240
        text(d, (xx, 264), counts[key], 39, color, True)
        text(d, (xx, 313), label, 19, MUTED)
    text(d, (x, 366), 'ARMOR DETAIL / recorded spectator view', 21, INK, True)
    # Remove only source title text; avoid the actor inset overlapping the
    # bottom 20 pixels of the source detail view.
    canvas.paste(frame.crop((640, 100, 1280, 560)), (x, 400))
    text(d, (x + 656, 366), 'PHYSICS OVERVIEW', 20, MUTED, True)
    canvas.paste(frame.crop((0, 100, 640, 560)).resize((320, 230), Image.Resampling.LANCZOS), (x + 656, 400))
    text(d, (x + 656, 641), 'RECORDED CAMERA INSET', 18, MUTED, True)
    inset_note = '(source caption retained)' if not source.summary['camera_profile'].get('overscan_pixels', 0) else '(native 1440x1080; shown 320x240)'
    text(d, (x + 656, 664), inset_note, 14, MUTED)
    # The existing 320x240 inset is copied intact, including any source
    # spectator-caption overlap. It is not a regenerated camera frame.
    canvas.paste(frame.crop((480, 560, 800, 800)), (x + 656, 680))
    text(d, (x, 880), f'Sim t = {sim_time:5.3f} s', 27, color, True)
    error = telemetry.get('aim_error_deg')
    error_text = f'{error:.2f} deg' if error is not None else 'unavailable'
    text(d, (x, 923), f'Reported aim error: {error_text}', 22)
    text(d, (x, 957), f'Tracking: {"yes" if telemetry.get("tracking") else "no"}  |  Fresh: {"yes" if telemetry.get("fresh") else "no"}', 21, MUTED)
    if impact:
        label = 'valid damage' if impact.get('valid_damage') else impact.get('reason', 'no valid damage').replace('_', ' ')
        event_line = f'Last impact @ {impact["sim_time"]:.3f}s: {label}'
    else:
        event_line = 'No impact recorded yet'
    text(d, (x, 991), event_line, 21, AMBER)
    totals = source.totals
    text(d, (x, 1026), f'Full {source.summary["seconds"]:.1f}s: ' + 'raw+ {raw_positive}  /  accepted {team_accepted}  /  shots {shots}  /  damage {damage}'.format(**totals), 18, MUTED)


def compose(frames, sources, scenario, chapter, chapters, sim_time, visual):
    canvas = Image.new('RGB', SIZE, BG)
    d = ImageDraw.Draw(canvas)
    profile = sources[0].summary['camera_profile']
    overscan = profile.get('overscan_pixels', 0)
    suffix = '  |  v2.1 overscan control' if overscan and 'v2.1' in visual else ('  |  v2.2 LED-core revision' if 'v2.2' in visual else '')
    text(d, (24, 20), f'{chapter:02d}/{chapters:02d}  {TITLES[scenario]}{suffix}', 38, INK, True)
    text(d, (24, 76), f'{visual} | Native source K/D, 1440x1080 association ASSUMED', 25, AMBER)
    text(d, (24, 116), 'Capture 80 Hz  /  detector service 36 Hz  /  policy 100 Hz  /  recorded video 30 fps', 21, MUTED)
    border = 100 * sources[0].summary.get('warp_black_border_fraction', 0.)
    text(d, (24, 148), f'Optics: {profile["name"]}  |  overscan {overscan}px  |  warp black border {border:.2f}%', 17, MUTED)
    for i, (frame, source) in enumerate(zip(frames, sources)):
        panel(canvas, 24 + 1024 * i, Image.fromarray(frame), source, sim_time, i)
    d = ImageDraw.Draw(canvas)
    d.line((24, 1067, 2024, 1067), fill='#3a4658', width=2)
    text(d, (24, 1082), 'Approximate plant / appearance. Uncalibrated synthetic fixture; not a hardware accuracy claim.', 22, AMBER)
    text(d, (24, 1117), 'Raw+/accepted count processed frames. Shots/damage use referee ledger. Camera insets are downscaled presentation, copied from recordings.', 19, MUTED)
    return canvas


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--out', type=Path, default=Path('artifacts/native80_diagnostic'))
    p.add_argument('--near-only', action='store_true')
    p.add_argument('--include-overscan', action='store_true')
    p.add_argument('--include-v22', action='store_true')
    args = p.parse_args()
    out = args.out if args.out.is_absolute() else args.root / args.out
    out.mkdir(parents=True, exist_ok=True)
    cases = []
    for scenario in (SCENARIOS[:1] if args.near_only else SCENARIOS):
        base = 'native80_matrix' if scenario == 'stationary_near' else 'native80_remaining'
        cases.append((scenario, args.root / 'artifacts' / base))
    if args.include_overscan:
        cases += [('stationary_near', args.root / 'artifacts/native80_v21_overscan')]
    if args.include_v22:
        cases += [(s, args.root / 'artifacts/native80_v22') for s in ['stationary_near', 'lateral']]
    pairs = [(scenario, [Source(base / f'{scenario}_{variant}') for variant in ['original', 'pitch_candidate']]) for scenario, base in cases]
    video = out / 'diagnostic.mp4'
    frame_map = []
    chapters = []
    output_frame = 0
    with imageio.get_writer(video, fps=FPS, codec='libx264', quality=8, macro_block_size=1,
                            ffmpeg_params=['-preset', 'fast', '-movflags', '+faststart', '-threads', '2']) as writer:
        for chapter, (scenario, sources) in enumerate(pairs, 1):
            assert sources[0].frames == sources[1].frames
            assert sources[0].summary['visual_profile'] == sources[1].summary['visual_profile']
            assert sources[0].summary['camera_profile'] == sources[1].summary['camera_profile']
            visual = sources[0].summary['visual_profile']
            print(f'ASSEMBLING {chapter}/{len(pairs)} {visual} {scenario}: {sources[0].frames} frames', flush=True)
            chapter_info = {'chapter': chapter, 'scenario': scenario, 'visual_profile': visual,
                            'output_start_s': output_frame / FPS, 'output_start_frame': output_frame,
                            'frame_count': sources[0].frames, 'sources': [s.manifest() for s in sources]}
            readers = [imageio.get_reader(s.video, format='ffmpeg') for s in sources]
            try:
                for n in range(sources[0].frames):
                    frames = [r.get_next_data() for r in readers]
                    # Original simulation video renders at the next physics tick
                    # on or after n/30; 2 kHz physics is recorded in each summary.
                    physics_hz = sources[0].summary['timing']['physics_hz']
                    sim_time = math.ceil((n / FPS) * physics_hz - 1e-8) / physics_hz
                    composed = compose(frames, sources, scenario, chapter, len(pairs), sim_time, visual)
                    writer.append_data(np.asarray(composed))
                    if n in [0, 10, sources[0].frames // 2, sources[0].frames - 1]:
                        composed.save(out / f'chapter_{chapter:02d}_{scenario}_frame_{n:04d}.png')
                    frame_map.append({'output_frame': output_frame, 'chapter': chapter,
                                      'source_frame': n, 'source_sim_time': sim_time})
                    output_frame += 1
            finally:
                for r in readers:
                    r.close()
            chapters.append(chapter_info)
    # Container chapters provide precise navigation without adding title-card
    # or frozen frames. This is stream-copy remuxing, not another image encode.
    metadata_lines = [';FFMETADATA1', 'title=Recorded MuJoCo native-camera diagnostic']
    for chapter_info in chapters:
        cp = chapter_info['sources'][0]['camera_profile']
        optics = f'overscan {cp.get("overscan_pixels", 0)}px'
        title = f'{chapter_info["chapter"]:02d}: {TITLES[chapter_info["scenario"]]} | {chapter_info["visual_profile"]} | {optics}'
        start = chapter_info['output_start_frame']
        end = start + chapter_info['frame_count']
        metadata_lines.extend(['[CHAPTER]', 'TIMEBASE=1/1000', f'START={round(1000 * start / FPS)}',
                               f'END={round(1000 * end / FPS)}', f'title={title}'])
    metadata_path = out / 'chapters.ffmetadata'
    metadata_path.write_text('\n'.join(metadata_lines) + '\n')
    chapter_video = out / 'diagnostic.chapters.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(video), '-i', str(metadata_path),
                    '-map_metadata', '1', '-map_chapters', '1', '-codec', 'copy',
                    '-movflags', '+faststart', str(chapter_video)], check=True)
    chapter_video.replace(video)
    result_probe = probe(video)
    assert int(result_probe['streams'][0]['nb_read_frames']) == output_frame
    assert abs(float(result_probe['format']['duration']) - output_frame / FPS) < .001
    assert len(result_probe.get('chapters', [])) == len(chapters)
    for _, sources in pairs:
        for source in sources:
            assert all(sha(source.path / name) == digest for name, digest in source.hashes.items()), 'Source modified'
    (out / 'frame_map.jsonl').write_text('\n'.join(json.dumps(row) for row in frame_map) + '\n')
    manifest = {'output': str(video), 'output_sha256': sha(video), 'output_probe': result_probe,
                'assembler_sha256': sha(Path(__file__)),
                'frame_count': output_frame, 'fps': FPS, 'duration_s': output_frame / FPS,
                'chapters': chapters,
                'method': 'Existing paired video frames only; one-to-one temporal mapping; crops, text overlays, one overview downscale. No inference, simulation, frame interpolation, new physics, or invented hits.',
                'source_inset': 'Exact 320x240 crop from source clip; native actor input was 1440x1080. Existing caption overlap retained. Full native pixels cannot be recovered from encoded inset.',
                'counter_definitions': {'raw_positive': 'Cumulative camera_frame ticks with raw_detections > 0',
                                        'team_accepted': 'Cumulative camera_frame ticks with detections > 0',
                                        'shots': 'Cumulative red_sentry fire referee events',
                                        'damage': 'Cumulative red_sentry impact referee events with valid_damage=true'},
                'counter_timing': 'Main numbers are cumulative at displayed source simulation time. Full-window footer uses all ledger rows, including final ticks after last recorded frame.',
                'source_files_unchanged': True}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'output': str(video), 'frames': output_frame, 'duration_s': output_frame / FPS, 'bytes': video.stat().st_size}, indent=2), flush=True)


if __name__ == '__main__':
    main()
