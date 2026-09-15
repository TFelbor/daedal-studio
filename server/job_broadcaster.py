"""WebSocket broadcaster for streaming job statuses, telemetry, and phase updates."""
import asyncio
import logging
from typing import Dict, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)

class JobBroadcaster:
    """Manages WebSocket connections and broadcasts messages to clients."""

    def __init__(self):
        self._connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, job_id: str, ws: WebSocket):
        """Register a new WebSocket connection for a specific job."""
        async with self._lock:
            if job_id not in self._connections:
                self._connections[job_id] = set()
            self._connections[job_id].add(ws)

    async def disconnect(self, job_id: str, ws: WebSocket):
        """Remove a WebSocket connection."""
        async with self._lock:
            if job_id in self._connections:
                self._connections[job_id].discard(ws)
                if not self._connections[job_id]:
                    del self._connections[job_id]

    async def broadcast(self, job_id: str, message: dict):
        """Broadcast a JSON message to all clients connected to a specific job."""
        dead_connections = set()

        async with self._lock:
            connections = list(self._connections.get(job_id, []))

        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.debug(f"Failed to send to WebSocket, marking as dead: {e}")
                dead_connections.add(ws)

        if dead_connections:
            async with self._lock:
                if job_id in self._connections:
                    for ws in dead_connections:
                        self._connections[job_id].discard(ws)
                    if not self._connections[job_id]:
                        del self._connections[job_id]

    async def broadcast_all(self, message: dict):
        """Broadcast a JSON message to all connected clients across all jobs."""
        dead_connections = []

        async with self._lock:
            # Flatten all connections
            connections = [(job_id, ws) for job_id, wss in self._connections.items() for ws in wss]

        for job_id, ws in connections:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.debug(f"Failed to send to WebSocket, marking as dead: {e}")
                dead_connections.append((job_id, ws))

        if dead_connections:
            async with self._lock:
                for job_id, ws in dead_connections:
                    if job_id in self._connections:
                        self._connections[job_id].discard(ws)
                        if not self._connections[job_id]:
                            del self._connections[job_id]

broadcaster = JobBroadcaster()
