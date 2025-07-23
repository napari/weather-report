from __future__ import annotations

import argparse
import datetime
import logging
import typing
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from napari_dashboard.db_schema.base import Base
from napari_dashboard.db_schema.helper_models import UpdateDBInfo
from napari_dashboard.db_update.conda import save_conda_download_information
from napari_dashboard.db_update.github import (
    save_issues,
    save_pull_requests,
    save_stars,
    update_artifact_download,
)
from napari_dashboard.db_update.imagesc import save_forum_info
from napari_dashboard.db_update.pypi import (
    save_package_release,
    save_pepy_download_stat,
    save_pypi_download_information,
)
from napari_dashboard.db_update.util import setup_cache

if typing.TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def check_if_recently_updated(session: Session) -> bool:
    twelve_hours_ago = datetime.datetime.now() - datetime.timedelta(hours=12)
    last_update = (
        session.query(UpdateDBInfo)
        .filter(UpdateDBInfo.datetime > twelve_hours_ago)
        .first()
    )
    if last_update is None:
        return False
    return last_update.datetime.date() == datetime.date.today()


def update_github(session: Session):
    save_stars("napari", "napari", session)
    save_stars("napari", "docs", session)
    save_stars("napari", "npe2", session)

    save_pull_requests("napari", "napari", session)
    save_pull_requests("napari", "docs", session)
    save_pull_requests("napari", "npe2", session)

    save_issues("napari", "napari", session)
    save_issues("napari", "docs", session)
    save_issues("napari", "npe2", session)

    update_artifact_download("napari", "napari", session)


def main(args: Sequence[str] | None = None) -> bool:
    parser = argparse.ArgumentParser()
    parser.add_argument("db_path", help="Path to the database", type=Path)
    args = parser.parse_args(args)

    setup_cache()

    engine = create_engine(f"sqlite:///{args.db_path.absolute()}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        if check_if_recently_updated(session):
            logger.info("Database was recently updated, skipping update")
            return False
        update_github(session)
        save_forum_info(session)
        save_conda_download_information(session)
        save_pepy_download_stat(session)
        save_pypi_download_information(session)
        save_package_release(session)
        session.add(UpdateDBInfo(datetime=datetime.datetime.now()))
        session.commit()
    return True


if __name__ == "__main__":
    main()
