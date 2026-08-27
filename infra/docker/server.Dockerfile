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

RUN pip install --no-cache-dir fastapi uvicorn aiohttp websockets "python-socketio[asyncio]" aiosqlite httpx paho-mqtt cryptography docker PyYAML

COPY pythonsrc/ ./pythonsrc/
COPY server/ ./server/
COPY tests/ ./tests/
COPY infra/ ./infra/
COPY --from=web-builder /app/dist ./web/dist

# If pipeline.py relies on config.py we'll bootstrap it just in case, but let's stick to the minimal.
COPY infra/docker/entrypoint.sh /usr/local/bin/ds-entrypoint
RUN chmod +x /usr/local/bin/ds-entrypoint

ENTRYPOINT ["/usr/local/bin/ds-entrypoint"]
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
