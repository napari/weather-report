import argparse
import logging
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from napari_dashboard.gdrive_util import fetch_database
from napari_dashboard.gen_stat.github import (
    get_last_week,
    get_last_week_active_core_devs,
    get_last_week_closed_issues_as_md,
    get_last_week_closed_pr_md,
    get_last_week_merged_pr_md,
    get_last_week_new_issues_md,
    get_last_week_new_pr_md,
    get_last_week_updated_issues_md,
    get_last_week_updated_pr_md,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

def generate_weekly_summary(fetch_db: bool) -> list[str]:
    """
    Generate Markdown for the weekly summary.
    It is served as a list of lines to easier split it in case of a long message.
    """
    start, end = get_last_week()
    if fetch_db:
        fetch_database()
    logger.info("Generating weekly summary")
    engine = create_engine("sqlite:///dashboard.db")
    res = [f"# Weekly Summary {start.date()}-{end.date()}\n"]
    logger.info("Database connected")
    with Session(engine) as session:
        logger.info("Fetch PR")
        if new_pr := get_last_week_new_pr_md(session):
            res.append("## New Pull Requests\n")
            res.extend(f" - {text}" for text in new_pr)
        logger.info("Fetch updated PR")
        if updated_pr := get_last_week_updated_pr_md(session):
            res.append("\n## Updated Pull Requests (state unchanged)\n")
            res.extend(f" - {text}" for text in updated_pr)
        logger.info("Fetch merged PR")
        if merged_pr := get_last_week_merged_pr_md(session):
            res.append("\n## Merged Pull Requests\n")
            res.extend(f" - {text}" for text in merged_pr)
        logger.info("Fetch closed PR")
        if closed_pr := get_last_week_closed_pr_md(session):
            res.append("\n## Closed Pull Requests (unmerged)\n")
            res.extend(f" - {text}" for text in closed_pr)
        logger.info("Fetch issues")
        if new_issue := get_last_week_new_issues_md(session):
            res.append("\n## New Issues\n")
            res.extend(f" - {text}" for text in new_issue)
        logger.info("Fetch updated issues")
        if updated_issue := get_last_week_updated_issues_md(session):
            res.append("\n## Updated Issues (state unchanged)\n")
            res.extend(f" - {text}" for text in updated_issue)
        logger.info("Fetch closed issues")
        if closed_issues := get_last_week_closed_issues_as_md(session):
            res.append("\n## Closed Issues\n")
            res.extend(f" - {text}" for text in closed_issues)

        res.append("\n## Core-devs active in repositories\n")
        res.append(", ".join(get_last_week_active_core_devs(session)))

    logger.info("Summary generated")

    return res


def main():
    parse = argparse.ArgumentParser()
    parse.add_argument("--send-zulip", action="store_true")
    parse.add_argument(
        "--channel",
        default="metrics and analytics",
        help="Zulip channel to send the message to",
    )
    parse.add_argument(
        "--no-fetch", action="store_true", help="Do not fetch the database"
    )

    args = parse.parse_args()

    message = generate_weekly_summary(not args.no_fetch)
    if args.send_zulip:
        logger.info("Sending message to Zulip")
        import zulip

        client = zulip.Client(
            email="dashboard-bot@napari.zulipchat.com",
            api_key=os.environ.get("ZULIP_API_KEY"),
            site="https://napari.zulipchat.com",
        )
        result = client.register(event_types=["message", "realm"])
        max_length = result[
            "max_message_length"
        ]  # get information about the max length of a message in characters
        message_in_parts = [[]]

        count = 0
        for line in message:
            line_length = len(line) + 1  # add 1 for newline
            if count + line_length > max_length:
                # message is too long, split it
                count = 0
                message_in_parts.append([])
            message_in_parts[-1].append(line)
            count += line_length

        # send the message to the channel
        for message_li in message_in_parts:
            content = "\n".join(message_li)
            client.send_message(
                {
                    "type": "stream",
                    "to": args.channel,
                    "subject": "Weekly Summary",
                    "content": content,
                }
            )

    print("\n".join(message))


if __name__ == "__main__":
    main()
