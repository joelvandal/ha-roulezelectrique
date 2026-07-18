"""Roulez Électrique Home Assistant integration.

This integration connects Home Assistant to the Roulez Électrique EV charging
rewards platform (roulezelectrique.club). It exposes your chargers as HA
devices with live sensor data. OCPP-capable chargers also get a switch entity
for remote start/stop.
"""

from __future__ import annotations

import logging
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OfflineError, RateLimitedError, RoulezElectriqueApiClient
from .const import CONF_API_TOKEN, CONF_BASE_URL, DOMAIN, PLATFORMS
from .coordinator import RoulezElectriqueCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_REMOTE_START = "remote_start"
SERVICE_REMOTE_STOP = "remote_stop"
SERVICE_SET_POWER_LIMIT = "set_power_limit"

SERVICE_REMOTE_START_SCHEMA = vol.Schema(
    {
        vol.Required("charger_id"): cv.string,
        vol.Optional("connector_id"): cv.positive_int,
        vol.Optional("id_tag"): cv.string,
    }
)

SERVICE_REMOTE_STOP_SCHEMA = vol.Schema(
    {
        vol.Required("charger_id"): cv.string,
        vol.Optional("transaction_id"): cv.positive_int,
    }
)

SERVICE_SET_POWER_LIMIT_SCHEMA = vol.Schema(
    {
        vol.Required("charger_id"): cv.string,
        vol.Required("amps"): cv.positive_int,
    }
)


def _resolve_charger_id(hass: HomeAssistant, target: str) -> int:
    """Resolve a device ID or numeric charger ID to the internal integer charger ID."""
    try:
        return int(target)
    except ValueError:
        pass

    device_registry = dr.async_get(hass)
    device_entry = device_registry.async_get(target)
    if not device_entry:
        raise HomeAssistantError(f"Device '{target}' not found in Home Assistant")

    for identifier in device_entry.identifiers:
        if identifier[0] == DOMAIN:
            try:
                return int(identifier[1])
            except ValueError:
                continue

    raise HomeAssistantError(f"Device '{target}' is not a valid Roulez Électrique charger")


def _get_client_and_coordinator(
    hass: HomeAssistant, charger_id: int
) -> tuple[RoulezElectriqueApiClient, RoulezElectriqueCoordinator] | tuple[None, None]:
    """Find the client and coordinator for a given charger_id across all entries."""
    for entry_id, val in hass.data.get(DOMAIN, {}).items():
        if isinstance(val, RoulezElectriqueCoordinator):
            if val.data and charger_id in val.data.chargers:
                client = hass.data[DOMAIN].get(f"{entry_id}_client")
                if client:
                    return client, val
    return None, None


def _async_setup_services(hass: HomeAssistant) -> None:
    """Set up the services for Roulez Électrique."""

    async def async_handle_remote_start(call) -> None:
        raw_charger_id = call.data["charger_id"]
        charger_id = _resolve_charger_id(hass, raw_charger_id)
        connector_id = call.data.get("connector_id")
        id_tag = call.data.get("id_tag")

        client, coordinator = _get_client_and_coordinator(hass, charger_id)
        if not client or not coordinator:
            raise HomeAssistantError(f"Charger with ID {charger_id} not found in any integration entry")

        try:
            result = await client.remote_start(
                charger_id=charger_id,
                connector_id=connector_id,
                id_tag=id_tag,
            )
            if not result.get("synchronous") and result.get("id") is not None:
                cmd = await client.await_command(result["id"])
                final_status = cmd.get("status", "")
                if final_status != "accepted":
                    error_detail = cmd.get("error") or cmd.get("result") or final_status
                    raise HomeAssistantError(f"Remote start {final_status}: {error_detail}")
            await coordinator.async_request_refresh()
        except OfflineError as err:
            raise HomeAssistantError(f"Charger {charger_id} is offline — cannot start charge session") from err
        except RateLimitedError as err:
            raise HomeAssistantError(f"Too many requests — please wait {err.retry_after}s before retrying") from err
        except Exception as err:
            if isinstance(err, HomeAssistantError):
                raise
            raise HomeAssistantError(f"Could not start charge session on charger {charger_id}: {err}") from err

    async def async_handle_remote_stop(call) -> None:
        raw_charger_id = call.data["charger_id"]
        charger_id = _resolve_charger_id(hass, raw_charger_id)
        transaction_id = call.data.get("transaction_id")

        client, coordinator = _get_client_and_coordinator(hass, charger_id)
        if not client or not coordinator:
            raise HomeAssistantError(f"Charger with ID {charger_id} not found in any integration entry")

        if transaction_id is None:
            charger_data = coordinator.data.chargers.get(charger_id, {})
            is_ocpp = bool(charger_data.get("is_ocpp"))
            transaction_id = charger_data.get("transaction_id")
            if is_ocpp and not transaction_id:
                raise HomeAssistantError(
                    f"No active transaction for charger {charger_id} — cannot stop charge session (no transaction_id reported)"
                )

        try:
            result = await client.remote_stop(
                charger_id=charger_id,
                transaction_id=transaction_id or 0,
            )
            if not result.get("synchronous") and result.get("id") is not None:
                cmd = await client.await_command(result["id"])
                final_status = cmd.get("status", "")
                if final_status != "accepted":
                    error_detail = cmd.get("error") or cmd.get("result") or final_status
                    raise HomeAssistantError(f"Remote stop {final_status}: {error_detail}")
            await coordinator.async_request_refresh()
        except OfflineError as err:
            raise HomeAssistantError(f"Charger {charger_id} is offline — cannot stop charge session") from err
        except RateLimitedError as err:
            raise HomeAssistantError(f"Too many requests — please wait {err.retry_after}s before retrying") from err
        except Exception as err:
            if isinstance(err, HomeAssistantError):
                raise
            raise HomeAssistantError(f"Could not stop charge session on charger {charger_id}: {err}") from err

    async def async_handle_set_power_limit(call) -> None:
        raw_charger_id = call.data["charger_id"]
        charger_id = _resolve_charger_id(hass, raw_charger_id)
        amps = call.data["amps"]

        client, coordinator = _get_client_and_coordinator(hass, charger_id)
        if not client or not coordinator:
            raise HomeAssistantError(f"Charger with ID {charger_id} not found in any integration entry")

        # Validation of max_amps
        charger_data = coordinator.data.chargers.get(charger_id, {})
        max_amps = charger_data.get("max_amps")
        if max_amps is not None and amps > max_amps:
            raise HomeAssistantError(
                f"Le courant demandé de {amps}A dépasse la limite maximale de la borne ({max_amps}A)"
            )

        try:
            result = await client.set_power_limit(
                charger_id=charger_id,
                amps=amps,
            )
            if not result.get("synchronous") and result.get("id") is not None:
                cmd = await client.await_command(result["id"])
                final_status = cmd.get("status", "")
                if final_status != "accepted":
                    error_detail = cmd.get("error") or cmd.get("result") or final_status
                    raise HomeAssistantError(f"Set charging current {final_status}: {error_detail}")
            await coordinator.async_request_refresh()
        except OfflineError as err:
            raise HomeAssistantError(f"Charger {charger_id} is offline — cannot set charging current") from err
        except RateLimitedError as err:
            raise HomeAssistantError(f"Too many requests — please wait {err.retry_after}s before retrying") from err
        except Exception as err:
            if isinstance(err, HomeAssistantError):
                raise
            raise HomeAssistantError(f"Could not set charging current on charger {charger_id}: {err}") from err

    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOTE_START,
        async_handle_remote_start,
        schema=SERVICE_REMOTE_START_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOTE_STOP,
        async_handle_remote_stop,
        schema=SERVICE_REMOTE_STOP_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_POWER_LIMIT,
        async_handle_set_power_limit,
        schema=SERVICE_SET_POWER_LIMIT_SCHEMA,
    )

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

    # Register services if not already done
    if not hass.data[DOMAIN].get("services_registered"):
        _async_setup_services(hass)
        hass.data[DOMAIN]["services_registered"] = True

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

        # If no entries remain, remove services and cleanup DOMAIN dict
        remaining_entries = [
            val
            for val in hass.data.get(DOMAIN, {}).values()
            if isinstance(val, RoulezElectriqueCoordinator)
        ]
        if not remaining_entries:
            for service in [SERVICE_REMOTE_START, SERVICE_REMOTE_STOP, SERVICE_SET_POWER_LIMIT]:
                if hass.services.has_service(DOMAIN, service):
                    hass.services.async_remove(DOMAIN, service)
            hass.data.pop(DOMAIN, None)
    return unload_ok


async def _async_reload_on_options_update(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options (e.g. scan_interval) change."""
    await hass.config_entries.async_reload(entry.entry_id)
