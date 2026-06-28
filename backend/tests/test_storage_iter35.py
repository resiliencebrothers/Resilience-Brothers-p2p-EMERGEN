"""Tests for the proof-upload helper + storage abstraction (iter35)."""
import base64
import importlib

import pytest


# ---------- Fixtures ----------

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
)
PNG_1PX_DATA_URL = "data:image/png;base64," + base64.b64encode(PNG_1PX).decode("ascii")


@pytest.fixture(autouse=True)
def _reset_storage(monkeypatch):
    """Make sure each test starts with a fresh storage state."""
    for k in ("STORAGE_PROVIDER", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
              "R2_BUCKET", "R2_ENDPOINT"):
        monkeypatch.delenv(k, raising=False)
    yield


# ---------- storage_service ----------

def test_storage_default_disabled():
    from services import storage as storage_service
    importlib.reload(storage_service)
    storage_service.init_storage()
    assert not storage_service.is_enabled()
    assert storage_service.put_object("x", b"123", "image/png") is None
    body, ct = storage_service.get_object_bytes("x")
    assert body is None and ct is None


def test_storage_unknown_provider_disables(monkeypatch):
    monkeypatch.setenv("STORAGE_PROVIDER", "ftp")
    from services import storage as storage_service
    importlib.reload(storage_service)
    assert storage_service.init_storage() == "none"
    assert not storage_service.is_enabled()


def test_storage_r2_missing_creds_falls_back(monkeypatch):
    monkeypatch.setenv("STORAGE_PROVIDER", "r2")
    # Intentionally NO R2_* creds set.
    from services import storage as storage_service
    importlib.reload(storage_service)
    assert storage_service.init_storage() == "none"
    assert not storage_service.is_enabled()


# ---------- proof_upload helper ----------

def test_maybe_upload_proof_passes_through_empty():
    from services.proof_upload import maybe_upload_proof
    assert maybe_upload_proof("", "orders") == ""
    assert maybe_upload_proof(None, "orders") is None


def test_maybe_upload_proof_passes_through_existing_ref():
    from services.proof_upload import maybe_upload_proof
    assert maybe_upload_proof("/api/files/orders/abc.png", "orders") == "/api/files/orders/abc.png"
    assert maybe_upload_proof("https://cdn/abc.png", "orders") == "https://cdn/abc.png"


def test_maybe_upload_proof_keeps_base64_when_storage_off():
    """If storage is disabled, the helper must return the original value
    intact so the existing flow keeps working."""
    from services.proof_upload import maybe_upload_proof
    assert maybe_upload_proof(PNG_1PX_DATA_URL, "orders") == PNG_1PX_DATA_URL


def test_maybe_upload_proof_uploads_when_storage_on(monkeypatch):
    """Patch the storage_service.put_object so we don't hit a real bucket."""
    from services import storage as storage_service
    monkeypatch.setattr(storage_service, "is_enabled", lambda: True)
    captured = {}

    def fake_put(key, data, content_type):
        captured.update(key=key, data=data, content_type=content_type)
        return key

    monkeypatch.setattr(storage_service, "put_object", fake_put)
    from services import proof_upload
    importlib.reload(proof_upload)

    result = proof_upload.maybe_upload_proof(PNG_1PX_DATA_URL, "orders")
    assert result.startswith("/api/files/orders/")
    assert result.endswith(".png")
    assert captured["data"] == PNG_1PX
    assert captured["content_type"] == "image/png"


def test_maybe_upload_proof_raises_413_on_oversize(monkeypatch):
    """iter36 — oversize uploads must raise HTTPException(413), regardless of
    whether storage is enabled. We never want a 10 MB blob to land in MongoDB."""
    from fastapi import HTTPException
    from services import storage as storage_service
    monkeypatch.setattr(storage_service, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_service, "put_object",
                          lambda *a, **kw: pytest.fail("put_object should not be called"))
    from services import proof_upload
    importlib.reload(proof_upload)
    big_bytes = b"A" * (10 * 1024 * 1024)
    big_data_url = "data:image/png;base64," + base64.b64encode(big_bytes).decode("ascii")
    with pytest.raises(HTTPException) as exc:
        proof_upload.maybe_upload_proof(big_data_url, "orders")
    assert exc.value.status_code == 413
    assert exc.value.detail["code"] == "PROOF_TOO_LARGE"
    assert exc.value.detail["size_mb"] > 8


def test_maybe_upload_proof_413_fires_even_when_storage_off(monkeypatch):
    """Size cap protects MongoDB even in legacy / dev mode (storage disabled)."""
    from fastapi import HTTPException
    from services import storage as storage_service
    monkeypatch.setattr(storage_service, "is_enabled", lambda: False)
    from services import proof_upload
    importlib.reload(proof_upload)
    big_bytes = b"B" * (10 * 1024 * 1024)
    big_data_url = "data:image/png;base64," + base64.b64encode(big_bytes).decode("ascii")
    with pytest.raises(HTTPException) as exc:
        proof_upload.maybe_upload_proof(big_data_url, "orders")
    assert exc.value.status_code == 413
