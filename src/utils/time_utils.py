"""Timezone helpers for quote freshness checks."""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def ensure_utc(dt: datetime) -> datetime:
    """Return a timezone-aware UTC datetime, assuming naive inputs are UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def quote_age_seconds(timestamp: datetime, now: datetime | None = None) -> float:
    """Return quote age in seconds relative to a UTC-aware reference time."""
    quote_time = ensure_utc(timestamp)
    reference_time = ensure_utc(now) if now is not None else utc_now()
    return (reference_time - quote_time).total_seconds()


def is_stale(
    timestamp: datetime,
    max_age_seconds: float,
    now: datetime | None = None,
) -> bool:
    """Return True when quote age is greater than the allowed maximum."""
    return quote_age_seconds(timestamp, now=now) > max_age_seconds
