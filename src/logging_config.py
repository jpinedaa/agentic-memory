"""Centralized logging configuration loader.

Loads logging config from a JSON file using Python's dictConfig schema.
Override the config file path via the LOG_CONFIG environment variable
or by passing a path directly to log_init().
"""

import json
import logging.config
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def log_init(log_config_path: str | None = None) -> None:
    """Initialize logging from a JSON config file.

    Resolution order for config path:
    1. log_config_path argument (if provided)
    2. LOG_CONFIG environment variable (if set)
    3. logging.json in the project root (default)
    """
    path = log_config_path or os.environ.get(
        "LOG_CONFIG", os.path.join(_PROJECT_ROOT, "logging.json")
    )
    with open(path) as f:
        config = json.load(f)
    logging.config.dictConfig(config)
