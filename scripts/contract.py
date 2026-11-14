"""Run the contract exporter without installing the package: `python scripts/contract.py [--check|--watch|--web]`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from earthtrend.api.contract import main  # noqa: E402

raise SystemExit(main())
