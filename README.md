# Roulez Électrique — Home Assistant Integration

> **BETA / EXPERIMENTAL** — This integration is under active development. APIs, entity names, and behavior may change without notice. Use in production at your own risk.

Connect your Roulez Électrique EV chargers to Home Assistant. Get live sensor data for all your chargers, and remotely start/stop OCPP-compatible chargers directly from HA.

---

## What you get

For **every charger** in your account:
- Power sensor (kW)
- Session energy sensor (kWh) — energy delivered in the **current session** (resets each session)
- Status sensor (Available / Charging / etc.)
- Current sensor (A)
- Voltage sensor (V)
- Last session timestamp
- Charging binary sensor

For **OCPP chargers** only:
- Online / connectivity binary sensor
- Start/Stop switch (remote start and stop charge sessions)

Non-OCPP chargers (Tesla, Wallbox, etc.) appear **read-only** — the platform does not support remote control for those.

---

## Requirements

- Home Assistant 2024.1.0 or later
- A Roulez Électrique account at [roulezelectrique.club](https://roulezelectrique.club)
- An API token from your profile

---

## Installation

### Via HACS (recommended)

1. Add this repository as a custom HACS repository:
   - HACS → Integrations → ⋮ → Custom repositories
   - URL: `https://github.com/joelvandal/roulezelectrique-ha`
   - Category: Integration
2. Search for "Roulez Électrique" and install.
3. Restart Home Assistant.

### Manual

1. Copy `custom_components/roulezelectrique/` into your HA `config/custom_components/` folder.
2. Restart Home Assistant.

---

## Setup

### Step 1 — Get your API token

1. Sign in at [roulezelectrique.club](https://roulezelectrique.club).
2. Go to **Profile → Integrations → Home Assistant**.
3. Click **Activate** (BETA). Your token is shown **once** — copy it now.

> **Note:** The install link from your profile page will point directly to this component once it is published.

### Step 2 — Add the integration in HA

1. Settings → Devices & Services → Add Integration.
2. Search for "Roulez Électrique".
3. Enter the base URL (`https://roulezelectrique.club`) and paste your API token.
4. Click Submit.

Your chargers will appear as HA devices within a few seconds.

---

## Options

After setup, go to the integration settings to adjust:

- **Update interval** (30–900 seconds, default 60): how often HA polls for new data.

---

## Token management

Your API token can be rotated or revoked at any time from **Profile → Integrations → Home Assistant** on the platform. If you revoke or rotate your token, the integration will prompt you to re-authenticate in HA.

---

## BETA limitations

- Remote control is OCPP-only (the platform has no remote API for Tesla/Wallbox).
- The **Session energy** sensor measures the current charging session only and resets to 0 each session — it is **not** a lifetime cumulative meter, so it is **not recommended as a Home Assistant Energy dashboard source** (the Energy dashboard expects an ever-increasing total).
- Brand assets (HA brands repo) are pending submission.
- A dedicated public GitHub repo for HACS distribution is forthcoming.

---

## License

MIT — see [LICENSE](LICENSE).
