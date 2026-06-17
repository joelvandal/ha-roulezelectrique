"""DataUpdateCoordinator for the Roulez Électrique (BETA) integration.

One GET /api/v1/home-assistant/state call per refresh interval. The result is
stored as a dict keyed by charger id (int) for O(1) lookup by entity platforms.

Error handling (fail-closed policy):
    401 AuthError         → ConfigEntryAuthFailed  (triggers reauth flow)
    429 RateLimitedError  → UpdateFailed + delay next poll via Retry-After
    5xx / ConnectError    → UpdateFailed (entities go unavailable, HA retries)
    Empty roster          → empty dict {} (no entities, no error)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AuthError, ConnectError, RateLimitedError, RoulezElectriqueApiClient
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class RoulezElectriqueCoordinator(DataUpdateCoordinator[dict[int, dict[str, Any]]]):
    """Coordinator that polls the Roulez Électrique state endpoint.

    Data shape: { charger_id (int): { ...charger dict... }, ... }
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: RoulezElectriqueApiClient,
    ) -> None:
        scan_interval = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self._entry = entry

    async def _async_update_data(self) -> dict[int, dict[str, Any]]:
        """Fetch and return charger state keyed by charger id.

        Called automatically by HA at each update_interval. Exceptions:
          - ConfigEntryAuthFailed → HA stops polling and shows reauth UI
          - UpdateFailed          → HA marks entities unavailable + retries
        """
        try:
            envelope = await self.client.get_state()
        except AuthError as err:
            # Token revoked or expired — stop polling, trigger reauth.
            raise ConfigEntryAuthFailed(str(err)) from err
        except RateLimitedError as err:
            # Back off: delay next update by Retry-After seconds on top of
            # the normal interval. We achieve this by temporarily widening
            # the update_interval; HA will reset it on next _async_update_data.
            self.update_interval = timedelta(seconds=err.retry_after)
            raise UpdateFailed(f"Rate limited by server: {err}") from err
        except ConnectError as err:
            raise UpdateFailed(f"Cannot reach Roulez Électrique API: {err}") from err
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Unexpected error from API: {err}") from err

        # Restore normal interval (may have been widened for rate-limit backoff).
        scan_interval = self._entry.options.get(
            CONF_SCAN_INTERVAL,
            self._entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        self.update_interval = timedelta(seconds=scan_interval)

        chargers: list[dict[str, Any]] = envelope.get("chargers", [])
        if not chargers:
            return {}

        return {int(c["id"]): c for c in chargers}
