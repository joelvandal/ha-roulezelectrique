# Roulez Électrique — Home Assistant Integration

Connect your [Roulez Électrique](https://roulezelectrique.club) EV chargers to Home Assistant: live telemetry for every charger in your account, plus remote control (start/stop, charging-current limit, lock) for the vendors that support it.

---

## Supported chargers

One HA **device per charger**, plus one **Account** device for program-level stats. What each vendor gets:

| Vendor | Telemetry sensors | Online | Charging | Plugged in | Start/Stop | Current limit slider | Lock |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **OCPP** (any OCPP 1.6J charger connected to the platform) | ✅ | ✅ | ✅ | — | ✅ | ✅ | — |
| **Wallbox** (linked account) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **AVE** (linked account) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| **Tesla** Wall Connector (linked account) | ✅ | ✅ | ✅ | ✅ | — | — | — |
| **Sigenergy AC** (linked account) | ✅ | ✅ | ✅ | — | — | ✅ | — |
| **Sigenergy DC** (linked account) | ✅ | ✅ | ✅ | — | — | — | — |

Control availability is decided **server-side** (the platform's `controllable` / `current_limit_controllable` flags): an OCPP charger must be online (live WebSocket), and cloud vendors (Wallbox, AVE, Sigenergy AC) need an active linked account. When control is temporarily unavailable, the entity exists but shows as *unavailable* — it never fails silently.

---

## Entities

### Per charger

**Sensors**
- **Power** (kW)
- **Session energy** (kWh) — energy delivered in the **current session**; resets each session
- **Status** (enum: available, preparing, charging, suspended_evse, suspended_ev, finishing, reserved, unavailable, faulted)
- **Current** (A)
- **Voltage** (V)
- **Last session** (timestamp)

Telemetry sensors (power, energy, current, voltage) go *unavailable* when the charger is offline or its data is stale; status and last-session remain readable.

**Binary sensors**
- **Online** (connectivity) — all vendors
- **Charging** — all vendors
- **Plugged in** — Wallbox, AVE, Tesla

**Controls**
- **Charge switch** (start/stop) — OCPP, Wallbox, AVE. Commands are confirmed end-to-end: OCPP commands are polled until the charger accepts/rejects; failures surface as an HA error toast and the switch reverts (no fake state).
- **Max current** (number slider, A) — OCPP (smart-charging `SetChargingProfile`), Wallbox, AVE, Sigenergy AC. Bounds come from the server (typically 6 A up to the charger's max).
- **Lock switch** — Wallbox only (on = locked).

### Account device

- **Rewards** (CAD): total, client, ambassador, referee, referrer
- **Invitations**: pending, accepted, referred
- **Lifetime energy** (kWh)
- **Charger count**

---

## Requirements

- Home Assistant **2024.1.0** or later
- A Roulez Électrique account at [roulezelectrique.club](https://roulezelectrique.club)
- An API token from your profile (see Setup)

---

## Installation

### Via HACS (recommended)

1. Add this repository as a custom HACS repository:
   - HACS → Integrations → ⋮ → Custom repositories
   - URL: `https://github.com/joelvandal/ha-roulezelectrique`
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
3. Click **Activate**. Your token is shown **once** — copy it now.

### Step 2 — Add the integration in HA

1. Settings → Devices & Services → Add Integration.
2. Search for "Roulez Électrique".
3. Paste your API token and click Submit — that's it (the platform URL is built in).

Your chargers appear as HA devices within a few seconds. The UI is available in **French and English**.

---

## Options

After setup, open the integration's settings to adjust:

- **Update interval** (30–900 seconds, default 60): how often HA polls for new data. The integration backs off automatically if the server rate-limits it.

---

## Token management

Your API token can be rotated or revoked at any time from **Profile → Integrations → Home Assistant** on the platform. If the token becomes invalid, the integration stops polling and prompts you to **re-authenticate** directly in HA (Settings → Devices & Services) — just paste the new token.

---

## Diagnostics

The integration supports HA's built-in diagnostics download (Settings → Devices & Services → Roulez Électrique → Download diagnostics). The API token is **redacted** from the dump.

---

## Upgrading

- **From v0.2.4 or earlier:** the account-level sensors (rewards, invitations, lifetime energy, charger count) had a duplicated internal ID that is corrected automatically the first time the integration reloads after upgrading — your existing entities, their history, and any dashboards/automations referencing them are preserved (no re-adding, no new entity).

---

## Known limitations

- Tesla and Sigenergy DC chargers are **read-only** — the platform does not expose remote control for them.
- The **Session energy** sensor measures the current charging session only and resets to 0 each session — it is **not** a lifetime cumulative meter, so it is **not recommended as a Home Assistant Energy dashboard source** (the Energy dashboard expects an ever-increasing total). The account's **Lifetime energy** sensor is the cumulative one.
- The integration ships its own brand icon/logo (`brand/` folder, supported since Home Assistant 2026.3.0). On older HA versions the integration works fine but shows without a logo.

---

## License

MIT — see [LICENSE](LICENSE).
