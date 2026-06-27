"""Tests for the Sentry config wrapper (iter34)."""
import importlib
import logging
import os

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("SENTRY_DSN", "SENTRY_ENV", "SENTRY_RELEASE",
              "SENTRY_TRACES_SAMPLE_RATE"):
        monkeypatch.delenv(k, raising=False)


def test_init_returns_false_when_dsn_missing(caplog):
    import sentry_config
    importlib.reload(sentry_config)
    with caplog.at_level(logging.INFO):
        assert sentry_config.init_sentry() is False


def test_init_returns_false_when_dsn_blank(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "   ")
    import sentry_config
    importlib.reload(sentry_config)
    assert sentry_config.init_sentry() is False


def test_init_returns_true_with_well_formed_dsn(monkeypatch):
    # Use a deterministic public-looking DSN. sentry_sdk validates the URL shape.
    monkeypatch.setenv(
        "SENTRY_DSN",
        "https://abc123def456@o4506999999.ingest.sentry.io/4507999999",
    )
    monkeypatch.setenv("SENTRY_ENV", "test")
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0.5")
    import sentry_config
    importlib.reload(sentry_config)
    assert sentry_config.init_sentry() is True

    # _filter_noise should drop HTTPException 4xx.
    from fastapi import HTTPException
    exc = HTTPException(status_code=404, detail="x")
    assert sentry_config._filter_noise({}, {"exc_info": (None, exc, None)}) is None

    # And keep HTTPException 5xx.
    exc500 = HTTPException(status_code=500, detail="boom")
    assert sentry_config._filter_noise({"k": "v"}, {"exc_info": (None, exc500, None)}) == {"k": "v"}
