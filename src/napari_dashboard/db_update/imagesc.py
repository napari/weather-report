import datetime
import time

import requests
import tqdm
from sqlalchemy.orm import Session

from napari_dashboard.db_schema.imagesc import ForumTag, ForumTopic, ForumUser
from napari_dashboard.db_update.util import get_or_create


def save_user_info(
    session: Session, user_dict: dict[str, ForumUser], user_data: dict
):
    for user in user_data:
        if user["id"] in user_dict:
            continue

        user = get_or_create(
            session,
            ForumUser,
            id=user["id"],
            username=user["username"],
            name=user["name"],
        )
        user_dict[user.id] = user


def save_tag_info(
    session: Session, tag_dict: dict[str, ForumTag], tag_data: list[str]
):
    for tag in tag_data:
        if tag not in tag_dict:
            tag_dict[tag] = get_or_create(session, ForumTag, name=tag)


def save_forum_info(session: Session):
    index = 1
    user_dict = {}
    tag_dict = {}

    with tqdm.tqdm(desc="Fetching forum information") as pbar:
        while True:
            pbar.update(1)
            topics_res = requests.get(
                f"https://forum.image.sc/tag/napari/l/latest.json?page={index}",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:20.0) Gecko/20100101 Firefox/20.0"
                },
            )
            if topics_res.status_code == 429:
                pbar.write(
                    "Rate limit exceeded. Waiting for 60 seconds before retrying."
                )
                time.sleep(60)
                continue
            topics = topics_res.json()
            index += 1
            if not topics["topic_list"]["topics"]:
                break

            save_user_info(session, user_dict, topics["users"])

            for topic in topics["topic_list"]["topics"]:
                save_tag_info(session, tag_dict, topic["tags"])

                topic_list = (
                    session.query(ForumTopic)
                    .filter(ForumTopic.id == topic["id"])
                    .all()
                )
                if not topic_list:
                    topic = ForumTopic(
                        id=topic["id"],
                        title=topic["title"],
                        fancy_title=topic["fancy_title"],
                        slug=topic["slug"],
                        created_at=datetime.datetime.fromisoformat(
                            topic["created_at"]
                        ).replace(tzinfo=None),
                        last_posted_at=datetime.datetime.fromisoformat(
                            topic["last_posted_at"]
                        ).replace(tzinfo=None),
                        post_count=topic["posts_count"],
                        tags=[tag_dict[x] for x in topic["tags"]],
                        users=[
                            user_dict[x["user_id"]] for x in topic["posters"]
                        ],
                    )
                    session.add(topic)
                else:
                    topic_ = topic_list[0]
                    topic_.last_posted_at = datetime.datetime.fromisoformat(
                        topic["last_posted_at"]
                    ).replace(tzinfo=None)
                    topic_.post_count = topic["posts_count"]
                    topic_.tags = [tag_dict[x] for x in topic["tags"]]
                    topic_.users = [
                        user_dict[x["user_id"]] for x in topic["posters"]
                    ]
                    session.commit()
