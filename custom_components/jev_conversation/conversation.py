"""Assist conversation agent: Jev picks intent and target, code checks and acts via services."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import re
import time
from typing import Literal, override

from homeassistant.components import conversation
from homeassistant.components.homeassistant.exposed_entities import async_should_expose
from homeassistant.core import Context, HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import intent
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import JevConfigEntry
from .api import JevAuthError, JevError
from .const import (
    CONF_ASK_THRESHOLD,
    CONF_EXECUTE_THRESHOLD,
    DEFAULT_ASK_THRESHOLD,
    DEFAULT_EXECUTE_THRESHOLD,
    DOMAIN,
)
from .numbers import is_relative, parse_number, parse_time

_LOGGER = logging.getLogger(__name__)

PENDING_TTL = 300  # seconds; Home Assistant keeps a conversation open for five minutes

# Question texts are Czech: on 30 Czech commands they scored 28/30, English ones 24/30.
ACTIONS = {
    # Imperatives in the descriptions: without them "Zapni televizi" split 48/52 between on and off.
    "turn_on": "Zapnout zařízení: zapni, rozsviť, pusť, spusť",
    "turn_off": "Vypnout zařízení: vypni, zhasni, zastav",
    "open": "Otevřít: otevři, vytáhni, zvedni (žaluzie, vrata, garáž)",
    "close": "Zavřít: zavři, stáhni (žaluzie, vrata, garáž)",
    "lock": "Zamknout: zamkni",
    "unlock": "Odemknout: odemkni",
    "arm": "Zapnout alarm nebo zabezpečení",
    "disarm": "Vypnout alarm nebo zabezpečení",
    "set_value": "Nastavit úroveň nebo hodnotu: nastav, ztlum, dej na (jas, teplota, poloha, hlasitost, čas)",
    "query_state": "Otázka na stav nebo hodnotu: je, svítí, kolik, jaký je",
    "activate_scene": "Spustit scénu, režim nebo skript",
    "none": "Není to příkaz pro domácnost: povídání, počasí, poděkování, obecné otázky",
}
_SWITCHABLE = {"light", "switch", "fan", "media_player", "climate", "input_boolean", "humidifier"}
# Domains an action may touch; the model's target is overruled when it picks outside them.
ACTION_DOMAINS: dict[str, set[str] | None] = {
    "turn_on": _SWITCHABLE,
    "turn_off": _SWITCHABLE,
    "open": {"cover"},
    "close": {"cover"},
    "lock": {"lock"},
    "unlock": {"lock"},
    "arm": {"alarm_control_panel"},
    "disarm": {"alarm_control_panel"},
    "set_value": {"light", "climate", "cover", "media_player", "fan", "input_number", "input_datetime"},
    "activate_scene": {"scene", "script"},
    "query_state": None,
}
SERVICES = {
    "turn_on": lambda domain: (domain, "turn_on"),
    "turn_off": lambda domain: (domain, "turn_off"),
    "open": lambda domain: ("cover", "open_cover"),
    "close": lambda domain: ("cover", "close_cover"),
    "lock": lambda domain: ("lock", "lock"),
    "unlock": lambda domain: ("lock", "unlock"),
    "arm": lambda domain: ("alarm_control_panel", "alarm_arm_away"),
    "disarm": lambda domain: ("alarm_control_panel", "alarm_disarm"),
    "activate_scene": lambda domain: (domain, "turn_on"),
}
VERBS = {
    "turn_on": "zapnout", "turn_off": "vypnout", "open": "otevřít", "close": "zavřít",
    "lock": "zamknout", "unlock": "odemknout", "arm": "zapnout", "disarm": "vypnout",
    "set_value": "nastavit", "activate_scene": "spustit",
}
DOMAIN_TYPES = {
    "light": "Světla, lampy, LED pásky",
    "switch": "Zásuvky a spínané spotřebiče",
    "fan": "Ventilátory",
    "media_player": "Televize a reproduktory",
    "climate": "Topení, klimatizace, termostat",
    "cover": "Žaluzie, rolety, vrata, garáž",
    "lock": "Zámky dveří",
    "alarm_control_panel": "Alarm",
    "scene": "Scény",
    "script": "Skripty",
    "sensor": "Senzory: teplota, vlhkost, kvalita vzduchu",
    "binary_sensor": "Čidla: dveře, okna, pohyb, přítomnost",
    "input_boolean": "Přepínače",
    "input_number": "Číselná nastavení",
    "input_datetime": "Budíky a časy",
    "vacuum": "Vysavače",
}
STATES_CS = {
    "on": "zapnuto", "off": "vypnuto", "open": "otevřeno", "closed": "zavřeno",
    "opening": "otevírá se", "closing": "zavírá se", "locked": "zamčeno", "unlocked": "odemčeno",
    "locking": "zamyká se", "unlocking": "odemyká se", "jammed": "zaseklý zámek",
    "unavailable": "nedostupné", "unknown": "neznámý stav", "playing": "hraje",
    "paused": "pozastaveno", "idle": "nečinné", "standby": "pohotovost", "heat": "topí",
    "cool": "chladí", "auto": "automatika", "heat_cool": "automatika", "dry": "vysoušení",
    "fan_only": "jen ventilátor", "armed_away": "alarm zapnutý", "armed_home": "alarm zapnutý doma",
    "armed_night": "alarm zapnutý na noc", "disarmed": "alarm vypnutý", "triggered": "alarm spuštěný",
    "arming": "alarm se zapíná", "pending": "alarm čeká", "home": "doma", "not_home": "pryč",
    "cleaning": "uklízí", "docked": "v nabíječce",
}
_BINARY_STATES = {
    **dict.fromkeys(("door", "window", "garage_door", "opening"), ("otevřeno", "zavřeno")),
    **dict.fromkeys(("presence", "occupancy"), ("přítomen", "nepřítomen")),
    "motion": ("pohyb", "klid"),
}
SENSITIVE_DOMAINS = {"lock", "alarm_control_panel"}
SENSITIVE_COVERS = {"garage", "gate"}

# A whole-house group needs these words; "zhasni stropní světla" once meant every light in the house.
WHOLE_HOUSE = re.compile(r"\bvšech|\bvšude|\bcel(ý|ém|ou) (dům|domě|byt|bytě)", re.IGNORECASE)

DONE = "Hotovo."
NOT_UNDERSTOOD = "Nerozumím."


@dataclass(slots=True)
class Device:
    """One exposed entity, as the model and the code see it."""

    entity_id: str
    key: str  # unique option label sent to Jev
    name: str
    aliases: list[str]
    area: str | None
    domain: str
    state: State

    @property
    def sensitive(self) -> bool:
        return self.domain in SENSITIVE_DOMAINS or (
            self.domain == "cover" and self.state.attributes.get("device_class") in SENSITIVE_COVERS
        )


@dataclass(slots=True)
class Pending:
    """A question we asked and the command it belongs to."""

    kind: Literal["confirm", "clarify", "value"]
    question: str
    action: str
    targets: list[Device]
    text: str  # where the value is read from
    options: dict[str, Device] = field(default_factory=dict)
    confirmed: bool = False
    created: float = field(default_factory=time.monotonic)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JevConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the conversation entity."""
    async_add_entities([JevConversationEntity(entry)])


def describe(state: State) -> str:
    """The state in Czech, short enough to say aloud."""
    attrs = state.attributes
    if state.domain == "binary_sensor" and (pair := _BINARY_STATES.get(attrs.get("device_class"))):
        text = pair[0] if state.state == "on" else pair[1] if state.state == "off" else STATES_CS.get(state.state, state.state)
    elif (unit := attrs.get("unit_of_measurement")) and state.state not in ("unavailable", "unknown"):
        text = f"{state.state.replace('.', ',')} {unit}"
    else:
        text = STATES_CS.get(state.state, state.state)
    if state.domain == "climate" and (current := attrs.get("current_temperature")) is not None:
        text += f", {str(current).replace('.', ',')} °C"
    return text


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " a " + names[-1]


class JevConversationEntity(conversation.ConversationEntity):
    """Czech voice commands through Jev."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = conversation.ConversationEntityFeature.CONTROL

    def __init__(self, entry: JevConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Jev",
            manufacturer="TypeSafe",
            model=entry.runtime_data.model,
            entry_type=DeviceEntryType.SERVICE,
        )
        self._pending: dict[str, Pending] = {}

    @property
    @override
    def supported_languages(self) -> list[str]:
        return ["cs"]

    @override
    async def _async_handle_message(
        self, user_input: conversation.ConversationInput, chat_log: conversation.ChatLog
    ) -> conversation.ConversationResult:
        start = time.monotonic()
        try:
            speech = await self._process(user_input.text, chat_log.conversation_id, user_input.context)
        except JevAuthError:
            _LOGGER.error("Jev rejected the API key")
            speech = "Jev odmítl API klíč, zkontroluj nastavení integrace."
        except JevError as err:
            _LOGGER.warning("Jev request failed, nothing executed: %s", err)
            speech = "Jev teď neodpovídá, zkus to prosím za chvíli."
        _LOGGER.info("Command handled in %.0f ms: %s", (time.monotonic() - start) * 1000, speech)
        _LOGGER.debug("Command text: %s", user_input.text)
        chat_log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(agent_id=user_input.agent_id, content=speech)
        )
        # A reply ending in "?" keeps the conversation open, so satellites listen for the answer.
        return conversation.async_get_result_from_chat_log(user_input, chat_log)

    @property
    def _thresholds(self) -> tuple[float, float]:
        cfg = {**self._entry.data, **self._entry.options}
        return (
            cfg.get(CONF_EXECUTE_THRESHOLD, DEFAULT_EXECUTE_THRESHOLD),
            cfg.get(CONF_ASK_THRESHOLD, DEFAULT_ASK_THRESHOLD),
        )

    async def _process(self, text: str, conversation_id: str, context: Context) -> str:
        pending = self._pending.pop(conversation_id, None)
        if pending and time.monotonic() - pending.created < PENDING_TTL:
            if (reply := await self._resume(pending, text, conversation_id, context)) is not None:
                return reply

        house = self._house()
        if not house:
            return "Nemám vystavená žádná zařízení."
        # ponytail: one flat target question, capped by Jev's 255 options per Choice;
        # ask the room first and then the device if a house ever exposes more.
        if len(house) > 254:
            return "Pro Assist je vystaveno přes 254 zařízení, tolik zatím neumím."
        execute, ask = self._thresholds
        answers = await self._entry.runtime_data.ask(self._state(text, house), self._questions(house))

        action_answer = answers["action"]
        action = action_answer["choice"]
        if action == "none":
            return "Tohle neumím." if action_answer["confidence"] >= ask else NOT_UNDERSTOOD
        targets, target_conf, ranked = self._targets(action, answers, house)
        if not targets:
            return "Takové zařízení tu nemám."
        conf = min(action_answer["confidence"], target_conf)
        if conf < ask:
            return NOT_UNDERSTOOD
        if action == "query_state":
            return " ".join(f"{d.name}: {describe(d.state)}." for d in targets[:5])
        whole_house = len(targets) > 1 and len({d.area for d in targets}) > 1
        if whole_house and not WHOLE_HOUSE.search(text):
            return self._ask_confirm(action, targets, text, conversation_id)
        if conf >= execute:
            return await self._act(action, targets, text, conversation_id, context)
        if action == "set_value" and target_conf >= execute and isinstance(self._value(targets, text), str):
            # Saying the value confirms the intent, so ask for it rather than for a yes.
            return await self._act(action, targets, text, conversation_id, context)
        # In between: ask which device when the target is the doubt, else ask to confirm.
        if target_conf < execute and len(ranked) > 1:
            question = f"Myslíš {ranked[0].name}, nebo {ranked[1].name}?"
            self._pending[conversation_id] = Pending(
                "clarify", question, action, [], text, options={d.key: d for d in ranked[:2]}
            )
            return question
        return self._ask_confirm(action, targets, text, conversation_id)

    def _ask_confirm(self, action: str, targets: list[Device], text: str, conversation_id: str) -> str:
        opener = "Opravdu" if any(d.sensitive for d in targets) else "Mám"
        names = _join([d.name for d in targets]) if len(targets) <= 3 else f"{len(targets)} zařízení"
        question = f"{opener} {VERBS[action]} {names}?"
        self._pending[conversation_id] = Pending("confirm", question, action, targets, text)
        return question

    async def _resume(self, pending: Pending, text: str, conversation_id: str, context: Context) -> str | None:
        """Handle the reply to our question. None means it is a new command."""
        execute, _ = self._thresholds
        if pending.kind == "value":
            return await self._act(
                pending.action, pending.targets, text, conversation_id, context, pending.confirmed, ask_value=False
            )

        state = {"otázka": pending.question, "odpověď": text}
        if pending.kind == "confirm":
            answer = (await self._entry.runtime_data.ask(state, {"reply": {
                "type": "choice",
                "instructions": "Souhlasí `odpověď` s tím, na co se ptá `otázka`?",
                "criteria": {"yes": "Ano, souhlasí nebo potvrzuje", "no": "Ne, odmítá, ruší nebo chce něco jiného"},
            }}))["reply"]
            if answer["choice"] == "yes" and answer["confidence"] >= execute:
                return await self._act(pending.action, pending.targets, pending.text, conversation_id, context, True)
            return "Dobře, nechám to být."

        answer = (await self._entry.runtime_data.ask(state, {"reply": {
            "type": "choice",
            "instructions": "Které zařízení z `otázka` vybírá `odpověď`?",
            "criteria": {**dict.fromkeys(pending.options), "none": "Žádné z nich, nebo je to jiný příkaz"},
        }}))["reply"]
        if answer["choice"] in pending.options and answer["confidence"] >= execute:
            return await self._act(
                pending.action, [pending.options[answer["choice"]]], pending.text, conversation_id, context
            )
        return None

    async def _act(
        self,
        action: str,
        targets: list[Device],
        text: str,
        conversation_id: str,
        context: Context,
        confirmed: bool = False,
        ask_value: bool = True,
    ) -> str:
        """Check the value and the confirmation, then call the services."""
        data: dict = {}
        if action == "set_value":
            value = self._value(targets, text)
            if isinstance(value, str):
                if value.endswith("?"):
                    if not ask_value:
                        return "Nerozuměl jsem hodnotě."
                    self._pending[conversation_id] = Pending("value", value, action, targets, text, confirmed=confirmed)
                return value
            data = value
        if not confirmed and any(d.sensitive for d in targets):
            return self._ask_confirm(action, targets, text, conversation_id)

        by_domain: dict[str, list[str]] = {}
        for d in targets:
            by_domain.setdefault(d.domain, []).append(d.entity_id)
        try:
            for domain, entity_ids in by_domain.items():
                if action == "set_value":
                    service_domain, service, extra = data[domain]
                else:
                    (service_domain, service), extra = SERVICES[action](domain), {}
                await self.hass.services.async_call(
                    service_domain, service, {"entity_id": entity_ids, **extra}, blocking=True, context=context
                )
        except HomeAssistantError as err:
            _LOGGER.warning("Service call for %s failed: %s", action, err)
            if (err.translation_key or "").startswith("code_"):
                return "Tohle vyžaduje kód a ten hlasem zadat neumím."
            return "To se nepovedlo."
        return DONE

    def _value(self, targets: list[Device], text: str) -> dict[str, tuple[str, str, dict]] | str:
        """Service data per domain parsed from the text, or what to say instead (a question ends in "?")."""
        # Digits in device and room names are not values ("Lampa 2").
        for d in targets:
            for name in (d.name, *d.aliases, d.area or ""):
                if name:
                    text = re.sub(re.escape(name), " ", text, flags=re.IGNORECASE)
        if is_relative(text):
            return "Změnu o kolik zatím neumím, řekni cílovou hodnotu."
        domain = targets[0].domain
        attrs = targets[0].state.attributes
        if domain == "input_datetime":
            if (hm := parse_time(text)) is None:
                return "Na kolik hodin?"
            return {domain: ("input_datetime", "set_datetime", {"time": f"{hm[0]:02d}:{hm[1]:02d}:00"})}
        value = parse_number(text)
        if value is None:
            return "Na kolik stupňů?" if domain == "climate" else "Na kolik?" if domain == "input_number" else "Na kolik procent?"
        if domain == "climate":
            low, high = attrs.get("min_temp", 5), attrs.get("max_temp", 35)
        elif domain == "input_number":
            low, high = attrs.get("min", float("-inf")), attrs.get("max", float("inf"))
        else:
            low, high = 0, 100
        if not low <= value <= high:
            return "To je mimo rozsah."
        return {
            "light": ("light", "turn_on", {"brightness_pct": value}),
            "climate": ("climate", "set_temperature", {"temperature": value}),
            "cover": ("cover", "set_cover_position", {"position": int(value)}),
            "media_player": ("media_player", "volume_set", {"volume_level": value / 100}),
            "fan": ("fan", "set_percentage", {"percentage": int(value)}),
            "input_number": ("input_number", "set_value", {"value": value}),
        }

    def _targets(self, action: str, answers: dict, house: list[Device]) -> tuple[list[Device], float, list[Device]]:
        """(targets, confidence, ranked candidates) with the action's domains enforced in code."""
        domains = ACTION_DOMAINS[action]
        allowed = [d for d in house if domains is None or d.domain in domains]
        kind = answers["device_type"]
        if answers["all_of_kind"]["noul"] >= 0.5 and kind["choice"] != "none" and (
            domains is None or kind["choice"] in domains
        ):
            area = answers.get("area", {"choice": "none"})
            group = [d for d in allowed if d.domain == kind["choice"] and area["choice"] in ("none", d.area)]
            if group:
                conf = kind["confidence"] if area["choice"] == "none" else min(kind["confidence"], area["confidence"])
                return group, conf, []
        if len(allowed) == 1:
            return allowed, 1.0, []
        target = answers["target"]
        probs = target["probabilities"]
        ranked = sorted(allowed, key=lambda d: probs.get(d.key, 0.0), reverse=True)
        if not ranked:
            return [], 0.0, []
        # The model's confidence only counts when its pick is a device this action can touch.
        conf = target["confidence"] if target["choice"] == ranked[0].key else 0.0
        second = ranked[1:2] if probs.get(ranked[1].key, 0.0) >= 0.05 else []
        return ranked[:1], conf, ranked[:1] + second

    def _house(self) -> list[Device]:
        """Entities exposed to Assist, with area and aliases."""
        hass = self.hass
        ent_reg, dev_reg, area_reg = er.async_get(hass), dr.async_get(hass), ar.async_get(hass)
        devices: list[Device] = []
        for state in hass.states.async_all():
            if state.domain == conversation.DOMAIN or not async_should_expose(
                hass, conversation.DOMAIN, state.entity_id
            ):
                continue
            entry = ent_reg.async_get(state.entity_id)
            area_id = entry.area_id if entry else None
            if entry and not area_id and entry.device_id and (device := dev_reg.async_get(entry.device_id)):
                area_id = device.area_id
            area = area_reg.async_get_area(area_id) if area_id else None
            aliases = [a for a in intent.async_get_entity_aliases(hass, entry, state=state) if a != state.name]
            devices.append(
                Device(state.entity_id, state.name, state.name, aliases, area.name if area else None, state.domain, state)
            )
        # Option keys must be unique: add the room, then the entity id, to repeated names.
        for attr in ("area", "entity_id"):
            seen: dict[str, int] = {}
            for d in devices:
                seen[d.key] = seen.get(d.key, 0) + 1
            for d in devices:
                if seen[d.key] > 1:
                    d.key = f"{d.key} ({getattr(d, attr) or d.entity_id})"
        return devices

    def _state(self, text: str, house: list[Device]) -> dict:
        devices = []
        for d in house:
            item = {"id": d.entity_id, "name": d.key, "state": describe(d.state)}
            if d.area:
                item["area"] = d.area
            if d.aliases:
                item["také"] = d.aliases
            devices.append(item)
        return {"command": text, "devices": devices}

    def _questions(self, house: list[Device]) -> dict[str, dict]:
        present = {d.domain for d in house}
        actions = {
            a: desc for a, desc in ACTIONS.items()
            if ACTION_DOMAINS.get(a, None) is None or ACTION_DOMAINS[a] & present
        }
        questions: dict[str, dict] = {
            "action": {"type": "choice", "instructions": "Co `command` po chytré domácnosti chce?", "criteria": actions},
            "device_type": {
                "type": "choice",
                "instructions": "Jakého druhu zařízení se `command` týká?",
                "criteria": {
                    **{dom: DOMAIN_TYPES.get(dom, dom) for dom in sorted(present)},
                    "none": "Druh zařízení není zmíněn",
                },
            },
            "all_of_kind": {
                "type": "noul",
                "instructions": "Týká se `command` všech zařízení jednoho druhu (třeba všech světel), a ne jednoho zařízení?",
            },
            "target": {
                "type": "choice",
                "instructions": "Kterého zařízení z `devices` se `command` týká?",
                "criteria": {
                    **{d.key: f"také: {', '.join(d.aliases)}" if d.aliases else None for d in house},
                    "none": "Žádného z těchto zařízení",
                },
            },
        }
        area_reg = ar.async_get(self.hass)
        areas = {d.area for d in house if d.area}
        if areas:
            aliases = {a.name: sorted(a.aliases) for a in area_reg.async_list_areas()}
            questions["area"] = {
                "type": "choice",
                "instructions": "Kterou místnost `command` jmenuje?",
                "criteria": {
                    **{a: f"také: {', '.join(aliases[a])}" if aliases.get(a) else None for a in sorted(areas)},
                    "none": "Žádná místnost není zmíněna",
                },
            }
        return questions
