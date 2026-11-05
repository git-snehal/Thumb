<div align="center">
<img src="https://user-images.githubusercontent.com/46998970/162791834-8c7c9ad0-42cf-4bc6-8208-d21f8a846f40.gif" width="100%" alt="Anime Painter Banner">

  <h1>🎨 Thumb Bot</h1>

  <h1>🎨 Thumb Bot</h1>
  
  <p><b>A Telegram bot that turns any anime title into a streaming-site style banner.</b></p>

  <p>
    <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
    <img src="https://img.shields.io/badge/Playwright-Chromium-2EAD33?style=for-the-badge&logo=playwright&logoColor=white" alt="Playwright">
    <img src="https://img.shields.io/badge/AniList-GraphQL-00b0ff?style=for-the-badge&logo=anilist&logoColor=white" alt="AniList">
    <img src="https://img.shields.io/badge/TMDB-Backup-01b4e4?style=for-the-badge&logo=themoviedb&logoColor=white" alt="TMDB">
  </p>
</div>

---

<p align="center">
  <i>Switch between 13 distinct layouts instantly using inline buttons with message updates in place. Customize your brand text or logo, pick corners, select fonts, and create high-definition posters.</i>
</p>

---

## ⚡ Quick Command Reference

```text
/start               Animated start message & onboarding
/poster [Title]      Generate banner + template selection buttons
/poster id:163134    Generate by AniList ID
/poster [URL]        Generate by AniList or TMDB link
/settings            Configure brand text, logo, corners, and fonts
/help  /version  /emojiid  /cancel

```

---

## ✨ Key Features

* **13 Layout Options:** Switch between Template 1, Poster 1 (v2 dark / v3 mirrored), Posters 2 through 10, and the fully loaded **Special Design**.
* **TMDB Backup Source:** If AniList fails or lacks a title, the bot automatically falls back to TMDB for metadata and HD backdrops.
* **Live Customization:** Edit synopses, genres, season titles, and episode labels per-anime and per-user.
* **HD Exports:** Generates standard views alongside sharp 2560x1440 PNG files.
* **Character AI Cutout:** Automatically removes backgrounds from uploaded character images using AI (`rembg`) for custom designs.
* **11 Bundled Fonts:** Poppins, Montserrat, Inter, Oswald, Bebas Neue, Anton, Playfair Display, Cinzel, Orbitron, Bangers, and Pacifico.

---

```text
Anime-Thumb-Bot/
├── bot/
│   ├── anilist.py          # AniList GraphQL API client
│   ├── assets.py           # Asset downloading, caching & data URIs
│   ├── fonts.py            # Font registries & styling handlers
│   └── render.py           # Jinja2 template rendering & Chromium bridge
├── templates/              # HTML/CSS layouts (1280x720 canvas definitions)
├── assets/                 # Fonts, special design default assets
├── scripts/                # Preview generators & TMDB diagnostic tools
├── tests/                  # Integration and flow test suites
└── bot.py                  # Main bot entrypoint & handlers

```

---

## ⚙️ Configuration & Settings

Controlled via environment variables, `.env`, or directly inside `settings.py`:

| Setting | Description |
| --- | --- |
| `BOT_TOKEN` | Your Telegram bot token from [@BotFather](https://t.me/BotFather) |
| `BRAND_NAME` | Default brand text for unconfigured users (`""` for none) |
| `BRAND_POSITION` / `LOGO_POSITION` | Corner placement (`tl`, `tr`, `bl`, `br`) |
| `TMDB_API_KEY` | Optional key for high-definition landscape backdrops |
| `AUTO_CUTOUT` | Enables automated background removal for custom characters |
| `DB_PATH` | Storage location for user preferences (`data/bot.db`) |

---

## 🚀 Installation & Deployment

### Run Locally / VPS

```bash
git clone [https://github.com/git-snehal/Anime-Thumb-Bot.git](https://github.com/git-snehal/Anime-Thumb-Bot.git)
cd Anime-Thumb-Bot
pip install -r requirements.txt
playwright install --with-deps chromium
python3 -m bot

```

### Docker

```bash
cp .env.example .env
# Fill in your BOT_TOKEN in .env
docker compose up -d --build

```
## 📜 Credits & License

* Built with Python, Playwright, Jinja2, and Chromium.
* Uses the AniList and TMDB APIs.*
*  **Made By**-[@shinnoirr](https://t.me/shinnoirr)

