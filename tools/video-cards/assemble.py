# Joins title cards and recordings into one H.264 video with fades and a silent audio track.
# usage: python tools/video-cards/assemble.py OUT.mp4 WIDTH HEIGHT SPEED SEGMENT...
#   SEGMENT = img:PATH:SECONDS (a card) | vid:PATH (a recording, played SPEED times faster)
import shutil
import subprocess  # nosec B404 - runs ffmpeg/ffprobe with arguments built here, no shell
import sys

FFMPEG, FFPROBE = shutil.which('ffmpeg'), shutil.which('ffprobe')
if not FFMPEG or not FFPROBE:
    sys.exit('ffmpeg and ffprobe must be installed')
out, W, H, speed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4])
segs = sys.argv[5:]
inputs, filters, total, labels = [], [], 0.0, []
for i, s in enumerate(segs):
    kind, path, *rest = s.split(':')
    if kind == 'img':
        d = float(rest[0]); inputs += ['-loop', '1', '-t', str(d), '-i', path]
        pre = ''
    else:
        raw = float(subprocess.check_output([FFPROBE, '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path]).decode())
        d = round(raw / speed, 3); inputs += ['-i', path]; pre = f'setpts=PTS/{speed},'
    fade_in = 'fade=in:st=0:d=0.4'
    fade_out = f'fade=out:st={d - 0.45:.3f}:d=0.45' if i < len(segs) - 1 else ''
    chain = f'[{i}]{pre}scale={W}:{H}:flags=lanczos,fps=30,format=yuv420p,{fade_in}' + (f',{fade_out}' if fade_out else '') + f'[s{i}]'
    filters.append(chain); labels.append(f'[s{i}]'); total += d
filters.append(''.join(labels) + f'concat=n={len(segs)}:v=1:a=0[v]')
n = len(segs)
cmd = [FFMPEG, '-v', 'error', '-y', *inputs, '-f', 'lavfi', '-t', f'{total:.3f}', '-i', 'anullsrc=channel_layout=stereo:sample_rate=48000',
       '-filter_complex', ';'.join(filters), '-map', '[v]', '-map', f'{n}:a', '-c:v', 'libx264', '-preset', 'slow', '-crf', '20',
       '-pix_fmt', 'yuv420p', '-profile:v', 'high', '-c:a', 'aac', '-b:a', '64k', '-shortest', '-movflags', '+faststart', out]
subprocess.check_call(cmd)
print(out, round(total, 1), 's')
