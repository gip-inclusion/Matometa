#!/usr/bin/env python3
"""Cron wrapper: incremental refresh of Notion research corpus."""

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "refresh_research.py"

sys.exit(subprocess.call([sys.executable, str(SCRIPT)]))
