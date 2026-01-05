"""
Convenience re-export of the Matomo API client.

This allows importing from the project root:
    from scripts.matomo import MatomoAPI

The actual implementation is in skills/matomo_query/scripts/matomo.py
"""

import sys
import importlib.util
from pathlib import Path

# Load modules directly to avoid relative import issues
_skills_path = Path(__file__).parent.parent / "skills" / "matomo_query" / "scripts"

# Load ui_mapping first (dependency)
_ui_mapping_path = _skills_path / "ui_mapping.py"
_ui_spec = importlib.util.spec_from_file_location("ui_mapping", _ui_mapping_path)
_ui_mapping = importlib.util.module_from_spec(_ui_spec)
sys.modules["ui_mapping"] = _ui_mapping
_ui_spec.loader.exec_module(_ui_mapping)

# Now load matomo module
_matomo_path = _skills_path / "matomo.py"
_matomo_spec = importlib.util.spec_from_file_location("matomo_module", _matomo_path)
_matomo = importlib.util.module_from_spec(_matomo_spec)

# Patch the relative import before loading
_matomo.__dict__["UI_MAPPING"] = _ui_mapping.UI_MAPPING
_matomo.__dict__["get_ui_url"] = _ui_mapping.get_ui_url
_matomo.__dict__["format_data_source"] = _ui_mapping.format_data_source

# Execute the module (skip the problematic import line)
import re
_source = _matomo_path.read_text()
_source = re.sub(r'^from \.ui_mapping import.*$', '# import handled by wrapper', _source, flags=re.MULTILINE)
exec(compile(_source, _matomo_path, 'exec'), _matomo.__dict__)

# Re-export
MatomoAPI = _matomo.MatomoAPI
MatomoError = _matomo.MatomoError
UI_MAPPING = _ui_mapping.UI_MAPPING
get_ui_url = _ui_mapping.get_ui_url
format_data_source = _ui_mapping.format_data_source

def load_api():
    """Load API client from .env in current directory or parents."""
    return MatomoAPI()

__all__ = [
    "MatomoAPI",
    "MatomoError",
    "UI_MAPPING",
    "get_ui_url",
    "format_data_source",
    "load_api",
]
