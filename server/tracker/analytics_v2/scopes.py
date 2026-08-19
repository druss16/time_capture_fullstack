"""
Parses the incoming JSON request body for /api/analytics/query/ into validated
Scope / LensKey / TimeRange objects.

Request shape:
    {
        "scope":   {"type": "client", "ids": [42], "filters": {}},
        "lens":    "profitability",
        "time":    {"type": "relative", "value": "this_quarter"},
        "compare": {"type": "relative", "value": "last_quarter"}  // optional
    }
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from typing import Any, Optional

from django.utils import timezone

from .types import LensKey, Scope, ScopeType, TimeRange


class RequestParseError(ValueError):
    """Raised on malformed request body; serialized as HTTP 400."""


# ---------------------------------------------------------------------------
# Relative time expressions
# ---------------------------------------------------------------------------

def _today() -> date:
    return timezone.now().date()


def _start_of_week(d: date) -> date:
    """Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


def _start_of_quarter(d: date) -> date:
    q_start_month = ((d.month - 1) // 3) * 3 + 1
    return date(d.year, q_start_month, 1)


def _end_of_quarter(d: date) -> date:
    q_start = _start_of_quarter(d)
    last_month = q_start.month + 2
    return date(q_start.year, last_month, monthrange(q_start.year, last_month)[1])


def _shift_months(d: date, months: int) -> date:
    """Shift a date by N months, clamping to month-end."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    last_day = monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def resolve_relative_time(expr: str) -> TimeRange:
    """
    Map a relative expression to a concrete TimeRange.
    Supported expressions are deliberately limited and well-known.
    """
    today = _today()
    e = expr.lower().strip()
    
    if e == "today":
        return TimeRange(today, today, "Today", expr)
    
    if e == "yesterday":
        y = today - timedelta(days=1)
        return TimeRange(y, y, "Yesterday", expr)
    
    if e == "this_week":
        return TimeRange(_start_of_week(today), today, "This week", expr)
    
    if e == "last_week":
        last_week_end = _start_of_week(today) - timedelta(days=1)
        last_week_start = _start_of_week(last_week_end)
        return TimeRange(last_week_start, last_week_end, "Last week", expr)
    
    if e == "this_month":
        start = today.replace(day=1)
        return TimeRange(start, today, today.strftime("%B %Y"), expr)
    
    if e == "last_month":
        first_this = today.replace(day=1)
        last_month_end = first_this - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        return TimeRange(last_month_start, last_month_end,
                         last_month_end.strftime("%B %Y"), expr)
    
    if e == "this_quarter":
        start = _start_of_quarter(today)
        return TimeRange(start, today, _quarter_label(start), expr)
    
    if e == "last_quarter":
        this_q_start = _start_of_quarter(today)
        last_q_end = this_q_start - timedelta(days=1)
        last_q_start = _start_of_quarter(last_q_end)
        return TimeRange(last_q_start, last_q_end, _quarter_label(last_q_start), expr)
    
    if e == "ytd":
        start = date(today.year, 1, 1)
        return TimeRange(start, today, f"YTD {today.year}", expr)
    
    if e == "last_30_days":
        return TimeRange(today - timedelta(days=29), today, "Last 30 days", expr)
    
    if e == "last_90_days":
        return TimeRange(today - timedelta(days=89), today, "Last 90 days", expr)
    
    if e == "trailing_12_months":
        return TimeRange(_shift_months(today, -12) + timedelta(days=1), today,
                         "Trailing 12 months", expr)
    
    # Specific calendar quarters: q1_2026, q2_2025, etc.
    if e.startswith("q") and "_" in e:
        try:
            q_str, year_str = e.split("_", 1)
            q = int(q_str[1])
            year = int(year_str)
            if q not in (1, 2, 3, 4):
                raise ValueError("invalid quarter")
            start_month = (q - 1) * 3 + 1
            start = date(year, start_month, 1)
            end = _end_of_quarter(start)
            return TimeRange(start, end, f"Q{q} {year}", expr)
        except (ValueError, IndexError) as exc:
            raise RequestParseError(f"Invalid quarter expression '{expr}': {exc}")
    
    # Busy season — CPA-specific, configurable per firm in future
    if e == "busy_season":
        # Jan 1 of current year through Apr 15
        year = today.year if today.month <= 4 else today.year + 1
        return TimeRange(date(year, 1, 1), date(year, 4, 15),
                         f"Busy season {year}", expr)
    
    if e == "extension_season":
        year = today.year
        return TimeRange(date(year, 4, 16), date(year, 10, 15),
                         f"Extension season {year}", expr)
    
    raise RequestParseError(f"Unknown relative time expression: '{expr}'")


def _quarter_label(start: date) -> str:
    q = (start.month - 1) // 3 + 1
    return f"Q{q} {start.year}"


# ---------------------------------------------------------------------------
# Request body parsing
# ---------------------------------------------------------------------------

VALID_SCOPE_TYPES: set[str] = {"firm", "client", "staff", "service", "engagement", "composite"}
VALID_LENS_KEYS: set[str] = {"pulse", "profitability", "utilization", "wip", "realization", "trends", "engagements"}


def parse_scope(raw: Any) -> Scope:
    """Parse a scope dict from the request body."""
    if not isinstance(raw, dict):
        raise RequestParseError("scope must be an object")
    
    scope_type = raw.get("type", "firm")
    if scope_type not in VALID_SCOPE_TYPES:
        raise RequestParseError(
            f"scope.type must be one of {sorted(VALID_SCOPE_TYPES)}, got '{scope_type}'"
        )
    
    ids_raw = raw.get("ids", [])
    if not isinstance(ids_raw, list):
        raise RequestParseError("scope.ids must be a list")
    
    try:
        ids = tuple(int(i) for i in ids_raw)
    except (TypeError, ValueError):
        raise RequestParseError("scope.ids must be a list of integers")
    
    filters = raw.get("filters", {})
    if not isinstance(filters, dict):
        raise RequestParseError("scope.filters must be an object")
    
    # 'firm' scope must not specify ids
    if scope_type == "firm" and ids:
        raise RequestParseError("scope.ids must be empty when type='firm'")
    
    # Non-firm scopes must specify at least one id, unless composite (which uses filters)
    if scope_type not in ("firm", "composite") and not ids:
        raise RequestParseError(f"scope.ids required when type='{scope_type}'")
    
    return Scope(
        type=scope_type,  # type: ignore[arg-type]
        ids=ids,
        filters=filters,
        label=str(raw.get("label", "")),
    )


def parse_lens(raw: Any) -> LensKey:
    if not isinstance(raw, str):
        raise RequestParseError("lens must be a string")
    if raw not in VALID_LENS_KEYS:
        raise RequestParseError(
            f"lens must be one of {sorted(VALID_LENS_KEYS)}, got '{raw}'"
        )
    return raw  # type: ignore[return-value]


def parse_time(raw: Any) -> TimeRange:
    """Parse a time spec — either {"type":"relative","value":"this_quarter"} or
    {"type":"absolute","value":{"start":"2026-04-01","end":"2026-06-30"}}."""
    if not isinstance(raw, dict):
        raise RequestParseError("time must be an object")
    
    t_type = raw.get("type", "relative")
    value = raw.get("value")
    
    if t_type == "relative":
        if not isinstance(value, str):
            raise RequestParseError("time.value must be a string for relative type")
        return resolve_relative_time(value)
    
    if t_type == "absolute":
        if not isinstance(value, dict):
            raise RequestParseError("time.value must be an object for absolute type")
        try:
            start = date.fromisoformat(value["start"])
            end = date.fromisoformat(value["end"])
        except (KeyError, ValueError) as exc:
            raise RequestParseError(f"Invalid absolute time range: {exc}")
        if start > end:
            raise RequestParseError("time.value.start must be <= end")
        label = f"{start.isoformat()} → {end.isoformat()}"
        return TimeRange(start, end, label)
    
    raise RequestParseError(f"time.type must be 'relative' or 'absolute', got '{t_type}'")


def parse_compare(raw: Any, base_time: TimeRange) -> Optional[TimeRange]:
    """Parse the optional compare spec. None if comparison wasn't requested."""
    if raw is None or raw == {}:
        return None
    if not isinstance(raw, dict):
        raise RequestParseError("compare must be null or an object")
    
    c_type = raw.get("type", "relative")
    value = raw.get("value")
    
    # Convenience: auto-resolve "prior_period" to a window of equal length
    # immediately preceding the base time range.
    if c_type == "relative" and value == "prior_period":
        delta = base_time.end - base_time.start
        end = base_time.start - timedelta(days=1)
        start = end - delta
        return TimeRange(start, end, "Prior period", "prior_period")
    
    return parse_time(raw)


def parse_request_body(body: dict) -> tuple[Scope, LensKey, TimeRange, Optional[TimeRange]]:
    """
    Top-level parser. Raises RequestParseError on any validation failure.
    Returns (scope, lens, time, compare-or-None).
    """
    if not isinstance(body, dict):
        raise RequestParseError("Request body must be a JSON object")
    
    scope = parse_scope(body.get("scope", {"type": "firm"}))
    lens = parse_lens(body.get("lens", "pulse"))
    time = parse_time(body.get("time", {"type": "relative", "value": "this_quarter"}))
    compare = parse_compare(body.get("compare"), time)
    
    return scope, lens, time, compare
