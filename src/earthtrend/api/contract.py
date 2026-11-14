"""Export the HTTP contract (OpenAPI) that the web app is generated from.

    python -m earthtrend.api.contract            # write contract/openapi.json
    python -m earthtrend.api.contract --check    # fail if the file is stale
    python -m earthtrend.api.contract --watch    # rewrite on every API change
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "contract" / "openapi.json"
WATCHED = Path(__file__).resolve().parent
WEB = ROOT / "web"


def build_schema() -> dict[str, Any]:
    from earthtrend.api.main import create_app

    return create_app().openapi_schema.to_schema()


def render(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def write(path: Path | None = None) -> bool:
    """Write the contract; return True when the file changed."""
    path = path or CONTRACT
    text = render(build_schema())
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return True


def check(path: Path | None = None) -> bool:
    """Return True when the committed contract matches the code."""
    path = path or CONTRACT
    return path.exists() and path.read_text(encoding="utf-8") == render(build_schema())


def _regenerate_web() -> None:
    npm = shutil.which("npm")
    if npm is None or not (WEB / "node_modules").exists():
        print("contract: skip web types (run `npm install` in web/)", file=sys.stderr)
        return
    subprocess.run([npm, "--prefix", str(WEB), "run", "--silent", "api:gen"], check=False)


def watch() -> None:  # pragma: no cover - long-running dev loop
    import importlib

    from watchfiles import watch as watch_files

    def refresh() -> None:
        for name in [m for m in sys.modules if m.startswith("earthtrend.api") and m != __name__]:
            del sys.modules[name]
        importlib.invalidate_caches()
        try:
            changed = write()
        except Exception as error:  # keep watching through broken edits
            print(f"contract: schema build failed: {error}", file=sys.stderr)
            return
        if changed:
            print(f"contract: updated {CONTRACT}", flush=True)
            _regenerate_web()

    refresh()
    print(f"contract: watching {WATCHED}", flush=True)
    for _ in watch_files(WATCHED, watch_filter=lambda _, p: p.endswith(".py")):
        refresh()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="exit 1 if contract/openapi.json is stale")
    mode.add_argument("--watch", action="store_true", help="regenerate on every change under api/")
    parser.add_argument("--web", action="store_true", help="also regenerate web TypeScript types")
    args = parser.parse_args(argv)

    if args.watch:  # pragma: no cover
        watch()
        return 0
    if args.check:
        if check():
            return 0
        print(
            "contract/openapi.json is out of date with the API.\n"
            "Run `python scripts/contract.py --web` (or `make contract`) and commit the result.",
            file=sys.stderr,
        )
        return 1
    changed = write()
    print(f"contract: {'updated' if changed else 'unchanged'} {CONTRACT}")
    if args.web:
        _regenerate_web()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
