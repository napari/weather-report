from __future__ import annotations

import argparse
import datetime
import os.path
import sys
from dataclasses import dataclass
from pathlib import Path

import humanize
import pandas as pd
from google.cloud import bigquery, bigquery_storage
from google.cloud.bigquery import UnknownJob
from packaging import version
from sqlalchemy import Engine, create_engine, func
from sqlalchemy.orm import Session
from tqdm import tqdm

from napari_dashboard.db_schema.base import Base
from napari_dashboard.db_schema.pypi import PyPi
from napari_dashboard.gdrive_util import (
    COMPRESSED_DB,
    DB_PATH,
    compress_file,
    fetch_database,
    upload_db_dump,
)

PROCESSED_BYTES_LIMIT = 1000**4 - 50 * 1000**3
# 950GB limit to ensure to fit in 1 TB free limit


# The query template
QUERRY = """
SELECT
  timestamp,
  country_code,
  file.filename AS project,
  details.python AS python,
  details.system.name AS system,
  details.system.release AS system_release,
  details.distro.name AS distro_name,
  details.distro.version AS distro_version
FROM
  `bigquery-public-data.pypi.file_downloads`
WHERE
  file.project = 'napari'
  AND details.installer.name = 'pip'
  AND timestamp BETWEEN TIMESTAMP('{begin}') AND TIMESTAMP('{end}')
ORDER BY
  timestamp;
"""


class EstimationError(Exception):
    pass


@dataclass
class ProjectInfo:
    name: str
    version: version.Version
    wheel: bool


def parse_file_name(file_name: str) -> ProjectInfo:
    """
    Parse the file name to get the project name, version and if it is a wheel file

    Parameters
    ----------
    file_name: str
        The name of the file to parse.
        The file needs to be a valid entry from the PyPi database.
        For example:
        napari-0.5.4.tar.gz
        napari-0.5.4-py3-none-any.whl

    Returns
    -------
    ProjectInfo
        The parsed information
    """
    name, ext = os.path.splitext(file_name)
    wheel = ext == ".whl"
    if ext == ".gz":
        name = os.path.splitext(name)[0]

    name, version_ = name.split("-", 2)[:2]
    return ProjectInfo(name, version.parse(version_), wheel)


def is_ci_install(system_release: str) -> bool:
    """Check if the download was performed on the CI system.

    It is done by check if the system_release string contains the information.
    It catches only part of Linux distributions.
    """
    if "azure" in system_release:
        return True
    if "amzn" in system_release:
        return True
    if "aws" in system_release:
        return True
    if "gcp" in system_release:
        return True
    if "cloud-amd64" in system_release:  # noqa: SIM103
        return True
    return False


def load_from_query(df: pd.DataFrame, engine: Engine):
    """Convert the data frame to the PyPi object and save it to the database"""
    with Session(engine) as session:
        for i, row in enumerate(df.iterrows()):
            project_info = parse_file_name(row[1].project)
            is_ci = is_ci_install(row[1].system_release)
            # print(row)
            obj = PyPi(
                timestamp=row[1].timestamp,
                date=row[1].timestamp.date(),
                country_code=row[1].country_code,
                project=project_info.name,
                version=str(project_info.version),
                python_version=row[1].python,
                system_name=row[1].system or "",
                system_release=row[1].system_release or "",
                distro_name=row[1].distro_name or "",
                distro_version=row[1].distro_version or "",
                wheel=project_info.wheel,
                ci_install=is_ci,
            )
            session.add(obj)
            if i % 10000 == 0:
                session.commit()
        session.commit()


def get_version_from_beginning(details: str, with_pre=True) -> tuple[str, str]:
    """Get the version from the beginning of the string.

    Helper function for load_from_czi_file function

    Parameters
    ----------
    details: str
        The string to parse
    with_pre: bool
        If True, the function will also parse the pre-release information

    Returns
    -------
    Tuple[str, str]
        The version and the rest of the string

    """
    suffix_li = ["rc", "a", "b", "dev", "post"] if with_pre else []
    i = 0
    while i < len(details):
        if details[i].isalpha():
            for suffix in suffix_li:
                if details[i:].startswith(suffix):
                    i += len(suffix)
                    break
            else:
                return details[:i], details[i:]
        else:
            i += 1
    return details, ""


def get_name_from_begin(details: str) -> tuple[str, str]:
    """Get the name from the beginning of the string.

    Helper function for load_from_czi_file function

    Parameters
    ----------
    details: str
        The string to parse

    Returns
    -------
    Tuple[str, str]
        The name and the rest of the string

    """
    for i in range(len(details)):
        if details[i].isdigit():
            return details[:i], details[i:]
    return details, ""


def parse_distro(distro: str):
    """Parse the distro string to get the name and version

    Helper function for load_from_czi_file function

    Parameters
    ----------
    distro: str
        The distro string to parse. For example:
        Ubuntu22.04jammy

    Returns
    -------
    Tuple[str, str]
        The distro name and version
    """
    for i in range(len(distro)):
        if distro[i].isdigit():
            distro_name = distro[:i]
            for j in range(i, len(distro)):
                if distro[j].isalpha():
                    distro_version = distro[i:j]
                    return distro_name, distro_version

    raise ValueError("No version found in distro string")


def parse_system_from_string(details: str) -> tuple[str, str, str, str]:
    """Parse the system string to get the name and version

    Helper function for load_from_czi_file function

    Parameters
    ----------
    details: str
        The system string to parse. For example:
        Linux5.10.16.3-microsoft-standard-WSL2x86_64

    Returns
    -------
    """
    for el in ("x86_64", "arm64", "AMD64", "i386", "OpenSSL", "iPad"):
        if el in details:
            details = details[: details.rfind(el)]
            break
    distribution_name, details = get_name_from_begin(details)
    if distribution_name.startswith("WindowsVista"):
        return "Windows", "Vista", "", ""
    if distribution_name.startswith("WindowsME"):
        return "Windows", "Me", "", ""
    if distribution_name.startswith("CYGWIN"):
        return "Cygwin", "", "", ""
    if distribution_name.startswith("MSYS"):
        return "MSYS", "", "", ""
    if distribution_name == "Windows":
        return distribution_name, details, "", ""

    distribution_version, details = get_version_from_beginning(
        details, with_pre=False
    )

    if distribution_name.startswith("Darwin"):
        return "", "", "Darwin", distribution_version

    if distribution_name == "iOS":
        name, version_ = get_name_from_begin(details)
        return distribution_name, distribution_version, name, version_

    if distribution_name in ("macOS", "OS X"):
        system_name, details = get_name_from_begin(details)
        assert system_name == "Darwin"
        system_version, details = get_version_from_beginning(
            details, with_pre=False
        )
        return (
            distribution_name,
            distribution_version,
            system_name,
            system_version,
        )

    if distribution_name == "Linux":
        return distribution_name, distribution_version, "", ""

    if "BSD" in distribution_name:
        return distribution_name, distribution_version, "", ""

    if "Linux" not in details:
        raise ValueError("System name not found")

    # we are in linux case
    linux_pos = details.find("Linux")
    linux_end = linux_pos + len("Linux")
    return (
        distribution_name,
        distribution_version,
        "Linux",
        details[linux_end:],
    )


def parse_python_from_string(details: str) -> tuple[str, str, str, str]:
    """Split string like this:

    Helper function for load_from_czi_file function

    pip23.0.13.10.6CPython3.10.6Ubuntu22.04jammyglibc2.35Linux5.10.16.3-microsoft-standard-WSL2x86_64OpenSSL 3.0.2 15 Mar 202267.4.01.67.1
    """
    python_str_li = ["CPython", "PyPy", "GraalVM"]

    for python_str in python_str_li:
        python_pos = details.find(python_str)
        if python_pos != -1:
            python_version = details[:python_pos]
            python_implementation = python_str
            python_implementation_version, details = (
                get_version_from_beginning(
                    details[python_pos + len(python_str) :]
                )
            )
            break
    else:
        raise ValueError("Python version not found")

    return (
        python_version,
        python_implementation,
        python_implementation_version,
        details,
    )


def parse_details(row):
    """Helper function for load_from_czi_file function"""
    # Parse strings like
    # pip21.33.8.3CPython3.8.3Windows7OpenSSL 1.1.1f 31 Mar 202062.1.0
    # pip23.0.13.10.6CPython3.10.6Ubuntu22.04jammyglibc2.35Linux5.10.16.3-microsoft-standard-WSL2x86_64OpenSSL 3.0.2 15 Mar 202267.4.01.67.1
    # pip20.3.13.7.4CPython3.7.4macOS10.12.6Darwin16.7.0x86_64OpenSSL 1.1.1d  10 Sep 201951.0.0

    details_str = row.DETAILS_ALL
    details_str = details_str[
        len(row.DETAILS_INSTALLER_NAME) + len(row.DETAILS_INSTALLER_VERSION) :
    ]

    (
        python_version,
        python_implementation,
        python_implementation_version,
        details_str,
    ) = parse_python_from_string(details_str)
    distro_name, distro_version, system_name, system_version = (
        parse_system_from_string(details_str)
    )
    return (
        python_version,
        python_implementation,
        python_implementation_version,
        system_name,
        system_version,
        distro_name,
        distro_version,
    )


def load_from_czi_file(czi_file: str, engine) -> None:
    """
    This is a helper function to load the data from the file
    that we get from the CZI.

    It was used to not need to perform download of all historical data

    Note
    ----
    This is not used in the current version of the code.
    Keep it for the future use if we need to initialize the database again.
    """
    df = pd.read_csv(czi_file)
    with Session(engine) as session:
        for i, row in tqdm(enumerate(df.iterrows()), total=len(df)):
            if row[1].PROJECT != "napari":
                continue
            (
                python_version,
                python_implementation,
                python_implementation_version,
                system_name,
                system_version,
                distro_name,
                distro_version,
            ) = parse_details(row[1])

            is_ci = is_ci_install(row[1].DETAILS_ALL)
            parse_python_from_string(row[1].DETAILS_ALL)
            obj = PyPi(
                timestamp=datetime.datetime.strptime(
                    row[1].TIMESTAMP, "%Y-%m-%d %H:%M:%S.%f"
                ),
                date=datetime.datetime.strptime(
                    row[1].TIMESTAMP, "%Y-%m-%d %H:%M:%S.%f"
                ).date(),
                country_code=row[1].COUNTRY_CODE,
                project=row[1].PROJECT,
                version=row[1].FILE_VERSION,
                python_version=python_version,
                system_name=system_name,
                system_release=system_version,
                distro_name=distro_name,
                distro_version=distro_version,
                wheel=row[1].FILE_TYPE == "bdist_wheel",
                ci_install=is_ci,
            )
            session.add(obj)
            if i % 10000 == 0:
                session.commit()
        session.commit()


def make_big_query_and_save_to_database(
    engine: Engine, transferred_bytes: int
) -> bool:
    with Session(engine) as session:
        # get maximum timestamp
        last_entry_date = session.query(func.max(PyPi.timestamp)).first()[0]

    if last_entry_date is None:
        raise ValueError("No entry found in the database")
    upper_constraints = datetime.datetime.now()
    upper_constraints = upper_constraints.replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    if upper_constraints - last_entry_date < datetime.timedelta(hours=10):
        send_zulip_message("Too little time between the last entry and now")
        return False
    if upper_constraints - last_entry_date > datetime.timedelta(days=15):
        raise ValueError("Too much time between the last entry and now")

    qr = QUERRY.format(
        begin=last_entry_date.strftime("%Y-%m-%d %H:%M:%S"),
        end=upper_constraints.strftime("%Y-%m-%d %H:%M:%S"),
    )
    print(last_entry_date)
    print(qr)
    # perform the query
    # gauth = login_with_local_webserver()
    client = bigquery.Client()  # credentials=gauth.credentials)
    bq_storage_client = bigquery_storage.BigQueryReadClient()
    job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    estimate_query_job = client.query(qr, job_config=job_config)
    estimated_bytes = int(estimate_query_job.total_bytes_processed)
    if transferred_bytes + estimated_bytes > PROCESSED_BYTES_LIMIT:
        send_zulip_message(
            "The estimated download size is more than the limit. Skip the update. "
            f"Currently processed bytes: {humanize.naturalsize(transferred_bytes)}. "
            f"Estimated bytes to processed query: {humanize.naturalsize(estimated_bytes)}. "
            f"Limit: {humanize.naturalsize(PROCESSED_BYTES_LIMIT)}."
        )
        raise EstimationError
    query_job = client.query(qr)

    results = query_job.result()
    df = results.to_dataframe(bqstorage_client=bq_storage_client)
    load_from_query(df, engine)
    processed_bytes = int(query_job.total_bytes_processed)
    send_zulip_message(
        f"Downloaded data from big query. Processed bytes {humanize.naturalsize(processed_bytes)}. "
        f"This makes total processed bytes growth from {humanize.naturalsize(transferred_bytes)} to "
        f"{humanize.naturalsize(transferred_bytes + processed_bytes)}. "
        f"The estimated size of the query was {humanize.naturalsize(estimated_bytes)}."
    )
    return True


def get_information_about_processed_bytes() -> int:
    """
    Get the information about the processed bytes in the current month

    Function performs the query to the Big Query to get the information about
    the processed bytes
    """
    # Initialize the client
    client = bigquery.Client()

    now = datetime.datetime.now(datetime.timezone.utc)
    month_begin = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    total_bytes_processed = 0
    # List recent jobs
    for job in client.list_jobs(all_users=True, min_creation_time=month_begin):
        if isinstance(job, UnknownJob):
            continue
        if job.error_result is not None and job.total_bytes_processed is None:
            continue
        total_bytes_processed += job.total_bytes_processed

    return total_bytes_processed


def send_zulip_message(message: str):
    """Send a message to the zulip chat.

    Helper function for better readability.

    Note
    ----
    This function does not check the length of the message.
    So if the message is too long, it will be cut off.
    """
    import zulip

    client = zulip.Client(
        email="dashboard-bot@napari.zulipchat.com",
        api_key=os.environ.get("ZULIP_API_KEY"),
        site="https://napari.zulipchat.com",
    )

    client.send_message(
        {
            "type": "stream",
            "to": "metrics and analytics",
            "subject": "Deploy dashboard",
            "content": message,
        }
    )


def main(args: None | list[str] = None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "db_path",
        help="Path to the database",
        type=Path,
        default=Path(DB_PATH),
        nargs="?",
    )
    args = parser.parse_args(args)

    processed_bytes = get_information_about_processed_bytes()

    if processed_bytes > PROCESSED_BYTES_LIMIT:
        send_zulip_message(
            f"Totally processed: {humanize.naturalsize(processed_bytes)} "
            f"is more than {humanize.naturalsize(PROCESSED_BYTES_LIMIT)} limit. "
            "Skip the update"
        )
        return -1

    fetch_database(args.db_path.absolute())
    engine = create_engine(f"sqlite:///{args.db_path.absolute()}")
    Base.metadata.create_all(engine)
    try:
        updated = make_big_query_and_save_to_database(engine, processed_bytes)
    except EstimationError:
        return -2
    if updated:
        compress_file(args.db_path.absolute(), COMPRESSED_DB)
        print("Uploading database")
        upload_db_dump(COMPRESSED_DB)
    return 0


if __name__ == "__main__":
    sys.exit(main())
