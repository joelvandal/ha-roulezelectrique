"""Tests for the Club Roulez Électrique select platform (IYILO time zone).

Covers:
  - the time-zone select is created only for chargers whose `capabilities`
    list contains "time_zone"
  - options come from the top-level `time_zones` list; labels shown, values
    written
  - empty `time_zones` (server cold/unavailable) still shows the borne's own
    current value, never a blank/empty select
  - a current `time_zone_value` NOT among `time_zones` is still shown, never
    silently dropped or replaced
  - select → set_ave_time_zone → accepted → refresh
  - failure paths (409 offline / 429 rate limited / 502 vendor error / 422
    invalid timezone) revert the optimistic value and raise
  - unavailable when settings_controllable is False
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.roulezelectrique.api import ConnectError, OfflineError, RateLimitedError
from custom_components.roulezelectrique.const import DOMAIN
from custom_components.roulezelectrique.coordinator import CoordinatorData
from custom_components.roulezelectrique.select import RoulezElectriqueTimeZoneSelect

from .conftest import (
    AVE_CHARGER,
    AVE_CHARGER_SETTINGS_UNCONTROLLABLE,
    AVE_CHARGER_UNKNOWN_TIME_ZONE,
    AVE_CHARGER_WITH_SETTINGS,
    OCPP_CHARGER,
    TIME_ZONES,
)

# Synchronous IYILO-style response (no command id to poll).
SYNC_ACCEPTED = {"id": None, "status": "accepted", "synchronous": True}


def _make_select(
    charger_data,
    time_zones=None,
    set_return=None,
    set_side_effect=None,
) -> tuple[RoulezElectriqueTimeZoneSelect, MagicMock]:
    """Create a time-zone select with mocked coordinator + client."""
    charger_id = charger_data["id"]
    coordinator = MagicMock()
    coordinator.data = CoordinatorData(
        chargers={charger_id: charger_data},
        account=None,
        time_zones=TIME_ZONES if time_zones is None else time_zones,
    )
    coordinator.last_update_success = True
    coordinator._listeners = {}
    coordinator.async_request_refresh = AsyncMock()

    client = MagicMock()
    if set_side_effect is not None:
        client.set_ave_time_zone = AsyncMock(side_effect=set_side_effect)
    else:
        client.set_ave_time_zone = AsyncMock(return_value=set_return or SYNC_ACCEPTED)
    client.await_command = AsyncMock(return_value={"id": 99, "status": "accepted"})

    select = RoulezElectriqueTimeZoneSelect(coordinator, client, charger_id)
    select.async_write_ha_state = MagicMock()
    return select, coordinator


# ---------------------------------------------------------------------------
# async_setup_entry: capability-gated creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_creates_select_only_with_time_zone_capability():
    """async_setup_entry creates the select only for chargers whose
    `capabilities` list contains "time_zone" — absent for a regular AVE
    charger with no `capabilities` key and for OCPP."""
    from custom_components.roulezelectrique.select import async_setup_entry

    coordinator = MagicMock()
    coordinator.data = CoordinatorData(
        chargers={
            1: OCPP_CHARGER,
            4: AVE_CHARGER,
            30: AVE_CHARGER_WITH_SETTINGS,
        },
        account=None,
        time_zones=TIME_ZONES,
    )

    hass = MagicMock()
    entry_id = "entry_id"
    hass.data = {DOMAIN: {entry_id: coordinator, f"{entry_id}_client": MagicMock()}}
    entry = MagicMock()
    entry.entry_id = entry_id

    added: list = []
    await async_setup_entry(hass, entry, lambda entities, **kw: added.extend(entities))

    assert len(added) == 1
    assert added[0]._charger_id == 30
    assert isinstance(added[0], RoulezElectriqueTimeZoneSelect)


# ---------------------------------------------------------------------------
# options / current_option: normal case
# ---------------------------------------------------------------------------


def test_options_are_server_labels():
    select, _ = _make_select(AVE_CHARGER_WITH_SETTINGS)
    assert select.options == [tz["label"] for tz in TIME_ZONES]


def test_current_option_is_label_for_known_value():
    select, _ = _make_select(AVE_CHARGER_WITH_SETTINGS)
    # AVE_CHARGER_WITH_SETTINGS.time_zone_value == "America/Toronto"
    assert select.current_option == "Eastern Time (Toronto)"


def test_select_available_when_settings_controllable():
    select, _ = _make_select(AVE_CHARGER_WITH_SETTINGS)
    assert select.available is True


def test_select_unavailable_when_settings_uncontrollable():
    select, _ = _make_select(AVE_CHARGER_SETTINGS_UNCONTROLLABLE)
    assert select.available is False


# ---------------------------------------------------------------------------
# Empty options: server cold/unavailable
# ---------------------------------------------------------------------------


def test_empty_time_zones_still_shows_current_value():
    """`time_zones` == [] must not blank out a borne's own reported value —
    it becomes its own (single) option instead."""
    select, _ = _make_select(AVE_CHARGER_WITH_SETTINGS, time_zones=[])
    assert select.options == ["America/Toronto"]
    assert select.current_option == "America/Toronto"


def test_empty_time_zones_and_never_reported_value_gives_no_options():
    """Nothing known server-side AND nothing reported by the borne → no
    options, current_option is None (honestly "unknown", not a fake zero)."""
    never_reported = {**AVE_CHARGER_WITH_SETTINGS, "time_zone_value": None}
    select, _ = _make_select(never_reported, time_zones=[])
    assert select.options == []
    assert select.current_option is None


# ---------------------------------------------------------------------------
# Unknown current value: present but not in the server's time_zones list
# ---------------------------------------------------------------------------


def test_unknown_current_value_is_appended_not_dropped():
    """AVE_CHARGER_UNKNOWN_TIME_ZONE reports "America/Regina", which TIME_ZONES
    does not carry — it must still appear, appended to the known labels."""
    select, _ = _make_select(AVE_CHARGER_UNKNOWN_TIME_ZONE)
    assert select.options == [tz["label"] for tz in TIME_ZONES] + ["America/Regina"]
    assert select.current_option == "America/Regina"


# ---------------------------------------------------------------------------
# async_select_option: happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_option_accepted():
    select, coordinator = _make_select(AVE_CHARGER_WITH_SETTINGS)

    await select.async_select_option("Pacific Time (Vancouver)")

    select._client.set_ave_time_zone.assert_awaited_once_with(30, "America/Vancouver")
    coordinator.async_request_refresh.assert_awaited_once()
    assert select._optimistic_value is None


@pytest.mark.asyncio
async def test_select_current_option_again_is_a_noop():
    select, coordinator = _make_select(AVE_CHARGER_WITH_SETTINGS)

    await select.async_select_option("Eastern Time (Toronto)")

    select._client.set_ave_time_zone.assert_not_awaited()
    coordinator.async_request_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_select_unknown_option_raises():
    select, _ = _make_select(AVE_CHARGER_WITH_SETTINGS)

    with pytest.raises(HomeAssistantError, match="Unknown time zone"):
        await select.async_select_option("Not A Real Zone")

    select._client.set_ave_time_zone.assert_not_awaited()


# ---------------------------------------------------------------------------
# async_select_option: failure paths (fail-closed, revert optimistic value)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_option_offline_409_reverts():
    select, coordinator = _make_select(
        AVE_CHARGER_WITH_SETTINGS, set_side_effect=OfflineError("offline")
    )

    with pytest.raises(HomeAssistantError, match="offline"):
        await select.async_select_option("Pacific Time (Vancouver)")

    assert select._optimistic_value is None
    coordinator.async_request_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_select_option_rate_limited_429_reverts():
    select, _ = _make_select(
        AVE_CHARGER_WITH_SETTINGS, set_side_effect=RateLimitedError(retry_after=15)
    )

    with pytest.raises(HomeAssistantError, match="Too many requests"):
        await select.async_select_option("Pacific Time (Vancouver)")

    assert select._optimistic_value is None


@pytest.mark.asyncio
async def test_select_option_vendor_error_502_reverts():
    """502 vendor_error surfaces as a generic ConnectError from the client —
    caught by the broad except clause."""
    select, _ = _make_select(
        AVE_CHARGER_WITH_SETTINGS,
        set_side_effect=ConnectError("Server error 502: vendor_error"),
    )

    with pytest.raises(HomeAssistantError, match="Could not change the time zone"):
        await select.async_select_option("Pacific Time (Vancouver)")

    assert select._optimistic_value is None


@pytest.mark.asyncio
async def test_select_option_invalid_timezone_422_reverts():
    """422 invalid_timezone surfaces as the generic RoulezElectriqueError —
    also caught by the broad except clause."""
    from custom_components.roulezelectrique.api import RoulezElectriqueError

    select, _ = _make_select(
        AVE_CHARGER_WITH_SETTINGS,
        set_side_effect=RoulezElectriqueError("Unexpected HTTP 422: invalid_timezone"),
    )

    with pytest.raises(HomeAssistantError, match="Could not change the time zone"):
        await select.async_select_option("Pacific Time (Vancouver)")

    assert select._optimistic_value is None


@pytest.mark.asyncio
async def test_select_option_rejected_reverts():
    select, coordinator = _make_select(
        AVE_CHARGER_WITH_SETTINGS,
        set_return={"id": None, "status": "rejected", "synchronous": True},
    )

    with pytest.raises(HomeAssistantError, match="rejected"):
        await select.async_select_option("Pacific Time (Vancouver)")

    assert select._optimistic_value is None
    coordinator.async_request_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_select_option_lock_prevents_overlap():
    select, _ = _make_select(AVE_CHARGER_WITH_SETTINGS)
    async with select._lock:
        with pytest.raises(HomeAssistantError, match="in progress"):
            await select.async_select_option("Pacific Time (Vancouver)")
