"""Contact sheet of a video or a folder of frames, so you can SEE what you made before sending it.

  python3 studio/contact_sheet.py VIDEO.mp4 OUT.jpg 0.5,3,8,20,40,...      (frames at those seconds)
  python3 studio/contact_sheet.py DIR OUT.jpg                               (every *.jpg in DIR, e.g. stills)
Then open OUT.jpg with the Read tool and look at every panel.
"""
import glob, os, subprocess, sys, tempfile
from PIL import Image, ImageDraw

src, out = sys.argv[1], sys.argv[2]
ims = []
if os.path.isdir(src):
    for f in sorted(glob.glob(os.path.join(src, '*.jpg'))): ims.append((os.path.basename(f), Image.open(f)))
else:
    tmp = tempfile.mkdtemp()
    for t in [float(x) for x in sys.argv[3].split(',')]:
        p = os.path.join(tmp, f'{t:07.2f}.jpg')
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-ss', str(t), '-i', src, '-frames:v', '1', p], check=True)
        ims.append((f'{t:.1f}s', Image.open(p)))
W = 270; cols = min(8, len(ims)); rows = (len(ims) + cols - 1) // cols
H = int(W * ims[0][1].height / ims[0][1].width)
sheet = Image.new('RGB', (cols * W, rows * (H + 22)), (15, 15, 15)); d = ImageDraw.Draw(sheet)
for i, (label, im) in enumerate(ims):
    x, y = (i % cols) * W, (i // cols) * (H + 22)
    sheet.paste(im.resize((W, H)), (x, y + 22)); d.text((x + 6, y + 5), label, fill=(242, 169, 59))
sheet.save(out, quality=88); print('wrote', out, len(ims), 'panels')
