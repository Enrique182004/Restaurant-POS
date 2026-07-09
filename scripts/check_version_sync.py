#!/usr/bin/env python3
"""Verify the app version is consistent across its sources of truth.

Checks:
  1. package.json "version" == python-backend/releases.json first entry "version"
  2. releases.json is valid JSON (a non-empty list)
  3. every entry has "version", "date" and "changes" keys
  4. entries are sorted newest-first (semver-ish tuple comparison)

Usage:
  python scripts/check_version_sync.py \
      [--package-json PATH] [--releases-json PATH]

Paths default to the repo files (resolved relative to this script's parent
directory), so the script works from any cwd.
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PACKAGE_JSON = REPO_ROOT / "package.json"
DEFAULT_RELEASES_JSON = REPO_ROOT / "python-backend" / "releases.json"


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def version_tuple(version: str):
    """Convert 'X.Y.Z' (or similar dotted numeric string) to a comparable tuple."""
    if not re.fullmatch(r"\d+(\.\d+)*", version):
        fail(f"version {version!r} is not a dotted numeric version (expected X.Y.Z)")
    return tuple(int(part) for part in version.split("."))


def load_json(path: Path, label: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        fail(f"{label} not found at {path}")
    except json.JSONDecodeError as exc:
        fail(f"{label} at {path} is not valid JSON: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--package-json", type=Path, default=DEFAULT_PACKAGE_JSON)
    parser.add_argument("--releases-json", type=Path, default=DEFAULT_RELEASES_JSON)
    args = parser.parse_args()

    package = load_json(args.package_json, "package.json")
    releases = load_json(args.releases_json, "releases.json")

    pkg_version = package.get("version")
    if not isinstance(pkg_version, str):
        fail(f"{args.package_json} has no string \"version\" field")

    if not isinstance(releases, list) or not releases:
        fail(f"{args.releases_json} must be a non-empty JSON array of release entries")

    for index, entry in enumerate(releases):
        if not isinstance(entry, dict):
            fail(f"releases.json entry {index} is not an object")
        missing = [key for key in ("version", "date", "changes") if key not in entry]
        if missing:
            fail(
                f"releases.json entry {index} "
                f"(version={entry.get('version', '?')!r}) is missing keys: "
                + ", ".join(missing)
            )

    for index in range(len(releases) - 1):
        current = releases[index]["version"]
        following = releases[index + 1]["version"]
        if version_tuple(current) < version_tuple(following):
            fail(
                "releases.json is not sorted newest-first: entry "
                f"{index} ({current}) is older than entry {index + 1} ({following})"
            )

    rel_version = releases[0]["version"]
    if pkg_version != rel_version:
        fail(
            "version mismatch:\n"
            f"  package.json          -> {pkg_version}\n"
            f"  releases.json (first) -> {rel_version}\n"
            "Update both files to the same version (see scripts/release.sh)."
        )

    print(f"OK: version {pkg_version} is in sync across package.json and releases.json")


if __name__ == "__main__":
    main()
