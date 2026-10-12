"""Config flow for Grok Bot Usage."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from typing import Any, override

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    GrokBotUsageAuthError,
    GrokBotUsageClient,
    GrokBotUsageError,
    GrokBotUsageForbiddenError,
    GrokBotUsageRateLimitError,
    GrokBotUsageResponseError,
    looks_like_session_cookie,
    normalize_api_key,
)
from .const import (
    AUTH_DOCS_URL,
    CONF_API_KEY,
    CONF_SCAN_INTERVAL,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

_API_KEY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        )
    }
)


def unique_id_for_api_key(api_key: str) -> str:
    """Return a stable identifier that does not reveal the API key."""
    digest = hashlib.sha256(api_key.encode()).hexdigest()
    return f"cursor-user-{digest[:32]}"


class GrokBotUsageConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Grok Bot Usage."""

    VERSION = 1

    @staticmethod
    @callback
    @override
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> GrokBotUsageOptionsFlow:
        """Return the options flow."""
        return GrokBotUsageOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a Cursor user API key and validate it."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = normalize_api_key(user_input.get(CONF_API_KEY, ""))
            error = await self._async_validate_key(api_key)
            if error is None:
                await self.async_set_unique_id(unique_id_for_api_key(api_key))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=DEFAULT_NAME,
                    data={CONF_API_KEY: api_key},
                    options={CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL},
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=_API_KEY_SCHEMA,
            description_placeholders={"docs_url": AUTH_DOCS_URL},
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start a reauth flow after the stored key is rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Replace the stored API key after validating the new one."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = normalize_api_key(user_input.get(CONF_API_KEY, ""))
            error = await self._async_validate_key(api_key)
            if error is None:
                entry = self._get_reauth_entry()
                new_id = unique_id_for_api_key(api_key)
                existing = self.hass.config_entries.async_entry_for_domain_unique_id(
                    DOMAIN, new_id
                )
                if existing is not None and existing.entry_id != entry.entry_id:
                    return self.async_abort(reason="already_configured")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_API_KEY: api_key},
                    unique_id=new_id,
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_API_KEY_SCHEMA,
            description_placeholders={"docs_url": AUTH_DOCS_URL},
            errors=errors,
        )

    async def _async_validate_key(self, api_key: str) -> str | None:
        """Return a translation key when the API key cannot be used."""
        if not api_key:
            return "missing_api_key"
        if looks_like_session_cookie(api_key):
            return "session_cookie"

        client = GrokBotUsageClient(async_get_clientsession(self.hass), api_key)
        try:
            await client.async_get_usage()
        except GrokBotUsageAuthError:
            return "invalid_auth"
        except GrokBotUsageForbiddenError:
            return "forbidden"
        except GrokBotUsageRateLimitError:
            return "rate_limited"
        except GrokBotUsageResponseError:
            return "invalid_response"
        except GrokBotUsageError:
            return "cannot_connect"
        except Exception:
            _LOGGER.error("Unexpected error validating the Cursor usage API key")
            return "unknown"
        return None


class GrokBotUsageOptionsFlow(OptionsFlowWithReload):
    """Change how often usage is polled."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the poll interval."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                interval = int(user_input[CONF_SCAN_INTERVAL])
            except TypeError, ValueError:
                errors["base"] = "invalid_scan_interval"
            else:
                if interval < MIN_SCAN_INTERVAL or interval > MAX_SCAN_INTERVAL:
                    errors["base"] = "invalid_scan_interval"
                else:
                    return self.async_create_entry(
                        title="",
                        data={CONF_SCAN_INTERVAL: interval},
                    )

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=30,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="seconds",
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                schema, {CONF_SCAN_INTERVAL: current}
            ),
            errors=errors,
        )
