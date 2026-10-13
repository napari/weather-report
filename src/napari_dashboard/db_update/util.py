import datetime as dt
import json
import sys

from sqlalchemy import Row


class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Row):
            return list(o)
        if isinstance(o, dt.date):
            return o.isoformat()
        return json.JSONEncoder.default(self, o)


def setup_cache(timeout=3600 * 5):
    """
    setup cache for speedup execution and reduce number of requests to GitHub API
    by default cache will expire after 1h (3600s)
    """
    try:
        import requests_cache
    except ImportError:
        print("requests_cache not installed", file=sys.stderr)
        return

    """setup cache for requests"""
    requests_cache.install_cache(
        "github_cache", backend="sqlite", expire_after=timeout
    )


def get_or_create(session, model, **kwargs):
    if "id" in kwargs:
        instance = session.query(model).get(kwargs["id"])
        if instance:
            for key, value in kwargs.items():
                setattr(instance, key, value)
            return instance
    instance = session.query(model).filter_by(**kwargs).first()
    if instance:
        return instance

    instance = model(**kwargs)
    session.add(instance)
    session.commit()
    return instance
