"""iter67 — Cross-device language preference sync tests.

The UI language a user picks in the switcher is now persisted server-side
so it follows them across devices (mobile, desktop, incognito). These tests
guard the contract:
  * PATCH /profile/language with a valid lang → 200, stored on user doc.
  * `en-GB`, `es-CU`, other region variants normalize to base language.
  * Unsupported languages → 400.
  * GET /profile/me surfaces the current `preferred_language`.
  * /auth/me returns the preference too (so AuthContext.checkAuth can pick
    it up on first render without a second round trip).
"""
from __future__ import annotations

import os
import requests
from pymongo import MongoClient

from tests.conftest import BASE_URL, VIP_TOKEN, NORMAL_TOKEN

API = f"{BASE_URL}/api"


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _clear_pref(user_id: str) -> None:
    _db().users.update_one(
        {"user_id": user_id},
        {"$unset": {"preferred_language": ""}},
    )


def test_patch_language_stores_valid_english():
    _clear_pref("user_test_vip01")
    r = requests.patch(
        f"{API}/profile/language",
        headers=_hdr(VIP_TOKEN),
        json={"language": "en"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"ok": True, "preferred_language": "en"}
    doc = _db().users.find_one({"user_id": "user_test_vip01"}, {"_id": 0})
    assert doc["preferred_language"] == "en"


def test_patch_language_stores_valid_spanish():
    _clear_pref("user_test_vip01")
    r = requests.patch(
        f"{API}/profile/language",
        headers=_hdr(VIP_TOKEN),
        json={"language": "es"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["preferred_language"] == "es"


def test_patch_language_normalizes_region_variant():
    """en-GB, en-US, es-CU, etc. should all collapse to their base."""
    for variant, base in [("en-GB", "en"), ("en-US", "en"),
                          ("es-CU", "es"), ("ES-MX", "es"), ("EN", "en")]:
        r = requests.patch(
            f"{API}/profile/language",
            headers=_hdr(VIP_TOKEN),
            json={"language": variant},
        )
        assert r.status_code == 200, f"variant={variant} failed: {r.text}"
        assert r.json()["preferred_language"] == base, (
            f"variant={variant!r} was stored as {r.json()['preferred_language']!r}, "
            f"expected {base!r}."
        )


def test_patch_language_rejects_unsupported():
    for bad in ["fr", "de", "zh", "", "xx", "portuguese"]:
        r = requests.patch(
            f"{API}/profile/language",
            headers=_hdr(VIP_TOKEN),
            json={"language": bad},
        )
        # 400 for validation, or 422 for Pydantic's min_length=2 on empty string
        assert r.status_code in (400, 422), f"bad={bad!r} → {r.status_code} {r.text}"


def test_patch_language_requires_auth():
    r = requests.patch(f"{API}/profile/language", json={"language": "en"})
    assert r.status_code in (401, 403)


def test_profile_me_returns_preferred_language():
    _db().users.update_one(
        {"user_id": "user_test_normal01"},
        {"$set": {"preferred_language": "en"}},
    )
    r = requests.get(f"{API}/profile/me", headers=_hdr(NORMAL_TOKEN))
    assert r.status_code == 200
    assert r.json()["preferred_language"] == "en"
    _clear_pref("user_test_normal01")


def test_profile_me_empty_when_unset():
    _clear_pref("user_test_normal01")
    r = requests.get(f"{API}/profile/me", headers=_hdr(NORMAL_TOKEN))
    assert r.status_code == 200
    assert r.json()["preferred_language"] == ""


def test_auth_me_returns_preferred_language():
    """AuthContext.checkAuth reads /auth/me, so the preference must be
    surfaced there too (avoids a second round trip on every hard-refresh)."""
    _db().users.update_one(
        {"user_id": "user_test_vip01"},
        {"$set": {"preferred_language": "en"}},
    )
    r = requests.get(f"{API}/auth/me", headers=_hdr(VIP_TOKEN))
    assert r.status_code == 200
    assert r.json().get("preferred_language") == "en"
    _clear_pref("user_test_vip01")
