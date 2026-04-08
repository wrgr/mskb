"""Tests for src/link_concepts_to_papers: CLI argument parser and main entry point."""

import argparse

import pytest

from src.link_concepts_to_papers import build_arg_parser, main


def test_build_arg_parser_returns_parser() -> None:
    """build_arg_parser returns an ArgumentParser instance."""
    parser = build_arg_parser()
    assert isinstance(parser, argparse.ArgumentParser)


def test_build_arg_parser_defaults() -> None:
    """build_arg_parser default values match documented conventions."""
    parser = build_arg_parser()
    args = parser.parse_args([])
    assert args.config == "config.yaml"
    assert args.provider == "auto"
    assert args.refresh is False
    assert args.dry_run is False
    assert args.only == ""


def test_build_arg_parser_refresh_flag() -> None:
    """--refresh flag is correctly parsed as True."""
    parser = build_arg_parser()
    args = parser.parse_args(["--refresh"])
    assert args.refresh is True


def test_build_arg_parser_provider_choices() -> None:
    """--provider only accepts defined choices."""
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--provider", "invalid_provider"])


def test_main_missing_config_exits() -> None:
    """main returns a non-zero exit code when the config file does not exist."""
    result = main(["--config", "/nonexistent/path/config.yaml"])
    assert isinstance(result, int)
    assert result != 0
