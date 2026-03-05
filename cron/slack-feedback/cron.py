#!/usr/bin/env python3
"""Cron wrapper: weekly Slack feedback DMs."""

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "slack_feedback.py"

sys.exit(subprocess.call([sys.executable, str(SCRIPT)]))
