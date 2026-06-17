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
    ):
        await async_setup_entry(hass, entry)

    # entry.async_on_unload should have been called (for the options listener)
    entry.async_on_unload.assert_called()
