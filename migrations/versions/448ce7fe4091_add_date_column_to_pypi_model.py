"""Add date column to PyPi model

Revision ID: 448ce7fe4091
Revises:
Create Date: 2024-11-24 20:22:17.132344

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "448ce7fe4091"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Read the existing schema using PRAGMA

    op.add_column(
        "pypi_downloads",
        sa.Column(
            "date", sa.Date(), nullable=False, server_default="1970-01-01"
        ),
    )

    # Populate the `date` column based on `timestamp`
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE pypi_downloads
            SET date = DATE(timestamp)
            """
        )
    )

    result = conn.execute(
        sa.text("PRAGMA table_info('pypi_downloads')")
    ).fetchall()

    # Construct the new table schema dynamically
    columns = []
    columns_names = []
    for col in result:
        col_name, col_type, notnull, default, pk = (
            col[1],
            col[2],
            col[3],
            col[4],
            col[5],
        )
        if col_name == "date":
            continue
        column_def = f"{col_name} {col_type}"
        if pk:
            column_def += " PRIMARY KEY"
        if notnull:
            column_def += " NOT NULL"
        if default is not None:
            column_def += f" DEFAULT {default}"
        columns.append(column_def)
        columns_names.append(col_name)

    # find the `timestamp` column index
    timestamp_index = [col[1] for col in result].index("timestamp")

    # Add the new `date` column definition
    columns.insert(timestamp_index + 1, "date DATE NOT NULL")
    columns_names.insert(timestamp_index + 1, "date")

    # Create new table SQL
    create_table_sql = f"""
    CREATE TABLE pypi_downloads_new (
        {", ".join(columns)}
    )
    """

    columns_order = ", ".join(columns_names)
    # Execute the table recreation
    op.execute(create_table_sql)
    op.execute(
        f"""
        INSERT INTO pypi_downloads_new SELECT {columns_order} FROM pypi_downloads
        """
    )

    # Replace the old table with the new one
    op.drop_table("pypi_downloads")
    op.execute("ALTER TABLE pypi_downloads_new RENAME TO pypi_downloads")


def downgrade() -> None:
    op.drop_column("pypi_downloads", "date")
