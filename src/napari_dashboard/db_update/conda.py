import datetime

import requests
import tqdm
from sqlalchemy.orm import Session

from napari_dashboard.db_schema.conda import CondaDownload
from napari_dashboard.utils import requests_get


def _save_conda_download_information_for_package(
    session: Session, pypi_name: str, conda_name: str, today: datetime.date
):
    if conda_name is None:
        return
    if (
        session.query(CondaDownload)
        .filter(
            CondaDownload.pypi_name == pypi_name, CondaDownload.date == today
        )
        .count()
        > 0
    ):
        return
    conda_info_res = requests.get(
        f"https://api.anaconda.org/package/{conda_name}"
    )
    if conda_info_res.status_code != 200:
        raise ValueError(
            f"Error fetching conda info for {conda_name} with status {conda_info_res.status_code} and body {conda_info_res.text}"
        )
    conda_info = conda_info_res.json()
    for file in conda_info["files"]:
        session.add(
            CondaDownload(
                pypi_name=pypi_name,
                name=conda_name,
                version=file["version"],
                download_count=file["ndownloads"],
                date=today,
                full_binary_name=file["full_name"],
                latest_version=file["version"] == conda_info["latest_version"],
            )
        )


def save_conda_download_information(session: Session, limit: int = 10):
    response = requests_get("https://api.napari.org/api/conda")
    conda_translation = response.json()
    today = datetime.date.today()

    _save_conda_download_information_for_package(
        session, "napari", "conda-forge/napari", today
    )
    _save_conda_download_information_for_package(
        session,
        "napari-plugin-manager",
        "conda-forge/napari-plugin-manager",
        today,
    )
    _save_conda_download_information_for_package(
        session, "npe2", "conda-forge/npe2", today
    )

    for pypi_name, conda_name in tqdm.tqdm(
        conda_translation.items(), desc="Fetching conda info"
    ):
        _save_conda_download_information_for_package(
            session, pypi_name, conda_name, today
        )
    session.commit()
