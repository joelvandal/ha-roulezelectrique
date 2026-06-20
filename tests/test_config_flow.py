"""Tests for the Roulez Électrique config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.roulezelectrique.api import AuthError, ConnectError
from custom_components.roulezelectrique.const import (
    CONF_API_TOKEN,
    CONF_BASE_URL,
    CONF_SCAN_INTERVAL,
    DEFAULT_BASE_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

from .conftest import STATE_ENVELOPE

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_INPUT = {
    # base_url is no longer a user-supplied field — the flow uses DEFAULT_BASE_URL
    # internally. Only the API token is asked of the user.
    CONF_API_TOKEN: "test-token-valid",
}


def _patch_validate(side_effect=None, return_value=None):
    """Patch _validate_credentials on the config flow."""
    if side_effect is not None:
        return patch(
            "custom_components.roulezelectrique.config_flow."
            "RoulezElectriqueConfigFlow._validate_credentials",
            new_callable=AsyncMock,
            side_effect=side_effect,
        )
    return patch(
        "custom_components.roulezelectrique.config_flow."
        "RoulezElectriqueConfigFlow._validate_credentials",
        new_callable=AsyncMock,
        return_value=return_value or ("user-testto", None),
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_flow_happy_path():
    """Valid credentials create a config entry."""
    from custom_components.roulezelectrique.config_flow import RoulezElectriqueConfigFlow

    flow = RoulezElectriqueConfigFlow()
    flow.hass = _mock_hass()

    with _patch_validate(return_value=("user-testto", None)):
        result = await flow.async_step_user(user_input=VALID_INPUT)

    assert result["type"] == "create_entry"
    assert result["data"][CONF_BASE_URL] == DEFAULT_BASE_URL
    assert result["data"][CONF_API_TOKEN] == "test-token-valid"


@pytest.mark.asyncio
async def test_config_flow_show_form_initially():
    """No user_input → show the form."""
    from custom_components.roulezelectrique.config_flow import RoulezElectriqueConfigFlow

    flow = RoulezElectriqueConfigFlow()
    flow.hass = _mock_hass()

    result = await flow.async_step_user(user_input=None)

    assert result["type"] == "form"
    assert result["step_id"] == "user"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_flow_invalid_auth():
    """AuthError → invalid_auth error shown, form redisplayed."""
    from custom_components.roulezelectrique.config_flow import RoulezElectriqueConfigFlow

    flow = RoulezElectriqueConfigFlow()
    flow.hass = _mock_hass()

    with _patch_validate(return_value=(None, "invalid_auth")):
        result = await flow.async_step_user(user_input=VALID_INPUT)

    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_auth"


@pytest.mark.asyncio
async def test_config_flow_cannot_connect():
    """ConnectError → cannot_connect error shown."""
    from custom_components.roulezelectrique.config_flow import RoulezElectriqueConfigFlow

    flow = RoulezElectriqueConfigFlow()
    flow.hass = _mock_hass()

    with _patch_validate(return_value=(None, "cannot_connect")):
        result = await flow.async_step_user(user_input=VALID_INPUT)

    assert result["type"] == "form"
    assert result["errors"]["base"] == "cannot_connect"


@pytest.mark.asyncio
async def test_config_flow_already_configured():
    """Duplicate unique_id → already_configured abort."""
    from custom_components.roulezelectrique.config_flow import RoulezElectriqueConfigFlow

    flow = RoulezElectriqueConfigFlow()
    flow.hass = _mock_hass()

    # _AbortFlow is raised by _abort_if_unique_id_configured; the flow catches
    # it and converts to an abort result dict via async_abort (patched below).
    def raise_abort_flow():
        raise _AbortFlow("already_configured")

    with (
        _patch_validate(return_value=("user-testto", None)),
        patch.object(flow, "async_set_unique_id", return_value=None),
        patch.object(
            flow,
            "_abort_if_unique_id_configured",
            side_effect=_AbortFlow("already_configured"),
        ),
    ):
        try:
            result = await flow.async_step_user(user_input=VALID_INPUT)
        except _AbortFlow as e:
            # The real HA framework catches this internally; in our unit-test
            # shim it propagates — treat it as an abort result.
            result = {"type": "abort", "reason": e.reason}

    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"


# ---------------------------------------------------------------------------
# Reauth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reauth_confirm_success():
    """Valid reauth token updates the entry and aborts with reauth_successful."""
    from custom_components.roulezelectrique.config_flow import RoulezElectriqueConfigFlow

    flow = RoulezElectriqueConfigFlow()
    flow.hass = _mock_hass()
    flow._base_url = DEFAULT_BASE_URL

    mock_entry = _mock_entry()

    with (
        _patch_validate(return_value=("user-testto", None)),
        patch.object(flow, "_get_reauth_entry", return_value=mock_entry),
        patch.object(flow, "async_set_unique_id", return_value=None),
        patch.object(flow.hass.config_entries, "async_update_entry"),
        patch.object(
            flow.hass.config_entries,
            "async_reload",
            new_callable=AsyncMock,
        ),
    ):
        result = await flow.async_step_reauth_confirm(
            user_input={CONF_API_TOKEN: "new-valid-token"}
        )

    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"


@pytest.mark.asyncio
async def test_reauth_confirm_invalid_auth():
    """Bad new token → invalid_auth, form redisplayed."""
    from custom_components.roulezelectrique.config_flow import RoulezElectriqueConfigFlow

    flow = RoulezElectriqueConfigFlow()
    flow.hass = _mock_hass()
    flow._base_url = DEFAULT_BASE_URL

    with _patch_validate(return_value=(None, "invalid_auth")):
        result = await flow.async_step_reauth_confirm(
            user_input={CONF_API_TOKEN: "bad-token"}
        )

    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_auth"


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_options_flow_valid_interval():
    """Valid scan_interval is saved."""
    from custom_components.roulezelectrique.config_flow import RoulezElectriqueOptionsFlow

    entry = _mock_entry()
    flow = RoulezElectriqueOptionsFlow(entry)

    result = await flow.async_step_init(user_input={CONF_SCAN_INTERVAL: 120})

    assert result["type"] == "create_entry"
    assert result["data"][CONF_SCAN_INTERVAL] == 120


@pytest.mark.asyncio
async def test_options_flow_too_low():
    """scan_interval below MIN → validation error."""
    from custom_components.roulezelectrique.config_flow import RoulezElectriqueOptionsFlow

    entry = _mock_entry()
    flow = RoulezElectriqueOptionsFlow(entry)

    result = await flow.async_step_init(
        user_input={CONF_SCAN_INTERVAL: MIN_SCAN_INTERVAL - 1}
    )

    assert result["type"] == "form"
    assert CONF_SCAN_INTERVAL in result["errors"]


@pytest.mark.asyncio
async def test_options_flow_too_high():
    """scan_interval above MAX → validation error."""
    from custom_components.roulezelectrique.config_flow import RoulezElectriqueOptionsFlow

    entry = _mock_entry()
    flow = RoulezElectriqueOptionsFlow(entry)

    result = await flow.async_step_init(
        user_input={CONF_SCAN_INTERVAL: MAX_SCAN_INTERVAL + 1}
    )

    assert result["type"] == "form"
    assert CONF_SCAN_INTERVAL in result["errors"]


@pytest.mark.asyncio
async def test_options_flow_boundary_values():
    """MIN and MAX scan intervals are accepted."""
    from custom_components.roulezelectrique.config_flow import RoulezElectriqueOptionsFlow

    for value in (MIN_SCAN_INTERVAL, MAX_SCAN_INTERVAL):
        entry = _mock_entry()
        flow = RoulezElectriqueOptionsFlow(entry)
        result = await flow.async_step_init(user_input={CONF_SCAN_INTERVAL: value})
        assert result["type"] == "create_entry", f"Expected create_entry for {value}"
        assert result["data"][CONF_SCAN_INTERVAL] == value


# ---------------------------------------------------------------------------
# Internal helpers (avoid heavy HA test harness)
# ---------------------------------------------------------------------------


class _AbortFlow(Exception):
    """Simulate homeassistant FlowResultType abort."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def __reduce__(self):
        return (self.__class__, (self.reason,))


# Monkey-patch _abort_if_unique_id_configured to raise _AbortFlow
# and config flow's async_abort to return the right dict.
import homeassistant.data_entry_flow as _def  # noqa: E402

_original_abort = getattr(
    RoulezElectriqueConfigFlow if False else type(None), "async_abort", None
)


class _FakeConfigEntries:
    async def async_reload(self, entry_id: str) -> None:
        pass

    def async_update_entry(self, entry, **kwargs):
        pass


class _FakeHass:
    def __init__(self):
        self.config_entries = _FakeConfigEntries()


def _mock_hass():
    return _FakeHass()


class _FakeEntry:
    def __init__(self):
        self.entry_id = "test_entry_id"
        self.data = {
            CONF_BASE_URL: DEFAULT_BASE_URL,
            CONF_API_TOKEN: "old-token",
        }
        self.options = {}
        self.unique_id = "user-oldtok"


def _mock_entry():
    return _FakeEntry()


# Patch config flow abort to return a dict (not raise, to simplify assertions)
def _make_abort_return_dict(self, reason, **kwargs):
    return {"type": "abort", "reason": reason}


# Apply patches at module level so all flow instances in tests work
from custom_components.roulezelectrique import config_flow as _cf  # noqa: E402

_cf.RoulezElectriqueConfigFlow.async_abort = _make_abort_return_dict
_cf.RoulezElectriqueConfigFlow.async_show_form = (
    lambda self, step_id, data_schema=None, errors=None, description_placeholders=None: {
        "type": "form",
        "step_id": step_id,
        "errors": errors or {},
    }
)
_cf.RoulezElectriqueConfigFlow.async_create_entry = (
    lambda self, title, data: {"type": "create_entry", "title": title, "data": data}
)
_cf.RoulezElectriqueConfigFlow.async_set_unique_id = AsyncMock(return_value=None)
_cf.RoulezElectriqueOptionsFlow.async_show_form = (
    lambda self, step_id, data_schema=None, errors=None, **kwargs: {
        "type": "form",
        "step_id": step_id,
        "errors": errors or {},
    }
)
_cf.RoulezElectriqueOptionsFlow.async_create_entry = (
    lambda self, title, data: {"type": "create_entry", "title": title, "data": data}
)
