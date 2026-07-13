"""Switch platform for the Roulez Électrique integration.

Two switch types:
  - Charge switch: created for every CONTROLLABLE-capable charger — OCPP,
    Wallbox, AVE and Sigenergy (AC + DC) bornes. on = charging; toggling
    calls remote-start/stop.
  - Lock switch: Wallbox ONLY — on = borne locked; toggling calls POST
    /chargers/{id}/lock {locked}. OCPP/AVE/Sigenergy have no lock concept (no
    lock switch).

The server's `controllable` predicate decides runtime availability (OCPP: live
WebSocket; Wallbox/AVE: active account; Sigenergy AC/DC: active linked
account). Other vendors (Tesla, …) are never controllable and get NO switch.

Switch behavior:
  - is_on: poll-confirmed `charging` value from coordinator
  - available: requires server `controllable` (pre-emptive check; avoids 409)
  - turn_on: POST remote-start → (OCPP) await_command, (Wallbox/AVE/Sigenergy)
    synchronous
  - turn_off: POST remote-stop → (OCPP) await_command, (Wallbox/AVE/Sigenergy)
    synchronous

OCPP vs synchronous-vendor control flow:
  - OCPP returns {id, status} and the command runs async on the borne — we
    poll GET /commands/{id} via await_command until a terminal status.
  - Wallbox, AVE and Sigenergy all return
    {id: null, status: "accepted", synchronous: true} — the cloud call
    already completed (or fail-closed errored) through the SAME
    /remote-start and /remote-stop endpoints the client already calls (the
    server branches AC vs DC internally for Sigenergy). We MUST NOT poll a
    null id: when `synchronous` is true (or id is null) we skip await_command
    and refresh the coordinator immediately.

Error handling (fail-closed):
  - rejected/timeout/failed → revert optimistic state + raise HomeAssistantError
  - 409 offline → HomeAssistantError (charger went offline between poll + action)
  - 429 rate limited → HomeAssistantError
  - Per-switch asyncio.Lock: prevents two overlapping commands on the same switch

Note: `transaction_id` is populated in coordinator data only while a charge
session is active on an OCPP charger. For OCPP, turn_off raises
HomeAssistantError if no transaction_id is present (safe: can't stop what
isn't started). Wallbox pause IS the stop and needs no transaction_id.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import ConnectError, OfflineError, RateLimitedError, RoulezElectriqueApiClient
from .const import DOMAIN
from .coordinator import RoulezElectriqueCoordinator
from .entity import RoulezElectriqueEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch entities from a config entry.

    Controllable-capable chargers (OCPP, Wallbox, AVE or Sigenergy AC/DC) get
    a charge switch. Wallbox bornes additionally get a lock switch. Other
    vendors are skipped.
    """
    coordinator: RoulezElectriqueCoordinator = hass.data[DOMAIN][entry.entry_id]
    client: RoulezElectriqueApiClient = hass.data[DOMAIN][f"{entry.entry_id}_client"]

    entities: list[RoulezElectriqueEntity] = []
    charger_map = coordinator.data.chargers if coordinator.data else {}
    for charger_id, charger_data in charger_map.items():
        # Create a switch for any controllable-capable vendor. We gate on the
        # stable vendor (OCPP, Wallbox, AVE or Sigenergy) rather than the live
        # `controllable` flag so the entity exists even while temporarily
        # uncontrollable (offline OCPP / inactive account) — `available`
        # reflects that at runtime. Other vendors (Tesla, …) never expose
        # remote control and get NO switch. Sigenergy covers both the AC and
        # DC vendor_label variants — both use the same `vendor == "sigenergy"`
        # string and the same synchronous remote-start/remote-stop calls (the
        # server branches AC vs DC internally).
        is_wallbox = charger_data.get("vendor") == "wallbox"
        is_ave = charger_data.get("vendor") == "ave"
        is_sigenergy = charger_data.get("vendor") == "sigenergy"
        if not (charger_data.get("is_ocpp") or is_wallbox or is_ave or is_sigenergy):
            _LOGGER.debug(
                "Charger %s is not controllable-capable — no switch entity created",
                charger_id,
            )
            continue
        entities.append(RoulezElectriqueSwitch(coordinator, client, charger_id))
        # Lock switch is Wallbox-only (OCPP/AVE/Sigenergy have no lock concept).
        if is_wallbox:
            entities.append(RoulezElectriqueLockSwitch(coordinator, client, charger_id))

    async_add_entities(entities)


class RoulezElectriqueSwitch(RoulezElectriqueEntity, SwitchEntity):
    """A switch entity that starts/stops an OCPP charge session.

    Availability is tied to the charger being online.
    A per-instance asyncio.Lock prevents overlapping commands.
    """

    _attr_translation_key = "charge"
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(
        self,
        coordinator: RoulezElectriqueCoordinator,
        client: RoulezElectriqueApiClient,
        charger_id: int,
    ) -> None:
        super().__init__(coordinator, charger_id)
        self._client = client
        self._attr_unique_id = f"{charger_id}_charge_switch"
        self._lock = asyncio.Lock()
        # Optimistic state overlay: None = use coordinator data
        self._optimistic_is_on: bool | None = None

    async def _resolve_command(self, result: dict[str, Any]) -> dict[str, Any]:
        """Turn a remote-start/stop response into a terminal command dict.

        OCPP returns {id, status} with an async command to poll. Wallbox
        returns {id: null, status: "accepted", synchronous: true} — the cloud
        call already completed, so we MUST NOT poll a null id. When the
        response is synchronous (or carries no id), return it as-is; otherwise
        poll GET /commands/{id} until terminal.
        """
        if result.get("synchronous") or result.get("id") is None:
            return result
        return await self._client.await_command(result["id"])

    @property
    def available(self) -> bool:
        """Switch available only when the charger is controllable (pre-emptive 409 guard).

        Consume the server's authoritative `controllable` predicate (= is_ocpp &&
        online, and whatever else the platform may add later) rather than
        re-deriving it from `online` here — so the switch can never drift from
        the server's source of truth and fail-closed on press.
        """
        if not super().available:
            return False
        return bool(self._charger_data.get("controllable"))

    @property
    def is_on(self) -> bool:
        """Return True if the charger is charging.

        During a command in-flight, falls back to coordinator's last known value.
        The optimistic overlay is reset after coordinator refresh.
        """
        if self._optimistic_is_on is not None:
            return self._optimistic_is_on
        return bool(self._charger_data.get("charging"))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Send a remote-start command and wait for acceptance.

        Raises HomeAssistantError if:
          - command is rejected, times out, or fails (HA shows a red toast)
          - charger went offline (409)
          - rate limited (429)
          - lock is already held by an in-progress command
        """
        if self._lock.locked():
            raise HomeAssistantError(
                "A command is already in progress for this charger"
            )

        async with self._lock:
            # Optimistic UI: show as ON while command is in-flight
            self._optimistic_is_on = True
            self.async_write_ha_state()

            try:
                result = await self._client.remote_start(self._charger_id)
                cmd = await self._resolve_command(result)
            except OfflineError as err:
                self._optimistic_is_on = None
                self.async_write_ha_state()
                raise HomeAssistantError(
                    "Charger is offline — cannot start charge session"
                ) from err
            except RateLimitedError as err:
                self._optimistic_is_on = None
                self.async_write_ha_state()
                raise HomeAssistantError(
                    f"Too many requests — please wait {err.retry_after}s before retrying"
                ) from err
            except (ConnectError, Exception) as err:  # noqa: BLE001
                self._optimistic_is_on = None
                self.async_write_ha_state()
                raise HomeAssistantError(f"Could not start charge session: {err}") from err

            final_status = cmd.get("status", "")
            if final_status != "accepted":
                # Command was sent but rejected/timed out — revert optimistic state
                self._optimistic_is_on = None
                self.async_write_ha_state()
                error_detail = cmd.get("error") or cmd.get("result") or final_status
                raise HomeAssistantError(
                    f"Remote start {final_status}: {error_detail}"
                )

            # Accepted — refresh coordinator to get the new charging state
            self._optimistic_is_on = None
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Send a remote-stop command.

        Requires a `transaction_id` in the coordinator data — cannot stop
        a session that isn't tracked (raises HomeAssistantError).

        Raises HomeAssistantError if:
          - no transaction_id (session not active / not tracked)
          - command rejected/timeout/failed
          - charger offline (409) or rate limited (429)
          - lock held by in-progress command
        """
        if self._lock.locked():
            raise HomeAssistantError(
                "A command is already in progress for this charger"
            )

        # OCPP needs the active transaction id to stop a specific session.
        # Wallbox pause IS the stop and ignores transaction_id, so don't gate
        # the Wallbox stop on a transaction id it never reports.
        is_ocpp = bool(self._charger_data.get("is_ocpp"))
        transaction_id = self._charger_data.get("transaction_id")
        if is_ocpp and not transaction_id:
            raise HomeAssistantError(
                "No active transaction — cannot stop charge session "
                "(no transaction_id reported by charger)"
            )

        async with self._lock:
            # Optimistic UI: show as OFF while command is in-flight
            self._optimistic_is_on = False
            self.async_write_ha_state()

            try:
                # transaction_id is required by the API client signature but is
                # ignored server-side for Wallbox (pause = stop). Pass 0 when we
                # have no OCPP transaction (Wallbox path).
                result = await self._client.remote_stop(
                    self._charger_id, transaction_id or 0
                )
                cmd = await self._resolve_command(result)
            except OfflineError as err:
                self._optimistic_is_on = None
                self.async_write_ha_state()
                raise HomeAssistantError(
                    "Charger is offline — cannot stop charge session"
                ) from err
            except RateLimitedError as err:
                self._optimistic_is_on = None
                self.async_write_ha_state()
                raise HomeAssistantError(
                    f"Too many requests — please wait {err.retry_after}s before retrying"
                ) from err
            except (ConnectError, Exception) as err:  # noqa: BLE001
                self._optimistic_is_on = None
                self.async_write_ha_state()
                raise HomeAssistantError(f"Could not stop charge session: {err}") from err

            final_status = cmd.get("status", "")
            if final_status != "accepted":
                # Revert: the stop was rejected, the session may still be active
                self._optimistic_is_on = None
                self.async_write_ha_state()
                error_detail = cmd.get("error") or cmd.get("result") or final_status
                raise HomeAssistantError(
                    f"Remote stop {final_status}: {error_detail}"
                )

            # Accepted — refresh coordinator
            self._optimistic_is_on = None
            await self.coordinator.async_request_refresh()


class RoulezElectriqueLockSwitch(RoulezElectriqueEntity, SwitchEntity):
    """A switch that locks/unlocks a Wallbox borne.

    on = locked. Reflects the server `locked` flag (null → unknown). Toggling
    calls POST /chargers/{id}/lock {locked} — a synchronous Wallbox cloud call.
    A per-instance asyncio.Lock prevents overlapping lock commands.
    """

    _attr_translation_key = "lock"
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(
        self,
        coordinator: RoulezElectriqueCoordinator,
        client: RoulezElectriqueApiClient,
        charger_id: int,
    ) -> None:
        super().__init__(coordinator, charger_id)
        self._client = client
        self._attr_unique_id = f"{charger_id}_lock_switch"
        self._lock = asyncio.Lock()
        # Optimistic state overlay: None = use coordinator data.
        self._optimistic_locked: bool | None = None

    async def _resolve_command(self, result: dict[str, Any]) -> dict[str, Any]:
        """Lock is a synchronous Wallbox call; only poll if a real id is returned."""
        if result.get("synchronous") or result.get("id") is None:
            return result
        return await self._client.await_command(result["id"])

    @property
    def available(self) -> bool:
        """Available only when the borne is controllable (active account).

        Also unavailable when the server has never reported a `locked` value
        (null) AND no optimistic overlay is set — the state would be unknown.
        """
        if not super().available:
            return False
        if not bool(self._charger_data.get("controllable")):
            return False
        if self._optimistic_locked is not None:
            return True
        return self._charger_data.get("locked") is not None

    @property
    def is_on(self) -> bool:
        """True when the borne is locked."""
        if self._optimistic_locked is not None:
            return self._optimistic_locked
        return bool(self._charger_data.get("locked"))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Lock the borne."""
        await self._set_locked(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Unlock the borne."""
        await self._set_locked(False)

    async def _set_locked(self, locked: bool) -> None:
        """Send a lock/unlock command (fail-closed, single-flight)."""
        if self._lock.locked():
            raise HomeAssistantError(
                "A command is already in progress for this charger"
            )

        async with self._lock:
            self._optimistic_locked = locked
            self.async_write_ha_state()

            try:
                result = await self._client.set_lock(self._charger_id, locked)
                cmd = await self._resolve_command(result)
            except OfflineError as err:
                self._optimistic_locked = None
                self.async_write_ha_state()
                raise HomeAssistantError(
                    "Charger is offline — cannot change the lock state"
                ) from err
            except RateLimitedError as err:
                self._optimistic_locked = None
                self.async_write_ha_state()
                raise HomeAssistantError(
                    f"Too many requests — please wait {err.retry_after}s before retrying"
                ) from err
            except (ConnectError, Exception) as err:  # noqa: BLE001
                self._optimistic_locked = None
                self.async_write_ha_state()
                raise HomeAssistantError(
                    f"Could not change the lock state: {err}"
                ) from err

            final_status = cmd.get("status", "")
            if final_status != "accepted":
                self._optimistic_locked = None
                self.async_write_ha_state()
                error_detail = cmd.get("error") or cmd.get("result") or final_status
                raise HomeAssistantError(
                    f"Lock command {final_status}: {error_detail}"
                )

            # Accepted — refresh so `locked` reflects the new state.
            self._optimistic_locked = None
            await self.coordinator.async_request_refresh()
