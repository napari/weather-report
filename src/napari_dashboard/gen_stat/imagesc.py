import datetime as dt

from sqlalchemy.orm import Session

from napari_dashboard.db_schema.imagesc import ForumTopic, ForumUser


def get_topics_count(since: dt.date, session: Session) -> dict:
    count = session.query(ForumTopic).count()
    active_count = (
        session.query(ForumTopic)
        .filter(ForumTopic.last_posted_at >= since)
        .count()
    )
    user_count = (
        session.query(ForumUser).join(ForumUser.topics).distinct().count()
    )
    user_count_last = (
        session.query(ForumUser)
        .join(ForumUser.topics)
        .filter(ForumTopic.last_posted_at >= since)
        .distinct()
        .count()
    )

    return {
        "topics_count": count,
        "users_count": user_count,
        "active_topics_count": active_count,
        "active_users_count": user_count_last,
    }
