"""Tests for the Club Roulez Électrique button platform (manual refresh).

Covers:
  - a refresh button is created per charger
  - pressing it calls coordinator.async_request_refresh()
  - the button is always available, even when unavailable-by-default rules
    (coordinator failure / no charger data) would apply to other entities
  - unique_id scheme: "{charger_id}_refresh"
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.roulezelectrique.button import RoulezElectriqueRefreshButton
from custom_components.roulezelectrique.const import DOMAIN
from custom_components.roulezelectrique.coordinator import CoordinatorData

from .conftest import (
    AVE_CHARGER,
    AVE_CHARGER_SETTINGS_UNCONTROLLABLE,
    AVE_CHARGER_WITH_SETTINGS,
    NON_OCPP_CHARGER,
    OCPP_CHARGER,
    WALLBOX_CHARGER,
)


def _make_button(charger_data: dict[str, Any]) -> tuple[RoulezElectriqueRefreshButton, MagicMock]:
    """Create a refresh button with a mocked coordinator."""
    charger_id = charger_data["id"]
    coordinator = MagicMock()
    coordinator.data = CoordinatorData(chargers={charger_id: charger_data}, account=None)
    coordinator.last_update_success = True
    coordinator._listeners = {}
    coordinator.async_request_refresh = AsyncMock()

    button = RoulezElectriqueRefreshButton(coordinator, charger_id)
    button.async_write_ha_state = MagicMock()
    return button, coordinator


# ---------------------------------------------------------------------------
# async_setup_entry: one button per charger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_creates_one_button_per_charger():
    """async_setup_entry creates a refresh button for every charger, any vendor."""
    from custom_components.roulezelectrique.button import async_setup_entry

    coordinator = MagicMock()
    coordinator.data = CoordinatorData(
        chargers={1: OCPP_CHARGER, 2: NON_OCPP_CHARGER, 3: WALLBOX_CHARGER},
        account=None,
    )

    hass = MagicMock()
    entry_id = "entry_id"
    hass.data = {DOMAIN: {entry_id: coordinator, f"{entry_id}_client": MagicMock()}}
    entry = MagicMock()
    entry.entry_id = entry_id

    added: list = []
    await async_setup_entry(hass, entry, lambda entities, **kw: added.extend(entities))

    assert len(added) == 3
    charger_ids = sorted(e._charger_id for e in added)
    assert charger_ids == [1, 2, 3]
    assert all(isinstance(e, RoulezElectriqueRefreshButton) for e in added)


@pytest.mark.asyncio
async def test_setup_creates_no_buttons_when_no_chargers():
    """No chargers → no refresh buttons (nothing to refresh a device for)."""
    from custom_components.roulezelectrique.button import async_setup_entry

    coordinator = MagicMock()
    coordinator.data = CoordinatorData(chargers={}, account=None)

    hass = MagicMock()
    entry_id = "entry_id"
    hass.data = {DOMAIN: {entry_id: coordinator, f"{entry_id}_client": MagicMock()}}
    entry = MagicMock()
    entry.entry_id = entry_id

    added: list = []
    await async_setup_entry(hass, entry, lambda entities, **kw: added.extend(entities))

    assert added == []


# ---------------------------------------------------------------------------
# unique_id
# ---------------------------------------------------------------------------


def test_unique_id_scheme():
    button, _ = _make_button(OCPP_CHARGER)
    assert button._attr_unique_id == "1_refresh"


# ---------------------------------------------------------------------------
# async_press → coordinator.async_request_refresh()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_press_requests_coordinator_refresh():
    """Pressing the button forces an immediate coordinator refresh."""
    button, coordinator = _make_button(OCPP_CHARGER)

    await button.async_press()

    coordinator.async_request_refresh.assert_awaited_once()


# ---------------------------------------------------------------------------
# Availability: always True, unlike every other entity in this integration
# ---------------------------------------------------------------------------


def test_button_available_when_charger_data_present():
    button, _ = _make_button(OCPP_CHARGER)
    assert button.available is True


def test_button_available_even_when_coordinator_has_no_data_for_charger():
    """A refresh button must keep working precisely when data is missing —
    that's exactly when a user needs to press it."""
    charger_id = OCPP_CHARGER["id"]
    coordinator = MagicMock()
    # No data at all for this charger (or for any charger).
    coordinator.data = CoordinatorData(chargers={}, account=None)
    coordinator.last_update_success = False
    coordinator._listeners = {}
    coordinator.async_request_refresh = AsyncMock()

    button = RoulezElectriqueRefreshButton(coordinator, charger_id)
    button.async_write_ha_state = MagicMock()

    assert button.available is True


# ---------------------------------------------------------------------------
# Reboot button (IYILO-only, capability-gated)
# ---------------------------------------------------------------------------


def _make_reboot_button(charger_data, reboot_side_effect=None):
    """Create a reboot button with mocked coordinator + client."""
    from custom_components.roulezelectrique.button import RoulezElectriqueRebootButton

    charger_id = charger_data["id"]
    coordinator = MagicMock()
    coordinator.data = CoordinatorData(chargers={charger_id: charger_data}, account=None)
    coordinator.last_update_success = True
    coordinator._listeners = {}
    coordinator.async_request_refresh = AsyncMock()

    client = MagicMock()
    if reboot_side_effect is not None:
        client.reboot_ave_charger = AsyncMock(side_effect=reboot_side_effect)
    else:
        client.reboot_ave_charger = AsyncMock(
            return_value={"id": None, "status": "accepted", "synchronous": True}
        )

    button = RoulezElectriqueRebootButton(coordinator, client, charger_id)
    button.async_write_ha_state = MagicMock()
    return button, coordinator


@pytest.mark.asyncio
async def test_setup_creates_reboot_button_only_with_capability():
    """async_setup_entry creates the reboot button only for chargers whose
    `capabilities` list contains "reboot" — absent for a regular AVE charger
    with no `capabilities` key and for OCPP/Wallbox."""
    from custom_components.roulezelectrique.button import (
        RoulezElectriqueRebootButton,
        async_setup_entry,
    )

    coordinator = MagicMock()
    coordinator.data = CoordinatorData(
        chargers={
            1: OCPP_CHARGER,
            3: WALLBOX_CHARGER,
            4: AVE_CHARGER,
            30: AVE_CHARGER_WITH_SETTINGS,
        },
        account=None,
    )

    hass = MagicMock()
    entry_id = "entry_id"
    hass.data = {DOMAIN: {entry_id: coordinator, f"{entry_id}_client": MagicMock()}}
    entry = MagicMock()
    entry.entry_id = entry_id

    added: list = []
    await async_setup_entry(hass, entry, lambda entities, **kw: added.extend(entities))

    # 4 refresh buttons (one per charger) + 1 reboot button (charger 30 only).
    reboot_buttons = [e for e in added if isinstance(e, RoulezElectriqueRebootButton)]
    assert len(reboot_buttons) == 1
    assert reboot_buttons[0]._charger_id == 30
    assert len(added) == 5


def test_reboot_button_is_disabled_by_default():
    """Owner-facing safety decision, not an accident: HA has no confirmation
    step for a button, and a button is reachable from scripts, automations and
    voice assistants. The reboot button must therefore ship disabled until
    someone enables it deliberately. The refresh button, which has no side
    effect on the borne, must stay enabled."""
    reboot, _ = _make_reboot_button(AVE_CHARGER_WITH_SETTINGS)
    assert reboot.entity_registry_enabled_default is False

    refresh = RoulezElectriqueRefreshButton(
        _make_reboot_button(AVE_CHARGER_WITH_SETTINGS)[1], 30
    )
    assert refresh.entity_registry_enabled_default is True


def test_reboot_button_available_when_settings_controllable():
    button, _ = _make_reboot_button(AVE_CHARGER_WITH_SETTINGS)
    assert button.available is True


def test_reboot_button_unavailable_when_settings_uncontrollable():
    button, _ = _make_reboot_button(AVE_CHARGER_SETTINGS_UNCONTROLLABLE)
    assert button.available is False


@pytest.mark.asyncio
async def test_reboot_button_press_calls_reboot_and_refreshes():
    button, coordinator = _make_reboot_button(AVE_CHARGER_WITH_SETTINGS)

    await button.async_press()

    button._client.reboot_ave_charger.assert_awaited_once_with(30)
    coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_reboot_button_offline_409_raises():
    from custom_components.roulezelectrique.api import OfflineError
    button, coordinator = _make_reboot_button(
        AVE_CHARGER_WITH_SETTINGS, reboot_side_effect=OfflineError("offline")
    )

    with pytest.raises(HomeAssistantError, match="offline"):
        await button.async_press()

    coordinator.async_request_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_reboot_button_rate_limited_429_raises():
    from custom_components.roulezelectrique.api import RateLimitedError
    button, _ = _make_reboot_button(
        AVE_CHARGER_WITH_SETTINGS, reboot_side_effect=RateLimitedError(retry_after=20)
    )

    with pytest.raises(HomeAssistantError, match="Too many requests"):
        await button.async_press()


@pytest.mark.asyncio
async def test_reboot_button_vendor_error_502_raises():
    from custom_components.roulezelectrique.api import ConnectError
    button, _ = _make_reboot_button(
        AVE_CHARGER_WITH_SETTINGS,
        reboot_side_effect=ConnectError("Server error 502: vendor_error"),
    )

    with pytest.raises(HomeAssistantError, match="Could not reboot"):
        await button.async_press()
