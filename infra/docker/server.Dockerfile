FROM node:20-alpine AS web-builder
WORKDIR /app
COPY web/package*.json ./
RUN npm install
COPY web/ ./
RUN npm run build

FROM python:3.10-slim
WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn aiohttp websockets "python-socketio[asyncio]" aiosqlite

COPY pythonsrc/ ./pythonsrc/
COPY server/ ./server/
COPY --from=web-builder /app/dist ./web/dist

# If pipeline.py relies on config.py we'll bootstrap it just in case, but let's stick to the minimal.
COPY infra/docker/entrypoint.sh /usr/local/bin/p2p-entrypoint
RUN chmod +x /usr/local/bin/p2p-entrypoint

ENTRYPOINT ["/usr/local/bin/p2p-entrypoint"]
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
