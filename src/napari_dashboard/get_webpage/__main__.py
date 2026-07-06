from __future__ import annotations

import argparse
import datetime
import typing
from pathlib import Path

from napari_dashboard.get_webpage import generate_webpage

if typing.TYPE_CHECKING:
    from collections.abc import Sequence


def main(args: Sequence[str] | None = None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "directory", help="Directory to save the webpage", type=Path
    )
    parser.add_argument("db_path", help="Path to the database", type=Path)
    parser.add_argument("--no-excel-dump", action="store_true")
    parser.add_argument(
        "--since-date",
        type=lambda s: datetime.datetime.strptime(s, "%Y-%m-%d"),
        default=None,
        help="Start date for statistics (default: 180 days ago)",
    )
    args = parser.parse_args(args)
    if args.since_date is None:
        args.since_date = datetime.datetime.now() - datetime.timedelta(days=180)

    generate_webpage(
        target_path=args.directory,
        db_path=args.db_path,
        since_date=args.since_date,
        dump_excel=not args.no_excel_dump,
    )


if __name__ == "__main__":
    main()
