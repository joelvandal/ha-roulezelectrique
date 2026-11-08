"""Button platform for the Club Roulez Électrique integration.

Two button types:
  - Refresh: one per charger device (every vendor). Pressing it calls
    `coordinator.async_request_refresh()` — the exact same call every write
    action (switch.py, number.py) already triggers on success — forcing an
    immediate re-poll of the server's cached state. A local, no-side-effect
    action: it never calls a vendor API and cannot itself fail.
  - Reboot: IYILO ONLY (server capability "reboot"; IYILO is the vendor this
    repo calls "ave" on the wire). Pressing it calls
    POST /chargers/{id}/ave/reboot and DOES power-cycle the physical borne —
    unlike Refresh, this has a real, disruptive side effect and interrupts
    any charging session in progress. See the class docstring below for why
    that matters here specifically (HA gives buttons no confirmation step).

Why Refresh exists: HA's own writes (start/stop, lock, set current) already
self-refresh instantly, so HA→app changes are never stale. But a change made
OUTSIDE Home Assistant (e.g. from the Club Roulez Électrique mobile app) is only
ever picked up by HA's periodic poll (`DEFAULT_SCAN_INTERVAL` /
the `scan_interval` option, see const.py), up to that many seconds later.
Re-opening the HA companion app does NOT force a poll — it only re-reads HA
Core's already-cached state — so there was previously no way for a user to
force an immediate re-check from the app. Refresh is that action.

`async_request_refresh()` only re-reads the server's already-cached state (see
coordinator.py's module docstring) — it never calls a vendor API and cannot
itself fail in a way that needs a fail-closed HomeAssistantError, unlike the
switch/number write paths, and unlike Reboot below.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from typing import Any

import logging

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
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
    """Set up buttons from a config entry: one refresh button per charger
    device, plus one reboot button for every IYILO-capable ("reboot"
    capability) charger."""
    coordinator: RoulezElectriqueCoordinator = hass.data[DOMAIN][entry.entry_id]
    client: RoulezElectriqueApiClient = hass.data[DOMAIN][f"{entry.entry_id}_client"]

    def _build(data: CoordinatorData) -> list[tuple[Hashable, Callable[[], Any]]]:
        found: list[tuple[Hashable, Callable[[], Any]]] = []
        for charger_id, charger_data in data.chargers.items():
            found.append(
                (
                    (charger_id, "refresh"),
                    lambda cid=charger_id: RoulezElectriqueRefreshButton(coordinator, cid),
                )
            )
            if "reboot" in charger_data.get("capabilities", []):
                found.append(
                    (
                        (charger_id, "reboot"),
                        lambda cid=charger_id: RoulezElectriqueRebootButton(
                            coordinator, client, cid
                        ),
                    )
                )
        return found

    async_add_entities_dynamically(entry, coordinator, async_add_entities, _build)


class RoulezElectriqueRefreshButton(RoulezElectriqueEntity, ButtonEntity):
    """A button that forces an immediate coordinator refresh.

    Always available, even when the coordinator's last update failed or this
    charger has no data yet (`RoulezElectriqueEntity.available` would
    otherwise report unavailable): a button whose only job is "check again
    now" must keep working exactly when the user most needs to press it.
    """

    _attr_translation_key = "refresh"
    _attr_icon = "mdi:refresh"
    # A "check again now" maintenance action, not one of the charger's primary
    # controls (charge/lock switches, current slider) — categorise it as CONFIG
    # so HA files it under the device's Configuration section instead of
    # cluttering the main controls (matches HA-core reboot/reconnect buttons).
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: RoulezElectriqueCoordinator,
        charger_id: int,
    ) -> None:
        super().__init__(coordinator, charger_id)
        self._attr_unique_id = f"{charger_id}_refresh"

    @property
    def available(self) -> bool:
        """Always available — see the class docstring."""
        return True

    async def async_press(self) -> None:
        """Force an immediate coordinator refresh."""
        await self.coordinator.async_request_refresh()


class RoulezElectriqueRebootButton(RoulezElectriqueEntity, ButtonEntity):
    """A button that IMMEDIATELY REBOOTS the physical IYILO borne.

    IYILO-only (server capability "reboot"; IYILO is the vendor this repo
    calls "ave" on the wire). Pressing it calls POST
    /chargers/{id}/ave/reboot — a SYNCHRONOUS IYILO cloud call that
    power-cycles the charger, interrupting any charging session in progress.

    Home Assistant offers NO confirmation dialog for button entities — press
    is fired the instant the tile/service is triggered, with no "are you
    sure?" step anywhere in HA's own UI. This is therefore filed under
    Configuration (EntityCategory.CONFIG, keeping it out of the primary
    controls row) and uses the RESTART device class plus the strongest
    icon/name wording HA allows on a button, so at least the label itself
    warns before the tap that this is disruptive — there is no other guard
    HA provides.
    """

    _attr_translation_key = "reboot"
    _attr_icon = "mdi:restart-alert"
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG
    # DISABLED BY DEFAULT, deliberately. The website's own reboot control asks
    # for a two-step confirmation first ("the charger restarts and briefly goes
    # offline. An active charging session will stop." — lang/*/iyilo.php,
    # reboot_confirm_detail); Home Assistant has no equivalent step for a
    # button, and a button is reachable from a dashboard tap, a script, an
    # automation and a voice assistant. Shipping it enabled would put a
    # zero-confirmation power cycle of a real charger one misheard voice
    # command away. Whoever wants it turns it on once in the entity settings,
    # which is the deliberate act HA otherwise never asks for.
    #
    # NOT gated on "is it charging right now" on purpose: a borne stuck in a
    # phantom session is exactly when an owner needs to reboot it, so refusing
    # mid-charge would block the one recovery this button exists for.
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: RoulezElectriqueCoordinator,
        client: RoulezElectriqueApiClient,
        charger_id: int,
    ) -> None:
        super().__init__(coordinator, charger_id)
        self._client = client
        self._attr_unique_id = f"{charger_id}_reboot"

    @property
    def available(self) -> bool:
        """Available only when settings are controllable on this borne.

        `settings_controllable` — false for an inactive IYILO account or a
        retired borne — is a SEPARATE flag from `controllable` (the charge
        switch's gate); see switch.py's module docstring.
        """
        if not super().available:
            return False
        return bool(self._charger_data.get("settings_controllable"))

    async def async_press(self) -> None:
        """Reboot the borne now (fail-closed: any failure raises).

        Raises HomeAssistantError if the charger is offline (409) or rate
        limited (429), or on any other failure (including a 502 vendor
        error).
        """
        try:
            await self._client.reboot_ave_charger(self._charger_id)
        except OfflineError as err:
            raise HomeAssistantError(
                "Charger is offline — cannot reboot"
            ) from err
        except RateLimitedError as err:
            raise HomeAssistantError(
                f"Too many requests — please wait {err.retry_after}s before retrying"
            ) from err
        except (ConnectError, Exception) as err:  # noqa: BLE001
            raise HomeAssistantError(f"Could not reboot charger: {err}") from err

        await self.coordinator.async_request_refresh()
