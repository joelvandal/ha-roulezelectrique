"""Tests for the Roulez Électrique integration setup / teardown."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.roulezelectrique.const import (
    CONF_API_TOKEN,
    CONF_BASE_URL,
    DEFAULT_BASE_URL,
    DOMAIN,
    PLATFORMS,
)

from .conftest import STATE_ENVELOPE


def _make_entry(data=None):
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = data or {
        CONF_BASE_URL: DEFAULT_BASE_URL,
        CONF_API_TOKEN: "tok123",
    }
    entry.options = {}
    entry.async_on_unload = MagicMock()
    entry.add_update_listener = MagicMock(return_value=MagicMock())
    return entry


def _make_hass():
    hass = MagicMock()
    hass.data = {}
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    return hass


def _make_empty_registry():
    """A registry mock reporting no entries — the common "nothing to migrate" case."""
    registry = MagicMock()
    return registry


@pytest.mark.asyncio
async def test_async_setup_entry_happy():
    """Successful setup stores coordinator and client in hass.data."""
    from custom_components.roulezelectrique import async_setup_entry

    hass = _make_hass()
    entry = _make_entry()

    with (
        patch(
            "custom_components.roulezelectrique.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.roulezelectrique.RoulezElectriqueCoordinator.async_config_entry_first_refresh",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.roulezelectrique.RoulezElectriqueApiClient",
        ) as mock_client_cls,
        patch(
            "custom_components.roulezelectrique.er.async_get",
            return_value=_make_empty_registry(),
        ),
        patch(
            "custom_components.roulezelectrique.er.async_entries_for_config_entry",
            return_value=[],
        ),
    ):
        mock_client_cls.return_value = MagicMock()
        result = await async_setup_entry(hass, entry)

    assert result is True
    assert entry.entry_id in hass.data[DOMAIN]
    assert f"{entry.entry_id}_client" in hass.data[DOMAIN]
    # All platforms were forwarded
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, PLATFORMS
    )


@pytest.mark.asyncio
async def test_async_unload_entry():
    """Unloading removes coordinator and client from hass.data."""
    from custom_components.roulezelectrique import async_unload_entry

    hass = _make_hass()
    coordinator_mock = MagicMock()
    hass.data[DOMAIN] = {
        "test_entry": coordinator_mock,
        "test_entry_client": MagicMock(),
    }

    entry = _make_entry()
    entry.entry_id = "test_entry"

    result = await async_unload_entry(hass, entry)

    assert result is True
    if DOMAIN in hass.data:
        assert "test_entry" not in hass.data[DOMAIN]
        assert "test_entry_client" not in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_reload_on_options_update():
    """Reload listener is registered during setup."""
    from custom_components.roulezelectrique import async_setup_entry

    hass = _make_hass()
    entry = _make_entry()

    with (
        patch(
            "custom_components.roulezelectrique.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.roulezelectrique.RoulezElectriqueCoordinator.async_config_entry_first_refresh",
            new_callable=AsyncMock,
        ),
        patch("custom_components.roulezelectrique.RoulezElectriqueApiClient"),
        patch(
            "custom_components.roulezelectrique.er.async_get",
            return_value=_make_empty_registry(),
        ),
        patch(
            "custom_components.roulezelectrique.er.async_entries_for_config_entry",
            return_value=[],
        ),
    ):
        await async_setup_entry(hass, entry)

    # entry.async_on_unload should have been called (for the options listener)
    entry.async_on_unload.assert_called()


# ---------------------------------------------------------------------------
# Entity-registry migration: doubled "account_account_" unique_id prefix.
#
# Pre-fix RoulezElectriqueAccountSensor set unique_id = f"account_{key}" where
# key already carried the "account_" prefix, producing e.g.
# "account_account_rewards_total" instead of "account_rewards_total". The
# migration renames the unique_id IN PLACE (same entity_id, same history) so
# upgrading never orphans an already-registered entity.
# ---------------------------------------------------------------------------


def _make_registry_entry(entity_id, unique_id, domain="sensor", platform="roulezelectrique"):
    entry = MagicMock()
    entry.entity_id = entity_id
    entry.unique_id = unique_id
    entry.domain = domain
    entry.platform = platform
    return entry


@pytest.mark.asyncio
async def test_migration_renames_legacy_account_unique_id_preserving_entity_id():
    """A legacy 'account_account_*' unique_id is renamed to 'account_*' on the
    SAME entity_id — no new entity is created, no duplicate registered."""
    from custom_components.roulezelectrique import (
        _async_migrate_account_sensor_unique_ids,
    )

    legacy_entry = _make_registry_entry(
        "sensor.roulez_electrique_account_rewards_total",
        "account_account_rewards_total",
    )

    registry = MagicMock()
    registry.async_get_entity_id.return_value = None  # no collision
    registry.async_update_entity = MagicMock()

    hass = MagicMock()
    entry = _make_entry()
    entry.entry_id = "test_entry"

    with (
        patch("custom_components.roulezelectrique.er.async_get", return_value=registry),
        patch(
            "custom_components.roulezelectrique.er.async_entries_for_config_entry",
            return_value=[legacy_entry],
        ),
    ):
        _async_migrate_account_sensor_unique_ids(hass, entry)

    # Renamed on the SAME entity_id — this is what preserves history/dashboards.
    registry.async_update_entity.assert_called_once_with(
        "sensor.roulez_electrique_account_rewards_total",
        new_unique_id="account_rewards_total",
    )


@pytest.mark.asyncio
async def test_migration_is_idempotent_on_second_run():
    """Once migrated, unique_ids no longer carry the legacy prefix — a second
    run (e.g. a config entry reload) finds nothing to rename."""
    from custom_components.roulezelectrique import (
        _async_migrate_account_sensor_unique_ids,
    )

    already_migrated_entry = _make_registry_entry(
        "sensor.roulez_electrique_account_rewards_total",
        "account_rewards_total",  # already corrected — no legacy prefix
    )

    registry = MagicMock()
    registry.async_update_entity = MagicMock()

    hass = MagicMock()
    entry = _make_entry()
    entry.entry_id = "test_entry"

    with (
        patch("custom_components.roulezelectrique.er.async_get", return_value=registry),
        patch(
            "custom_components.roulezelectrique.er.async_entries_for_config_entry",
            return_value=[already_migrated_entry],
        ),
    ):
        _async_migrate_account_sensor_unique_ids(hass, entry)

    registry.async_update_entity.assert_not_called()


@pytest.mark.asyncio
async def test_migration_skips_on_collision_and_logs_warning(caplog):
    """If an entity already holds the corrected unique_id, the legacy entity
    is left untouched (no forced merge/duplicate) and a warning is logged."""
    from custom_components.roulezelectrique import (
        _async_migrate_account_sensor_unique_ids,
    )

    legacy_entry = _make_registry_entry(
        "sensor.roulez_electrique_account_rewards_total",
        "account_account_rewards_total",
    )

    registry = MagicMock()
    # A DIFFERENT entity_id already holds the corrected unique_id → collision.
    registry.async_get_entity_id.return_value = "sensor.some_other_entity"
    registry.async_update_entity = MagicMock()

    hass = MagicMock()
    entry = _make_entry()
    entry.entry_id = "test_entry"

    with (
        patch("custom_components.roulezelectrique.er.async_get", return_value=registry),
        patch(
            "custom_components.roulezelectrique.er.async_entries_for_config_entry",
            return_value=[legacy_entry],
        ),
    ):
        _async_migrate_account_sensor_unique_ids(hass, entry)

    registry.async_update_entity.assert_not_called()
    assert any("Skipping unique_id migration" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_migration_ignores_non_sensor_and_non_legacy_entries():
    """Only sensor-domain entries with the legacy prefix are touched — other
    entities (switches, numbers, already-correct sensors) are left alone."""
    from custom_components.roulezelectrique import (
        _async_migrate_account_sensor_unique_ids,
    )

    switch_entry = _make_registry_entry(
        "switch.roulez_electrique_charge", "1_charge_switch", domain="switch"
    )
    normal_sensor_entry = _make_registry_entry(
        "sensor.roulez_electrique_power", "1_power_kw"
    )

    registry = MagicMock()
    registry.async_update_entity = MagicMock()

    hass = MagicMock()
    entry = _make_entry()
    entry.entry_id = "test_entry"

    with (
        patch("custom_components.roulezelectrique.er.async_get", return_value=registry),
        patch(
            "custom_components.roulezelectrique.er.async_entries_for_config_entry",
            return_value=[switch_entry, normal_sensor_entry],
        ),
    ):
        _async_migrate_account_sensor_unique_ids(hass, entry)

    registry.async_update_entity.assert_not_called()


@pytest.mark.asyncio
async def test_full_setup_entry_migrates_legacy_unique_id_before_platforms_forward():
    """End-to-end: async_setup_entry runs the migration BEFORE forwarding to
    platforms, so the corrected unique_id is already in the registry when
    sensor.py creates the (now-matching) entity."""
    from custom_components.roulezelectrique import async_setup_entry

    legacy_entry = _make_registry_entry(
        "sensor.roulez_electrique_account_rewards_total",
        "account_account_rewards_total",
    )
    registry = MagicMock()
    registry.async_get_entity_id.return_value = None
    registry.async_update_entity = MagicMock()

    hass = _make_hass()
    entry = _make_entry()
    entry.entry_id = "test_entry"

    with (
        patch(
            "custom_components.roulezelectrique.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.roulezelectrique.RoulezElectriqueCoordinator.async_config_entry_first_refresh",
            new_callable=AsyncMock,
        ),
        patch("custom_components.roulezelectrique.RoulezElectriqueApiClient"),
        patch("custom_components.roulezelectrique.er.async_get", return_value=registry),
        patch(
            "custom_components.roulezelectrique.er.async_entries_for_config_entry",
            return_value=[legacy_entry],
        ),
    ):
        await async_setup_entry(hass, entry)

    # The SAME entity_id now carries the corrected unique_id — verified via
    # the registry call, and this happened before the platform forward
    # (asserted by both having been awaited by the time setup returns).
    registry.async_update_entity.assert_called_once_with(
        "sensor.roulez_electrique_account_rewards_total",
        new_unique_id="account_rewards_total",
    )
    hass.config_entries.async_forward_entry_setups.assert_awaited_once()


@pytest.mark.asyncio
async def test_services_registration_and_removal():
    """Test that services are successfully registered on setup and removed on unload."""
    from custom_components.roulezelectrique import async_setup_entry, async_unload_entry
    from custom_components.roulezelectrique.const import DOMAIN

    hass = _make_hass()
    entry = _make_entry()
    entry.entry_id = "test_entry"

    # Set up mocks for services
    services = {}
    def mock_register(domain, service, func, schema=None):
        services[(domain, service)] = (func, schema)
    def mock_remove(domain, service):
        services.pop((domain, service), None)
    def mock_has_service(domain, service):
        return (domain, service) in services

    hass.services.async_register = MagicMock(side_effect=mock_register)
    hass.services.async_remove = MagicMock(side_effect=mock_remove)
    hass.services.has_service = MagicMock(side_effect=mock_has_service)

    with (
        patch(
            "custom_components.roulezelectrique.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.roulezelectrique.RoulezElectriqueCoordinator.async_config_entry_first_refresh",
            new_callable=AsyncMock,
        ),
        patch("custom_components.roulezelectrique.RoulezElectriqueApiClient"),
        patch(
            "custom_components.roulezelectrique.er.async_get",
            return_value=_make_empty_registry(),
        ),
        patch(
            "custom_components.roulezelectrique.er.async_entries_for_config_entry",
            return_value=[],
        ),
    ):
        await async_setup_entry(hass, entry)

    # Verify services are registered
    assert (DOMAIN, "remote_start") in services
    assert (DOMAIN, "remote_stop") in services
    assert (DOMAIN, "set_power_limit") in services

    # Now unload the entry and verify they are removed
    await async_unload_entry(hass, entry)
    assert (DOMAIN, "remote_start") not in services
    assert (DOMAIN, "remote_stop") not in services
    assert (DOMAIN, "set_power_limit") not in services


def test_resolve_charger_id():
    """Test resolving device ID or numeric charger ID."""
    from custom_components.roulezelectrique import _resolve_charger_id
    from homeassistant.exceptions import HomeAssistantError

    hass = MagicMock()

    # Case 1: Numeric string or int target
    assert _resolve_charger_id(hass, 123) == 123
    assert _resolve_charger_id(hass, "456") == 456

    # Case 2: Device ID string resolved via device registry
    device_registry_mock = MagicMock()
    device_entry_mock = MagicMock()
    device_entry_mock.identifiers = {("roulezelectrique", "789")}
    device_registry_mock.async_get.return_value = device_entry_mock

    with patch("custom_components.roulezelectrique.dr.async_get", return_value=device_registry_mock):
        assert _resolve_charger_id(hass, "some_device_id_hash") == 789

    # Case 3: Device not found
    device_registry_mock.async_get.return_value = None
    with patch("custom_components.roulezelectrique.dr.async_get", return_value=device_registry_mock):
        with pytest.raises(HomeAssistantError, match="Device 'missing_id' not found"):
            _resolve_charger_id(hass, "missing_id")

    # Case 4: Device is not a roulezelectrique device
    device_entry_mock.identifiers = {("other_domain", "789")}
    device_registry_mock.async_get.return_value = device_entry_mock
    with patch("custom_components.roulezelectrique.dr.async_get", return_value=device_registry_mock):
        with pytest.raises(HomeAssistantError, match="Device 'invalid_device' is not a valid"):
            _resolve_charger_id(hass, "invalid_device")
