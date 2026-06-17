"""Async API client for the Roulez Électrique platform.

Uses HA's bundled aiohttp session (async_get_clientsession) — no extra pip deps.

Exceptions hierarchy:
    RoulezElectriqueError          base
    ├── AuthError                  401 — token invalid/revoked → trigger reauth
    ├── ConnectError               network / timeout / 5xx
    ├── RateLimitedError           429 — carry Retry-After seconds
    ├── OfflineError               409 — charger offline at command time
    └── ForbiddenError             403 — non-OCPP charger or onboarding gate
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .const import (
    API_COMMAND_POLL_PATH,
    API_REMOTE_START_PATH,
    API_REMOTE_STOP_PATH,
    API_STATE_PATH,
    COMMAND_POLL_INTERVAL,
    COMMAND_TERMINAL_STATUSES,
    COMMAND_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

# Request timeout for individual HTTP calls
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)


class RoulezElectriqueError(Exception):
    """Base exception for all API errors."""


class AuthError(RoulezElectriqueError):
    """HTTP 401 — token invalid or revoked."""


class ConnectError(RoulezElectriqueError):
    """Network error, timeout, or unexpected 5xx response."""


class RateLimitedError(RoulezElectriqueError):
    """HTTP 429 — too many requests. Carry retry_after seconds."""

    def __init__(self, retry_after: int = 60) -> None:
        super().__init__(f"Rate limited; retry after {retry_after}s")
        self.retry_after = retry_after


class OfflineError(RoulezElectriqueError):
    """HTTP 409 — charger is offline, command cannot be sent."""


class ForbiddenError(RoulezElectriqueError):
    """HTTP 403 — non-OCPP charger or account onboarding gate."""


class RoulezElectriqueApiClient:
    """Thin typed client for the Roulez Électrique Home Assistant API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        api_token: str,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._api_token = api_token

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a single HTTP request and return parsed JSON.

        Raises the appropriate typed exception for 4xx/5xx status codes.
        Wraps network failures in ConnectError.
        """
        url = f"{self._base_url}{path}"
        try:
            async with self._session.request(
                method,
                url,
                headers=self._headers,
                json=json,
                timeout=_REQUEST_TIMEOUT,
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                if resp.status == 401:
                    raise AuthError("Invalid or revoked API token")
                if resp.status == 403:
                    raise ForbiddenError("Charger does not support remote control or account not fully set up")
                if resp.status == 409:
                    raise OfflineError("Charger is offline")
                if resp.status == 429:
                    retry_after = int(resp.headers.get("Retry-After", "60"))
                    raise RateLimitedError(retry_after)
                if resp.status >= 500:
                    body = await resp.text()
                    raise ConnectError(f"Server error {resp.status}: {body[:200]}")
                # 4xx not otherwise handled (404, 422, etc.)
                body = await resp.text()
                raise RoulezElectriqueError(f"Unexpected HTTP {resp.status}: {body[:200]}")
        except (aiohttp.ClientConnectionError, aiohttp.ServerTimeoutError, asyncio.TimeoutError) as err:
            raise ConnectError(f"Network error contacting {url}: {err}") from err
        except (AuthError, ForbiddenError, OfflineError, RateLimitedError, ConnectError, RoulezElectriqueError):
            raise

    async def get_state(self) -> dict[str, Any]:
        """GET /api/v1/home-assistant/state → full state envelope.

        Returns the raw JSON dict:
            {
                "generated_at": "...",
                "poll_interval_seconds": 30,
                "chargers": [...]
            }
        """
        return await self._request("GET", API_STATE_PATH)

    async def remote_start(
        self,
        charger_id: int,
        connector_id: int | None = None,
        id_tag: str | None = None,
    ) -> dict[str, Any]:
        """POST /api/v1/chargers/{id}/remote-start → {id, status}.

        Raises OfflineError (409), ForbiddenError (403), RateLimitedError (429).
        """
        path = API_REMOTE_START_PATH.format(charger_id=charger_id)
        payload: dict[str, Any] = {}
        if connector_id is not None:
            payload["connector_id"] = connector_id
        if id_tag is not None:
            payload["id_tag"] = id_tag
        return await self._request("POST", path, json=payload)

    async def remote_stop(
        self,
        charger_id: int,
        transaction_id: int,
    ) -> dict[str, Any]:
        """POST /api/v1/chargers/{id}/remote-stop → {id, status}.

        Raises OfflineError (409), ForbiddenError (403), RateLimitedError (429).
        """
        path = API_REMOTE_STOP_PATH.format(charger_id=charger_id)
        return await self._request("POST", path, json={"transaction_id": transaction_id})

    async def get_command(self, command_id: int | str) -> dict[str, Any]:
        """GET /api/v1/commands/{id} → {id, status, result, error}.

        Status is one of: queued, pending, accepted, rejected, timeout, failed.
        """
        path = API_COMMAND_POLL_PATH.format(command_id=command_id)
        return await self._request("GET", path)

    async def await_command(self, command_id: int | str) -> dict[str, Any]:
        """Poll GET /commands/{id} every COMMAND_POLL_INTERVAL seconds until a
        terminal status (accepted/rejected/timeout/failed) or COMMAND_TIMEOUT.

        Returns the final command dict.
        Raises ConnectError on timeout (we exceeded COMMAND_TIMEOUT seconds).
        """
        deadline = asyncio.get_event_loop().time() + COMMAND_TIMEOUT
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise ConnectError(
                    f"Command {command_id} did not reach a terminal state within {COMMAND_TIMEOUT}s"
                )
            cmd = await self.get_command(command_id)
            status = cmd.get("status", "")
            _LOGGER.debug("Command %s status: %s", command_id, status)
            if status in COMMAND_TERMINAL_STATUSES:
                return cmd
            await asyncio.sleep(min(COMMAND_POLL_INTERVAL, remaining))
