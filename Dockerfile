# ORION web — container image for the web access layer only.
# The desktop app is not included; this serves app.web over the database at
# /data/orion.db (mount a persistent volume there).
#
# Two stages: the Next.js front end (frontend/) is exported to static files at
# build time, then copied into the Python image. No Node runs in production —
# FastAPI serves the export directly (see app/web/ui_next.py).
#
# Required at runtime:
#   ORION_UNLOCK_PASSPHRASE  strong passphrase (production refuses to run the
#                            demo passphrase)
#   ORION_WEB_SECRET         session-signing secret (any long random string)
# Recommended behind TLS:
#   ORION_WEB_SECURE=1       HTTPS-only cookies + HSTS
#
# See docs/DEPLOY.md for platform walkthroughs and the privacy trade-offs.

# ---------------------------------------------------------------- UI build
# Base path the redesigned UI is served under. It sits alongside the Jinja app
# rather than at "/" because their route names collide; see app/web/ui_next.py.
# Must match ORION_UI_BASE_PATH in the runtime stage — Next bakes it into the
# emitted asset URLs, so a mismatch yields a page that loads no CSS or JS.
ARG ORION_UI_BASE_PATH=/v2

FROM node:24-bookworm-slim AS ui
ARG ORION_UI_BASE_PATH
ENV ORION_UI_BASE_PATH=${ORION_UI_BASE_PATH}
WORKDIR /build

RUN corepack enable

# Install against the lockfile first so dependency layers cache independently
# of source edits.
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend/ ./
RUN pnpm build

# ---------------------------------------------------------------- runtime
FROM python:3.12-slim
ARG ORION_UI_BASE_PATH

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/orion

COPY packaging/requirements-web.txt ./requirements-web.txt
RUN pip install -r requirements-web.txt

COPY app ./app
COPY --from=ui /build/out ./ui

ENV ORION_ENV=production \
    ORION_WEB_HOST=0.0.0.0 \
    ORION_WEB_PORT=8321 \
    ORION_DATABASE_URL=sqlite:////data/orion.db \
    ORION_UI_DIR=/srv/orion/ui \
    ORION_UI_BASE_PATH=${ORION_UI_BASE_PATH}

VOLUME /data
EXPOSE 8321

CMD ["python", "-m", "app.web.server"]
