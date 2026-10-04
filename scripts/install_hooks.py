"""Enable the committed git hooks for this clone: `python scripts/install_hooks.py`."""

import subprocess
import sys
from pathlib import Path


def main() -> int:
    subprocess.run(["git", "config", "core.hooksPath", ".githooks"], check=True)
    for hook in Path(".githooks").iterdir():
        hook.chmod(hook.stat().st_mode | 0o111)  # git ignores hooks without the exec bit
    print("git hooks enabled (core.hooksPath=.githooks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
