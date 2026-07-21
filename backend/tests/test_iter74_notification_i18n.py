"""iter74 — Backend notification i18n unit tests.

Verifies that:
 1. `services.notification_i18n.t()` renders every catalogue key/field in both
    languages without KeyError / IndexError.
 2. `resolve_lang(db, user_id)` reads `preferred_language` and falls back to
    Spanish when absent.
 3. Push payload builders honour `lang=` and route English recipients to the
    English catalogue.
 4. `_rate_fanout_inapp` picks per-user language and generates title/message
    in that language.
 5. Order in-app notifications (`create_inapp_order_notification`) render in
    the target user's language.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.notification_i18n import (
    t, resolve_lang, get_field, CATALOG, DEFAULT_LANG,
)


# ============================================================
# 1) CATALOG — every key/field renders in both locales
# ============================================================

def test_catalog_has_es_and_en_for_every_key():
    for key, section in CATALOG.items():
        assert "es" in section, f"missing es for {key}"
        assert "en" in section, f"missing en for {key}"


def test_catalog_es_and_en_share_field_set():
    for key, section in CATALOG.items():
        es_fields = set(section["es"].keys())
        en_fields = set(section["en"].keys())
        assert es_fields == en_fields, (
            f"key={key} field mismatch: es={es_fields} en={en_fields}"
        )


def test_t_falls_back_to_default_for_unknown_lang():
    got = t("phone_verified", "de", "title")  # de not supported
    assert got == CATALOG["phone_verified"]["es"]["title"]


def test_t_returns_key_for_unknown_key():
    assert t("does_not_exist", "en", "title") == "does_not_exist"


def test_t_returns_key_for_missing_field_in_both_langs():
    assert t("phone_verified", "en", "nonexistent_field") == "phone_verified"


def test_t_renders_placeholders():
    got = t("new_user_pending", "en", "message",
            name="Alice", email="a@b.co", phone="+123")
    assert "Alice" in got and "a@b.co" in got and "+123" in got
    assert got.startswith("Alice (a@b.co)")


def test_t_es_and_en_differ_in_content():
    for key in ["phone_verified", "phone_rejected", "kyc_verified",
                "order_approved", "rate_change"]:
        section = CATALOG[key]
        assert section["es"]["title"] != section["en"]["title"], (
            f"{key} title identical in es/en — did you forget to translate?"
        )


# ============================================================
# 2) resolve_lang — user lookup + fallback
# ============================================================

@pytest.mark.asyncio
async def test_resolve_lang_returns_stored_preference():
    mock_db = MagicMock()
    mock_db.users.find_one = AsyncMock(return_value={"preferred_language": "en"})
    assert await resolve_lang(mock_db, "u1") == "en"


@pytest.mark.asyncio
async def test_resolve_lang_falls_back_when_user_missing():
    mock_db = MagicMock()
    mock_db.users.find_one = AsyncMock(return_value=None)
    assert await resolve_lang(mock_db, "unknown") == DEFAULT_LANG


@pytest.mark.asyncio
async def test_resolve_lang_falls_back_when_field_absent():
    mock_db = MagicMock()
    mock_db.users.find_one = AsyncMock(return_value={})
    assert await resolve_lang(mock_db, "u1") == DEFAULT_LANG


@pytest.mark.asyncio
async def test_resolve_lang_normalises_locale_variants():
    mock_db = MagicMock()
    mock_db.users.find_one = AsyncMock(return_value={"preferred_language": "en-US"})
    assert await resolve_lang(mock_db, "u1") == "en"


@pytest.mark.asyncio
async def test_resolve_lang_empty_user_id():
    mock_db = MagicMock()
    assert await resolve_lang(mock_db, "") == DEFAULT_LANG


# ============================================================
# 3) get_field — untemplated fragment access
# ============================================================

def test_get_field_returns_untemplated_value():
    assert get_field("rate_change", "en", "vip_suffix") == " (VIP rate)"
    assert get_field("rate_change", "es", "vip_suffix") == " (tarifa VIP)"


def test_get_field_falls_back_to_es_then_default():
    # Non-existent lang for existing field
    assert get_field("kyc_rejected", "fr", "reason_default") == "Documentación insuficiente"
    # Non-existent field
    assert get_field("kyc_rejected", "en", "nope", default="X") == "X"


# ============================================================
# 4) Push payload builders honour lang
# ============================================================

def test_build_order_approved_payload_english():
    from push_service import build_order_approved_payload
    order = {"id": "abcd1234efgh", "amount_to": 100, "to_code": "CUP"}
    p = build_order_approved_payload(order, lang="en")
    assert "approved" in p["title"].lower()
    assert "ready for delivery" in p["body"].lower()
    assert "abcd1234" in p["title"]


def test_build_order_approved_payload_spanish_default():
    from push_service import build_order_approved_payload
    order = {"id": "abcd1234efgh", "amount_to": 100, "to_code": "CUP"}
    p = build_order_approved_payload(order)  # no lang → es
    assert "aprobada" in p["title"].lower()
    assert "listos para entregar" in p["body"].lower()


def test_build_rate_changed_payload_en_vip():
    from push_service import build_rate_changed_payload
    p = build_rate_changed_payload(
        "USD", "CUP", rate_normal=380, rate_vip=395,
        for_role="vip", lang="en",
    )
    assert p["title"] == "New rate USD → CUP"
    assert "1 USD = 395 CUP (VIP)" in p["body"]
    assert "before trading" in p["body"].lower()


def test_build_rate_changed_payload_es_normal():
    from push_service import build_rate_changed_payload
    p = build_rate_changed_payload(
        "USD", "CUP", rate_normal=380, rate_vip=395,
        for_role="normal", lang="es",
    )
    assert p["title"] == "Nueva tasa USD → CUP"
    assert "1 USD = 380 CUP" in p["body"]
    assert "VIP" not in p["body"]


def test_build_phone_verified_payload_english():
    from push_service import build_phone_verified_payload
    p = build_phone_verified_payload({"user_id": "u1"}, lang="en")
    assert "active" in p["title"].lower()
    assert "verified" in p["body"].lower()


def test_build_new_pending_user_payload_english():
    from push_service import build_new_pending_user_payload
    p = build_new_pending_user_payload(
        {"user_id": "u1", "name": "Bob", "phone": "+1", "email": "b@x.com"},
        lang="en",
    )
    assert "awaiting verification" in p["title"].lower()


def test_build_order_completed_payload_english_all_methods():
    from push_service import build_order_completed_payload
    for method, kw in [
        ("accumulate", "credited"),
        ("crypto", "wallet"),
        ("cash", "cash payout"),
        ("transfer", "transferred"),
    ]:
        p = build_order_completed_payload(
            {"id": "abcd1234", "amount_to": 100, "to_code": "USDT",
             "delivery_method": method},
            lang="en",
        )
        assert kw in p["body"].lower(), f"method={method}: {p['body']}"


# ============================================================
# 5) rate fanout inapp — per-user language
# ============================================================

@pytest.mark.asyncio
async def test_rate_fanout_inapp_uses_recipient_lang():
    from routes.market import _rate_fanout_inapp
    inserts = []

    async def fake_insert(*, recipient_user_id, type, title, message, data):
        inserts.append({
            "user_id": recipient_user_id, "type": type,
            "title": title, "message": message,
        })
        return "id"

    with patch("routes.notifications._insert_notification", side_effect=fake_insert):
        clients = [
            {"user_id": "u_es", "role": "normal", "preferred_language": "es"},
            {"user_id": "u_en", "role": "normal", "preferred_language": "en"},
            {"user_id": "u_default", "role": "vip"},  # no preferred_language → es
        ]
        n = await _rate_fanout_inapp(clients, "USD", "CUP", 0, 0, 380, 395)
        assert n == 3

    by_user = {i["user_id"]: i for i in inserts}
    assert "Nueva tasa" in by_user["u_es"]["title"]
    assert by_user["u_es"]["message"].endswith(".")
    assert "New rate" in by_user["u_en"]["title"]
    assert "1 USD = 380" in by_user["u_en"]["message"]
    assert "(VIP rate)" not in by_user["u_en"]["message"]  # normal role
    # VIP default-lang user gets Spanish + VIP suffix
    assert "tarifa VIP" in by_user["u_default"]["message"]


# ============================================================
# 6) Order in-app notification — recipient language
# ============================================================

@pytest.mark.asyncio
async def test_create_inapp_order_notification_english():
    from services.orders_helpers import create_inapp_order_notification
    inserts = []

    async def fake_insert(*, recipient_user_id, type, title, message, data):
        inserts.append({"title": title, "message": message, "data": data})

    with patch("routes.notifications._insert_notification", side_effect=fake_insert), \
         patch("services.notification_i18n.resolve_lang", new=AsyncMock(return_value="en")):
        await create_inapp_order_notification(
            {"id": "abcd1234efgh", "user_id": "u_en",
             "amount_to": 3800, "to_code": "CUP", "delivery_method": "transfer"},
            "approved",
        )
    assert len(inserts) == 1
    got = inserts[0]
    assert "confirmed" in got["title"].lower()
    assert "received your payment" in got["message"].lower()
    assert "3800" in got["message"] and "CUP" in got["message"]


@pytest.mark.asyncio
async def test_create_inapp_order_notification_spanish_default():
    from services.orders_helpers import create_inapp_order_notification
    inserts = []

    async def fake_insert(*, recipient_user_id, type, title, message, data):
        inserts.append({"title": title, "message": message})

    with patch("routes.notifications._insert_notification", side_effect=fake_insert), \
         patch("services.notification_i18n.resolve_lang", new=AsyncMock(return_value="es")):
        await create_inapp_order_notification(
            {"id": "abcd1234efgh", "user_id": "u_es",
             "amount_to": 3800, "to_code": "CUP", "delivery_method": "cash"},
            "completed",
        )
    assert "completada" in inserts[0]["title"].lower()
    assert "efectivo" in inserts[0]["message"].lower()
