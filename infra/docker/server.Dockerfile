FROM node:20-alpine AS web-builder
WORKDIR /app
COPY web/package*.json ./
RUN npm install
COPY web/ ./
RUN npm run build

FROM python:3.10-slim
WORKDIR /app

# Install Docker CLI + compose plugin for pipeline orchestration from within container
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# `pywebpush` is the web push sender (server/push.py); it is pinned in
# requirements-base.txt for the reason given there, and pinned here too because this
# image installs a list rather than that file.
#
# `fonttools` is the only geometry-adjacent thing this image installs, and it is here
# because it is **not** geometry: `pythonsrc/organizer/lettering.py` reads the vendored
# font's glyph metrics with it so `POST /organizer/resolve` can tell somebody the font
# cannot set their name while they are still typing it. Pure Python, no kernel, downloads
# nothing at runtime — which is exactly why that module was split off from `compiler.py`.
# MIT; see THIRD-PARTY-NOTICES.md § 2.
RUN pip install --no-cache-dir fastapi uvicorn aiohttp websockets "python-socketio[asyncio]" "psycopg[binary,pool]>=3.2,<4" httpx paho-mqtt cryptography docker PyYAML "pywebpush==2.5.0" "fonttools>=4.50"

COPY pythonsrc/ ./pythonsrc/
COPY server/ ./server/
COPY tests/ ./tests/
COPY infra/ ./infra/
COPY --from=web-builder /app/dist ./web/dist

# If pipeline.py relies on config.py we'll bootstrap it just in case, but let's stick to the minimal.
COPY infra/docker/entrypoint.sh /usr/local/bin/ds-entrypoint
RUN chmod +x /usr/local/bin/ds-entrypoint

ENTRYPOINT ["/usr/local/bin/ds-entrypoint"]
# `--host 0.0.0.0` is this container's own interface, not an exposure decision, and
# it must stay: Docker publishes a port by connecting to the container's address, so
# a loopback bind here makes the published port dead. Who may reach the server is
# decided by the bind address on the host side — `ports:` in
# infra/docker-compose.yml, loopback by default, moved by $DS_API_BIND.
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
