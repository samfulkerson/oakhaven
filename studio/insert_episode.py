"""Put (or replace) an episode in index.html's EPISODES, newest first.

  python3 studio/insert_episode.py work/day9.js

The file holds one entry as written by episode.py ("  day9: { ... },"). If index.html already has that key, it is replaced.
"""
import re, sys

js = open(sys.argv[1], encoding='utf-8').read()
key = re.match(r'\s*(\w+): \{', js).group(1)
p = 'index.html'
s = open(p, encoding='utf-8').read()
head = 'const EPISODES = {\n'
assert s.count(head) == 1
i0 = s.index(head) + len(head)
m = re.search(rf'^  {key}: \{{', s[i0:], re.M)
if m:                                              # replace the old version: up to the next top-level entry
    a = i0 + m.start()
    nxt = re.search(r'^  \w+: \{', s[a + 3:], re.M)
    b = a + 3 + nxt.start() if nxt else s.index('\n};', a) + 1
    s = s[:a] + js + s[b:]
    print('replaced', key)
else:
    s = s[:i0] + js + s[i0:]
    print('inserted', key)
open(p, 'w', encoding='utf-8').write(s)
