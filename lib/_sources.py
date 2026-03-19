"""
PRIVATE MODULE - Do not import directly.

Use lib.query for all queries (provides logging):
    from lib.query import execute_query, execute_metabase_query, execute_matomo_query

This module provides the underlying client factories for internal use only.
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


def _substitute_env_vars(value: Any, strict: bool = False) -> Any:
    """
    Recursively substitute ${env.VAR} patterns with environment values.

    Args:
        value: Value to process
        strict: If True, raise error for missing env vars. If False, keep original string.
    """
    if isinstance(value, str):
        pattern = r"\$\{env\.([^}]+)\}"

        def replacer(match):
            var_name = match.group(1)
            env_value = os.environ.get(var_name)
            if env_value is None:
                if strict:
                    raise ValueError(f"Environment variable {var_name} not set")
                return match.group(0)  # Keep original ${env.VAR} string
            return env_value

        return re.sub(pattern, replacer, value)

    elif isinstance(value, dict):
        return {k: _substitute_env_vars(v, strict=strict) for k, v in value.items()}

    elif isinstance(value, list):
        return [_substitute_env_vars(item, strict=strict) for item in value]

    return value


def load_config(force_reload: bool = False) -> dict:
    """Load and parse sources.yaml, substituting environment variables."""
    global _config

    if _config is not None and not force_reload:
        return _config

    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Config file not found: {CONFIG_PATH}\nCopy config/sources.yaml.example to config/sources.yaml"
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
        raise ValueError(f"Unknown {source_type} instance: {instance}. Available: {', '.join(available)}")

    # Re-substitute with strict mode to catch missing env vars for this specific instance
    instance_config = source_config[instance]
    return _substitute_env_vars(instance_config, strict=True)


def get_metabase(instance: str | None = None, database_id: int | None = None):
    """
    Get a configured MetabaseAPI client.

    Args:
        instance: Instance name ("stats", "datalake"), or None for default
        database_id: Override the default database ID for queries

    Returns:
        Configured MetabaseAPI instance
    """
    from ._metabase import MetabaseAPI

    config = get_source_config("metabase", instance)
    instance_name = instance or get_default_instance("metabase") or "stats"

    return MetabaseAPI(
        url=config["url"],
        api_key=config["api_key"],
        database_id=database_id,
        instance=instance_name,
    )


def get_matomo(instance: str | None = None):
    """
    Get a configured MatomoAPI client.

    Args:
        instance: Instance name, or None for default

    Returns:
        Configured MatomoAPI instance
    """
    from ._matomo import MatomoAPI

    config = get_source_config("matomo", instance)
    instance_name = instance or get_default_instance("matomo") or "inclusion"

    # MatomoAPI expects hostname only (without https://)
    url = config["url"]
    if url.startswith("https://"):
        url = url[8:]
    elif url.startswith("http://"):
        url = url[7:]

    return MatomoAPI(
        url=url,
        token=config["token"],
        instance=instance_name,
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


def get_tag_manager_sites() -> list[dict]:
    """Get tag manager site configurations from sources.yaml."""
    config = load_config()
    return config.get("tag_manager", {}).get("sites", [])
