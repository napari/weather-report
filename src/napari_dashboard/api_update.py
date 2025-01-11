"""
This module provides a command line interface to update the database and upload it to Google Drive.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from napari_dashboard.db_update.__main__ import main as db_update_main
from napari_dashboard.gdrive_util import (
    COMPRESSED_DB,
    DB_PATH,
    compress_file,
    fetch_database,
    upload_db_dump,
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

    fetch_database(args.db_path)
    print("Database fetched.")
    updated = db_update_main([str(args.db_path)])
    print(f"Database updated: {updated}")
    if updated:
        print("Uploading database")
        compress_file(args.db_path, COMPRESSED_DB)
        upload_db_dump(COMPRESSED_DB)


if __name__ == "__main__":
    main()
