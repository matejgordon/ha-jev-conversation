"""Fixtures: a small Czech house exposed to Assist, and the integration with the Jev API mocked."""

from __future__ import annotations

import pytest

from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.jev_conversation.const import CONF_BASE_URL, CONF_MODEL, DOMAIN

BASE_URL = "https://jev.test/api"
JEV_URL = f"{BASE_URL}/v1/systemone"

# entity_id, name, area, state, attributes
HOUSE = [
    ("light.lampa_gauc", "Lampa u gauče", "Obývák", "off", {}),
    ("light.lampa_okno", "Lampa u okna", "Obývák", "off", {}),
    ("light.loznice", "Světlo v ložnici", "Ložnice", "off", {}),
    ("climate.loznice", "Topení v ložnici", "Ložnice", "heat", {"temperature": 21, "min_temp": 7, "max_temp": 30}),
    ("lock.vchod", "Vchodové dveře", "Chodba", "locked", {}),
    ("cover.garaz", "Garážová vrata", None, "closed", {"device_class": "garage"}),
    ("sensor.teplota_loznice", "Teplota v ložnici", "Ložnice", "22.5",
     {"unit_of_measurement": "°C", "device_class": "temperature"}),
]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/ in every test."""


@pytest.fixture(autouse=True)
async def core(hass: HomeAssistant) -> None:
    """Exposed-entity settings live in the homeassistant component; conversation needs it."""
    assert await async_setup_component(hass, "homeassistant", {})


@pytest.fixture
async def house(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "conversation", {})
    areas, entities = ar.async_get(hass), er.async_get(hass)
    for entity_id, name, area, state, attrs in HOUSE:
        domain, object_id = entity_id.split(".")
        entities.async_get_or_create(domain, "test", object_id, suggested_object_id=object_id)
        if area:
            area_id = (areas.async_get_area_by_name(area) or areas.async_create(area)).id
            entities.async_update_entity(entity_id, area_id=area_id)
        hass.states.async_set(entity_id, state, {"friendly_name": name, **attrs})
        # Locks and sensors are not exposed by default; the user exposes them in the UI.
        async_expose_entity(hass, "conversation", entity_id, True)


@pytest.fixture
async def agent_id(hass: HomeAssistant, house, aioclient_mock) -> str:
    """The agent, set up after the HTTP mock so its session is the mocked one."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: "secret-key", CONF_BASE_URL: BASE_URL, CONF_MODEL: "jev-test"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return er.async_get(hass).async_get_entity_id("conversation", DOMAIN, entry.entry_id)
