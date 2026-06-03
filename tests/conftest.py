"""Ensure tests can `from src...` regardless of pytest invocation cwd.

The CI runs `pytest tests/` from the repo root, but there is no
`pyproject.toml`/`setup.py` registering `src` as an importable package,
so we prepend the repo root to sys.path here.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
