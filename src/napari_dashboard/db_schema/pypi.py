"""
Database schema for pypi_downloads table

Schema:
ibis.Schema {
  timestamp     !timestamp('UTC')
  country_code  string
  url           !string
  project       !string
  file          !struct<filename: string, project: string, version: string, type: string>
  details       struct<installer: struct<name: string, version: string>, python: string, implementation: struct<name: string, version: string>, distro: struct<name: string, version: string, id: string, libc: struct<lib: string, version: string>>, system: struct<name: string, release: string>, cpu: string, openssl_version: string, setuptools_version: string, rustc_version: string, ci: boolean>
  tls_protocol  string
  tls_cipher    string
}
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    PrimaryKeyConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Boolean, Date, DateTime, String

from napari_dashboard.db_schema.base import Base


class PyPi(Base):
    __tablename__ = "pypi_downloads"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    date: Mapped[date] = mapped_column(Date)
    country_code: Mapped[Optional[str]] = mapped_column(String)
    project: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String)
    python_version: Mapped[str] = mapped_column(String)
    system_name: Mapped[str] = mapped_column(String)
    system_release: Mapped[str] = mapped_column(String)
    distro_name: Mapped[str] = mapped_column(String)
    distro_version: Mapped[str] = mapped_column(String)
    wheel: Mapped[bool] = mapped_column(Boolean)
    ci_install: Mapped[bool] = mapped_column(Boolean)


class PePyDownloadStat(Base):
    __tablename__ = "pepy_download_stats"
    __table_args__ = (PrimaryKeyConstraint("name", "version", "date"),)

    name: Mapped[str] = Column(String)
    downloads: Mapped[int] = Column(Integer)
    version: Mapped[str] = Column(String)
    date: Mapped[Date] = Column(Date)


class PePyTotalDownloads(Base):
    __tablename__ = "pepy_total_downloads"

    name: Mapped[str] = Column(String, primary_key=True)
    downloads: Mapped[int] = Column(Integer)


class PyPiStatsDownloads(Base):
    __tablename__ = "pypi_stats_downloads"
    __table_args__ = (PrimaryKeyConstraint("name", "date"),)

    name: Mapped[str] = Column(String)
    date: Mapped[Date] = Column(Date)
    downloads: Mapped[int] = Column(Integer)
    downloads_with_mirror: Mapped[int] = Column(Integer)

    per_os = relationship("PyPiDownloadPerOS", back_populates="package")
    per_python_version = relationship(
        "PyPiDownloadPerPythonVersion", back_populates="package"
    )


class PackageRelease(Base):
    __tablename__ = "pypi_package_releases"
    __table_args__ = (PrimaryKeyConstraint("name", "version"),)

    name: Mapped[str] = Column(String)
    version: Mapped[str] = Column(String)
    release_date: Mapped[Date] = Column(Date)


class OperatingSystem(Base):
    __tablename__ = "pypi_operating_systems"

    name: Mapped[str] = Column(String, primary_key=True)
    packages: Mapped["PyPiDownloadPerOS"] = relationship(
        "PyPiDownloadPerOS", back_populates="os"
    )


class PythonVersion(Base):
    __tablename__ = "pypi_python_versions"

    version: Mapped[str] = Column(String, primary_key=True)
    packages: Mapped["PyPiDownloadPerPythonVersion"] = relationship(
        "PyPiDownloadPerPythonVersion", back_populates="python_version"
    )


class PyPiDownloadPerOS(Base):
    __tablename__ = "pypi_downloads_per_os"
    __table_args__ = (
        PrimaryKeyConstraint("os_name", "package_name", "package_date"),
        ForeignKeyConstraint(
            ["package_name", "package_date"],
            ["pypi_stats_downloads.name", "pypi_stats_downloads.date"],
        ),
    )

    os_name: Mapped[str] = Column(
        String, ForeignKey("pypi_operating_systems.name")
    )
    os = relationship(OperatingSystem, back_populates="packages")
    package_name: Mapped[str] = Column(String)
    package_date: Mapped[Date] = Column(Date)
    downloads: Mapped[int] = Column(Integer)
    package: Mapped[PyPiStatsDownloads] = relationship(
        PyPiStatsDownloads, back_populates="per_os"
    )


class PyPiDownloadPerPythonVersion(Base):
    __tablename__ = "pypi_downloads_per_python_version"
    __table_args__ = (
        PrimaryKeyConstraint(
            "python_version_name", "package_name", "package_date"
        ),
        ForeignKeyConstraint(
            ["package_name", "package_date"],
            ["pypi_stats_downloads.name", "pypi_stats_downloads.date"],
        ),
    )

    python_version_name: Mapped[str] = Column(
        String, ForeignKey("pypi_python_versions.version")
    )
    python_version = relationship(PythonVersion, back_populates="packages")
    package_name: Mapped[str] = Column(String)
    package_date: Mapped[Date] = Column(Date)
    downloads: Mapped[int] = Column(Integer)

    package: Mapped[PyPiStatsDownloads] = relationship(
        PyPiStatsDownloads, back_populates="per_python_version"
    )
