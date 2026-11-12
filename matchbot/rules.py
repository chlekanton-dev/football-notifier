"""Які сповіщення пора надсилати для матчу."""

from datetime import datetime, timedelta

from .espn import Match

EARLY = "early"
LATE = "late"
RESULT = "result"
CANCELLED = "cancelled"

EARLY_REMINDER = timedelta(hours=10)
LATE_REMINDER = timedelta(minutes=30)
# Розклад GitHub Actions запізнюється, тому нагадування ще має сенс одразу після початку
KICKOFF_GRACE = timedelta(minutes=5)
# Старіші результати не надсилаємо, щоб після простою бот не засипав канал
RESULT_MAX_AGE = timedelta(hours=6)

CANCELLED_STATUSES = frozenset(
    {"STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_ABANDONED", "STATUS_SUSPENDED"}
)


def due_kinds(match: Match, sent: frozenset[str], now: datetime) -> list[str]:
    """Повертає види сповіщень, які треба надіслати зараз."""
    if match.status in CANCELLED_STATUSES:
        # Про скасування пишемо лише якщо матч уже анонсували
        return [CANCELLED] if sent and CANCELLED not in sent else []

    if match.completed:
        is_fresh = now - match.kickoff <= RESULT_MAX_AGE
        return [RESULT] if RESULT not in sent and is_fresh else []

    if match.state != "pre" or not match.time_valid:
        return []

    until_kickoff = match.kickoff - now
    if LATE_REMINDER < until_kickoff <= EARLY_REMINDER:
        return [EARLY] if EARLY not in sent else []
    if -KICKOFF_GRACE < until_kickoff <= LATE_REMINDER:
        return [LATE] if LATE not in sent else []
    return []
