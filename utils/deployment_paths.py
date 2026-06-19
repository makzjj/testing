"""Deployment-safe paths for bundled resources and writable runtime data."""

from __future__ import annotations

from pathlib import Path
import shutil
import sys


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_source_root() -> Path:
    return Path(__file__).resolve().parents[1]


def get_bundle_root() -> Path:
    if is_frozen():
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            return Path(bundle_root).resolve()
        return Path(sys.executable).resolve().parent
    return get_source_root()


def get_runtime_root() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return get_source_root()


def get_runtime_data_root() -> Path:
    return get_runtime_root() / "data"


def get_runtime_logs_dir() -> Path:
    return get_runtime_data_root() / "logs"


def get_runtime_exports_dir() -> Path:
    return get_runtime_data_root() / "exports"


def get_runtime_config_dir() -> Path:
    return get_runtime_data_root() / "config"


def get_runtime_project_configs_dir() -> Path:
    return get_runtime_config_dir() / "project_configs"


def get_bundle_resource_path(*parts: str) -> Path:
    return get_bundle_root().joinpath(*parts)


def get_bundled_project_configs_dir() -> Path:
    return get_bundle_root() / "project_configs"


def ensure_runtime_directories() -> dict[str, Path]:
    """Create the writable runtime folder layout beside the executable."""
    dirs = {
        "data": get_runtime_data_root(),
        "logs": get_runtime_logs_dir(),
        "exports": get_runtime_exports_dir(),
        "config": get_runtime_config_dir(),
        "project_configs": get_runtime_project_configs_dir(),
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def seed_directory_if_empty(source_dir: Path, target_dir: Path) -> None:
    """Copy a bundled directory into a writable runtime directory once."""
    if target_dir.exists() and any(target_dir.iterdir()):
        return
    if not source_dir.exists():
        return

    target_dir.mkdir(parents=True, exist_ok=True)
    for source_path in source_dir.iterdir():
        destination = target_dir / source_path.name
        if source_path.is_dir():
            if not destination.exists():
                shutil.copytree(source_path, destination)
        elif source_path.is_file():
            shutil.copy2(source_path, destination)

