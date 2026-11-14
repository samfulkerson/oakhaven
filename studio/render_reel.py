"""Render an Oakhaven episode (EPISODES.<key> in index.html) frame by frame, plus its cold-open (hook) frames, from ONE simulation.

  python3 studio/render_reel.py EPISODE OUTDIR [--hook SECONDS] [--url URL] [--stills t1,t2,...] [--inject file.js]

  OUTDIR/main/f00000.jpg ...  every frame of the episode at 30 fps (1080x1920)
  OUTDIR/hook/h00000.jpg ...  SECONDS*30 frames of the cold open: the episode's footage from hook.from, with the hook overlay

  --stills 4,12.5,30   test mode: only save these moments (as OUTDIR/still_004.00.jpg ...) and stop after the last one.
                       The world still runs from t=0, so the stills look exactly like the full render will.
  --inject file.js     run extra JS in the page before preparing (used for one-off spotlight scenes, see README).
  --url                default http://localhost:8768/index.html (start it with: cd <repo> && python3 -m http.server 8768)

Needs Python playwright (pre-installed) and the Chakra Petch fonts in studio/fonts/. A 2-minute episode takes about 11 minutes.
"""
import argparse, asyncio, base64, os, shutil, sys, time
from playwright.async_api import async_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
FPS = 30
ap = argparse.ArgumentParser()
ap.add_argument('episode'); ap.add_argument('outdir')
ap.add_argument('--hook', type=float, default=0.0); ap.add_argument('--url', default='http://localhost:8768/index.html')
ap.add_argument('--stills', default=''); ap.add_argument('--inject', default='')
a = ap.parse_args()
STILLS = sorted(float(x) for x in a.stills.split(',') if x.strip())


async def main():
    os.makedirs(a.outdir, exist_ok=True)
    if not STILLS:
        for d in ('main', 'hook'):
            shutil.rmtree(os.path.join(a.outdir, d), ignore_errors=True); os.makedirs(os.path.join(a.outdir, d))
    args = ['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist']
    async with async_playwright() as p:
        kw = {'executable_path': '/usr/bin/google-chrome'} if os.path.exists('/usr/bin/google-chrome') else {}
        b = await p.chromium.launch(args=args, **kw)
        pg = await b.new_page(viewport={'width': 1080, 'height': 1920}, device_scale_factor=1)
        errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
        await pg.goto(a.url)
        css = ''.join("@font-face{font-family:'Chakra Petch';font-weight:%d;src:url(data:font/woff2;base64,%s) format('woff2')}"
                      % (w, base64.b64encode(open(f'{HERE}/fonts/chakra-petch-latin-{w}-normal.woff2', 'rb').read()).decode()) for w in (600, 700))
        await pg.add_style_tag(content=css); await pg.wait_for_timeout(3000)
        await pg.evaluate("Promise.all([document.fonts.load('700 60px \"Chakra Petch\"'), document.fonts.load('600 60px \"Chakra Petch\"')])")
        if a.inject:
            await pg.evaluate(open(a.inject).read())
        dur = await pg.evaluate(f"""(() => {{
          const sc = document.querySelector('.screen'); sc.classList.add('studio', 'export'); document.getElementById('studioBar').hidden = true;
          window.__vt = performance.now(); performance.now = () => window.__vt;   // the page's clock only moves when we step it
          fit(); return oakEpisode.prepare('{a.episode}'); }})()""")
        hk = await pg.evaluate("oakEpisode.hook()")
        print('episode', a.episode, 'dur', dur, 'hook', hk, 'errors', errs, flush=True)
        if errs: sys.exit('page errors: fix index.html first')
        hframes, hn, t0 = int(round(a.hook * FPS)), 0, time.time()
        todo = list(STILLS)
        for n in range(int(round(dur * FPS))):
            t = n / FPS
            main, hookimg = await pg.evaluate(f"(() => {{ window.__vt += {1000 / FPS}; return oakEpisode.frames2({t}, {a.hook if hk else 0}); }})()")
            if STILLS:
                if todo and t + 1e-6 >= todo[0]:
                    open(os.path.join(a.outdir, f'still_{todo[0]:06.2f}.jpg'), 'wb').write(base64.b64decode(main.split(',')[1])); todo.pop(0)
                if not todo: break
                continue
            open(os.path.join(a.outdir, 'main', f'f{n:05d}.jpg'), 'wb').write(base64.b64decode(main.split(',')[1]))
            if hookimg and hn < hframes:
                open(os.path.join(a.outdir, 'hook', f'h{hn:05d}.jpg'), 'wb').write(base64.b64decode(hookimg.split(',')[1])); hn += 1
            if n % 300 == 0: print(f'frame {n} / {int(dur * FPS)}  {time.time() - t0:.0f}s', flush=True)
        print('done. hook frames', hn, 'of', hframes, '| page errors', errs, flush=True)
        await b.close()

asyncio.run(main())
