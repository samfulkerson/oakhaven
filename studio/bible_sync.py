"""A starter camera-roll profile for every survivor who doesn't have one in photos/bible.json yet.

  python3 studio/bible_sync.py need       (no browser: exit 0 if anyone is missing a profile, 1 if not)
  python3 studio/bible_sync.py missing    (write the missing profiles; the local server must be running)

The profile is read off the survivor's own sprite in the live game (skin, hair, jacket, trousers, what the role wears and
carries, any weapon they've been given), so the photos match the map from the first day. The nightly workflow runs this
for everyone who joins. Entries it writes are marked "auto": true. Edit them as much as you like: a name that is already
in bible.json is never touched again.
"""
import asyncio, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BIBLE = os.path.join(HERE, '..', 'photos', 'bible.json')
DATA = os.path.join(HERE, '..', 'data.json')
NAMED = {  # the game's palettes (SKIN, HAIR, JACKET, PANTS in index.html), in words
    'skin': {'#f1c9a5': 'fair skin', '#d9a679': 'light tan skin', '#b97f55': 'medium-brown skin', '#8d5a3b': 'brown skin', '#5e3b27': 'dark brown skin'},
    'hair': {'#2a1d14': 'dark brown hair', '#5a3a22': 'brown hair', '#141210': 'black hair', '#a8743a': 'sandy blonde hair', '#7d7d7d': 'gray hair', '#7a3a22': 'auburn hair', '#d9b45a': 'blonde hair', '#3b2416': 'dark brown hair'},
    'jacket': {'#5b6b3a': 'olive-green jacket', '#6e4a33': 'brown work jacket', '#3f5466': 'slate-blue jacket', '#7a3b33': 'brick-red jacket', '#55525a': 'charcoal-gray jacket', '#8a7a4a': 'khaki-tan jacket', '#3d4a3c': 'dark green jacket', '#6a5a7a': 'dusty purple jacket'},
    'pants': {'#2f3540': 'navy pants', '#3a3328': 'dark brown pants', '#47402f': 'khaki-brown pants', '#2b2b2b': 'black jeans', '#3b3f2c': 'olive cargo pants'},
}
# what the role adds to the sprite: [headwear or None, jacket override or None, what they carry, how the face stays hidden]
ROLE = {
    'Scavenger': [None, None, 'a worn brown backpack', 'from behind, the backpack filling the frame'],
    'Radio Operator': [None, None, 'a backpack radio with a tall whip antenna (red tip), a headset around the neck', 'angle and crop, the headset strap crossing the face'],
    'Scout': ['an olive hood, always up', 'olive-green field jacket', 'binoculars on a strap', 'hood up, from the side or behind'],
    'Sharpshooter': [None, None, 'a scoped rifle slung on the back', 'from behind or over the shoulder'],
    'Guard': [None, None, 'a long wooden club', 'from behind, shoulders squared to the fence'],
    'Gunsmith': [None, None, 'a hammer in hand, a leather apron', 'head down over the work, or from behind'],
    'Mechanic': ['a faded blue cap', None, 'a big adjustable wrench', 'cap brim low, often bent over an engine'],
    'Medic': [None, 'off-white medic jacket with a red cross on the chest', 'a red first-aid bag', 'a surgical mask, or head down over a patient'],
    'Farmer': ['a wide straw hat', None, 'a garden trowel and a seed pouch', 'hat brim low, bent over the plants'],
    'Builder': ['a yellow hard hat', None, 'a claw hammer in a tool belt', 'hard hat tipped forward, or from behind'],
    'Cook': ["a white cook's cap", None, 'a ladle and a dented stock pot', 'head down over the pot, steam in front of the face'],
    'Chef': ["a white chef's hat", 'off-white chef jacket', 'a ladle and a dented stock pot', 'head down over the pot, steam in front of the face'],
    'Engineer': ['safety goggles pushed up on the forehead', None, 'a canvas tool roll', 'goggles down, or from behind'],
}
ROLE['EMT'] = ROLE['Medic']


def nearest(kind, hx):
    t = NAMED[kind]
    if hx in t: return t[hx]
    rgb = lambda h: [int(h[i:i + 2], 16) for i in (1, 3, 5)]
    return t[min(t, key=lambda k: sum((a - b) ** 2 for a, b in zip(rgb(k), rgb(hx))))]


def todo():
    d, b = json.load(open(DATA, encoding='utf-8')), json.load(open(BIBLE, encoding='utf-8'))
    return [s for s in d['survivors'] if s.get('status') != 'dead' and s.get('joined', 1) <= d['day'] and s['name'] not in b['characters']]


def entry(s, look):
    head, jacket, carry, face = ROLE.get(s.get('role'), [None, None, 'a canvas shoulder bag', 'from behind or in shadow'])
    hair = nearest('hair', look['hair']) + (', tied up in a bun' if look.get('bun') else ', worn long' if look.get('long') else '')
    weapon = next((g['name'] for g in s.get('gear', []) if g.get('kind') == 'weapon'), None)
    outfit = [jacket or nearest('jacket', look['jacket']), nearest('pants', look['pants'])] + ([head] if head else []) + ['work gloves']
    return {'role': s.get('role', 'Survivor'), 'skin': nearest('skin', look['skin']), 'hair': hair + (f', under {head}' if head else ''),
            'outfit': ', '.join(outfit), 'signature': carry + (f', and the {weapon[0].lower() + weapon[1:]} they were given' if weapon else ''), 'face': face, 'auto': True}


async def main():
    mode = sys.argv[1]
    need = todo(); print('no profile yet:', [s['name'] for s in need])
    if mode == 'need': sys.exit(0 if need else 1)
    if not need: return
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        kw = {'executable_path': '/usr/bin/google-chrome'} if os.path.exists('/usr/bin/google-chrome') else {}
        b = await p.chromium.launch(args=['--use-gl=swiftshader'], **kw)
        pg = await b.new_page(); await pg.goto('http://localhost:8768/index.html'); await pg.wait_for_timeout(2500)
        looks = await pg.evaluate("names => Object.fromEntries(DATA.survivors.filter(d => names.includes(d.name)).map(d => [d.name, { ...lookFor(d.ig || d.name, d.role), ...(d.look || {}) }]))", [s['name'] for s in need])
        await b.close()
    raw = open(BIBLE, encoding='utf-8').read(); bible = json.loads(raw)
    for s in need:
        if s['name'] in looks: bible['characters'][s['name']] = entry(s, looks[s['name']]); print('wrote', s['name'], bible['characters'][s['name']])
    json.dump(bible, open(BIBLE, 'w', encoding='utf-8'), indent=1 if raw.startswith('{\n "') else 2, ensure_ascii=False); open(BIBLE, 'a').write('\n')

asyncio.run(main())
