from datetime import date, datetime, timezone

import icalendar
import pytest

from napari_dashboard import meeting_reminder
from napari_dashboard.meeting_reminder import (
    Meeting,
    format_meeting_message,
    format_no_meetings,
    get_meetings,
    get_window,
    meeting_topic,
)

ICS = r"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:community@test
SUMMARY:napari community meeting (Eurasia)
DTSTART;TZID=Europe/Paris:20261104T090000
DTEND;TZID=Europe/Paris:20261104T100000
RRULE:FREQ=WEEKLY;BYDAY=WE
EXDATE;TZID=Europe/Paris:20261118T090000
LOCATION:https://numfocus-org.zoom.us/j/111?pwd=abc
DESCRIPTION:Agenda: https://hackmd.io/@napari/community-eurasia/edit
END:VEVENT
BEGIN:VEVENT
UID:community@test
RECURRENCE-ID;TZID=Europe/Paris:20261125T090000
SUMMARY:napari community meeting (Eurasia)
DTSTART;TZID=Europe/Paris:20261125T110000
DTEND;TZID=Europe/Paris:20261125T120000
LOCATION:https://numfocus-org.zoom.us/j/111?pwd=abc
DESCRIPTION:Agenda: https://hackmd.io/@napari/community-eurasia/edit
END:VEVENT
BEGIN:VEVENT
UID:plugins@test
SUMMARY:plugin working group
DTSTART;TZID=America/Los_Angeles:20261105T083000
DTEND;TZID=America/Los_Angeles:20261105T093000
RRULE:FREQ=WEEKLY;BYDAY=TH
LOCATION:https://numfocus-org.zoom.us/j/222
END:VEVENT
BEGIN:VEVENT
UID:plugins@test
RECURRENCE-ID;TZID=America/Los_Angeles:20261119T083000
SUMMARY:plugin working group
STATUS:CANCELLED
DTSTART;TZID=America/Los_Angeles:20261119T083000
DTEND;TZID=America/Los_Angeles:20261119T093000
END:VEVENT
BEGIN:VEVENT
UID:cafe@test
SUMMARY:Tim: napari Code Cafe
DTSTART:20261117T170000Z
DTEND:20261117T180000Z
DESCRIPTION:Join <a href="https://www.google.com/url?q=https://numfocus-org
 .zoom.us/j/333&amp;sa=D&amp;source=calendar">Zoom</a>\, notes <a href="htt
 ps://www.google.com/url?q=https://hackmd.io/@napari/cafe/edit&amp;sa=D">he
 re</a>.
END:VEVENT
BEGIN:VEVENT
UID:cancelled-title@test
SUMMARY:CANCELED: Documentation working group
DTSTART:20261119T210000Z
DTEND:20261119T220000Z
END:VEVENT
BEGIN:VEVENT
UID:core@test
SUMMARY:napari Core Team Meeting
DTSTART:20261116T210000Z
DTEND:20261116T220000Z
END:VEVENT
BEGIN:VEVENT
UID:release@test
SUMMARY:v0.7.0
DTSTART;VALUE=DATE:20261118
DTEND;VALUE=DATE:20261119
END:VEVENT
END:VCALENDAR
"""


@pytest.fixture
def calendar():
    return icalendar.Calendar.from_ical(ICS)


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("kind", "today", "expected"),
    [
        # Friday: Saturday, Sunday and Monday
        ("friday", date(2026, 11, 13), (utc(2026, 11, 14), utc(2026, 11, 17))),
        # Monday: Tuesday to Friday
        ("monday", date(2026, 11, 16), (utc(2026, 11, 17), utc(2026, 11, 21))),
        # next week: whole Monday-Sunday week after today
        (
            "next-week",
            date(2026, 11, 13),
            (utc(2026, 11, 16), utc(2026, 11, 23)),
        ),
        (
            "next-week",
            date(2026, 11, 16),
            (utc(2026, 11, 23), utc(2026, 11, 30)),
        ),
        (
            "next-week",
            date(2026, 11, 15),
            (utc(2026, 11, 16), utc(2026, 11, 23)),
        ),
    ],
)
def test_get_window(kind, today, expected):
    assert get_window(kind, today) == expected


def test_scheduled_windows_are_contiguous():
    friday = get_window("friday", date(2026, 11, 13))
    monday = get_window("monday", date(2026, 11, 16))
    next_friday = get_window("friday", date(2026, 11, 20))
    assert friday[1] == monday[0]
    assert monday[1] == next_friday[0]


def test_get_window_unknown():
    with pytest.raises(ValueError, match="Unknown window"):
        get_window("sunday", date(2026, 11, 13))


def test_get_meetings(calendar):
    meetings = get_meetings(calendar, utc(2026, 11, 16), utc(2026, 11, 30))
    # Not listed:
    # - 2026-11-16 core team meeting (excluded title)
    # - 2026-11-18 Eurasia meeting (EXDATE) and v0.7.0 (all-day)
    # - 2026-11-19 plugin working group (STATUS:CANCELLED instance)
    # - 2026-11-19 documentation working group ("CANCELED:" title)
    assert [(m.title, m.start) for m in meetings] == [
        ("Tim: napari Code Cafe", utc(2026, 11, 17, 17)),
        # moved from 9:00 to 11:00 Paris time
        ("napari community meeting (Eurasia)", utc(2026, 11, 25, 10)),
        ("plugin working group", utc(2026, 11, 26, 16, 30)),
    ]


def test_links(calendar):
    meetings = get_meetings(calendar, utc(2026, 11, 9), utc(2026, 11, 18))
    by_title = {m.title: m for m in meetings}

    eurasia = by_title["napari community meeting (Eurasia)"]
    assert eurasia.zoom == "https://numfocus-org.zoom.us/j/111?pwd=abc"
    assert eurasia.agenda == "https://hackmd.io/@napari/community-eurasia/edit"

    plugins = by_title["plugin working group"]
    assert plugins.zoom == "https://numfocus-org.zoom.us/j/222"
    assert plugins.agenda is None

    # links only in an HTML description, wrapped in Google redirects
    cafe = by_title["Tim: napari Code Cafe"]
    assert cafe.zoom == "https://numfocus-org.zoom.us/j/333"
    assert cafe.agenda == "https://hackmd.io/@napari/cafe/edit"


def meeting(start, zoom=None, agenda=None, title="community meeting"):
    return Meeting(title=title, start=start, zoom=zoom, agenda=agenda)


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        # Pacific: Thursday evening in America, Friday in Australia
        (utc(2026, 11, 13, 2), "2026-11-12/13"),
        # Documentation: Thursday afternoon in America, Friday morning
        # in Australia
        (utc(2026, 11, 19, 21), "2026-11-19/20"),
        # Atlantic: Thursday 3:30 in Australia is not counted
        (utc(2026, 11, 18, 16, 30), "2026-11-18"),
        # Eurasia: midnight in America is not counted
        (utc(2026, 11, 11, 8), "2026-11-11"),
        # only Europe is awake
        (utc(2026, 11, 11, 13, 30), "2026-11-11"),
        # crossing the end of month
        (utc(2026, 12, 1, 2), "2026-11-30/01"),
    ],
)
def test_meeting_topic_dates(start, expected):
    assert meeting_topic(meeting(start)) == f"{expected} community meeting"


def test_meeting_topic_length():
    topic = meeting_topic(meeting(utc(2026, 11, 18, 16), title="x" * 100))
    assert len(topic) == 60


def test_format_meeting_message():
    message = format_meeting_message(
        meeting(
            utc(2026, 11, 18, 16, 30),
            zoom="https://zoom.us/j/1",
            agenda="https://hackmd.io/a",
        )
    )
    assert message == (
        "Howdy napari folks! The community meeting is this "
        "<time:2026-11-18T16:30:00+00:00>\n"
        "\n"
        "Please feel free to update the [agenda](https://hackmd.io/a) with "
        "your topics of discussion and come join us on "
        "[Zoom](https://zoom.us/j/1)! :napari:\n"
        "\n"
        "Planning to join? React with :+1: to this message "
        "so we know who to expect.\n"
        "\n"
        "Zoom: https://zoom.us/j/1\n"
        "Agenda: https://hackmd.io/a"
    )


def test_format_meeting_message_missing_links():
    start = utc(2026, 11, 18, 16, 30)
    only_zoom = format_meeting_message(meeting(start, zoom="https://z"))
    assert "Come join us on [Zoom](https://z)! :napari:" in only_zoom
    assert "agenda" not in only_zoom.lower()

    only_agenda = format_meeting_message(meeting(start, agenda="https://a"))
    assert "update the [agenda](https://a)" in only_agenda
    assert "zoom" not in only_agenda.lower()

    no_links = format_meeting_message(meeting(start))
    assert (
        "See the [napari calendar]"
        "(https://napari.org/stable/community/meeting_schedule.html) "
        "for details. :napari:"
    ) in no_links
    assert no_links.endswith(
        "React with :+1: to this message so we know who to expect."
    )


def test_format_no_meetings():
    message = format_no_meetings(utc(2026, 11, 14), utc(2026, 11, 17))
    assert message == (
        "No napari meetings are scheduled from Saturday, November 14 "
        "to Monday, November 16 (UTC dates)."
    )


class FakeZulipClient:
    def __init__(self, reaction_result="success"):
        self.messages = []
        self.reactions = []
        self.reaction_result = reaction_result

    def send_message(self, request):
        self.messages.append(request)
        return {"result": "success", "id": len(self.messages)}

    def add_reaction(self, request):
        self.reactions.append(request)
        return {"result": self.reaction_result}


@pytest.fixture
def run_main(monkeypatch, calendar):
    def run(*args, client=None):
        client = client or FakeZulipClient()
        monkeypatch.setattr(
            meeting_reminder, "fetch_calendar", lambda: calendar
        )
        monkeypatch.setattr(
            meeting_reminder, "get_zulip_client", lambda: client
        )
        monkeypatch.setattr("sys.argv", ["meeting_reminder", *args])
        meeting_reminder.main()
        return client

    return run


def test_main_topic_per_meeting(run_main):
    client = run_main(
        "--window",
        "monday",
        "--today",
        "2026-11-16",
        "--send-zulip",
        "--channel",
        "215290",
    )
    assert [(m["to"], m["topic"]) for m in client.messages] == [
        (215290, "2026-11-17 Tim: napari Code Cafe")
    ]
    assert client.reactions == [{"message_id": 1, "emoji_name": "+1"}]


def test_main_single_topic(run_main):
    client = run_main(
        "--window",
        "next-week",
        "--today",
        "2026-11-20",
        "--send-zulip",
        "--topic",
        "Meeting reminder",
    )
    assert [m["topic"] for m in client.messages] == ["Meeting reminder"] * 2
    assert [m["to"] for m in client.messages] == ["metrics and analytics"] * 2
    assert client.messages[0]["content"].startswith(
        "**Topic:** `2026-11-25 napari community meeting (Eurasia)`\n\n"
        "Howdy napari folks!"
    )
    assert [r["message_id"] for r in client.reactions] == [1, 2]


def test_main_no_meetings(run_main):
    # nothing is posted to the community channel
    client = run_main(
        "--window",
        "friday",
        "--today",
        "2026-11-13",
        "--send-zulip",
        "--channel",
        "215290",
    )
    assert client.messages == []

    # the test topic gets a note, without a reaction
    client = run_main(
        "--window",
        "friday",
        "--today",
        "2026-11-13",
        "--send-zulip",
        "--topic",
        "Meeting reminder",
    )
    assert [m["content"] for m in client.messages] == [
        (
            "No napari meetings are scheduled from Saturday, November 14 "
            "to Monday, November 16 (UTC dates)."
        )
    ]
    assert client.reactions == []


def test_main_dry_run_does_not_connect(run_main, monkeypatch):
    def fail():
        raise AssertionError("Zulip client created in a dry run")

    monkeypatch.setattr(meeting_reminder, "get_zulip_client", fail)
    monkeypatch.setattr(meeting_reminder, "fetch_calendar", lambda: None)
    monkeypatch.setattr(meeting_reminder, "get_meetings", lambda *args: [])
    monkeypatch.setattr("sys.argv", ["meeting_reminder"])
    meeting_reminder.main()


def test_main_failed_reaction_still_posts_everything(run_main):
    client = FakeZulipClient(reaction_result="error")
    with pytest.raises(SystemExit) as exc_info:
        run_main(
            "--window",
            "next-week",
            "--today",
            "2026-11-20",
            "--send-zulip",
            "--channel",
            "215290",
            client=client,
        )
    assert exc_info.value.code == 1
    assert len(client.messages) == 2
    assert len(client.reactions) == 2
