"""Number formatting for market tables: one place, consistent signs, safe on missing data.

    {% load market_format %}
    {{ etf.change|signed_money }}   ->  -$25.34 / +$0.59 / $0.00 / —
    {{ etf.change_pct|signed_pct }} ->  -3.52% / +0.62% / 0.00% / —
    {{ etf.change_pct|direction }}  ->  negative / positive / flat / missing   (CSS class)
"""
import math

from django import template

register = template.Library()

MISSING = "—"


def _num(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _sign(v: float) -> str:
    # Round first so a value like -0.004 prints as "0.00", not "-0.00".
    if round(v, 2) > 0:
        return "+"
    if round(v, 2) < 0:
        return "-"
    return ""


@register.filter
def signed_money(value) -> str:
    v = _num(value)
    return MISSING if v is None else f"{_sign(v)}${abs(v):,.2f}"


@register.filter
def signed_pct(value) -> str:
    v = _num(value)
    return MISSING if v is None else f"{_sign(v)}{abs(v):.2f}%"


@register.filter
def money(value) -> str:
    v = _num(value)
    return MISSING if v is None else f"${v:,.2f}"


@register.filter
def compact_money(value) -> str:
    """4978144444416 -> $4.98T. For market caps and deal sizes."""
    v = _num(value)
    if v is None:
        return MISSING
    for size, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(v) >= size:
            return f"${v / size:,.2f}{suffix}"
    return f"${v:,.0f}"


@register.filter
def pct_vs(value, base):
    """Percent difference of value relative to base: {{ target|pct_vs:price|signed_pct }}."""
    v, b = _num(value), _num(base)
    if v is None or b is None or b == 0:
        return None
    return (v - b) / b * 100.0


@register.filter
def direction(value) -> str:
    v = _num(value)
    if v is None:
        return "missing"
    return {"+": "positive", "-": "negative", "": "flat"}[_sign(v)]
