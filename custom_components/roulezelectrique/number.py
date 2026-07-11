"""Number platform for the Roulez Électrique (BETA) integration.

Exposes the max charging current (amps) as a slider for bornes that support
current-limit control:
  - OCPP bornes (smart-charging SetChargingProfile)
  - Wallbox bornes (setAmps cloud call — synchronous)
  - AVE bornes (setAmps cloud call — synchronous)
  - Sigenergy AC bornes (setAcCurrent cloud call — synchronous)

Other vendors (Tesla, Sigenergy DC, …) are never current-limit controllable
and get NO number entity. Entity creation is data-driven (gated on the
server's `current_limit_controllable` flag, see async_setup_entry below), so
adding a new controllable vendor server-side requires NO change here.

Entity behavior:
  - native_min/max_value: from the charger's `min_amps`/`max_amps` (server-
    authoritative — = the power-limit endpoint's validated 6..maxControlAmps
    range). Falls back to DEFAULT_MIN_AMPS/DEFAULT_MAX_AMPS when the server
    omits them (older server / a fail-soft vendor read).
  - native_value: the current setting (`current_a`) when reported, else the max
    (so the slider shows a sensible position rather than empty).
  - available: gated on the server `current_limit_controllable` flag (pre-emptive
    409 guard). For AVE/Sigenergy AC this is true when the account is active
    (not gated on a live WebSocket — the cloud API is always reachable when
    the account is active).
  - set: POST /chargers/{id}/power-limit {amps}. OCPP returns a command id to
    poll (await_command); Wallbox, AVE and Sigenergy AC return a synchronous
    result ({id:null, synchronous:true}) that MUST NOT be polled.

Error handling (fail-closed): rejected/timeout/failed, 409 offline, 429 rate
limited → raise HomeAssistantError; a per-entity asyncio.Lock prevents two
overlapping set commands on the same borne.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricCurrent
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import ConnectError, OfflineError, RateLimitedError, RoulezElectriqueApiClient
from .const import DEFAULT_MAX_AMPS, DEFAULT_MIN_AMPS, DOMAIN
from .coordinator import RoulezElectriqueCoordinator
from .entity import RoulezElectriqueEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the max-current number entity for controllable-capable chargers.

    Gates on the server's `current_limit_controllable` flag (data-driven —
    see the module docstring), falling back to the legacy is_ocpp/Wallbox
    check for older servers that don't send the field yet. Runtime
    availability reflects the same flag via the `available` property.
    """
    coordinator: RoulezElectriqueCoordinator = hass.data[DOMAIN][entry.entry_id]
    client: RoulezElectriqueApiClient = hass.data[DOMAIN][f"{entry.entry_id}_client"]

    entities: list[RoulezElectriqueMaxCurrentNumber] = []
    charger_map = coordinator.data.chargers if coordinator.data else {}
    for charger_id, charger_data in charger_map.items():
        # Gate on the stable `current_limit_controllable` flag from the server:
        # true for OCPP (online), Wallbox (active account), and Sigenergy AC
        # (active account). Older servers without this field fall back to the
        # legacy is_ocpp/vendor check so the entity still appears on upgrade.
        is_limit_controllable = charger_data.get("current_limit_controllable")
        if is_limit_controllable is None:
            # Older server: fall back to legacy gate (OCPP or Wallbox).
            is_limit_controllable = (
                charger_data.get("is_ocpp") or charger_data.get("vendor") == "wallbox"
            )
        if not is_limit_controllable:
            _LOGGER.debug(
                "Charger %s does not support current-limit control — no max-current number entity",
                charger_id,
            )
            continue
        entities.append(RoulezElectriqueMaxCurrentNumber(coordinator, client, charger_id))

    async_add_entities(entities)


class RoulezElectriqueMaxCurrentNumber(RoulezElectriqueEntity, NumberEntity):
    """A slider that sets the borne's max charging current (amps)."""

    _attr_translation_key = "max_current"
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        coordinator: RoulezElectriqueCoordinator,
        client: RoulezElectriqueApiClient,
        charger_id: int,
    ) -> None:
        super().__init__(coordinator, charger_id)
        self._client = client
        self._attr_unique_id = f"{charger_id}_max_current"
        self._lock = asyncio.Lock()
        # Optimistic overlay: None = use coordinator data.
        self._optimistic_value: float | None = None

    async def _resolve_command(self, result: dict[str, Any]) -> dict[str, Any]:
        """Turn a power-limit response into a terminal command dict.

        Wallbox returns {id: null, synchronous: true} — the cloud call already
        completed, so DON'T poll a null id. OCPP returns {id, status} to poll.
        Same contract as the charge switch's helper.
        """
        if result.get("synchronous") or result.get("id") is None:
            return result
        return await self._client.await_command(result["id"])

    @property
    def native_min_value(self) -> float:
        """Lower bound = server `min_amps` (the validated floor), else default."""
        value = self._charger_data.get("min_amps")
        return float(value) if value is not None else float(DEFAULT_MIN_AMPS)

    @property
    def native_max_value(self) -> float:
        """Upper bound = server `max_amps` (= maxControlAmps), else default.

        Never let the max fall below the min (a degenerate server payload would
        otherwise make the slider unusable).
        """
        value = self._charger_data.get("max_amps")
        ceiling = float(value) if value is not None else float(DEFAULT_MAX_AMPS)
        return max(ceiling, self.native_min_value)

    @property
    def available(self) -> bool:
        """Available only when current-limit control is active (pre-emptive 409 guard).

        Uses `current_limit_controllable` (true for OCPP online, Wallbox active
        account, Sigenergy AC active account). Falls back to `controllable` for
        older server versions that do not yet expose the separate flag.
        """
        if not super().available:
            return False
        clc = self._charger_data.get("current_limit_controllable")
        if clc is not None:
            return bool(clc)
        # Older server fallback: use `controllable` (gated the same way before
        # Sigenergy AC support was added — avoids a regression on upgrade).
        return bool(self._charger_data.get("controllable"))

    @property
    def native_value(self) -> float | None:
        """The current amps setting if reported, else the max (slider default).

        During an in-flight set, the optimistic overlay is shown until the next
        coordinator refresh.
        """
        if self._optimistic_value is not None:
            return self._optimistic_value
        current = self._charger_data.get("current_a")
        if current is not None:
            return float(current)
        # No reported setting → park the slider at the ceiling so it has a
        # sensible position rather than rendering empty/unknown.
        return self.native_max_value

    async def async_set_native_value(self, value: float) -> None:
        """Set the max charging current (amps).

        Raises HomeAssistantError on rejection / offline (409) / rate limit
        (429) / any failure, reverting the optimistic value (fail-closed).
        """
        if self._lock.locked():
            raise HomeAssistantError(
                "A command is already in progress for this charger"
            )

        amps = int(round(value))

        async with self._lock:
            self._optimistic_value = float(amps)
            self.async_write_ha_state()

            try:
                result = await self._client.set_power_limit(self._charger_id, amps)
                cmd = await self._resolve_command(result)
            except OfflineError as err:
                self._optimistic_value = None
                self.async_write_ha_state()
                raise HomeAssistantError(
                    "Charger is offline — cannot set the charging current"
                ) from err
            except RateLimitedError as err:
                self._optimistic_value = None
                self.async_write_ha_state()
                raise HomeAssistantError(
                    f"Too many requests — please wait {err.retry_after}s before retrying"
                ) from err
            except (ConnectError, Exception) as err:  # noqa: BLE001
                self._optimistic_value = None
                self.async_write_ha_state()
                raise HomeAssistantError(
                    f"Could not set the charging current: {err}"
                ) from err

            final_status = cmd.get("status", "")
            if final_status != "accepted":
                self._optimistic_value = None
                self.async_write_ha_state()
                error_detail = cmd.get("error") or cmd.get("result") or final_status
                raise HomeAssistantError(
                    f"Set charging current {final_status}: {error_detail}"
                )

            # Accepted — refresh so current_a reflects the new setting.
            self._optimistic_value = None
            await self.coordinator.async_request_refresh()
