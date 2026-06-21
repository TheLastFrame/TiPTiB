from __future__ import annotations

import json
import tomllib
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

SOURCE_URL = "https://github.com/TheLastFrame/TiPTiB"
RELEASES_URL = f"{SOURCE_URL}/releases"
DEFAULT_VERSION = "0.0.0"
VERSION_FILE = Path(__file__).with_name("VERSION.json")
PYPROJECT_FILE = Path(__file__).resolve().parent.parent / "pyproject.toml"


@dataclass(frozen=True)
class VersionInfo:
    version: str
    commit: str = ""
    build_date: str = ""
    source_url: str = SOURCE_URL
    releases_url: str = RELEASES_URL

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _clean_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _package_version() -> str:
    try:
        return metadata.version("tiptib")
    except metadata.PackageNotFoundError:
        return ""


def _pyproject_version(path: Path = PYPROJECT_FILE) -> str:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ""
    project = data.get("project", {})
    if not isinstance(project, dict):
        return ""
    return _clean_text(project.get("version"))


def fallback_version() -> str:
    return _pyproject_version() or _package_version() or DEFAULT_VERSION


def load_version_info(path: Path = VERSION_FILE) -> VersionInfo:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}

    return VersionInfo(
        version=_clean_text(data.get("version")) or fallback_version(),
        commit=_clean_text(data.get("commit")),
        build_date=_clean_text(data.get("build_date")),
        source_url=_clean_text(data.get("source_url")) or SOURCE_URL,
        releases_url=_clean_text(data.get("releases_url")) or RELEASES_URL,
    )
