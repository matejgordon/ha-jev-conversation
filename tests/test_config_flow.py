"""Config and options flow."""

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.jev_conversation.const import (
    CONF_ASK_THRESHOLD,
    CONF_BASE_URL,
    CONF_EXECUTE_THRESHOLD,
    CONF_MODEL,
    DOMAIN,
)

from .conftest import BASE_URL, JEV_URL

FORM = {
    CONF_API_KEY: "k",
    CONF_BASE_URL: BASE_URL,
    CONF_MODEL: "jev-test",
    CONF_EXECUTE_THRESHOLD: 0.85,
    CONF_ASK_THRESHOLD: 0.5,
}
PROBE = {"model": "jev-test", "answers": {"probe": {"type": "noul", "noul": 0.9}}}


async def _submit(hass, data):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    return await hass.config_entries.flow.async_configure(result["flow_id"], data)


async def test_flow_tests_the_key_and_creates_the_entry(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.post(JEV_URL, json=PROBE)
    result = await _submit(hass, FORM)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == FORM


async def test_flow_reports_a_rejected_key(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.post(JEV_URL, status=401)
    result = await _submit(hass, FORM)
    assert result["errors"] == {"base": "invalid_auth"}


async def test_flow_reports_unreachable_api(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.post(JEV_URL, exc=TimeoutError())
    result = await _submit(hass, FORM)
    assert result["errors"] == {"base": "cannot_connect"}


async def test_flow_rejects_thresholds_in_the_wrong_order(hass: HomeAssistant):
    result = await _submit(hass, {**FORM, CONF_ASK_THRESHOLD: 0.9})
    assert result["errors"] == {CONF_ASK_THRESHOLD: "ask_above_execute"}


async def test_options_change_thresholds(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.post(JEV_URL, json=PROBE)
    entry = hass.config_entries.async_get_entry((await _submit(hass, FORM))["result"].entry_id)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_EXECUTE_THRESHOLD: 0.9, CONF_ASK_THRESHOLD: 0.6}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_EXECUTE_THRESHOLD: 0.9, CONF_ASK_THRESHOLD: 0.6}
