"""Build an EPISODES entry for index.html from a narration take, so every caption and camera move lands on the right words.

Use it from a small per-day script (copy studio/examples/day8.py):

    from episode import Episode
    ep = Episode('day9', 'work/align.json')          # the output of align_narration.py
    ep.hook(0, 1, at=0.3)                             # sentences 0-1 are the hook line, 0.3 s into the cold open
    ep.segment('A', 2, 3, at=1.0)                     # sentences 2-3 start at 1.0 s of the EPISODE (title card)
    ep.segment('B', 4, 9, at=4.5)
    s, e = ep.s, ep.e                                 # s(i) / e(i): when sentence i starts / ends in episode time
    ...build cam / hour / events / captions using s() and e()...
    ep.write(title='Day 9 · ...', dur=e(LAST) + 3.2, hook={...}, cam=cam, hour=hour, events=events, captions=captions)

write() saves work/<key>.js (the EPISODES entry) and work/<key>_segments.json (for assemble_reel.py), and prints the
cold-open length to pass to render_reel.py --hook. Then: python3 studio/insert_episode.py work/<key>.js
"""
import json, math, os


class Episode:
    def __init__(self, key, align_json, workdir=None):
        self.key = key
        self.sent = {k: (a, b, t) for k, a, b, t in json.load(open(align_json))['sentences']}
        self.T, self.segs, self.hook_seg = {}, [], None
        self.workdir = workdir or os.path.dirname(os.path.abspath(align_json))

    def _place(self, name, first, last, at, hook=False):
        off = at - self.sent[first][0]
        seg = {'name': name, 'from': self.sent[first][0], 'to': self.sent[last][1], 'at': at}
        if hook: seg['hook'] = True
        else:
            for i in range(first, last + 1): self.T[i] = (round(self.sent[i][0] + off, 2), round(self.sent[i][1] + off, 2))
        self.segs.append(seg); return seg

    def hook(self, first, last, at=0.3):
        self.hook_seg = self._place('hook', first, last, at, hook=True)

    def segment(self, name, first, last, at):
        self._place(name, first, last, at)

    def s(self, i): return self.T[i][0]
    def e(self, i): return self.T[i][1]

    def hook_seconds(self):
        if not self.hook_seg: return 0.0
        h = self.hook_seg['at'] + (self.hook_seg['to'] - self.hook_seg['from']) + .45      # the line, then a breath before the title
        return math.ceil(h * 30) / 30

    def write(self, title, dur, cam, hour, events, captions, hook=None, audio_offset=1.0):
        r = lambda v: json.dumps(v, ensure_ascii=False)
        rnd = lambda rows: [[round(x[0], 2)] + list(x[1:]) for x in rows]
        for name, rows in (('cam', cam), ('hour', hour)):
            ts = [x[0] for x in rows]
            assert ts == sorted(ts), f'{name} keys must be in time order: {ts}'
        assert all(c[0] < c[1] for c in captions), 'a caption ends before it starts'
        h = ''
        if hook:
            h = f"\n    hook: {{ from: {hook['from']}, tag: {r(hook['tag'])}, lines: {r(hook['lines'])} }},"
        js = (f"  {self.key}: {{\n    title: {r(title)}, dur: {round(dur, 1)}, audioOffset: {audio_offset},{h}\n"
              f"    cam: {r(rnd(cam))},\n    hour: {r(rnd(hour))},\n    events: {r(rnd(events))},\n"
              f"    captions: {r([[round(c[0], 2), round(c[1], 2)] + list(c[2:]) for c in captions])}\n  }},\n")
        jp = os.path.join(self.workdir, f'{self.key}.js'); open(jp, 'w').write(js)
        sp = os.path.join(self.workdir, f'{self.key}_segments.json')
        json.dump({'hook_seconds': self.hook_seconds(), 'main_dur': round(dur, 1), 'segments': self.segs}, open(sp, 'w'), indent=1)
        print(f'wrote {jp} and {sp}')
        print(f'episode {round(dur, 1)} s + cold open {self.hook_seconds():.3f} s = {round(dur, 1) + self.hook_seconds():.1f} s total')
        print(f'render with: python3 studio/render_reel.py {self.key} work/render --hook {self.hook_seconds():.3f}')
