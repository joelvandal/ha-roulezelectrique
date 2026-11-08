"""Number platform for the Club Roulez Électrique integration.

Exposes the max charging current (amps) as a slider for bornes that support
current-limit control:
  - OCPP bornes (smart-charging SetChargingProfile)
  - Wallbox bornes (setAmps cloud call — synchronous)
  - AVE bornes (setAmps cloud call — synchronous)
  - Sigenergy AC bornes (setAcCurrent cloud call — synchronous)

"Core"-only OCPP bornes (the EVduty/Elmec family) support NONE of that: they
reject SetChargingProfile outright with NotSupported. They get a SECOND,
separate entity instead — RoulezElectriqueEvdutyMaxCurrentNumber — driven by
the server's `max_current_controllable` flag and the dedicated
POST /chargers/{id}/max-current endpoint. The server guarantees the two flags
are MUTUALLY EXCLUSIVE, so a borne never gets both entities.

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
from collections.abc import Callable, Hashable
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricCurrent
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import (
    ChargingInProgressError,
    ConnectError,
    OfflineError,
    RateLimitedError,
    RoulezElectriqueApiClient,
)
from .const import DEFAULT_MAX_AMPS, DEFAULT_MIN_AMPS, DOMAIN
from .coordinator import CoordinatorData, RoulezElectriqueCoordinator
from .entity import RoulezElectriqueEntity, async_add_entities_dynamically

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
    Re-evaluated on every poll (0.11.1+): a charger that becomes controllable
    later gets its slider with no reload.
    """
    coordinator: RoulezElectriqueCoordinator = hass.data[DOMAIN][entry.entry_id]
    client: RoulezElectriqueApiClient = hass.data[DOMAIN][f"{entry.entry_id}_client"]

    # Chargers already on the EVduty path (see _build). Remembered so a charger
    # that got the EVduty slider can never also get the generic one later.
    evduty_path: set[int] = set()

    def _build(data: CoordinatorData) -> list[tuple[Hashable, Callable[[], Any]]]:
        found: list[tuple[Hashable, Callable[[], Any]]] = []
        for charger_id, charger_data in data.chargers.items():
            # Gate on the stable `current_limit_controllable` flag from the server:
            # true for OCPP (online), Wallbox (active account), and Sigenergy AC
            # (active account). Older servers without this field fall back to the
            # legacy is_ocpp/vendor check so the entity still appears on upgrade.
            #
            # EVduty/Elmec exception (0.11.1): before the server has read such a
            # borne's first configuration it reports current_limit_controllable
            # = true (optimistic window), then flips to
            # max_current_controllable = true. With dynamic addition the generic
            # slider created in that window would stay forever as an unavailable
            # duplicate. The server advertises the "max_current" capability up
            # front (before the baseline read, in the very first poll) for
            # exactly these chargers, so that capability — or having already
            # created the EVduty slider — marks the EVduty path and the generic
            # slider is never created for it. Trade-off: no slider at all until
            # the server reports max_current_controllable for such a borne.
            if "max_current" in (charger_data.get("capabilities") or []):
                evduty_path.add(charger_id)
            is_limit_controllable = charger_data.get("current_limit_controllable")
            if is_limit_controllable is None:
                # Older server: fall back to legacy gate (OCPP or Wallbox).
                is_limit_controllable = (
                    charger_data.get("is_ocpp") or charger_data.get("vendor") == "wallbox"
                )
            if is_limit_controllable and charger_id not in evduty_path:
                found.append(
                    (
                        (charger_id, "max_current"),
                        lambda cid=charger_id: RoulezElectriqueMaxCurrentNumber(
                            coordinator, client, cid
                        ),
                    )
                )
                continue

            # "Core"-only OCPP borne (EVduty/Elmec): SetChargingProfile is refused
            # by the firmware, so the server exposes the MaxCurrent path instead.
            # Mutually exclusive with the flag above — checked second so a server
            # bug that set both could never produce two competing sliders.
            # The realistic direction is the reverse of the generic-first order
            # above: the optimistic window (generic flag true), then EVduty —
            # handled by the evduty_path rule, which keeps the generic slider
            # from ever being created for these chargers.
            if charger_data.get("max_current_controllable"):
                evduty_path.add(charger_id)
                found.append(
                    (
                        (charger_id, "evduty_max_current"),
                        lambda cid=charger_id: RoulezElectriqueEvdutyMaxCurrentNumber(
                            coordinator, client, cid
                        ),
                    )
                )
                continue

            _LOGGER.debug(
                "Charger %s does not support current-limit control — no max-current number entity",
                charger_id,
            )
        return found

    async_add_entities_dynamically(entry, coordinator, async_add_entities, _build)


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


class RoulezElectriqueEvdutyMaxCurrentNumber(RoulezElectriqueEntity, RestoreNumber):
    """MaxCurrent slider for "Core"-only OCPP bornes (EVduty/Elmec).

    Separate from RoulezElectriqueMaxCurrentNumber because the two controls
    only LOOK alike. This one:

      - hits POST /chargers/{id}/max-current, not /power-limit (the borne
        rejects SetChargingProfile with NotSupported — the whole reason this
        class exists);
      - is SYNCHRONOUS: the server runs the whole change inside the one
        request and returns an outcome dict, so there is NO command id to
        poll;
      - does NOT reboot the borne and works during a charge (the client sends
        `allow_while_charging`, like the mobile app); the server rate limits
        it to 10/min;
      - has no server-reported current value to read back — the payload only
        carries the bounds — so the applied value is restored across restarts
        via RestoreNumber rather than re-derived from coordinator data.
    """

    _attr_translation_key = "evduty_max_current"
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: RoulezElectriqueCoordinator,
        client: RoulezElectriqueApiClient,
        charger_id: int,
    ) -> None:
        super().__init__(coordinator, charger_id)
        self._client = client
        # Deliberately NOT "{id}_max_current": that unique_id belongs to the
        # SetChargingProfile entity above. A borne can only ever have one of
        # the two, but reusing the id would silently adopt the other entity's
        # history and settings if a borne ever flipped between them (e.g. its
        # feature profiles get read for the first time and it turns out to be
        # Core-only).
        self._attr_unique_id = f"{charger_id}_evduty_max_current"
        self._lock = asyncio.Lock()
        self._applied_value: float | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the last applied amperage (nothing reports it back)."""
        await super().async_added_to_hass()
        last_number_data = await self.async_get_last_number_data()
        if last_number_data is not None and last_number_data.native_value is not None:
            self._applied_value = float(last_number_data.native_value)

    @property
    def native_min_value(self) -> float:
        """Server `max_current_min` (the 6 A floor the service enforces)."""
        value = self._charger_data.get("max_current_min")
        return float(value) if value is not None else float(DEFAULT_MIN_AMPS)

    @property
    def native_max_value(self) -> float:
        """Server `max_current_max` — the borne's captured install baseline.

        This is a hard ceiling: the service refuses to write above the
        baseline without a recorded owner attestation that the electrical
        installation supports more, which Home Assistant cannot give. Never
        let it fall below the min.
        """
        value = self._charger_data.get("max_current_max")
        ceiling = float(value) if value is not None else float(DEFAULT_MAX_AMPS)
        return max(ceiling, self.native_min_value)

    @property
    def available(self) -> bool:
        """Available only while the server reports MaxCurrent control active."""
        if not super().available:
            return False
        return bool(self._charger_data.get("max_current_controllable"))

    @property
    def native_value(self) -> float | None:
        """The last value this entity applied, else the baseline ceiling.

        The borne's live MaxCurrent is not part of the state payload, so there
        is nothing authoritative to fall back to; parking at the ceiling (the
        captured install baseline) matches how the borne left the factory and
        mirrors the sibling entity's convention.
        """
        if self._applied_value is not None:
            return self._applied_value
        return self.native_max_value

    async def async_set_native_value(self, value: float) -> None:
        """Apply a new MaxCurrent (works mid-charge; no borne reboot).

        Fail-closed: anything short of `ok` leaves the displayed value alone
        and raises. A PARTIAL outcome (confirmed amps but not ok — not
        expected from the current server) is reported as its own message rather than a
        generic failure — the borne may already hold the new setting, and the
        owner needs to know that to decide whether to retry.
        """
        if self._lock.locked():
            raise HomeAssistantError(
                "A command is already in progress for this charger"
            )

        amps = int(round(value))
        previous = self._applied_value

        async with self._lock:
            self._applied_value = float(amps)
            self.async_write_ha_state()

            def revert() -> None:
                self._applied_value = previous
                self.async_write_ha_state()

            try:
                result = await self._client.set_max_current(self._charger_id, amps)
            except ChargingInProgressError as err:
                revert()
                raise HomeAssistantError(
                    "The platform refused to change the maximum current while a "
                    "charging session is in progress — try again once the session ends"
                ) from err
            except OfflineError as err:
                revert()
                raise HomeAssistantError(
                    "Charger is offline — cannot set the maximum current"
                ) from err
            except RateLimitedError as err:
                revert()
                raise HomeAssistantError(
                    f"Too many requests — please wait {err.retry_after}s before retrying"
                ) from err
            except (ConnectError, Exception) as err:  # noqa: BLE001
                revert()
                raise HomeAssistantError(
                    f"Could not set the maximum current: {err}"
                ) from err

            if not result.get("ok"):
                step = result.get("step") or "unknown"
                confirmed = result.get("confirmed_amps")
                if confirmed is not None:
                    # Reported as confirmed but not ok (not expected from the
                    # current server) — keep showing the confirmed
                    # value, since that IS what the borne now holds.
                    self._applied_value = float(confirmed)
                    self.async_write_ha_state()
                    raise HomeAssistantError(
                        f"Maximum current {confirmed} A was written and confirmed, but the "
                        f"platform did not report a complete success ({step}). "
                        "Check the charger before retrying."
                    )
                revert()
                raise HomeAssistantError(f"Could not set the maximum current ({step})")

            confirmed = result.get("confirmed_amps")
            if confirmed is not None:
                self._applied_value = float(confirmed)
            await self.coordinator.async_request_refresh()
