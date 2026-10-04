"""Enable the committed git hooks for this clone: `python scripts/install_hooks.py`."""

import subprocess
import sys


def main() -> int:
    subprocess.run(["git", "config", "core.hooksPath", ".githooks"], check=True)
    print("git hooks enabled (core.hooksPath=.githooks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
