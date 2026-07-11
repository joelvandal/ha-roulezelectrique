"""Tests for the Roulez Électrique switch platform.

Covers:
  - turn_on → remote-start → await_command → accepted → refresh
  - turn_on rejected → HomeAssistantError + optimistic state reverted
  - turn_on timeout → HomeAssistantError
  - turn_off requires transaction_id
  - turn_off offline (409) → HomeAssistantError
  - turn_off rate limited (429) → HomeAssistantError
  - per-switch lock prevents overlap
  - NO switch for non-OCPP charger
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.roulezelectrique.api import ConnectError, OfflineError, RateLimitedError
from custom_components.roulezelectrique.const import DOMAIN
from custom_components.roulezelectrique.switch import RoulezElectriqueSwitch

from custom_components.roulezelectrique.switch import RoulezElectriqueLockSwitch

from .conftest import (
    AVE_CHARGER,
    COMMAND_ACCEPTED,
    COMMAND_REJECTED,
    COMMAND_TIMEOUT,
    NON_OCPP_CHARGER,
    OCPP_CHARGER,
    OCPP_CHARGER_CHARGING,
    SIGENERGY_DC_CHARGER,
    TESLA_CHARGER_LIVE,
    WALLBOX_CHARGER,
)

# Synchronous Wallbox-style response (no command id to poll).
SYNC_ACCEPTED: dict[str, Any] = {"id": None, "status": "accepted", "synchronous": True}


def _make_lock_switch(
    charger_data: dict[str, Any],
    set_return=None,
    set_side_effect=None,
) -> tuple[RoulezElectriqueLockSwitch, MagicMock]:
    """Create a lock switch with mocked coordinator + client."""
    from custom_components.roulezelectrique.coordinator import CoordinatorData

    charger_id = charger_data["id"]
    coordinator = MagicMock()
    coordinator.data = CoordinatorData(chargers={charger_id: charger_data}, account=None)
    coordinator.last_update_success = True
    coordinator._listeners = {}
    coordinator.async_request_refresh = AsyncMock()

    client = MagicMock()
    if set_side_effect is not None:
        client.set_lock = AsyncMock(side_effect=set_side_effect)
    else:
        client.set_lock = AsyncMock(return_value=set_return or SYNC_ACCEPTED)
    client.await_command = AsyncMock(return_value=COMMAND_ACCEPTED)

    switch = RoulezElectriqueLockSwitch(coordinator, client, charger_id)
    switch.async_write_ha_state = MagicMock()
    return switch, coordinator


def _make_switch(
    charger_data: dict[str, Any],
    start_return=None,
    stop_return=None,
    command_return=None,
    command_side_effect=None,
    await_command_return=None,
    await_command_side_effect=None,
) -> tuple[RoulezElectriqueSwitch, MagicMock]:
    """Create a switch entity with mocked coordinator and API client.

    async_write_ha_state is patched to a no-op because the entity has no
    `hass` assigned in pure-unit tests (the HA runtime normally sets it).
    """
    from custom_components.roulezelectrique.coordinator import CoordinatorData

    charger_id = charger_data["id"]
    coordinator = MagicMock()
    coordinator.data = CoordinatorData(chargers={charger_id: charger_data}, account=None)
    coordinator.last_update_success = True
    coordinator._listeners = {}
    coordinator.async_request_refresh = AsyncMock()

    client = MagicMock()
    client.remote_start = AsyncMock(
        return_value=start_return or {"id": 99, "status": "queued"}
    )
    client.remote_stop = AsyncMock(
        return_value=stop_return or {"id": 99, "status": "queued"}
    )
    if await_command_side_effect is not None:
        client.await_command = AsyncMock(side_effect=await_command_side_effect)
    else:
        client.await_command = AsyncMock(
            return_value=await_command_return or COMMAND_ACCEPTED
        )

    switch = RoulezElectriqueSwitch(coordinator, client, charger_id)
    # Patch out the HA state-write call — it requires hass to be set, which
    # is only done by the HA runtime when an entity is registered in a platform.
    # In unit tests we verify _optimistic_is_on directly instead.
    switch.async_write_ha_state = MagicMock()
    return switch, coordinator


# ---------------------------------------------------------------------------
# turn_on happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_turn_on_accepted():
    """turn_on: remote-start succeeds, command accepted, coordinator refreshes."""
    switch, coordinator = _make_switch(OCPP_CHARGER, await_command_return=COMMAND_ACCEPTED)

    await switch.async_turn_on()

    switch._client.remote_start.assert_awaited_once_with(1)
    switch._client.await_command.assert_awaited_once_with(99)
    coordinator.async_request_refresh.assert_awaited_once()
    # Optimistic state cleared after refresh
    assert switch._optimistic_is_on is None


# ---------------------------------------------------------------------------
# turn_on failure cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_turn_on_rejected():
    """turn_on: command rejected → HomeAssistantError, optimistic state reverted."""
    switch, coordinator = _make_switch(OCPP_CHARGER, await_command_return=COMMAND_REJECTED)

    with pytest.raises(HomeAssistantError, match="rejected"):
        await switch.async_turn_on()

    # Optimistic state must be reverted
    assert switch._optimistic_is_on is None
    # Coordinator refresh not called on failure
    coordinator.async_request_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_turn_on_timeout():
    """turn_on: command timeout → HomeAssistantError."""
    switch, coordinator = _make_switch(OCPP_CHARGER, await_command_return=COMMAND_TIMEOUT)

    with pytest.raises(HomeAssistantError, match="timeout"):
        await switch.async_turn_on()

    assert switch._optimistic_is_on is None


@pytest.mark.asyncio
async def test_turn_on_offline_409():
    """turn_on: charger offline (OfflineError/409) → HomeAssistantError."""
    switch, coordinator = _make_switch(
        OCPP_CHARGER,
        await_command_side_effect=OfflineError("offline"),
    )
    switch._client.remote_start = AsyncMock(side_effect=OfflineError("offline"))

    with pytest.raises(HomeAssistantError, match="offline"):
        await switch.async_turn_on()

    assert switch._optimistic_is_on is None


@pytest.mark.asyncio
async def test_turn_on_rate_limited_429():
    """turn_on: 429 from remote-start → HomeAssistantError with wait hint."""
    switch, coordinator = _make_switch(OCPP_CHARGER)
    switch._client.remote_start = AsyncMock(side_effect=RateLimitedError(retry_after=60))

    with pytest.raises(HomeAssistantError, match="Too many requests"):
        await switch.async_turn_on()

    assert switch._optimistic_is_on is None


# ---------------------------------------------------------------------------
# turn_off
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_turn_off_accepted():
    """turn_off: stop command sent with transaction_id, accepted, refresh called."""
    switch, coordinator = _make_switch(
        OCPP_CHARGER_CHARGING, await_command_return=COMMAND_ACCEPTED
    )

    await switch.async_turn_off()

    switch._client.remote_stop.assert_awaited_once_with(1, 42)
    coordinator.async_request_refresh.assert_awaited_once()
    assert switch._optimistic_is_on is None


@pytest.mark.asyncio
async def test_turn_off_requires_transaction_id():
    """turn_off without transaction_id → HomeAssistantError (no command sent)."""
    # OCPP_CHARGER has transaction_id=None
    switch, _ = _make_switch(OCPP_CHARGER)

    with pytest.raises(HomeAssistantError, match="transaction_id"):
        await switch.async_turn_off()

    switch._client.remote_stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_turn_off_offline_409():
    """turn_off: charger offline → HomeAssistantError."""
    switch, _ = _make_switch(OCPP_CHARGER_CHARGING)
    switch._client.remote_stop = AsyncMock(side_effect=OfflineError("offline"))

    with pytest.raises(HomeAssistantError, match="offline"):
        await switch.async_turn_off()

    assert switch._optimistic_is_on is None


@pytest.mark.asyncio
async def test_turn_off_rate_limited():
    """turn_off: 429 → HomeAssistantError."""
    switch, _ = _make_switch(OCPP_CHARGER_CHARGING)
    switch._client.remote_stop = AsyncMock(side_effect=RateLimitedError(retry_after=30))

    with pytest.raises(HomeAssistantError, match="Too many requests"):
        await switch.async_turn_off()


@pytest.mark.asyncio
async def test_turn_off_rejected():
    """turn_off: command rejected → HomeAssistantError, state reverted."""
    switch, coordinator = _make_switch(
        OCPP_CHARGER_CHARGING, await_command_return=COMMAND_REJECTED
    )

    with pytest.raises(HomeAssistantError, match="rejected"):
        await switch.async_turn_off()

    assert switch._optimistic_is_on is None
    coordinator.async_request_refresh.assert_not_awaited()


# ---------------------------------------------------------------------------
# asyncio.Lock prevents overlapping commands
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lock_prevents_concurrent_command():
    """A second turn_on while a command is in progress raises HomeAssistantError."""
    switch, coordinator = _make_switch(OCPP_CHARGER)

    # Hold the lock to simulate an in-progress command
    async with switch._lock:
        with pytest.raises(HomeAssistantError, match="in progress"):
            await switch.async_turn_on()


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def test_switch_available_when_online():
    """Switch is available when charger is online."""
    switch, _ = _make_switch(OCPP_CHARGER)
    assert switch.available is True


def test_switch_unavailable_when_offline():
    """Switch is unavailable when charger is offline."""
    # The server sets controllable = is_ocpp && online, so an offline OCPP
    # charger reports controllable=False; the switch keys off that predicate.
    offline_charger = {**OCPP_CHARGER, "online": False, "controllable": False}
    switch, _ = _make_switch(offline_charger)
    assert switch.available is False


# ---------------------------------------------------------------------------
# is_on: poll-confirmed charging
# ---------------------------------------------------------------------------


def test_is_on_reflects_charging_state():
    switch, _ = _make_switch(OCPP_CHARGER_CHARGING)
    assert switch.is_on is True


def test_is_on_false_when_not_charging():
    switch, _ = _make_switch(OCPP_CHARGER)
    assert switch.is_on is False


def test_is_on_uses_optimistic_override():
    """During a command, the optimistic state is used."""
    switch, _ = _make_switch(OCPP_CHARGER)
    switch._optimistic_is_on = True
    assert switch.is_on is True


# ---------------------------------------------------------------------------
# Non-OCPP: no switch should be created
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_switch_for_non_ocpp_charger():
    """async_setup_entry must NOT create a switch for non-OCPP chargers."""
    from custom_components.roulezelectrique.switch import async_setup_entry

    from custom_components.roulezelectrique.coordinator import CoordinatorData

    coordinator = MagicMock()
    coordinator.data = CoordinatorData(
        chargers={1: OCPP_CHARGER, 2: NON_OCPP_CHARGER},
        account=None,
    )

    hass = MagicMock()
    entry_id = "entry_id"
    # Keys must match what __init__.py stores: entry_id and f"{entry_id}_client"
    hass.data = {
        DOMAIN: {
            entry_id: coordinator,
            f"{entry_id}_client": MagicMock(),
        }
    }

    entry = MagicMock()
    entry.entry_id = entry_id

    added_entities: list = []

    # async_add_entities is called synchronously by the platform setup helper
    def add_entities(entities, **kwargs):
        added_entities.extend(entities)

    await async_setup_entry(hass, entry, add_entities)

    # Only one switch (for OCPP charger 1); non-OCPP charger 2 gets none
    assert len(added_entities) == 1
    assert added_entities[0]._charger_id == 1


# ---------------------------------------------------------------------------
# Wallbox: charge switch + lock switch created; lock switch behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wallbox_gets_charge_and_lock_switch():
    """async_setup_entry creates a charge switch AND a lock switch for Wallbox."""
    from custom_components.roulezelectrique.switch import async_setup_entry

    from custom_components.roulezelectrique.coordinator import CoordinatorData

    coordinator = MagicMock()
    coordinator.data = CoordinatorData(
        chargers={1: OCPP_CHARGER, 3: WALLBOX_CHARGER}, account=None
    )

    hass = MagicMock()
    entry_id = "entry_id"
    hass.data = {DOMAIN: {entry_id: coordinator, f"{entry_id}_client": MagicMock()}}
    entry = MagicMock()
    entry.entry_id = entry_id

    added: list = []
    await async_setup_entry(hass, entry, lambda entities, **kw: added.extend(entities))

    # OCPP → 1 charge switch; Wallbox → 1 charge switch + 1 lock switch = 3.
    assert len(added) == 3
    lock_switches = [e for e in added if isinstance(e, RoulezElectriqueLockSwitch)]
    assert len(lock_switches) == 1
    assert lock_switches[0]._charger_id == 3


# ---------------------------------------------------------------------------
# AVE: charge switch created (account-based control), NO lock switch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ave_gets_charge_switch_but_no_lock_switch():
    """async_setup_entry creates a charge switch for AVE, but no lock switch —
    ChargerActionsController's /lock route is Wallbox-only."""
    from custom_components.roulezelectrique.switch import async_setup_entry

    from custom_components.roulezelectrique.coordinator import CoordinatorData

    coordinator = MagicMock()
    coordinator.data = CoordinatorData(
        chargers={1: OCPP_CHARGER, 4: AVE_CHARGER}, account=None
    )

    hass = MagicMock()
    entry_id = "entry_id"
    hass.data = {DOMAIN: {entry_id: coordinator, f"{entry_id}_client": MagicMock()}}
    entry = MagicMock()
    entry.entry_id = entry_id

    added: list = []
    await async_setup_entry(hass, entry, lambda entities, **kw: added.extend(entities))

    # OCPP → 1 charge switch; AVE → 1 charge switch, no lock switch = 2 total.
    assert len(added) == 2
    lock_switches = [e for e in added if isinstance(e, RoulezElectriqueLockSwitch)]
    assert len(lock_switches) == 0
    charge_switch_ids = sorted(e._charger_id for e in added)
    assert charge_switch_ids == [1, 4]


@pytest.mark.asyncio
async def test_ave_charge_switch_reflects_charging_and_is_available():
    """AVE's charge switch state/availability follow the same server fields
    (controllable, charging) as OCPP/Wallbox — no AVE-specific branching."""
    switch, _ = _make_switch(AVE_CHARGER)
    assert switch.available is True
    assert switch.is_on is True


@pytest.mark.asyncio
async def test_no_switch_for_tesla_or_sigenergy_dc():
    """Tesla and Sigenergy DC are never controllable — no switch entity."""
    from custom_components.roulezelectrique.switch import async_setup_entry

    from custom_components.roulezelectrique.coordinator import CoordinatorData

    coordinator = MagicMock()
    coordinator.data = CoordinatorData(
        chargers={5: TESLA_CHARGER_LIVE, 6: SIGENERGY_DC_CHARGER}, account=None
    )

    hass = MagicMock()
    entry_id = "entry_id"
    hass.data = {DOMAIN: {entry_id: coordinator, f"{entry_id}_client": MagicMock()}}
    entry = MagicMock()
    entry.entry_id = entry_id

    added: list = []
    await async_setup_entry(hass, entry, lambda entities, **kw: added.extend(entities))

    assert added == []


def test_lock_switch_is_on_reflects_locked():
    switch, _ = _make_lock_switch({**WALLBOX_CHARGER, "locked": True})
    assert switch.is_on is True

    switch2, _ = _make_lock_switch({**WALLBOX_CHARGER, "locked": False})
    assert switch2.is_on is False


def test_lock_switch_unavailable_when_locked_unknown():
    """A null `locked` (never reported) → unavailable (state unknown)."""
    switch, _ = _make_lock_switch({**WALLBOX_CHARGER, "locked": None})
    assert switch.available is False


def test_lock_switch_unavailable_when_not_controllable():
    switch, _ = _make_lock_switch({**WALLBOX_CHARGER, "controllable": False})
    assert switch.available is False


@pytest.mark.asyncio
async def test_lock_switch_turn_on_synchronous():
    """turn_on (lock): synchronous Wallbox response → no poll, refresh called."""
    switch, coordinator = _make_lock_switch(WALLBOX_CHARGER, set_return=SYNC_ACCEPTED)

    await switch.async_turn_on()

    switch._client.set_lock.assert_awaited_once_with(3, True)
    switch._client.await_command.assert_not_awaited()
    coordinator.async_request_refresh.assert_awaited_once()
    assert switch._optimistic_locked is None


@pytest.mark.asyncio
async def test_lock_switch_turn_off_unlocks():
    switch, coordinator = _make_lock_switch(
        {**WALLBOX_CHARGER, "locked": True}, set_return=SYNC_ACCEPTED
    )

    await switch.async_turn_off()

    switch._client.set_lock.assert_awaited_once_with(3, False)
    coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_lock_switch_offline_raises():
    switch, _ = _make_lock_switch(WALLBOX_CHARGER, set_side_effect=OfflineError("x"))

    with pytest.raises(HomeAssistantError, match="offline"):
        await switch.async_turn_on()

    assert switch._optimistic_locked is None


@pytest.mark.asyncio
async def test_lock_switch_rate_limited_raises():
    switch, _ = _make_lock_switch(
        WALLBOX_CHARGER, set_side_effect=RateLimitedError(retry_after=30)
    )

    with pytest.raises(HomeAssistantError, match="Too many requests"):
        await switch.async_turn_on()


@pytest.mark.asyncio
async def test_lock_switch_lock_prevents_overlap():
    switch, _ = _make_lock_switch(WALLBOX_CHARGER)
    async with switch._lock:
        with pytest.raises(HomeAssistantError, match="in progress"):
            await switch.async_turn_on()
