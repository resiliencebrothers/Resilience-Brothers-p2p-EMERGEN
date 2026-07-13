"""iter36 — 3 wiring changes: openapi under /api, 413 on oversize proof,
backfill script idempotency.

Items 1-10 of the iter36 review request live here. Item 11 (regression) is
exercised by running the named test files in CI.
"""
import base64
import os
import subprocess
import sys

import pytest
import requests

from conftest import ADMIN_TOKEN, NORMAL_TOKEN

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
)
PNG_1PX_DATA_URL = "data:image/png;base64," + base64.b64encode(PNG_1PX).decode("ascii")


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


# ---------- Items 1-4: openapi / docs / redoc routes ----------

class TestOpenAPIWiring:
    def test_openapi_json_reachable_publicly(self):
        """Item 1 — /api/openapi.json must be reachable through the public ingress."""
        r = requests.get(f"{BASE_URL}/api/openapi.json", timeout=10)
        assert r.status_code == 200, f"expected 200, got {r.status_code}"
        body = r.json()
        paths = body.get("paths", {})
        # iter52: added 2 balance-ledger endpoints → 87 paths.
        # iter55.36: platform continues to grow. Assert a minimum floor instead
        # of a hardcoded count so path additions don't break this wiring test.
        assert len(paths) >= 107, f"expected ≥ 107 paths, got {len(paths)}"
        assert "/api/files/{key}" in paths

    def test_swagger_docs_reachable_publicly(self):
        """Item 2 — /api/docs (Swagger UI) returns HTML."""
        r = requests.get(f"{BASE_URL}/api/docs", timeout=10)
        assert r.status_code == 200
        ct = r.headers.get("content-type", "")
        assert "text/html" in ct, f"expected html, got {ct}"
        # Swagger UI page references openapi.json
        assert "openapi" in r.text.lower() or "swagger" in r.text.lower()

    def test_redoc_reachable_publicly(self):
        """Item 3 — /api/redoc returns HTML."""
        r = requests.get(f"{BASE_URL}/api/redoc", timeout=10)
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")
        assert "redoc" in r.text.lower()

    def test_legacy_openapi_json_no_longer_served_by_backend(self):
        """Item 4 — legacy /openapi.json must NOT serve the JSON schema.

        On the public URL, /openapi.json is now handled by the frontend SPA
        (not 404, but it returns HTML — confirms the backend no longer
        publishes the schema there). On the internal port the backend
        returns 404 for /openapi.json.
        """
        # Internal backend port — clean 404
        r_internal = requests.get("http://localhost:8001/openapi.json", timeout=10)
        assert r_internal.status_code == 404, (
            f"backend must not serve /openapi.json, got {r_internal.status_code}"
        )
        # Public URL — either 404, or HTML SPA fallback (NOT the json schema)
        r_pub = requests.get(f"{BASE_URL}/openapi.json", timeout=10)
        ct = r_pub.headers.get("content-type", "")
        if r_pub.status_code == 200:
            assert "application/json" not in ct, (
                f"openapi schema leaking on legacy path; content-type={ct}"
            )
        else:
            assert r_pub.status_code in (404, 301, 302)


# ---------- Items 5-7: 413 on oversize / normal upload ----------

class TestProofSizeContract:
    def test_oversize_proof_returns_413_and_order_not_created(self):
        """Item 5 — POST /api/orders with >8 MB proof_image returns 413
        PROOF_TOO_LARGE and does NOT create the order."""
        from pymongo import MongoClient
        db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        sender = "Iter36 Big Proof Sender"
        before = db.orders.count_documents({"sender_name": sender})

        big_bytes = b"\x00" * (9 * 1024 * 1024)  # 9 MB
        big_url = "data:image/png;base64," + base64.b64encode(big_bytes).decode("ascii")
        payload = {
            "from_code": "USD", "to_code": "CUP", "amount_from": 1.0,
            "delivery_method": "transfer", "delivery_details": "x",
            "sender_name": sender, "proof_image": big_url,
        }
        r = requests.post(
            f"{BASE_URL}/api/orders", headers=_h(NORMAL_TOKEN), json=payload, timeout=60
        )
        assert r.status_code == 413, r.text
        detail = r.json().get("detail") or {}
        assert detail.get("code") == "PROOF_TOO_LARGE"
        assert detail.get("size_mb", 0) > 8
        assert detail.get("limit_mb") == 8
        # Verify the order was not persisted
        after = db.orders.count_documents({"sender_name": sender})
        assert after == before, (
            f"413 path leaked an order document: before={before} after={after}"
        )

    def test_small_proof_uploads_successfully(self):
        """Item 6 — A ~100 KB base64 proof_image is uploaded to /api/files/orders/..."""
        # ~100 KB of random-ish data, encoded as a fake-PNG header + payload
        small_bytes = PNG_1PX + b"\x00" * (100 * 1024)
        small_url = "data:image/png;base64," + base64.b64encode(small_bytes).decode("ascii")
        payload = {
            "from_code": "USD", "to_code": "CUP", "amount_from": 1.0,
            "delivery_method": "transfer", "delivery_details": "x",
            "sender_name": "Iter36 100kb",
            "proof_image": small_url,
        }
        r = requests.post(
            f"{BASE_URL}/api/orders", headers=_h(NORMAL_TOKEN), json=payload, timeout=30
        )
        assert r.status_code == 200, r.text
        proof = r.json().get("proof_image") or ""
        assert proof.startswith("/api/files/orders/"), f"got {proof[:80]!r}"
        assert proof.endswith(".png")

    def test_normal_small_base64_upload_round_trips(self):
        """Item 7 — Standard 68-byte PNG proof gets stored and is fetchable."""
        payload = {
            "from_code": "USD", "to_code": "CUP", "amount_from": 1.0,
            "delivery_method": "transfer", "delivery_details": "x",
            "sender_name": "Iter36 round-trip",
            "proof_image": PNG_1PX_DATA_URL,
        }
        r = requests.post(
            f"{BASE_URL}/api/orders", headers=_h(NORMAL_TOKEN), json=payload, timeout=20
        )
        assert r.status_code == 200, r.text
        proof = r.json()["proof_image"]
        assert proof.startswith("/api/files/orders/") and proof.endswith(".png")
        key = proof.split("/api/files/", 1)[1]
        rf = requests.get(
            f"{BASE_URL}/api/files/{key}", headers=_h(ADMIN_TOKEN), timeout=15
        )
        assert rf.status_code == 200
        assert rf.headers.get("content-type", "").startswith("image/png")
        assert rf.content == PNG_1PX


# ---------- Item 9: backfill script idempotency ----------

class TestBackfillScript:
    SCRIPT = "/app/backend/scripts/backfill_base64_to_r2.py"

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, self.SCRIPT, *args],
            capture_output=True, text=True, timeout=120,
            cwd="/app/backend",
        )

    def _output(self, r):
        # logging.basicConfig in the script defaults to stderr; the boot
        # message from storage_service goes to stdout. Concatenate so the
        # assertions can be agnostic to where each line ends up.
        return (r.stdout or "") + (r.stderr or "")

    def test_dry_run_completes_successfully(self):
        r = self._run("--dry-run")
        assert r.returncode == 0, f"stderr={r.stderr}\nstdout={r.stdout}"
        out = self._output(r)
        assert "==> Summary" in out
        assert "Migrated" in out

    def test_dry_run_is_idempotent(self):
        """Two consecutive dry-runs must report identical counts."""
        r1 = self._run("--dry-run")
        r2 = self._run("--dry-run")
        assert r1.returncode == 0 and r2.returncode == 0

        def _extract_summary(out):
            lines = [line.strip() for line in out.splitlines()
                     if line.strip().startswith(("Scanned:", "Migrated:",
                                                 "Skipped (oversize):",
                                                 "Skipped (invalid):",
                                                 "Errors:"))]
            return lines

        s1 = _extract_summary(self._output(r1))
        s2 = _extract_summary(self._output(r2))
        assert s1 and s1 == s2, f"\nrun1: {s1}\nrun2: {s2}"

    def test_post_migration_no_pending_orders(self):
        r = self._run("--dry-run")
        assert r.returncode == 0
        out = self._output(r)
        for line in out.splitlines():
            s = line.strip()
            if s.startswith("Migrated:"):
                after = s.split(":", 1)[1].strip().split()[0]
                assert after == "0", (
                    f"Expected 0 migratable docs (idempotency), got {after}\n"
                    f"Full output:\n{out}"
                )
                break
        else:
            pytest.fail(f"No 'Migrated:' line in summary:\n{out}")


# ---------- Item 10: spot-check a migrated /api/files/orders/* ----------

class TestMigratedOrderSpotCheck:
    def test_random_migrated_order_is_fetchable(self):
        """Item 10 — pick any order whose proof_image starts with
        /api/files/orders/ and verify GET returns 200 + image content-type."""
        from pymongo import MongoClient
        db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        doc = db.orders.find_one(
            {"proof_image": {"$regex": "^/api/files/orders/"}},
            {"_id": 0, "proof_image": 1, "id": 1},
        )
        if doc is None:
            pytest.skip("No migrated /api/files/orders/* documents in DB")

        key = doc["proof_image"].split("/api/files/", 1)[1]
        r = requests.get(
            f"{BASE_URL}/api/files/{key}", headers=_h(ADMIN_TOKEN), timeout=20
        )
        assert r.status_code == 200, (
            f"failed to fetch migrated order {doc['id']} proof at {key}: "
            f"{r.status_code} {r.text[:200]}"
        )
        ct = r.headers.get("content-type", "")
        assert ct.startswith("image/"), f"unexpected content-type: {ct}"
        assert len(r.content) > 0
