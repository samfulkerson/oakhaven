"""Oakhaven nightly update.

Runs once a night (GitHub Actions does it for you) and moves the world forward exactly one day:
  1. counts the vote on the newest Reel (one vote per account, their latest comment counts)
  2. sends out today's run or mission and rolls for injuries and deaths
  3. heals survivors whose injuries are over
  4. adds new survivors from join comments (Claude reads them), up to a daily cap
  5. updates the follower count, advances the day, and writes data.json plus report.md (a recap to narrate from)
  5b. keeps the stockpile: everyone eats and drinks, runs bring loot home, ammo gets spent, the fence wears down
  6. moves the power project along: runs bring back fuel and parts, new arrivals bring skills, generators come back on
  7. sets tomorrow's vote: picks three places the squad could go and has Claude word the question

Secrets it reads from the environment (set them in GitHub under Settings > Secrets and variables > Actions):
  IG_TOKEN               Instagram access token from "API setup with Instagram login"  (optional: skipped if missing)
  ANTHROPIC_API_KEY      for reading join comments                                         (optional: skipped if missing)
Options:
  DRY_RUN=1              print what would happen, change nothing
"""
import os, re, json, random, time
from datetime import datetime, timezone
from collections import Counter

# ---------------------------------------------------------------- settings you might want to change
DATA_FILE = "data.json"
REPORT_FILE = "report.md"
IG_ACCOUNT_ID = os.environ.get("IG_USER_ID") or "17841422748770654"   # @surviveoakhaven's Instagram account ID, shown on the Meta app page
MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-5-5")
MAX_NEW_PER_DAY = 25          # pacing: at most this many new survivors move in per day; the rest wait in line
ROLES = ["Scavenger", "Medic", "Scout", "Sharpshooter", "Farmer", "Builder", "Radio Operator", "Mechanic", "Guard", "Cook", "Engineer"]

# chance of an injury / a death for each person on an outing, by difficulty
RISK = {"easy": (0.06, 0.005), "medium": (0.12, 0.02), "hard": (0.20, 0.05), "deadly": (0.30, 0.12)}
SQUAD_SIZE = {"easy": 1, "medium": 3, "hard": 4, "deadly": 6}
INJURY_DAYS = {"easy": (2, 3), "medium": (2, 4), "hard": (3, 5), "deadly": (4, 6)}
MISSION_DAYS = {"easy": 2, "medium": 3, "hard": 5, "deadly": 7}   # missions take several nights of work
INJURIES = ["a twisted ankle", "a deep cut from broken glass", "cracked ribs", "a bad fall", "a concussion", "burned hands", "a dislocated shoulder"]
DEATHS = ["Pulled down by the horde at the {p}.", "Bitten covering the squad's retreat from the {p}.",
          "Went back for a dropped bag at the {p} and never came out.", "Cornered in the dark at the {p}.",
          "Held the door at the {p} so the others could get out."]

DRY = os.environ.get("DRY_RUN") == "1"


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- Instagram
def ig_base():
    """Instagram-login tokens (they start with IG) talk to graph.instagram.com; business tokens (EAA...) talk to graph.facebook.com."""
    if os.environ.get("IG_GRAPH"):
        return os.environ["IG_GRAPH"].rstrip("/")
    return "https://graph.instagram.com/v25.0" if os.environ["IG_TOKEN"].strip().startswith("IG") else "https://graph.facebook.com/v25.0"


def ig_get(url, **params):
    import requests
    params["access_token"] = os.environ["IG_TOKEN"].strip()
    r = requests.get(url, params=params, timeout=30)
    if r.status_code != 200:   # show Meta's own explanation, never the token
        try:
            err = r.json().get("error", {})
        except ValueError:
            err = {}
        raise RuntimeError(f"Instagram API error {r.status_code} on {url.split('?')[0]}: {err.get('message', 'no message')} (type {err.get('type')}, code {err.get('code')})")
    return r.json()


def fetch_instagram(since=None):
    """Follower count, the day's vote Reel, and every comment left since the last run on ANY recent post.
    Extra posts (a story video, a spotlight) don't hide the vote: people comment wherever they like.
    Returns None if no Instagram credentials are set."""
    if not os.environ.get("IG_TOKEN"):
        log("No IG_TOKEN set: skipping Instagram (no vote count, no new survivors).")
        return None
    GRAPH = ig_base()
    uid = "me" if "graph.instagram.com" in GRAPH else IG_ACCOUNT_ID
    log(f"Instagram API: {GRAPH.split('//')[1]} as {uid}")
    followers = ig_get(f"{GRAPH}/{uid}", fields="followers_count")["followers_count"]
    media = ig_get(f"{GRAPH}/{uid}/media", fields="id,caption,media_type,media_product_type,permalink,timestamp", limit=15)["data"]
    if not media:
        log("No posts yet.")
        return {"followers": followers, "reel": None, "comments": []}
    since = since or time.time() - 36 * 3600
    stamp = lambda t: datetime.strptime(t[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    recent = [m for m in media if stamp(m["timestamp"]) > time.time() - 72 * 3600] or media[:1]
    # the vote Reel: the newest recent post that asks for a pick; otherwise just the newest Reel
    reels = [m for m in media if m.get("media_product_type") == "REELS" or m.get("media_type") in ("VIDEO", "REELS")]
    reel = next((m for m in recent if "comment your pick" in (m.get("caption") or "").lower()), reels[0] if reels else media[0])
    comments = []
    for m in recent:
        url, params = f"{GRAPH}/{m['id']}/comments", {"fields": "username,text,timestamp", "limit": 50}
        while url:
            page = ig_get(url, **params)
            comments += [c for c in page.get("data", []) if c.get("username") and stamp(c.get("timestamp", "1970-01-01T00:00:00")) > since]
            url, params = page.get("paging", {}).get("next"), {}
    comments.sort(key=lambda c: c.get("timestamp", ""))
    log(f"Instagram: {followers} followers, {len(comments)} comments on {len(recent)} recent post(s); vote Reel {reel['permalink']}")
    return {"followers": followers, "reel": reel, "comments": comments}


# ---------------------------------------------------------------- 1. the vote
def count_vote(data, comments):
    vote = data.get("vote") or {}
    options = [o[0].upper() for o in vote.get("opts", [])]
    if not options:
        return None, {}
    # each option can also be voted with its emoji (💊 for PHARMACY); variation selectors are ignored so ✈ and ✈️ both count
    plain = lambda t: t.replace("\ufe0f", "")
    emojis = {}
    for o in vote["opts"]:
        e = o[4] if len(o) > 4 and o[4] else EMOJI.get(o[3] if len(o) > 3 else o[0].lower()) or EMOJI.get(o[0].lower())
        if e:
            emojis[o[0].upper()] = plain(e)
    ballots = {}
    owner = str(data.get("handle", "")).lstrip("@").lower()
    for c in comments:
        if c["username"].lower() == owner:                 # your own replies on the Reel don't count as votes
            continue
        text = " " + re.sub(r"[^A-Z0-9 ]", " ", c.get("text", "").upper()) + " "
        pick = next((o for o in options if re.search(rf"(?<![A-Z]){re.escape(o)}(?![A-Z])", text)), None) \
            or next((o for o in options if o in emojis and emojis[o] in plain(c.get("text", ""))), None)
        if pick:
            ballots[c["username"].lower()] = pick          # later comments overwrite earlier ones
    tally = Counter(ballots.values())
    for o in vote["opts"]:
        o[1] = tally.get(o[0].upper(), 0)
    top = tally.most_common()
    winner = top[0][0] if top and (len(top) == 1 or top[0][1] > top[1][1]) else None   # a tie means no winner
    return winner, dict(tally)


# ---------------------------------------------------------------- 2. today's outing, injuries and deaths
def find_target(data, word):
    """Match a vote word like HOSPITAL to a run or mission."""
    if not word:
        return None
    w = word.lower()
    for m in data.get("missions", []):
        if m.get("status") == "done":
            continue
        name = (m.get("poi") or m.get("name") or "").lower()
        if w == name or w in name.split():
            return ("mission", m)
    for r in data.get("runs", []):
        if w == r["dest"].lower() or w in r["dest"].lower():
            return ("run", r)
    return None


def place_name(kind, item):
    if kind == "mission":
        return item.get("name") or item.get("poi", "mission").replace("_", " ").title()
    return item.get("place") or item["dest"].replace("_", " ").title()


def pick_squad(data, kind, item, rng):
    living = [s for s in data["survivors"] if s.get("status") not in ("dead", "injured", "away") and s.get("joined", 1) <= data["day"]]
    by_name = {s["name"]: s for s in living}
    squad = [by_name[n] for n in item.get("squad", []) if n in by_name]
    want = SQUAD_SIZE.get(item.get("difficulty", "medium"), 2)
    if kind == "run" and item.get("squad") == ["Sam"] and len(living) == 1:
        want = 1
    rest = [s for s in living if s not in squad]
    rng.shuffle(rest)
    rest.sort(key=lambda s: s.get("outings", 0))          # spread the work: people who've been out least go first
    roles_have = {s["role"] for s in squad}
    for need in ("Medic", "Sharpshooter"):                 # on hard and deadly outings, try to bring a medic and a shooter
        if item.get("difficulty") in ("hard", "deadly") and need not in roles_have:
            pro = next((s for s in rest if s["role"] == need), None)
            if pro and len(squad) < want:
                squad.append(pro); rest.remove(pro); roles_have.add(need)
    while len(squad) < want and rest:
        squad.append(rest.pop(0))
    return squad


def has_gear(s, kind):
    return any(g.get("kind") == kind for g in s.get("gear", []))


def gear_odds(s, die, inj):
    """Gear found in the daily spotlight posts: armor takes the edge off injuries and deaths, a melee weapon helps a little."""
    if has_gear(s, "armor"):
        die *= .6; inj *= .6
    if has_gear(s, "weapon"):
        die *= .85; inj *= .9
    return die, inj


def resolve_outing(data, kind, item, rng):
    first = not item.get("done_day")
    diff = item.get("difficulty", "medium")
    place = place_name(kind, item)
    squad = pick_squad(data, kind, item, rng)
    if not squad:
        return {"target": place, "key": item.get("dest") or item.get("poi"), "first": first, "kind": kind, "difficulty": diff, "squad": [], "results": [], "note": "Nobody was fit to go."}
    roles = {s["role"] for s in squad}
    inj, die = RISK.get(diff, RISK["medium"])
    if "Medic" in roles:
        die *= 0.5; inj *= 0.85
    if "Sharpshooter" in roles:
        die *= 0.75; inj *= 0.75
    if stock_get(data, "Ammo") < AMMO_USE.get(diff, 6):       # out of bullets: everything is more dangerous
        die *= 1.5; inj *= 1.4
    if data.get("hungry_days", 0) > 0:                        # weak from hunger
        inj *= 1.3
    results = []
    for s in squad:
        s["outings"] = s.get("outings", 0) + 1
        roll = rng.random()
        die_s, inj_s = gear_odds(s, die, inj)
        if roll < die_s and not s.get("protected"):
            s.update(status="dead", died_day=data["day"], died_at=place, cause=rng.choice(DEATHS).format(p=place))
            results.append({"name": s["name"], "ig": s.get("ig", ""), "outcome": "dead", "detail": s["cause"]})
        elif roll < die_s + inj_s:       # an injury; a protected character (Sam) who rolls death gets the worst injury instead
            lo, hi = INJURY_DAYS.get(diff, (2, 4))
            days = rng.randint(lo, hi) + (2 if roll < die_s else 0)
            s.update(status="injured", injury=rng.choice(INJURIES), injured_until=data["day"] + days)
            results.append({"name": s["name"], "ig": s.get("ig", ""), "outcome": "injured", "detail": f"{s['injury']}, out until Day {s['injured_until']}"})
        else:
            results.append({"name": s["name"], "ig": s.get("ig", ""), "outcome": "ok"})
    # progress
    if kind == "run":
        item["done_day"] = data["day"]
        item["squad"] = [s["name"] for s in squad if s.get("status") != "dead"] or item.get("squad", [])
    else:
        item["days"] = item.get("days") or MISSION_DAYS.get(diff, 3)
        item["days_done"] = item.get("days_done", 0) + 1
        item["status"] = "done" if item["days_done"] >= item["days"] else "active"
    return {"target": place, "key": item.get("dest") or item.get("poi"), "first": first, "kind": kind, "difficulty": diff, "squad": [s["name"] for s in squad], "results": results,
            "mission_status": item.get("status") if kind == "mission" else None}


def todays_outing(data, winner, rng):
    # 1) anything planned by hand in data.json "outings"; 2) an active multi-day mission; 3) the vote winner; 4) the next run
    planned = data.pop("outings", None) or []
    targets = []
    for o in planned:
        t = find_target(data, o.get("target", ""))
        if t:
            if o.get("squad"):
                t[1]["squad"] = o["squad"]
            targets.append(t)
    if not targets:
        active = next((m for m in data.get("missions", []) if m.get("status") == "active"), None)
        if active:
            targets.append(("mission", active))
    if not targets:
        t = find_target(data, winner)
        if t:
            targets.append(t)
    if not targets and data.get("runs"):
        runs = data["runs"]
        fresh = [r for r in runs if not r.get("done_day")]
        nxt = fresh[0] if fresh else min(runs, key=lambda r: r.get("done_day", 0))
        targets.append(("run", nxt))
    return [resolve_outing(data, k, it, rng) for k, it in targets]


# ---------------------------------------------------------------- 3. healing
def heal(data, new_day):
    healed = []
    for s in data["survivors"]:
        if s.get("status") == "injured" and s.get("injured_until", 0) <= new_day:
            for k in ("status", "injury", "injured_until"):
                s.pop(k, None)
            healed.append(s["name"])
    return healed


# ---------------------------------------------------------------- 3b. story beats planned ahead
# data.json "schedule" holds beats that fire on a given day, e.g.
#   {"on_day": 4, "do": "scout", "who": "Tanny", "role": "Scout", "until": 5, "note": "...", "back": "...", "talk": ["..."]}
#   {"on_day": 5, "do": "horde_warning", "horde_day": 7, "note": "..."}
#   {"on_day": 4, "do": "broadcast", "text": "..."}            (a message on the radio for the site to show)
def run_schedule(data, new_day, rng):
    news, keep = [], []
    for ev in data.get("schedule", []):
        if ev.get("on_day", 0) > new_day:
            keep.append(ev)
            continue
        do = ev.get("do")
        if ev.get("broadcast"):
            data["broadcast"] = {"day": new_day, "from": ev.get("from", "Unknown"), "text": ev["broadcast"]}
        if do == "broadcast":
            data["broadcast"] = {"day": new_day, "from": ev.get("from", "Unknown"), "text": ev.get("text", "")}
        elif do == "scout":
            fit = [s for s in data["survivors"] if s.get("status") not in ("dead", "injured", "away") and s.get("joined", 1) <= new_day]
            s = next((s for s in fit if s["name"] == ev.get("who")), None) \
                or next((s for s in fit if s.get("role") == ev.get("role", "Scout") and not s.get("protected")), None) \
                or next((s for s in sorted(fit, key=lambda s: s.get("outings", 0)) if not s.get("protected")), None)
            if not s:
                news.append("Nobody was fit to go scouting.")
                continue
            s.update(status="away", away_until=ev.get("until", new_day + 1), away_note=ev.get("note", "Out scouting"),
                     away_back=ev.get("back", ""), away_talk=ev.get("talk", []))
            news.append(f"{s['name']} left alone: {s['away_note']}. Back Day {s['away_until']}.")
        elif do == "unlock":                         # new kinds of dead join the map: runners, dock brutes, soldiers...
            have = data.setdefault("zombie_types", ["walker"])
            have += [z for z in ev.get("zombies", []) if z not in have]
            if ev.get("note"):
                news.append(ev["note"])
        elif do == "ballot":
            data["ballot"] = {"day": new_day, "keys": ev.get("keys", [])}
            if ev.get("note"):
                news.append(ev["note"])
        elif do == "horde_warning":
            if not data.get("horde"):
                data["horde"] = {"day": ev.get("horde_day", new_day + 2), "week": 1}
            news.append(ev.get("note") or f"A horde is coming. It reaches Oakhaven on Day {data['horde']['day']}.")
    data["schedule"] = keep
    return news


def scout_trips(data, new_day, rng, outings):
    """A side trip planned in data.json "schedule" ({"do": "trip", ...}): a few random people who weren't on today's run
    walk out somewhere, bring a little back, and report what's still there. Goes in before the stockpile is counted."""
    busy = {n for o in outings for n in o.get("squad", [])}
    news, keep = [], []
    for ev in data.get("schedule", []):
        if ev.get("do") != "trip" or ev.get("on_day", 0) > new_day:
            keep.append(ev)
            continue
        fit = [s for s in data["survivors"] if s.get("status") not in ("dead", "injured", "away") and s.get("joined", 1) <= data["day"]
               and not s.get("protected") and s["name"] not in busy and s["name"] not in ev.get("exclude", [])]
        crew = rng.sample(fit, min(ev.get("count", 2), len(fit)))
        if not crew:
            news.append(f"Nobody was free to go to {ev.get('place', 'scout')}.")
            continue
        names = " and ".join(s["name"] for s in crew)
        got = {}
        for item, (lo, hi) in (ev.get("gain") or {}).items():
            got[item] = rng.randint(lo, hi)
            data.setdefault("camp_bonus", []).append({"item": item, "amt": got[item], "why": ev.get("why", "scouts")})
        for s in crew:
            s["outings"] = s.get("outings", 0) + 1
        what = " and ".join(f"+{v} {UNITS.get(k, k.lower())}" for k, v in got.items()) or "nothing"
        news.append(f"{names} {ev.get('went', 'went scouting')} and came back with {what}.")
        for r in data.get("runs", []):            # the place now counts as visited, so small runs can go there
            if ev.get("dest") and r["dest"] == ev["dest"]:
                r.setdefault("scouted", new_day - 1)
        news += [r.replace("{crew}", names).replace("{a}", crew[0]["name"]).replace("{b}", crew[-1]["name"]) for r in ev.get("report", [])]
    data["schedule"] = keep
    return news


def come_home(data, new_day):
    back = []
    for s in data["survivors"]:
        if s.get("status") == "away" and s.get("away_until", 0) <= new_day:
            back.append(f"{s['name']} made it back. {s.get('away_back', '')}".strip())
            for k in ("status", "away_until", "away_note", "away_back", "away_talk"):
                s.pop(k, None)
    return back


# ---------------------------------------------------------------- 3c. horde nights
# Once a week the dead come all at once. The fence, the ammo and the people standing at the wire decide how it goes.
def horde_night(data, rng, day):
    h = data.get("horde")
    if not h or h.get("day") != day:
        return None
    home = [s for s in data["survivors"] if s.get("status") not in ("dead", "away") and s.get("joined", 1) <= day]
    fit = [s for s in home if s.get("status") != "injured"]
    roles = Counter(s.get("role") for s in fit)
    lit = any(g.get("status") == "running" and not g.get("dry") for g in data.get("power", []))
    strength = 70 + 15 * (h.get("week", 1) - 1) + min(data.get("followers") or 0, 80) * 0.5 + rng.uniform(-10, 10)
    if lit:
        strength *= 1.15                                  # the light draws them in
    fence, ammo = stock_get(data, "Barricades"), stock_get(data, "Ammo")
    defense = fence * .5 + min(ammo, 60) * .5 + len(fit) * 6 + roles["Sharpshooter"] * 8 + roles["Builder"] * 5 \
        + sum(2 for s in fit if has_gear(s, "weapon")) + sum(1 for s in fit if has_gear(s, "armor")) \
        + sum(f.get("defense", 0) for f in data.get("features", []))
    margin = round(defense - strength)
    def hurt(n, why):
        pool = [s for s in fit if s.get("status") != "injured"]
        rng.shuffle(pool)
        out = []
        for s in pool[:n]:
            s.update(status="injured", injury=why, injured_until=day + 1 + rng.randint(2, 3))
            out.append(f"{s['name']} ({why}, out until Day {s['injured_until']})")
        return out
    def spend(name, amt):
        r = stock_row(data, name)
        if r:
            r[1] = max(0, r[1] - amt)
    hurt_list, dead = [], []
    if margin >= 15:
        outcome, fence_hit, ammo_hit = "held", 15, 20
    elif margin >= 0:
        outcome, fence_hit, ammo_hit = "barely held", 25, 30
        if rng.random() < .5:
            hurt_list = hurt(1, "clawed at the fence")
    elif margin >= -20:
        outcome, fence_hit, ammo_hit = "breached", 40, 35
        hurt_list = hurt(rng.randint(1, 2), "bitten back from the breach")
    else:
        outcome, fence_hit, ammo_hit = "overrun", fence - 20, 40
        victims = [s for s in fit if not s.get("protected")]
        if len(home) > 2 and victims:                      # never wipes out the camp
            s = rng.choice(victims)
            s.update(status="dead", died_day=day, died_at="the laundromat fence", cause="Pulled over the fence when the horde broke through.")
            dead.append(s["name"])
        hurt_list = hurt(2, "hurt holding the laundromat")
    spend("Barricades", max(0, fence_hit)); spend("Ammo", ammo_hit)
    if stock_get(data, "Barricades") < 10:
        stock_row(data, "Barricades")[1] = 10
    res = {"day": day, "week": h.get("week", 1), "outcome": outcome, "strength": round(strength), "defense": round(defense),
           "defenders": [s["name"] for s in fit], "hurt": hurt_list, "dead": dead, "lit": lit,
           "fence": stock_get(data, "Barricades"), "ammo": stock_get(data, "Ammo")}
    h["last"] = res
    h["day"], h["week"] = day + 7, h.get("week", 1) + 1
    return res


# ---------------------------------------------------------------- 3d. small scavenging runs during the day
# Each night plans tomorrow's small runs: who goes, where, when, and what they find. The site plays them at those times
# (the same for every viewer), and the next night adds the finds to the stockpile. Small on purpose: about a quarter
# of a day's food and water at most, so the vote still matters. Mostly safe: some scares, a rare one-day injury, never
# a death, and no injuries the day of a horde night or the day before.
FINDS = {"pharmacy": ["Medicine", "Water", "Food"], "diner": ["Food", "Water", "Food"], "gas": ["Water", "Scrap", "Food"],
         "market": ["Food", "Water", "Food"], "hardware": ["Scrap", "Scrap", "Water"], "gunshop": ["Ammo", "Ammo", "Scrap"],
         "maple": ["Food", "Water", "Ammo"], "storage": ["Scrap", "Ammo", "Food"], "harbor": ["Water", "Food", "Scrap"],
         "port": ["Food", "Scrap", "Food"], "farm": ["Food", "Water", "Food"]}
DEFAULT_FINDS = ["Food", "Water", "Scrap"]
DAY_CAP = {"Food": 3, "Water": 3, "Ammo": 8, "Scrap": 4, "Medicine": 1}
FIND_AMT = {"Food": (1, 2), "Water": (1, 2), "Ammo": (2, 5), "Scrap": (1, 3), "Medicine": (1, 1)}
FIND_LINES = {"Food": ["{n} cans of soup behind the counter", "{n} boxes of crackers nobody wanted", "{n} jars of peanut butter in a back room"],
              "Water": ["{n} jugs of water under a sink", "{n} cases of bottled water in a stockroom", "{n} containers of rainwater worth boiling"],
              "Ammo": ["{n} rounds in a glovebox", "{n} rounds rolling around a drawer", "a box with {n} rounds left in it"],
              "Scrap": ["{n} loads of sheet metal and wire", "{n} armfuls of planks and bolts", "{n} car doors for the fence"],
              "Medicine": ["a bottle of painkillers", "a first-aid kit, half full", "a dose of antibiotics in a cabinet"]}
UNITS = {"Food": "food", "Water": "water", "Ammo": "rounds", "Scrap": "scrap", "Medicine": "medicine"}
SCARES = ["One came out of the freezer aisle. We're fine. Heading back.", "Had to hide in a stairwell for ten minutes. They moved on.",
          "Something knocked over a shelf in the back. We didn't wait to see what.", "Three of them at the door when we came out. Went out the back."]
HURTS = ["a sprained ankle", "a cut hand", "a twisted knee", "a pulled shoulder"]
DAY_TIMES = ["08:40", "10:15", "11:50", "13:30", "15:05"]


def plan_day_runs(data, new_day, rng):
    fit = [s for s in data["survivors"] if s.get("status") not in ("dead", "injured", "away") and s.get("joined", 1) <= new_day]
    # only places the story has already been: a voted mission (done_day) or survivors in a daily post (scouted)
    places = [r["dest"] for r in data.get("runs", []) if r.get("done_day") or r.get("scouted")]
    if not fit or not places:
        data.pop("day_runs", None)
        return
    h = data.get("horde") or {}
    safe = h.get("day") is not None and 0 <= h["day"] - new_day <= 1          # no injuries right before a horde night
    n = max(1, min(3, len(fit) // 4))          # a few small runs a day, not a constant stream
    pool = sorted(fit, key=lambda s: (s.get("day_outings", 0), rng.random()))
    used = {k: 0 for k in DAY_CAP}
    runs = []
    for i, t in enumerate(sorted(rng.sample(DAY_TIMES, n))):
        crew = [pool.pop(0)["name"] for _ in range(2 if len(pool) >= 2 and len(fit) > 3 else 1) if pool]
        if not crew:
            break
        dest = rng.choice(places)
        run = {"time": t, "dest": dest, "crew": crew, "find": {}, "event": "ok"}
        roll = rng.random()
        if roll < .25:
            run["line"] = f"{crew[0]}: Picked clean. Nothing worth carrying. Heading home."
        else:
            item = rng.choice(FINDS.get(dest, DEFAULT_FINDS))
            amt = min(rng.randint(*FIND_AMT[item]), DAY_CAP[item] - used[item])
            if amt <= 0:
                run["line"] = f"{crew[0]}: Somebody beat us to it. Coming home empty."
            else:
                used[item] += amt
                run["find"] = {item: amt}
                run["line"] = f"{crew[0]}: Found " + rng.choice(FIND_LINES[item]).format(n=amt) + ". Heading home."
        risk = rng.random()
        if risk < .05 and not safe:
            who = rng.choice(crew)
            run.update(event="hurt", hurt=who, injury=rng.choice(HURTS))
            run["scare"] = f"{crew[-1]}: {who} went down hard. {run['injury'].capitalize()}. We're coming back slow."
        elif risk < .17:
            run.update(event="scare", scare=f"{crew[-1]}: " + rng.choice(SCARES))
        runs.append(run)
    data["day_runs"] = {"day": new_day, "runs": runs}


def settle_day_runs(data, day, rng):
    """The day's small runs are over: their finds go into the stockpile and anyone hurt sits out tonight."""
    dr = data.pop("day_runs", None)
    if not dr or dr.get("day") != day:
        return [], {}
    total, lines = {}, []
    for r in dr["runs"]:
        for k, v in r.get("find", {}).items():
            total[k] = total.get(k, 0) + v
        what = ", ".join(f"+{v} {UNITS[k]}" for k, v in r.get("find", {}).items()) or "nothing"
        place = next((place_name("run", x) for x in data.get("runs", []) if x["dest"] == r["dest"]), r["dest"].title())
        lines.append(f"{' & '.join(r['crew'])} → {place} ({r['time']}): {what}" + (" (a close call)" if r["event"] == "scare" else ""))
        for name in r["crew"]:
            s = next((s for s in data["survivors"] if s["name"] == name), None)
            if s:
                s["day_outings"] = s.get("day_outings", 0) + 1
        if r["event"] == "hurt":
            s = next((s for s in data["survivors"] if s["name"] == r["hurt"] and s.get("status") not in ("dead", "away")), None)
            if s and s.get("status") != "injured":
                s.update(status="injured", injury=r["injury"], injured_until=day + 1)     # heals by morning: just misses tonight
                lines.append(f"{s['name']} came back with {r['injury']} and sat out tonight.")
    for k, v in total.items():
        data.setdefault("camp_bonus", []).append({"item": k, "amt": v, "why": "small runs"})
    return lines, total


# ---------------------------------------------------------------- 3e. follower milestones that change the world
# data.json milestones: [followers, text, effect, what it does]. Reaching one builds it for real.
def milestone_unlocks(data, new_day):
    hit, out = data.setdefault("milestones_hit", []), []
    for m in data.get("milestones", []):
        if len(m) < 3 or m[0] in hit or (data.get("followers") or 0) < m[0]:
            continue
        fx = m[2]
        hit.append(m[0])
        feats = data.setdefault("features", [])
        if fx == "lookout":
            feats.append({"id": "lookout", "name": "Lookout tower", "day": new_day, "defense": 6})
        elif fx == "pumps":
            data.setdefault("income", []).append({"item": "Fuel", "amt": 2, "why": "gas station pumps"})
        elif fx == "wall":
            feats.append({"id": "wall", "name": "Block wall", "day": new_day, "defense": 10})
            data.setdefault("camp_bonus", []).append({"item": "Barricades", "amt": 25, "why": "the block wall"})
        out.append(f"{m[0]} followers: {m[1]}. {m[3] if len(m) > 3 else ''}".strip())
    return out


# ---------------------------------------------------------------- 3f. the dead, counted
# Oakhaven had 40,000 people. data.json "undead" keeps the city's running count: the runs thin it out, a few more turn
# every night, and a horde brings thousands. The site's map only shows the ones near the camp.
KILLS_PER = {"easy": (1, 3), "medium": (2, 4), "hard": (3, 6), "deadly": (4, 8)}


def update_undead(data, outings, day_runs, horde, rng):
    U = data.setdefault("undead", {"count": 28400})
    killed = 0
    for o in outings:
        lo, hi = KILLS_PER.get(o.get("difficulty", "medium"), (2, 4))
        killed += sum(rng.randint(lo, hi) for r in o.get("results", []) if r["outcome"] != "dead")
    killed += sum(rng.randint(0, 2) for _ in range(day_runs))
    turned = rng.randint(2, 9)
    arrived = 0
    if horde:
        arrived = horde["strength"] * 40                     # the whole column, not just the ones that hit the fence
        killed += int(min(horde["strength"], horde["defense"]) * 6)
    U["count"] = max(0, U["count"] - killed + turned + arrived)
    U["last"] = {"day": data["day"], "killed": killed, "turned": turned, "arrived": arrived}
    return U


# ---------------------------------------------------------------- 4. new survivors
PROMPT = """These are Instagram comments on a zombie survival game. Some are people asking to join
(they give a name, a job, and maybe something about themselves). Others are votes, chatter, emoji or spam.
For each real join request return an object with:
  "ig": the username exactly as given
  "name": the character name they asked for (short, cleaned up, nothing hateful)
  "role": the closest match from {roles}
  "bio": one short, fun third-person sentence built from what they said
Crude, sexual or joke answers still get in: pick the closest role and write a bio that roasts it with a wink
(e.g. "Gary ran the adult shop on Main. The town pervert, and somehow still alive.") without getting graphic.
Skip anything that is not a join request, and anything hateful, harassing or aimed at a real person.
Reply with only a JSON array.

Comments:
"""


def read_joins(comments, skip):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log("No ANTHROPIC_API_KEY set: skipping new survivors.")
        return []
    import anthropic
    client = anthropic.Anthropic()
    by_user = {}
    for c in comments:
        u = c["username"]
        if u.lower() in skip:
            continue
        by_user.setdefault(u, []).append(c.get("text", "").replace("\n", " ")[:300])
    items, out = list(by_user.items()), []
    for i in range(0, len(items), 40):
        batch = "\n".join(f"@{u}: {' / '.join(t)}" for u, t in items[i:i + 40])
        msg = client.messages.create(model=MODEL, max_tokens=4000,
                                     messages=[{"role": "user", "content": PROMPT.format(roles=ROLES) + batch}])
        text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")   # skip thinking blocks
        try:
            out += json.loads(text[text.index("["): text.rindex("]") + 1])
        except ValueError:
            log("Skipped a batch: couldn't read Claude's reply:", text[:200])
    return out


def add_survivors(data, parsed):
    taken = {s["name"].lower() for s in data["survivors"]}   # the fallen keep their names; a newcomer called the same gets a number
    living_ig = {s.get("ig", "").lower() for s in data["survivors"] if s.get("status") != "dead"}
    queue = data.get("waitlist", []) + [p for p in parsed if isinstance(p, dict)]
    added, wait, seen = [], [], set()
    for p in queue:
        ig = str(p.get("ig", "")).lstrip("@").strip()
        if not ig or ig.lower() in living_ig or ig.lower() in seen or p.get("role") not in ROLES or not p.get("name"):
            continue
        seen.add(ig.lower())
        if len(added) >= MAX_NEW_PER_DAY:
            wait.append(p); continue
        base = str(p["name"]).strip()[:18]
        name, n = base, 2
        while name.lower() in taken:
            name, n = f"{base} {n}", n + 1
        s = {"name": name, "ig": ig, "role": p["role"], "bio": str(p.get("bio", ""))[:200], "joined": data["day"] + 1}
        data["survivors"].append(s)
        taken.add(name.lower()); living_ig.add(ig.lower()); added.append(s)
    data["waitlist"] = wait
    return added


# ---------------------------------------------------------------- 5b. the stockpile
# data.json "stock" rows are [name, amount, capacity, unit]. Food and water are rations: one per survivor per day.
# What each place brings home on a first visit (half that when it's been picked over), give or take a quarter.
LOOT = {"pharmacy": {"Medicine": 6, "Food": 2}, "diner": {"Food": 12, "Water": 6}, "gas": {"Fuel": 20, "Water": 8},
        "market": {"Food": 18, "Water": 10}, "hardware": {"Scrap": 25}, "gunshop": {"Ammo": 40}, "port": {"Food": 30, "Scrap": 10},
        "ranger": {"Ammo": 15, "Medicine": 4, "Food": 4}, "hangar": {"Fuel": 30, "Scrap": 10}, "firestation": {"Medicine": 6, "Scrap": 15, "Water": 10},
        "maple": {"Food": 8, "Ammo": 4}, "storage": {"Scrap": 15, "Food": 4}, "mall": {"Scrap": 15, "Water": 10, "Food": 6},
        "freight": {"Food": 25}, "farm": {"Food": 15, "Water": 6}, "fair": {"Food": 10, "Scrap": 8}, "harbor": {"Water": 10, "Food": 6},
        "hunter": {"Ammo": 12, "Food": 8}, "cold": {"Food": 30}, "greenhouse": {"Food": 8, "Water": 4}, "airfreight": {"Medicine": 15},
        "checkpoint": {"Ammo": 60, "Food": 6, "Medicine": 4}, "surplus": {"Water": 15, "Food": 6, "Medicine": 2},
        "funhouse": {"Scrap": 12}, "arcade": {"Scrap": 10}, "showbarn": {"Food": 12}}
AMMO_USE = {"easy": 2, "medium": 6, "hard": 15, "deadly": 30}     # rounds a squad burns on an outing
FENCE_WEAR = 4                                                   # barricade % the dead tear down each night


def stock_row(data, name):
    return next((r for r in data.get("stock", []) if r[0] == name), None)


def stock_get(data, name):
    r = stock_row(data, name)
    return r[1] if r else 0


def keep_stockpile(data, outings, rng, new_day):
    """Runs bring things home, everyone eats, generators burn fuel, the fence wears. Returns (ledger, notes)."""
    ledger, notes = {}, []
    def add(name, amt, why):
        r = stock_row(data, name)
        if not r or not amt:
            return 0
        before = r[1]
        r[1] = max(0, min(r[2], r[1] + amt))
        if r[1] != before:
            ledger.setdefault(name, []).append((r[1] - before, why))
        return r[1] - before
    present = [s for s in data["survivors"] if s.get("status") != "dead" and s.get("joined", 1) <= data["day"]]

    # one-off story bonuses set by hand in data.json, e.g. {"item": "Food", "amt": 8, "why": "Tanny's jerky", "note": "..."}
    for b in data.pop("camp_bonus", []):
        add(b["item"], b["amt"], b.get("why", "bonus"))
        if b.get("note"):
            notes.append(b["note"])

    # loot and ammo from today's outings
    for o in outings:
        if not o.get("squad"):
            continue
        add("Ammo", -AMMO_USE.get(o.get("difficulty"), 6), f"{o['target']} run")
        if o.get("kind") == "run" and any(r["outcome"] != "dead" for r in o["results"]):
            for item, amt in LOOT.get(o.get("key"), {}).items():
                add(item, round(amt * (1 if o.get("first") else .5) * rng.uniform(.75, 1.25)), o["target"])

    # finished missions pay out once ("gain"), and some keep giving every night after ("income": the windmill, the milk cows)
    for o in outings:
        if o.get("kind") == "mission" and o.get("mission_status") == "done" and any(r["outcome"] != "dead" for r in o["results"]):
            m = next((m for m in data.get("missions", []) if m.get("poi") == o.get("key")), {})
            for item, amt in (m.get("gain") or {}).items():
                add(item, amt, m.get("name", o["target"]))
            for item, amt in (m.get("income") or {}).items():
                data.setdefault("income", []).append({"item": item, "amt": amt, "why": m.get("name", o["target"])})
            if m.get("done_note"):
                notes.append(m["done_note"])
            have = data.setdefault("zombie_types", ["walker"])
            for z in m.get("unlock_zombies", []):
                if z not in have:
                    have.append(z)
                    notes.append(m.get("unlock_note") or f"Something new out there: {z}s.")
    for inc in data.get("income", []):          # the windmill, the milk cows, Mateen's roof garden once it grows...
        if new_day >= inc.get("from_day", 0):
            add(inc["item"], inc["amt"], inc["why"])

    # everyone eats and drinks
    n = len(present)
    short = stock_get(data, "Food") < n or stock_get(data, "Water") < n
    add("Food", -n, "eaten"); add("Water", -n, "drunk")
    data["hungry_days"] = data.get("hungry_days", 0) + 1 if short else 0
    if short:
        notes.append("The camp went to bed hungry." if data["hungry_days"] < 2 else f"Day {data['hungry_days']} without enough to eat.")
    if data["hungry_days"] >= 2:
        weak = [s for s in present if not s.get("protected") and s.get("status") not in ("injured", "away")]
        if weak:
            s = rng.choice(weak)
            s.update(status="injured", injury="collapsed from hunger", injured_until=new_day + 2)
            notes.append(f"{s['name']} collapsed from hunger and is out until Day {s['injured_until']}.")

    # medicine speeds healing: one dose a night takes a day off an injury
    for s in present:
        if s.get("status") == "injured" and s.get("injured_until", 0) > new_day and stock_get(data, "Medicine") >= 1:
            add("Medicine", -1, f"{s['name']}'s injury")
            s["injured_until"] -= 1

    # running generators burn fuel; an empty tank means the lights go out until there's more
    for g in data.get("power", []):
        if g.get("status") != "running":
            continue
        burn = g.get("burn", 2)
        if stock_get(data, "Fuel") >= burn:
            add("Fuel", -burn, g["name"])
            if g.pop("dry", None):
                notes.append(f"The {g['name']} is back on.")
        elif not g.get("dry"):
            g["dry"] = True
            notes.append(f"The {g['name']} ran out of fuel and went dark.")

    # the dead wear the fence down; builders and scrap patch it up
    add("Barricades", -FENCE_WEAR, "the dead at the fence")
    builders = [s for s in present if s.get("role") == "Builder" and s.get("status") not in ("injured", "away")]
    for b in builders:
        if stock_get(data, "Scrap") >= 3 and stock_get(data, "Barricades") < 100:
            add("Scrap", -3, "fence repairs"); add("Barricades", 5, f"{b['name']} rebuilt a section")
    if stock_get(data, "Barricades") < 70 and stock_get(data, "Scrap") >= 4:
        add("Scrap", -4, "fence repairs"); add("Barricades", 4, "patched with scrap")
    if stock_get(data, "Barricades") <= 0:
        victims = [s for s in present if not s.get("protected") and s.get("status") not in ("dead", "away")]
        if victims:
            s = rng.choice(victims)
            s.update(status="injured", injury="caught when the fence gave way", injured_until=new_day + 3)
            notes.append(f"The fence gave way in the night. {s['name']} was caught and is out until Day {s['injured_until']}.")
        add("Barricades", 30, "emergency barricade")
    data["stock_change"] = {k: sum(a for a, _ in v) for k, v in ledger.items()}
    return ledger, notes


def days_left(data, name):
    n = max(1, len([s for s in data["survivors"] if s.get("status") != "dead" and s.get("joined", 1) <= data["day"]]))
    return stock_get(data, name) // n


# ---------------------------------------------------------------- 6. the power project
# Each generator in data.json "power" can list what it needs to run: things a run brings back ("dest"), a skill someone in
# camp has ("role"), or enough people ("people"). Needs get ticked off as the story goes; when they're all met it runs.
def power_progress(data, outings, new_day):
    living = [s for s in data["survivors"] if s.get("status") != "dead" and s.get("joined", 1) <= new_day]
    came_back = {o.get("key") for o in outings if o.get("results") and any(r["outcome"] != "dead" for r in o["results"])}
    news, busy, lit = [], set(), False      # each skill works on one generator a night, and only one comes on per night
    for g in data.get("power", []):
        needs = g.get("needs") or []
        if not needs or g.get("status") == "running":
            continue
        if g.get("status") == "rumor" and g.get("found_by") in came_back:
            g["status"] = "found"
            news.append(f"Found the {g['name']} during the {g['found_by']} run.")
        if g.get("status") == "rumor":
            continue
        for n in needs:
            if n.get("done"):
                continue
            hit = (n.get("dest") and n["dest"] in came_back) \
                or (n.get("role") and n["role"] not in busy and any(s["role"] == n["role"] and s.get("status") not in ("injured", "away") for s in living)) \
                or (n.get("people") and len(living) >= n["people"])
            if hit and n.get("role"):
                busy.add(n["role"])
            if hit:
                n["done"], n["day"] = True, new_day - 1
                news.append(f"{g['name']}: {n['label']} ✓")
        done = sum(1 for n in needs if n.get("done"))
        if done == len(needs) and not lit:
            lit = True
            g["status"], g["on_day"] = "running", new_day - 1
            g.pop("progress", None)
            news.append(f"⚡ The {g['name']} is RUNNING. {g.get('powers', '')}")
        elif done:
            g["status"], g["progress"] = "repairing", round(done / len(needs) * 100) if done < len(needs) else 99
    return news


def power_wants(data):
    """Run destinations that would tick off an open power need, for the vote to favor."""
    out = []
    for g in data.get("power", []):
        if g.get("status") in ("found", "repairing"):
            out += [(n["dest"], g["name"], n["label"]) for n in g.get("needs", []) if n.get("dest") and not n.get("done")]
    return out


# ---------------------------------------------------------------- 7. tomorrow's vote
# the word people comment for each place (must be easy to type and not contain another option's word)
LABELS = {"gunshop": "GUN SHOP", "port": "PIER", "firestation": "FIRE STATION", "cold": "COLD STORAGE", "airfreight": "AIR FREIGHT",
          "showbarn": "SHOW BARN", "hunter": "CABIN", "harbor": "HARBOR", "storage": "STORAGE UNITS", "surplus": "SURPLUS"}
EMOJI = {"pharmacy": "💊", "diner": "🍳", "gas": "⛽", "market": "🛒", "hardware": "🔨", "gunshop": "🔫", "port": "⚓", "ranger": "🌲",
         "hangar": "🛩", "firestation": "🚒", "maple": "🏘", "storage": "📦", "mall": "🛍", "freight": "🚂", "farm": "🌾", "fair": "🎡",
         "harbor": "⛵", "hunter": "🏕", "cold": "🧊", "greenhouse": "🌱", "airfreight": "🛫", "checkpoint": "🪖", "surplus": "🎒", "windmill": "💧", "harvest": "🌽", "cattle": "🐄", "fortify": "🧱",
         "funhouse": "🤡", "arcade": "🕹", "showbarn": "🐄", "hospital": "🏥", "police": "🚓", "terminal": "🛬"}
UNLOCK = {"easy": 1, "medium": 2, "hard": 4, "deadly": 6}     # healthy survivors needed before a difficulty shows up in the vote

VOTE_PROMPT = """You write the daily vote for Oakhaven, an Instagram zombie survival story told by a gravelly narrator.
Tomorrow is Day {day}. Here is what happened today:
{recap}

The survivors can go to one of these places tomorrow (the word in capitals is what followers comment):
{options}

Write:
  "q": the vote question, starting with "Day {day}." then one or two short, tense sentences that set up the choice from today's events. Under 140 characters.
  "desc": for each option word, one short line (under 70 characters) on why it's tempting or what the risk is. Don't promise what they'll find.
Only use facts from the recap above: don't invent what happened, who was there or what was found.
Reply with only JSON like {{"q": "...", "desc": {{"WORD": "..."}}}}."""


def vote_options(data, new_day, rng):
    healthy = [s for s in data["survivors"] if s.get("status") not in ("dead", "injured", "away") and s.get("joined", 1) <= new_day]
    n = len(healthy)
    ok = lambda diff: n >= UNLOCK.get(diff, 2)
    runs = [r for r in data.get("runs", []) if ok(r.get("difficulty", "easy"))]
    fresh = [r for r in runs if not r.get("done_day")]
    again = sorted([r for r in runs if r.get("done_day")], key=lambda r: r["done_day"])   # longest since the last visit first
    pool = [("run", r) for r in (fresh[:5] or again[:5])]
    picks = rng.sample(pool, min(3, len(pool)))
    missions = [m for m in data.get("missions", []) if m.get("poi") and m.get("status") != "done" and n >= SQUAD_SIZE.get(m.get("difficulty", "hard"), 4)]
    if missions and picks and rng.random() < .5:
        picks[-1] = ("mission", rng.choice(missions))
    want = {}
    for d, g, l in power_wants(data):
        want.setdefault(d, (g, l))
    if want and not any(it.get("dest") in want for _, it in picks):     # one option always moves the power project along
        r = next((r for r in runs if r["dest"] in want), None)
        if r:
            picks = picks[:2] + [("run", r)]
    if days_left(data, "Food") < 3 and not any(LOOT.get(it.get("dest"), {}).get("Food", 0) >= 8 for k, it in picks if k == "run"):
        r = next((r for r in fresh + again if LOOT.get(r["dest"], {}).get("Food", 0) >= 8), None)
        if r and all(it is not r for _, it in picks):
            picks = picks[:1] + [("run", r)] + picks[2:] if len(picks) > 1 else picks + [("run", r)]
    while len(picks) < 3 and again:
        r = again.pop(0)
        if all(it is not r for _, it in picks):
            picks.append(("run", r))
    out = []
    for kind, it in picks:
        key = it["poi"] if kind == "mission" else it["dest"]
        label = LABELS.get(key, key.upper())
        if any(label in o["label"] or o["label"] in label for o in out):
            continue
        out.append({"kind": kind, "key": key, "label": label, "place": place_name(kind, it), "difficulty": it.get("difficulty", "easy"),
                    "hint": it.get("goal") if kind == "mission" else (f"needed for the {want[key][0]}: {want[key][1]}" if key in want else ("visited before" if it.get("done_day") else "never searched"))})
    return out


def ballot_options(data, ballot):
    """A ballot set by a story beat: {"day": 5, "keys": ["gunshop", "fortify", "windmill", "harvest"]}."""
    out = []
    for k in ballot.get("keys", []):
        t = find_target(data, k)
        if not t or (t[0] == "mission" and t[1].get("status") == "done"):
            continue
        kind, it = t
        key = it["poi"] if kind == "mission" else it["dest"]
        out.append({"kind": kind, "key": key, "label": LABELS.get(key, key.upper()), "place": place_name(kind, it), "difficulty": it.get("difficulty", "easy"),
                    "hint": it.get("goal") if kind == "mission" else ("visited before" if it.get("done_day") else "never searched")})
    return out


def next_vote(data, new_day, rng, recap, problems):
    active = next((m for m in data.get("missions", []) if m.get("status") == "active"), None)
    if active:
        left = active.get("days", 3) - active.get("days_done", 0)
        return {"q": f"Day {new_day}. No vote today: the squad is still inside {place_name('mission', active)} ({left} more night{'s' if left != 1 else ''}).",
                "opts": [], "how": "Comment your name and your job to move in."}
    ballot = data.get("ballot") if (data.get("ballot") or {}).get("day") == new_day else None
    opts = ballot_options(data, ballot) if ballot else vote_options(data, new_day, rng)
    if len(opts) < 2:
        return {"q": f"Day {new_day}. Nowhere left to vote on tonight.", "opts": [], "how": "Comment your name and your job to move in."}
    q, desc = f"Day {new_day}. Where does the squad go next?", {}
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic
            lines = "\n".join(f"- {o['label']}: {o['place']} ({o['difficulty']}{', a mission: ' + o['hint'] if o['kind'] == 'mission' else ', ' + o['hint']})" for o in opts)
            msg = anthropic.Anthropic().messages.create(model=MODEL, max_tokens=4000, messages=[{"role": "user", "content": VOTE_PROMPT.format(day=new_day, recap=recap, options=lines)}])
            text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
            got = json.loads(text[text.index("{"): text.rindex("}") + 1])
            if str(got.get("q", "")).startswith(f"Day {new_day}"):
                q = str(got["q"])[:200]
            desc = {str(k).upper(): str(v)[:90] for k, v in (got.get("desc") or {}).items()}
        except Exception as e:
            log(f"!! Writing the vote failed, using plain wording: {e}")
            problems.append(f"Vote wording: {e}")
    fallback = {"easy": "A quick run. Low risk.", "medium": "Further out. More of them.", "hard": "Dangerous. Bring a medic.", "deadly": "Not everyone comes back."}
    words = [o["label"] for o in opts]
    return {"q": q,
            "opts": [[o["label"], 0, desc.get(o["label"]) or fallback.get(o["difficulty"], ""), o["key"], EMOJI.get(o["key"], "")] for o in opts],
            "how": f"Comment {', '.join(words[:-1])} or {words[-1]} (or its emoji) on the Day {new_day} Reel. One vote per account, your last comment counts."}


# ---------------------------------------------------------------- main
def main():
    data = json.load(open(DATA_FILE, encoding="utf-8"))
    # GitHub often starts the scheduled run hours late. If the day was already advanced by hand (the Run workflow button)
    # in the last 12 hours, the late scheduled run skips, so a day is never advanced twice.
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and time.time() - data.get("last_run", 0) < 12 * 3600:
        log("Already advanced in the last 12 hours (by hand). Skipping this scheduled run.")
        return
    day = data["day"]
    rng = random.Random(f"oakhaven-{day}-{os.environ.get('OAKHAVEN_SEED', '')}")
    problems = []
    try:
        ig = fetch_instagram(data.get("last_run"))
    except Exception as e:                                 # an expired token shouldn't stop the story: the day still advances
        log(f"!! Instagram failed: {e}")
        problems.append(f"Instagram: {e}")
        ig = None
    comments = ig["comments"] if ig else []

    day_lines, day_finds = settle_day_runs(data, day, rng)
    winner, tally = count_vote(data, comments)
    tiebreak = None
    if not winner and tally:                             # a tie: Sam's call if one is set in data.json vote "tiebreak", otherwise a coin flip
        top = max(tally.values())
        tied = sorted(k for k, v in tally.items() if v == top)
        call = str((data.get("vote") or {}).get("tiebreak", "")).upper()
        winner = call if call in tied else rng.choice(tied)
        tiebreak = f"{' / '.join(tied)} tied. " + (f"Sam broke the tie: {winner}." if call in tied else f"A coin flip picked {winner}.")
    keys = {o[0].upper(): o[3] for o in (data.get("vote") or {}).get("opts", []) if len(o) > 3}
    outings = todays_outing(data, keys.get(winner, winner), rng)
    new_day = day + 1
    trips = scout_trips(data, new_day, rng, outings)
    ledger, stock_notes = keep_stockpile(data, outings, rng, new_day)
    horde = horde_night(data, rng, day)
    healed = heal(data, new_day)
    returned = come_home(data, new_day)
    story = trips + run_schedule(data, new_day, rng)

    living_ig = {s.get("ig", "").lower() for s in data["survivors"] if s.get("status") != "dead"}
    living_ig |= {str(p.get("ig", "")).lower() for p in data.get("waitlist", [])}
    try:
        parsed = read_joins(comments, living_ig) if comments else []
        if DRY and not comments:
            parsed_test = read_joins([{"username": "test_jake", "text": "Jake here, I'll be the mechanic. Scared of birds."},
                                      {"username": "test_vote", "text": "DINER!!"}], set())
            log(f"Claude self-test (not saved): {parsed_test}")
    except Exception as e:
        log(f"!! Reading join comments failed: {e}")
        problems.append(f"Claude: {e}")
        parsed = []
    added = add_survivors(data, parsed)
    power_news = power_progress(data, outings, new_day)

    if ig:
        data["followers"] = ig["followers"]
    unlocked = milestone_unlocks(data, new_day)
    undead = update_undead(data, outings, len(day_lines), horde, rng)
    data["day"] = new_day
    entry = {"day": day, "vote": {"question": (data.get("vote") or {}).get("q"), "results": tally, "winner": winner, "tiebreak": tiebreak,
                                  "reel": ig["reel"]["permalink"] if ig and ig.get("reel") else None},
             "outings": outings, "healed": healed, "joined": [s["name"] for s in added], "waiting": len(data.get("waitlist", [])), "power": power_news,
             "stock": data.get("stock_change", {}), "camp": stock_notes,
             "horde": horde, "returned": returned, "story": story, "day_runs": day_lines}
    data.setdefault("log", []).append(entry)
    data["log"] = data["log"][-60:]                      # keep the file small: the last two months

    # recap for writing tomorrow's Reel
    lines = [f"# Oakhaven: Day {day} recap", ""]
    if tally:
        lines.append(f"**Vote:** {', '.join(f'{k} {v}' for k, v in tally.items())}. Winner: {winner or 'tie, no winner'}.")
    if tiebreak:
        lines.append(f"**Tie:** {tiebreak}")
    for o in outings:
        lines.append(f"**{o['kind'].title()}: {o['target']}** ({o['difficulty']}), squad: {', '.join(o['squad']) or 'nobody'}"
                     + (f" — mission {o['mission_status']}" if o.get("mission_status") else ""))
        for r in o["results"]:
            if r["outcome"] == "dead":
                lines.append(f"- † **{r['name']}** (@{r['ig']}) died. {r['detail']}")
            elif r["outcome"] == "injured":
                lines.append(f"- {r['name']} (@{r['ig']}) was hurt: {r['detail']}")
        if o.get("note"):
            lines.append(f"- {o['note']} The camp stayed behind the fence.")
        elif all(r["outcome"] == "ok" for r in o["results"]):
            lines.append("- Everyone came back in one piece.")
    if horde:
        lines.append(f"**Horde night (week {horde['week']}): the fence {horde['outcome'].upper()}.** {horde['strength']} of them against a defense of {horde['defense']}"
                     + (" (the generator light drew more in)" if horde["lit"] else "") + f". Defenders: {', '.join(horde['defenders']) or 'nobody'}.")
        for d_ in horde["dead"]:
            lines.append(f"- † **{d_}** was pulled over the fence.")
        for h_ in horde["hurt"]:
            lines.append(f"- Hurt: {h_}")
    if day_lines:
        lines.append("**Small runs today:** " + " · ".join(day_lines))
    if healed:
        lines.append(f"**Back on their feet:** {', '.join(healed)}")
    for r_ in returned:
        lines.append(f"**Back from scouting:** {r_}")
    for n_ in story:
        lines.append(f"**Story:** {n_}")
    L_ = undead["last"]
    lines.append(f"**Undead in Oakhaven:** {undead['count']:,} (−{L_['killed']} killed, +{L_['turned']} newly turned"
                 + (f", +{L_['arrived']:,} arrived with the horde" if L_["arrived"] else "") + ")")
    for u_ in unlocked:
        lines.append(f"**Milestone reached:** {u_} (shout out the new followers in the Reel!)")
    if data.get("broadcast", {}).get("day") == new_day:
        lines.append(f"**On the radio ({data['broadcast']['from']}):** {data['broadcast']['text']}")
    for n in power_news:
        lines.append(f"**Power:** {n}")
    if ledger:
        parts = []
        for name, moves in ledger.items():
            parts.append(f"{name} {stock_get(data, name)} (" + ", ".join(f"{a:+d} {why}" for a, why in moves) + ")")
        lines.append("**Stockpile:** " + " · ".join(parts))
    fd, wd = days_left(data, 'Food'), days_left(data, 'Water')
    lines.append(f"**Supplies left:** food for {fd} day{'s' if fd != 1 else ''}, water for {wd} day{'s' if wd != 1 else ''}, {stock_get(data, 'Ammo')} rounds, fence at {stock_get(data, 'Barricades')}%")
    for n in stock_notes:
        lines.append(f"**Camp:** {n}")
    if data.get("horde"):
        left = data["horde"]["day"] - new_day
        lines.append(f"**Horde:** " + ("arrives TONIGHT (Day %d). Fence %d%%, %d rounds." % (data["horde"]["day"], stock_get(data, "Barricades"), stock_get(data, "Ammo"))
                                       if left == 0 else f"reaches the fence in {left} day{'s' if left != 1 else ''} (Day {data['horde']['day']})."))
    lines.append(f"**New survivors ({len(added)}):** " + (", ".join(f"{s['name']} the {s['role']} (@{s['ig']})" for s in added) or "none"))
    if data.get("waitlist"):
        lines.append(f"**Still waiting to get in:** {len(data['waitlist'])}")
    lines.append(f"**Followers:** {data.get('followers')}  |  **Tomorrow is Day {new_day}**")
    data["vote"] = next_vote(data, new_day, rng, "\n".join(lines), problems)
    plan_day_runs(data, new_day, random.Random(f"oakhaven-day-{new_day}-{os.environ.get('OAKHAVEN_SEED', '')}"))
    v = data["vote"]
    lines.append(f"**Tomorrow's vote:** {v['q']}" + (" " + " / ".join(f"{(o[4] + ' ') if len(o) > 4 and o[4] else ''}{o[0]} ({o[2]})" for o in v["opts"]) if v["opts"] else ""))
    for p in problems:
        lines.append(f"**⚠ Problem:** {p}")
    report = "\n".join(lines) + "\n"
    log("\n" + report)

    if DRY:
        log("DRY_RUN: nothing written.")
        return
    data["last_run"] = int(time.time())
    json.dump(data, open(DATA_FILE, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    open(REPORT_FILE, "w", encoding="utf-8").write(report)


if __name__ == "__main__":
    main()
