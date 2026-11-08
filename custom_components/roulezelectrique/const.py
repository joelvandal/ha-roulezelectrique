"""Constants for the Club Roulez Électrique Home Assistant integration."""

DOMAIN = "roulezelectrique"
INTEGRATION_NAME = "Club Roulez Électrique"

# Config entry keys
CONF_BASE_URL = "base_url"
CONF_API_TOKEN = "api_token"
CONF_SCAN_INTERVAL = "scan_interval"

# Defaults
DEFAULT_BASE_URL = "https://roulezelectrique.club"
# 30s (was 60s): this poll is the ONLY thing that ever picks up a change made
# OUTSIDE Home Assistant (e.g. from the Club Roulez Électrique mobile app) — HA's
# own writes already self-refresh instantly via async_request_refresh() (see
# number.py/switch.py), so only the app→HA direction was ever waiting on this
# timer. Halving it halves worst-case latency for that direction. Safe to
# lower: MIN_SCAN_INTERVAL already permits 30, the server's
# /home-assistant/state read is cheap/cached, and any install with its own
# saved `scan_interval` option is unaffected (this is only the fallback for
# entries that never customized it).
DEFAULT_SCAN_INTERVAL = 30  # seconds
MIN_SCAN_INTERVAL = 30
MAX_SCAN_INTERVAL = 900

# API paths
API_STATE_PATH = "/api/v1/home-assistant/state"
API_REMOTE_START_PATH = "/api/v1/chargers/{charger_id}/remote-start"
API_REMOTE_STOP_PATH = "/api/v1/chargers/{charger_id}/remote-stop"
API_POWER_LIMIT_PATH = "/api/v1/chargers/{charger_id}/power-limit"
API_MAX_CURRENT_PATH = "/api/v1/chargers/{charger_id}/max-current"
API_LOCK_PATH = "/api/v1/chargers/{charger_id}/lock"
API_COMMAND_POLL_PATH = "/api/v1/commands/{command_id}"

# The EVduty/Elmec MaxCurrent recipe (ChangeConfiguration -> read-back ->
# Reset) runs SYNCHRONOUSLY inside the server's single HTTP request, with a
# per-step budget of ~12s x 3 steps. The default 20s client timeout would
# abort a perfectly healthy call mid-recipe, so this endpoint gets its own,
# wider budget. Kept under the server-side ceiling it is bounded by
# (php max_execution_time 60s / nginx fastcgi_read_timeout 120s).
MAX_CURRENT_REQUEST_TIMEOUT = 75  # seconds

# IYILO-only settings (server calls this vendor "ave" on the wire — see
# switch.py's charge switch gate). All three are FULLY SYNCHRONOUS, same
# contract as remote-start/remote-stop/lock above: the response IS the
# outcome, never a command id to poll. Gated server-side on the
# per-charger `plug_and_charge`/`time_zone`/`reboot` capability strings.
API_AVE_PLUG_AND_CHARGE_PATH = "/api/v1/chargers/{charger_id}/ave/plug-and-charge"
API_AVE_TIMEZONE_PATH = "/api/v1/chargers/{charger_id}/ave/timezone"
API_AVE_REBOOT_PATH = "/api/v1/chargers/{charger_id}/ave/reboot"

# Default current bounds for the power-limit number entity, used when the
# server omits them (older server / read failure). The server validates
# min:6 / max:maxControlAmps, so 6 is the hard floor everywhere.
DEFAULT_MIN_AMPS = 6
DEFAULT_MAX_AMPS = 32

# Command polling
COMMAND_POLL_INTERVAL = 2  # seconds between polls
COMMAND_TIMEOUT = 37  # seconds; server timeout is ~35s, add small buffer

# Terminal command statuses (stop polling)
COMMAND_TERMINAL_STATUSES = {"accepted", "rejected", "timeout", "failed"}

# Coordinator data key
COORDINATOR_CHARGERS_KEY = "chargers"

# Platforms
PLATFORMS = ["binary_sensor", "button", "number", "select", "sensor", "switch"]
