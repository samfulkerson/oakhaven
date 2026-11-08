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
import os, re, json, random
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


def fetch_instagram():
    """Follower count, newest Reel and every comment on it. Returns None if no Instagram credentials are set."""
    if not os.environ.get("IG_TOKEN"):
        log("No IG_TOKEN set: skipping Instagram (no vote count, no new survivors).")
        return None
    GRAPH = ig_base()
    uid = "me" if "graph.instagram.com" in GRAPH else IG_ACCOUNT_ID
    log(f"Instagram API: {GRAPH.split('//')[1]} as {uid}")
    followers = ig_get(f"{GRAPH}/{uid}", fields="followers_count")["followers_count"]
    media = ig_get(f"{GRAPH}/{uid}/media", fields="id,media_type,media_product_type,permalink,timestamp", limit=15)["data"]
    reels = [m for m in media if m.get("media_product_type") == "REELS" or m.get("media_type") in ("VIDEO", "REELS")]
    if not reels:
        log("No Reel found yet.")
        return {"followers": followers, "reel": None, "comments": []}
    reel = reels[0]
    comments, url, params = [], f"{GRAPH}/{reel['id']}/comments", {"fields": "username,text,timestamp", "limit": 50}
    while url:
        page = ig_get(url, **params)
        comments += page.get("data", [])
        url, params = page.get("paging", {}).get("next"), {}
    comments = [c for c in comments if c.get("username")]
    comments.sort(key=lambda c: c.get("timestamp", ""))
    log(f"Instagram: {followers} followers, {len(comments)} comments on {reel['permalink']}")
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
        pick = next((o for o in options if f" {o} " in text), None) \
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
    living = [s for s in data["survivors"] if s.get("status") not in ("dead", "injured") and s.get("joined", 1) <= data["day"]]
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
        if roll < die and not s.get("protected"):
            s.update(status="dead", died_day=data["day"], died_at=place, cause=rng.choice(DEATHS).format(p=place))
            results.append({"name": s["name"], "ig": s.get("ig", ""), "outcome": "dead", "detail": s["cause"]})
        elif roll < die + inj:       # an injury; a protected character (Sam) who rolls death gets the worst injury instead
            lo, hi = INJURY_DAYS.get(diff, (2, 4))
            days = rng.randint(lo, hi) + (2 if roll < die else 0)
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

    # everyone eats and drinks
    n = len(present)
    short = stock_get(data, "Food") < n or stock_get(data, "Water") < n
    add("Food", -n, "eaten"); add("Water", -n, "drunk")
    data["hungry_days"] = data.get("hungry_days", 0) + 1 if short else 0
    if short:
        notes.append("The camp went to bed hungry." if data["hungry_days"] < 2 else f"Day {data['hungry_days']} without enough to eat.")
    if data["hungry_days"] >= 2:
        weak = [s for s in present if not s.get("protected") and s.get("status") != "injured"]
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
    builders = [s for s in present if s.get("role") == "Builder" and s.get("status") != "injured"]
    for b in builders:
        if stock_get(data, "Scrap") >= 3 and stock_get(data, "Barricades") < 100:
            add("Scrap", -3, "fence repairs"); add("Barricades", 5, f"{b['name']} rebuilt a section")
    if stock_get(data, "Barricades") < 70 and stock_get(data, "Scrap") >= 4:
        add("Scrap", -4, "fence repairs"); add("Barricades", 4, "patched with scrap")
    if stock_get(data, "Barricades") <= 0:
        victims = [s for s in present if not s.get("protected") and s.get("status") != "dead"]
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
                or (n.get("role") and n["role"] not in busy and any(s["role"] == n["role"] and s.get("status") != "injured" for s in living)) \
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
         "harbor": "⛵", "hunter": "🏕", "cold": "🧊", "greenhouse": "🌱", "airfreight": "🛫", "checkpoint": "🪖", "surplus": "🎒",
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
    healthy = [s for s in data["survivors"] if s.get("status") not in ("dead", "injured") and s.get("joined", 1) <= new_day]
    n = len(healthy)
    ok = lambda diff: n >= UNLOCK.get(diff, 2)
    runs = [r for r in data.get("runs", []) if ok(r.get("difficulty", "easy"))]
    fresh = [r for r in runs if not r.get("done_day")]
    again = sorted([r for r in runs if r.get("done_day")], key=lambda r: r["done_day"])   # longest since the last visit first
    pool = [("run", r) for r in (fresh[:5] or again[:5])]
    picks = rng.sample(pool, min(3, len(pool)))
    missions = [m for m in data.get("missions", []) if m.get("status") != "done" and n >= SQUAD_SIZE.get(m.get("difficulty", "hard"), 4)]
    if missions and picks and rng.random() < .5:
        picks[-1] = ("mission", missions[0])
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


def next_vote(data, new_day, rng, recap, problems):
    active = next((m for m in data.get("missions", []) if m.get("status") == "active"), None)
    if active:
        left = active.get("days", 3) - active.get("days_done", 0)
        return {"q": f"Day {new_day}. No vote today: the squad is still inside {place_name('mission', active)} ({left} more night{'s' if left != 1 else ''}).",
                "opts": [], "how": "Comment your name and your job to move in."}
    opts = vote_options(data, new_day, rng)
    if len(opts) < 2:
        return {"q": f"Day {new_day}. Nowhere left to vote on tonight.", "opts": [], "how": "Comment your name and your job to move in."}
    q, desc = f"Day {new_day}. Where does the squad go next?", {}
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic
            lines = "\n".join(f"- {o['label']}: {o['place']} ({o['difficulty']}{', a multi-night mission: ' + o['hint'] if o['kind'] == 'mission' else ', ' + o['hint']})" for o in opts)
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
    day = data["day"]
    rng = random.Random(f"oakhaven-{day}-{os.environ.get('OAKHAVEN_SEED', '')}")
    problems = []
    try:
        ig = fetch_instagram()
    except Exception as e:                                 # an expired token shouldn't stop the story: the day still advances
        log(f"!! Instagram failed: {e}")
        problems.append(f"Instagram: {e}")
        ig = None
    comments = ig["comments"] if ig else []

    winner, tally = count_vote(data, comments)
    keys = {o[0].upper(): o[3] for o in (data.get("vote") or {}).get("opts", []) if len(o) > 3}
    outings = todays_outing(data, keys.get(winner, winner), rng)
    new_day = day + 1
    ledger, stock_notes = keep_stockpile(data, outings, rng, new_day)
    healed = heal(data, new_day)

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
    data["day"] = new_day
    entry = {"day": day, "vote": {"question": (data.get("vote") or {}).get("q"), "results": tally, "winner": winner,
                                  "reel": ig["reel"]["permalink"] if ig and ig.get("reel") else None},
             "outings": outings, "healed": healed, "joined": [s["name"] for s in added], "waiting": len(data.get("waitlist", [])), "power": power_news,
             "stock": data.get("stock_change", {}), "camp": stock_notes}
    data.setdefault("log", []).append(entry)
    data["log"] = data["log"][-60:]                      # keep the file small: the last two months

    # recap for writing tomorrow's Reel
    lines = [f"# Oakhaven: Day {day} recap", ""]
    if tally:
        lines.append(f"**Vote:** {', '.join(f'{k} {v}' for k, v in tally.items())}. Winner: {winner or 'tie, no winner'}.")
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
    if healed:
        lines.append(f"**Back on their feet:** {', '.join(healed)}")
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
    lines.append(f"**New survivors ({len(added)}):** " + (", ".join(f"{s['name']} the {s['role']} (@{s['ig']})" for s in added) or "none"))
    if data.get("waitlist"):
        lines.append(f"**Still waiting to get in:** {len(data['waitlist'])}")
    lines.append(f"**Followers:** {data.get('followers')}  |  **Tomorrow is Day {new_day}**")
    data["vote"] = next_vote(data, new_day, rng, "\n".join(lines), problems)
    v = data["vote"]
    lines.append(f"**Tomorrow's vote:** {v['q']}" + (" " + " / ".join(f"{(o[4] + ' ') if len(o) > 4 and o[4] else ''}{o[0]} ({o[2]})" for o in v["opts"]) if v["opts"] else ""))
    for p in problems:
        lines.append(f"**⚠ Problem:** {p}")
    report = "\n".join(lines) + "\n"
    log("\n" + report)

    if DRY:
        log("DRY_RUN: nothing written.")
        return
    json.dump(data, open(DATA_FILE, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    open(REPORT_FILE, "w", encoding="utf-8").write(report)


if __name__ == "__main__":
    main()
