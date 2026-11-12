"""Пам'ять бота між запусками: які сповіщення вже надіслано."""

import json
from datetime import datetime, timedelta
from pathlib import Path

from .espn import Match, parse_time
from .rules import CANCELLED, RESULT

KEEP_FOR = timedelta(days=7)
FINAL_KINDS = frozenset({RESULT, CANCELLED})


class StateError(Exception):
    """Файл стану пошкоджено."""


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise StateError(f"Не вдалося прочитати {path}: {error}")
    if not isinstance(state, dict):
        raise StateError(f"{path} має бути JSON-об'єктом")
    return state


def save_state(path: Path, state: dict) -> None:
    text = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)
    path.write_text(text + "\n", encoding="utf-8")


def sent_kinds(state: dict, match_id: str) -> frozenset[str]:
    return frozenset(state.get(match_id, {}).get("sent", []))


def mark_sent(state: dict, match: Match, kind: str) -> dict:
    """Новий стан із позначкою, що сповіщення kind для матчу надіслано."""
    entry = {
        "slug": match.slug,
        "kickoff": match.kickoff.isoformat(),
        "sent": sorted(sent_kinds(state, match.id) | {kind}),
    }
    return {**state, match.id: entry}


def prune(state: dict, now: datetime) -> dict:
    return {
        match_id: entry
        for match_id, entry in state.items()
        if now - parse_time(entry["kickoff"]) <= KEEP_FOR
    }


def awaiting_result(state: dict) -> list[tuple[str, datetime]]:
    """Турнір і час початку матчів, які анонсовано, але результат ще не надіслано."""
    return [
        (entry["slug"], parse_time(entry["kickoff"]))
        for entry in state.values()
        if not FINAL_KINDS & set(entry["sent"])
    ]
