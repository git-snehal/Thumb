# Anime Thumb Bot

Telegram bot that turns an anime title into a streaming-site style banner. Switch between
13 layouts with inline buttons (the same message updates in place), and let every user add their own
brand text or logo, pick a corner, and choose a font.

```
/start                      animated start message
/poster Solo Leveling       banner + template buttons
/poster id:163134           by AniList id
/poster https://anilist.co/anime/163134
/settings                   brand text, logo (PNG), their corners, and font
/help   /version   /emojiid   /cancel
```

## Features

* **TMDB as a backup source:** if AniList is down, errors, or simply doesn't have a title, `/poster` searches TMDB
  instead and builds the poster from TMDB's data (title, synopsis, genres, score, studio, cast, poster and backdrops;
  the accent colour is taken from the poster). Under AniList results a **Not here? Search TMDB** button runs the same
  search on TMDB, and you can paste a themoviedb.org link or `tmdb:tv/1399` / `tmdb:movie/603`. Needs `TMDB_API_KEY`.
  AniList is skipped for 45 seconds after it fails (so nobody waits on a dead service), and a title already opened
  keeps working from its last good copy during an outage.
* **Preview all designs**: one numbered picture of the same anime in every design; tap a number and that picture
  turns into the banner.
* **HD file**: a sharper 2560x1440 PNG (built from TMDB's full-size art when available), next to the normal file.
* **Edit text** (Customize): fix the synopsis, genres, season line and episode label (AniList is often wrong for
  sequels). Applies to every design; per anime and per person.
* **Special Design colours from your character**: one tap pulls a 3-colour gradient from the character PNG.
* **Genres on every design** (Template 1, Posters 2 to 10 and the Special Design all show them).
* **13 templates**: Template 1, Poster 1 (v2 dark / v3 mirrored), Posters 2 to 10, and the **Special Design**.
  Poster 9 is a cinematic hero (huge title, production line, Watch Now / Watch List pills); Poster 10 is a
  showcase (accent panel, sliced art, glass description box, genre line, All Episodes / Download).
* **HD background art**: Template 1 and Posters 2 to 10 can use a wide, high-definition image instead of AniList's
  small cover. Priority: the person's own uploaded image, then a TMDB backdrop (optional, needs a free key), then the
  AniList cover. Customize -> Background image lets people upload their own, flip through TMDB images (Next image), or
  switch to AniList's own art (AniList button: cover, then banner). Poster 9
  becomes a true full-bleed hero when the image is wide.
* **Special Design**: a poster with *your* character in the middle (vertical title, four side boxes, ghost
  watermark, Next box, joined Download/More Info, four icons). It ships with built-in defaults from `assets/special/`
  (`boxes.png`, a faded `watermark.png`, and a small `credit.png`). Someone who sets their own brand text gets
  their text instead (its first word as the watermark, the full text as the credit); Remove brand hides them.
  The built-in watermark and credit are fixed: even "Remove brand" doesn't hide them (set
  `SPECIAL_DEFAULTS = False` to turn them off). A logo uses its own corner and the title makes room for it.
  The vertical title stays on **one line** when the whole name fits at a good size ("ONE PIECE"); only longer names
  split into a small column plus a big last word. Swap the PNGs in `assets/special/` (white on transparent) to rebrand.
  * **Type your own title** (Title button): up to 3 lines in ONE message (Shift+Enter for a new line on desktop), e.g.
    `Chitose Is in the Ramune Bottle` / `2nd Cour`. Line 1 is the big one and sits in the **right-hand column**, the
    upper line when you tilt your head to read it; line 2 sits to its left (the Swap button flips this). **Every
    line has its own size (➖➕) and position (⬆️⬇️)**, plus a gap between lines. A line can't be longer than the poster is
    tall, so a long first line stays modest (growing it past the edge cuts it off); a shorter first line goes bigger
    (try `Chitose` / `Is in the Ramune Bottle 2nd Cour`). Retyping keeps your tuned sizes; Auto resets everything.
  * **Colors**: presets, Auto from the cover, or your own **1 to 4 hex colors** (top to bottom). With 3 or 4 colors the
    background fades through each one; light colors are darkened a little so the white text stays readable.
  * The big OD3N **watermark spans the full width**, the studio and rating line up with the Download box, and the two
    **Next cards show two different pictures** (the next TMDB scenes, or AniList's pictures). Choose with
    Customize -> Next-card images (Next images / AniList). Tapping it asks for a character image. A transparent PNG is best (send it as a *file*);
  a normal image gets its background removed automatically. Then pick a background colour scheme (7 presets,
  Auto from the cover, or your own hex colours) and nudge the character bigger/smaller/left/right. The character
  is remembered per anime, so switching templates and back doesn't ask again.
* **Customize** (button under every banner, or /settings): brand text, brand logo (PNG with transparency),
  the corner for the **text** and, separately, the corner for the **logo**, and **11 fonts**. Changes re-render the banner live.
  Layouts automatically slide their navigation out of the brand's way.
* **Animated start** with a progress animation, then a styled welcome message.
* **Animated button icons** (optional, see below).
* **Get file** button sends the full-quality PNG (Telegram compresses normal photos).
* Accent colour comes from each anime's own cover colour on AniList.

## Settings

On a VPS or in Docker use **environment variables / `.env`** (they win over `settings.py`). In Colab, where `.env` isn't read, use
`settings.py`.

Open `settings.py` and fill in `BOT_TOKEN` (from @BotFather). That file is read directly, so it works in
Google Colab. Environment variables / `.env` still work as a fallback.

| Setting | What it does |
|---|---|
| `BRAND_NAME` | Default brand text for people who haven't set their own. `""` = none |
| `BRAND_POSITION` / `LOGO_POSITION` | Default corner for the brand text / logo: `tl`, `tr`, `bl`, `br` |
| `SPECIAL_BOXES_OPACITY` | How bright the five side boxes are (1 = pure white, lower = softer) |
| `ALLOWED_USER_IDS` / `ADMIN_IDS` / `RATE_LIMIT_PER_MIN` | Make the bot private, exempt admins, and protect a public server from being hammered |
| `LOG_LEVEL` | `INFO` / `DEBUG` ... |
| `TMDB_API_KEY` | Optional. Enables TMDB HD backdrops (see below) |
| `SPECIAL_DEFAULTS` / `SPECIAL_WATERMARK_OPACITY` | Built-in watermark, credit and boxes in the Special Design, and how faded the watermark is |
| `KILL_OLD_INSTANCES` | Stop leftover copies of the bot on start (`"auto"` = Colab only) |
| `FANCY_TEXT` | ꜱᴍᴀʟʟ ᴄᴀᴘꜱ styling on buttons and messages |
| `ICONS` | Animated button icons (custom emoji IDs) |
| `AUTO_CUTOUT` | Remove backgrounds from normal (non-transparent) character images with AI |
| `DB_PATH` | Where per-user settings are stored (`data/bot.db`) |

## Animated button icons

Those moving icons are Telegram **custom emoji** attached to buttons. Telegram only accepts them if the
Telegram account that owns the bot has **Premium** (or the bot has Fragment usernames).

1. Start the bot and send `/emojiid`.
2. Send it a message containing Premium animated emoji. It replies with each emoji's ID.
3. Paste IDs into the slots in `ICONS` in `settings.py` (for example `"template": "5368..."`) and restart.

If Telegram refuses the icons, the bot logs a warning and falls back to normal emoji automatically.

## HD background art (TMDB)

TMDB (themoviedb.org) has high-definition **landscape backdrops** (usually 1920x1080 or larger, mostly text-free), which
is what the full-bleed designs want. OMDb isn't used: it only offers a small poster, no backdrops.

1. Make a free account at themoviedb.org, then Settings -> API, and request a key.
2. Paste the **API Key** (or the long **API Read Access Token**) into `TMDB_API_KEY` in `settings.py`.
3. Check it on a few titles before relying on it: `python -m scripts.tmdb_check "The Eminence in Shadow"`
   (or `--id <AniList id>`). It prints the match and the image links. Preview a real banner with
   `python -m scripts.preview --id 163134 --tmdb YOUR_KEY --only animeposter9`.

How it picks: titles are matched against TMDB (season words like "2nd Cour" are stripped, titles must be similar enough,
and TMDB's own top animation hit from the same year is trusted for romaji titles). Backdrops are ranked text-free first,
then largest. If there is no key, no confident match or any network error, the bot quietly uses AniList art. A wrong
match is possible on unusual titles, so people can tap Next image, or upload their own image for that anime.

TMDB requires this notice, which the bot shows in /help when a key is set: *This product uses the TMDB API but is
not endorsed or certified by TMDB.*

## If thumbnails look different every other time

That means two copies of the bot are answering the same token, often an old version left running. Send
`/version`: it shows the version, start time and process of whichever copy replied, and whether the special-design
defaults, TMDB art and AI cutout are switched on. On Google Colab a stopped cell
can leave the old process alive, so the bot now stops leftover `python -m bot` processes when it starts
(`KILL_OLD_INSTANCES = "auto"` in `settings.py`, on for Colab only). To be sure, choose Runtime -> Disconnect and
delete runtime, upload the new zip, and run once. Two *different* Colab sessions can't see each other, so close the other one.

## Special Design: how backgrounds are removed

For a character that isn't already transparent the bot tries, in order:
1. **AI** (`rembg` with its anime model `isnet-anime`). The ~180 MB model downloads the first time the bot
   starts, in the background. Needs `rembg` and `onnxruntime` (in `requirements.txt`). CPU is fine, a few seconds per image.
2. **Plain-background removal** (white or any single solid colour), which needs no model.
3. If neither works the image is kept as is and the user is told it may look boxed, and to send a transparent PNG.

Results depend on the artwork. Clean single-character images cut best; busy scenes, text overlays or several
characters can cut badly. Set `AUTO_CUTOUT = False` to skip the AI step.

## Fonts

Poppins (default), Montserrat, Inter, Oswald, Bebas Neue, Anton, Playfair Display, Cinzel, Orbitron,
Bangers, Pacifico. All are SIL OFL and bundled in `assets/fonts` (licences in `assets/fonts/licenses`).
Poppins, Montserrat and Inter also style the description text; the others style titles and buttons only.
To add one, drop its `woff2` files in `assets/fonts` and add a line in `bot/fonts.py`.

## Run it

**On a VPS:** see **[DEPLOY.md](DEPLOY.md)** (Docker or systemd, no open ports needed, health check, backups, updates).
In short: `cp .env.example .env`, put `BOT_TOKEN` in it, `docker compose up -d --build`.


**Google Colab:** upload `anime-thumb-bot-colab.ipynb` and run the cells top to bottom.

**Docker:** edit `settings.py`, then `docker compose up -d --build`.

**Plain Python:**

```bash
pip install -r requirements.txt
playwright install --with-deps chromium
sudo apt install fonts-noto-cjk   # optional, for Japanese titles
python -m bot
```

## How it works

1. **AniList** (free GraphQL API, no key) provides title, synopsis, genres, score, studio, cover art,
   characters and voice actors. `bot/anilist.py`
2. Images are downloaded once, embedded in the page as data URIs and cached, so switching template or
   font never re-fetches. `bot/assets.py`
3. A **Jinja2 HTML template** is filled in and screenshotted by headless Chromium. `bot/render.py`, `templates/`
4. Buttons carry `t:<user>:<anime>:<template>` etc. Only the person who made a banner can change it.
5. Per-user choices live in SQLite (`bot/store.py`); logos are resized and kept in `data/logos/`.

## Preview templates without Telegram

```bash
python -m scripts.preview --sample                                   # placeholder art, offline
python -m scripts.preview --id 163134 --brand "My Hub" --pos tr --logo-pos tl --logo mylogo.png --font bebas
python -m scripts.preview --sample --only animeposter7 --logo mylogo.png
```

The PNGs already in `preview/` use placeholder art, not real posters.

## Adding or changing templates

Copy a file in `templates/`, register it in `bot/registry.py`. Canvas is 1280x720. Data available as `a`:
`title`, `title_a`/`title_b` (two-line split), `description`, `genres`, `score10`, `star_pct`, `studio`, `year`,
`episodes`, `cover`, `banner`, `thumbs`, `characters`, `accent`, `accent_fg`. Use `title_size(...)` for the heading
size so it adapts to length and font, and give any top-left nav `left: max(Npx, var(--tl-shift, 0px))`.
Hide a template without code: `templates.json` with `{"animeposter5": {"active": false}}`.

## Tests

`python -m tests.test_config` checks configuration (environment beats settings.py), the health check and that the Docker
files agree on the Playwright version. `python -m tests.test_flow` drives the real handlers and Chromium against a fake AniList and fake Telegram
(start animation, banners, switching, position, font, text and logo input, brand removal, the Special Design
flow with colours and character upload, emoji helper, icon fallback). No token or internet needed.

## Not included yet

Payments / Telegram Stars and access locks.
