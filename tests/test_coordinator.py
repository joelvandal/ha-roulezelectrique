"""Tests for the Roulez Électrique coordinator."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.roulezelectrique.api import AuthError, ConnectError, RateLimitedError
from custom_components.roulezelectrique.const import DEFAULT_SCAN_INTERVAL, DOMAIN

from .conftest import (
    OCPP_CHARGER,
    NON_OCPP_CHARGER,
    STATE_ENVELOPE,
    STATE_ENVELOPE_EMPTY,
    STATE_ENVELOPE_MULTI,
)


def _make_coordinator(state_return=None, state_side_effect=None):
    """Create a coordinator with a mocked API client and minimal HA mocks."""
    from custom_components.roulezelectrique.coordinator import RoulezElectriqueCoordinator

    client = MagicMock()
    if state_side_effect is not None:
        client.get_state = AsyncMock(side_effect=state_side_effect)
    else:
        client.get_state = AsyncMock(return_value=state_return or STATE_ENVELOPE)

    hass = MagicMock()
    hass.loop = MagicMock()

    entry = MagicMock()
    entry.data = {}
    entry.options = {}

    coordinator = RoulezElectriqueCoordinator.__new__(RoulezElectriqueCoordinator)
    coordinator.client = client
    coordinator._entry = entry
    coordinator.data = None
    coordinator.update_interval = timedelta(seconds=DEFAULT_SCAN_INTERVAL)
    coordinator.hass = hass
    coordinator.logger = MagicMock()
    coordinator.name = DOMAIN
    # Provide _listeners to avoid AttributeError in tests
    coordinator._listeners = {}
    coordinator._unsub_refresh = None

    return coordinator


# ---------------------------------------------------------------------------
# Happy path: parse state into charger map
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coordinator_parse_state_single_ocpp():
    """State with one OCPP charger → dict keyed by charger id."""
    from custom_components.roulezelectrique.coordinator import RoulezElectriqueCoordinator

    coordinator = _make_coordinator(state_return=STATE_ENVELOPE)
    result = await coordinator._async_update_data()

    assert 1 in result
    assert result[1]["name"] == "Borne OCPP"
    assert result[1]["is_ocpp"] is True


@pytest.mark.asyncio
async def test_coordinator_parse_state_multi():
    """State with multiple chargers → all keyed by id."""
    coordinator = _make_coordinator(state_return=STATE_ENVELOPE_MULTI)
    result = await coordinator._async_update_data()

    assert set(result.keys()) == {1, 2}
    assert result[2]["vendor"] == "tesla"


@pytest.mark.asyncio
async def test_coordinator_empty_roster():
    """Empty charger list → empty dict (not an error)."""
    coordinator = _make_coordinator(state_return=STATE_ENVELOPE_EMPTY)
    result = await coordinator._async_update_data()

    assert result == {}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coordinator_401_raises_auth_failed():
    """AuthError (401) → ConfigEntryAuthFailed to trigger reauth."""
    from homeassistant.exceptions import ConfigEntryAuthFailed

    coordinator = _make_coordinator(state_side_effect=AuthError("token revoked"))

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_coordinator_429_raises_update_failed():
    """RateLimitedError (429) → UpdateFailed + update_interval widened."""
    from homeassistant.helpers.update_coordinator import UpdateFailed

    coordinator = _make_coordinator(
        state_side_effect=RateLimitedError(retry_after=120)
    )

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    # update_interval should have been widened to Retry-After seconds
    assert coordinator.update_interval == timedelta(seconds=120)


@pytest.mark.asyncio
async def test_coordinator_connect_error_raises_update_failed():
    """ConnectError (5xx / network) → UpdateFailed."""
    from homeassistant.helpers.update_coordinator import UpdateFailed

    coordinator = _make_coordinator(
        state_side_effect=ConnectError("server unreachable")
    )

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_coordinator_interval_restored_after_rate_limit():
    """After a rate-limit, a successful refresh restores the normal interval."""
    coordinator = _make_coordinator()
    coordinator.update_interval = timedelta(seconds=120)  # simulated post-rate-limit

    await coordinator._async_update_data()

    assert coordinator.update_interval == timedelta(seconds=DEFAULT_SCAN_INTERVAL)
