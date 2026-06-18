"""Tests for the Roulez Électrique number platform (max charging current).

Covers:
  - native_min/max from server min_amps/max_amps (+ defaults when omitted)
  - native_value: current_a when reported, else the max
  - available gated on `controllable`
  - set → power-limit → (OCPP) await_command, (Wallbox) synchronous → refresh
  - rejected / offline (409) / rate limited (429) → HomeAssistantError + revert
  - per-entity lock prevents overlap
  - number created for OCPP + Wallbox, NOT for other vendors
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.roulezelectrique.api import OfflineError, RateLimitedError
from custom_components.roulezelectrique.const import (
    DEFAULT_MAX_AMPS,
    DEFAULT_MIN_AMPS,
    DOMAIN,
)
from custom_components.roulezelectrique.coordinator import CoordinatorData
from custom_components.roulezelectrique.number import RoulezElectriqueMaxCurrentNumber

from .conftest import (
    COMMAND_ACCEPTED,
    COMMAND_REJECTED,
    NON_OCPP_CHARGER,
    OCPP_CHARGER,
    WALLBOX_CHARGER,
)

# A synchronous Wallbox-style power-limit response (no id to poll).
SYNC_ACCEPTED: dict[str, Any] = {"id": None, "status": "accepted", "synchronous": True}


def _make_number(
    charger_data: dict[str, Any],
    set_return=None,
    set_side_effect=None,
    await_command_return=None,
) -> tuple[RoulezElectriqueMaxCurrentNumber, MagicMock]:
    charger_id = charger_data["id"]
    coordinator = MagicMock()
    coordinator.data = CoordinatorData(chargers={charger_id: charger_data}, account=None)
    coordinator.last_update_success = True
    coordinator._listeners = {}
    coordinator.async_request_refresh = AsyncMock()

    client = MagicMock()
    if set_side_effect is not None:
        client.set_power_limit = AsyncMock(side_effect=set_side_effect)
    else:
        client.set_power_limit = AsyncMock(
            return_value=set_return or {"id": 99, "status": "queued"}
        )
    client.await_command = AsyncMock(return_value=await_command_return or COMMAND_ACCEPTED)

    number = RoulezElectriqueMaxCurrentNumber(coordinator, client, charger_id)
    number.async_write_ha_state = MagicMock()
    return number, coordinator


# ── range / value ──────────────────────────────────────────────────────────


def test_range_from_server_bounds():
    number, _ = _make_number(WALLBOX_CHARGER)
    assert number.native_min_value == 6.0
    assert number.native_max_value == 40.0


def test_range_falls_back_to_defaults_when_omitted():
    charger = {**WALLBOX_CHARGER, "min_amps": None, "max_amps": None}
    number, _ = _make_number(charger)
    assert number.native_min_value == float(DEFAULT_MIN_AMPS)
    assert number.native_max_value == float(DEFAULT_MAX_AMPS)


def test_value_uses_current_a_when_present():
    number, _ = _make_number(WALLBOX_CHARGER)  # current_a = 16
    assert number.native_value == 16.0


def test_value_defaults_to_max_when_no_current():
    charger = {**WALLBOX_CHARGER, "current_a": None}
    number, _ = _make_number(charger)
    assert number.native_value == 40.0


def test_available_gated_on_controllable():
    number, _ = _make_number(WALLBOX_CHARGER)
    assert number.available is True

    not_ctrl = {**WALLBOX_CHARGER, "controllable": False}
    number2, _ = _make_number(not_ctrl)
    assert number2.available is False


# ── set value ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_value_wallbox_synchronous():
    """Wallbox: synchronous response → no command poll, coordinator refreshes."""
    number, coordinator = _make_number(WALLBOX_CHARGER, set_return=SYNC_ACCEPTED)

    await number.async_set_native_value(20)

    number._client.set_power_limit.assert_awaited_once_with(3, 20)
    number._client.await_command.assert_not_awaited()  # synchronous → no poll
    coordinator.async_request_refresh.assert_awaited_once()
    assert number._optimistic_value is None


@pytest.mark.asyncio
async def test_set_value_ocpp_polls_command():
    """OCPP: async command id → await_command polled until accepted."""
    number, coordinator = _make_number(OCPP_CHARGER, await_command_return=COMMAND_ACCEPTED)

    await number.async_set_native_value(24)

    number._client.set_power_limit.assert_awaited_once_with(1, 24)
    number._client.await_command.assert_awaited_once_with(99)
    coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_value_rejected_raises():
    number, coordinator = _make_number(OCPP_CHARGER, await_command_return=COMMAND_REJECTED)

    with pytest.raises(HomeAssistantError, match="rejected"):
        await number.async_set_native_value(20)

    assert number._optimistic_value is None
    coordinator.async_request_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_value_offline_raises():
    number, _ = _make_number(WALLBOX_CHARGER, set_side_effect=OfflineError("offline"))

    with pytest.raises(HomeAssistantError, match="offline"):
        await number.async_set_native_value(18)

    assert number._optimistic_value is None


@pytest.mark.asyncio
async def test_set_value_rate_limited_raises():
    number, _ = _make_number(
        WALLBOX_CHARGER, set_side_effect=RateLimitedError(retry_after=45)
    )

    with pytest.raises(HomeAssistantError, match="Too many requests"):
        await number.async_set_native_value(18)


@pytest.mark.asyncio
async def test_lock_prevents_concurrent_set():
    number, _ = _make_number(WALLBOX_CHARGER)
    async with number._lock:
        with pytest.raises(HomeAssistantError, match="in progress"):
            await number.async_set_native_value(20)


# ── platform setup gating ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_number_created_for_ocpp_and_wallbox_not_others():
    from custom_components.roulezelectrique.number import async_setup_entry

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

    ids = sorted(e._charger_id for e in added)
    assert ids == [1, 3]  # OCPP + Wallbox; Tesla (2) excluded
