# Oakhaven content studio: the complete guide

This is how every Oakhaven post is made: the daily Reel, its caption and roll-call comment, the survivor spotlight, and the camera-roll photo posts. Follow it step by step. Every step here exists because skipping it once produced a wrong or ugly result.

You are making content for **Sam** (Instagram **@surviveoakhaven**, site **surviveoakhaven.com**). Sam posts everything himself. Your job ends when the finished files are in his hands (sent in chat **and** copied to his computer's `Downloads`).

---

## 0. The quality bar (read this first)

A finished daily Reel looks like this (Day 8, "The Horde", 2:10):

1. **Cold open, 5 s.** The episode's single most dramatic moment, with a found-footage overlay (blinking REC dot, `REC DAY 07 · 21:52`, hazard tape) and three short hook lines in big type, the last one amber. The narrator says the hook line over it.
2. **Title card**: `OAKHAVEN` / `DAY 8`, narrator says "Oakhaven. Day eight."
3. **The recap**, told by the camera *in the real game world*: the camera flies to where things happened, follows named survivors in close-up when the narrator names them, and every on-screen caption appears on the exact word the narrator says it.
4. **Status**: survivors, food/water days, next threat.
5. **A tease** (a mystery, a voice on the radio).
6. **Vote card** with the real options from `data.json`, then the **end card**: one question + "COMMENT YOUR NAME + JOB TO MOVE IN".

Narration is one deep gravelly voice (ElevenLabs "Atlas"), mixed over a faint room-tone bed at -17.5 LUFS. Video is 1080x1920, 30 fps, H.264, about 100 MB for 2 minutes.

The worst failures so far, all of which this guide prevents:
- Saying things the game didn't do (a different vote winner, an invented injury, a find that isn't in the stockpile). **Every fact comes from `report.md` / `data.json`, or from Sam's notes, and Sam's notes get written into `data.json` too** (section 4).
- Two numbers that contradict each other (e.g. "97 of them" and "600 didn't get up": one was the horde's *strength*, the other the city's *undead count change*). Use one number per idea.
- Captions that wrap badly (`THE VOTE: POLICE 4 · DINER 1` broke into two lines with a lone "1"). Keep each caption to one line of about 22 characters, or two balanced lines.
- Scenes too dark to read. Night scenes use hour 19.0 to 19.4, not midnight.
- Rendering from a different take than the one you aligned, or editing the script after generating the voice.
- Real faces in the photo posts. Never: survivors are always seen from behind, hooded, masked or cropped.

---

## 1. Ground rules

- **Never `git push`.** Every change reaches GitHub through the GitHub **web editor** or **upload page**, in the browser (section 11). Afterwards `git fetch && git reset --hard origin/main` so your clone matches GitHub, and delete `work/`, `__pycache__/`. The repo must be clean when you finish.
- **Never create accounts, enter passwords or API keys, or buy anything.** Sam is already signed in to ElevenLabs, Gemini and GitHub in his browser.
- **ElevenLabs credits are limited** (each generation costs about 1 credit per character; check the remaining number before you generate). Generate **once**, only after Sam approves the script text. Never "try again" to fix a word: fix pronunciation in the alignment instead.
- **Faces**: never show any survivor's face in a photo. Zombies' faces are fine.
- **Sam approves before anything costs credits or goes live**: the script (before ElevenLabs), the photo picks (before stamping). Show drafts early.
- Talk to Sam in plain words. He doesn't need to hear about scripts, commits or tools unless something went wrong.

---

## 2. Setup (every session)

```bash
# the repo (read access is enough; changes go through the web editor)
git clone https://github.com/samfulkerson/oakhaven.git && cd oakhaven
mkdir -p work                         # all scratch files live here, never commit it
python3 -m http.server 8768 >/dev/null 2>&1 &     # the renderer loads the game from here
python3 -c "import playwright, pocketsphinx, PIL" && which ffmpeg     # all should exist
```
If `pocketsphinx` is missing: `pip install pocketsphinx --break-system-packages`.

You also need:
- **A browser tool on Sam's own Chrome** (Claude in Chrome) for ElevenLabs, Gemini and GitHub. Make a new tab for your work and close it when done.
- **The bridge to Sam's computer** (tools named `mcp__remote-devices__*`): browser downloads land in `~/Downloads` on his computer; you copy them into the session with `device_stage_files` (they appear under `/mnt/user-data/uploads/Downloads/`), and put finished files back with `device_commit_files` (pass the `fileUuid` that `SendUserFile` returned; large files only work that way).

Files you'll use, all in this folder:

| File | What it does |
|---|---|
| `align_narration.py` | word + sentence timings of a narration take |
| `episode.py` | builds an `EPISODES` entry timed to the narration |
| `examples/day8.py` | the complete Day 8 Reel as a worked example: copy it each day |
| `insert_episode.py` | puts the entry into `index.html` |
| `render_reel.py` | renders frames (or test stills) from the real game |
| `assemble_reel.py` | frames + narration → finished `.mp4` |
| `contact_sheet.py` | a grid of frames so you can look at your work |
| `spotlight.py` | the spotlight still |
| `github_patch.py` | safe edit snippet for GitHub's web editor |
| `../photos/camera.py` | makes a generated image look like the camp's old digital camera, with date stamp |
| `../photos/bible.json` | how every survivor and place looks in photos |

---

## 3. The daily rhythm

- The game advances itself at **05:07 UTC** (11:07 pm Central) via GitHub Actions: it counts the Instagram votes, runs the day's outing, rolls injuries, handles the horde, adds new survivors, and writes **`report.md`** (the recap) and **`data.json`** (the whole world).
- **The day's content is always built from that run.** Before it lands, you can only prepare (scripts for features, studio code). If Sam asks for the Reel earlier, say so and offer to prepare.
- After `git fetch && git reset --hard origin/main`, read `report.md` top to bottom, then check details in `data.json`:
  - `day`, `followers`, `milestones_hit`, `milestones` (anything newly reached gets a shout-out)
  - `vote` (tomorrow's question and options: these go on the vote card), last night's tally is in `report.md`
  - `missions` (an `"active"` mission keeps its squad inside for several nights)
  - `horde` (`day` = next horde night; `last` = last night's result: `outcome`, `strength`, `defenders`)
  - `stock` (food/water are rations: one per survivor per day; "days left" = amount ÷ living survivors), `survivors` (names, roles, `ig` handles, `status`, `injury`, `gear`)
- `report.md` is written for narration, but it is terse. Translate it, never contradict it.

---

## 4. When Sam gives story notes

Sam often adds beats ("they find a water cooler", "Tanny and Francis split off to the diner", "Seth hears a voice on the radio"). Two jobs, always both:

1. **Put it in the script.**
2. **Make the game agree**, so the site, tomorrow's report and the stockpile match the Reel. Edit `data.json` locally, then push it (section 11). Common edits:

| Beat | data.json change |
|---|---|
| A find (+water, +food...) | add directly to `stock` (`["Water", 18, 200, "rations"]`), **or** queue it for tonight's run with `"camp_bonus": [{"item": "Water", "amt": 6, "why": "Tanny and Francis's diner run", "note": "…"}]` (the note shows in tomorrow's report) |
| Credit a survivor on their card on the site | append to `highlights`: `{"day": 8, "who": "Tanny", "kind": "find", "title": "The diner", "text": "…"}` |
| A place got searched | that run in `runs`: `"done_day": 8, "squad": ["Tanny", "Francis"]` |
| A voice on the site's radio panel | `"broadcast": {"day": 8, "from": "Unknown, picked up by Seth", "text": "...[static]... Fort Corran..."}` |
| A future beat on a given day | `schedule`: `{"on_day": 10, "do": "broadcast", "text": "…"}` (see nightly.py, `run_schedule`) |
| How a multi-night mission ends | on that mission: `"days"`, `"squad"`, `"gain": {"Ammo": 120}`, `"gear": [{"kind": "armor", "name": "Riot vest", "icon": "vest"}, {"kind": "weapon", "name": "Service pistol", "icon": "pistol"}]`, `"recruit": [{"name": "Officer Reyes", "ig": "", "role": "Guard", "bio": "…"}]`, `"done_note": "…"`, `"broadcast": {"from": "…", "text": "…"}` |
| New gear (spotlight) | the survivor's `gear`: `{"kind": "weapon", "name": "Boat hook", "icon": "hook"}` (icons: blade, club, axe, spear, hook, rifle, pistol; armor: `kind: "armor"`). It is drawn on their sprite. |

If a note conflicts with the game (e.g. "run the vote" on a day the game posted no vote because a mission is active), **tell Sam before writing**, explain what the game did, and offer options. Don't silently pick.

If a beat needs new game logic (nightly.py), make it a real, tested change (run `nightly.py` on a copy of the repo in `work/` with `count_vote` patched, as many nights as needed, and read the report it writes) before pushing.

---

## 5. Writing the script

**Structure** (Day 8 as the model, 300 words ≈ 2:00; a normal day is 150–200 words ≈ 1:10–1:30):

1. **Hook line** (first sentence the narrator says, plays over the cold open): two short sentences, under 5 seconds, a tension or a number, not the outcome. *"Ninety-seven of them hit the fence last night. Thirteen of us were behind it."*
2. **"Oakhaven. Day N."**
3. **The big event** of the night/day, in short concrete sentences. Name survivors with what they carry: *"Jaylozy's fire axe. Seth's maul."*
4. **The vote result** and the outing: who went, what happened, injuries with how long they're out, what was found.
5. **Side beats** (Sam's notes, small runs worth telling).
6. **Milestone / new survivors** ("One more at the gate. Elder. A mechanic.").
7. **Status**: "Seventeen survivors. Food for two days. Water for one." + the next threat.
8. **Tease** (radio, a mystery).
9. **Vote**: name the options in plain words. **End**: one question to drive comments + "Comment your name and your job, to move in."

**Voice**: first person plural ("us", "we"), past tense, flat and tired, no exclamation marks, no hype words, numbers written out as words in the TTS text ("Ninety-seven", "Day ten"). Short sentences; every sentence ends with `.` or `?` (the timing tools split on them).

**Check every fact** against `report.md`/`data.json` and your section 4 edits before showing Sam. Then show Sam the script **with the on-screen captions** in this format:

```
**THE HORDE** (night, replay at the fence)
> They came after dark. Blades through the chain link.
On screen: `DAY 7 · 21:40 · THE HORDE` → `13 ON THE FENCE`
```

Revise until he says go. Changes after the voice is generated cost a full regeneration.

---

## 6. The narration (ElevenLabs)

1. Make the TTS text: the approved script as plain sentences, **no** stage directions, **no** `...` (pauses are made later in the edit, and dots cost credits), numbers as words. Save it as `work/script.txt`. Count characters (`wc -c`); it must be less than the remaining credits.
2. Browser: `https://elevenlabs.io/app/speech-synthesis/text-to-speech`. Dismiss any upgrade popup ("Remind Me Later").
3. Check the settings panel: **Voice: Atlas - Deep, Gravelly Narrator**, **Model: Eleven v4**, Stability about the middle (50), Similarity about 75%. Don't touch "Auto-tag".
4. Replace the text. The editor is a TipTap/ProseMirror box that keeps old text if you just type; replace it exactly with JavaScript:
   ```js
   const ed=document.querySelector('.tiptap.ProseMirror').editor;
   const node=ed.state.doc.firstChild; const tr=ed.state.tr;
   tr.insertText(`PASTE THE SCRIPT HERE`, 1, 1+node.content.size); ed.view.dispatch(tr);
   ed.getText().length      // must equal your character count
   ```
   Check the counter under the box says the same number.
5. Click **Generate speech** once. It produces **two** generations (cards "Generation 1" / "Generation 2"). Pause playback. Click the **download icon on each card** (not the player bar). Files land in Sam's `~/Downloads` as `ElevenLabs_<date>_Atlas - Deep, Gravelly Narrator_pvc_s50_sim75_v4.mp3` and `... (1).mp3`.
6. `device_stage_files` both, copy into `work/` as `take1.mp3`, `take2.mp3`.
7. Align both and compare (section 7). Pick the one whose sentence table looks natural (no sentence absurdly long or squeezed). If they're equal, take 1.

---

## 7. Timing: align, then build the episode

```bash
python3 studio/align_narration.py work/take1.mp3 work/script.txt work/align.json
```
It prints every sentence with its number and start/end in the take. If it stops with "Add pronunciations", add the names to `PRON` in `align_narration.py` (ARPAbet, copy the pattern of the others) and run again. Every new survivor name needs an entry.

Then copy the example and edit it:
```bash
cp studio/examples/day8.py work/day9.py      # then edit it: key 'day9', segments, cam, hour, events, captions, title, hook
python3 work/day9.py
python3 studio/insert_episode.py work/day9.js
```
Always run these from the repo root.

### 7a. Segments: placing the narration

You group sentences into **segments** and say when each starts in **episode time** (the episode starts after the cold open):
```python
ep.hook(0, 1, at=0.3)            # hook line, 0.3 s into the cold open
ep.segment('A', 2, 3, at=1.0)    # "Oakhaven. Day eight." with the title card (always at 1.0)
ep.segment('B', 4, 5, at=5.4)    # starts later than the take would: 2 s of silent footage first
```
Inside a segment the narrator's own pacing is kept. Gaps between segments are silence you design: give big moments room (2–3 s of silent fight, a beat before a reveal). `ep.s(i)` / `ep.e(i)` then give the episode time when sentence `i` starts/ends; use them for every caption and camera key so nothing drifts.

The episode's `dur` = end of the last sentence + about 3 s.

### 7b. The episode format (`EPISODES.dayN` in index.html)

```js
dayN: {
  title: 'Day 8 · The Horde', dur: 124.6, audioOffset: 1.0,
  hook: { from: 28.3, tag: 'DAY 07 · 21:52', lines: ['97 OF THEM.', 'ONE FENCE.', '13 OF US.'] },
  cam: [[t, x, y, width] | [t, 'follow', 'Name', width], ...],
  hour: [[t, hourOfDay], ...],
  events: [[t, 'type', ...args], ...],
  captions: [[t0, t1, 'kind', ...], ...]
}
```

**Camera** (`cam`): keys in time order. Between two keys the camera eases; two keys 0.1–0.2 s apart make a cut. `width` is how many world pixels fill the 1080-px-wide frame: 100–130 = close-up on a person, 150–250 = a building and its yard, 300–450 = a few blocks, 700–1300 = the whole city. `follow` tracks a survivor (they must be visible). Hold each shot at least 1.5 s; push in slowly during a shot (e.g. width 120 → 112) so it never feels frozen.

**Hour** (`hour`): the in-game hour, interpolated. It can go past 24 to reach the next morning (30 = 6 am). Darkness: full day 7–17.5, darkening to night by 20.5. **For readable night scenes use 19.0–19.4.** A dusk-to-night cut: two keys 1–1.5 s apart (e.g. 38 → 49.5).

**Who's on screen**: at t=0 everyone is inside the laundromat. In daylight they wander out into the yard on their own; at night they go in. Use events to put people where the story needs them, and `away` to hide anyone who is out on a mission.

**Events**:

| Event | Effect |
|---|---|
| `[t, 'away', [names]]` | hide them (out on a mission, not in camp) |
| `[t, 'settle', [names]]` | back inside the laundromat |
| `[t, 'stand', [names]]` | visible, wandering in the yard |
| `[t, 'walk', 'Name', [[x,y], [x,y], ...]]` | appears at the first point and walks the path (about 12 world px per second) |
| `[t, 'run', 'Name', 'poiKey']` | leaves the camp door and walks the real route to a place |
| `[t, 'arrive', [names], 'poiKey']` | walks the last stretch home from a place, in a little column |
| `[t, 'defend', [[name, x, y], [name, x, y, 1], ...]]` | stands them still at a spot; with `1` they have a gun. During a horde they fight whatever is in reach (guns at range, others through the fence). Also used to place someone alone (on the roof lookout: 441, 457) |
| `[t, 'horde', n, [[x,y], [x,y]], 'e'|'s'|'w', seconds]` | n zombies come in a strung-out column along the route and spread along that side of the fence |
| `[t, 'clearHorde']` | everything left at the fence falls (use during a sunrise transition) |
| `[t, 'brute', [x,y], [tx,ty]]` + `[t, 'hit', 'Name']` | a scripted dock brute walks to a spot; each `hit` is a sure blow from that survivor (needs 3) |
| `[t, 'preview', true]` | the planned route of the next run, drawn on the map |

Zombies already in the world fight anyone walking outside the fence by themselves. Survivors kill them.

**Captions**:

| Kind | Looks like | Args |
|---|---|---|
| `title` | huge amber word + subtitle | `'OAKHAVEN', 'DAY 8'` (only at 1.0–3.3) |
| `capTop` | white caption, upper part | `'TEXT'` |
| `cap` | white caption, lower part | `'TEXT'` |
| `vote` | the vote card (question + 3 option boxes, "COMMENT YOUR PICK") | `'QUESTION?', ['GAS', 'GUN SHOP', 'MAPLE']` |
| `card` | end card (dark, line, handle, OAKHAVEN) | `'QUESTION?', 'COMMENT YOUR NAME + JOB TO MOVE IN'` |

Rules: start a caption on the word (`s(i)`), end it at the end of that thought (`e(i) + .2`), never overlap two captions of the same kind, uppercase, about 22 characters per line max. Put captions on the half of the frame the action isn't in (`capTop` when the action is low, `cap` when it's high). Use `·` to join two facts: `ELDER · MECHANIC`. Vote card options are exactly the `vote.opts` labels in `data.json`.

**Hook** (`hook`): `from` = the episode second where the cold-open footage starts. Pick the most violent/dramatic, readable shot (a wide fight with muzzle flashes, a brute in a doorway). The narrator's hook line lasts `hook_seconds` (printed by `episode.py`); the footage from `from` to `from + hook_seconds` is reused. `tag` is the camera's timestamp text. `lines`: 3 lines, each 2–3 words, last line the twist.

### 7c. Map reference (world pixels, 1600 x 1200)

- **Laundromat (home)**: building box 400–448 x 456–492, door (424, 492). **Fence** x 390–458, y 452–514. Yard ≈ (396–452, 496–510). Gate/south path (424, 514) → street at y 552. Lookout platform on the roof ≈ (441, 457).
- **Streets**: horizontal y = 192, 312, 432, 552, 672, 784, 912, 1040; vertical x = 216, 352, 488, 624, 760, 1280. The camp's block is x 360–480, y 440–544 (north street y 432, south y 552, east x 488, west x 352).
- **Places** (key: centre-ish / door): pharmacy (409, 370) door (409, 392) · diner (554, 358) door (554, 380), street entry (554, 432) · gas station (584, 468) door (584, 484) · market (554, 583) door (554, 600) · hardware (270, 583) door (264, 600) · gun shop (685, 371) door (685, 392) · Pier 9 port (826, 349) door (826, 378) · ranger station (98, 401) door (98, 418) · hospital (560, 237) door (560, 268) · **police** (276, 471) door (276, 494) · airport terminal (490, 136) · cargo ship (934, 530) · fire station (282, 824) · Maple Court (592, 950) door (592, 964) · farm (115, 1104) · mall (624, 1098) · harbor master (812, 469) · cold storage (816, 623) · hunter's cabin (140, 859) · Fort Corran (1450, 230) door (1310, 240) · Blackrock prison (1070, 380) · army checkpoint (1244, 276) · army surplus (1246, 345) · fairground (1330, 678) · KOAK radio tower (1525, 975). Full list: `const POIS` in index.html.
- Walking into a place from the camp: south through the gate to y 552, along the street, then up/down to the door, e.g. police: `[[372, 552], [276, 552], [276, 498]]`.

---

## 8. Test stills before the full render

The full render is long; a mistake found afterwards costs the whole render. Always:
```bash
python3 studio/render_reel.py day9 work/stills --stills 4,9,14,20,26,30,35,40,52,66,80,95,110,120
python3 studio/contact_sheet.py work/stills work/stills_sheet.jpg
```
Open `work/stills_sheet.jpg` with Read and check **every** panel:
- the subject is in frame and big enough (if you can't tell who/what it is at phone size, push in);
- people are where the story says (the squad isn't in the yard while "inside the police station"; nobody walks through walls);
- captions: right text at the right moment, no ugly wraps, not covering the action;
- night is readable; daylight where it should be;
- the vote card shows the real options.
Fix and repeat until it's right. Each test pass simulates from t=0, so stills match the final render.

---

## 9. Render, assemble, check

```bash
python3 studio/render_reel.py day9 work/render --hook <hook_seconds printed by episode.py>     # run it in the background, ~6 frames/s
python3 studio/assemble_reel.py work/render work/take1.mp3 work/day9_segments.json work/oakhaven-day9.mp4
python3 studio/contact_sheet.py work/oakhaven-day9.mp4 work/final.jpg 0.5,3,6.5,12,20,30,40,50,60,70,80,90,100,110,120
ffmpeg -i work/oakhaven-day9.mp4 -af ebur128 -f null - 2>&1 | grep -A1 "Integrated loudness"
```
Check: the first frame is the cold open with the hook text; `OAKHAVEN DAY 9` appears right when the narrator says it (≈ hook_seconds + 1 s); the last frames are the end card; loudness about -17 to -18 LUFS; size well under 200 MB (re-encode with `-crf 23` if not).

**The renderer's world is random** (zombie positions differ every run): anything that has to happen at a certain moment must be an event, not luck.

---

## 10. Deliver

Make a folder `/mnt/user-data/outputs/dayN/` with:

**`oakhaven-dayN.mp4`**

**`caption.txt`** (Instagram caption, in this shape):
```
🧟 Day 8: The horde hit the fence.
97 of them. 13 of us. The fence held. Sixty percent of it, anyway.

🚓 You voted POLICE, 4–1. Carl, Quinn, Javier and Asa cut the chains. … +10 water. Two more nights inside, and whoever chained those doors is still in there.
🍳 Tanny and Francis … +6 water.
⛽ 50 followers: the gas station pumps are running. +2 fuel every night.
🔧 New at the gate: Elder, mechanic (@themortimer)
📻 Last night Seth caught a voice on the radio. A woman. "…Fort Corran…" Then nothing.

🗳️ While the squad's inside, where does a small group go? Comment ⛽ GAS, 🔫 GUN SHOP or 🏘 MAPLE
Who do you think is on that radio? 👇
Comment your name + job to move in.

#zombie #zombieapocalypse #survival #interactivestory #pixelart
```
Rules: one emoji-led line per beat, the vote options with their emoji exactly as in `data.json` `vote.opts[i][4]`, new survivors tagged with their `@handle`, the next milestone if it's close ("2 more followers and…"), the join line, 4–5 hashtags.

**`rollcall_comment.txt`** (Sam posts it as the first comment and pins it):
```
Roll call, Day 7 🧟‍♂️
🎯 @jaemos16 Jaylozy, sharpshooter (Pulaski fire axe)
🥩 @sir.tanny Tanny, scout (revolver)
…every living survivor with an ig handle: emoji for their role, @handle, name, role, (gear · injury, out until Day N) …
IF INSTAGRAM BLOCKS THE TAGS, post these as separate comments:
@a @b @c @d
@e @f @g @h
```
(Up to about 4 tags per line in the fallback; Instagram limits mentions per comment.)

Then: `SendUserFile` all files to Sam, and `device_commit_files` them into his `~/Downloads` (`oakhaven-dayN.mp4`, `oakhaven-dayN-caption.txt`, `oakhaven-dayN-rollcall.txt`). Tell him in two or three sentences what's in it, anything he must know (e.g. ElevenLabs credits left), and stop.

Also push the new episode in `index.html` (section 11) so it's in the site's studio, and any `data.json` story edits.

---

## 11. Pushing to GitHub (web editor only)

**Edit an existing text file** (index.html, data.json, nightly.py, scrapbook/scrapbook.json):
```bash
git fetch && python3 studio/github_patch.py index.html work/patch.js
```
1. Browser: open `https://github.com/samfulkerson/oakhaven/edit/main/index.html`.
2. Run the contents of `work/patch.js` with the javascript tool. It must return `OK`. (`OLD MISMATCH`: GitHub has changed since your fetch; re-fetch, redo your edit on the new version, regenerate. Never commit after a mismatch.)
3. Commit with JavaScript (one call):
   ```js
   [...document.querySelectorAll('button')].find(x=>/Commit changes/.test(x.textContent)).click();
   await new Promise(r=>setTimeout(r,1000));
   const i=document.querySelector('#commit-message-input');
   Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(i,'Day 9 episode'); i.dispatchEvent(new Event('input',{bubbles:true}));
   const d=document.querySelector('dialog[open], [role=dialog]');
   [...d.querySelectorAll('button')].find(x=>/^\s*Commit changes\s*$/.test(x.textContent)).click(); 'ok'
   ```
4. Verify: `git fetch && git diff origin/main -- index.html` shows nothing (GitHub sometimes adds a final newline to data.json; that's fine). Then `git reset --hard origin/main`.

Don't edit `data.json` around 05:00–05:30 UTC (the nightly run writes it).

**Add new files** (photos, thumbnails): copy them under `/mnt/user-data/uploads/...` (the upload tool only takes files from there), open `https://github.com/samfulkerson/oakhaven/upload/main/<folder>`, use `find` to get the hidden file input ("Choose your files"), `file_upload` the files (≤ 10 MB per call), wait until every file name shows, set `input[name="message"]` like above, click the "Commit changes" button. Verify with `git fetch && git ls-tree origin/main <folder>/`.

---

## 12. The survivor spotlight (daily, with the Reel)

One survivor, one real change in the game (new weapon or armor, a build, a find), one picture, one short caption.
1. Make the change in `data.json` (gear on the survivor, or a `features`/`highlights` entry) and push it.
2. `python3 studio/spotlight.py work/spot.jpg "JEREMY MADE A BAYONET SPEAR" --who Jeremy` (adjust `--x --y --w` so the survivor and the gear fill the frame; look at it).
3. Caption:
```
Survivor spotlight: Jeremy 🎯
Pier 9 cost us 6 of our last 8 rounds. Jeremy doesn't like not being able to shoot.
So he pulled a bayonet out of a crate at the pier, lashed it to a mop handle with fence wire, and now he holds the fence without firing a shot.
New gear: 🗡️ Bayonet spear (+2 horde defense). You can see it on him on the live map.
@intrepid11
🗳️ Today's vote is on the Day 5 Reel: 🔫 GUN SHOP 🧱 FORTIFY 💧 WINDMILL 🌽 HARVEST
#zombie #pixelart #zombieapocalypse #survival #interactivestory
```

---

## 13. Camera-roll photo posts

Francis found a cheap digital camera on Day 6; since then one survivor "shoots" each big mission. A roll is 5–7 photos telling the mission in order, plus a caption, and it goes into the site's scrapbook.

**Plan the roll first** and show Sam the list: who holds the camera (someone on the mission who isn't in the photos much; an injured survivor watching is great), and each shot: time, who, what, angle. Shots alternate wide/close; end on a quiet aftermath or "walking home" shot.

**Generate** in Gemini (free, Sam's account): `https://gemini.google.com/app`, one chat for the whole roll so it stays consistent.
- Each prompt: start with `Generate an image, portrait 4:5.` (first) or `Next photo in the same roll, same camera, same night, portrait 4:5.`, then the camera look, then the scene, then the rules. The camera look (from `photos/bible.json` `style`): *A candid snapshot taken on a cheap mid-2000s compact digital camera (7-megapixel point-and-shoot, small CCD sensor). Harsh direct on-camera flash at night with hard flash shadows and fast falloff into black (or: no flash, high ISO, heavy grain, underexposed); flat overcast late-autumn daylight by day. Slightly blown highlights, noisy shadows, slightly soft focus, imperfect amateur framing. Photorealistic, unglamorous, not cinematic, no color grading.*
- Survivors: describe them **only** by outfit + carried item from `bible.json` `characters`, and always say **"seen strictly from behind, faces never visible"**, plus "work gloves". If a survivor isn't in the bible yet, invent a simple distinctive outfit and add it to the bible (push it) so they look the same next time.
- Zombies: *gray-green mottled skin, cloudy faces, torn dirty clothes; their eyes glow a dim red, small red points of light clearly visible in the dark, subtle, not neon* (Sam wants the red eyes like the live game). *Creepy, not gory, no heavy blood.*
- Places: use the place's description in `bible.json` `places` (the laundromat is a one-story red-brick building with a blue LAUNDROMAT sign, plywood windows, sandbags, a chain-link fence around a dirt yard with a burn barrel, a blue tarp, lawn chairs; on its flat roof a wooden lookout tower and a garden box). Things the photographer stands on must be part of that place (the lookout tower is ON the laundromat's roof).
- End every prompt with `No text, no watermark, no date stamp, no borders.`
- Send with Enter, wait ~30 s.
- **Download full size**: get the newest image's position with JS (`[...document.querySelectorAll('img')].filter(i=>i.naturalWidth>300)`, last one, `scrollIntoView`, read its rect), **click it** to open the viewer, click the viewer's **download icon (top right)**, then the viewer's **back arrow (top left)**. Don't click the top-left corner when the viewer isn't open (that's the Gemini logo: it opens a new chat). Files land in `~/Downloads` as `Gemini_Generated_Image_*.jpeg` (928x1152); stage them.
- **Fix one thing in an image**: upload it back (`find` the hidden image file input, `file_upload` the staged file) and say "Edit this photo. Keep everything exactly the same (…), and change only one thing: …". Use this for red eyes, a wrong prop, an extra building.
- Look at every image yourself (contact sheet) for: any visible face, wrong outfit/prop, things that contradict the story (a bandage before the injury happened, lettering on clothes, a building that shouldn't be there). Then **show Sam a labeled sheet and let him pick**; do his fixes.

**Finish**:
```bash
python3 photos/camera.py work/raw3.jpg out/3.jpg --day 7 --time 21:51 [--flash] --seed 83
```
(`--flash` for flash shots; different `--seed` per photo.) Make `sheet.jpg` of the roll.

Caption:
```
📷 Camera roll, Day 7: horde night
Sam couldn't swing an axe with cracked ribs, so he took the camera up the lookout tower.
1. 21:38. From the tower. They came down the street in one long line.
2. 21:44. Jaylozy's fire axe and Seth's maul, right through the chain link.
…
📸 @surviveoakhaven
@handles of everyone in the photos
🗳️ Today's vote is on the Day 8 Reel: ⛽ GAS 🔫 GUN SHOP 🏘 MAPLE
#zombie #zombieapocalypse #survival #interactivestory #foundfootage
```

**Scrapbook** (the site's page of every roll):
1. Copy the 7 finished photos as `scrapbook/<id>-<n>.jpg` (1080x1350) and 432x540 thumbnails as `scrapbook/thumbs/<id>-<n>.jpg` (`id` like `day7-horde`), under `/mnt/user-data/uploads/`, and upload each folder (section 11).
2. Add the roll to `scrapbook/scrapbook.json` as the **first** item of `rolls`, in the same style as the others (one photo object per line): `id, day, place, by, crew, intro, outro, photos: [{time, who?, note}]`. A photo without `who` counts the whole crew. Push it with the web editor.

Deliver the photos + caption to Sam (send + `~/Downloads/oakhaven-camera-roll/<id>/`).

---

## 14. Before you say "done"

- [ ] Every fact in the Reel/caption matches `report.md`/`data.json` (and Sam's notes are in `data.json`).
- [ ] You looked at the stills sheet and the final contact sheet, panel by panel.
- [ ] The video starts on the cold open, the title lands on "Oakhaven. Day N.", captions land on their words.
- [ ] Vote card and caption options = `data.json` `vote.opts`.
- [ ] No faces in any photo.
- [ ] Files sent and copied to Sam's Downloads.
- [ ] index.html / data.json / scrapbook pushed via the web editor and verified; local clone reset; `work/` deleted; server stopped (`pkill -f "http.server 8768"`).
