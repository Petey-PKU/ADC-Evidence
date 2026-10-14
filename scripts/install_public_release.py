"""Download and install the database and retrieval index from a public release.

The release archive is an external artifact. It is deliberately kept out of
the Git history, while this installer makes a fresh checkout usable without
running the source-ingestion pipeline first.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

try:  # Works both as ``python scripts/...`` and ``python -m scripts...``.
    from scripts.verify_public_release import verify_release
except ModuleNotFoundError:  # pragma: no cover - direct script invocation path
    from verify_public_release import verify_release


REPOSITORY = "Petey-PKU/ADC-Evidence"
DEFAULT_TAG = "v0.7.0"
DEFAULT_ASSET = "adc-public-2026-09-30.zip"


def release_asset_url(*, tag: str, asset: str, repository: str = REPOSITORY) -> str:
    """Return the stable GitHub Releases download URL for one asset."""
    if not tag or not asset or "/" in asset or "\\" in asset:
        raise ValueError("tag and asset must be non-empty; asset must be a filename")
    encoded_tag = urllib.parse.quote(tag, safe="")
    encoded_asset = urllib.parse.quote(asset, safe="")
    return f"https://github.com/{repository}/releases/download/{encoded_tag}/{encoded_asset}"


def _member_path(root: Path, member: str) -> Path:
    """Resolve a ZIP member below root and reject traversal or absolute paths."""
    pure = PurePosixPath(member)
    windows = PureWindowsPath(member)
    if (
        pure.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or ".." in pure.parts
        or "\\" in member
        or not member
    ):
        raise ValueError(f"unsafe release member path: {member!r}")
    resolved = (root / Path(*pure.parts)).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"release member escapes destination: {member!r}")
    return resolved


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ADC-Evidence-public-release-installer"},
    )
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)


def _runtime_members(archive: zipfile.ZipFile) -> tuple[str, list[str]]:
    manifest = json.loads(archive.read("RELEASE_MANIFEST.json"))
    application = manifest.get("application", {})
    database = str(application.get("database_path", ""))
    index = str(application.get("index_path", ""))
    if (
        not database
        or not index
        or not database.startswith("data/processed/")
        or not index.startswith("artifacts/vector_index/")
        or database not in archive.namelist()
    ):
        raise ValueError("release manifest does not describe a usable database and index")
    index_members = sorted(
        name for name in archive.namelist() if name.startswith(index.rstrip("/") + "/")
    )
    if not index_members:
        raise ValueError("release archive does not contain the retrieval index")
    return database, [database, *index_members]


def install_snapshot(*, archive_path: Path, destination: Path, force: bool = False) -> dict[str, object]:
    """Verify an archive and install only its database and retrieval index."""
    archive_path = archive_path.resolve()
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    verification = verify_release(archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        database, members = _runtime_members(archive)
        outputs = [_member_path(destination, member) for member in members]
        existing = [path for path in outputs if path.exists()]
        if existing and not force:
            names = ", ".join(str(path.relative_to(destination)) for path in existing)
            raise FileExistsError(
                f"release files already exist: {names}; use --force to replace them"
            )
        with tempfile.TemporaryDirectory(prefix="adc-release-", dir=destination) as temp_name:
            temp_root = Path(temp_name)
            staged: list[tuple[Path, Path]] = []
            for member in members:
                staged_path = _member_path(temp_root, member)
                staged_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, staged_path.open("wb") as target:
                    shutil.copyfileobj(source, target)
                staged.append((staged_path, _member_path(destination, member)))
            for staged_path, output in staged:
                output.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged_path, output)
    return {
        "status": "installed",
        "database": database,
        "files_installed": len(members),
        "destination": str(destination),
        "verification": verification,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--archive", type=Path, help="Use an already downloaded release archive.")
    source.add_argument("--tag", default=DEFAULT_TAG, help=f"GitHub release tag (default: {DEFAULT_TAG}).")
    parser.add_argument("--asset", default=DEFAULT_ASSET, help=f"Release asset filename (default: {DEFAULT_ASSET}).")
    parser.add_argument("--repository", default=REPOSITORY, help=f"GitHub repository (default: {REPOSITORY}).")
    parser.add_argument("--destination", type=Path, default=Path.cwd(), help="Checkout directory to receive data and index.")
    parser.add_argument("--force", action="store_true", help="Replace an existing database or index file.")
    parser.add_argument("--keep-archive", action="store_true", help="Keep a downloaded archive under the destination.")
    args = parser.parse_args()

    destination = args.destination.resolve()
    temporary_archive: Path | None = None
    archive = args.archive.resolve() if args.archive else None
    if archive is None:
        destination.mkdir(parents=True, exist_ok=True)
        temporary_archive = destination / f".{args.asset}.download"
        url = release_asset_url(tag=args.tag, asset=args.asset, repository=args.repository)
        print(f"Downloading {url}")
        try:
            _download(url, temporary_archive)
            archive = temporary_archive
            result = install_snapshot(archive_path=archive, destination=destination, force=args.force)
        finally:
            if temporary_archive is not None and temporary_archive.exists() and not args.keep_archive:
                temporary_archive.unlink()
    else:
        result = install_snapshot(archive_path=archive, destination=destination, force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
