"""The daily survivor spotlight picture: one close-up still from the live game with a headline, 1080x1350 (Instagram 4:5).

  python3 studio/spotlight.py OUT.jpg "JEREMY MADE A BAYONET SPEAR" --who Jeremy [--x 428 --y 500 --w 62 --hour 13]

x, y = the world point to centre on (the yard is around 424, 500; see the map table in README), w = how many world pixels
wide the shot is (50-70 is a tight close-up of the yard). Make the gear/feature change in data.json FIRST (locally), so the
survivor is drawn holding it, then run this with the local server up. --who stands that survivor still near x, y, apart
from the crowd. Look at the result; move x/y/w until the person and the gear are clearly in frame.
"""
import argparse, json, os, subprocess, sys, tempfile
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument('out'); ap.add_argument('headline')
ap.add_argument('--x', type=float, default=428); ap.add_argument('--y', type=float, default=500); ap.add_argument('--w', type=float, default=62)
ap.add_argument('--hour', type=float, default=13); ap.add_argument('--who', default='')
a = ap.parse_args()
d = tempfile.mkdtemp()
inj = os.path.join(d, 'spot.js')
open(inj, 'w').write("EPISODES.spot = { title: 'spot', dur: 4, audioOffset: 0, cam: [[0, %s, %s, %s], [4, %s, %s, %s]], hour: [[0, %s], [4, %s]], events: %s, "
                     "captions: [[0, 4, 'capTop', %s]] };" % (a.x, a.y, a.w, a.x, a.y, a.w, a.hour, a.hour, json.dumps([[0, 'defend', [[a.who, a.x, a.y + 4]]]] if a.who else []), json.dumps(a.headline.upper())))
subprocess.run([sys.executable, os.path.join(HERE, 'render_reel.py'), 'spot', d, '--stills', '2', '--inject', inj], check=True)
im = Image.open(os.path.join(d, 'still_002.00.jpg'))
top = 250                                                   # keeps the headline (drawn at 17% of the height) inside the 4:5 crop
im.crop((0, top, 1080, top + 1350)).save(a.out, quality=92)
print('wrote', a.out)
