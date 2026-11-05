# Oakhaven

A dead city, one survivor, and every Instagram follower moves in.

- `index.html` is the game. It reads `data.json` when the page opens.
- `data.json` is the whole state of the world: day, followers, survivors, the vote, runs, missions and generators.
- `nightly.py` moves the world forward one day, every night, and writes `report.md`, a recap to narrate the next Reel from.
- `.github/workflows/nightly.yml` runs `nightly.py` on a schedule and publishes the site. You don't need your computer on.

## One-time setup (about 20 minutes)

### 1. Put the files on GitHub
1. On github.com, click **New repository**. Name it `oakhaven`, set it to **Public** (free GitHub Pages needs a public repo), and create it.
2. On the new repo's page, click **uploading an existing file**. Drag in everything from this folder **except** the `.github` folder, then click **Commit changes**.
3. GitHub's uploader skips folders that start with a dot, so add the workflow by hand: click **Add file > Create new file**, type `.github/workflows/nightly.yml` as the name, paste in the contents of that file, and commit.

### 2. Turn on the website
1. Go to **Settings > Pages**. Under **Build and deployment > Source**, pick **GitHub Actions**.
2. Go to **Settings > Actions > General > Workflow permissions**. Pick **Read and write permissions** and save.
3. Go to the **Actions** tab, click **Oakhaven nightly**, then **Run workflow** with **Dry run** checked. When it goes green, the site is live at `https://<your-username>.github.io/oakhaven/`.

### 3. Add your keys (when you're ready to go live)
Under **Settings > Secrets and variables > Actions > New repository secret**, add:

| Secret | Where to get it |
|---|---|
| `IG_TOKEN` | The access token from your Meta app: **Instagram > API setup with Instagram login > Generate token**. It lasts about 60 days, so set a reminder to generate a new one and replace the secret. |
| `ANTHROPIC_API_KEY` | console.anthropic.com > API keys. Reading join comments costs pennies a day. |

Until those are added, the nightly run still works: it sends out the day's run and advances the day, but skips the vote count and new survivors.

## What happens every night
At 11:07 pm Central (12:07 am in summer; GitHub sometimes runs a few minutes late):

1. **Vote.** Counts the vote words from `data.json` > `vote` > `opts` in the comments on your newest Reel. Each account gets one vote, and their last comment counts. A tie means no winner.
2. **The day's outing.** It picks what to send out in this order:
   - anything you listed in `outings` (for example `"outings": [{"target": "hospital"}]`)
   - a multi-night mission already underway
   - the vote winner, if it names a run or mission (DINER, PHARMACY, HOSPITAL…)
   - otherwise the next run on the list
3. **Risk.** Everyone on the outing rolls for injury or death based on its difficulty:

   | Difficulty | Injured | Killed | Squad size | Nights for a mission |
   |---|---|---|---|---|
   | Easy | 6% | 0.5% | 1 | 2 |
   | Medium | 12% | 2% | 3 | 3 |
   | Hard | 20% | 5% | 4 | 5 |
   | Deadly | 30% | 12% | 6 | 7 |

   - A **Medic** on the squad halves the death chance.
   - A **Sharpshooter** cuts both chances by a quarter.
   - Injured survivors sit out for a few days.
   - **Sam is protected**: a roll that would kill him leaves him badly hurt instead.
   - The fallen get a grave in the churchyard, and their name is crossed out on the site. The same account can comment again to join as a new character.
4. **Healing.** Anyone whose injury is over is back on their feet.
5. **New survivors.** Claude reads the comments and turns real join requests into survivors with a name, job and bio. They move in the next day. At most 25 a day get in, and the rest wait in line, so a viral day doesn't flood the town.
6. **Day + 1.** It updates the follower count, saves `data.json`, writes `report.md` and republishes the site.

The rolls use the day number as a seed, so re-running the same night gives the same result.

## Your daily routine (about 10 minutes)
1. Open `report.md` on GitHub to see what happened last night: the vote, who got hurt or died, and who moved in.
2. Set tomorrow's vote: edit `data.json` on GitHub (the pencil icon), change `vote` > `q`, `opts` and `how`, and commit. The site updates in a minute or two. Or paste `report.md` to Claude and ask for the next vote, the Reel script and the caption.
3. Post the Reel.

## Handy settings in `nightly.py`
- `MAX_NEW_PER_DAY`: the daily cap on new survivors (25)
- `RISK`, `SQUAD_SIZE`, `MISSION_DAYS`: tune how dangerous things are
- `GRAPH`: the Instagram Graph API address and version (v25.0). Meta retires old versions about every two years, so bump it if Meta says to.
- Run it yourself without changing anything: `DRY_RUN=1 python nightly.py`
