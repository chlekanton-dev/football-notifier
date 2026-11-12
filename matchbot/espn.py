"""Розклад і результати матчів з відкритого API ESPN (ключ не потрібен)."""

import gzip
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer"
CL_SLUG = "uefa.champions"
BARCA_TEAM_ID = "83"

REQUEST_TIMEOUT_SECONDS = 20
REQUEST_ATTEMPTS = 3
RETRY_PAUSE_SECONDS = 2
GZIP_MAGIC = b"\x1f\x8b"


class EspnError(Exception):
    """Не вдалося отримати або розібрати дані ESPN."""


@dataclass(frozen=True)
class Match:
    id: str
    slug: str
    league: str
    kickoff: datetime
    time_valid: bool
    home: str
    away: str
    home_id: str
    away_id: str
    home_score: str
    away_score: str
    home_shootout: int | None
    away_shootout: int | None
    status: str
    state: str
    completed: bool
    venue: str
    scorers: tuple[str, ...]

    @property
    def is_barca(self) -> bool:
        return BARCA_TEAM_ID in (self.home_id, self.away_id)


@dataclass(frozen=True)
class Fixture:
    """Майбутній матч Барселони: достатньо, щоб знати, який турнір опитувати."""

    id: str
    slug: str
    kickoff: datetime


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def fetch_json(url: str) -> dict:
    last_error: Exception | None = None
    for attempt in range(REQUEST_ATTEMPTS):
        try:
            # Власний User-Agent не ставимо: ESPN відповідає 403 на все, що містить "bot"
            with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                body = response.read()
            # ESPN віддає gzip, навіть якщо його не просили
            if body.startswith(GZIP_MAGIC):
                body = gzip.decompress(body)
            return json.loads(body.decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
            last_error = error
            if attempt < REQUEST_ATTEMPTS - 1:
                time.sleep(RETRY_PAUSE_SECONDS)
    raise EspnError(f"ESPN не відповів на {url}: {last_error}")


def _scorers(competition: dict) -> tuple[str, ...]:
    goals = []
    for detail in competition.get("details", []):
        if not detail.get("scoringPlay") or detail.get("shootout"):
            continue
        minute = detail.get("clock", {}).get("displayValue", "")
        players = detail.get("athletesInvolved", [])
        name = players[0].get("displayName", "") if players else ""
        note = "(автогол)" if detail.get("ownGoal") else ""
        goals.append(" ".join(part for part in (minute, name, note) if part))
    return tuple(goals)


def _side(competition: dict, home_away: str) -> dict:
    for competitor in competition.get("competitors", []):
        if competitor.get("homeAway") == home_away:
            return competitor
    raise EspnError(f"У матчі немає сторони {home_away}")


def parse_match(event: dict, slug: str, league: str) -> Match:
    try:
        competition = event["competitions"][0]
        home = _side(competition, "home")
        away = _side(competition, "away")
        status = competition["status"]["type"]
        return Match(
            id=str(event["id"]),
            slug=slug,
            league=league,
            kickoff=parse_time(event["date"]),
            time_valid=competition.get("timeValid", True),
            home=home["team"]["displayName"],
            away=away["team"]["displayName"],
            home_id=str(home["team"].get("id", "")),
            away_id=str(away["team"].get("id", "")),
            home_score=str(home.get("score", "")),
            away_score=str(away.get("score", "")),
            home_shootout=home.get("shootoutScore"),
            away_shootout=away.get("shootoutScore"),
            status=status.get("name", ""),
            state=status.get("state", ""),
            completed=bool(status.get("completed")),
            venue=competition.get("venue", {}).get("fullName", ""),
            scorers=_scorers(competition),
        )
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise EspnError(f"Незрозумілий формат матчу {event.get('id')}: {error!r}")


def fetch_scoreboard(slug: str, day: str) -> list[Match]:
    """Усі матчі турніру за день; day у форматі YYYYMMDD (за часом Нью-Йорка)."""
    data = fetch_json(f"{BASE_URL}/{slug}/scoreboard?dates={day}")
    leagues = data.get("leagues") or [{}]
    league = leagues[0].get("name", slug)
    return [parse_match(event, slug, league) for event in data.get("events", [])]


def fetch_barca_fixtures() -> list[Fixture]:
    """Майбутні матчі Барселони в усіх турнірах."""
    data = fetch_json(f"{BASE_URL}/all/teams/{BARCA_TEAM_ID}/schedule?fixture=true")
    fixtures = []
    for event in data.get("events", []):
        slug = event.get("league", {}).get("slug")
        if not slug or not event.get("timeValid", True):
            continue
        fixtures.append(Fixture(str(event["id"]), slug, parse_time(event["date"])))
    return fixtures
