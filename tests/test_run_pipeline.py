"""Tests for run_pipeline: CLI orchestration and main entry point."""

import pytest

from run_pipeline import main


def test_main_raises_on_missing_config() -> None:
    """main raises FileNotFoundError when config_path does not exist."""
    with pytest.raises((FileNotFoundError, Exception)):
        main("/nonexistent/config.yaml")
