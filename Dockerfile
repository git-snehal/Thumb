# Anime Thumb Bot: production image.
# The base image ships Chromium and its system libraries. Its tag MUST match the playwright version in
# requirements.lock.txt (both are 1.56.0).
FROM mcr.microsoft.com/playwright/python:v1.56.0-noble

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    DB_PATH=/app/data/bot.db \
    U2NET_HOME=/app/data/rembg \
    TZ=UTC

WORKDIR /app

# CJK fonts so Japanese/Chinese/Korean titles never render as empty boxes; tini reaps zombie processes
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk tini \
    && rm -rf /var/lib/apt/lists/*

# dependencies first, so rebuilds after a code change are fast
COPY requirements.txt requirements.lock.txt ./
RUN pip install -r requirements.lock.txt

COPY . .

# runs as the unprivileged user that the Playwright image provides; /app/data is the persistent volume
RUN mkdir -p /app/data && chown -R pwuser:pwuser /app
USER pwuser

# the bot rewrites data/heartbeat every 30 s; the check fails if it goes stale (event loop stuck)
HEALTHCHECK --interval=60s --timeout=10s --start-period=120s --retries=3 \
    CMD ["python", "/app/deploy/healthcheck.py"]

ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "bot"]
