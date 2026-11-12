"""Тексти сповіщень. Щоб змінити вигляд повідомлень, достатньо правити цей файл."""

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from .espn import Match
from .rules import CANCELLED, EARLY, LATE, RESULT
from .team_names import team_name

LOCAL_ZONE = ZoneInfo("Europe/Kyiv")

LEAGUE_NAMES = {
    "uefa.champions": "Ліга чемпіонів",
    "esp.1": "Ла Ліга",
    "esp.copa_del_rey": "Кубок Іспанії",
    "esp.super_cup": "Суперкубок Іспанії",
    "club.friendly": "Товариський матч",
    "fifa.cwc": "Клубний чемпіонат світу",
}


def _league(match: Match) -> str:
    name = LEAGUE_NAMES.get(match.slug, match.league)
    marker = "🔵🔴 Барселона · " if match.is_barca else ""
    return f"🏆 {marker}{escape(name)}"


def _name(espn_name: str) -> str:
    return escape(team_name(espn_name))


def _teams(match: Match) -> str:
    return f"{_name(match.home)} — {_name(match.away)}"


def _day_word(kickoff: datetime, now: datetime) -> str:
    days = (kickoff.astimezone(LOCAL_ZONE).date() - now.astimezone(LOCAL_ZONE).date()).days
    if days == 0:
        return "Сьогодні"
    if days == 1:
        return "Завтра"
    return kickoff.astimezone(LOCAL_ZONE).strftime("%d.%m")


def _clock(kickoff: datetime) -> str:
    return kickoff.astimezone(LOCAL_ZONE).strftime("%H:%M")


def _early(match: Match, now: datetime) -> str:
    lines = [
        f"📅 <b>{_teams(match)}</b>",
        _league(match),
        f"🕙 {_day_word(match.kickoff, now)} о {_clock(match.kickoff)} за Києвом",
    ]
    if match.venue:
        lines.append(f"🏟 {escape(match.venue)}")
    return "\n".join(lines)


def _late(match: Match, now: datetime) -> str:
    minutes = max(0, round((match.kickoff - now).total_seconds() / 60))
    when = f"Початок через {minutes} хв, о {_clock(match.kickoff)}" if minutes else "Матч починається"
    return "\n".join([f"⏰ <b>{_teams(match)}</b>", _league(match), when])


def _result(match: Match, now: datetime) -> str:
    score = f"{_name(match.home)} {match.home_score}:{match.away_score} {_name(match.away)}"
    lines = [f"🏁 <b>{score}</b>", _league(match)]
    if match.home_shootout is not None and match.away_shootout is not None:
        lines.append(f"Серія пенальті: {match.home_shootout}:{match.away_shootout}")
    if match.scorers:
        lines.append("⚽ " + escape(", ".join(match.scorers), quote=False))
    return "\n".join(lines)


def _cancelled(match: Match, now: datetime) -> str:
    return "\n".join([f"⚠️ <b>{_teams(match)}</b>", _league(match), "Матч перенесено або скасовано"])


_FORMATTERS = {EARLY: _early, LATE: _late, RESULT: _result, CANCELLED: _cancelled}


def format_message(kind: str, match: Match, now: datetime) -> str:
    """Текст сповіщення у HTML-розмітці Telegram."""
    return _FORMATTERS[kind](match, now)
