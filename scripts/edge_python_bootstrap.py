from __future__ import annotations

import runpy
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
for import_root in (REPO_ROOT / "src", REPO_ROOT / ".venv" / "Lib" / "site-packages"):
    import_path = str(import_root)
    if import_path not in sys.path:
        sys.path.insert(0, import_path)


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--script":
        script = Path(sys.argv[2]).resolve()
        sys.argv = [str(script), *sys.argv[3:]]
        runpy.run_path(str(script), run_name="__main__")
        return 0

    from csbaoyan_daily.cli import main as cli_main

    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
