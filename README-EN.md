# Roulez Électrique — Home Assistant Integration

Connect your [Roulez Électrique](https://roulezelectrique.club) EV chargers to Home Assistant: live telemetry for every charger in your account, plus remote control (start/stop, charging-current limit, lock) for the vendors that support it.

---

## Supported chargers

One HA **device per charger**, plus one **Account** device for program-level stats. What each vendor gets:

| Vendor | Telemetry sensors | Online | Charging | Plugged in | Start/Stop | Current limit slider | Lock |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **OCPP** (any OCPP 1.6J charger connected to the platform) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| **Wallbox** (linked account) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **AVE** (linked account) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| **Tesla** Wall Connector (linked account) | ✅ | ✅ | ✅ | ✅ | — | — | — |
| **Sigenergy AC** (linked account) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| **Sigenergy DC** (linked account) | ✅ | ✅ | ✅ | ✅ | ✅ | — | — |

Control availability is decided **server-side** (the platform's `controllable` / `current_limit_controllable` flags): an OCPP charger must be online (live WebSocket), and cloud vendors (Wallbox, AVE, Sigenergy AC and DC) need an active linked account. When control is temporarily unavailable, the entity exists but shows as *unavailable* — it never fails silently.

**New in v0.5.0:** Sigenergy AC and DC now get the start/stop switch (through the same synchronous call as Wallbox/AVE — the platform branches AC vs DC internally). Only Sigenergy AC keeps the max-current slider; there is no current-limit API for DC.

Extra per-vendor sensors (below) are created **only for the chargers that can report them** — a Tesla Wall Connector never gets a temperature sensor, a Wallbox never gets a VIN sensor, etc. This is decided by the platform, per charger (via the `capabilities` list the server returns for each charger), so it stays correct automatically as the platform adds vendors or new capabilities — including the **Plugged in** binary sensor, which is also fully capability-driven as of v0.5.0 (see below).

| Vendor | Lifetime energy/sessions | Measured current | Temperature | Battery % | Last connection | Session start | Charging speed / Added range | Connection type | VIN |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **OCPP** | ✅ | — | rare¹ | rare¹ | ✅ | ✅ | — | — | — |
| **Wallbox** | ✅ | — | — | — | ✅ | — | ✅ | — | — |
| **AVE** | ✅ | — | — | — | — | ✅ | — | — | — |
| **Tesla** | ✅ | — | — | — | — | — | — | — | ✅ |
| **Sigenergy AC** | ✅ | ✅ | ✅ | — | — | ✅ | — | ✅ | — |
| **Sigenergy DC** | ✅ | — | — | — | — | — | — | — | — |

¹ Only chargers that actually send a Temperature/SoC reading in their reports will show a value; most don't. The sensor is created for every OCPP charger (so it appears the moment a charger starts reporting it) but reads *unknown* until then.

---

## Entities

### Per charger

**Sensors**
- **Power** (kW)
- **Session energy** (kWh) — energy delivered in the **current session**; resets each session
- **Status** (enum: available, preparing, charging, suspended_evse, suspended_ev, finishing, reserved, unavailable, faulted) — vendor-specific diagnostic codes (e.g. Tesla wall-connector codes, Sigenergy diagnostics), when the platform has any for that charger, are attached as extra attributes on this sensor
- **Current** (A)
- **Voltage** (V)
- **Last session** (timestamp)
- **Lifetime energy** (kWh) — cumulative energy across every session ever recorded for this charger; see *Energy dashboard* below
- **Lifetime sessions** (count)
- **Temperature** (°C) — OCPP (when reported) and Sigenergy AC
- **Battery level** (%) — OCPP only, when the charger reports it (rare)
- **Measured current** (A) — Sigenergy AC only; the *live* draw, separate from the "Current" sensor above, which stays the configured limit
- **Last connection** (timestamp) — OCPP, Wallbox
- **Session start** (timestamp) — OCPP, AVE, Sigenergy AC (not available from Wallbox's cloud)
- **Charging speed** (km/h) and **Added range** (km) — Wallbox only
- **Connection type** (ethernet/wifi/cellular) — Sigenergy AC only
- **VIN** — Tesla only, the connected vehicle's VIN
- **Wi-Fi signal** (%) — OCPP only; enabled by default
- **Maximum charge level** (%) — OCPP only; disabled by default
- **Minimum charge level** (%) — OCPP only; disabled by default
- **Charger current limit** (A) — OCPP only; disabled by default
- **Heartbeat interval** (s) — OCPP only; disabled by default
- **Meter sample interval** (s) — OCPP only; disabled by default

Telemetry sensors (power, energy, current, voltage, temperature, battery level, measured current, charging speed, added range) go *unavailable* when the charger is offline or its data is stale. Status, last-session, lifetime energy/sessions, last connection, session start, connection type, VIN and the six OCPP diagnostic sensors above remain readable even while the charger is offline.

**OCPP configuration diagnostics (new in v0.6.0)** — the six sensors above (Wi-Fi signal, Maximum charge level, Minimum charge level, Charger current limit, Heartbeat interval, Meter sample interval) are read by the server directly from the `GetConfiguration` data the charger reports about itself, roughly once an hour — they are **not** live measurements, so a value can lag reality by up to an hour (which is also why they stay readable while offline, unlike the telemetry sensors above). They are created **per charger**, not per vendor: only for the specific OCPP charger that actually reported that key with a plausible value. Most of the fleet (EVduty/Elmec) only reports the heartbeat and meter-sample intervals; Wallbox Pulsar Plus chargers speaking OCPP additionally report Wi-Fi signal, min/max charge level and the current limit. Only **Wi-Fi signal** is enabled by default; the other five are disabled on install — enable them in the entity's settings if you want them. A charger linked less than an hour ago has not had its configuration read by the server yet, so these entities don't exist for it yet. Reload the integration once after the first hourly read to pick them up (unlike the vendor-driven sensors, which appear immediately).

**Binary sensors**
- **Online** (connectivity) — all vendors
- **Charging** — all vendors
- **Plugged in** — driven by the platform's `capabilities` list rather than a hardcoded vendor list; currently covers OCPP, Wallbox, AVE, Tesla and Sigenergy AC/DC

**Controls**
- **Charge switch** (start/stop) — OCPP, Wallbox, AVE, Sigenergy AC and DC. Commands are confirmed end-to-end: OCPP commands are polled until the charger accepts/rejects; the other vendors respond synchronously (the result is already known in the response); failures surface as an HA error toast and the switch reverts (no fake state).
- **Max current** (number slider, A) — OCPP (smart-charging `SetChargingProfile`), Wallbox, AVE, Sigenergy AC. Bounds come from the server (typically 6 A up to the charger's max). Since v0.6.0, when an OCPP charger reports its own hardware current limit in its configuration, that value is used as the ceiling — for example, Wallbox Pulsar Plus chargers on OCPP that report 48 A now get a 48 A ceiling instead of the generic 32 A default. Not available for Sigenergy DC (no current-limit API on the DC side).
- **Lock switch** — Wallbox only (on = locked).

### Account device

- **Rewards** (CAD): total, client, ambassador, referee, referrer
- **Invitations**: pending, accepted, referred
- **Lifetime energy** (kWh) — a running lifetime total across all your chargers that may occasionally be adjusted downward when the platform corrects duplicate or erroneous session data (a periodic recount, not a live meter); see *Energy dashboard* below
- **Charger count**

---

## Energy dashboard

Use each charger's **Lifetime energy** sensor as the source when adding a charger to Home Assistant's Energy dashboard. It is a running lifetime total that may occasionally be adjusted downward when the platform corrects duplicate or erroneous session data (a periodic recount, not a live meter) — it remains the right sensor for the Energy dashboard. The **Session energy** sensor resets to 0 at the start of every charging session, so it is **not** suitable there (see *Known limitations*).

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
- **From v0.3.x:** new per-charger sensors (Lifetime energy, Lifetime sessions, Temperature, Battery level, Measured current, Last connection, Session start, Charging speed, Added range, Connection type, VIN) appear automatically on the first reload for every charger whose vendor can report them — no re-adding, no configuration change needed. Existing entity IDs are untouched, but the account-level **Lifetime energy** sensor's state class changes from `total_increasing` to `total` (it can now be corrected downward, e.g. after a data cleanup, without Home Assistant misreading that as a meter reset). Home Assistant may log a one-time "statistics metadata changed" notice for that sensor when this happens — this is expected and harmless; its long-term statistics and history keep working normally.
- **From v0.4.x:** Sigenergy AC and DC now get the start/stop switch (remote control, requires an active linked account), and the **Plugged in** binary sensor now also covers OCPP and Sigenergy AC/DC (previously limited to Wallbox/AVE/Tesla). These new entities appear automatically on the first reload for the affected chargers — no re-adding, no configuration change needed.
- **From v0.5.x:** six new OCPP diagnostic sensors (Wi-Fi signal, Maximum charge level, Minimum charge level, Charger current limit, Heartbeat interval, Meter sample interval) appear for eligible OCPP chargers on the first reload after their configuration is next read hourly — no re-adding, no configuration change needed (see *Entities* above for the per-charger detail and default enablement).

---

## Known limitations

- Tesla chargers are **read-only** — the platform does not expose remote control for them.
- Sigenergy DC chargers get the start/stop switch but **not** the max-current slider — there is no current-limit API on the DC side.
- The **Session energy** sensor measures the current charging session only and resets to 0 each session — it is **not** a lifetime cumulative meter, so it is **not recommended as a Home Assistant Energy dashboard source** (the Energy dashboard expects an ever-increasing total). Each charger's own **Lifetime energy** sensor (and the account's) is the cumulative one — see *Energy dashboard* above.
- **WiFi signal strength via a vendor's cloud API is not available for any charger, from any vendor.** Tesla's own device does report a signal-strength value, but only over its local network API on the same LAN — the cloud API this platform reads from does not carry it, so there is no way to surface it here for Tesla or any other vendor through that path. The **Wi-Fi signal** diagnostic sensor described above is a different thing: it comes from the `GetConfiguration` data an OCPP charger reports about itself (e.g. Wallbox Pulsar Plus on OCPP), not a live cloud API, so it only exists for OCPP chargers that report it.
- **Temperature** and **Battery level** sensors on OCPP chargers only show a value for the small number of chargers whose firmware actually reports those readings; most read *unknown* permanently, which is expected (the sensor is still created so it starts working the moment a charger begins reporting it).
- The integration ships its own brand icon/logo (`brand/` folder, supported since Home Assistant 2026.3.0). On older HA versions the integration works fine but shows without a logo.

---

## License

MIT — see [LICENSE](LICENSE).
