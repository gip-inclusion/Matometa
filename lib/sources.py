"""
Load data source configuration and return configured API clients.

Usage:
    from lib.sources import get_metabase, get_matomo, load_config

    api = get_metabase()           # default instance (stats)
    api = get_metabase("datalake") # explicit instance

    matomo = get_matomo()          # default instance (inclusion)
"""

import os
import re
from pathlib import Path
from typing import Any

import yaml


# Config file location
CONFIG_PATH = Path(__file__).parent.parent / "config" / "sources.yaml"

# Cached config
_config: dict | None = None


def _substitute_env_vars(value: Any) -> Any:
    """Recursively substitute ${env.VAR} patterns with environment values."""
    if isinstance(value, str):
        pattern = r'\$\{env\.([^}]+)\}'

        def replacer(match):
            var_name = match.group(1)
            env_value = os.environ.get(var_name)
            if env_value is None:
                raise ValueError(f"Environment variable {var_name} not set")
            return env_value

        return re.sub(pattern, replacer, value)

    elif isinstance(value, dict):
        return {k: _substitute_env_vars(v) for k, v in value.items()}

    elif isinstance(value, list):
        return [_substitute_env_vars(item) for item in value]

    return value


def load_config(force_reload: bool = False) -> dict:
    """Load and parse sources.yaml, substituting environment variables."""
    global _config

    if _config is not None and not force_reload:
        return _config

    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Config file not found: {CONFIG_PATH}\n"
            f"Copy config/sources.yaml.example to config/sources.yaml"
        )

    with open(CONFIG_PATH) as f:
        raw_config = yaml.safe_load(f)

    _config = _substitute_env_vars(raw_config)
    return _config


def get_source_config(source_type: str, instance: str | None = None) -> dict:
    """
    Get configuration for a specific source instance.

    Args:
        source_type: "metabase" or "matomo"
        instance: Instance name, or None for default

    Returns:
        Configuration dict for the instance
    """
    config = load_config()

    if source_type not in config:
        raise ValueError(f"Unknown source type: {source_type}")

    source_config = config[source_type]

    # Resolve instance name
    if instance is None:
        instance = source_config.get("_default")
        if instance is None:
            raise ValueError(f"No default instance for {source_type}")

    if instance not in source_config:
        available = [k for k in source_config.keys() if not k.startswith("_")]
        raise ValueError(
            f"Unknown {source_type} instance: {instance}. "
            f"Available: {', '.join(available)}"
        )

    return source_config[instance]


def get_metabase(instance: str | None = None):
    """
    Get a configured MetabaseAPI client.

    Args:
        instance: Instance name ("stats", "datalake"), or None for default

    Returns:
        Configured MetabaseAPI instance
    """
    from skills.metabase_query.scripts.metabase import MetabaseAPI

    config = get_source_config("metabase", instance)

    return MetabaseAPI(
        url=config["url"],
        api_key=config["api_key"],
    )


def get_matomo(instance: str | None = None):
    """
    Get a configured MatomoAPI client.

    Args:
        instance: Instance name, or None for default

    Returns:
        Configured MatomoAPI instance
    """
    from skills.matomo_query.scripts.matomo import MatomoAPI

    config = get_source_config("matomo", instance)

    return MatomoAPI(
        base_url=config["url"],
        token=config["token"],
    )


def list_instances(source_type: str) -> list[str]:
    """List available instances for a source type."""
    config = load_config()

    if source_type not in config:
        return []

    return [k for k in config[source_type].keys() if not k.startswith("_")]


def get_default_instance(source_type: str) -> str | None:
    """Get the default instance name for a source type."""
    config = load_config()

    if source_type not in config:
        return None

    return config[source_type].get("_default")
