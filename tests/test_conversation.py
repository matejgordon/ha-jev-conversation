"""The agent end to end, with Jev's answers mocked and service calls recorded."""

from __future__ import annotations

from homeassistant.components import conversation
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from .conftest import JEV_URL


def jev(action, target, *, action_conf=1.0, target_conf=1.0, probs=None, all_of_kind=0.0, kind="none", area="none"):
    """A Jev reply to the command request."""
    choice = lambda c, conf, p=None: {"type": "choice", "choice": c, "confidence": conf, "probabilities": p or {c: 1.0}}
    return {
        "model": "jev-test",
        "answers": {
            "action": choice(action, action_conf),
            "device_type": choice(kind, 1.0),
            "all_of_kind": {"type": "noul", "noul": all_of_kind},
            "target": choice(target, target_conf, probs),
            "area": choice(area, 1.0),
        },
        "usage": {"input_tokens": 1000},
    }


def reply(choice, conf=0.98):
    """A Jev reply to a follow-up (confirmation or which-device) request."""
    return {"model": "jev-test", "answers": {"reply": {"type": "choice", "choice": choice, "confidence": conf,
                                                       "probabilities": {choice: conf}}}}


async def say(hass, agent_id, aioclient_mock, text, answer, conversation_id=None):
    aioclient_mock.clear_requests()
    aioclient_mock.post(JEV_URL, json=answer)
    result = await conversation.async_converse(
        hass, text, conversation_id, Context(), language="cs", agent_id=agent_id
    )
    return result, result.response.speech["plain"]["speech"]


async def test_confident_command_runs(hass: HomeAssistant, agent_id, aioclient_mock):
    calls = async_mock_service(hass, "light", "turn_on")
    result, speech = await say(hass, agent_id, aioclient_mock, "Rozsviť lampu u gauče", jev("turn_on", "Lampa u gauče"))
    assert speech == "Hotovo."
    assert not result.continue_conversation
    assert [c.data["entity_id"] for c in calls] == [["light.lampa_gauc"]]
    sent = aioclient_mock.mock_calls[0][2]
    assert sent["state"]["command"] == "Rozsviť lampu u gauče"
    assert {d["name"] for d in sent["state"]["devices"]} >= {"Lampa u gauče", "Vchodové dveře"}


async def test_medium_confidence_asks_which_then_acts(hass: HomeAssistant, agent_id, aioclient_mock):
    calls = async_mock_service(hass, "light", "turn_on")
    probs = {"Lampa u gauče": 0.55, "Lampa u okna": 0.45}
    result, speech = await say(
        hass, agent_id, aioclient_mock, "Rozsviť lampu", jev("turn_on", "Lampa u gauče", target_conf=0.6, probs=probs)
    )
    assert speech == "Myslíš Lampa u gauče, nebo Lampa u okna?"
    assert result.continue_conversation
    assert not calls

    _, speech = await say(hass, agent_id, aioclient_mock, "tu u okna", reply("Lampa u okna"), result.conversation_id)
    assert speech == "Hotovo."
    assert [c.data["entity_id"] for c in calls] == [["light.lampa_okno"]]


async def test_low_confidence_does_nothing(hass: HomeAssistant, agent_id, aioclient_mock):
    calls = async_mock_service(hass, "light", "turn_on")
    result, speech = await say(hass, agent_id, aioclient_mock, "Hmm lampa", jev("turn_on", "Lampa u gauče", action_conf=0.3))
    assert speech == "Nerozumím."
    assert not result.continue_conversation
    assert not calls


async def test_lock_always_needs_voice_confirmation(hass: HomeAssistant, agent_id, aioclient_mock):
    calls = async_mock_service(hass, "lock", "unlock")
    # The model even picked a light: the action's domain overrules it, and there is one lock.
    result, speech = await say(hass, agent_id, aioclient_mock, "Odemkni", jev("unlock", "Lampa u gauče"))
    assert speech == "Opravdu odemknout Vchodové dveře?"
    assert result.continue_conversation
    assert not calls

    _, speech = await say(hass, agent_id, aioclient_mock, "ano", reply("yes"), result.conversation_id)
    assert speech == "Hotovo."
    assert [c.data["entity_id"] for c in calls] == [["lock.vchod"]]


async def test_garage_confirmation_can_be_refused(hass: HomeAssistant, agent_id, aioclient_mock):
    calls = async_mock_service(hass, "cover", "open_cover")
    result, speech = await say(hass, agent_id, aioclient_mock, "Otevři garáž", jev("open", "Garážová vrata"))
    assert speech == "Opravdu otevřít Garážová vrata?"
    _, speech = await say(hass, agent_id, aioclient_mock, "ne, nech to", reply("no"), result.conversation_id)
    assert speech == "Dobře, nechám to být."
    assert not calls


async def test_api_outage_says_so_and_does_nothing(hass: HomeAssistant, agent_id, aioclient_mock):
    calls = async_mock_service(hass, "light", "turn_on")
    aioclient_mock.clear_requests()
    aioclient_mock.post(JEV_URL, exc=TimeoutError())
    result = await conversation.async_converse(hass, "Rozsviť lampu", None, Context(), language="cs", agent_id=agent_id)
    assert result.response.speech["plain"]["speech"] == "Jev teď neodpovídá, zkus to prosím za chvíli."

    aioclient_mock.clear_requests()
    aioclient_mock.post(JEV_URL, status=500, text="boom")
    result = await conversation.async_converse(hass, "Rozsviť lampu", None, Context(), language="cs", agent_id=agent_id)
    assert result.response.speech["plain"]["speech"] == "Jev teď neodpovídá, zkus to prosím za chvíli."
    assert not calls


async def test_values_are_parsed_in_code(hass: HomeAssistant, agent_id, aioclient_mock):
    lights = async_mock_service(hass, "light", "turn_on")
    climate = async_mock_service(hass, "climate", "set_temperature")

    await say(hass, agent_id, aioclient_mock, "Ztlum světlo v ložnici na třicet procent", jev("set_value", "Světlo v ložnici"))
    assert lights[-1].data == {"entity_id": ["light.loznice"], "brightness_pct": 30}

    await say(hass, agent_id, aioclient_mock, "Nastav topení v ložnici na dvaadvacet a půl", jev("set_value", "Topení v ložnici"))
    assert climate[-1].data == {"entity_id": ["climate.loznice"], "temperature": 22.5}

    # No value said: it asks, and reads the answer without another model call.
    result, speech = await say(hass, agent_id, aioclient_mock, "Nastav topení v ložnici", jev("set_value", "Topení v ložnici"))
    assert speech == "Na kolik stupňů?"
    aioclient_mock.clear_requests()
    result = await conversation.async_converse(
        hass, "dvacet", result.conversation_id, Context(), language="cs", agent_id=agent_id
    )
    assert result.response.speech["plain"]["speech"] == "Hotovo."
    assert climate[-1].data["temperature"] == 20
    assert not aioclient_mock.mock_calls

    _, speech = await say(hass, agent_id, aioclient_mock, "Topení na padesát", jev("set_value", "Topení v ložnici"))
    assert speech == "To je mimo rozsah."


async def test_query_answers_from_state(hass: HomeAssistant, agent_id, aioclient_mock):
    _, speech = await say(hass, agent_id, aioclient_mock, "Kolik je v ložnici?", jev("query_state", "Teplota v ložnici"))
    assert speech == "Teplota v ložnici: 22,5 °C."


async def test_all_lights_in_a_room(hass: HomeAssistant, agent_id, aioclient_mock):
    calls = async_mock_service(hass, "light", "turn_off")
    await say(hass, agent_id, aioclient_mock, "Zhasni v obýváku",
              jev("turn_off", "Lampa u gauče", all_of_kind=0.9, kind="light", area="Obývák"))
    assert sorted(calls[-1].data["entity_id"]) == ["light.lampa_gauc", "light.lampa_okno"]


async def test_api_key_is_sent_but_never_logged(hass: HomeAssistant, agent_id, aioclient_mock, caplog):
    caplog.set_level("DEBUG")
    async_mock_service(hass, "light", "turn_on")
    await say(hass, agent_id, aioclient_mock, "Rozsviť lampu u gauče", jev("turn_on", "Lampa u gauče"))
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == "Bearer secret-key"
    assert "secret-key" not in caplog.text
    assert "Jev call" in caplog.text and "Command handled in" in caplog.text


async def test_value_missing_in_ask_band_asks_for_the_value(hass: HomeAssistant, agent_id, aioclient_mock):
    climate = async_mock_service(hass, "climate", "set_temperature")
    result, speech = await say(hass, agent_id, aioclient_mock, "Nastav topení v ložnici",
                               jev("set_value", "Topení v ložnici", action_conf=0.66))
    assert speech == "Na kolik stupňů?"
    aioclient_mock.clear_requests()
    result = await conversation.async_converse(
        hass, "dvacet jedna", result.conversation_id, Context(), language="cs", agent_id=agent_id
    )
    assert result.response.speech["plain"]["speech"] == "Hotovo."
    assert climate[-1].data["temperature"] == 21


async def test_whole_house_group_needs_an_explicit_all(hass: HomeAssistant, agent_id, aioclient_mock):
    calls = async_mock_service(hass, "light", "turn_off")
    group = jev("turn_off", "Lampa u gauče", all_of_kind=0.9, kind="light")
    result, speech = await say(hass, agent_id, aioclient_mock, "Zhasni stropní světla", group)
    assert speech == "Mám vypnout Lampa u gauče, Lampa u okna a Světlo v ložnici?"
    assert not calls
    _, speech = await say(hass, agent_id, aioclient_mock, "Zhasni všechna světla", group)
    assert speech == "Hotovo."
    assert len(calls[-1].data["entity_id"]) == 3


async def test_group_without_room_uses_the_satellites_room(hass: HomeAssistant, agent_id, aioclient_mock):
    calls = async_mock_service(hass, "light", "turn_on")
    entry = MockConfigEntry(domain="esphome")
    entry.add_to_hass(hass)
    satellite = dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, identifiers={("esphome", "voice")})
    dr.async_get(hass).async_update_device(satellite.id, area_id=ar.async_get(hass).async_get_area_by_name("Obývák").id)

    aioclient_mock.clear_requests()
    aioclient_mock.post(JEV_URL, json=jev("turn_on", "Lampa u gauče", all_of_kind=0.6, kind="light"))
    result = await conversation.async_converse(
        hass, "Rozsviť světlo", None, Context(), language="cs", agent_id=agent_id, device_id=satellite.id
    )
    assert result.response.speech["plain"]["speech"] == "Hotovo."
    assert sorted(calls[-1].data["entity_id"]) == ["light.lampa_gauc", "light.lampa_okno"]

    # "všechna" still means the whole house.
    result = await conversation.async_converse(
        hass, "Rozsviť všechna světla", None, Context(), language="cs", agent_id=agent_id, device_id=satellite.id
    )
    assert result.response.speech["plain"]["speech"] == "Hotovo."
    assert len(calls[-1].data["entity_id"]) == 3


async def test_device_not_in_house_is_not_replaced_by_the_only_candidate(hass: HomeAssistant, agent_id, aioclient_mock):
    calls = async_mock_service(hass, "cover", "close_cover")
    _, speech = await say(hass, agent_id, aioclient_mock, "Stáhni žaluzie", jev("close", "none", target_conf=0.98))
    assert speech == "Takové zařízení tu nemám."
    assert not calls
