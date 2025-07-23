import bz2
import hashlib
import logging
import os.path
from pathlib import Path
from typing import Optional, Union

from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive, GoogleDriveFile

COMPRESSED_DB = "dashboard.db.bz2"
DB_PATH = "dashboard.db"


def login_with_local_webserver():
    logging.info("Using local webserver")

    gauth = GoogleAuth()
    # Try to load saved client credentials
    gauth.LoadCredentialsFile("credentials.json")
    if gauth.credentials is None:
        # Authenticate if they're not there
        gauth.LocalWebserverAuth()
    elif gauth.access_token_expired:
        # Refresh them if expired
        gauth.Refresh()
    else:
        # Initialize the saved creds
        gauth.Authorize()
    # Save the current credentials to a file
    gauth.SaveCredentialsFile("credentials.json")

    return gauth


def login_with_service_account() -> GoogleAuth:
    """
    Google Drive service with a service account.
    note: for the service account to work, you need to share the folder or
    files with the service account email.

    """
    # Define the settings dict to use a service account
    # We also can use all options available for the settings dict like
    # oauth_scope,save_credentials,etc.
    logging.info("Using service account")
    settings = {
        "client_config_backend": "service",
        "service_config": {"client_json_file_path": "service-secrets.json"},
    }
    # Create instance of GoogleAuth
    gauth = GoogleAuth(settings=settings)
    # Authenticate
    gauth.ServiceAuth()
    return gauth


def get_auth():
    if os.path.exists("service-secrets.json"):
        gauth = login_with_service_account()
    else:
        gauth = login_with_local_webserver()
    return gauth


def get_or_create_gdrive_file(
    drive: GoogleDrive, file_name: str, folder_name: str = "napari_dashboard"
) -> GoogleDriveFile:
    """
    Get or create a file in a folder in Google Drive.

    Returns the file object if file exists, otherwise creates a new file in the folder.
    """
    file_list = drive.ListFile(
        {"q": f"title='{file_name}' and trashed=false"}
    ).GetList()
    if file_list:
        return file_list[0]
    folders = drive.ListFile(
        {
            "q": f"title='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        }
    ).GetList()
    for folder in folders:
        if folder["title"] == folder_name:
            return drive.CreateFile(
                {"title": file_name, "parents": [{"id": folder["id"]}]}
            )
    raise ValueError("Folder not found")


def upload_xlsx_dump():
    drive = GoogleDrive(get_auth())
    file = get_or_create_gdrive_file(drive, "napari_dashboard.xlsx")
    file.SetContentFile("webpage/napari_dashboard.xlsx")
    file.Upload()


def upload_db_dump(file_name=COMPRESSED_DB):
    drive = GoogleDrive(get_auth())
    file = get_or_create_gdrive_file(drive, file_name)
    file.SetContentFile(file_name)
    file.Upload()


def get_db_file() -> Optional[GoogleDriveFile]:
    drive = GoogleDrive(get_auth())
    file_list = drive.ListFile(
        {"q": "title='dashboard.db.bz2' and trashed=false"}
    ).GetList()
    if file_list:
        return file_list[0]
    return None


def calculate_md5(file_path: Union[str, Path]) -> str:
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def compress_file(original_file_path: str, compressed_file_path: str):
    with (
        open(original_file_path, "rb") as original_file,
        bz2.open(compressed_file_path, "wb") as compressed_file,
    ):
        compressed_file.writelines(original_file)


def uncompressed_file(compressed_file_path, original_file_path):
    with (
        bz2.open(compressed_file_path, "rb") as compressed_file,
        open(original_file_path, "wb") as original_file,
    ):
        original_file.writelines(compressed_file)


def fetch_database(db_path=DB_PATH):
    """Fetch the database from Google Drive."""
    logging.info("fetching database")

    db_path = Path(db_path)
    archive_path = db_path.with_suffix(".db.bz2")
    db_file = get_db_file()
    if db_file is not None:
        db_file.FetchMetadata(fields="md5Checksum")
        if not (
            archive_path.exists()
            and calculate_md5(archive_path) == db_file["md5Checksum"]
        ):
            logging.info("download database")

            db_file.GetContentFile(str(archive_path))
            logging.info("uncompressing database")
            uncompressed_file(archive_path, db_path)
            logging.info("migrate database")
            # call alembic upgrade
            import subprocess

            logging.info("Running alembic upgrade via subprocess...")
            subprocess.run(["alembic", "upgrade", "head"], check=True)
            logging.info("Subprocess finished")

    else:
        logging.info("Database not found")
