"""Shared fixtures for Roulez Électrique integration tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixture data helpers
# ---------------------------------------------------------------------------

OCPP_CHARGER: dict[str, Any] = {
    "id": 1,
    "name": "Borne OCPP",
    "serial_number": "RE-ABC123",
    "vendor": "ocpp",
    "vendor_label": "Generic OCPP",
    "is_ocpp": True,
    "controllable": True,
    "online": True,
    "status": "Available",
    "charging": False,
    "power_kw": 0.0,
    "energy_kwh": 5.3,
    "current_a": 0.0,
    "voltage_v": 240.0,
    "transaction_id": None,
    "max_amps": 32,
    "min_amps": 6,
    "locked": None,
    "plugged_in": False,
    "fresh": True,
    "stale": False,
    "last_session": {
        "occurred_at": "2026-06-01T12:00:00+00:00",
        "energy_kwh": 10.5,
        "duration_seconds": 3600,
    },
}

OCPP_CHARGER_CHARGING: dict[str, Any] = {
    **OCPP_CHARGER,
    "status": "Charging",
    "charging": True,
    "power_kw": 7.2,
    "energy_kwh": 2.1,
    "current_a": 30.0,
    "voltage_v": 240.0,
    "transaction_id": 42,
}

NON_OCPP_CHARGER: dict[str, Any] = {
    "id": 2,
    "name": "Tesla Wall Connector",
    "serial_number": "TW-XYZ789",
    "vendor": "tesla",
    "vendor_label": "Tesla",
    "is_ocpp": False,
    "controllable": False,
    "online": False,
    "status": None,
    "charging": False,
    "power_kw": None,
    "energy_kwh": None,
    "current_a": None,
    "voltage_v": None,
    "transaction_id": None,
    "max_amps": None,
    "min_amps": None,
    "locked": None,
    "plugged_in": None,
    "fresh": False,
    "stale": True,
    "last_session": {
        "occurred_at": "2026-05-15T08:00:00+00:00",
        "energy_kwh": 20.0,
        "duration_seconds": 7200,
    },
}

# A controllable Wallbox borne: active account → controllable, with the
# control metadata the server now returns (max/min amps, locked, plugged_in).
WALLBOX_CHARGER: dict[str, Any] = {
    "id": 3,
    "name": "Wallbox Pulsar",
    "serial_number": "WB-001",
    "vendor": "wallbox",
    "vendor_label": "Wallbox",
    "is_ocpp": False,
    "controllable": True,
    "online": True,
    "status": "charging",
    "charging": True,
    "power_kw": 7.2,
    "energy_kwh": 4.3,
    "current_a": 16,
    "voltage_v": None,
    "transaction_id": None,
    "max_amps": 40,
    "min_amps": 6,
    "locked": False,
    "plugged_in": True,
    "fresh": True,
    "stale": False,
    "last_session": None,
}

# A controllable AVE borne: active account → controllable AND
# current_limit_controllable (start/stop + setAmps both go through the AVE
# cloud), with a warm cached live snapshot merged in by the server.
AVE_CHARGER: dict[str, Any] = {
    "id": 4,
    "name": "AVE Borne",
    "serial_number": "AVE-001",
    "vendor": "ave",
    "vendor_label": "AVE",
    "is_ocpp": False,
    "controllable": True,
    "current_limit_controllable": True,
    "online": True,
    "status": "Charging",
    "charging": True,
    "power_kw": 7.2,
    "energy_kwh": 5.5,
    "current_a": 32,
    "voltage_v": None,
    "transaction_id": "12345",
    "max_amps": 40,
    "min_amps": 6,
    "locked": None,
    "plugged_in": True,
    "fresh": True,
    "stale": False,
    "last_session": None,
}

# A read-only Tesla Wall Connector with a warm cached live snapshot merged in
# (plugged_in + charging derived from power_w > 100 W, see TeslaLiveState).
# Never controllable — ChargerActionsController has no Tesla branch.
TESLA_CHARGER_LIVE: dict[str, Any] = {
    "id": 5,
    "name": "Tesla Wall Connector",
    "serial_number": "TESLA-LIVE-001",
    "vendor": "tesla",
    "vendor_label": "Tesla",
    "is_ocpp": False,
    "controllable": False,
    "current_limit_controllable": False,
    "online": True,
    "status": "Charging",
    "charging": True,
    "power_kw": 7.2,
    "energy_kwh": None,
    "current_a": None,
    "voltage_v": None,
    "transaction_id": None,
    "max_amps": None,
    "min_amps": None,
    "locked": None,
    "plugged_in": True,
    "fresh": False,
    "stale": False,
    "last_session": None,
}

# A read-only Sigenergy DC EVSE with a warm cached live snapshot. Never
# controllable — no DC control API exists (mutation endpoints not captured).
SIGENERGY_DC_CHARGER: dict[str, Any] = {
    "id": 6,
    "name": "Sigenergy DC",
    "serial_number": "SG-DC-001",
    "vendor": "sigenergy",
    "vendor_label": "Sigenergy (DC)",
    "is_ocpp": False,
    "controllable": False,
    "current_limit_controllable": False,
    "online": True,
    "status": "Charging",
    "charging": True,
    "power_kw": None,
    "energy_kwh": None,
    "current_a": None,
    "voltage_v": None,
    "transaction_id": None,
    "max_amps": None,
    "min_amps": None,
    "locked": None,
    "plugged_in": None,
    "fresh": False,
    "stale": False,
    "last_session": None,
}

ACCOUNT_DATA: dict[str, Any] = {
    "rewards": {
        "client": 12.50,
        "installer": 5.00,
        "referee": 1.25,
        "referrer": 0.75,
        "total": 19.50,
        "currency": "CAD",
    },
    "invitations": {
        "pending": 2,
        "accepted": 3,
        "referred": 4,
    },
    "energy_kwh_lifetime": 1234.567,
    "charger_count": 2,
}

STATE_ENVELOPE: dict[str, Any] = {
    "generated_at": "2026-06-17T10:00:00+00:00",
    "poll_interval_seconds": 30,
    "chargers": [OCPP_CHARGER],
    "account": ACCOUNT_DATA,
}

STATE_ENVELOPE_MULTI: dict[str, Any] = {
    "generated_at": "2026-06-17T10:00:00+00:00",
    "poll_interval_seconds": 30,
    "chargers": [OCPP_CHARGER, NON_OCPP_CHARGER],
    "account": ACCOUNT_DATA,
}

STATE_ENVELOPE_EMPTY: dict[str, Any] = {
    "generated_at": "2026-06-17T10:00:00+00:00",
    "poll_interval_seconds": 30,
    "chargers": [],
    "account": None,
}

# Envelope from an older server that doesn't include the account block.
STATE_ENVELOPE_NO_ACCOUNT: dict[str, Any] = {
    "generated_at": "2026-06-17T10:00:00+00:00",
    "poll_interval_seconds": 30,
    "chargers": [OCPP_CHARGER],
}

COMMAND_QUEUED: dict[str, Any] = {"id": 99, "status": "queued", "result": None, "error": None}
COMMAND_ACCEPTED: dict[str, Any] = {"id": 99, "status": "accepted", "result": None, "error": None}
COMMAND_REJECTED: dict[str, Any] = {"id": 99, "status": "rejected", "result": None, "error": "ChargePoint rejected"}
COMMAND_TIMEOUT: dict[str, Any] = {"id": 99, "status": "timeout", "result": None, "error": "No response"}
