#!/usr/bin/env bash
# Release helper: bumps the version everywhere it lives, then prints the
# git commands to finish the release. It never commits, tags or pushes.
#
# Usage:
#   bash scripts/release.sh <version> "<change 1>" ["<change 2>" ...]
#
# Example:
#   bash scripts/release.sh 2.1.0 "Fixed the thing" "Added the other thing"
#
# For testing, REPO_ROOT can be overridden to point at a directory that
# contains copies of package.json and python-backend/releases.json:
#   REPO_ROOT=/tmp/sandbox bash scripts/release.sh 9.9.9 "test change"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(dirname "$SCRIPT_DIR")}"
PACKAGE_JSON="$REPO_ROOT/package.json"
RELEASES_JSON="$REPO_ROOT/python-backend/releases.json"

usage() {
    echo "Usage: bash scripts/release.sh <version> \"<change 1>\" [\"<change 2>\" ...]" >&2
    exit 1
}

[ "$#" -ge 2 ] || usage

VERSION="$1"
shift

if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "ERROR: version '$VERSION' is not in X.Y.Z format" >&2
    exit 1
fi

[ -f "$PACKAGE_JSON" ] || { echo "ERROR: $PACKAGE_JSON not found" >&2; exit 1; }
[ -f "$RELEASES_JSON" ] || { echo "ERROR: $RELEASES_JSON not found" >&2; exit 1; }

RELEASE_VERSION="$VERSION" PACKAGE_JSON="$PACKAGE_JSON" RELEASES_JSON="$RELEASES_JSON" \
python3 - "$@" <<'PYEOF'
import datetime
import json
import os
import sys

version = os.environ["RELEASE_VERSION"]
package_path = os.environ["PACKAGE_JSON"]
releases_path = os.environ["RELEASES_JSON"]
changes = sys.argv[1:]

with open(package_path, encoding="utf-8") as f:
    package = json.load(f)
package["version"] = version
with open(package_path, "w", encoding="utf-8") as f:
    json.dump(package, f, indent=2, ensure_ascii=False)
    f.write("\n")

with open(releases_path, encoding="utf-8") as f:
    releases = json.load(f)
releases.insert(0, {
    "version": version,
    "date": datetime.date.today().isoformat(),
    "changes": changes,
})
with open(releases_path, "w", encoding="utf-8") as f:
    json.dump(releases, f, indent=2, ensure_ascii=False)
    f.write("\n")

print(f"Updated {package_path} -> {version}")
print(f"Prepended {version} entry to {releases_path}")
PYEOF

python3 "$SCRIPT_DIR/check_version_sync.py" \
    --package-json "$PACKAGE_JSON" \
    --releases-json "$RELEASES_JSON"

cat <<EOF

Version bumped to $VERSION. Review the changes, then run:

  git add package.json python-backend/releases.json
  git commit -m "chore: release v$VERSION"
  git tag v$VERSION
  git push origin main v$VERSION
EOF
