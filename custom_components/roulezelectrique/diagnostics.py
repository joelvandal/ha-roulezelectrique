"""Diagnostics support for Roulez Électrique (BETA).

The API token is redacted to prevent accidental exposure in diagnostic dumps.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_API_TOKEN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics data for a config entry.

    Redacts the API token; all other config data and coordinator state is
    included verbatim to aid in bug reports.
    """
    data = dict(entry.data)
    if CONF_API_TOKEN in data:
        data[CONF_API_TOKEN] = "**REDACTED**"

    from .const import DOMAIN  # local import avoids circular import at module level

    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    coordinator_data = coordinator.data if coordinator else None

    return {
        "entry": {
            "title": entry.title,
            "unique_id": entry.unique_id,
            "data": data,
            "options": dict(entry.options),
        },
        "coordinator_data": coordinator_data,
    }
