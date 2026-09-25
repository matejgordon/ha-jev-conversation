"""Czech numbers and times in voice commands, written as digits or words.

Jev decides intent and target; values are parsed here, because the model is
not reliable with numbers (see the jev-1.13 jaggedness notes).
"""

from __future__ import annotations

import re

_UNITS = {
    "nula": 0, "jedna": 1, "jeden": 1, "jedno": 1, "jednu": 1, "dva": 2, "dvě": 2,
    "tři": 3, "čtyři": 4, "pět": 5, "šest": 6, "sedm": 7, "osm": 8, "devět": 9,
    # Genitive forms: "o dvou stupních", "na pěti procentech".
    "jedné": 1, "jednoho": 1, "dvou": 2, "tří": 3, "čtyř": 4, "pěti": 5,
    "šesti": 6, "sedmi": 7, "osmi": 8, "devíti": 9,
}
_TEENS = {
    "deset": 10, "jedenáct": 11, "dvanáct": 12, "třináct": 13, "čtrnáct": 14,
    "patnáct": 15, "šestnáct": 16, "sedmnáct": 17, "osmnáct": 18, "devatenáct": 19,
}
_TENS = {
    "dvacet": 20, "třicet": 30, "čtyřicet": 40, "padesát": 50, "šedesát": 60,
    "sedmdesát": 70, "osmdesát": 80, "devadesát": 90,
}
_WORDS = {
    **_UNITS, **_TEENS, **_TENS, "sto": 100,
    **{w + "i": v for w, v in {**_TEENS, **_TENS}.items()},  # "dvaceti", "deseti"
}
# "dvaadvacet", "jednadvacet", "pětatřicet"
_COMPOUND = re.compile(
    r"^(jedn|dva|tři|čtyři|pět|šest|sedm|osm|devět)a(" + "|".join(_TENS) + r")i?$"
)
_COMPOUND_UNITS = {"jedn": 1, "dva": 2, "tři": 3, "čtyři": 4, "pět": 5,
                   "šest": 6, "sedm": 7, "osm": 8, "devět": 9}
_EXTREMES = {"maximum": 100, "maximální": 100, "naplno": 100, "plno": 100,
             "minimum": 1, "minimální": 1, "půl": 50, "polovinu": 50, "polovina": 50}
_TOKEN = re.compile(r"\d+(?:[.,]\d+)?|\w+")

# Ordinal genitive hours for "půl osmé" (7:30).
_ORDINAL_HOURS = {
    "první": 1, "jedné": 1, "druhé": 2, "třetí": 3, "čtvrté": 4, "páté": 5,
    "šesté": 6, "sedmé": 7, "osmé": 8, "deváté": 9, "desáté": 10,
    "jedenácté": 11, "dvanácté": 12,
}
_RELATIVE = re.compile(r"\bo\s+(\d|" + "|".join(_WORDS) + r")", re.IGNORECASE)


def _word_value(word: str) -> int | None:
    if word in _WORDS:
        return _WORDS[word]
    if m := _COMPOUND.match(word):
        return _COMPOUND_UNITS[m.group(1)] + _TENS[m.group(2)]
    return None


def _numbers(text: str, *, extremes: bool) -> list[float]:
    """Every number in the text, in order; "dvacet dva" and "22 a půl" are one number."""
    tokens = _TOKEN.findall(text.lower())
    found: list[float] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if tok[0].isdigit():
            value: float | None = float(tok.replace(",", "."))
        else:
            value = _word_value(tok)
        if value is None:
            if extremes and tok in _EXTREMES and not (tok == "půl" and i and tokens[i - 1] == "a"):
                found.append(_EXTREMES[tok])
            i += 1
            continue
        if value in _TENS.values() and nxt in _UNITS and _UNITS[nxt] > 0:
            value += _UNITS[nxt]  # "dvacet dva"
            i += 1
            nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if nxt == "a" and i + 2 < len(tokens) and tokens[i + 2] == "půl":
            value += 0.5  # "dvacet dva a půl"
            i += 2
        elif nxt in ("celá", "celých") and i + 2 < len(tokens):
            frac = tokens[i + 2]
            digit = int(frac[0]) if frac.isdigit() else _UNITS.get(frac)
            if digit is not None:
                value += digit / 10  # "dvacet dva celá pět"
                i += 2
        found.append(value)
        i += 1
    return found


def parse_number(text: str) -> float | None:
    """The last number said, so "nastav topení 2 na 22" gives 22. None if there is none.

    Also reads "maximum"/"naplno" as 100, "minimum" as 1 and "půl"/"polovinu" as 50.
    """
    found = _numbers(text, extremes=True)
    return found[-1] if found else None


def is_relative(text: str) -> bool:
    """True for a change by an amount ("o dva stupně", "o 10 %"), which is not a level."""
    return bool(_RELATIVE.search(text))


def parse_time(text: str) -> tuple[int, int] | None:
    """(hour, minute) from "7:30", "v sedm třicet", "půl osmé", "čtvrt na osm", "v osm večer"."""
    low = text.lower()
    hm: tuple[int, int] | None = None
    if m := re.search(r"\b(\d{1,2})[:.](\d{2})\b", low):
        hm = (int(m.group(1)), int(m.group(2)))
    elif (m := re.search(r"\bpůl\s+(\w+)", low)) and m.group(1) in _ORDINAL_HOURS:
        hm = (_ORDINAL_HOURS[m.group(1)] - 1 or 12, 30)
    elif m := re.search(r"\b(tři\s+)?čtvrt[ě]?\s+na\s+(\w+)", low):
        hour = int(m.group(2)) if m.group(2).isdigit() else _word_value(m.group(2))
        if hour:
            hm = (hour - 1 or 12, 45 if m.group(1) else 15)
    else:
        found = [int(n) for n in _numbers(low, extremes=False) if n == int(n)]
        if found:
            minute = found[1] if len(found) > 1 and found[1] < 60 else 0
            hm = (found[0], minute)
    if hm is None:
        return None
    hour, minute = hm
    if hour < 12 and re.search(r"\b(večer|odpoledne|v noci)\b", low):
        hour += 12
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None
    return hour, minute
