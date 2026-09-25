# Jev Conversation

Czech conversation agent for Home Assistant Assist on [TypeSafe Jev](https://docs.typesafe.ai/),
a System One model that picks from typed options instead of generating text. One request per
command, about 300 ms.

Jev picks the intent and the device. Code checks the domain, parses numbers, asks back or asks for
confirmation, and acts only through Home Assistant services.

## Install

HACS: three-dot menu, Custom repositories, add `https://github.com/matejgordon/ha-jev-conversation`
with type Integration, then download **Jev Conversation** and restart.

Manual: copy `custom_components/jev_conversation` from the latest release into
`config/custom_components/` and restart.

Requires Home Assistant 2026.9 or newer.

## Set up

Settings, Devices and services, Add integration, **Jev Conversation**:

| Field | Default | Note |
|---|---|---|
| API key | | OpenRouter key, or a TypeSafe key |
| API address | `https://openrouter.ai/api` | TypeSafe direct: `https://api.typesafe.ai` |
| Model | `typesafe/jev-1.13-20260917` | pinned so thresholds stay valid; TypeSafe direct: `jev-1.13.0` |
| Execute from confidence | 0.85 | |
| Ask back from confidence | 0.5 | |

The key is tested before the entry is created. Thresholds can be changed later under Configure.

Then Settings, Voice assistants, your Czech pipeline: set Conversation agent to **Jev** and keep
**Prefer handling commands locally** on, so exact sentences stay with Home Assistant's own intents.

## What it does

| Case | Result |
|---|---|
| Confidence at or above the execute threshold | acts, says "Hotovo." |
| Between the thresholds, device unclear | "Myslíš Lampa u gauče, nebo Lampa u okna?" and listens |
| Between the thresholds, device clear | "Mám zapnout …?" and listens |
| Below the ask threshold | "Nerozumím.", nothing done |
| Lock, alarm, cover with device class garage or gate | always "Opravdu …?" first, regardless of confidence |
| Group across rooms without "všechna/všude/celý dům" | asks first |
| Value missing ("Nastav topení v ložnici") | "Na kolik stupňů?", the reply is parsed without another model call |
| Question ("Kolik je CO2?") | answers from the entity state |
| API error or timeout (5 s) | "Jev teď neodpovídá…", nothing done |

Only entities exposed to Assist are sent, with their area, aliases, domain and state. Values are parsed
in code from digits or Czech words: `22,5`, `dvaadvacet a půl`, `třicet procent`, `naplno`,
`půl osmé`, `v osm večer`.

## Logs

```yaml
logger:
  logs:
    custom_components.jev_conversation: info   # latency of each Jev call and of each command
    # debug: also Jev's full answers with probabilities, for tuning thresholds
```

The API key is never logged.

## Tips

- Give every device a room. A light without one is invisible to "Zhasni v obýváku".
- Add Czech aliases to devices with English names ("washer-outlet" → "pračka").

## Not done yet

- Several devices named by part of their names ("stropní světla" for three bulbs): it asks about the
  whole kind instead.
- Changes by an amount ("o dva stupně víc"): it asks for the target value.
- Delayed actions ("za deset minut") and alarm codes.
- The satellite's room is used only for groups ("Zhasni světla" = lights in that room), not to pick
  between same-named devices.
- More than 254 exposed entities: refused with a message (Jev allows 255 options per question).

## Development

```sh
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements-test.txt
.venv/bin/pytest
```

## Related

[AboveColin/HA-Jev](https://github.com/AboveColin/HA-Jev) is a broader Jev integration (sensors,
actions, an English-question conversation agent). This one is Czech-only and keeps the agent small.
It is not affiliated with TypeSafe.
