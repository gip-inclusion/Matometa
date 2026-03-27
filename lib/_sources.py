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

from ._matomo import MatomoAPI
from ._metabase import MetabaseAPI

# Config file location
CONFIG_PATH = Path(__file__).parent.parent / "config" / "sources.yaml"

# Cached config
config_cache: dict | None = None


def substitute_env_vars(value: Any, strict: bool = False) -> Any:
    """Recursively substitute ${env.VAR} patterns with environment values."""
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
        return {k: substitute_env_vars(v, strict=strict) for k, v in value.items()}

    elif isinstance(value, list):
        return [substitute_env_vars(item, strict=strict) for item in value]

    return value


def load_config(force_reload: bool = False) -> dict:
    global config_cache

    if config_cache is not None and not force_reload:
        return config_cache

    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Config file not found: {CONFIG_PATH}\nCopy config/sources.yaml.example to config/sources.yaml"
        )

    with open(CONFIG_PATH) as f:
        raw_config = yaml.safe_load(f)

    config_cache = substitute_env_vars(raw_config)
    return config_cache


def get_source_config(source_type: str, instance: str | None = None) -> dict:
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
    return substitute_env_vars(instance_config, strict=True)


def get_metabase(instance: str | None = None, database_id: int | None = None):
    config = get_source_config("metabase", instance)
    instance_name = instance or get_default_instance("metabase") or "stats"

    return MetabaseAPI(
        url=config["url"],
        api_key=config["api_key"],
        database_id=database_id,
        instance=instance_name,
    )


def get_matomo(instance: str | None = None):
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
    config = load_config()

    if source_type not in config:
        return []

    return [k for k in config[source_type].keys() if not k.startswith("_")]


def get_default_instance(source_type: str) -> str | None:
    config = load_config()

    if source_type not in config:
        return None

    return config[source_type].get("_default")
