from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from matchbot import __main__ as bot
from matchbot.espn import CL_SLUG, Fixture, Match, parse_match
from matchbot.messages import format_message
from matchbot.rules import CANCELLED, EARLY, LATE, RESULT, due_kinds
from matchbot.state import awaiting_result, load_state, mark_sent, prune, save_state, sent_kinds

KICKOFF = datetime(2026, 11, 25, 17, 45, tzinfo=timezone.utc)
NOTHING_SENT = frozenset()


def make_match(**changes) -> Match:
    base = Match(
        id="401915378",
        slug=CL_SLUG,
        league="UEFA Champions League",
        kickoff=KICKOFF,
        time_valid=True,
        home="Sabah FK",
        away="Barcelona",
        home_id="1",
        away_id="83",
        home_score="0",
        away_score="0",
        home_shootout=None,
        away_shootout=None,
        status="STATUS_SCHEDULED",
        state="pre",
        completed=False,
        venue="Baku Olympic Stadium",
        scorers=(),
    )
    return replace(base, **changes)


def finished(**changes) -> Match:
    return make_match(status="STATUS_FULL_TIME", state="post", completed=True, **changes)


def before(**delta) -> datetime:
    return KICKOFF - timedelta(**delta)


def test_no_reminder_earlier_than_ten_hours_before_kickoff():
    assert due_kinds(make_match(), NOTHING_SENT, before(hours=10, minutes=1)) == []


@pytest.mark.parametrize("delta", [{"hours": 10}, {"hours": 5}, {"minutes": 31}])
def test_early_reminder_inside_ten_hour_window(delta):
    assert due_kinds(make_match(), NOTHING_SENT, before(**delta)) == [EARLY]


def test_early_reminder_is_sent_only_once():
    assert due_kinds(make_match(), frozenset({EARLY}), before(hours=5)) == []


@pytest.mark.parametrize("delta", [{"minutes": 30}, {"minutes": 10}, {"minutes": -4}])
def test_late_reminder_from_thirty_minutes_until_just_after_kickoff(delta):
    assert due_kinds(make_match(), frozenset({EARLY}), before(**delta)) == [LATE]


def test_late_reminder_skipped_when_bot_wakes_up_too_late():
    assert due_kinds(make_match(), NOTHING_SENT, before(minutes=-6)) == []


def test_no_reminder_when_kickoff_time_is_not_confirmed():
    assert due_kinds(make_match(time_valid=False), NOTHING_SENT, before(hours=5)) == []


def test_match_in_progress_produces_nothing():
    live = make_match(status="STATUS_FIRST_HALF", state="in")
    assert due_kinds(live, frozenset({EARLY, LATE}), before(minutes=-20)) == []


def test_result_sent_once_after_full_time():
    now = before(hours=-2)
    assert due_kinds(finished(), frozenset({EARLY, LATE}), now) == [RESULT]
    assert due_kinds(finished(), frozenset({EARLY, LATE, RESULT}), now) == []


def test_stale_result_is_not_sent():
    assert due_kinds(finished(), NOTHING_SENT, before(hours=-7)) == []


def test_cancellation_reported_only_for_announced_match():
    postponed = make_match(status="STATUS_POSTPONED", state="post")
    assert due_kinds(postponed, NOTHING_SENT, before(hours=1)) == []
    assert due_kinds(postponed, frozenset({EARLY}), before(hours=1)) == [CANCELLED]
    assert due_kinds(postponed, frozenset({EARLY, CANCELLED}), before(hours=1)) == []


def test_early_message_shows_kyiv_time_and_barca_marker():
    text = format_message(EARLY, make_match(), before(hours=10))
    assert "Сабах — Барселона" in text
    assert "Сьогодні о 19:45" in text
    assert "Барселона · Ліга чемпіонів" in text
    assert "Baku Olympic Stadium" in text


def test_early_message_says_tomorrow_for_next_day_kickoff():
    night_match = make_match(kickoff=datetime(2026, 11, 26, 1, 0, tzinfo=timezone.utc))
    text = format_message(EARLY, night_match, datetime(2026, 11, 25, 16, 0, tzinfo=timezone.utc))
    assert "Завтра о 03:00" in text


def test_late_message_shows_minutes_left():
    assert "через 27 хв, о 19:45" in format_message(LATE, make_match(), before(minutes=27))


def test_result_message_has_score_scorers_and_shootout():
    match = finished(
        home_score="1", away_score="1", home_shootout=3, away_shootout=4, scorers=("12' Yamal",)
    )
    text = format_message(RESULT, match, before(hours=-3))
    assert "Сабах 1:1 Барселона" in text
    assert "Серія пенальті: 3:4" in text
    assert "12' Yamal" in text


def test_message_escapes_html_in_team_names():
    text = format_message(CANCELLED, make_match(home="A<b>&B", home_id="2", away_id="3"), KICKOFF)
    assert "A&lt;b&gt;&amp;B" in text
    assert "🔵🔴" not in text


def espn_event() -> dict:
    return {
        "id": "401915383",
        "date": "2026-11-04T17:45Z",
        "competitions": [
            {
                "venue": {"fullName": "OPAP Arena"},
                "status": {"type": {"name": "STATUS_FULL_TIME", "state": "post", "completed": True}},
                "competitors": [
                    {"homeAway": "away", "score": "3", "team": {"id": "86", "displayName": "Real Madrid"}},
                    {"homeAway": "home", "score": "2", "team": {"id": "887", "displayName": "AEK Athens"}},
                ],
                "details": [
                    {
                        "scoringPlay": True,
                        "clock": {"displayValue": "12'"},
                        "athletesInvolved": [{"displayName": "Aboubakary Koita"}],
                    },
                    {"scoringPlay": False, "clock": {"displayValue": "34'"}},
                    {"scoringPlay": True, "ownGoal": True, "clock": {"displayValue": "50'"}},
                    {"scoringPlay": True, "shootout": True, "clock": {"displayValue": "120'"}},
                ],
            }
        ],
    }


def test_parse_match_reads_espn_event():
    match = parse_match(espn_event(), CL_SLUG, "UEFA Champions League")
    assert (match.home, match.home_score, match.away, match.away_score) == (
        "AEK Athens", "2", "Real Madrid", "3",
    )
    assert match.kickoff == datetime(2026, 11, 4, 17, 45, tzinfo=timezone.utc)
    assert match.completed and not match.is_barca
    assert match.scorers == ("12' Aboubakary Koita", "50' (автогол)")


def test_parse_match_rejects_unknown_shape():
    from matchbot.espn import EspnError

    with pytest.raises(EspnError):
        parse_match({"id": "1", "date": "2026-11-04T17:45Z", "competitions": []}, CL_SLUG, "x")


def test_mark_sent_returns_new_state_without_touching_old():
    old = {}
    new = mark_sent(mark_sent(old, make_match(), EARLY), make_match(), LATE)
    assert old == {}
    assert sent_kinds(new, "401915378") == {EARLY, LATE}


def test_awaiting_result_lists_only_unfinished_matches():
    state = mark_sent({}, make_match(), EARLY)
    state = mark_sent(state, make_match(id="2", slug="esp.1"), RESULT)
    assert awaiting_result(state) == [(CL_SLUG, KICKOFF)]


def test_prune_drops_matches_older_than_a_week():
    state = mark_sent({}, make_match(), RESULT)
    assert prune(state, KICKOFF + timedelta(days=6)) == state
    assert prune(state, KICKOFF + timedelta(days=8)) == {}


def test_state_survives_save_and_load(tmp_path):
    path = tmp_path / "state.json"
    assert load_state(path) == {}
    state = mark_sent({}, make_match(), EARLY)
    save_state(path, state)
    assert load_state(path) == state


def test_scoreboards_cover_champions_league_barca_fixtures_and_pending_results():
    now = before(hours=9)
    fixtures = [
        Fixture("1", "esp.1", now + timedelta(hours=8)),
        Fixture("2", "esp.copa_del_rey", now + timedelta(days=5)),
    ]
    state = mark_sent({}, make_match(id="3", slug="esp.super_cup", kickoff=now - timedelta(hours=2)), LATE)
    targets = bot.scoreboards_to_fetch(now, fixtures, state)
    assert {(CL_SLUG, "20261124"), (CL_SLUG, "20261125"), (CL_SLUG, "20261126")} <= targets
    assert ("esp.1", "20261125") in targets
    assert ("esp.super_cup", "20261125") in targets
    assert not any(slug == "esp.copa_del_rey" for slug, _ in targets)


def run_with_fakes(monkeypatch, tmp_path, matches, now, fail_send=False):
    sent = []

    def fake_send(token, chat_id, text):
        if fail_send:
            raise bot.TelegramError("403: bot is not a member")
        sent.append(text)

    monkeypatch.setattr(bot, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(bot, "fetch_barca_fixtures", lambda: [])
    monkeypatch.setattr(bot, "fetch_scoreboard", lambda slug, day: matches if slug == CL_SLUG else [])
    monkeypatch.setattr(bot, "send_message", fake_send)
    monkeypatch.setattr(bot, "PAUSE_BETWEEN_MESSAGES_SECONDS", 0)
    errors = bot.run(now, "token", "chat", dry_run=False)
    return sent, errors


def test_run_sends_each_notification_once_across_runs(monkeypatch, tmp_path):
    first, errors = run_with_fakes(monkeypatch, tmp_path, [make_match()], before(hours=9))
    second, _ = run_with_fakes(monkeypatch, tmp_path, [make_match()], before(hours=8))
    third, _ = run_with_fakes(monkeypatch, tmp_path, [make_match()], before(minutes=25))
    fourth, _ = run_with_fakes(monkeypatch, tmp_path, [finished(away_score="2")], before(hours=-2))
    assert errors == []
    assert (len(first), len(second), len(third), len(fourth)) == (1, 0, 1, 1)
    assert "0:2" in fourth[0]


def test_run_retries_next_time_when_telegram_fails(monkeypatch, tmp_path):
    sent, errors = run_with_fakes(monkeypatch, tmp_path, [make_match()], before(hours=9), fail_send=True)
    assert sent == [] and len(errors) == 1
    retried, _ = run_with_fakes(monkeypatch, tmp_path, [make_match()], before(hours=9))
    assert len(retried) == 1


def test_run_ignores_other_clubs_outside_champions_league(monkeypatch, tmp_path):
    other = make_match(slug="esp.1", home_id="5", away_id="6")
    monkeypatch.setattr(bot, "is_wanted", bot.is_wanted)
    assert not bot.is_wanted(other)
    assert bot.is_wanted(make_match(slug="esp.1"))


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self.body


def http_error(code: int, body: dict):
    import io
    import json
    import urllib.error

    payload = io.BytesIO(json.dumps(body).encode("utf-8"))
    return urllib.error.HTTPError("https://example.invalid", code, "error", {}, payload)


def test_fetch_json_unpacks_gzip_and_retries_after_failure(monkeypatch):
    import gzip
    import urllib.error

    from matchbot import espn

    responses = [urllib.error.URLError("down"), FakeResponse(gzip.compress(b'{"events": []}'))]

    def fake_urlopen(request, timeout):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(espn.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(espn, "RETRY_PAUSE_SECONDS", 0)
    assert espn.fetch_json("https://example.invalid") == {"events": []}


def test_fetch_json_gives_up_with_clear_error(monkeypatch):
    import urllib.error

    from matchbot import espn

    def always_down(request, timeout):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(espn.urllib.request, "urlopen", always_down)
    monkeypatch.setattr(espn, "RETRY_PAUSE_SECONDS", 0)
    with pytest.raises(espn.EspnError):
        espn.fetch_json("https://example.invalid")


def test_fetch_barca_fixtures_skips_matches_without_confirmed_time(monkeypatch):
    from matchbot import espn

    data = {
        "events": [
            {"id": "1", "date": "2026-11-22T13:00Z", "timeValid": True, "league": {"slug": "esp.1"}},
            {"id": "2", "date": "2026-12-20T00:00Z", "timeValid": False, "league": {"slug": "esp.1"}},
        ]
    }
    monkeypatch.setattr(espn, "fetch_json", lambda url: data)
    assert [fixture.id for fixture in espn.fetch_barca_fixtures()] == ["1"]


def test_fetch_scoreboard_labels_matches_with_league_name(monkeypatch):
    from matchbot import espn

    data = {"leagues": [{"name": "UEFA Champions League"}], "events": [espn_event()]}
    monkeypatch.setattr(espn, "fetch_json", lambda url: data)
    [match] = espn.fetch_scoreboard(CL_SLUG, "20261104")
    assert match.league == "UEFA Champions League"


def test_send_message_waits_and_retries_when_telegram_rate_limits(monkeypatch):
    from matchbot import telegram

    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        if len(calls) == 1:
            raise http_error(429, {"description": "Too Many Requests", "parameters": {"retry_after": 0}})
        return FakeResponse(b"{}")

    monkeypatch.setattr(telegram.urllib.request, "urlopen", fake_urlopen)
    telegram.send_message("token", "chat", "text")
    assert len(calls) == 2


def test_send_message_error_has_description_but_not_token(monkeypatch):
    from matchbot import telegram

    def fake_urlopen(request, timeout):
        raise http_error(403, {"description": "Forbidden: bot is not a member of the channel chat"})

    monkeypatch.setattr(telegram.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(telegram.TelegramError) as caught:
        telegram.send_message("SECRET-TOKEN", "chat", "text")
    assert "bot is not a member" in str(caught.value)
    assert "SECRET-TOKEN" not in str(caught.value)


def test_main_refuses_to_run_without_secrets(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("DRY_RUN", raising=False)
    assert bot.main() == 2


def test_unknown_team_keeps_its_original_name():
    text = format_message(EARLY, make_match(home="Unionistas de Salamanca"), before(hours=5))
    assert "Unionistas de Salamanca — Барселона" in text
