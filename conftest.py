from __future__ import annotations
import sys
from pathlib import Path

# Ensure project root is importable when pytest picks a different rootdir
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

