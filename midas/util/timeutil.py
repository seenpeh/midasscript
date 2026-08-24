"""Epoch-second <-> text conversions.

Every module used to carry its own copy of these three lines; they live here
now so a timestamp is formatted exactly one way across the whole project.
"""

from __future__ import annotations

from datetime import datetime, timezone

MINUTE_FORMAT = "%Y-%m-%d %H:%M"
DAY_FORMAT = "%Y-%m-%d"
ACCEPTED_INPUT_FORMATS = (MINUTE_FORMAT, DAY_FORMAT)


def to_utc(epoch) -> datetime:
    """Epoch seconds -> an aware UTC datetime."""
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc)


def format_minute(epoch) -> str:
    """Epoch seconds -> 'YYYY-MM-DD HH:MM' (UTC)."""
    return to_utc(epoch).strftime(MINUTE_FORMAT)


def format_day(epoch) -> str:
    """Epoch seconds -> 'YYYY-MM-DD' (UTC)."""
    return to_utc(epoch).strftime(DAY_FORMAT)


def parse_day(text: str) -> int:
    """'YYYY-MM-DD' -> epoch seconds (UTC). Raises ValueError otherwise."""
    return int(datetime.strptime(text, DAY_FORMAT)
               .replace(tzinfo=timezone.utc).timestamp())


def parse_timestamp(text: str | None) -> int | None:
    """Accept 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM' -> epoch seconds UTC.

    Empty/None input means "no bound" and returns None, so callers can pass an
    optional CLI flag or JSON field straight through.
    """
    if not text:
        return None
    text = text.strip()
    for fmt in ACCEPTED_INPUT_FORMATS:
        try:
            return int(datetime.strptime(text, fmt)
                       .replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
    raise ValueError(
        f"Unparseable date: {text!r}  (use YYYY-MM-DD or 'YYYY-MM-DD HH:MM')")


def now_utc_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
