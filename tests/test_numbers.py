"""Czech numbers and times, in digits and in words."""

import pytest

from custom_components.jev_conversation.numbers import is_relative, parse_number, parse_time


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("nastav topení na 22 stupňů", 22),
        ("nastav topení na 22,5", 22.5),
        ("nastav topení na dvaadvacet stupňů", 22),
        ("nastav topení na dvacet dva", 22),
        ("nastav topení na jednadvacet a půl", 21.5),
        ("nastav topení na dvacet dva celá pět", 22.5),
        ("ztlum světlo na třicet procent", 30),
        ("ztlum světlo na 30 %", 30),
        ("dej světlo na maximum", 100),
        ("rozsviť naplno", 100),
        ("rozsviť na plno", 100),
        ("dej jas na minimum", 1),
        ("stáhni žaluzie na půl", 50),
        ("hlasitost na patnáct", 15),
        ("topení na devatenáct", 19),
        ("nastav topení 2 na 22", 22),
        ("zapni světlo", None),
    ],
)
def test_parse_number(text, expected):
    assert parse_number(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("budík na 7:30", (7, 30)),
        ("budík na sedm", (7, 0)),
        ("budík na sedm třicet", (7, 30)),
        ("budík na půl osmé", (7, 30)),
        ("budík na čtvrt na osm", (7, 15)),
        ("budík na tři čtvrtě na osm", (7, 45)),
        ("budík na osm večer", (20, 0)),
        ("budík na dvacet dva třicet", (22, 30)),
        ("budík", None),
    ],
)
def test_parse_time(text, expected):
    assert parse_time(text) == expected


def test_relative():
    assert is_relative("zvyš teplotu o dva stupně")
    assert is_relative("zesil o 10 %")
    assert not is_relative("nastav topení do dvaceti")
    assert not is_relative("nastav topení na dvacet")
