import pytest

from market.templatetags.market_format import compact_money, direction, money, pct_vs, signed_money, signed_pct


@pytest.mark.parametrize("value, expected", [
    (4_978_144_444_416, "$4.98T"),
    (205_498_654_747, "$205.50B"),
    (12_500_000, "$12.50M"),
    (950_000, "$950,000"),
    (None, "—"),
])
def test_compact_money(value, expected):
    assert compact_money(value) == expected


def test_pct_vs():
    assert pct_vs(110, 100) == pytest.approx(10.0)
    assert pct_vs(90, 100) == pytest.approx(-10.0)
    assert pct_vs(1, 0) is None
    assert pct_vs(None, 100) is None


@pytest.mark.parametrize("value, expected", [
    (-25.34, "-$25.34"),   # was rendered as "$-25.34"
    (0.59, "+$0.59"),
    (0, "$0.00"),
    (-0.004, "$0.00"),     # rounds to zero: no "-$0.00"
    (1234.5, "+$1,234.50"),
    (None, "—"),
    (float("nan"), "—"),
    ("abc", "—"),
])
def test_signed_money(value, expected):
    assert signed_money(value) == expected


@pytest.mark.parametrize("value, expected", [(-3.52, "-3.52%"), (0.62, "+0.62%"), (0.0, "0.00%"), (None, "—")])
def test_signed_pct(value, expected):
    assert signed_pct(value) == expected


def test_money():
    assert money(693.714) == "$693.71"
    assert money(None) == "—"


@pytest.mark.parametrize("value, expected", [(1.2, "positive"), (-0.5, "negative"), (0.001, "flat"), (None, "missing")])
def test_direction(value, expected):
    assert direction(value) == expected
