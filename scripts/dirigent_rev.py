"""Print the dirigent commit uv.lock resolved dirigent-server to.

The web UI bundle is gitignored in dirigent, so a dirigent-server installed from git carries
no static/ directory. The image builds the bundle itself, and it has to build it from the very
commit the lock installed, which is the one this prints.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}")


def dirigent_rev(lock: Path) -> str:
    """Return the commit sha the lock pins dirigent-server to."""
    data = tomllib.loads(lock.read_text())
    for package in data.get("package", []):
        if package.get("name") != "dirigent-server":
            continue
        source = package.get("source", {}).get("git", "")
        _, _, rev = source.partition("#")
        if SHA.fullmatch(rev):
            return rev
        raise SystemExit(f"dirigent-server has no resolved git rev in the lock: {source!r}")
    raise SystemExit("dirigent-server is not in the lock")


def main() -> int:
    """Print the rev for the lock named on the command line, or ./uv.lock."""
    lock = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("uv.lock")
    print(dirigent_rev(lock))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
