"""Storage abstraction — iter35.

Single interface for uploading and reading binary objects (proof-of-transfer
images, payout receipts, etc.). Backed by one of:

- `r2`    → Cloudflare R2 (S3-compatible, recommended)
- `s3`    → AWS S3
- `none`  → no-op (returns the input untouched; legacy base64 fallback)

Switch the backend in `.env`:

    STORAGE_PROVIDER=r2

Required env vars per provider:

  r2 / s3:
    R2_ACCESS_KEY_ID            (or S3_ACCESS_KEY_ID)
    R2_SECRET_ACCESS_KEY        (or S3_SECRET_ACCESS_KEY)
    R2_BUCKET                   (or S3_BUCKET)
    R2_ENDPOINT                 (R2 only — full URL with account-id)
    S3_REGION                   (S3 only — defaults to us-east-1)

Returns:
  - `put_object(key, data, content_type)` → str absolute key (the same `key`
    passed in). Caller stores this in MongoDB and serves it via the
    `GET /api/files/{key:path}` route.
  - `get_object_bytes(key)` → (bytes, content_type) or (None, None) when missing.
"""
import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_provider: str = "none"
_client = None
_bucket: str = ""


def init_storage() -> str:
    """Initialise the storage client once at app boot. Returns the active
    provider name (`r2` / `s3` / `none`)."""
    global _provider, _client, _bucket
    provider = (os.environ.get("STORAGE_PROVIDER") or "none").strip().lower()
    if provider not in ("r2", "s3", "none"):
        print(f"[storage] unknown STORAGE_PROVIDER={provider!r} — falling back to 'none'", flush=True)
        provider = "none"
    if provider == "none":
        _provider = "none"
        print("[storage] disabled (STORAGE_PROVIDER=none). Base64 fallback active.", flush=True)
        return "none"

    try:
        import boto3
        from botocore.config import Config

        if provider == "r2":
            endpoint = os.environ.get("R2_ENDPOINT", "").strip()
            access = os.environ.get("R2_ACCESS_KEY_ID", "").strip()
            secret = os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
            bucket = os.environ.get("R2_BUCKET", "").strip()
            if not (endpoint and access and secret and bucket):
                print("[storage] R2 credentials incomplete — disabling.", flush=True)
                _provider = "none"
                return "none"
            _client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=access,
                aws_secret_access_key=secret,
                region_name="auto",
                config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
            )
            _bucket = bucket
        else:  # s3
            access = os.environ.get("S3_ACCESS_KEY_ID", "").strip()
            secret = os.environ.get("S3_SECRET_ACCESS_KEY", "").strip()
            bucket = os.environ.get("S3_BUCKET", "").strip()
            region = os.environ.get("S3_REGION", "us-east-1").strip()
            if not (access and secret and bucket):
                print("[storage] S3 credentials incomplete — disabling.", flush=True)
                _provider = "none"
                return "none"
            _client = boto3.client(
                "s3",
                aws_access_key_id=access,
                aws_secret_access_key=secret,
                region_name=region,
                config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
            )
            _bucket = bucket

        # Quick HEAD on the bucket to fail fast if creds/bucket are wrong.
        _client.head_bucket(Bucket=_bucket)
        _provider = provider
        print(f"[storage] {provider.upper()} ready — bucket={_bucket}", flush=True)
        return provider
    except Exception as e:
        print(f"[storage] init failed for {provider}: {e} — falling back to 'none'", flush=True)
        _provider = "none"
        _client = None
        _bucket = ""
        return "none"


def is_enabled() -> bool:
    return _provider in ("r2", "s3") and _client is not None


def put_object(key: str, data: bytes, content_type: str = "application/octet-stream") -> Optional[str]:
    """Upload `data` to the configured bucket under `key`. Returns the key on
    success or None on failure. Callers SHOULD check the return value and fall
    back to base64 storage when None to avoid losing user uploads."""
    if not is_enabled():
        return None
    assert _client is not None  # narrowed by is_enabled()
    try:
        _client.put_object(
            Bucket=_bucket, Key=key, Body=data,
            ContentType=content_type,
            CacheControl="private, max-age=300",
        )
        return key
    except Exception as e:
        logger.error(f"[storage] put_object {key} failed: {e}")
        return None


def get_object_bytes(key: str) -> Tuple[Optional[bytes], Optional[str]]:
    """Read an object's body and content-type. Returns (None, None) on miss."""
    if not is_enabled():
        return None, None
    assert _client is not None  # narrowed by is_enabled()
    try:
        resp = _client.get_object(Bucket=_bucket, Key=key)
        return resp["Body"].read(), resp.get("ContentType", "application/octet-stream")
    except Exception as e:
        logger.warning(f"[storage] get_object {key} failed: {e}")
        return None, None


def delete_object(key: str) -> bool:
    if not is_enabled():
        return False
    assert _client is not None  # narrowed by is_enabled()
    try:
        _client.delete_object(Bucket=_bucket, Key=key)
        return True
    except Exception as e:
        logger.error(f"[storage] delete_object {key} failed: {e}")
        return False
