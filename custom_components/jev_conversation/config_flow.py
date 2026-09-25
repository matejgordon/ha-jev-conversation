"""Config flow for Jev Conversation."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_API_KEY
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

from .api import JevAuthError, JevClient, JevError
from .const import (
    CONF_ASK_THRESHOLD,
    CONF_BASE_URL,
    CONF_EXECUTE_THRESHOLD,
    CONF_MODEL,
    DEFAULT_ASK_THRESHOLD,
    DEFAULT_BASE_URL,
    DEFAULT_EXECUTE_THRESHOLD,
    DEFAULT_MODEL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

_THRESHOLD = NumberSelector(NumberSelectorConfig(min=0, max=1, step=0.01, mode=NumberSelectorMode.BOX))


def _threshold_fields(values: dict[str, Any]) -> dict:
    return {
        vol.Required(
            CONF_EXECUTE_THRESHOLD, default=values.get(CONF_EXECUTE_THRESHOLD, DEFAULT_EXECUTE_THRESHOLD)
        ): _THRESHOLD,
        vol.Required(
            CONF_ASK_THRESHOLD, default=values.get(CONF_ASK_THRESHOLD, DEFAULT_ASK_THRESHOLD)
        ): _THRESHOLD,
    }


def _threshold_errors(values: dict[str, Any]) -> dict[str, str]:
    if values[CONF_ASK_THRESHOLD] >= values[CONF_EXECUTE_THRESHOLD]:
        return {CONF_ASK_THRESHOLD: "ask_above_execute"}
    return {}


class JevConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for the key, endpoint, pinned model and thresholds, and test them."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        values = user_input or {}
        if user_input is not None:
            errors = _threshold_errors(user_input)
            if not errors:
                client = JevClient(
                    async_get_clientsession(self.hass),
                    user_input[CONF_BASE_URL],
                    user_input[CONF_API_KEY],
                    user_input[CONF_MODEL],
                )
                try:
                    await client.ask("Rozsviť v kuchyni.", {"probe": {"type": "noul", "instructions": "Je to příkaz?"}})
                except JevAuthError:
                    errors["base"] = "invalid_auth"
                except JevError as err:
                    _LOGGER.warning("Jev test request failed: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_create_entry(title="Jev", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                vol.Required(CONF_BASE_URL, default=values.get(CONF_BASE_URL, DEFAULT_BASE_URL)): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.URL)
                ),
                vol.Required(CONF_MODEL, default=values.get(CONF_MODEL, DEFAULT_MODEL)): str,
                **_threshold_fields(values),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={"openrouter_url": DEFAULT_BASE_URL, "typesafe_url": "https://api.typesafe.ai"},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return JevOptionsFlow()


class JevOptionsFlow(OptionsFlow):
    """Change the thresholds after setup."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _threshold_errors(user_input)
            if not errors:
                return self.async_create_entry(data=user_input)
        current = user_input or {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(_threshold_fields(current)), errors=errors
        )
