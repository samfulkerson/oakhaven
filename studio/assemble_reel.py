"""Put the finished Reel together: cold open + episode frames, the narration cut into segments and placed on the timeline,
a very quiet room-tone bed, loudness -17.5 LUFS, H.264 sized for Instagram.

  python3 studio/assemble_reel.py RENDER_DIR NARRATION.mp3 SEGMENTS.json OUT.mp4

RENDER_DIR is what render_reel.py wrote (main/ and hook/). SEGMENTS.json is written by the episode builder:
  {"hook_seconds": 5.0, "main_dur": 124.6,
   "segments": [{"name": "hook", "from": 0.0, "to": 4.31, "at": 0.3, "hook": true},      # placed in the cold open
                {"name": "A", "from": 4.96, "to": 6.84, "at": 1.0}, ...]}               # 'at' is EPISODE time
'from'/'to' are seconds in the narration take (from align_narration.py). Final video length = hook_seconds + main_dur.
"""
import json, os, subprocess, sys

rd, narr, segf, out = sys.argv[1:5]
cfg = json.load(open(segf)); H, MD, segs = cfg['hook_seconds'], cfg['main_dur'], cfg['segments']
fps = 30
hook = sorted(f for f in os.listdir(f'{rd}/hook') if f.endswith('.jpg'))
main = sorted(f for f in os.listdir(f'{rd}/main') if f.endswith('.jpg'))
assert len(hook) == round(H * fps), f'{len(hook)} hook frames, expected {round(H * fps)}: render with --hook {H}'
assert abs(len(main) - round(MD * fps)) <= 1, f'{len(main)} episode frames, expected {round(MD * fps)}'
lst = out + '.txt'
with open(lst, 'w') as f:
    for d, names in (('hook', hook), ('main', main)):
        for n in names: f.write(f"file '{os.path.abspath(rd)}/{d}/{n}'\nduration {1 / fps}\n")
subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', lst, '-vf', f'fps={fps},format=yuv420p',
                '-c:v', 'libx264', '-crf', '21', '-preset', 'veryfast', out + '.v.mp4'], check=True)
total = H + MD
segs = sorted(segs, key=lambda s: s['from'])
parts, labels = [], []
for i, s in enumerate(segs):
    a = max(0, s['from'] - .1); b = s['to'] + .25                 # a little air either side of the words
    if i + 1 < len(segs) and segs[i + 1]['from'] < b + .05: b = (s['to'] + segs[i + 1]['from']) / 2
    at = s['at'] if s.get('hook') else H + s['at']
    ms = int(round((at - (s['from'] - a)) * 1000))
    parts.append(f"[1:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,afade=t=in:d=0.04,afade=t=out:st={b - a - .06:.3f}:d=0.06,adelay={ms}|{ms}[s{i}]")
    labels.append(f'[s{i}]')
flt = (';'.join(parts) + f";{''.join(labels)}amix=inputs={len(labels)}:normalize=0,apad,atrim=0:{total}[n];"
       f"[2:a]lowpass=f=300,volume=0.023,atrim=0:{total}[b];[n][b]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-17.5:TP=-1.5:LRA=7,alimiter=limit=0.84[m]")
subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', out + '.v.mp4', '-i', narr, '-f', 'lavfi', '-i', f'anoisesrc=color=brown:d={total}:r=44100',
                '-filter_complex', flt, '-map', '0:v', '-map', '[m]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-t', f'{total}',
                '-movflags', '+faststart', out], check=True)
os.remove(out + '.v.mp4'); os.remove(lst)
size = os.path.getsize(out) / 1e6
print(f'wrote {out}: {total:.1f} s, {size:.0f} MB')
