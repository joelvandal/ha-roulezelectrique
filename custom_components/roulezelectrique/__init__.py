"""Roulez Électrique Home Assistant integration.

This integration connects Home Assistant to the Roulez Électrique EV charging
rewards platform (roulezelectrique.club). It exposes your chargers as HA
devices with live sensor data. OCPP-capable chargers also get a switch entity
for remote start/stop.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RoulezElectriqueApiClient
from .const import CONF_API_TOKEN, CONF_BASE_URL, DOMAIN, PLATFORMS
from .coordinator import RoulezElectriqueCoordinator

_LOGGER = logging.getLogger(__name__)

# The doubled prefix a pre-fix RoulezElectriqueAccountSensor produced: it set
# unique_id = f"account_{description.key}", but description.key ALREADY
# carried the "account_" prefix (e.g. "account_rewards_total"), yielding
# "account_account_rewards_total". Fixed in sensor.py to use description.key
# directly — see _async_migrate_account_sensor_unique_ids() below for the
# one-time upgrade path that preserves already-registered entities.
_LEGACY_ACCOUNT_UNIQUE_ID_PREFIX = "account_account_"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Roulez Électrique from a config entry.

    Creates the API client, coordinator, performs initial data fetch, migrates
    any stale entity-registry unique_ids from a past bug, then forwards setup
    to each entity platform.
    """
    session = async_get_clientsession(hass)
    client = RoulezElectriqueApiClient(
        session=session,
        base_url=entry.data[CONF_BASE_URL],
        api_token=entry.data[CONF_API_TOKEN],
    )

    coordinator = RoulezElectriqueCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator
    # Store client separately so switch.py can reach it for commands
    hass.data[DOMAIN][f"{entry.entry_id}_client"] = client

    # Must run BEFORE platforms are forwarded: entities are (re)created by
    # async_forward_entry_setups, and a fixed unique_id must already be in the
    # registry so the new entity created there matches the OLD (still
    # registered) row instead of being treated as a brand-new entity.
    _async_migrate_account_sensor_unique_ids(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for options updates (scan_interval change) and reload the entry
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_options_update))

    return True


def _async_migrate_account_sensor_unique_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """One-time entity-registry migration for the doubled account_ prefix bug.

    Renames each affected entity's unique_id IN PLACE via the entity registry
    (rather than letting the platform setup create a brand-new entity), so the
    upgrade preserves entity_id, history, and any dashboards/automations that
    reference it. HA keys registry rows by (platform, unique_id); an unfixed
    entity would otherwise appear as a NEW entity and the old row would go
    permanently unavailable.

    Idempotent: a second run finds no entries with the legacy prefix and does
    nothing. Fail-soft on a collision: if an entity already holds the
    corrected unique_id (e.g. a fresh entity created before this migration
    shipped), the legacy entity is left untouched and a warning is logged —
    never silently merged or duplicated.
    """
    registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.domain != "sensor" or not reg_entry.unique_id.startswith(
            _LEGACY_ACCOUNT_UNIQUE_ID_PREFIX
        ):
            continue

        corrected_unique_id = reg_entry.unique_id.removeprefix("account_")

        collision = registry.async_get_entity_id(
            reg_entry.domain, reg_entry.platform, corrected_unique_id
        )
        if collision is not None and collision != reg_entry.entity_id:
            _LOGGER.warning(
                "Skipping unique_id migration for %s (%s): an entity with the "
                "corrected unique_id %s already exists (%s)",
                reg_entry.entity_id,
                reg_entry.unique_id,
                corrected_unique_id,
                collision,
            )
            continue

        _LOGGER.info(
            "Migrating entity %s unique_id %s -> %s (doubled account_ prefix fix)",
            reg_entry.entity_id,
            reg_entry.unique_id,
            corrected_unique_id,
        )
        registry.async_update_entity(reg_entry.entity_id, new_unique_id=corrected_unique_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Roulez Électrique config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        hass.data[DOMAIN].pop(f"{entry.entry_id}_client", None)
    return unload_ok


async def _async_reload_on_options_update(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options (e.g. scan_interval) change."""
    await hass.config_entries.async_reload(entry.entry_id)
