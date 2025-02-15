from __future__ import annotations

import math
import typing
from datetime import date, timedelta

import pycountry
from packaging.version import parse as parse_version
from sqlalchemy import func, null

from napari_dashboard.db_schema.pypi import (
    PackageRelease,
    PePyDownloadStat,
    PePyTotalDownloads,
    PyPi,
    PyPiDownloadPerOS,
    PyPiDownloadPerPythonVersion,
)

if typing.TYPE_CHECKING:
    from sqlalchemy.orm import Session


def get_active_packages(session: Session, packages: set[str], threshold: int):
    month_ago = date.today() - timedelta(days=30)
    subquery = (
        session.query(
            PePyDownloadStat.name,
            func.sum(PePyDownloadStat.downloads).label("total_download"),
        )
        .filter(PePyDownloadStat.date >= month_ago)
        .filter(PePyDownloadStat.name.in_(packages))
        .group_by(PePyDownloadStat.name)
        .subquery()
    )

    return dict(
        session.query(subquery)
        .filter(subquery.c.total_download > threshold)
        .all()
    )


def get_download_info(session: Session, packages: list[str]):
    day_ago = date.today() - timedelta(days=1)
    week_ago = date.today() - timedelta(days=7)
    month_ago = date.today() - timedelta(days=30)

    query_month = dict(
        session.query(
            PePyDownloadStat.name,
            func.sum(PePyDownloadStat.downloads).label("Last month"),
        )
        .filter(PePyDownloadStat.date >= month_ago)
        .filter(PePyDownloadStat.name.in_(packages))
        .group_by(PePyDownloadStat.name)
        .all()
    )
    query_week = dict(
        session.query(
            PePyDownloadStat.name,
            func.sum(PePyDownloadStat.downloads).label("Last week"),
        )
        .filter(PePyDownloadStat.date >= week_ago)
        .filter(PePyDownloadStat.name.in_(packages))
        .group_by(PePyDownloadStat.name)
        .all()
    )

    query_day = dict(
        session.query(
            PePyDownloadStat.name,
            func.sum(PePyDownloadStat.downloads).label("Last day"),
        )
        .filter(PePyDownloadStat.date >= day_ago)
        .filter(PePyDownloadStat.name.in_(packages))
        .group_by(PePyDownloadStat.name)
        .all()
    )

    total_query = dict(
        session.query(PePyTotalDownloads.name, PePyTotalDownloads.downloads)
        .filter(PePyTotalDownloads.name.in_(packages))
        .all()
    )

    return {
        "Last day": query_day,
        "Last week": query_week,
        "Last month": query_month,
        "Total": total_query,
    }


def get_pepy_download_per_day(session: Session, package: str):
    return dict(
        session.query(
            PePyDownloadStat.date, func.sum(PePyDownloadStat.downloads)
        )
        .filter(PePyDownloadStat.name == package)
        .group_by(PePyDownloadStat.date)
        .all()
    )


def get_pypi_download_per_day(session: Session, package: str):
    assert package == "napari", "We only collect data for napari now"
    return dict(
        session.query(PyPi.date, func.count(PyPi.timestamp))
        .filter(PyPi.project == package)
        .filter(PyPi.ci_install.isnot(True))
        .group_by(PyPi.date)
        .all()
    )


def get_total_pypi_download(session: Session, packages: set[str]):
    return (
        session.query(func.sum(PePyTotalDownloads.downloads))
        .filter(PePyTotalDownloads.name.in_(packages))
        .scalar()
    )


def get_recent_releases_date(
    session: Session, packages: set[str], after: date
):
    return (
        session.query(PackageRelease.name)
        .filter(PackageRelease.name.in_(packages))
        .filter(PackageRelease.release_date >= after)
        .group_by(PackageRelease.name)
        .count()
    )


def get_weekly_download_per_os(session: Session, package: str, since: date):
    return dict(
        session.query(
            PyPiDownloadPerOS.os, func.sum(PyPiDownloadPerOS.downloads)
        )
        .filter(PyPiDownloadPerOS.package_name == package)
        .filter(PyPiDownloadPerOS.date >= since)
        .group_by(PyPiDownloadPerOS.os)
        .all()
    )


def get_download_per_python_version(
    session: Session, package: str, since: date
):
    return sorted(
        filter(
            lambda x: x[0] != "null" and x[1] > 100,
            session.query(
                PyPiDownloadPerPythonVersion.python_version_name,
                func.sum(PyPiDownloadPerPythonVersion.downloads),
            )
            .filter(PyPiDownloadPerPythonVersion.package_name == package)
            .filter(PyPiDownloadPerPythonVersion.package_date >= since)
            .group_by(PyPiDownloadPerPythonVersion.python_version_name)
            .all(),
        ),
        key=lambda x: parse_version(x[0]),
    )


def get_download_per_operating_system(
    session: Session, package: str, since: date
):
    return (
        session.query(
            PyPiDownloadPerOS.os_name, func.sum(PyPiDownloadPerOS.downloads)
        )
        .filter(PyPiDownloadPerOS.package_name == package)
        .filter(PyPiDownloadPerOS.package_date >= since)
        .group_by(PyPiDownloadPerOS.os_name)
        .all()
    )


def is_country(x):
    return pycountry.countries.get(alpha_2=x) is not None


def add_country_info(row):
    country_info = pycountry.countries.get(alpha_2=row.country_code)
    if country_info is None:
        print(row)
    return country_info.alpha_3, country_info.name


def add_plot_info(df):
    sum_ = df["count"].sum()

    def _add_plot_info(row):
        percent = row["count"] / sum_ * 100
        return (
            math.log10(row["count"]),
            f"{row.country_name}<br>Downloads: {row['count']}<br>Percent: {percent:.2f}%",
        )

    return _add_plot_info


def get_per_country_download(
    session: Session, package: str, since: date | None = None
):
    query = (
        session.query(
            PyPi.country_code, func.count(PyPi.country_code).label("count")
        )
        .filter(PyPi.project == package)
        # filter out ci downloads
        .filter(PyPi.ci_install.isnot(True))
        # filter out None country code
        .filter(PyPi.country_code.isnot(null()))
    )
    if since is not None:
        query = query.filter(PyPi.timestamp >= since)
    query = query.group_by(PyPi.country_code)
    return query.all()
