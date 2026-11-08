"""Diagnostics support for Club Roulez Électrique.

The whole dump goes through ``async_redact_data`` so that neither the
credential nor anything that identifies the account or a charger leaves the
user's Home Assistant: the API token, the config entry unique id (which embeds
the first characters of the token), and each charger's name, serial number and
VIN. Everything else (status, power, current, vendor, model, firmware,
capabilities, reward totals) is kept to make bug reports useful.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_API_TOKEN, DOMAIN

# api_token / unique_id: credential and a fragment of it.
# name / serial_number / vin: identify a charger (and its owner's vehicle).
TO_REDACT = {CONF_API_TOKEN, "unique_id", "vin", "serial_number", "name"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics data for a config entry."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    coordinator_data = (
        asdict(coordinator.data)
        if coordinator is not None and coordinator.data is not None
        else None
    )

    return async_redact_data(
        {
            "entry": {
                "title": entry.title,
                "unique_id": entry.unique_id,
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
            "coordinator_data": coordinator_data,
        },
        TO_REDACT,
    )
