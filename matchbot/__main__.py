"""Один прохід бота: зібрати матчі, надіслати все, що пора, зберегти стан."""

import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .espn import CL_SLUG, EspnError, Fixture, Match, fetch_barca_fixtures, fetch_scoreboard
from .messages import format_message
from .rules import EARLY_REMINDER, due_kinds
from .state import awaiting_result, load_state, mark_sent, prune, save_state, sent_kinds
from .telegram import TelegramError, send_message

STATE_PATH = Path(os.environ.get("STATE_PATH", "state.json"))
# ESPN групує матчі за датою у Нью-Йорку
SCOREBOARD_ZONE = ZoneInfo("America/New_York")
FIXTURE_LOOKAHEAD = EARLY_REMINDER + timedelta(hours=1)
PAUSE_BETWEEN_MESSAGES_SECONDS = 1.1


logger = logging.getLogger("matchbot")


def log(text: str) -> None:
    logger.info(text)


def scoreboard_day(moment: datetime) -> str:
    return moment.astimezone(SCOREBOARD_ZONE).strftime("%Y%m%d")


def scoreboards_to_fetch(now: datetime, fixtures: list[Fixture], state: dict) -> set[tuple[str, str]]:
    """Пари (турнір, день), які треба опитати в цьому проході."""
    targets = {(CL_SLUG, scoreboard_day(now + timedelta(days=shift))) for shift in (-1, 0, 1)}
    targets |= {
        (fixture.slug, scoreboard_day(fixture.kickoff))
        for fixture in fixtures
        if timedelta(0) <= fixture.kickoff - now <= FIXTURE_LOOKAHEAD
    }
    targets |= {(slug, scoreboard_day(kickoff)) for slug, kickoff in awaiting_result(state)}
    return targets


def is_wanted(match: Match) -> bool:
    return match.slug == CL_SLUG or match.is_barca


def collect_matches(targets: set[tuple[str, str]]) -> tuple[list[Match], list[str]]:
    matches: dict[str, Match] = {}
    errors = []
    for slug, day in sorted(targets):
        try:
            found = fetch_scoreboard(slug, day)
        except EspnError as error:
            errors.append(str(error))
            continue
        matches.update({match.id: match for match in found if is_wanted(match)})
    return sorted(matches.values(), key=lambda match: match.kickoff), errors


def run(now: datetime, token: str, chat_id: str, dry_run: bool) -> list[str]:
    """Виконує прохід і повертає список помилок (порожній, якщо все гаразд)."""
    state = prune(load_state(STATE_PATH), now)
    errors = []
    try:
        fixtures = fetch_barca_fixtures()
    except EspnError as error:
        fixtures = []
        errors.append(str(error))

    matches, fetch_errors = collect_matches(scoreboards_to_fetch(now, fixtures, state))
    errors.extend(fetch_errors)

    for match in matches:
        for kind in due_kinds(match, sent_kinds(state, match.id), now):
            text = format_message(kind, match, now)
            if dry_run:
                log(f"--- {kind} ---\n{text}\n")
                continue
            try:
                send_message(token, chat_id, text)
            except TelegramError as error:
                errors.append(f"{match.home} — {match.away} ({kind}): {error}")
                continue
            state = mark_sent(state, match, kind)
            log(f"Надіслано {kind}: {match.home} — {match.away}")
            time.sleep(PAUSE_BETWEEN_MESSAGES_SECONDS)

    if not dry_run:
        save_state(STATE_PATH, state)
    return errors


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    dry_run = os.environ.get("DRY_RUN") == "1"
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not dry_run and not (token and chat_id):
        log("Потрібні змінні середовища TELEGRAM_BOT_TOKEN і TELEGRAM_CHAT_ID")
        return 2

    errors = run(datetime.now(timezone.utc), token, chat_id, dry_run)
    for error in errors:
        log(f"ПОМИЛКА: {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
