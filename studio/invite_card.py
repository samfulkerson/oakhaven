"""An invite card for one survivor: their own sprite in the middle of the street, the dead closing in, and what a friend gets for joining.

  python3 studio/invite_card.py "Jaylozy" OUT.jpg            (1080x1350, Instagram 4:5; the local server must be running)
  python3 studio/invite_card.py all OUTDIR                   (one card for every living survivor with an Instagram handle)

The sprite, gear and colours come straight from the live game, so the card always matches the map.
The perk wording is in PERKS below: keep it in step with what nightly.py really gives.
"""
import asyncio, base64, json, os, re, sys
from playwright.async_api import async_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
PERKS = [["DOUBLE RATIONS", "You both arrive with a full pack: +6 food and +6 water."],
         ["BATTLE BUDDIES", "On the same run you cover each other: fewer injuries for both."]]
JS = r"""
(async ([NAME, PERKS]) => {
  const d = DATA.survivors.find(s => s.name === NAME); if (!d) return null;
  const e = people.find(p => p.d && p.d.name === NAME);
  const Wc = 1080, Hc = 1350, c = document.createElement('canvas'); c.width = Wc; c.height = Hc; const x = c.getContext('2d'); x.imageSmoothingEnabled = false;
  const F1 = '"Chakra Petch", sans-serif', AMB = '#f2a93b', INK = '#f3f4f0';
  // the street: the crossroads south-east of the laundromat, at night
  const S = 9, sw = Wc / S, sh = Hc / S, sx = 488 - sw / 2, sy = 552 - sh / 2 - 8;
  x.drawImage(BG, sx, sy, sw, sh, 0, 0, Wc, Hc);
  x.fillStyle = 'rgba(8,10,26,.66)'; x.fillRect(0, 0, Wc, Hc);
  const cx = 540, cy = 700;
  let g = x.createRadialGradient(cx, cy - 60, 30, cx, cy - 60, 430); g.addColorStop(0, 'rgba(255,214,150,.42)'); g.addColorStop(.45, 'rgba(255,190,110,.14)'); g.addColorStop(1, 'rgba(255,190,110,0)');
  x.globalCompositeOperation = 'lighter'; x.fillStyle = g; x.fillRect(0, 0, Wc, Hc); x.globalCompositeOperation = 'source-over';
  const put = (img, fx, fy, sc, flip, alpha = 1) => { x.save(); x.globalAlpha = alpha; x.translate(Math.round(fx), Math.round(fy)); if (flip) x.scale(-1, 1); x.drawImage(img, -Math.floor(img.width * sc / 2), -img.height * sc + sc, img.width * sc, img.height * sc); x.restore(); };
  // the dead, in a ring, all facing in. Further ones are dimmer; every one has the red eyes
  const zs = [];
  const R = n => { let h = strHash(NAME + ':' + n); return (h >>> 0) / 4294967296; };
  for (let i = 0; i < 22; i++) { const an = i / 22 * Math.PI * 2 + R(i) * .22, rr = 300 + R(i + 50) * 230; zs.push([cx + Math.cos(an) * rr * 1.0, cy - 40 + Math.sin(an) * rr * .78, i]); }
  zs.sort((a, b) => a[1] - b[1]);
  for (const [zx, zy, i] of zs) {
    if (zy > cy - 150 && zy < cy + 60 && Math.abs(zx - cx) < 150) continue;
    if (zy > cy + 40 && Math.abs(zx - cx) < 250) continue;                     // keep the name plate clear
    const runner = i % 7 === 3, brute = i === 1, sc = brute ? 16 : S, look = runner ? { zombie: 1, ztype: 'runner' } : brute ? { zombie: 1, ztype: 'brute' } : lookFor('inv' + NAME + i, null, true);
    const img = sprite(look, i % 2 ? 'w0' : 'w1'), flip = zx > cx, far = Math.hypot(zx - cx, zy - cy) / 560;
    x.fillStyle = 'rgba(0,0,0,.35)'; x.fillRect(zx - 4 * sc, zy + sc, 8 * sc, sc);
    put(img, zx, zy, sc, flip, 1 - far * .35);
    const fxs = flip ? -1 : 1, ey = zy - 8 * sc, ex = brute ? [-2.5, 1.5] : runner ? [-2.5 * fxs - .5, -.5 * fxs - .5] : [-fxs - .5, fxs - .5];
    x.fillStyle = '#ff3b2a'; for (const o of ex) x.fillRect(Math.round(zx + o * sc), Math.round(ey), sc, sc);
    x.globalCompositeOperation = 'lighter'; const eg = x.createRadialGradient(zx, ey, 0, zx, ey, sc * 5); eg.addColorStop(0, 'rgba(255,50,30,.38)'); eg.addColorStop(1, 'rgba(255,50,30,0)'); x.fillStyle = eg; x.fillRect(zx - sc * 5, ey - sc * 5, sc * 10, sc * 10); x.globalCompositeOperation = 'source-over';
  }
  // the survivor, twice the size of everything else
  const HS = 20, hero = sprite(e ? e.look : lookFor(d.ig || d.name, d.role), 'stand');
  x.fillStyle = 'rgba(0,0,0,.45)'; x.beginPath(); x.ellipse(cx, cy + HS, HS * 5, HS * 1.2, 0, 0, 7); x.fill();
  put(hero, cx, cy, HS, false);
  // vignette, tape, type
  g = x.createLinearGradient(0, 0, 0, 330); g.addColorStop(0, 'rgba(6,7,12,.94)'); g.addColorStop(1, 'rgba(6,7,12,0)'); x.fillStyle = g; x.fillRect(0, 0, Wc, 330);
  for (let X = -40; X < Wc; X += 40) { x.fillStyle = AMB; x.beginPath(); x.moveTo(X, 0); x.lineTo(X + 20, 0); x.lineTo(X + 32, 12); x.lineTo(X + 12, 12); x.fill(); }
  const T = (s, X, Y, px, col, w = 700, al = 'center', ls = 0) => { x.font = `${w} ${px}px ${F1}`; x.textAlign = al; x.textBaseline = 'alphabetic'; x.fillStyle = col; try { x.letterSpacing = ls + 'px'; } catch (er) {} x.fillText(s, X, Y); };
  const wrap = (s, px, w, max) => { x.font = `${w} ${px}px ${F1}`; const out = []; let cur = ''; for (const wd of s.split(' ')) { const t = cur ? cur + ' ' + wd : wd; if (x.measureText(t).width > max && cur) { out.push(cur); cur = wd; } else cur = t; } if (cur) out.push(cur); return out; };
  x.shadowColor = 'rgba(0,0,0,.8)'; x.shadowBlur = 14;
  T('OAK', 540 - 6, 84, 46, INK, 700, 'right', 5); T('HAVEN', 540 - 2, 84, 46, AMB, 700, 'left', 5);
  const head = (NAME.split(' ')[0] + ' NEEDS BACKUP.').toUpperCase(); let hp = 92; x.font = `700 ${hp}px ${F1}`; while (x.measureText(head).width > 980 && hp > 50) { hp -= 4; x.font = `700 ${hp}px ${F1}`; }
  T(head, 540, 186, hp, INK, 700);
  T(d.ig ? `@${d.ig} is surrounded. Move in and stand with them.` : 'Surrounded. Move in and stand with them.', 540, 236, 31, '#d8dcd6', 600);
  x.shadowBlur = 0;
  // name plate under the survivor
  const plate = `${NAME.toUpperCase()}  ·  ${String(d.role || 'Survivor').toUpperCase()}`; x.font = `700 30px ${F1}`; const pw = x.measureText(plate).width + 44;
  x.fillStyle = 'rgba(10,11,14,.86)'; x.fillRect(540 - pw / 2, cy + 46, pw, 50); x.fillStyle = AMB; x.fillRect(540 - pw / 2, cy + 46, 5, 50); T(plate, 540 + 2, cy + 82, 30, INK, 700);
  // the offer
  const py = 940; g = x.createLinearGradient(0, py - 110, 0, py); g.addColorStop(0, 'rgba(6,7,12,0)'); g.addColorStop(1, 'rgba(6,7,12,.95)'); x.fillStyle = g; x.fillRect(0, py - 110, Wc, 110);
  x.fillStyle = 'rgba(6,7,12,.95)'; x.fillRect(0, py, Wc, Hc - py); x.fillStyle = AMB; x.fillRect(56, py + 6, 968, 3);
  T('JOIN WITH A FRIEND', 56, py + 66, 50, AMB, 700, 'left', 2);
  let y = py + 124;
  PERKS.forEach(([t, s], i) => {
    x.fillStyle = AMB; x.fillRect(56, y - 30, 40, 40); x.fillStyle = '#0b0c10'; x.font = `700 28px ${F1}`; x.textAlign = 'center'; x.fillText(i ? '+' : '×2', 76, y);
    T(t, 116, y - 4, 32, INK, 700, 'left', 1);
    for (const ln of wrap(s, 27, 500, 900)) { y += 34; T(ln, 116, y, 27, '#b9c2c6', 500, 'left'); }
    y += 62;
  });
  x.fillStyle = 'rgba(242,169,59,.14)'; x.fillRect(56, Hc - 108, 968, 68); x.strokeStyle = 'rgba(242,169,59,.6)'; x.setLineDash([8, 6]); x.strokeRect(56.5, Hc - 107.5, 967, 67); x.setLineDash([]);
  const how = `Follow @${String(DATA.handle || 'surviveoakhaven').replace(/^@/, '')}  ·  comment your name + job + “with ${d.ig ? '@' + d.ig : NAME}”`; let wp = 28; x.font = `600 ${wp}px ${F1}`; while (x.measureText(how).width > 930 && wp > 18) { wp -= 1; x.font = `600 ${wp}px ${F1}`; }
  T(how, 540, Hc - 64, wp, INK, 600);
  return c.toDataURL('image/jpeg', .93);
})
"""


async def main():
    who, out = sys.argv[1], sys.argv[2]
    async with async_playwright() as p:
        kw = {'executable_path': '/usr/bin/google-chrome'} if os.path.exists('/usr/bin/google-chrome') else {}
        b = await p.chromium.launch(args=['--use-gl=swiftshader'], **kw)
        pg = await b.new_page()
        await pg.goto('http://localhost:8768/index.html')
        css = ''.join("@font-face{font-family:'Chakra Petch';font-weight:%d;src:url(data:font/woff2;base64,%s) format('woff2')}"
                      % (w, base64.b64encode(open(f'{HERE}/fonts/chakra-petch-latin-{w}-normal.woff2', 'rb').read()).decode()) for w in (600, 700))
        await pg.add_style_tag(content=css); await pg.wait_for_timeout(2500)
        await pg.evaluate("Promise.all([document.fonts.load('700 60px \"Chakra Petch\"'), document.fonts.load('600 60px \"Chakra Petch\"')])")
        names = [who]
        if who == 'all':
            os.makedirs(out, exist_ok=True)
            names = await pg.evaluate("DATA.survivors.filter(s => s.status !== 'dead' && s.ig && (s.joined || 1) <= DATA.day).map(s => s.name)")
        for n in names:
            url = await pg.evaluate(f"({JS})({json.dumps([n, PERKS])})")
            if not url: print('no survivor called', n); continue
            path = os.path.join(out, 'invite-' + re.sub(r'[^a-z0-9]+', '-', n.lower()).strip('-') + '.jpg') if who == 'all' else out
            open(path, 'wb').write(base64.b64decode(url.split(',')[1])); print('wrote', path)
        await b.close()

asyncio.run(main())
