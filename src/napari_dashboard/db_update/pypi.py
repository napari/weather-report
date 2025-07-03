from __future__ import annotations

import datetime
import logging
import os
import typing
from time import sleep

import requests
import tqdm
from sqlalchemy.orm import Session

from napari_dashboard.db_schema.pypi import (
    OperatingSystem,
    PackageRelease,
    PePyDownloadStat,
    PePyTotalDownloads,
    PyPi,
    PyPiDownloadPerOS,
    PyPiDownloadPerPythonVersion,
    PyPiStatsDownloads,
    PythonVersion,
)
from napari_dashboard.plugins_info import (
    get_packages_to_fetch,
    plugin_name_list,
)

if typing.TYPE_CHECKING:
    from sqlalchemy import Engine

START_DATE = "2018-01-01"


class PackageNotFound(Exception):
    pass


def indexed_projects(engine: Engine) -> list[str]:
    with Session(engine) as session:
        dist = session.query(PyPi.project).distinct()
    return [d[0] for d in dist]


def new_projects(engine: Engine) -> list[str]:
    all_projects = plugin_name_list()
    return sorted(set(all_projects) - set(indexed_projects(engine)))


def get_last_entry(engine: Engine) -> PyPi | None:
    with Session(engine) as session:
        return session.query(PyPi).order_by(PyPi.timestamp.desc()).first()


def get_last_entry_timestamp(engine: Engine) -> str:
    last_entry = get_last_entry(engine)
    if last_entry is None:
        return START_DATE
    return last_entry.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f UTC")


def get_now_timestamp() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f UTC")


QUERY = """
SELECT *
FROM `bigquery-public-data.pypi.file_downloads`
WHERE file.project in ({projects})
  AND timestamp > '{timestamp_lower}'
  AND timestamp < '{timestamp_upper}'
"""


def build_update_query(engine: Engine) -> str:
    projects = indexed_projects(engine)
    timstamp_lower = get_last_entry_timestamp(engine)
    timstamp_upper = get_now_timestamp()
    if not projects:
        projects = ["napari"]
    return QUERY.format(
        projects=", ".join(f"'{x}'" for x in projects),
        timestamp_lower=timstamp_lower,
        timestamp_upper=timstamp_upper,
    )


def build_new_projects_query(engine: Engine) -> str:
    projects = new_projects(engine)
    return QUERY.format(
        projects=", ".join(f"'{x}'" for x in projects),
        timestamp_lower=START_DATE,
        timestamp_upper=get_now_timestamp(),
    )


def _save_pepy_download_stat(session: Session, package: str):
    res = requests.get(
        f"https://pepy.tech/api/v2/projects/{package}",
        headers={"X-Api-Key": os.environ["PEPY_KEY"]},
    )
    if res.status_code == 429:
        logging.warning("Too many requests for %s, waiting", package)
        sleep(30) if "CI" in os.environ else sleep(1)
        _save_pepy_download_stat(session, package)
        return
    pepy = res.json()
    if "total_downloads" not in pepy:
        logging.warning(
            "Error fetching pepy info for %s with message %s",
            package,
            pepy["message"],
        )
        return
    session.merge(
        PePyTotalDownloads(name=package, downloads=pepy["total_downloads"])
    )
    for day, downloads in pepy["downloads"].items():
        day_date = datetime.date.fromisoformat(day)
        for version, count in downloads.items():
            # if (pepy := session.query(PePyDownloadStat).filter(
            #     PePyDownloadStat.name == package,
            #     PePyDownloadStat.version == version,
            #     PePyDownloadStat.date == day_date,
            # ).first()) is not None:
            #     pepy.downloads = count
            # else:
            session.merge(
                PePyDownloadStat(
                    name=package,
                    version=version,
                    date=day_date,
                    downloads=count,
                )
            )
    session.commit()


def save_pepy_download_stat(session: Session):
    for plugin in tqdm.tqdm(
        get_packages_to_fetch(), desc="Fetching pepy plugin stats"
    ):
        _save_pepy_download_stat(session, plugin)
    session.commit()


def init_os(session: Session):
    all_os = {x[0] for x in session.query(OperatingSystem.name).all()}
    for os_ in ("darwin", "linux", "windows", "other", "null"):
        if os_ not in all_os:
            session.add(OperatingSystem(name=os_))


def init_python_version(session: Session):
    all_python_version = {
        x[0] for x in session.query(PythonVersion.version).all()
    }
    for python_version in [f"3.{num}" for num in range(6, 19)] + ["null"]:
        if python_version not in all_python_version:
            session.add(PythonVersion(version=python_version))


def _fetch_pypi_download_information(url: str, depth=10):
    result = requests.get(url)
    if result.status_code == 429:
        sleep(30) if "CI" in os.environ else sleep(1)
        if depth == 0:
            raise ValueError("Too many timeouts for pypi stats")
        return _fetch_pypi_download_information(url, depth - 1)
    if result.status_code == 404:
        raise PackageNotFound(f"Package not found at {url}")
    if result.status_code != 200:
        raise ValueError(
            f"Error fetching pypi info for {url} with status {result.status_code} and body {result.text}"
        )
    return result.json()


def _save_pypi_download_information(session: Session, package: str):
    try:
        overall = _fetch_pypi_download_information(
            f"https://pypistats.org/api/packages/{package}/overall"
        )
        python_minor = _fetch_pypi_download_information(
            f"https://pypistats.org/api/packages/{package}/python_minor"
        )
        system = _fetch_pypi_download_information(
            f"https://pypistats.org/api/packages/{package}/system"
        )
    except PackageNotFound:
        logging.warning("Package %s not found", package)
        return

    for el in overall["data"]:
        session.merge(
            PyPiStatsDownloads(
                name=package,
                date=datetime.date.fromisoformat(el["date"]),
                downloads=el["downloads"],
            )
        )
    for el in python_minor["data"]:
        session.merge(
            PyPiDownloadPerPythonVersion(
                package_name=package,
                package_date=datetime.date.fromisoformat(el["date"]),
                python_version_name=el["category"],
                downloads=el["downloads"],
            )
        )
    for el in system["data"]:
        session.merge(
            PyPiDownloadPerOS(
                package_name=package,
                package_date=datetime.date.fromisoformat(el["date"]),
                os_name=el["category"],
                downloads=el["downloads"],
            )
        )


def save_pypi_download_information(session: Session):
    init_os(session)
    session.commit()
    init_python_version(session)
    session.commit()

    for plugin in tqdm.tqdm(
        get_packages_to_fetch(), desc="Fetching pypistats data"
    ):
        _save_pypi_download_information(session, plugin)

    session.commit()


def _save_package_release(session: Session, name: str):
    data = requests.get(f"https://pypi.org/pypi/{name}/json").json()
    if "releases" not in data:
        return
    for version, artifacts in data["releases"].items():
        if not artifacts:
            continue
        release_date = min(
            datetime.datetime.fromisoformat(x["upload_time"])
            for x in artifacts
        ).date()
        session.merge(
            PackageRelease(
                name=name, version=version, release_date=release_date
            )
        )


def save_package_release(session: Session):
    for plugin in tqdm.tqdm(
        get_packages_to_fetch(), desc="Fetching pypi release data"
    ):
        _save_package_release(session, plugin)
    session.commit()
