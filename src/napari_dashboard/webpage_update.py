"""
Module to update the webpage with the latest data from the database.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from napari_dashboard.gdrive_util import DB_PATH, fetch_database
from napari_dashboard.get_webpage.__main__ import main as get_webpage_main


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
    logging.basicConfig(level=logging.INFO)

    fetch_database(args.db_path)
    logging.info("Database fetched.")
    get_webpage_main(["webpage", str(args.db_path), "--no-excel-dump"])


if __name__ == "__main__":
    main()
