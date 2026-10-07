"""Async API client for the Roulez Électrique platform.

Uses HA's bundled aiohttp session (async_get_clientsession) — no extra pip deps.

Exceptions hierarchy:
    RoulezElectriqueError          base
    ├── AuthError                  401 — token invalid/revoked → trigger reauth
    ├── ConnectError               network / timeout / 5xx
    ├── RateLimitedError           429 — carry Retry-After seconds
    ├── OfflineError               409 — charger offline at command time
    ├── ChargingInProgressError    409 {"error": "charging_in_progress"} —
    │                              set_max_current only; the server refuses to
    │                              run a reboot-ending recipe mid-session
    └── ForbiddenError             403 — non-OCPP charger or onboarding gate
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .const import (
    API_AVE_PLUG_AND_CHARGE_PATH,
    API_AVE_REBOOT_PATH,
    API_AVE_TIMEZONE_PATH,
    API_COMMAND_POLL_PATH,
    API_LOCK_PATH,
    API_MAX_CURRENT_PATH,
    API_POWER_LIMIT_PATH,
    API_REMOTE_START_PATH,
    API_REMOTE_STOP_PATH,
    API_STATE_PATH,
    COMMAND_POLL_INTERVAL,
    COMMAND_TERMINAL_STATUSES,
    COMMAND_TIMEOUT,
    MAX_CURRENT_REQUEST_TIMEOUT,
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


class ChargingInProgressError(RoulezElectriqueError):
    """HTTP 409 {"error": "charging_in_progress"} — set_max_current only.

    The MaxCurrent recipe ends with a Reset(Soft) that interrupts whatever
    charge is running, so the server refuses it while a session is active (or
    while that state cannot be determined). Distinct from OfflineError because
    the remedy is the opposite: wait for the session to END, rather than for
    the borne to come back online.
    """


class ForbiddenError(RoulezElectriqueError):
    """HTTP 403 — non-OCPP charger or account onboarding gate."""


class NotFoundError(RoulezElectriqueError):
    """HTTP 404 — command or resource not found."""


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
        timeout: aiohttp.ClientTimeout | None = None,
    ) -> dict[str, Any]:
        """Make a single HTTP request and return parsed JSON.

        Raises the appropriate typed exception for 4xx/5xx status codes.
        Wraps network failures in ConnectError. `timeout` overrides the default
        20s budget for the one endpoint that legitimately runs longer (see
        set_max_current).
        """
        url = f"{self._base_url}{path}"
        try:
            async with self._session.request(
                method,
                url,
                headers=self._headers,
                json=json,
                timeout=timeout or _REQUEST_TIMEOUT,
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                if resp.status == 401:
                    raise AuthError("Invalid or revoked API token")
                if resp.status == 403:
                    raise ForbiddenError("Charger does not support remote control or account not fully set up")
                if resp.status == 404:
                    body = await resp.text()
                    raise NotFoundError(f"Resource not found: {body[:200]}")
                if resp.status == 409:
                    # 409 is overloaded: every command endpoint uses it for
                    # "borne offline", and max-current adds
                    # {"error": "charging_in_progress"}. Read the body to tell
                    # them apart — the two need opposite advice. Fail back to
                    # OfflineError (the historical meaning) whenever the body
                    # is missing, non-JSON or unrecognised, so no existing
                    # caller changes behaviour.
                    error_code = None
                    try:
                        body = await resp.json()
                        if isinstance(body, dict):
                            error_code = body.get("error")
                    except (aiohttp.ContentTypeError, ValueError):
                        pass
                    if error_code == "charging_in_progress":
                        raise ChargingInProgressError(
                            "A charging session is in progress on this charger"
                        )
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
        except aiohttp.ContentTypeError as err:
            # resp.json() raised because the response body was not JSON —
            # most commonly a Cloudflare HTML error page (wrong base URL,
            # 5xx from the edge) or a non-HTTPS redirect that returned HTML.
            # Surface as ConnectError so the config flow shows "cannot_connect"
            # rather than the opaque "unknown" error.
            raise ConnectError(f"Server returned non-JSON response from {url}: {err}") from err
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

    async def set_power_limit(
        self,
        charger_id: int,
        amps: int,
    ) -> dict[str, Any]:
        """POST /api/v1/chargers/{id}/power-limit → {id, status, synchronous?}.

        Sets the max charging current (amps). For Wallbox this is a SYNCHRONOUS
        cloud call ({id: null, synchronous: true}); for OCPP it returns a
        command id to poll. The server validates 6 ≤ amps ≤ maxControlAmps and
        returns 422 for an out-of-range value (surfaced as RoulezElectriqueError).

        Raises OfflineError (409), ForbiddenError (403), RateLimitedError (429).
        """
        path = API_POWER_LIMIT_PATH.format(charger_id=charger_id)
        return await self._request("POST", path, json={"amps": amps})

    async def set_max_current(
        self,
        charger_id: int,
        amps: int,
    ) -> dict[str, Any]:
        """POST /api/v1/chargers/{id}/max-current → the recipe outcome dict.

        The EVduty/Elmec `MaxCurrent` amperage control — the ONLY power-limit
        path for "Core"-only OCPP bornes, which reject SetChargingProfile with
        NotSupported (so /power-limit can never work for them).

        Unlike every other command endpoint this one is SYNCHRONOUS and returns
        NO command id to poll: the server runs the whole
        ChangeConfiguration -> read-back -> Reset(Soft) recipe inside the
        request and returns its outcome:

            {
                "step": "applied" | "change_timeout" | "change_rejected"
                      | "readback_offline" | "readback_timeout"
                      | "readback_mismatch" | "reset_offline" | "reset_failed",
                "ok": bool,
                "confirmed_amps": int | None,
                "change_command_id": int,
                "readback_command_id": int | None,
                "reset_command_id": int | None,
                "cp_status": str | None,
            }

        `ok` is the only success signal — a partial outcome (e.g. the value was
        written and confirmed but the Reset failed) returns ok=False WITH a
        non-null confirmed_amps, and callers must report that honestly rather
        than as a plain failure: the borne may already hold the new value.

        The final Reset(Soft) reboots the borne for 30-60s, so the server
        refuses (409 charging_in_progress → ChargingInProgressError) while a
        session is running. Rate limited to 10/min server-side.

        Raises ChargingInProgressError (409), OfflineError (409),
        RateLimitedError (429), ForbiddenError (403), and
        RoulezElectriqueError for a 422 (not an EVduty/Elmec borne, no baseline
        known, or amps outside the borne's permitted range).
        """
        path = API_MAX_CURRENT_PATH.format(charger_id=charger_id)
        return await self._request(
            "POST",
            path,
            json={"amps": amps},
            timeout=aiohttp.ClientTimeout(total=MAX_CURRENT_REQUEST_TIMEOUT),
        )

    async def set_lock(
        self,
        charger_id: int,
        locked: bool,
    ) -> dict[str, Any]:
        """POST /api/v1/chargers/{id}/lock → {id, status, synchronous?}.

        Locks (locked=True) or unlocks (locked=False) the borne. Wallbox-only;
        a SYNCHRONOUS cloud call. Raises OfflineError (409), ForbiddenError
        (403), RateLimitedError (429).
        """
        path = API_LOCK_PATH.format(charger_id=charger_id)
        return await self._request("POST", path, json={"locked": locked})

    async def set_ave_plug_and_charge(
        self,
        charger_id: int,
        enabled: bool,
    ) -> dict[str, Any]:
        """POST /api/v1/chargers/{id}/ave/plug-and-charge → {id, status, synchronous}.

        IYILO-only (server calls this vendor "ave" on the wire). FULLY
        SYNCHRONOUS — same contract as remote_start/remote_stop/set_lock
        above: {id: null, status: "accepted", synchronous: true} on success,
        no command id to poll.

        Raises OfflineError (409 offline). A vendor-side failure (502) or an
        unrecognized value surface as the generic ConnectError/
        RoulezElectriqueError respectively — not otherwise typed, same
        convention as set_max_current()'s 422 case above. RateLimitedError
        (429).
        """
        path = API_AVE_PLUG_AND_CHARGE_PATH.format(charger_id=charger_id)
        return await self._request("POST", path, json={"enabled": enabled})

    async def set_ave_time_zone(
        self,
        charger_id: int,
        time_zone_value: str,
    ) -> dict[str, Any]:
        """POST /api/v1/chargers/{id}/ave/timezone → {id, status, synchronous}.

        IYILO-only. FULLY SYNCHRONOUS, same contract as
        set_ave_plug_and_charge() above.

        Raises OfflineError (409 offline). An unknown `time_zone_value`
        surfaces as the generic RoulezElectriqueError (422
        {"error": "invalid_timezone"}); a vendor-side failure as ConnectError
        (502 {"error": "vendor_error"}) — neither is a dedicated exception
        type, same convention as set_max_current()'s 422 case above.
        RateLimitedError (429).
        """
        path = API_AVE_TIMEZONE_PATH.format(charger_id=charger_id)
        return await self._request(
            "POST", path, json={"time_zone_value": time_zone_value}
        )

    async def reboot_ave_charger(self, charger_id: int) -> dict[str, Any]:
        """POST /api/v1/chargers/{id}/ave/reboot → {id, status, synchronous}.

        IYILO-only, no request body. FULLY SYNCHRONOUS, same contract as
        set_ave_plug_and_charge() above — physically power-cycles the borne,
        interrupting any charge in progress.

        Raises OfflineError (409 offline), RateLimitedError (429). A
        vendor-side failure (502) surfaces as the generic ConnectError, same
        convention as the other two methods above.
        """
        path = API_AVE_REBOOT_PATH.format(charger_id=charger_id)
        return await self._request("POST", path)

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
        Raises ConnectError on timeout (we exceeded COMMAND_TIMEOUT seconds), or
        re-raises the last exception if polling continuously fails.
        """
        deadline = asyncio.get_running_loop().time() + COMMAND_TIMEOUT
        last_exception: Exception | None = None
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                if last_exception:
                    raise last_exception
                raise ConnectError(
                    f"Command {command_id} did not reach a terminal state within {COMMAND_TIMEOUT}s"
                )
            try:
                cmd = await self.get_command(command_id)
            except (RoulezElectriqueError, ConnectError) as err:
                last_exception = err
                _LOGGER.debug(
                    "Command %s poll encountered error (will retry): %s",
                    command_id,
                    err,
                )
            else:
                last_exception = None
                status = cmd.get("status", "")
                _LOGGER.debug("Command %s status: %s", command_id, status)
                if status in COMMAND_TERMINAL_STATUSES:
                    return cmd
            await asyncio.sleep(min(COMMAND_POLL_INTERVAL, remaining))
