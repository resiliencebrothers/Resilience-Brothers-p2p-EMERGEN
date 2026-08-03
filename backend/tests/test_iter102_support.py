"""iter102 — Support tickets + FAQ end-to-end.

Coverage:
 1. Client (normal) creates a ticket → shows up in `/support/tickets/me`
    and in `/admin/support/tickets` unread queue.
 2. Employee (no `support` perm) → 403 on `/admin/support/tickets`.
 3. Admin replies → status flips to `answered`, `unread_by_client=True`.
 4. Client marks-as-read → `unread_by_client=False`.
 5. Client replies to answered ticket → status back to `open`,
    `unread_by_staff=True`.
 6. Admin closes ticket → client cannot reply anymore (400).
 7. Rate-limit guard: 6 tickets in < 1 hour → the 6th returns 429.
 8. FAQ CRUD as admin: create, list, update, delete.
"""
import os
import pytest
import httpx

API_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
from conftest import NORMAL_TOKEN, VIP_TOKEN, EMPLOYEE_TOKEN, ADMIN_TOKEN


def h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _clean_tickets_and_faq(user_id: str) -> None:
    from db_client import db
    await db.support_tickets.delete_many({"user_id": user_id})
    # Only wipe test-created FAQ entries (keep seed intact)
    await db.faq_entries.delete_many({"question_es": {"$regex": r"^\[test\]"}})


class TestSupportFlow:
    @pytest.mark.asyncio
    async def test_full_ticket_lifecycle(self):
        await _clean_tickets_and_faq("user_test_normal01")
        async with httpx.AsyncClient(base_url=API_URL, timeout=15) as c:
            # 1. Client creates
            r = await c.post("/api/support/tickets", headers=h(NORMAL_TOKEN),
                             json={"category": "general",
                                   "subject": "Test ticket lifecycle",
                                   "message": "Necesito ayuda con mi cuenta."})
            assert r.status_code == 200, r.text
            ticket = r.json()
            assert ticket["status"] == "open"
            assert ticket["unread_by_staff"] is True
            assert ticket["unread_by_client"] is False
            tid = ticket["id"]

            # 2. Employee: `require_permission` grants access when
            # `allowed_permissions` is empty (legacy unrestricted employees).
            # For a scoped employee we'd expect 403 — that path is exercised
            # by `test_employee_scoped_denied` below via a per-request scope
            # patch. Here we just confirm the endpoint answers 200 to the
            # default full-access employee (matches every other admin route).
            r = await c.get("/api/admin/support/tickets", headers=h(EMPLOYEE_TOKEN))
            assert r.status_code == 200, r.text

            # 3. Admin lists → sees it as unread
            r = await c.get("/api/admin/support/tickets", headers=h(ADMIN_TOKEN))
            assert r.status_code == 200
            data = r.json()
            assert data["unread"] >= 1
            assert any(t["id"] == tid for t in data["items"])

            # 4. Admin replies
            r = await c.post(f"/api/admin/support/tickets/{tid}/reply",
                             headers=h(ADMIN_TOKEN),
                             json={"text": "Hola, cuéntanos más detalles."})
            assert r.status_code == 200
            t2 = r.json()
            assert t2["status"] == "answered"
            assert t2["unread_by_client"] is True
            assert t2["unread_by_staff"] is False
            assert len(t2["messages"]) == 2
            assert t2["messages"][-1]["author_role"] == "staff"

            # 5. Client marks as read
            r = await c.post(f"/api/support/tickets/{tid}/mark-read",
                             headers=h(NORMAL_TOKEN), json={})
            assert r.status_code == 200

            # 6. Client replies → flips back to open
            r = await c.post(f"/api/support/tickets/{tid}/reply",
                             headers=h(NORMAL_TOKEN),
                             json={"text": "Aquí van los detalles."})
            assert r.status_code == 200
            t3 = r.json()
            assert t3["status"] == "open"
            assert t3["unread_by_staff"] is True
            assert len(t3["messages"]) == 3

            # 7. Admin closes → client cannot reply
            r = await c.post(f"/api/admin/support/tickets/{tid}/close",
                             headers=h(ADMIN_TOKEN), json={})
            assert r.status_code == 200
            assert r.json()["status"] == "closed"

            r = await c.post(f"/api/support/tickets/{tid}/reply",
                             headers=h(NORMAL_TOKEN),
                             json={"text": "Otro intento"})
            assert r.status_code == 400, "closed ticket should not accept replies"

    @pytest.mark.asyncio
    async def test_rate_limit_normal_ticket_creation(self):
        # This test creates 6 tickets rapidly; the 6th must be rejected.
        # It uses the VIP account to keep the normal account clean for the
        # lifecycle test above.
        from db_client import db
        await db.support_tickets.delete_many({"user_id": "user_test_vip01"})
        async with httpx.AsyncClient(base_url=API_URL, timeout=15) as c:
            for i in range(5):
                r = await c.post("/api/support/tickets", headers=h(VIP_TOKEN),
                                 json={"category": "general",
                                       "subject": f"Rate limit probe {i}",
                                       "message": "Testing 1 2 3."})
                assert r.status_code == 200, f"ticket {i} failed: {r.text}"
            # 6th → 429
            r = await c.post("/api/support/tickets", headers=h(VIP_TOKEN),
                             json={"category": "general",
                                   "subject": "Should get 429",
                                   "message": "This one should be rejected."})
            assert r.status_code == 429, f"expected 429, got {r.status_code}"

    @pytest.mark.asyncio
    async def test_employee_cannot_create_ticket(self):
        # Employees route their questions through internal channels.
        async with httpx.AsyncClient(base_url=API_URL, timeout=15) as c:
            r = await c.post("/api/support/tickets", headers=h(EMPLOYEE_TOKEN),
                             json={"category": "general",
                                   "subject": "Blocked",
                                   "message": "Should not work."})
            assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_scoped_employee_without_support_perm_is_403(self):
        """When an employee has `allowed_permissions` set to a specific
        list that does NOT include 'support', `require_permission("support")`
        must return 403. Guards against a future regression where the
        support permission accidentally becomes universal."""
        from db_client import db
        # Snapshot then patch
        orig = await db.users.find_one({"user_id": "user_test_employee01"},
                                       {"_id": 0, "allowed_permissions": 1}) or {}
        try:
            await db.users.update_one(
                {"user_id": "user_test_employee01"},
                {"$set": {"allowed_permissions": ["orders"]}},  # scoped, no `support`
            )
            async with httpx.AsyncClient(base_url=API_URL, timeout=15) as c:
                r = await c.get("/api/admin/support/tickets", headers=h(EMPLOYEE_TOKEN))
                assert r.status_code == 403, f"expected 403, got {r.status_code}"
                detail = r.json().get("detail", "")
                assert "Soporte" in detail or "support" in detail.lower()
        finally:
            # Restore original perms (or clear if there were none).
            if orig.get("allowed_permissions") is not None:
                await db.users.update_one(
                    {"user_id": "user_test_employee01"},
                    {"$set": {"allowed_permissions": orig["allowed_permissions"]}},
                )
            else:
                await db.users.update_one(
                    {"user_id": "user_test_employee01"},
                    {"$unset": {"allowed_permissions": ""}},
                )


class TestFaqCrud:
    @pytest.mark.asyncio
    async def test_admin_faq_full_crud(self):
        await _clean_tickets_and_faq("user_test_normal01")
        async with httpx.AsyncClient(base_url=API_URL, timeout=15) as c:
            # 1. Public read as normal → seeded entries visible
            r = await c.get("/api/support/faq", headers=h(NORMAL_TOKEN))
            assert r.status_code == 200
            seeded_count = len(r.json())
            assert seeded_count >= 8, "expected the default FAQ seed to be present"

            # 2. Admin creates a new entry
            r = await c.post("/api/admin/support/faq", headers=h(ADMIN_TOKEN),
                             json={"category": "convert",
                                   "question_es": "[test] ¿Pregunta test?",
                                   "question_en": "[test] Question test?",
                                   "answer_es": "[test] Respuesta test.",
                                   "answer_en": "[test] Test answer.",
                                   "order": 999,
                                   "is_active": True})
            assert r.status_code == 200, r.text
            entry = r.json()
            entry_id = entry["id"]

            # 3. Normal user sees it now
            r = await c.get("/api/support/faq", headers=h(NORMAL_TOKEN))
            assert any(e["id"] == entry_id for e in r.json())

            # 4. Admin updates the entry (mark inactive)
            r = await c.put(f"/api/admin/support/faq/{entry_id}", headers=h(ADMIN_TOKEN),
                            json={"category": "convert",
                                  "question_es": "[test] ¿Pregunta editada?",
                                  "question_en": "[test] Edited question?",
                                  "answer_es": "[test] Respuesta editada.",
                                  "answer_en": "[test] Edited answer.",
                                  "order": 999,
                                  "is_active": False})
            assert r.status_code == 200
            assert r.json()["is_active"] is False

            # 5. Normal user should NOT see the inactive entry
            r = await c.get("/api/support/faq", headers=h(NORMAL_TOKEN))
            assert all(e["id"] != entry_id for e in r.json()), \
                "inactive FAQ leaked to normal user"

            # 6. Admin deletes
            r = await c.delete(f"/api/admin/support/faq/{entry_id}", headers=h(ADMIN_TOKEN))
            assert r.status_code == 200

            # 7. Deleting again → 404
            r = await c.delete(f"/api/admin/support/faq/{entry_id}", headers=h(ADMIN_TOKEN))
            assert r.status_code == 404
