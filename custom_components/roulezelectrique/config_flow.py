"""Config flow for the Roulez Électrique (BETA) integration.

Steps:
  user  → ask for base_url + api_token; validate via GET /state
  reauth → ask for api_token only (base_url preserved from entry)

OptionsFlow: scan_interval (30–900 s, default 60).
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_URL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AuthError, ConnectError, RoulezElectriqueApiClient, RoulezElectriqueError
from .const import (
    CONF_API_TOKEN,
    CONF_BASE_URL,
    CONF_SCAN_INTERVAL,
    DEFAULT_BASE_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def _token_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_API_TOKEN): str,
        }
    )


class RoulezElectriqueConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Roulez Électrique (BETA)."""

    VERSION = 1

    def __init__(self) -> None:
        self._base_url: str = DEFAULT_BASE_URL
        self._api_token: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Initial step: collect api_token only.

        The base URL is fixed to DEFAULT_BASE_URL and is not exposed as a user
        field — there is only one correct value (the platform URL). It is stored
        in the config entry so existing entries keep working if the URL ever
        changes, but users should never need to type it themselves.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            self._api_token = user_input[CONF_API_TOKEN]

            unique_id, error = await self._validate_credentials(
                self._base_url, self._api_token
            )
            if error:
                errors["base"] = error
            elif unique_id is not None:
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=self._entry_title(),
                    data={
                        CONF_BASE_URL: self._base_url,
                        CONF_API_TOKEN: self._api_token,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_token_schema(),
            errors=errors,
            description_placeholders={"base_url": self._base_url},
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Reauth step triggered when the coordinator raises ConfigEntryAuthFailed."""
        self._base_url = entry_data.get(CONF_BASE_URL, DEFAULT_BASE_URL)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user for a fresh API token during reauth."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._api_token = user_input[CONF_API_TOKEN]
            unique_id, error = await self._validate_credentials(
                self._base_url, self._api_token
            )
            if error:
                errors["base"] = error
            else:
                # Update the existing entry with the new token.
                entry = await self.async_set_unique_id(unique_id)
                self.hass.config_entries.async_update_entry(
                    self._get_reauth_entry(),
                    data={
                        CONF_BASE_URL: self._base_url,
                        CONF_API_TOKEN: self._api_token,
                    },
                )
                await self.hass.config_entries.async_reload(
                    self._get_reauth_entry().entry_id
                )
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_token_schema(),
            errors=errors,
            description_placeholders={"base_url": self._base_url},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow for this entry."""
        return RoulezElectriqueOptionsFlow(config_entry)

    async def _validate_credentials(
        self, base_url: str, api_token: str
    ) -> tuple[str | None, str | None]:
        """Validate credentials by calling GET /state.

        Returns (unique_id, None) on success or (None, error_key) on failure.
        The unique_id is derived from first charger owner or a fixed string;
        since the API doesn't expose /me we use "user-token" as the unique id
        to detect duplicate entries.  We prefix with the token's first 8 chars
        so a second account gets a different unique id.
        """
        session = async_get_clientsession(self.hass)
        client = RoulezElectriqueApiClient(session, base_url, api_token)
        try:
            await client.get_state()
            # Use first 8 chars of token as a stable unique id per token.
            # This prevents adding the same token twice.
            unique_id = f"user-{api_token[:8]}"
            return unique_id, None
        except AuthError:
            return None, "invalid_auth"
        except (ConnectError, RoulezElectriqueError):
            # RoulezElectriqueError covers any unexpected HTTP status during
            # setup (404 for a wrong base URL path, 403, 422, etc.). All of
            # these indicate a connectivity/configuration issue rather than a
            # bad token, so "cannot_connect" is the most actionable label.
            return None, "cannot_connect"
        except Exception:  # noqa: BLE001
            return None, "unknown"

    def _entry_title(self) -> str:
        host = self._base_url.replace("https://", "").replace("http://", "")
        return f"Roulez Électrique — {host}"


class RoulezElectriqueOptionsFlow(OptionsFlow):
    """Options flow: let the user adjust the poll interval."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and process the options form."""
        errors: dict[str, str] = {}
        current_interval = self._entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )

        if user_input is not None:
            interval = user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            if not (MIN_SCAN_INTERVAL <= interval <= MAX_SCAN_INTERVAL):
                errors[CONF_SCAN_INTERVAL] = "invalid_scan_interval"
            else:
                return self.async_create_entry(
                    title="",
                    data={CONF_SCAN_INTERVAL: interval},
                )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=current_interval,
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    ),
                }
            ),
            errors=errors,
        )
