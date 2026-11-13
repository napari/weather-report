"""
Post upcoming napari meetings from the public Google Calendar to Zulip.

Events are read from the public iCal feed of the napari calendar, so no
API key is needed. Recurring events are expanded locally with
``recurring-ical-events``.

The schedule is split so every meeting is announced a few days ahead:

* ``friday`` -- posted on Friday, covers Saturday, Sunday and Monday
  (so Monday meetings are announced before the weekend),
* ``monday`` -- posted on Monday, covers Tuesday to Friday,
* ``next-week`` -- the whole next week (Monday to Sunday), used to check
  that the bot works after a merge to ``main``.

All window boundaries are midnight UTC.

Every meeting gets its own message in its own topic named like
``2026-11-12/13 napari community meeting (Pacific)``, following the
convention used in the ``community-meeting`` channel. With ``--topic``
all messages go to that single topic instead (used for testing).
"""

import argparse
import html
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import quote, unquote
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events
import requests

logger = logging.getLogger(__name__)

CALENDAR_ID = "c_35r93ec6vtp8smhm7dv5uot0v4@group.calendar.google.com"
ICAL_URL = (
    "https://calendar.google.com/calendar/ical/"
    f"{quote(CALENDAR_ID)}/public/basic.ics"
)

# Meetings with these words in the title are not announced publicly.
EXCLUDED_TITLE_PATTERNS = ("core team", "steering council")

# Used to name topics with every date on which the meeting happens during
# waking hours somewhere in the community, e.g. "2026-11-12/13".
COMMUNITY_TIMEZONES = (
    ZoneInfo("America/Los_Angeles"),
    ZoneInfo("Europe/London"),
    ZoneInfo("Australia/Sydney"),
)
WAKING_HOURS = range(7, 23)
ZULIP_MAX_TOPIC_LENGTH = 60

# People react with this emoji to say they plan to join; the bot adds the
# first reaction itself so joining is a single click.
RSVP_EMOJI = "+1"

_CANCELLED_TITLE = re.compile(r"^\s*cancell?ed\b", re.IGNORECASE)
_URL_END = r"[^\s<>\"'()\[\]\\]*"
_ZOOM_URL = re.compile(rf"https://[\w.-]*zoom\.us/{_URL_END}")
_HACKMD_URL = re.compile(rf"https://hackmd\.io/{_URL_END}")
_GOOGLE_REDIRECT = re.compile(
    r"https://www\.google\.com/url\?q=([^&\s<>\"']+)[^\s<>\"']*"
)

WINDOWS = ("friday", "monday", "next-week")


@dataclass(frozen=True)
class Meeting:
    title: str
    start: datetime
    zoom: str | None
    agenda: str | None


def get_window(kind: str, today: date) -> tuple[datetime, datetime]:
    """Return the ``[start, end)`` UTC window of meetings to announce."""
    this_monday = today - timedelta(days=today.weekday())
    next_monday = this_monday + timedelta(days=7)
    if kind == "friday":
        start = next_monday - timedelta(days=2)
        end = next_monday + timedelta(days=1)
    elif kind == "monday":
        start = this_monday + timedelta(days=1)
        end = this_monday + timedelta(days=5)
    elif kind == "next-week":
        start, end = next_monday, next_monday + timedelta(days=7)
    else:
        raise ValueError(f"Unknown window {kind!r}, expected one of {WINDOWS}")
    return (
        datetime.combine(start, time(), tzinfo=timezone.utc),
        datetime.combine(end, time(), tzinfo=timezone.utc),
    )


def fetch_calendar(url: str = ICAL_URL) -> icalendar.Calendar:
    logger.info("Fetching calendar %s", url)
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return icalendar.Calendar.from_ical(response.content)


def _unwrap_google_redirects(text: str) -> str:
    """Replace ``https://www.google.com/url?q=<url>&...`` with ``<url>``."""
    return _GOOGLE_REDIRECT.sub(lambda m: unquote(m.group(1)), text)


def _find_url(pattern: re.Pattern, *texts: str) -> str | None:
    for text in texts:
        text = _unwrap_google_redirects(html.unescape(text))
        if match := pattern.search(text):
            return match.group(0).rstrip(".,;:")
    return None


def _is_announced(event: icalendar.Event) -> bool:
    title = str(event.get("SUMMARY", "")).strip()
    if str(event.get("STATUS", "")).upper() == "CANCELLED":
        return False
    if _CANCELLED_TITLE.match(title):
        return False
    lower_title = title.lower()
    return not any(word in lower_title for word in EXCLUDED_TITLE_PATTERNS)


def get_meetings(
    calendar: icalendar.Calendar, start: datetime, end: datetime
) -> list[Meeting]:
    """Expand recurring events and return meetings starting in the window."""
    meetings = []
    for event in recurring_ical_events.of(calendar).between(start, end):
        event_start = event.start
        if not isinstance(event_start, datetime):
            # all-day entries (e.g. release dates) are not meetings
            continue
        if not _is_announced(event):
            continue
        location = str(event.get("LOCATION", ""))
        description = str(event.get("DESCRIPTION", ""))
        meetings.append(
            Meeting(
                title=str(event.get("SUMMARY", "Meeting")).strip(),
                start=event_start.astimezone(timezone.utc),
                zoom=_find_url(_ZOOM_URL, location, description),
                agenda=_find_url(_HACKMD_URL, description, location),
            )
        )
    return sorted(meetings, key=lambda m: (m.start, m.title))


CALENDAR_PAGE = "https://napari.org/stable/community/meeting_schedule.html"


def _format_day(day: datetime) -> str:
    return f"{day:%A}, {day:%B} {day.day}"


def meeting_topic(meeting: Meeting) -> str:
    """
    Topic name like ``2026-11-12/13 napari community meeting (Pacific)``.

    It lists every date on which the meeting is during waking hours in
    one of ``COMMUNITY_TIMEZONES``, so people can find it by their date.
    """
    dates = sorted(
        {
            local.date()
            for tz in COMMUNITY_TIMEZONES
            if (local := meeting.start.astimezone(tz)).hour in WAKING_HOURS
        }
    ) or [meeting.start.astimezone(timezone.utc).date()]
    date_str = dates[0].isoformat() + "".join(
        f"/{day.day:02d}" for day in dates[1:]
    )
    return f"{date_str} {meeting.title}"[:ZULIP_MAX_TOPIC_LENGTH]


def format_meeting_message(meeting: Meeting) -> str:
    time_tag = f"<time:{meeting.start.isoformat()}>"
    lines = [f"Howdy napari folks! The {meeting.title} is this {time_tag}", ""]
    if meeting.agenda and meeting.zoom:
        lines.append(
            f"Please feel free to update the [agenda]({meeting.agenda}) with "
            "your topics of discussion and come join us on "
            f"[Zoom]({meeting.zoom})! :napari:"
        )
    elif meeting.zoom:
        lines.append(f"Come join us on [Zoom]({meeting.zoom})! :napari:")
    elif meeting.agenda:
        lines.append(
            f"Please feel free to update the [agenda]({meeting.agenda}) with "
            "your topics of discussion! :napari:"
        )
    else:
        lines.append(
            f"See the [napari calendar]({CALENDAR_PAGE}) for details. :napari:"
        )
    lines += [
        "",
        (
            f"Planning to join? React with :{RSVP_EMOJI}: to this message "
            "so we know who to expect."
        ),
    ]
    if meeting.zoom or meeting.agenda:
        lines.append("")
    if meeting.zoom:
        lines.append(f"Zoom: {meeting.zoom}")
    if meeting.agenda:
        lines.append(f"Agenda: {meeting.agenda}")
    return "\n".join(lines)


def format_no_meetings(start: datetime, end: datetime) -> str:
    last_day = end - timedelta(days=1)
    return (
        f"No napari meetings are scheduled from {_format_day(start)} "
        f"to {_format_day(last_day)} (UTC dates)."
    )


def get_zulip_client():
    import zulip

    return zulip.Client(
        email="dashboard-bot@napari.zulipchat.com",
        api_key=os.environ.get("ZULIP_API_KEY"),
        site="https://napari.zulipchat.com",
    )


def send_zulip_message(client, content: str, channel: str, topic: str) -> int:
    """Send a channel message and return its id."""
    # Zulip accepts either a channel name or its numeric id
    to: str | int = int(channel) if channel.isdigit() else channel
    result = client.send_message(
        {"type": "stream", "to": to, "topic": topic, "content": content}
    )
    if result.get("result") != "success":
        raise RuntimeError(f"Failed to send Zulip message: {result}")
    return result["id"]


def add_zulip_reaction(client, message_id: int, emoji_name: str) -> bool:
    result = client.add_reaction(
        {"message_id": message_id, "emoji_name": emoji_name}
    )
    if result.get("result") != "success":
        logger.error("Failed to add reaction to %s: %s", message_id, result)
        return False
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--window",
        choices=WINDOWS,
        default="next-week",
        help="Which meetings to announce (default: %(default)s)",
    )
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        default=None,
        help="Pretend today is this date (YYYY-MM-DD), for testing",
    )
    parser.add_argument("--send-zulip", action="store_true")
    parser.add_argument(
        "--channel",
        default="metrics and analytics",
        help="Zulip channel name or numeric id",
    )
    parser.add_argument(
        "--topic",
        default=None,
        help=(
            "Send all messages to this single topic, each prefixed with the "
            "topic it would get normally (for testing). Without it every "
            "meeting gets its own topic."
        ),
    )
    args = parser.parse_args()

    today = args.today or datetime.now(timezone.utc).date()
    start, end = get_window(args.window, today)
    logger.info("Looking for meetings between %s and %s", start, end)
    meetings = get_meetings(fetch_calendar(), start, end)

    # (topic, content, add RSVP reaction)
    messages = [
        (meeting_topic(meeting), format_meeting_message(meeting), True)
        for meeting in meetings
    ]
    if args.topic:
        messages = [
            (args.topic, f"**Topic:** `{topic}`\n\n{content}", react)
            for topic, content, react in messages
        ] or [(args.topic, format_no_meetings(start, end), False)]
    elif not messages:
        logger.info("No meetings to announce")

    client = get_zulip_client() if args.send_zulip else None
    reactions_ok = True
    for topic, content, react in messages:
        print(f"=== {topic}\n{content}\n")
        if client is None:
            continue
        logger.info("Sending message to %s > %s", args.channel, topic)
        message_id = send_zulip_message(client, content, args.channel, topic)
        if react:
            reactions_ok &= add_zulip_reaction(client, message_id, RSVP_EMOJI)

    if not reactions_ok:
        # the announcements are out, but report the problem in CI
        sys.exit(1)


if __name__ == "__main__":
    main()
