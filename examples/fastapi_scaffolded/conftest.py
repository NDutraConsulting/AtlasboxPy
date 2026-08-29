"""Makes this directory itself the sys.path root for its tests — matching
how a real scaffolded project runs (its own directory as root, not nested
inside a larger package), so `main`, `controllers`, and `validator_gateways`
resolve as the bare top-level modules the CLI generates them to be."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
