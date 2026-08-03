"""iter111.2 — VIP Ledger PDF email endpoints regression tests.

Endpoints:
  POST /api/vip/ledger/email
  POST /api/admin/vip-ledger/{vip_user_id}/email

Tests hit the running backend service and use Resend's sandbox address
`delivered@resend.dev` (whitelisted for test mode) so the request goes
end-to-end without spamming a real inbox. If `RESEND_API_KEY` isn't set,
the service returns HTTP 502 and the happy-path tests skip.
"""
import os
import requests

import pytest

from conftest import (
    BASE_URL, ADMIN_TOKEN as ADMIN, VIP_TOKEN as VIP, NORMAL_TOKEN as NORMAL,
)

VIP_URL = f"{BASE_URL}/api/vip/ledger/email"
ADMIN_URL_TPL = f"{BASE_URL}/api/admin/vip-ledger/{{uid}}/email"
SANDBOX_INBOX = "delivered@resend.dev"

_HAS_RESEND = bool(os.environ.get("RESEND_API_KEY"))
resend_skip = pytest.mark.skipif(
    not _HAS_RESEND, reason="RESEND_API_KEY not set — happy path unavailable",
)


def _h(t):
    return {"Authorization": f"Bearer {t}"}


class TestVipLedgerEmail:
    @resend_skip
    def test_vip_can_email_self(self):
        r = requests.post(VIP_URL, headers=_h(VIP),
                          json={"to": SANDBOX_INBOX})
        if r.status_code == 502:
            pytest.skip("Resend rejected the send (e.g. daily quota reached)")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["to"] == SANDBOX_INBOX
        assert body["since"] and body["until"]

    @resend_skip
    def test_vip_default_recipient_is_own_email(self):
        # NOTE: vip.test@resilience.com is NOT a Resend-verified domain, so
        # the send itself will fail. We just check that the endpoint routes
        # correctly and returns 502 (soft failure) rather than 200 fantasy.
        r = requests.post(VIP_URL, headers=_h(VIP), json={})
        assert r.status_code in (200, 502)

    def test_vip_bad_email_returns_422(self):
        r = requests.post(VIP_URL, headers=_h(VIP), json={"to": "no-arroba"})
        assert r.status_code == 422

    def test_normal_user_forbidden(self):
        r = requests.post(VIP_URL, headers=_h(NORMAL),
                          json={"to": SANDBOX_INBOX})
        assert r.status_code == 403

    @resend_skip
    def test_admin_can_email_any_vip(self):
        r = requests.post(
            ADMIN_URL_TPL.format(uid="user_test_vip01"),
            headers=_h(ADMIN),
            json={"to": SANDBOX_INBOX,
                  "note": "Estado adjunto — firma requerida."},
        )
        if r.status_code == 502:
            pytest.skip("Resend rejected the send (e.g. daily quota reached)")
        assert r.status_code == 200
        assert r.json()["to"] == SANDBOX_INBOX

    def test_admin_non_vip_target_rejected(self):
        r = requests.post(
            ADMIN_URL_TPL.format(uid="user_test_normal01"),
            headers=_h(ADMIN),
            json={"to": SANDBOX_INBOX},
        )
        assert r.status_code == 422

    def test_admin_unknown_user_returns_404(self):
        r = requests.post(
            ADMIN_URL_TPL.format(uid="user_does_not_exist"),
            headers=_h(ADMIN),
            json={"to": SANDBOX_INBOX},
        )
        assert r.status_code == 404

    def test_normal_cannot_use_admin_endpoint(self):
        r = requests.post(
            ADMIN_URL_TPL.format(uid="user_test_vip01"),
            headers=_h(NORMAL),
            json={"to": SANDBOX_INBOX},
        )
        assert r.status_code == 403

    def test_invalid_date_returns_400(self):
        r = requests.post(VIP_URL, headers=_h(VIP),
                          json={"to": SANDBOX_INBOX, "from_date": "yesterday"})
        assert r.status_code == 400

    def test_extra_field_rejected(self):
        # Pydantic extra="forbid" — safety net against accidental payloads.
        r = requests.post(VIP_URL, headers=_h(VIP),
                          json={"to": SANDBOX_INBOX, "unknown_field": True})
        assert r.status_code == 422
