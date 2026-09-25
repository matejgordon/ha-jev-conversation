"""Jev Conversation: a fast Czech conversation agent for Assist on TypeSafe Jev."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import JevClient
from .const import CONF_BASE_URL, CONF_MODEL

PLATFORMS = [Platform.CONVERSATION]

type JevConfigEntry = ConfigEntry[JevClient]


async def async_setup_entry(hass: HomeAssistant, entry: JevConfigEntry) -> bool:
    """Set up Jev Conversation from a config entry."""
    entry.runtime_data = JevClient(
        async_get_clientsession(hass),
        entry.data[CONF_BASE_URL],
        entry.data[CONF_API_KEY],
        entry.data[CONF_MODEL],
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: JevConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: JevConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
