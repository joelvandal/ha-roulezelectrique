"""Select platform for the Club Roulez Électrique integration.

One entity: the IYILO time-zone select. IYILO-only (server capability
"time_zone"; IYILO is the vendor this repo calls "ave" on the wire, same as
switch.py's charge switch gate). Options come from the TOP-LEVEL `time_zones`
list in the state envelope (`[{"value": ..., "label": ...}, ...]`, see
coordinator.py) — labels are shown, values are what gets written. Selecting
an option calls POST /chargers/{id}/ave/timezone {time_zone_value} — a
SYNCHRONOUS IYILO cloud call, same {id: null, status: "accepted",
synchronous: true} contract as switch.py's Plug & Charge switch, so it
follows the same optimistic-write-then-revert pattern.

Two states this entity must never get wrong:
  - `time_zones` is empty (server cold/unavailable, or the account has no
    IYILO borne at all): there is nothing to pick from. The select still
    shows the borne's own current `time_zone_value` if one is reported (as a
    single, un-selectable-elsewhere option) rather than going blank — see
    `options`/`current_option` below. If the borne has never reported a
    value either, `current_option` is None (HA renders "unknown"), which is
    honest: there is genuinely nothing to show.
  - the borne's current `time_zone_value` is not among the server's known
    `time_zones` (a value IYILO reports that our own list doesn't carry, or
    a list that hasn't caught up yet): the current value is APPENDED to
    `options` rather than silently dropped or replaced by something else —
    HA's own SelectEntity.state renders None whenever current_option isn't
    literally a member of `options` (see select/__init__.py), so leaving it
    out would make a real, known setting look "unknown".
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Hashable
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import ConnectError, OfflineError, RateLimitedError, RoulezElectriqueApiClient
from .const import DOMAIN
from .coordinator import CoordinatorData, RoulezElectriqueCoordinator
from .entity import RoulezElectriqueEntity, async_add_entities_dynamically

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the time-zone select for every IYILO-capable ("time_zone"
    capability) charger."""
    coordinator: RoulezElectriqueCoordinator = hass.data[DOMAIN][entry.entry_id]
    client: RoulezElectriqueApiClient = hass.data[DOMAIN][f"{entry.entry_id}_client"]

    def _build(data: CoordinatorData) -> list[tuple[Hashable, Callable[[], Any]]]:
        found: list[tuple[Hashable, Callable[[], Any]]] = []
        for charger_id, charger_data in data.chargers.items():
            if "time_zone" in charger_data.get("capabilities", []):
                found.append(
                    (
                        (charger_id, "time_zone"),
                        lambda cid=charger_id: RoulezElectriqueTimeZoneSelect(
                            coordinator, client, cid
                        ),
                    )
                )
            else:
                _LOGGER.debug(
                    "Charger %s does not support time-zone control — no select entity created",
                    charger_id,
                )
        return found

    async_add_entities_dynamically(entry, coordinator, async_add_entities, _build)


class RoulezElectriqueTimeZoneSelect(RoulezElectriqueEntity, SelectEntity):
    """A select that shows/sets an IYILO borne's time zone.

    See the module docstring for the empty-options and unknown-current-value
    handling. A per-instance asyncio.Lock prevents overlapping commands.
    """

    _attr_translation_key = "time_zone"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: RoulezElectriqueCoordinator,
        client: RoulezElectriqueApiClient,
        charger_id: int,
    ) -> None:
        super().__init__(coordinator, charger_id)
        self._client = client
        self._attr_unique_id = f"{charger_id}_time_zone"
        self._lock = asyncio.Lock()
        # Optimistic overlay: None = use coordinator data. Holds the wire
        # VALUE (not the label) being written, same convention as
        # `time_zone_value` on the charger dict.
        self._optimistic_value: str | None = None

    async def _resolve_command(self, result: dict[str, Any]) -> dict[str, Any]:
        """Time-zone set is a synchronous IYILO call; only poll a real id."""
        if result.get("synchronous") or result.get("id") is None:
            return result
        return await self._client.await_command(result["id"])

    @property
    def _time_zones(self) -> list[dict[str, Any]]:
        """The top-level `time_zones` list from the coordinator, never None."""
        data = self.coordinator.data
        if data is None:
            return []
        return data.time_zones or []

    def _label_for_value(self, value: str) -> str | None:
        for tz in self._time_zones:
            if tz.get("value") == value:
                label = tz.get("label")
                return str(label) if label is not None else None
        return None

    def _value_for_label(self, label: str) -> str | None:
        for tz in self._time_zones:
            if tz.get("label") == label:
                return tz.get("value")
        return None

    @property
    def options(self) -> list[str]:
        """Labels for every server-known time zone.

        Plus, when the borne's own current value isn't among them (or the
        list is empty), the current value is appended so it is never
        silently dropped — see the module docstring.
        """
        labels = [
            str(tz.get("label")) for tz in self._time_zones if tz.get("label") is not None
        ]

        current_value = (
            self._optimistic_value
            if self._optimistic_value is not None
            else self._charger_data.get("time_zone_value")
        )
        if current_value is None:
            return labels

        current_label = self._label_for_value(current_value)
        if current_label is not None:
            # Already represented by a server-known label — nothing to add.
            return labels

        # Unknown to the server's list: show the raw value as its own
        # option, appended (never replacing anything already listed).
        fallback = str(current_value)
        if fallback not in labels:
            labels = [*labels, fallback]
        return labels

    @property
    def current_option(self) -> str | None:
        """The label for the current time zone, or the raw value if unknown."""
        current_value = (
            self._optimistic_value
            if self._optimistic_value is not None
            else self._charger_data.get("time_zone_value")
        )
        if current_value is None:
            return None
        return self._label_for_value(current_value) or str(current_value)

    @property
    def available(self) -> bool:
        """Available only when settings are controllable on this borne.

        `settings_controllable` is a SEPARATE flag from `controllable` — an
        inactive IYILO account or a retired borne makes settings
        uncontrollable independently of charging control (see switch.py's
        module docstring).
        """
        if not super().available:
            return False
        return bool(self._charger_data.get("settings_controllable"))

    async def async_select_option(self, option: str) -> None:
        """Set the borne's time zone.

        `option` is a LABEL (as shown in `options`); it is translated back to
        the wire value before writing. Selecting the current option again
        (including the unknown-value fallback case) is a no-op — there is
        nothing new to tell the server.

        Raises HomeAssistantError on rejection / offline (409) / rate limit
        (429) / a vendor error (502) / an unrecognized time zone (422) / any
        failure, reverting the optimistic value (fail-closed).
        """
        if option == self.current_option:
            return

        value = self._value_for_label(option)
        if value is None:
            raise HomeAssistantError(f"Unknown time zone option: {option}")

        if self._lock.locked():
            raise HomeAssistantError(
                "A command is already in progress for this charger"
            )

        async with self._lock:
            self._optimistic_value = value
            self.async_write_ha_state()

            try:
                result = await self._client.set_ave_time_zone(self._charger_id, value)
                cmd = await self._resolve_command(result)
            except OfflineError as err:
                self._optimistic_value = None
                self.async_write_ha_state()
                raise HomeAssistantError(
                    "Charger is offline — cannot change the time zone"
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
                    f"Could not change the time zone: {err}"
                ) from err

            final_status = cmd.get("status", "")
            if final_status != "accepted":
                self._optimistic_value = None
                self.async_write_ha_state()
                error_detail = cmd.get("error") or cmd.get("result") or final_status
                raise HomeAssistantError(
                    f"Set time zone {final_status}: {error_detail}"
                )

            # Accepted — refresh so `time_zone_value` reflects the new setting.
            self._optimistic_value = None
            await self.coordinator.async_request_refresh()
