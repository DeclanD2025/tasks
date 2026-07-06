# ORION web — container image for the web access layer only.
# The desktop app is not included; this serves app.web over the database at
# /data/orion.db (mount a persistent volume there).
#
# Required at runtime:
#   ORION_UNLOCK_PASSPHRASE  strong passphrase (production refuses to run the
#                            demo passphrase)
#   ORION_WEB_SECRET         session-signing secret (any long random string)
# Recommended behind TLS:
#   ORION_WEB_SECURE=1       HTTPS-only cookies + HSTS
#
# See docs/DEPLOY.md for platform walkthroughs and the privacy trade-offs.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/orion

COPY packaging/requirements-web.txt ./requirements-web.txt
RUN pip install -r requirements-web.txt

COPY app ./app

ENV ORION_ENV=production \
    ORION_WEB_HOST=0.0.0.0 \
    ORION_WEB_PORT=8321 \
    ORION_DATABASE_URL=sqlite:////data/orion.db

VOLUME /data
EXPOSE 8321

CMD ["python", "-m", "app.web.server"]
