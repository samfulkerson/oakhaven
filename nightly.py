"""Oakhaven nightly update.

Runs once a night (GitHub Actions does it for you) and moves the world forward exactly one day:
  1. counts the vote on the newest Reel (one vote per account, their latest comment counts)
  2. sends out today's run or mission and rolls for injuries and deaths
  3. heals survivors whose injuries are over
  4. adds new survivors from join comments (Claude reads them), up to a daily cap
  5. updates the follower count, advances the day, and writes data.json plus report.md (a recap to narrate from)

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
    ballots = {}
    for c in comments:
        text = " " + re.sub(r"[^A-Z0-9 ]", " ", c.get("text", "").upper()) + " "
        pick = next((o for o in options if f" {o} " in text), None)
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
    diff = item.get("difficulty", "medium")
    place = place_name(kind, item)
    squad = pick_squad(data, kind, item, rng)
    if not squad:
        return {"target": place, "kind": kind, "difficulty": diff, "squad": [], "results": [], "note": "Nobody was fit to go."}
    roles = {s["role"] for s in squad}
    inj, die = RISK.get(diff, RISK["medium"])
    if "Medic" in roles:
        die *= 0.5; inj *= 0.85
    if "Sharpshooter" in roles:
        die *= 0.75; inj *= 0.75
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
    return {"target": place, "kind": kind, "difficulty": diff, "squad": [s["name"] for s in squad], "results": results,
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
  "name": the character name they asked for (short, cleaned up, nothing offensive)
  "role": the closest match from {roles}
  "bio": one short, fun third-person sentence built from what they said
Skip anything that is not a join request, and anything hateful, sexual or harassing.
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
        text = msg.content[0].text
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


# ---------------------------------------------------------------- main
def main():
    data = json.load(open(DATA_FILE, encoding="utf-8"))
    day = data["day"]
    rng = random.Random(f"oakhaven-{day}-{os.environ.get('OAKHAVEN_SEED', '')}")
    ig = fetch_instagram()
    comments = ig["comments"] if ig else []

    winner, tally = count_vote(data, comments)
    outings = todays_outing(data, winner, rng)
    new_day = day + 1
    healed = heal(data, new_day)

    living_ig = {s.get("ig", "").lower() for s in data["survivors"] if s.get("status") != "dead"}
    living_ig |= {str(p.get("ig", "")).lower() for p in data.get("waitlist", [])}
    added = add_survivors(data, read_joins(comments, living_ig) if comments else [])

    if ig:
        data["followers"] = ig["followers"]
    data["day"] = new_day
    entry = {"day": day, "vote": {"question": (data.get("vote") or {}).get("q"), "results": tally, "winner": winner,
                                  "reel": ig["reel"]["permalink"] if ig and ig.get("reel") else None},
             "outings": outings, "healed": healed, "joined": [s["name"] for s in added], "waiting": len(data.get("waitlist", []))}
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
        if all(r["outcome"] == "ok" for r in o["results"]):
            lines.append("- Everyone came back in one piece.")
    if healed:
        lines.append(f"**Back on their feet:** {', '.join(healed)}")
    lines.append(f"**New survivors ({len(added)}):** " + (", ".join(f"{s['name']} the {s['role']} (@{s['ig']})" for s in added) or "none"))
    if data.get("waitlist"):
        lines.append(f"**Still waiting to get in:** {len(data['waitlist'])}")
    lines.append(f"**Followers:** {data.get('followers')}  |  **Tomorrow is Day {new_day}**")
    report = "\n".join(lines) + "\n"
    log("\n" + report)

    if DRY:
        log("DRY_RUN: nothing written.")
        return
    json.dump(data, open(DATA_FILE, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    open(REPORT_FILE, "w", encoding="utf-8").write(report)


if __name__ == "__main__":
    main()
