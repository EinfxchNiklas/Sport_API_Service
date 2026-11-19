# Sport Dashboard API – Container-Image mit Google Chrome (für den WhoScored-Scraper).
# Hinweis: Google Chrome gibt es nur für linux/amd64 (Render nutzt amd64).
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/app \
    SOCCERDATA_DIR=/tmp/soccerdata

# Systempakete + Google Chrome (offizielles apt-Repository, signiert über Keyring).
# tini räumt verwaiste Chrome-Prozesse (Zombies) auf.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg fonts-liberation tini \
    && install -d -m 0755 /etc/apt/keyrings \
    && curl -fsSL https://dl-ssl.google.com/linux/linux_signing_key.pub \
        | gpg --dearmor -o /etc/apt/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
        > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Nicht-Root-Benutzer mit beschreibbarem HOME und WORKDIR (seleniumbase legt downloaded_files/ im CWD an).
RUN useradd --create-home --home-dir /home/app --shell /usr/sbin/nologin app \
    && mkdir -p /app /tmp/soccerdata \
    && chown app:app /app /tmp/soccerdata
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# chromedriver / uc_driver passend zur installierten Chrome-Version schon beim Build laden,
# damit der erste Scraper-Lauf nicht erst herunterladen muss. Die Zielordner bleiben für den
# App-Benutzer beschreibbar (seleniumbase patcht uc_driver bei Bedarf, tls_requests lädt seine Bibliothek nach).
RUN sbase get chromedriver \
    && sbase get uc_driver \
    && SB_DIR="$(python -c 'import os, seleniumbase; print(os.path.dirname(seleniumbase.__file__))')" \
    && TLS_DIR="$(python -c 'import os, tls_requests; print(os.path.dirname(tls_requests.__file__))')" \
    && mkdir -p "$TLS_DIR/bin" \
    && chown -R app:app "$SB_DIR/drivers" "$TLS_DIR/bin"

COPY --chown=app:app . .

USER app
EXPOSE 8000

# Nur EIN uvicorn-Worker: der Browser-Lock (und der Scheduler) gelten pro Prozess.
# Migrationen laufen hier im Start-Befehl, weil preDeployCommand auf Render nur für bezahlte Dienste gilt.
# Chrome-Flags (--no-sandbox, --disable-dev-shm-usage, --headless) setzt seleniumbase unter Linux selbst.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
