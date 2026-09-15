"""Internal telemetry relay helpers.

This module provides a small abstraction for sending telemetry updates from
collector processes back to the API server when the collectors are running in a
separate process or container.
"""

import logging
import os
from typing import Any, Dict

import aiohttp

from pythonsrc.api_token import resolve_api_token

try:
    from server.job_broadcaster import broadcaster as local_broadcaster
except ImportError:
    local_broadcaster = None

logger = logging.getLogger(__name__)

INTERNAL_TELEMETRY_PATH = "/jobs/{job_id}/internal-telemetry"

#: Logged once per process when there is no token to send. A collector that relays
#: every sample would otherwise repeat the same line a few times a second.
_warned_about_missing_token = False


def internal_telemetry_headers() -> Dict[str, str]:
    """The `Authorization` header for the relay, or nothing when there is no token.

    `POST /jobs/{id}/internal-telemetry` is authenticated like every other route —
    until it was, anyone who could reach the port could inject invented samples into a
    live job and into the dataset the whole project exists to gather. The pipeline
    container and the dispatch operator are handed the token beside `DS_API_URL` (see
    `server/app.py`'s `subprocess_env`); a collector that somehow has neither says so
    once and falls through to the local broadcaster, which is what a collector running
    inside the server process uses anyway.
    """
    global _warned_about_missing_token

    token = resolve_api_token()
    if token:
        return {"Authorization": f"Bearer {token}"}

    if not _warned_about_missing_token:
        _warned_about_missing_token = True
        logger.warning(
            "No DS_API_TOKEN for the internal telemetry relay: posts to %s will be "
            "refused and samples will fall back to the local broadcaster.",
            get_internal_api_url(),
        )
    return {}


def get_internal_api_url() -> str | None:
    """Get the configured API server URL for internal telemetry forwarding."""
    api_url = os.environ.get("DS_API_URL")
    if not api_url:
        return None
    return api_url.rstrip("/")


async def _post_internal_telemetry(job_id: str, message: Dict[str, Any]) -> bool:
    api_url = get_internal_api_url()
    if not api_url:
        return False

    url = f"{api_url}{INTERNAL_TELEMETRY_PATH.format(job_id=job_id)}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=message, timeout=10, headers=internal_telemetry_headers()
            ) as response:
                if response.status != 200:
                    text = await response.text()
                    logger.error(
                        "Internal telemetry POST failed: %s %s -> %s",
                        response.status,
                        url,
                        text,
                    )
                    return False
                return True
    except Exception as exc:
        logger.error("Failed to POST internal telemetry to %s: %s", url, exc)
        return False


async def send_internal_telemetry(job_id: str, message: Dict[str, Any]) -> bool:
    """Relay telemetry/state updates to the API server or local broadcaster."""
    if get_internal_api_url():
        success = await _post_internal_telemetry(job_id, message)
        if success:
            return True
        logger.warning(
            "Falling back to local broadcaster for telemetry because internal API post failed."
        )

    if local_broadcaster:
        try:
            await local_broadcaster.broadcast(job_id, message)
            return True
        except Exception as exc:
            logger.error("Local broadcaster failed to send telemetry: %s", exc)
    else:
        logger.debug("No local broadcaster available for telemetry relay.")

    return False
