# 2.2.0

New
- fanart.tv (FANART_API_KEY): Special Design finds a transparent character itself; Customize -> Character -> Next character
  cycles candidates; Upload my own stays as the fallback. Real title logos on Posters 9 and 10 (fanart.tv, then TMDB).
- Next image now also cycles portrait posters from Jikan (MyAnimeList) and Kitsu (no keys).
- Small covers are enlarged cleanly (LANCZOS + light sharpen) before drawing.
- Badges (SUB, DUB, 1080p, 4K, HD, Completed, Ongoing, New + custom, max 4) on Template 1 and Posters 2, 5, 7, 8, 9, 10.
- Title language per person: Auto / English / Romaji / Native. Title logo on/off per person.
- Private chats: send the anime name with no command. Groups still need /poster.
- Optional owner watermark: WATERMARK_TEXT (visible) and WATERMARK_KEY (invisible, verify with python -m bot.watermark).
- tests/test_features.py (no browser needed), new end-to-end sections in tests/test_flow.py, GitHub Actions CI.

Upgrading: the database upgrades itself (new columns are added on start). New settings are all optional.
