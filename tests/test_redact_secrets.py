"""Tests for utils.redact_secrets — prevents API keys leaking into pipeline logs."""

from src.utils import redact_secrets


def test_redacts_gemini_key_in_url() -> None:
    msg = (
        "Max retries exceeded with url: /v1beta/models/gemini-2.5-flash:"
        "generateContent?key=AIzaSyAxs-3K7wPQ2m8Ddkisyy7JQTadUxMMSDY"
    )
    out = redact_secrets(msg)
    assert "AIzaSy" not in out
    assert "key=<redacted>" in out


def test_redacts_multiple_secret_params() -> None:
    msg = "error at https://api.example.com/?api_key=abc123&access_token=xyz789"
    out = redact_secrets(msg)
    assert "abc123" not in out
    assert "xyz789" not in out
    assert "api_key=<redacted>" in out
    assert "access_token=<redacted>" in out


def test_leaves_non_secret_params_alone() -> None:
    msg = "fetched page?limit=50&cursor=abc"
    assert redact_secrets(msg) == msg


def test_empty_input() -> None:
    assert redact_secrets("") == ""
