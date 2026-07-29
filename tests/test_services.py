"""Tests for the Roulez Électrique services."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.roulezelectrique import _async_setup_services
from custom_components.roulezelectrique.api import (
    ChargingInProgressError,
    OfflineError,
    RateLimitedError,
)
from custom_components.roulezelectrique.const import (
    DOMAIN,
    DEFAULT_MIN_AMPS,
    DEFAULT_MAX_AMPS,
)
from custom_components.roulezelectrique.coordinator import CoordinatorData, RoulezElectriqueCoordinator

from .conftest import (
    EVDUTY_CHARGER,
    OCPP_CHARGER,
)


class MockServiceCall:
    """Mock ServiceCall class for testing."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data


class MockCoordinator(RoulezElectriqueCoordinator):
    """Subclass of coordinator to pass isinstance check in service handler helper."""

    def __init__(self, data: CoordinatorData) -> None:
        self.data = data
        self.async_request_refresh = AsyncMock()


def _setup_mock_hass_for_services(charger_data: dict[str, Any]) -> tuple[MagicMock, MagicMock, dict[str, Any]]:
    """Helper to set up mock hass with coordinator and client."""
    hass = MagicMock()
    hass.data = {}

    charger_id = charger_data["id"]
    coordinator = MockCoordinator(CoordinatorData(chargers={charger_id: charger_data}, account=None))

    client = MagicMock()

    entry_id = "test_entry"
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry_id] = coordinator
    hass.data[DOMAIN][f"{entry_id}_client"] = client

    # Gather registered services
    registered_services = {}

    def mock_register(domain, service, func, schema=None):
        if domain == DOMAIN:
            registered_services[service] = func

    hass.services.async_register = MagicMock(side_effect=mock_register)

    _async_setup_services(hass)

    return hass, client, registered_services


@pytest.mark.asyncio
async def test_set_power_limit_standard_happy():
    """Test set_power_limit routes to set_power_limit for standard chargers."""
    charger_id = OCPP_CHARGER["id"]
    hass, client, services = _setup_mock_hass_for_services(OCPP_CHARGER)

    client.set_power_limit = AsyncMock(return_value={"synchronous": True})

    # Call service
    await services["set_power_limit"](MockServiceCall({"charger_id": charger_id, "amps": 16}))

    client.set_power_limit.assert_awaited_once_with(charger_id=charger_id, amps=16)
    client.set_max_current.assert_not_called()


@pytest.mark.asyncio
async def test_set_power_limit_evduty_happy():
    """Test set_power_limit routes to set_max_current for EVduty chargers."""
    charger_id = EVDUTY_CHARGER["id"]
    hass, client, services = _setup_mock_hass_for_services(EVDUTY_CHARGER)

    client.set_max_current = AsyncMock(return_value={"ok": True, "confirmed_amps": 16})

    # Call service
    await services["set_power_limit"](MockServiceCall({"charger_id": charger_id, "amps": 16}))

    client.set_max_current.assert_awaited_once_with(charger_id=charger_id, amps=16)
    client.set_power_limit.assert_not_called()


@pytest.mark.asyncio
async def test_set_power_limit_validation_standard():
    """Test set_power_limit validation for standard chargers."""
    charger_id = OCPP_CHARGER["id"]
    charger = {**OCPP_CHARGER, "max_amps": 32}
    hass, client, services = _setup_mock_hass_for_services(charger)

    # Over limit
    with pytest.raises(HomeAssistantError, match="dépasse la limite maximale de la borne"):
        await services["set_power_limit"](MockServiceCall({"charger_id": charger_id, "amps": 40}))


@pytest.mark.asyncio
async def test_set_power_limit_validation_evduty():
    """Test set_power_limit validation for EVduty chargers."""
    charger_id = EVDUTY_CHARGER["id"]
    charger = {
        **EVDUTY_CHARGER,
        "max_current_min": 6,
        "max_current_max": 32,
    }
    hass, client, services = _setup_mock_hass_for_services(charger)

    # Over max limit
    with pytest.raises(HomeAssistantError, match="doit être entre 6A et 32A pour cette borne"):
        await services["set_power_limit"](MockServiceCall({"charger_id": charger_id, "amps": 40}))

    # Under min limit
    with pytest.raises(HomeAssistantError, match="doit être entre 6A et 32A pour cette borne"):
        await services["set_power_limit"](MockServiceCall({"charger_id": charger_id, "amps": 5}))


@pytest.mark.asyncio
async def test_set_power_limit_evduty_partial_outcome():
    """Test set_power_limit EVduty partial outcome handling."""
    charger_id = EVDUTY_CHARGER["id"]
    hass, client, services = _setup_mock_hass_for_services(EVDUTY_CHARGER)

    # ok is False but confirmed_amps is set
    client.set_max_current = AsyncMock(
        return_value={"ok": False, "step": "reset_failed", "confirmed_amps": 16}
    )

    with pytest.raises(HomeAssistantError, match="written and confirmed, but the charger reboot"):
        await services["set_power_limit"](MockServiceCall({"charger_id": charger_id, "amps": 16}))


@pytest.mark.asyncio
async def test_set_power_limit_evduty_charging_in_progress():
    """Test set_power_limit EVduty raises clean error when charging in progress."""
    charger_id = EVDUTY_CHARGER["id"]
    hass, client, services = _setup_mock_hass_for_services(EVDUTY_CHARGER)

    client.set_max_current = AsyncMock(side_effect=ChargingInProgressError("Charging in progress"))

    with pytest.raises(HomeAssistantError, match="A charging session is in progress"):
        await services["set_power_limit"](MockServiceCall({"charger_id": charger_id, "amps": 16}))


@pytest.mark.asyncio
async def test_service_exception_handling():
    """Test exceptions are cleanly converted to HomeAssistantError with the new pattern."""
    charger_id = OCPP_CHARGER["id"]
    hass, client, services = _setup_mock_hass_for_services(OCPP_CHARGER)

    # Test OfflineError
    client.remote_start = AsyncMock(side_effect=OfflineError("offline"))
    with pytest.raises(HomeAssistantError, match="is offline"):
        await services["remote_start"](MockServiceCall({"charger_id": charger_id}))

    # Test RateLimitedError
    client.remote_stop = AsyncMock(side_effect=RateLimitedError(retry_after=10))
    with pytest.raises(HomeAssistantError, match="Too many requests"):
        await services["remote_stop"](MockServiceCall({"charger_id": charger_id, "transaction_id": 42}))

    # Test Generic Exception
    client.remote_start = AsyncMock(side_effect=ValueError("Some internal error"))
    with pytest.raises(HomeAssistantError, match="Could not start charge session"):
        await services["remote_start"](MockServiceCall({"charger_id": charger_id}))
