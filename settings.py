"""
Put your settings here. This file is read directly, so it works in Google Colab
where .env files are not picked up.

Never share this file (or a notebook containing it) once the token is filled in.
"""

# From @BotFather on Telegram
BOT_TOKEN = "PASTE_YOUR_BOT_TOKEN_HERE"

# Default brand text for people who haven't set their own in /settings.
# Leave as "" for clean banners with no branding.
BRAND_NAME = ""

# Default corners: "tl" top-left, "tr" top-right, "bl" bottom-left, "br" bottom-right.
# The brand TEXT and the brand LOGO can sit in different corners (people can change both in /settings).
BRAND_POSITION = "tr"   # text
LOGO_POSITION = "tl"    # logo

# Styled text (ꜱᴍᴀʟʟ ᴄᴀᴘꜱ) on buttons and in the start/help messages. Set False for plain text.
FANCY_TEXT = True

# Animated button icons. These are Telegram *custom emoji* IDs.
# They only work if the Telegram account that owns this bot has Telegram Premium.
# Get IDs by sending the bot a message containing Premium emoji: it replies with their IDs.
# Leave a slot as "" to use a normal emoji instead.
ICONS = {
    "template": "",    # every template button
    "active": "",      # the currently selected template
    "file": "",        # "Get full-quality file"
    "customize": "",   # open the brand/font panel
    "help": "",
    "settings": "",
    "make": "",        # "Make a thumbnail" on the start message
    "text": "",        # brand text
    "logo": "",        # brand logo
    "position": "",
    "font": "",
    "remove": "",
    "back": "",
    "close": "",
    "special": "",     # the Special Design button
    "colors": "",
    "character": "",
    "preview": "",     # Preview all
    "hd": "",          # HD file
    "edit": "",        # Edit text
}

# Special Design: when someone uploads a normal (non-transparent) image, try to remove its background
# automatically with an AI model (needs `rembg`; the ~180 MB anime model downloads on first use).
AUTO_CUTOUT = True

# Special Design: ship with the built-in OD3N watermark, small "OD3N COMMUNITY" credit and side boxes
# (assets/special/*.png). Anyone who sets their own brand text gets their text instead.
SPECIAL_DEFAULTS = True
SPECIAL_WATERMARK_OPACITY = 0.11   # how faded the big background watermark is (0 to 1)
SPECIAL_BOXES_OPACITY = 1.0        # the five side boxes: 1 = pure white, lower = softer

# Optional: TMDB (themoviedb.org). Gives high-definition landscape artwork for the full-bleed designs AND acts as a
# backup search: if AniList is down or doesn't have a title, /poster finds it on TMDB instead.
# Free key: themoviedb.org -> your profile -> Settings -> API. Paste the "API Key" (or the long "API Read
# Access Token"). Leave "" to use AniList art only. Customers can also upload their own image per anime.
TMDB_API_KEY = ""

# Optional: fanart.tv. Gives the Special Design a transparent character automatically (with a "Next character"
# button) and real title logos for the designs that support them. Free personal key: fanart.tv -> sign up -> your
# profile -> API key. Works best together with TMDB_API_KEY. Leave "" to keep uploading characters by hand.
FANART_API_KEY = ""

# Optional switches (all on by default). Set to False to turn a feature off.
EXTRA_ART_SOURCES = True    # more poster choices in "Next image" from Jikan (MyAnimeList) and Kitsu, no key needed
UPSCALE_SMALL_ART = True    # clean enlargement of small covers so the 2x HD file isn't blocky
TITLE_LOGOS = True          # use the show's real title logo (fanart.tv / TMDB) on Posters 9 and 10 when one exists

# Optional owner watermark on every image the bot sends. Both are off while empty.
WATERMARK_TEXT = ""         # faint diagonal text across the picture, e.g. "@MyAnimeHub"
WATERMARK_KEY = ""          # any secret phrase: adds an INVISIBLE mark you can check with  python -m bot.watermark verify

# Who may use the bot: Telegram user IDs separated by commas. Empty = anyone. ADMIN_IDS are always allowed
# and never rate-limited. (Find an ID with @userinfobot.)
ALLOWED_USER_IDS = ""
ADMIN_IDS = ""
RATE_LIMIT_PER_MIN = 20     # render actions per person per minute (HD file = 2, Preview all = 3). 0 = unlimited
LOG_LEVEL = "INFO"          # DEBUG, INFO, WARNING, ERROR

# Stop leftover copies of the bot on start. "auto" = only on Google Colab. Use True / False to force.
KILL_OLD_INSTANCES = "auto"

# Optional tuning (defaults are fine)
RENDER_CONCURRENCY = 2   # banners rendered at the same time
CACHE_TTL = 3600         # seconds an anime's data/images stay cached
DB_PATH = "data/bot.db"  # where per-user settings are stored
