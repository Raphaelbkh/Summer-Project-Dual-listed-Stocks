from datetime import datetime, timedelta, timezone

from src.utils.time_utils import ensure_utc, is_stale, quote_age_seconds, utc_now


def test_utc_now_returns_timezone_aware_utc_datetime() -> None:
    now = utc_now()

    assert now.tzinfo == timezone.utc


def test_naive_datetime_becomes_utc_aware() -> None:
    dt = datetime(2026, 1, 1, 12, 0)

    result = ensure_utc(dt)

    assert result.tzinfo == timezone.utc
    assert result.hour == 12


def test_timezone_aware_datetime_remains_valid() -> None:
    cet = timezone(timedelta(hours=1))
    dt = datetime(2026, 1, 1, 13, 0, tzinfo=cet)

    result = ensure_utc(dt)

    assert result.tzinfo == timezone.utc
    assert result.hour == 12


def test_quote_age_seconds_works() -> None:
    timestamp = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    now = datetime(2026, 1, 1, 12, 0, 5, tzinfo=timezone.utc)

    assert quote_age_seconds(timestamp, now=now) == 5.0


def test_stale_quote_detected() -> None:
    timestamp = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    now = datetime(2026, 1, 1, 12, 0, 6, tzinfo=timezone.utc)

    assert is_stale(timestamp, max_age_seconds=5, now=now) is True


def test_fresh_quote_not_stale() -> None:
    timestamp = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    now = datetime(2026, 1, 1, 12, 0, 5, tzinfo=timezone.utc)

    assert is_stale(timestamp, max_age_seconds=5, now=now) is False
