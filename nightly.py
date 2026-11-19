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
import os, re, json, math, random, time
from datetime import datetime, timezone
from collections import Counter

# ---------------------------------------------------------------- settings you might want to change
DATA_FILE = "data.json"
REPORT_FILE = "report.md"
IG_ACCOUNT_ID = os.environ.get("IG_USER_ID") or "17841422748770654"   # @surviveoakhaven's Instagram account ID, shown on the Meta app page
MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-5-5")
MAX_NEW_PER_DAY = 25          # pacing: at most this many new survivors move in per day; the rest wait in line
BUDDY_PACK = {"Food": 6, "Water": 6}   # someone who joins "with @a_survivor" arrives with a full pack, and the two become buddies
BUDDY_RISK = 0.7                        # buddies on the same outing cover each other: injury and death odds x0.7 for both
# camp jobs: everyone who spends the day at the laundromat (not out on the vote's run, not on a mission, not hurt) works their job,
# so a bigger camp feeds itself better. role -> (item, amount each, why)
CAMP_JOBS = {"Farmer": ("Food", 3, "the farm plots"), "Scout": ("Food", 1, "snares and hunting"), "Scavenger": ("Food", 1, "foraging the block"),
             "Engineer": ("Water", 2, "rain catchers and pipe taps")}
CHEF_STRETCH = 0.1          # a chef at home stretches every meal: this share of the camp's food comes back
PACK = {"Food": 2, "Water": 2}  # what each new survivor carries in; counted the next night, when they start eating
ROLES = ["Scavenger", "Medic", "EMT", "Scout", "Sharpshooter", "Gunsmith", "Farmer", "Builder", "Radio Operator", "Mechanic", "Guard", "Cook", "Engineer"]
ACTS_AS = {"EMT": "Medic"}     # roles that do another role's job in the game: an EMT patches people up like a medic
def role_of(s):
    r = s.get("role", "")
    return ACTS_AS.get(r, r)

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
        url, params = f"{GRAPH}/{m['id']}/comments", {"fields": "username,text,timestamp,like_count,replies{username,text,timestamp,like_count}", "limit": 50}
        while url:
            page = ig_get(url, **params)
            for c in page.get("data", []):          # replies count too: people change their vote, or give their name, in a reply
                for x in [c] + (c.get("replies") or {}).get("data", []):
                    if x.get("username") and stamp(x.get("timestamp", "1970-01-01T00:00:00")) > since:
                        comments.append({"username": x["username"], "text": x.get("text") or "", "timestamp": x.get("timestamp") or "", "likes": x.get("like_count") or 0})
            url, params = page.get("paging", {}).get("next"), {}
    comments.sort(key=lambda c: c.get("timestamp", ""))
    log(f"Instagram: {followers} followers, {len(comments)} comments on {len(recent)} recent post(s); vote Reel {reel['permalink']}")
    return {"followers": followers, "reel": reel, "comments": comments}


# ---------------------------------------------------------------- 1b. story questions: let an NPC in (YES/NO), name the dog
YES_RE = re.compile(r"\b(yes|yeah|yep|yup|let him in|open the gate|trust him)\b", re.I)
NO_RE = re.compile(r"\b(no(?! idea| clue)|nope|nah|keep him out|don'?t trust|leave him|shut the gate|turn him away)\b", re.I)
ARM_RE = re.compile(r"\b(arms?|sleeves?|roll (it|that) up|check (him|his))\b", re.I)   # "show us your arm first": its own answer, ahead of yes/no
NAME_RE = [re.compile(p, re.I) for p in (
    r"\b(?:name (?:him|her|it|the dog|that dog|the pup|our dog)|call (?:him|her|it|the dog))\s*[:\-]?\s*['\"]?([a-z][a-z'\-]{1,14})",
    r"\bdog(?:'s name)?\s*(?:is|should be|named|=|:|-)\s*['\"]?([a-z][a-z'\-]{1,14})",
    r"(?:🐶|🐕|🐾)\s*['\"]?([a-z][a-z'\-]{1,14})",
    r"\b([a-z][a-z'\-]{1,14})\s+(?:for|as) the dog\b")]
NOT_NAMES = {"him", "her", "it", "the", "a", "an", "dog", "should", "be", "is", "yes", "no", "something", "after", "maybe"}


def story_questions(data, comments, new_day):
    """Elias at the gate: the comments decide YES (let him in) or NO. The dog: the most-liked name in the comments."""
    lines, latest = [], {}
    for c in comments:                                    # one voice per person: their last word counts
        latest[c["username"]] = c
    for n in data.get("npcs", []):
        if n.get("status") != "gate" or new_day - 1 < n.get("from_day", 0):
            continue
        yes = no = arm = 0
        asked = not n.get("shown_arm")                    # until he has shown it, "show your arm" is an answer of its own
        for c in latest.values():
            t = c.get("text") or ""
            if asked and ARM_RE.search(t):
                arm += 1; continue
            y, nn = bool(YES_RE.search(t)), bool(NO_RE.search(t))
            if y != nn:
                yes, no = yes + y, no + nn
        if asked and arm > max(yes, no):
            n["shown_arm"] = {"day": new_day, "yes": yes, "no": no, "arm": arm}
            lines.append(f"**{n['name']}:** SHOW YOUR ARM {arm}, YES {yes}, NO {no}. Reyes made him roll up the left sleeve, all the way, under the floodlight. "
                         "The arm is burned from wrist to shoulder. Old burns, healed ugly. No bite. "
                         "*\"House fire. First week. I went into the Tedeschi place after them. Didn't figure anyone needed to see that.\"* "
                         "He rolled the sleeve back down and buttoned his collar. He waits at the gate one more night. **He showed you. LET HIM IN? Comment YES or NO.**")
            continue
        if yes == no:
            lines.append(f"**{n['name']}:** YES {yes}, NO {no}. Nobody could decide. He waits at the gate another night.")
            continue
        n["status"] = "inside" if yes > no else "outside"
        n["decided"] = {"day": new_day, "yes": yes, "no": no, **({"arm": arm} if asked else {})}
        hd = (data.get("horde") or {}).get("day")
        if yes < no and hd and hd >= new_day - 1:             # turned away: on the next horde night, the northeast floodlight goes dark (see horde_night)
            n["cut_light"] = {"horde_day": hd, "lamp": 1}
        lines.append(f"**{n['name']}:** YES {yes}, NO {no}. " + ("The gate opened. He sleeps inside the fence tonight." if yes > no else
                     "The gate stays shut. He doesn't leave. He sets up across the road, where he can see the fence."))
    dog = data.get("dog")
    if dog and not dog.get("name") and new_day - 1 >= dog.get("from_day", 0):
        votes = {}
        for c in comments:
            for rx in NAME_RE:
                m = rx.search(c.get("text") or "")
                if m and m.group(1).lower() not in NOT_NAMES:
                    nm = m.group(1).strip("'-").capitalize()
                    v = votes.setdefault(nm, [0, 0]); v[0] += 1 + (c.get("likes") or 0); v[1] += 1
                    break
        if votes:
            best = max(votes.items(), key=lambda kv: (kv[1][0], kv[1][1]))
            dog["name"] = best[0]; dog["named_day"] = new_day
            others = ", ".join(f"{k} {v[0]}" for k, v in sorted(votes.items(), key=lambda kv: -kv[1][0])[:5])
            lines.append(f"**The dog:** named **{best[0]}** ({others}; a name scores its comments plus their likes).")
    return lines


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
    ballots, named = {}, {}
    owner = str(data.get("handle", "")).lstrip("@").lower()
    for c in comments:
        if c["username"].lower() == owner:                 # your own replies on the Reel don't count as votes
            continue
        raw = c.get("text") or ""
        text = " " + re.sub(r"[^A-Z0-9 ]", " ", raw.upper()) + " "
        at = {}
        for o in options:                                  # where in the comment each option is named, by word or by emoji
            word = lambda w: "(?:SHOP|STORE)" if w in ("SHOP", "STORE") else re.escape(w[:-1]) + "S?" if w.endswith("S") and len(w) > 3 else re.escape(w)
            pat = r"\s*".join(word(w) for w in o.split())   # "storage unit", "gun store", "gunshop" and "watertower" all count
            m = re.search(rf"(?<![A-Z]){pat}(?![A-Z])", text)
            spots = [m.start()] if m else []
            if o in emojis and emojis[o] in plain(raw):
                spots.append(plain(raw).index(emojis[o]))
            if spots:
                at[o] = min(spots)
        if at:
            who = c["username"].lower()
            ballots[who] = min(at, key=at.get)             # the first place named is the vote; later comments overwrite earlier ones
            named[who] = set(at)                           # "HANGAR, and send a few to the FARM" asks for two groups: one to each
    tally = Counter(ballots.values())
    for o in vote["opts"]:
        o[1] = tally.get(o[0].upper(), 0)
    top = tally.most_common()
    winner = top[0][0] if top and (len(top) == 1 or top[0][1] > top[1][1]) else None   # a tie means no winner
    support = Counter(o for picks in named.values() if len(picks) > 1 for o in picks)   # only people who asked for two places
    return winner, dict(tally), dict(support), len(ballots)


# A second group: when enough people name two places in one comment ("HANGAR, and send a few to the FARM"),
# a separate group goes to the most-asked-for other place the same day. A plain vote for the runner-up doesn't count toward it. It only goes to a run, never starts a multi-night mission, and only if the camp can spare people.
SPLIT_MIN, SPLIT_SHARE, SPLIT_SPARE = 3, .15, 10       # at least 3 people and 15% of voters asking; at least 10 fit to go out


def second_group(data, winner, support, voters, keys):
    if not winner or not support:
        return None
    need = max(SPLIT_MIN, -(-voters * SPLIT_SHARE // 1))
    for word, n in sorted(support.items(), key=lambda kv: -kv[1]):
        if word == winner or n < need:
            continue
        t = find_target(data, keys.get(word, word))
        if t and t[0] == "run":
            return {"word": word, "support": n, "need": int(need)}
    return None


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


def mission_crew(data):
    """Names of the squad working inside an active multi-night mission: they're busy, so votes and small runs send other people."""
    m = next((m for m in data.get("missions", []) if m.get("status") == "active"), None)
    return set(m.get("squad", [])) if m else set()


def pick_squad(data, kind, item, rng, busy=(), at_least=1):
    living = [s for s in data["survivors"] if s.get("status") not in ("dead", "injured", "away") and s.get("joined", 1) <= data["day"] and s["name"] not in busy]
    by_name = {s["name"]: s for s in living}
    squad = [by_name[n] for n in item.get("squad", []) if n in by_name]
    want = max(at_least, SQUAD_SIZE.get(item.get("difficulty", "medium"), 2))
    if kind == "run" and item.get("squad") == ["Sam"] and len(living) == 1:
        want = 1
    rest = [s for s in living if s not in squad]
    rng.shuffle(rest)
    rest.sort(key=lambda s: s.get("outings", 0))          # spread the work: people who've been out least go first
    roles_have = {role_of(s) for s in squad}
    for need in ("Medic", "Sharpshooter"):                 # on hard and deadly outings, try to bring a medic and a shooter
        if item.get("difficulty") in ("hard", "deadly") and need not in roles_have:
            pro = next((s for s in rest if role_of(s) == need), None)
            if pro and len(squad) < want:
                squad.append(pro); rest.remove(pro); roles_have.add(need)
    while len(squad) < want and rest:
        squad.append(rest.pop(0))
    # buddies go out together when they can: one swap, for the last person picked who isn't there for their role or their own buddy
    fixed = set(item.get("squad", []))
    for s in list(squad):
        pal = next((r for r in rest if r["name"] in s.get("buddies", [])), None)
        if not pal or any(m["name"] in s.get("buddies", []) for m in squad):
            continue
        out = next((m for m in reversed(squad) if m is not s and m["name"] not in fixed and not m.get("buddies")
                    and not (item.get("difficulty") in ("hard", "deadly") and role_of(m) in ("Medic", "Sharpshooter"))), None)
        if out:
            squad[squad.index(out)] = pal; rest.remove(pal); rest.append(out)
            break
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


def resolve_outing(data, kind, item, rng, busy=(), at_least=1):
    first = not item.get("done_day")
    diff = item.get("difficulty", "medium")
    place = place_name(kind, item)
    squad = pick_squad(data, kind, item, rng, busy, at_least)
    if not squad:
        return {"target": place, "key": item.get("dest") or item.get("poi"), "first": first, "kind": kind, "difficulty": diff, "squad": [], "results": [], "note": "Nobody was fit to go."}
    roles = {role_of(s) for s in squad}
    inj, die = RISK.get(diff, RISK["medium"])
    if "Medic" in roles:
        die *= 0.5; inj *= 0.85
    if "Sharpshooter" in roles:
        die *= 0.75; inj *= 0.75
    if "Decoy" in roles:                                      # he breaks in the middle of the street; every zombie on the block turns to watch
        inj *= 0.8
    if stock_get(data, "Ammo") < AMMO_USE.get(diff, 6):       # out of bullets: everything is more dangerous
        die *= 1.5; inj *= 1.4
    if data.get("hungry_days", 0) > 0:                        # weak from hunger
        inj *= 1.3
    if has_feat(data, "antenna"):                             # milestone: other camps radio in what's on the road
        inj *= 0.85
    if has_feat(data, "workshop"):                            # milestone: every blade sharpened, every pack mended
        die *= 0.8
    results = []
    for s in squad:
        s["outings"] = s.get("outings", 0) + 1
        roll = rng.random()
        die_s, inj_s = gear_odds(s, die, inj)
        if role_of(s) == "Decoy":                             # ...which is great for everyone except the decoy
            inj_s *= 1.25
        if any(m["name"] in s.get("buddies", []) for m in squad):      # a buddy on the same outing watches their back
            die_s *= BUDDY_RISK; inj_s *= BUDDY_RISK
        if has_feat(data, "training") and s["outings"] <= 3:           # milestone: rookies have been drilled before their first runs
            inj_s *= 0.75
        if roll < die_s and not s.get("protected"):
            s.update(status="dead", died_day=data["day"], died_at=place, cause=rng.choice(DEATHS).format(p=place))
            results.append({"name": s["name"], "ig": s.get("ig", ""), "outcome": "dead", "detail": s["cause"]})
        elif roll < die_s + inj_s:       # an injury; a protected character (Sam) who rolls death gets the worst injury instead
            lo, hi = INJURY_DAYS.get(diff, (2, 4))
            days = sick_days(data, rng.randint(lo, hi) + (2 if roll < die_s else 0))
            s.update(status="injured", injury=rng.choice(INJURIES), injured_until=data["day"] + days, injured_on=data["day"])
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
        item["squad"] = [s["name"] for s in squad if s.get("status") not in ("dead", "injured")]   # the same crew goes back in tomorrow
        item["status"] = "done" if item["days_done"] >= item["days"] else "active"
    return {"target": place, "key": item.get("dest") or item.get("poi"), "first": first, "kind": kind, "difficulty": diff, "squad": [s["name"] for s in squad], "results": results,
            "mission_status": item.get("status") if kind == "mission" else None}


def todays_outing(data, winner, rng, second=None):
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
        t = find_target(data, winner)
        if t and (not active or t[0] == "run"):       # a mission in progress doesn't stop the vote: a small group goes out too
            targets.append(t)
        t2 = find_target(data, second) if second and targets else None
        fit = [s for s in data["survivors"] if s.get("status") not in ("dead", "injured", "away") and s.get("joined", 1) <= data["day"]]
        if t2 and t2[0] == "run" and all(t2[1] is not it for _, it in targets) and len(fit) - len(mission_crew(data)) >= SPLIT_SPARE:
            targets.append(t2 + ("second",))
    if not targets and data.get("runs"):
        runs = data["runs"]
        fresh = [r for r in runs if not r.get("done_day")]
        nxt = fresh[0] if fresh else min(runs, key=lambda r: r.get("done_day", 0))
        targets.append(("run", nxt))
    out = []
    for k, it, *tag in targets:
        busy = {n for o in out for n in o["squad"]}       # nobody goes out twice in one day
        o = resolve_outing(data, k, it, rng, busy, 2 if tag else 1)     # a second group is never one person alone
        if tag:
            o["second"] = True
        out.append(o)
    return out


# ---------------------------------------------------------------- 3. healing
def heal(data, new_day):
    healed = []
    for s in data["survivors"]:
        if s.get("status") == "injured" and s.get("injured_until", 0) <= new_day:
            for k in ("status", "injury", "injured_until", "injured_on"):
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
    roles = Counter(role_of(s) for s in fit)
    lit = any(g.get("status") == "running" and not g.get("dry") for g in data.get("power", []))
    wk = h.get("week", 1) - 1                            # the horde grows with the camp: every survivor at the laundromat is more noise and more
    heads = len(fit) + .5 * (len(home) - len(fit))        # smell to follow (the injured, kept inside, count half)
    strength = (HORDE_BASE + HORDE_WEEK * wk + HORDE_PER_HEAD * heads * (1 + HORDE_HEAD_GROWTH * wk)) * rng.uniform(.9, 1.1)
    if lit:
        strength *= 1.10                                  # the light draws them in
    fence, ammo = stock_get(data, "Barricades"), stock_get(data, "Ammo")
    defense = fence * .5 + min(ammo, 60) * .5 + len(fit) * 6 + roles["Sharpshooter"] * 8 + roles["Builder"] * 5 \
        + sum(2 for s in fit if has_gear(s, "weapon")) + sum(1 for s in fit if has_gear(s, "armor")) \
        + sum(f.get("defense", 0) for f in data.get("features", []))
    intel = data.get("intel") or {}
    scouted = intel.get("defense", 0) if intel.get("horde_day") == day else 0      # scouts who watched the horde gather: the camp knows where to hold
    defense += scouted
    traps = data.get("traps") or {}
    trap_run = next((r for r in data.get("runs", []) if r.get("dest") == traps.get("needs")), None)
    trapped = traps.get("defense", 0) if traps.get("horde_day") == day and (not traps.get("needs") or (trap_run and trap_run.get("done_day"))) else 0
    defense += trapped                                                              # booby traps on the wall, built from what a run brought back
    flood = 0
    if lit:                                               # the floodlights: the light draws more of them in, but now the shooters can see
        shooters = sum(1 for s in fit if s.get("role") == "Sharpshooter" or any(g.get("icon") in ("rifle", "pistol") for g in s.get("gear", [])))
        flood = FLOOD_BASE + FLOOD_PER_SHOOTER * shooters
        defense += flood
    cutter = next((n for n in data.get("npcs", []) if n.get("status") == "outside" and (n.get("cut_light") or {}).get("horde_day") == day), None)
    cut_lost = 0
    if cutter and lit:                                    # someone cut the northeast floodlight's line from outside the fence, partway through the night
        cut_lost = max(1, round(flood / 4))               # that corner's share of the floodlight bonus is gone
        defense -= cut_lost
    margin = round(defense - strength)
    ratio = defense / max(1, strength)                    # outcomes go by how far ahead or behind the camp is, so they work at any size
    def hurt(n, why):
        pool = [s for s in fit if s.get("status") != "injured"]
        rng.shuffle(pool)
        out = []
        for s in pool[:n]:
            s.update(status="injured", injury=why, injured_until=day + 1 + sick_days(data, rng.randint(2, 3)))
            out.append(f"{s['name']} ({why}, out until Day {s['injured_until']})")
        return out
    def spend(name, amt):
        r = stock_row(data, name)
        if r:
            r[1] = max(0, r[1] - amt)
    hurt_list, dead = [], []
    if ratio >= 1.08:
        outcome, fence_hit, ammo_hit = "held", 15, 20
    elif ratio >= 1.0:
        outcome, fence_hit, ammo_hit = "barely held", 25, 30
        if rng.random() < .5:
            hurt_list = hurt(1, "clawed at the fence")
    elif ratio >= .88:
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
    if cut_lost:                                          # the dark corner costs the fence and someone on watch, whatever else happens
        fence_hit += 10
        hurt_list += hurt(1, "caught in the dark at the northeast corner")
        lamp = cutter["cut_light"].get("lamp", 1)
        data["lamps_out"] = [l for l in data.get("lamps_out", []) if l.get("lamp") != lamp] + [{"lamp": lamp, "since": day, "until": day + 3}]
        cutter["cut_light"]["done"] = True
    spend("Barricades", max(0, fence_hit)); spend("Ammo", ammo_hit)
    if stock_get(data, "Barricades") < 10:
        stock_row(data, "Barricades")[1] = 10
    res = {"day": day, "week": h.get("week", 1), "outcome": outcome, "strength": round(strength), "defense": round(defense),
           "defenders": [s["name"] for s in fit], "hurt": hurt_list, "dead": dead, "lit": lit, "flood": flood, "intel": scouted, "intel_by": intel.get("by", []) if scouted else [], "traps": trapped, "traps_note": traps.get("note", "") if trapped else "", "cut": cut_lost,
           "fence": stock_get(data, "Barricades"), "ammo": stock_get(data, "Ammo")}
    if twins_here(data, day):        # the twins walk at the front of every horde: the story's, not the dice's. Same night, same odds, and they can't die.
        res["led"] = True
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
    busy = mission_crew(data)
    fit = [s for s in data["survivors"] if s.get("status") not in ("dead", "injured", "away") and s.get("joined", 1) <= new_day and s["name"] not in busy]
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


# ---------------------------------------------------------------- 3d2. the weather, rolled once a day so every visitor sees the same sky
# data.json "weather": {"day": N, "kind": clear | wind | fog | rain | storm | snow}. Rain fills the barrels. Set "season": "winter" in
# data.json to turn rain into snow; set "weather_next": "storm" to choose tomorrow's weather by hand (for a story beat).
WEATHER = [("clear", 50), ("wind", 14), ("fog", 14), ("rain", 16), ("storm", 6)]
def roll_weather(data, new_day, rng):
    kind = data.pop("weather_next", None) or rng.choices([k for k, _ in WEATHER], [w for _, w in WEATHER])[0]
    if data.get("season") == "winter" and kind in ("rain", "storm"):
        kind = "snow"
    data["weather"] = {"day": new_day, "kind": kind}
    if kind in ("rain", "storm"):
        amt = 4 if kind == "rain" else 6
        data.setdefault("camp_bonus", []).append({"item": "Water", "amt": amt, "why": "rain in the barrels",
            "note": ("It rained all night." if kind == "rain" else "A storm came through in the night.") + f" The barrels caught {amt} rations of water."})
    return kind


# ---------------------------------------------------------------- 3e. follower milestones that change the world
# data.json milestones: [followers, text, effect, what it does]. Reaching one builds it for real.
def twins_here(data, day):
    """Scott and Ryan Tedeschi, Oakhaven's first dead (data.json "twins"): in the story from their reveal day on."""
    t = data.get("twins") or {}
    return bool(t) and day >= t.get("reveal_day", 10 ** 6)


def has_feat(data, fid):
    return any(f.get("id") == fid for f in data.get("features", []))


def sick_days(data, days):
    """How long an injury keeps someone out. The infirmary (75 followers) sends everyone back a day sooner."""
    return max(1, days - 1) if has_feat(data, "infirmary") else days


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
        elif fx == "antenna":          # other camps call in what they see: fewer injuries on every outing
            feats.append({"id": "antenna", "name": "Radio antenna", "day": new_day})
        elif fx == "infirmary":        # injuries heal a day sooner (sick_days)
            feats.append({"id": "infirmary", "name": "Infirmary", "day": new_day})
        elif fx == "workshop":         # sharper blades, mended packs: fewer deaths on every outing
            feats.append({"id": "workshop", "name": "Workbench", "day": new_day})
        elif fx == "training":         # the veterans drill the newcomers: rookies get hurt less
            feats.append({"id": "training", "name": "Morning drills", "day": new_day})
        elif fx == "kitchen":          # one long table, nothing wasted
            feats.append({"id": "kitchen", "name": "Camp kitchen", "day": new_day})
            data.setdefault("income", []).append({"item": "Food", "amt": 3, "why": "the camp kitchen"})
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
  "with": if they say they're joining with, or were invited by, someone already in the game ("with @name", "invited by @name",
          "@name sent me"), that username without the @; otherwise ""
Crude, sexual or joke answers still get in: pick the closest role and write a bio that roasts it with a wink
(e.g. "Gary ran the adult shop on Main. The town pervert, and somehow still alive.") without getting graphic.
Skip anything that is not a join request, and anything hateful, harassing or aimed at a real person.
Today's vote options are {votes}. A comment that only names one of them is a vote, not a join request,
even if the word could pass for a name or a job ("RANGER" is a vote for the ranger station, not a ranger joining).
Reply with only a JSON array.

Comments:
"""


VOTE_FILLER = {"THE", "STATION", "VOTE", "GO", "TO", "PLEASE", "PICK", "MY", "I", "SAY", "FOR", "AND", "ALSO", "TOO", "THEN", "SEND", "SPLIT", "UP",
               "SECOND", "GROUP", "TEAM", "SQUAD", "SOME", "A", "FEW", "PEOPLE", "BOTH", "OR", "OTHER", "ANOTHER", "TO", "THE"}


def is_just_a_vote(text, votes):
    """'Ranger', 'ranger station 🌲', 'GAS!!' and emoji-only comments are votes or chatter, never join requests."""
    words = re.sub(r"[^A-Z ]", " ", str(text).upper()).split()
    return not words or set(words) <= set(votes) | VOTE_FILLER


def read_joins(comments, skip, votes=()):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log("No ANTHROPIC_API_KEY set: skipping new survivors.")
        return []
    import anthropic
    client = anthropic.Anthropic()
    by_user = {}
    for c in comments:
        u = c["username"]
        if u.lower() in skip or is_just_a_vote(c.get("text", ""), votes):
            continue
        by_user.setdefault(u, []).append(c.get("text", "").replace("\n", " ")[:300])
    items, out = list(by_user.items()), []
    for i in range(0, len(items), 40):
        batch = "\n".join(f"@{u}: {' / '.join(t)}" for u, t in items[i:i + 40])
        msg = client.messages.create(model=MODEL, max_tokens=4000,
                                     messages=[{"role": "user", "content": PROMPT.format(roles=ROLES, votes=", ".join(votes) or "none") + batch}])
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
        w = str(p.get("with") or "").lstrip("@").strip().lower()          # joined with a friend who's already here
        host = next((h for h in data["survivors"] if w and h.get("status") != "dead" and w in (h.get("ig", "").lower(), h["name"].lower())), None)
        if host:
            s["buddies"] = [host["name"]]; s["invited_by"] = host["name"]
            host.setdefault("buddies", []).append(name)
        data["survivors"].append(s)
        taken.add(name.lower()); living_ig.add(ig.lower()); added.append(s)
    data["waitlist"] = wait
    solo, paired = [s for s in added if not s.get("invited_by")], [s for s in added if s.get("invited_by")]
    for item, amt in PACK.items():               # everyone who moves in brings a pack, so growth pays for part of itself
        if solo:
            data.setdefault("camp_bonus", []).append({"item": item, "amt": amt * len(solo), "why": "new survivors' packs"})
    for i, (item, amt) in enumerate(BUDDY_PACK.items()):
        if paired:
            note = " ".join(f"{s['name']} moved in with {s['invited_by']}: buddies now, and a full pack between them." for s in paired) if i == 0 else None
            data.setdefault("camp_bonus", []).append({"item": item, "amt": amt * len(paired), "why": "invited friends' full packs", **({"note": note} if note else {})})
    return added


# ---------------------------------------------------------------- 5b. the stockpile
# data.json "stock" rows are [name, amount, capacity, unit]. Food and water are rations: one per survivor per day.
# What each place brings home on a first visit (half that when it's been picked over), give or take a quarter.
# Food and water from runs grow with the camp: survivors / 15, at least 1x, at most 2.5x (reached at about 37 people).
# Past that, runs alone fall behind again and the camp needs lasting sources (the water tower, harvests, cattle, the kitchen).
# Ammo, fuel, scrap and medicine never scale; repeat visits still give half.
SCALED_LOOT, HAUL_PER, HAUL_CAP = ("Food", "Water"), 15, 2.5


def haul_scale(people):
    return max(1.0, min(HAUL_CAP, people / HAUL_PER))


LOOT = {"pharmacy": {"Medicine": 6, "Food": 2}, "diner": {"Food": 12, "Water": 6}, "gas": {"Fuel": 20, "Water": 8},
        "market": {"Food": 18, "Water": 10}, "hardware": {"Scrap": 25}, "gunshop": {"Ammo": 40}, "port": {"Food": 30, "Scrap": 10},
        "ranger": {"Ammo": 15, "Medicine": 4, "Food": 4}, "hangar": {"Fuel": 30, "Scrap": 10}, "firestation": {"Medicine": 6, "Scrap": 15, "Water": 10},
        "maple": {"Food": 8, "Ammo": 4}, "storage": {"Scrap": 15, "Food": 4}, "mall": {"Scrap": 15, "Water": 10, "Food": 6},
        "freight": {"Food": 25}, "farm": {"Food": 15, "Water": 6}, "fair": {"Food": 10, "Scrap": 8}, "harbor": {"Water": 10, "Food": 6},
        "hunter": {"Ammo": 12, "Food": 8}, "cold": {"Food": 30}, "greenhouse": {"Food": 8, "Water": 4}, "airfreight": {"Medicine": 15},
        "checkpoint": {"Ammo": 60, "Food": 6, "Medicine": 4}, "surplus": {"Water": 15, "Food": 6, "Medicine": 2},
        "funhouse": {"Scrap": 12}, "arcade": {"Scrap": 10}, "showbarn": {"Food": 12}}
AMMO_USE = {"easy": 2, "medium": 6, "hard": 15, "deadly": 30}     # rounds a squad burns on an outing
# Horde strength: a base, more every week, and more for every survivor at the laundromat (that share also grows each week).
# Tuned so a normal camp usually holds or barely holds, a neglected one (low fence, little ammo, people hurt) can be breached.
HORDE_BASE, HORDE_WEEK, HORDE_PER_HEAD, HORDE_HEAD_GROWTH = 40, 10, 7.5, .04
FENCE_WEAR = 4                                                   # barricade % the dead tear down each night
FLOOD_WEAR = 2                                                   # ...less while the yard floodlight is on: the guards see them coming and clear the fence
FLOOD_BASE, FLOOD_PER_SHOOTER = 10, 4                            # horde-night defense from the floodlights: a flat bonus, plus more for every shooter


def stock_row(data, name):
    return next((r for r in data.get("stock", []) if r[0] == name), None)


def stock_get(data, name):
    r = stock_row(data, name)
    return r[1] if r else 0


GUN_FIRST = ["Gunsmith", "Guard", "Scout", "Sharpshooter"]   # who the camp trusts with a gun first


def hand_out(data, gear, squad, present):
    """Give found weapons to people who have none: guns to the gunsmith, guards and scouts first, blades and axes to the squad
    that found them first. Returns [(name, item)]."""
    given = []
    for g in gear:
        unarmed = [s for s in present if not has_gear(s, "weapon") and s.get("status") != "dead"]
        if not unarmed:
            break
        gun = g.get("icon") in ("rifle", "pistol")
        def rank(s):
            role = s.get("role", "")
            return ((GUN_FIRST.index(role) if role in GUN_FIRST else len(GUN_FIRST)) if gun else 0,
                    0 if s["name"] in squad else 1, present.index(s))
        who = min(unarmed, key=rank)
        who.setdefault("gear", []).insert(0, dict(g))
        given.append((who["name"], g))
    return given


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
                mult = haul_scale(len(present)) if item in SCALED_LOOT else 1      # a bigger camp sends bigger squads with more packs
                add(item, round(amt * mult * (1 if o.get("first") else .5) * rng.uniform(.75, 1.25)), o["target"])
            run = next((r for r in data.get("runs", []) if r["dest"] == o.get("key")), {})
            haul = run.get("haul")
            if haul and o.get("first") and not run.get("haul_taken"):      # a one-time find set by hand in data.json (a locked gun locker...)
                run["haul_taken"] = new_day
                for item, amt in haul.get("stock", {}).items():
                    add(item, amt, haul.get("why", o["target"]))
                if haul.get("note"):
                    notes.append(haul["note"])
                given = hand_out(data, haul.get("gear", []), [r["name"] for r in o["results"] if r["outcome"] != "dead"], present)
                if given:
                    notes.append("Handed out: " + ", ".join(f"{n} gets the {g['name'].lower()}" for n, g in given) + ".")

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
            crew = [r["name"] for r in o["results"] if r["outcome"] != "dead"]
            weapons = [g for g in m.get("gear", []) if g.get("kind") == "weapon"]
            given = hand_out(data, weapons, crew, present) if weapons else []
            for g in (g for g in m.get("gear", []) if g.get("kind") != "weapon"):      # armor: the squad first, then whoever has none
                bare = [s for s in present if s.get("status") != "dead" and not has_gear(s, g["kind"])]
                if not bare:
                    break
                who = min(bare, key=lambda s: (0 if s["name"] in crew else 1, present.index(s)))
                who.setdefault("gear", []).append(dict(g)); given.append((who["name"], g))
            if given:
                notes.append("Handed out: " + ", ".join(f"{n} gets the {g['name'].lower()}" for n, g in given) + ".")
            for p in m.get("recruit", []):           # someone found alive inside comes home with the squad
                if not any(s["name"] == p["name"] for s in data["survivors"]):
                    data["survivors"].append({**p, "joined": new_day})
                    notes.append(f"{p['name']} came home with the squad: {p.get('bio', '')}".strip())
            if m.get("broadcast"):
                data["broadcast"] = {"day": new_day, **m["broadcast"]}
            have = data.setdefault("zombie_types", ["walker"])
            for z in m.get("unlock_zombies", []):
                if z not in have:
                    have.append(z)
                    notes.append(m.get("unlock_note") or f"Something new out there: {z}s.")
    # camp jobs: the people who stayed home today work their jobs
    out_today = {n for o in outings for n in o.get("squad", [])} | mission_crew(data)
    home = [s for s in present if s.get("status") not in ("injured", "away") and s["name"] not in out_today]
    jobs = {}
    for s in home:
        job = CAMP_JOBS.get(role_of(s))
        if job:
            jobs.setdefault(job, []).append(s["name"])
    done = []
    for (item, amt, why), names in jobs.items():
        got = add(item, amt * len(names), why)
        if got:
            done.append(f"{' and '.join(names) if len(names) < 3 else f'{len(names)} of them'} ({why}): +{got} {item.lower()}")
    chefs = [s["name"] for s in home if role_of(s) in ("Chef", "Cook")]
    if chefs:
        got = add("Food", math.ceil(len(present) * CHEF_STRETCH), f"{chefs[0]}'s cooking")
        if got:
            done.append(f"{chefs[0]} stretched every meal: +{got} food")
    if done:
        notes.append("Camp jobs: " + "; ".join(done) + ".")

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
        if s.get("status") == "injured" and s.get("injured_until", 0) > new_day and s.get("injured_on") != data["day"] and stock_get(data, "Medicine") >= 1:   # starts the night after
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
    lit_now = any(g.get("status") == "running" and not g.get("dry") for g in data.get("power", []))
    add("Barricades", -(FENCE_WEAR - FLOOD_WEAR if lit_now else FENCE_WEAR), "the dead at the fence" + (" (the floodlight keeps them back)" if lit_now else ""))
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
def power_progress(data, outings, new_day, ledger=None):
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
            if not hit and n.get("fuel") and stock_get(data, "Fuel") >= n["fuel"]:    # "bring fuel" counts as done if the stockpile already has it
                hit = True
                stock_row(data, "Fuel")[1] -= n["fuel"]
                if ledger is not None:
                    ledger.setdefault("Fuel", []).append((-n["fuel"], f"{g['name']}'s first tank, from the stockpile"))
                data.setdefault("stock_change", {})["Fuel"] = data.get("stock_change", {}).get("Fuel", 0) - n["fuel"]
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
LABELS = {"watertower": "WATER TOWER", "gunshop": "GUN SHOP", "port": "PIER", "firestation": "FIRE STATION", "cold": "COLD STORAGE", "airfreight": "AIR FREIGHT",
          "showbarn": "SHOW BARN", "hunter": "CABIN", "harbor": "HARBOR", "storage": "STORAGE UNITS", "surplus": "SURPLUS"}
EMOJI = {"pharmacy": "💊", "diner": "🍳", "gas": "⛽", "market": "🛒", "hardware": "🔨", "gunshop": "🔫", "port": "⚓", "ranger": "🌲",
         "hangar": "🛩", "firestation": "🚒", "maple": "🏘", "storage": "📦", "mall": "🛍", "freight": "🚂", "farm": "🌾", "fair": "🎡",
         "harbor": "⛵", "hunter": "🏕", "cold": "🧊", "greenhouse": "🌱", "airfreight": "🛫", "checkpoint": "🪖", "surplus": "🎒", "windmill": "💧", "watertower": "🚰", "harvest": "🌽", "cattle": "🐄", "fortify": "🧱",
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


def vote_options(data, new_day, rng, missions_ok=True):
    healthy = [s for s in data["survivors"] if s.get("status") not in ("dead", "injured", "away") and s.get("joined", 1) <= new_day]
    n = len(healthy)
    ok = lambda diff: n >= UNLOCK.get(diff, 2)
    runs = [r for r in data.get("runs", []) if ok(r.get("difficulty", "easy"))]
    fresh = [r for r in runs if not r.get("done_day")]
    again = sorted([r for r in runs if r.get("done_day")], key=lambda r: r["done_day"])   # longest since the last visit first
    pool = [("run", r) for r in (fresh[:5] or again[:5])]
    picks = rng.sample(pool, min(3, len(pool)))
    missions = [m for m in data.get("missions", []) if m.get("poi") and m.get("status") != "done" and n >= SQUAD_SIZE.get(m.get("difficulty", "hard"), 4)
                and new_day >= m.get("from_day", 0)]          # "from_day": keep a mission off the ballot until a set day
    if missions_ok and missions and picks and rng.random() < .5:
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
    wt = next((m for m in missions if m.get("poi") == "watertower"), None)
    if wt and missions_ok and days_left(data, "Water") < 2 and all(it is not wt for _, it in picks):    # out of water: tapping the tower is always on the ballot
        picks = (picks[:2] if len(picks) >= 3 else picks) + [("mission", wt)]
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
    left = active.get("days", 3) - active.get("days_done", 0) if active else 0
    inside = f"the squad is still inside {place_name('mission', active)} ({left} more night{'s' if left != 1 else ''})" if active else ""
    ballot = data.get("ballot") if (data.get("ballot") or {}).get("day") == new_day else None
    opts = ballot_options(data, ballot) if ballot else vote_options(data, new_day, rng, missions_ok=not active)
    if active:
        opts = [o for o in opts if o["kind"] == "run"]          # while the squad is inside, the vote sends a small group on a run
    if len(opts) < 2:
        if active:
            return {"q": f"Day {new_day}. No vote today: {inside}.", "opts": [], "how": "Comment your name and your job to move in."}
        return {"q": f"Day {new_day}. Nowhere left to vote on tonight.", "opts": [], "how": "Comment your name and your job to move in."}
    q, desc = (f"Day {new_day}. While {inside}, where does a small group go?" if active else f"Day {new_day}. Where does the squad go next?"), {}
    if active:
        recap += f"\nThe main squad ({', '.join(active.get('squad', []))}) is still inside {place_name('mission', active)}: this vote sends a separate small group on a run."
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
            "how": f"Comment {', '.join(words[:-1])} or {words[-1]} (or its emoji) on the Day {new_day} Reel. One vote per account, your last comment counts. Name a second place too, and if enough of you ask for it, a separate group goes there as well."}


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
    winner, tally, support, voters = count_vote(data, comments)
    tiebreak = None
    if not winner and tally:                             # a tie: Sam's call if one is set in data.json vote "tiebreak", otherwise a coin flip
        top = max(tally.values())
        tied = sorted(k for k, v in tally.items() if v == top)
        call = str((data.get("vote") or {}).get("tiebreak", "")).upper()
        winner = call if call in tied else rng.choice(tied)
        tiebreak = f"{' / '.join(tied)} tied. " + (f"Sam broke the tie: {winner}." if call in tied else f"A coin flip picked {winner}.")
    keys = {o[0].upper(): o[3] for o in (data.get("vote") or {}).get("opts", []) if len(o) > 3}
    split = second_group(data, winner, support, voters, keys)
    called = str((data.get("vote") or {}).get("second", "")).upper()   # Sam can send a second group himself: data.json vote "second"
    if not split and called and winner and called != winner:
        split = {"word": called, "support": support.get(called, 0), "need": 0, "called": True}
    outings = todays_outing(data, keys.get(winner, winner), rng, keys.get(split["word"], split["word"]) if split else None)
    if split and not any(o.get("second") for o in outings):
        split = None                                       # not enough people to spare today
    new_day = day + 1
    trips = scout_trips(data, new_day, rng, outings)
    roll_weather(data, new_day, random.Random(f"oakhaven-weather-{new_day}-{os.environ.get('OAKHAVEN_SEED', '')}"))
    ledger, stock_notes = keep_stockpile(data, outings, rng, new_day)
    horde = horde_night(data, rng, day)
    healed = heal(data, new_day)
    returned = come_home(data, new_day)
    story = trips + run_schedule(data, new_day, rng)

    living_ig = {s.get("ig", "").lower() for s in data["survivors"] if s.get("status") != "dead"}
    living_ig |= {str(p.get("ig", "")).lower() for p in data.get("waitlist", [])}
    try:
        parsed = read_joins(comments, living_ig, list(keys)) if comments else []
        if DRY and not comments:
            parsed_test = read_joins([{"username": "test_jake", "text": "Jake here, I'll be the mechanic. Scared of birds."},
                                      {"username": "test_vote", "text": "DINER!!"}], set())
            log(f"Claude self-test (not saved): {parsed_test}")
    except Exception as e:
        log(f"!! Reading join comments failed: {e}")
        problems.append(f"Claude: {e}")
        parsed = []
    added = add_survivors(data, parsed)
    power_news = power_progress(data, outings, new_day, ledger)

    if ig:
        data["followers"] = ig["followers"]
    unlocked = milestone_unlocks(data, new_day)
    undead = update_undead(data, outings, len(day_lines), horde, rng)
    question_lines = story_questions(data, comments, new_day)
    if data.get("lamps_out"):                             # a cut floodlight stays dark until it's spliced (the map reads this too)
        data["lamps_out"] = [l for l in data["lamps_out"] if l.get("until", 0) > new_day] or None
        if data["lamps_out"] is None: data.pop("lamps_out")
    data["day"] = new_day
    entry = {"day": day, "vote": {"question": (data.get("vote") or {}).get("q"), "results": tally, "winner": winner, "tiebreak": tiebreak,
                                  "second": {"place": split["word"], "asked": split["support"]} if split else None,
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
    lines += question_lines
    if split:
        lines.append((f"**Second group:** {tally[split['word']]} of you voted {split['word']}, so Sam sent a small group there as well." if tally.get(split['word']) else f"**Second group:** Sam sent a small group to {split['word']} as well.") if split.get("called") else
                     f"**Second group:** {split['support']} of {voters} voters asked for {split['word']} as well, so a separate group went there too.")
    for o in outings:
        lines.append(f"**{'Second group run' if o.get('second') else o['kind'].title()}: {o['target']}** ({o['difficulty']}), squad: {', '.join(o['squad']) or 'nobody'}"
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
                     + (" — the twins at the front" if horde.get("led") else "")
                     + (f" (the floodlight drew more in, but it gave the shooters +{horde.get('flood', 0)} defense)" if horde["lit"] else "")
                     + (f" ({' and '.join(horde['intel_by'])}'s scouting: +{horde['intel']} defense, the camp knew which side to hold)" if horde.get("intel") else "")
                     + (f" ({horde['traps_note']}: +{horde['traps']} defense)" if horde.get("traps") else "") + f". Defenders: {', '.join(horde['defenders']) or 'nobody'}.")
        if horde.get("cut"):
            lines.append(f"- Partway through the night, the **northeast floodlight went dark** (-{horde['cut']} defense, and the fence took more at that corner). "
                         "In the morning Frost found the power line cut clean on the outside of the fence. Not chewed. Cut. Nobody saw who did it. "
                         "Frost says he can splice it in two days.")
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
    lines.append(f"**New survivors ({len(added)}):** " + (", ".join(f"{s['name']} the {s['role']} (@{s['ig']})" for s in added) or "none")
                 + (" (each brought a pack: " + ", ".join(f"+{v} {k.lower()}" for k, v in PACK.items()) + ")" if added else ""))
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
