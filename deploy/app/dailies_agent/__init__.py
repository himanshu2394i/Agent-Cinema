"""ADK loads this package as `dailies_agent`.

Cloud Run packaging may drop in same-named modules from the project root
(`shot_schema.py`, `vocab.py`, …) that use absolute imports like
`from vocab import …`. Put this directory on sys.path first so those imports
resolve to the bundled copies next to this file.
"""

import sys
from pathlib import Path

_pkg_dir = str(Path(__file__).resolve().parent)
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)

from . import agent  # noqa: F401
