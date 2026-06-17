"""Constants for the Roulez Électrique (BETA) Home Assistant integration."""

DOMAIN = "roulezelectrique"
INTEGRATION_NAME = "Roulez Électrique (BETA)"

# Config entry keys
CONF_BASE_URL = "base_url"
CONF_API_TOKEN = "api_token"
CONF_SCAN_INTERVAL = "scan_interval"

# Defaults
DEFAULT_BASE_URL = "https://roulezelectrique.club"
DEFAULT_SCAN_INTERVAL = 60  # seconds
MIN_SCAN_INTERVAL = 30
MAX_SCAN_INTERVAL = 900

# API paths
API_STATE_PATH = "/api/v1/home-assistant/state"
API_REMOTE_START_PATH = "/api/v1/chargers/{charger_id}/remote-start"
API_REMOTE_STOP_PATH = "/api/v1/chargers/{charger_id}/remote-stop"
API_COMMAND_POLL_PATH = "/api/v1/commands/{command_id}"

# Command polling
COMMAND_POLL_INTERVAL = 2  # seconds between polls
COMMAND_TIMEOUT = 37  # seconds; server timeout is ~35s, add small buffer

# Terminal command statuses (stop polling)
COMMAND_TERMINAL_STATUSES = {"accepted", "rejected", "timeout", "failed"}

# Coordinator data key
COORDINATOR_CHARGERS_KEY = "chargers"

# Platforms
PLATFORMS = ["binary_sensor", "sensor", "switch"]
