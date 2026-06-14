from __future__ import annotations

from app.core.security import DEMO_PASSPHRASE, redact, verify_unlock


def test_demo_passphrase_accepted_in_development():
    assert verify_unlock(DEMO_PASSPHRASE) is True
    assert verify_unlock("wrong") is False


def test_redact_masks_secret_like_keys():
    out = redact({"api_key": "abc", "TOKEN": "xyz", "name": "ok", "empty_secret": ""})
    assert out["api_key"] == "***redacted***"
    assert out["TOKEN"] == "***redacted***"
    assert out["name"] == "ok"
    assert out["empty_secret"] == ""  # empty values not masked
