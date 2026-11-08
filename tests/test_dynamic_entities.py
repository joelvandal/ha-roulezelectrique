"""Entities appear on a LATER poll, with no reload (0.11.1).

The platforms used to build their entities once, from the first poll. A
charger the server newly reports as controllable (or a charger added to the
account later) therefore needed an integration reload. Each platform now
re-checks its creation conditions on every coordinator update and adds only
the entities it has not added yet.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.roulezelectrique import binary_sensor, button, number, select, sensor, switch
from custom_components.roulezelectrique.const import DOMAIN
from custom_components.roulezelectrique.coordinator import CoordinatorData

from .conftest import OCPP_CHARGER, WALLBOX_CHARGER

# A vendor the client has no hardcoded knowledge of, not controllable yet.
NEW_VENDOR_OFF: dict[str, Any] = {
    **OCPP_CHARGER,
    "id": 50,
    "vendor": "newbrand",
    "is_ocpp": False,
    "controllable": False,
    "current_limit_controllable": False,
    "max_current_controllable": False,
    "online": False,
}
NEW_VENDOR_ON: dict[str, Any] = {
    **NEW_VENDOR_OFF,
    "controllable": True,
    "current_limit_controllable": True,
}
EVDUTY_ON: dict[str, Any] = {
    **NEW_VENDOR_OFF,
    "id": 51,
    "controllable": True,
    "max_current_controllable": True,
}


class FakeCoordinator:
    def __init__(self, chargers: dict[int, dict[str, Any]]) -> None:
        self.data = CoordinatorData(chargers=chargers, account=None)
        self.last_update_success = True
        self.listeners: list = []

    def async_add_listener(self, update_callback, context=None):
        self.listeners.append(update_callback)
        return lambda: self.listeners.remove(update_callback)

    def poll(self, chargers: dict[int, dict[str, Any]]) -> None:
        self.data = CoordinatorData(chargers=chargers, account=None)
        for cb in list(self.listeners):
            cb()


class Harness:
    def __init__(self, platform, chargers):
        self.coordinator = FakeCoordinator(chargers)
        self.added: list = []
        self.unloads: list = []
        self.entry = MagicMock()
        self.entry.entry_id = "e1"
        self.entry.async_on_unload = self.unloads.append
        self.hass = MagicMock()
        self.hass.data = {DOMAIN: {"e1": self.coordinator, "e1_client": MagicMock()}}
        self.platform = platform

    async def setup(self):
        await self.platform.async_setup_entry(
            self.hass, self.entry, lambda ents: self.added.extend(ents)
        )

    def ids(self) -> list[str]:
        return [e.unique_id for e in self.added]


@pytest.mark.asyncio
async def test_switch_and_number_appear_on_second_poll_exactly_once():
    sw = Harness(switch, {50: NEW_VENDOR_OFF})
    nb = Harness(number, {50: NEW_VENDOR_OFF})
    await sw.setup()
    await nb.setup()
    assert sw.ids() == []
    assert nb.ids() == []

    for h in (sw, nb):
        h.coordinator.poll({50: NEW_VENDOR_ON})
    assert sw.ids() == ["50_charge_switch"]
    assert nb.ids() == ["50_max_current"]

    # Third poll, and a poll where it flips off and on again: no duplicates.
    for h in (sw, nb):
        h.coordinator.poll({50: NEW_VENDOR_ON})
        h.coordinator.poll({50: NEW_VENDOR_OFF})
        h.coordinator.poll({50: NEW_VENDOR_ON})
    assert sw.ids() == ["50_charge_switch"]
    assert nb.ids() == ["50_max_current"]


@pytest.mark.asyncio
async def test_evduty_slider_appears_later():
    nb = Harness(number, {51: {**EVDUTY_ON, "max_current_controllable": False}})
    await nb.setup()
    assert nb.ids() == []
    nb.coordinator.poll({51: EVDUTY_ON})
    nb.coordinator.poll({51: EVDUTY_ON})
    assert len(nb.added) == 1
    assert type(nb.added[0]).__name__ == "RoulezElectriqueEvdutyMaxCurrentNumber"


@pytest.mark.asyncio
async def test_charger_added_to_account_later_gets_its_entities():
    harness = {
        p: Harness(p, {1: OCPP_CHARGER})
        for p in (switch, number, sensor, binary_sensor, button)
    }
    for h in harness.values():
        await h.setup()
    before = {p: h.ids() for p, h in harness.items()}
    assert "1_charge_switch" in before[switch]

    for h in harness.values():
        h.coordinator.poll({1: OCPP_CHARGER, 3: WALLBOX_CHARGER})
        h.coordinator.poll({1: OCPP_CHARGER, 3: WALLBOX_CHARGER})
    sw = harness[switch].ids()
    assert sw.count("3_charge_switch") == 1
    assert sw.count("3_lock_switch") == 1
    assert harness[number].ids().count("3_max_current") == 1
    assert len([i for i in harness[button].ids() if i.startswith("3_")]) >= 1
    # Existing entities were not re-added.
    for p, h in harness.items():
        assert len(h.ids()) == len(set(h.ids())), p
        assert h.ids()[: len(before[p])] == before[p]


@pytest.mark.asyncio
async def test_every_platform_registers_listener_and_unsubscribes():
    for p in (switch, number, sensor, binary_sensor, button, select):
        h = Harness(p, {1: OCPP_CHARGER})
        await h.setup()
        assert len(h.coordinator.listeners) == 1, p
        assert len(h.unloads) == 1, p
        h.unloads[0]()
        assert h.coordinator.listeners == [], p


@pytest.mark.asyncio
async def test_evduty_optimistic_window_never_gets_the_generic_slider():
    """Poll 1: optimistic current_limit_controllable; poll 2: EVduty flag.

    The server advertises the "max_current" capability up front, so the
    generic slider is already avoided in poll 1. Exactly one slider (EVduty).
    """
    base = {
        **OCPP_CHARGER,
        "id": 9,
        "vendor": "evduty-ocpp",
        "capabilities": ["power", "max_current"],
    }
    poll1 = {**base, "current_limit_controllable": True, "max_current_controllable": False}
    poll2 = {**base, "current_limit_controllable": False, "max_current_controllable": True}
    nb = Harness(number, {9: poll1})
    await nb.setup()
    assert nb.added == []
    nb.coordinator.poll({9: poll2})
    nb.coordinator.poll({9: poll2})
    assert [type(e).__name__ for e in nb.added] == ["RoulezElectriqueEvdutyMaxCurrentNumber"]
    # Even if the optimistic flag comes back, no generic slider is added.
    nb.coordinator.poll({9: poll1})
    assert len(nb.added) == 1


@pytest.mark.asyncio
async def test_evduty_slider_already_created_blocks_generic_even_without_capability():
    base = {**OCPP_CHARGER, "id": 9, "vendor": "evduty-ocpp"}
    on = {**base, "current_limit_controllable": False, "max_current_controllable": True}
    nb = Harness(number, {9: on})
    await nb.setup()
    nb.coordinator.poll({9: {**base, "current_limit_controllable": True}})
    assert [type(e).__name__ for e in nb.added] == ["RoulezElectriqueEvdutyMaxCurrentNumber"]
