"""Roulez Électrique (BETA) Home Assistant integration.

This integration connects Home Assistant to the Roulez Électrique EV charging
rewards platform (roulezelectrique.club). It exposes your chargers as HA
devices with live sensor data. OCPP-capable chargers also get a switch entity
for remote start/stop.

BETA / EXPERIMENTAL: feature parity and API stability may change.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RoulezElectriqueApiClient
from .const import CONF_API_TOKEN, CONF_BASE_URL, DOMAIN, PLATFORMS
from .coordinator import RoulezElectriqueCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Roulez Électrique from a config entry.

    Creates the API client, coordinator, performs initial data fetch, then
    forwards setup to each entity platform.
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

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for options updates (scan_interval change) and reload the entry
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_options_update))

    return True


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
