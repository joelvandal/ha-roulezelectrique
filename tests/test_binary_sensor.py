"""Tests for the Roulez Électrique binary_sensor platform.

Covers:
  - online/charging created for every vendor
  - plugged_in created CAPABILITY-DRIVEN: whenever the server's per-charger
    `capabilities` list contains "plugged_in" (0.5.0+) — no vendor hardcoding.
    This now covers OCPP and Sigenergy AC/DC in addition to Wallbox/AVE/Tesla.
  - plugged_in NOT created when `capabilities` omits it (or is absent
    entirely, e.g. an older server / a vendor like FLO that never reports it)
  - is_on values reflect the server's generic fields (no vendor branching)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.roulezelectrique.binary_sensor import (
    BINARY_SENSOR_DESCRIPTIONS,
    RoulezElectriqueBinarySensor,
    async_setup_entry,
)
from custom_components.roulezelectrique.const import DOMAIN
from custom_components.roulezelectrique.coordinator import CoordinatorData

from .conftest import (
    AVE_CHARGER,
    BASELINE_CHARGER_FULL,
    OCPP_CHARGER_CHARGING,
    OCPP_CHARGER_FULL,
    SIGENERGY_AC_CHARGER_FULL,
    SIGENERGY_DC_CHARGER,
    TESLA_CHARGER_LIVE,
    WALLBOX_CHARGER,
)


def _make_coordinator(charger_data: dict[int, dict[str, Any]]):
    coordinator = MagicMock()
    coordinator.data = CoordinatorData(chargers=charger_data, account=None)
    coordinator.last_update_success = True
    coordinator._listeners = {}
    return coordinator


def _make_binary_sensor(
    charger_data: dict[str, Any], description_key: str
) -> RoulezElectriqueBinarySensor:
    charger_id = charger_data["id"]
    coordinator = _make_coordinator({charger_id: charger_data})
    description = next(d for d in BINARY_SENSOR_DESCRIPTIONS if d.key == description_key)
    return RoulezElectriqueBinarySensor(coordinator, charger_id, description)


async def _setup(charger_map: dict[int, dict[str, Any]]) -> list:
    coordinator = _make_coordinator(charger_map)
    hass = MagicMock()
    entry_id = "entry_id"
    hass.data = {DOMAIN: {entry_id: coordinator, f"{entry_id}_client": MagicMock()}}
    entry = MagicMock()
    entry.entry_id = entry_id

    added: list = []
    await async_setup_entry(hass, entry, lambda entities, **kw: added.extend(entities))
    return added


# ---------------------------------------------------------------------------
# Entity creation gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_online_and_charging_created_for_every_vendor():
    added = await _setup(
        {
            1: OCPP_CHARGER_CHARGING,
            3: WALLBOX_CHARGER,
            4: AVE_CHARGER,
            5: TESLA_CHARGER_LIVE,
            6: SIGENERGY_DC_CHARGER,
        }
    )
    online_ids = sorted(e._charger_id for e in added if e.entity_description.key == "online")
    charging_ids = sorted(e._charger_id for e in added if e.entity_description.key == "charging")
    assert online_ids == [1, 3, 4, 5, 6]
    assert charging_ids == [1, 3, 4, 5, 6]


@pytest.mark.asyncio
async def test_plugged_in_created_from_capability_not_vendor():
    """plugged_in is created purely from the server's `capabilities` list —
    OCPP and Sigenergy AC now report the capability too (0.5.0+), while a
    vendor whose capabilities list omits it (FLO/baseline) gets none.
    """
    added = await _setup(
        {
            10: OCPP_CHARGER_FULL,
            12: SIGENERGY_AC_CHARGER_FULL,
            14: BASELINE_CHARGER_FULL,
        }
    )
    plugged_in_ids = sorted(
        e._charger_id for e in added if e.entity_description.key == "plugged_in"
    )
    # OCPP (10) and Sigenergy AC (12) both list "plugged_in" in `capabilities`;
    # FLO/baseline (14) does not.
    assert plugged_in_ids == [10, 12]


@pytest.mark.asyncio
async def test_plugged_in_not_created_without_capabilities_key():
    """A charger dict with no `capabilities` key at all (older server, or a
    fixture predating the capability) never gets the plugged_in sensor, even
    for a vendor known to report it in production. This documents the
    intentional 0.5.0 change from a hardcoded vendor tuple to a purely
    capability-driven gate.
    """
    added = await _setup(
        {
            3: WALLBOX_CHARGER,
            4: AVE_CHARGER,
            5: TESLA_CHARGER_LIVE,
        }
    )
    plugged_in_ids = [
        e._charger_id for e in added if e.entity_description.key == "plugged_in"
    ]
    assert plugged_in_ids == []


# ---------------------------------------------------------------------------
# Values — generic across vendors, no per-vendor branching
# ---------------------------------------------------------------------------


def test_ave_plugged_in_and_charging_values():
    sensor = _make_binary_sensor(AVE_CHARGER, "plugged_in")
    assert sensor.is_on is True
    sensor2 = _make_binary_sensor(AVE_CHARGER, "charging")
    assert sensor2.is_on is True
    sensor3 = _make_binary_sensor(AVE_CHARGER, "online")
    assert sensor3.is_on is True


def test_tesla_plugged_in_and_charging_values():
    sensor = _make_binary_sensor(TESLA_CHARGER_LIVE, "plugged_in")
    assert sensor.is_on is True
    sensor2 = _make_binary_sensor(TESLA_CHARGER_LIVE, "charging")
    assert sensor2.is_on is True


def test_sigenergy_dc_online_and_charging_values():
    sensor = _make_binary_sensor(SIGENERGY_DC_CHARGER, "online")
    assert sensor.is_on is True
    sensor2 = _make_binary_sensor(SIGENERGY_DC_CHARGER, "charging")
    assert sensor2.is_on is True


def test_sigenergy_ac_plugged_in_value():
    """Sigenergy AC's plugged_in value follows the same generic field read
    as every other vendor — no Sigenergy-specific branching."""
    sensor = _make_binary_sensor(SIGENERGY_AC_CHARGER_FULL, "plugged_in")
    assert sensor.is_on is True
